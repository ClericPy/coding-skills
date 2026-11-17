#!/usr/bin/env python
"""change-linter 与仓内自检的黑盒回归用例。

在临时 git 仓库里跑真实的 CLI，只断言外部可观察的行为（输出与退出码），
不依赖内部实现细节。

放在仓库根 `tests/` 而不是技能目录内 —— 技能目录会被 `npx skills add` 整包分发给用户。
只用标准库，直接运行即可：

    uv run --no-project tests/test_verify.py            # 默认：跳过慢测
    CS_SLOW=1 uv run --no-project tests/test_verify.py  # 全跑，含联网的集成用例

默认模式先看仓库状态：工作区干净且 HEAD 与上次通过时一致时，打印「无相关改动，跳过」
并 exit 0（`--force` 强制重跑）。慢测（真起外部工具 / 联网）默认跳过并显式计数。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar, cast
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "skills" / "change-linter" / "scripts" / "verify.py"
VALIDATE = REPO_ROOT / "scripts" / "validate.py"
GIT = shutil.which("git") or ""

CS_SLOW = os.environ.get("CS_SLOW") == "1"
SLOW_REASON = "慢测：真起外部工具或联网；用 CS_SLOW=1 全跑"
STATE_DIR = Path(tempfile.gettempdir()) / "coding-skills-test-state"
F = TypeVar("F", bound=Callable[..., object])


def slow_test(func: F) -> F:
    """标记默认不跑的慢测：真起外部工具或联网，`CS_SLOW=1` 才执行。"""
    wrapped = unittest.skipUnless(CS_SLOW, SLOW_REASON)(func)
    cast(Any, wrapped).__cs_slow__ = True
    return wrapped


def _git(*args: str) -> subprocess.CompletedProcess[str] | None:
    """在仓库根跑一条只读 git 命令；git 缺失时返回 None。"""
    if not GIT:
        return None
    return subprocess.run(  # noqa: S603
        [GIT, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _state_path() -> Path:
    """每个仓库一个状态文件；放系统临时目录，不污染工作区。"""
    digest = hashlib.sha256(str(REPO_ROOT).encode("utf-8")).hexdigest()[:16]
    return STATE_DIR / f"{digest}.json"


def record_passed_run(head: str) -> None:
    """记下这次通过时的 HEAD，供下次判断有无相关改动。"""
    payload = {
        "repo": str(REPO_ROOT),
        "head": head,
        "slow": CS_SLOW,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(
            json.dumps(payload) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError:
        pass  # 记不上只损失一次早退机会，不影响测试结论


def skip_if_nothing_changed() -> str | None:
    """工作区干净且 HEAD 与上次通过时一致时，返回要打印的跳过理由。"""
    status = _git("status", "--porcelain")
    head_proc = _git("rev-parse", "HEAD")
    if status is None or head_proc is None or head_proc.returncode != 0:
        return None
    if any(line.strip() for line in status.stdout.splitlines()):
        return None
    head = head_proc.stdout.strip()
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if state.get("head") != head:
        return None
    return (
        f"无相关改动，跳过（HEAD {head[:7]} 与上次通过时一致，"
        "skills/ scripts/ tests/ README.md 与根目录模板无 diff）。"
        "强制重跑加 --force，跑慢测用 CS_SLOW=1"
    )


def _iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def count_slow_tests(suite: unittest.TestSuite) -> int:
    """数出被 slow_test 标记的用例条数（与它们当前是否被跳过无关）。"""
    total = 0
    for test in _iter_tests(suite):
        method = getattr(type(test), test._testMethodName, None)
        if getattr(method, "__cs_slow__", False):
            total += 1
    return total


CLEAN_PY = "x = 1\n"
BAD_PY = "import os\n\n\nx = 1\n"
BAD_SYNTAX_PY = "def f(:\n    pass\n"

# Git for Windows 自带 bash 但默认不写进 PATH；verify.py 会回退探测这些位置
BASH_FALLBACK_PARTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ProgramFiles", ("Git", "bin", "bash.exe")),
    ("ProgramFiles", ("Git", "usr", "bin", "bash.exe")),
    ("ProgramFiles(x86)", ("Git", "bin", "bash.exe")),
    ("LOCALAPPDATA", ("Programs", "Git", "bin", "bash.exe")),
)


def bash_available() -> bool:
    """本机是否有可用的 bash（PATH 或 Git 安装目录）。"""
    if shutil.which("bash"):
        return True
    for env_name, parts in BASH_FALLBACK_PARTS:
        base = os.environ.get(env_name)
        if base and (Path(base) / Path(*parts)).is_file():
            return True
    return False


def branched_function(name: str, count: int) -> str:
    """生成一个分支数可控的函数，用于复杂度阈值用例。"""
    body = "".join(f"    if value == {i}:\n        return {i}\n" for i in range(count))
    return f"def {name}(value: int) -> int:\n{body}    return -1\n"


def load_verify_module():
    """按路径加载 verify.py 供进程内断言（黑盒用例仍走子进程）。

    必须先注册进 sys.modules：dataclass 装饰器会在装饰期回查 sys.modules[__module__]，
    未注册时报 'NoneType' object has no attribute '__dict__'。
    """
    spec = importlib.util.spec_from_file_location("change_linter_verify", VERIFY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {VERIFY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CliTestCase(unittest.TestCase):
    """提供临时目录、git 仓库与 CLI 调用的公共设施。"""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="coding-skills-test-"))
        # 传零参可调用对象：addCleanup 的 *args/**kwargs 转发会让类型检查器误判 rmtree 签名
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def run_cli(
        self, script: Path, cwd: Path, *args: str, path: str | None = None
    ) -> tuple[int, str]:
        """执行一个 CLI 脚本；path 非空时用它替换 PATH（用于模拟工具缺失）。"""
        env = {**os.environ, "PATH": path} if path is not None else None
        # 参数全部由本测试构造，且脚本路径为绝对路径，非外部输入
        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(script), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def commit_all(self, repo: Path) -> None:
        """把当前内容提交成基线，后续改动才会被 git diff 看见。"""
        subprocess.run(  # noqa: S603
            [GIT, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        subprocess.run(  # noqa: S603
            [GIT, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )

    def make_repo(self, files: dict[str, str], name: str = "repo") -> Path:
        """建一个 git 仓库，并按 {文件名: 内容} 写入文件。

        用 dict 而不是关键字参数：文件名带点（`app.py`），而关键字参数名不允许含点。
        """
        repo = self.tmp / name
        repo.mkdir(parents=True)
        subprocess.run(  # noqa: S603
            [GIT, "init", "-q"], cwd=str(repo), capture_output=True, check=True
        )
        for filename, content in files.items():
            # 显式 LF：Windows 上默认 write_text 会写 CRLF，ruff format 会因此要求重排，
            # 把「格式检查」变成干扰项
            (repo / filename).write_text(content, encoding="utf-8", newline="\n")
        return repo

    def empty_path_dir(self) -> str:
        """返回一个不含任何工具的空目录，用于模拟「工具全部缺失」。"""
        target = self.tmp / "empty-path"
        target.mkdir(exist_ok=True)
        return str(target)


@unittest.skipIf(not GIT, "需要 git 才能构造临时仓库")
class VerifyCliTest(CliTestCase):
    """verify.py 的行为回归。"""

    def test_probe_lists_tools_and_succeeds(self) -> None:
        code, out = self.run_cli(VERIFY, self.tmp, "--probe")
        self.assertEqual(code, 0)
        self.assertIn("工具清单", out)

    def test_non_git_directory_reports_unverified(self) -> None:
        plain = self.tmp / "plain"
        plain.mkdir()
        (plain / "app.py").write_text(CLEAN_PY, encoding="utf-8")
        code, out = self.run_cli(VERIFY, plain, "--level", "L1")
        self.assertEqual(code, 1)
        self.assertIn("未校验", out)

    def test_discovers_untracked_file(self) -> None:
        """未跟踪的新文件必须被发现：默认 git status 只输出目录名，会整体漏检。"""
        repo = self.make_repo({"app.py": BAD_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 1)
        self.assertIn("app.py", out)

    def test_clean_file_passes(self) -> None:
        repo = self.make_repo({"app.py": CLEAN_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 0)
        self.assertIn("全部通过", out)

    def test_files_without_python_or_shell_is_reported(self) -> None:
        repo = self.make_repo({"note.md": "# hi\n"})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--files", "note.md")
        self.assertEqual(code, 1)
        self.assertIn("不含 .py / .sh", out)

    def test_missing_ruff_is_hard_failure_with_py_compile_floor(self) -> None:
        repo = self.make_repo({"app.py": CLEAN_PY})
        code, out = self.run_cli(
            VERIFY,
            repo,
            "--level",
            "L1",
            "--files",
            "app.py",
            path=self.empty_path_dir(),
        )
        self.assertEqual(code, 1)
        self.assertIn("py_compile", out)
        self.assertIn("必需工具缺失", out)
        # 缺工具只提示不装：默认不联网，缺口按未校验标注
        self.assertIn("本次未安装（默认不联网）", out)
        self.assertIn("检查强度不足", out)
        self.assertIn("--install-missing", out)
        self.assertNotIn("安装缺失工具", out)

    def test_missing_ruff_still_catches_syntax_error(self) -> None:
        repo = self.make_repo({"bad.py": BAD_SYNTAX_PY})
        code, out = self.run_cli(
            VERIFY,
            repo,
            "--level",
            "L1",
            "--files",
            "bad.py",
            path=self.empty_path_dir(),
        )
        self.assertEqual(code, 1)
        self.assertIn("SyntaxError", out)

    def test_deleted_file_is_not_linted(self) -> None:
        """删除 .py 是合法改动：不存在的路径不得送检而误报失败。"""
        repo = self.make_repo({"gone.py": CLEAN_PY})
        subprocess.run(  # noqa: S603
            [GIT, "add", "-A"], cwd=str(repo), capture_output=True, check=True
        )
        subprocess.run(  # noqa: S603
            [GIT, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        (repo / "gone.py").unlink()
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 0, out)
        self.assertIn("无适用校验对象", out)

    def test_cjk_filename_is_discovered(self) -> None:
        """非 ASCII 文件名必须原样发现：git 默认把这类路径转义成八进制。"""
        repo = self.make_repo({"中文测试.py": CLEAN_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 0, out)
        self.assertIn("全部通过", out)

    @slow_test
    def test_project_scope_catches_downstream_breakage(self) -> None:
        """--project-scope 让类型工具扫整个项目：改签名破坏的下游调用方必须被扫出。

        默认只查改动文件——a.py 改了签名、clean 的 caller.py 不在检查范围，漏报；
        项目级扫描时 caller.py 的存量类型错误被暴露。

        慢测：两次 L3 要依次起 ruff + ty + pyrefly + pyright 并各扫一遍项目目录；
        pyright 的版本查询已在 verify.py 里关掉（`PYRIGHT_PYTHON_IGNORE_WARNINGS=1`），
        这条不再联网，只是仍比其余用例慢。
        """
        if not shutil.which("pyrefly"):
            self.skipTest("需要 pyrefly 才能覆盖项目级类型扫描")
        repo = self.make_repo(
            {
                "a.py": "def f(x: int) -> int:\n    return x\n",
                "caller.py": "from a import f\n\n\ny: int = f('oops')\n",
            }
        )
        subprocess.run(  # noqa: S603
            [GIT, "add", "-A"], cwd=str(repo), capture_output=True, check=True
        )
        subprocess.run(  # noqa: S603
            [GIT, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        (repo / "a.py").write_text(
            "def f(x: int) -> int:\n    return x\n# tweaked\n", encoding="utf-8"
        )
        _, default_out = self.run_cli(VERIFY, repo, "--level", "L3")
        self.assertNotIn("caller.py", default_out, "默认模式不应检查未改动的 caller.py")
        # 退出码不作判据：本机缺 ty 时 L3 恒退 1（降级），只看输出里是否扫出 caller.py
        scoped_code, scoped_out = self.run_cli(
            VERIFY, repo, "--level", "L3", "--project-scope"
        )
        self.assertIn("caller.py", scoped_out, "项目级扫描应扫出 caller.py 的类型错误")
        self.assertEqual(scoped_code, 1)

    def test_project_ruff_config_takes_precedence(self) -> None:
        """项目自带 ruff 配置时不传兜底参数：项目行宽 200 要盖过脚本默认的 120。"""
        repo = self.make_repo(
            {
                "app.py": 'message = "' + "a" * 140 + '"\n',
                "ruff.toml": "line-length = 200\n",
            }
        )
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 0, out)
        (repo / "ruff.toml").unlink()
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 1, "无项目配置时应回落兜底行宽 120 并报 E501")
        self.assertIn("E501", out)

    def test_per_file_ignores_apply_with_absolute_paths(self) -> None:
        """绝对路径 + cwd 不在配置根时，per-file-ignores 仍须生效。

        回归：ruff 按「文件相对工作目录的路径」匹配 per-file-ignores，工作目录错位
        会让 `app/**` 之类豁免静默失效，产生成片假阳性（实测 S101）。
        """
        if not shutil.which("ruff"):
            self.skipTest("本机未安装 ruff")
        repo = self.make_repo({})
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
            '[tool.ruff.lint]\nselect = ["E", "F", "S"]\n\n'
            '[tool.ruff.lint.per-file-ignores]\n"app/**" = ["S101"]\n',
            encoding="utf-8",
        )
        (repo / "app").mkdir()
        target = repo / "app" / "check.py"
        target.write_text(
            "def check(x):\n    assert x\n    return x\n", encoding="utf-8"
        )

        outside = self.tmp / "outside"
        outside.mkdir()
        code, out = self.run_cli(
            VERIFY, outside, "--level", "L1", "--files", str(target)
        )
        self.assertEqual(code, 0, out)
        self.assertNotIn("S101", out, out)

        code, out = self.run_cli(
            VERIFY, repo, "--level", "L1", "--files", "app/check.py"
        )
        self.assertEqual(code, 0, out)
        self.assertNotIn("S101", out, out)

    def test_shellcheck_runs_when_available(self) -> None:
        """有 .sh 改动且本机装了 shellcheck 时加跑静态检查：未引号变量要被抓到。

        shellcheck 是 bash -n 之外的可选增强，而 L1 的 .sh 分支仍以 bash 为准：
        verify.py 会先按 PATH、再按 Git 安装目录探测 bash，两者都找不到时整个
        Level 判为未校验、根本不进入 shellcheck，因此这里两个前置都在才跑。
        """
        if not shutil.which("shellcheck"):
            self.skipTest("本机未安装 shellcheck")
        if not bash_available():
            self.skipTest("本机没有可用 bash（PATH 与 Git 安装目录都没有）")
        repo = self.make_repo({"run.sh": "#!/usr/bin/env bash\nrm -rf $1\n"})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1")
        self.assertEqual(code, 1)
        self.assertIn("shellcheck", out)

    def test_missing_type_checker_never_reports_full_pass(self) -> None:
        """类型检查器缺失时降级，但绝不能报「全部通过」。"""
        if shutil.which("ty"):
            self.skipTest("本机装了 ty，无法覆盖降级分支")
        repo = self.make_repo({"app.py": CLEAN_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L2", "--files", "app.py")
        self.assertEqual(code, 1)
        self.assertIn("未真正执行", out)

    def test_excludes_own_installed_copy(self) -> None:
        """技能装进项目后，它自身的副本不该被当成用户的改动。"""
        repo = self.make_repo({"app.py": CLEAN_PY})
        skill_dir = repo / ".claude" / "skills" / "change-linter"
        (skill_dir / "scripts").mkdir(parents=True)
        installed = skill_dir / "scripts" / "verify.py"
        shutil.copy(VERIFY, installed)
        code, out = self.run_cli(installed, repo, "--level", "L1")
        self.assertIn("已排除本技能自身文件 1 个", out)
        self.assertEqual(code, 0)

    def test_complexity_new_code_over_limit_fails(self) -> None:
        """本次新增的函数按 8 卡：分支数 11 即超限。"""
        repo = self.make_repo({"app.py": branched_function("f", 10)})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--files", "app.py")
        self.assertEqual(code, 1, out)
        self.assertIn("新代码超限（>8）1 处", out)

    def test_complexity_legacy_within_tolerance_passes(self) -> None:
        """存量函数 8~12 放过：本次只碰了同文件里的另一个函数。"""
        repo = self.make_repo({"app.py": branched_function("f", 10)})
        self.commit_all(repo)
        with (repo / "app.py").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n\ndef touched(value: int) -> int:\n    return value\n")
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--files", "app.py")
        self.assertEqual(code, 0, out)
        self.assertIn("存量容忍（8~12）1 处", out)

    def test_complexity_legacy_over_limit_fails(self) -> None:
        """存量函数超过 12 仍要拦下。"""
        repo = self.make_repo({"app.py": branched_function("f", 13)})
        self.commit_all(repo)
        with (repo / "app.py").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n\ndef touched(value: int) -> int:\n    return value\n")
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--files", "app.py")
        self.assertEqual(code, 1, out)
        self.assertIn("存量超限（>12）1 处", out)

    def test_files_path_is_prechecked(self) -> None:
        """--files 按 cwd 解析：找不到时要说清并响亮失败，而不是让 ruff 报 E902。"""
        repo = self.make_repo({"app.py": CLEAN_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--files", "nope.py")
        self.assertEqual(code, 1, out)
        self.assertIn("--files 找不到文件: nope.py", out)
        self.assertIn("相对当前工作目录解析", out)

    def test_bash_fallback_probes_git_install_locations(self) -> None:
        """PATH 上没有 bash 时，按 Git for Windows 的常见位置回退探测。

        直接对 verify.py 的探测函数做进程内验证：Windows 会强制还原 ProgramFiles，
        子进程无法伪造该变量，所以这里改从可继承的 LOCALAPPDATA 切入。
        """
        if os.name != "nt":
            self.skipTest("回退候选是 Windows 的 Git 安装位置")
        verify = load_verify_module()
        fake_home = self.tmp / "fake-home"
        target = fake_home / "Programs" / "Git" / "bin" / "bash.exe"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"")
        # Windows 上 os.environ 的键是大写，过滤时不能按原样比对
        skip = {"PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"}
        patched = {
            key: value for key, value in os.environ.items() if key.upper() not in skip
        }
        patched["LOCALAPPDATA"] = str(fake_home)
        with mock.patch.dict(os.environ, patched, clear=True):
            self.assertEqual(verify._bash_fallback(), str(target))

    def test_probe_resolves_bash_without_path_entry(self) -> None:
        """本机有 Git bash 时，--probe 必须解析出路径，而不是报「未安装」。"""
        if not bash_available():
            self.skipTest("本机没有可说清的 bash（PATH 与 Git 安装目录都没有）")
        code, out = self.run_cli(VERIFY, self.tmp, "--probe")
        self.assertEqual(code, 0, out)
        bash_line = next(
            (line for line in out.splitlines() if line.strip().startswith("bash")),
            "",
        )
        self.assertNotIn("未安装", bash_line, out)


def make_outcome(tool: str, detail: str, passed: bool = False):
    """构造一条校验结果，供两个轴的进程内断言使用。"""
    verify = load_verify_module()
    check = verify.Check(tool=tool, label=tool, argv=(tool,))
    return verify.CheckOutcome(check=check, passed=passed, detail=detail)


@unittest.skipIf(not GIT, "需要 git 才能构造临时仓库")
class AxisCliTest(CliTestCase):
    """两个正交轴（--security / --deps）的接线与报告口径。"""

    def test_deps_without_source_is_reported_as_unverified(self) -> None:
        """找不到依赖来源时必须报「未校验」：裸跑 pip-audit 会给出假绿。"""
        repo = self.make_repo({"app.py": CLEAN_PY})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--deps")
        self.assertEqual(code, 1)
        self.assertIn("依赖轴未校验", out)

    def test_deps_only_change_does_not_claim_a_level_passed(self) -> None:
        """只改 lock 文件时没有 .py / .sh 可查，不能写成「L1 通过」。"""
        repo = self.make_repo({"uv.lock": "version = 1\n"})
        code, out = self.run_cli(VERIFY, repo, "--level", "L1", "--deps")
        self.assertEqual(code, 1)
        self.assertIn("仅执行 --deps 依赖审计", out)
        self.assertIn("后置校验 D", out)
        self.assertNotIn("后置校验 L1", out)

    @unittest.skipUnless(bash_available(), "需要 bash 才能让 .sh 改动进入校验")
    def test_security_axis_without_python_files_is_reported(self) -> None:
        """安全轴只扫 .py：没有 .py 改动时明确报未校验，而不是静默跳过。"""
        repo = self.make_repo({"run.sh": "echo hi\n"})
        _, out = self.run_cli(VERIFY, repo, "--level", "L1", "--security")
        self.assertIn("安全轴未校验", out)


@unittest.skipIf(not GIT, "需要 git 才能构造临时仓库")
class IntegrationSlowTest(CliTestCase):
    """默认不跑的集成用例：真起外部工具，且需要网络。

    按 AGENTS §3「真外部依赖只进默认不跑的集成测试」归到这里：默认模式跳过并显式计数，
    由 `CS_SLOW=1` 或 CI / 容器环境显式开启。
    """

    @slow_test
    def test_axis_label_lists_enabled_axes(self) -> None:
        """报告头带上轴标记，轴是否生效一目了然。

        需要网络：pip index —— pip-audit 要解析 requirements 并从 PyPI 查询漏洞数据，
        实测单次约 20 秒；索引不可达时会重试到 39 秒。
        """
        repo = self.make_repo(
            {"app.py": CLEAN_PY, "requirements.txt": "requests==2.19.0\n"}
        )
        _, out = self.run_cli(VERIFY, repo, "--level", "L1", "--security", "--deps")
        self.assertIn("后置校验 L1 + S + D", out)


class AxisFinalizeTest(unittest.TestCase):
    """两个轴的判定口径：都不看退出码，解析输出后自行裁决。"""

    def test_bandit_findings_fail_with_location(self) -> None:
        detail = json.dumps(
            {
                "results": [
                    {
                        "filename": "a.py",
                        "line_number": 3,
                        "test_id": "B324",
                        "issue_severity": "HIGH",
                        "issue_confidence": "HIGH",
                        "issue_text": "Use of weak MD5 hash",
                    }
                ]
            }
        )
        verify = load_verify_module()
        result = verify._finalize_security(make_outcome("bandit", detail))
        self.assertFalse(result.passed)
        self.assertIn("a.py:3", result.detail)
        self.assertIn("B324", result.detail)

    def test_bandit_clean_run_passes(self) -> None:
        verify = load_verify_module()
        result = verify._finalize_security(
            make_outcome("bandit", json.dumps({"results": []}), passed=True)
        )
        self.assertTrue(result.passed)

    def test_bandit_own_error_is_not_swallowed(self) -> None:
        """bandit 自身报错时原样保留，不得被改写成「通过」。"""
        verify = load_verify_module()
        raw = "bandit: error: unrecognized arguments: --nope"
        result = verify._finalize_security(make_outcome("bandit", raw))
        self.assertFalse(result.passed)
        self.assertIn("unrecognized arguments", result.detail)

    def test_json_extraction_tolerates_surrounding_logs(self) -> None:
        verify = load_verify_module()
        self.assertEqual(
            verify._extract_json('INFO start\n{"results": []}\ntrailing'),
            {"results": []},
        )
        self.assertIsNone(verify._extract_json("no json here"))

    def test_pip_audit_vulnerabilities_fail_and_ids_are_deduped(self) -> None:
        """pip-audit 会重复列出同一个漏洞 ID，原样打印会把一行撑成一屏。"""
        detail = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "requests",
                        "version": "2.19.0",
                        "vulns": [
                            {"id": "PYSEC-1"},
                            {"id": "PYSEC-1"},
                            {"id": "PYSEC-2"},
                        ],
                    }
                ]
            }
        )
        verify = load_verify_module()
        result = verify._finalize_deps(make_outcome("pip-audit", detail))
        self.assertFalse(result.passed)
        self.assertIn("PYSEC-1、PYSEC-2", result.detail)

    def test_pip_audit_clean_run_passes(self) -> None:
        detail = json.dumps(
            {"dependencies": [{"name": "requests", "version": "2.32.5", "vulns": []}]}
        )
        verify = load_verify_module()
        result = verify._finalize_deps(make_outcome("pip-audit", detail, passed=True))
        self.assertTrue(result.passed)
        self.assertIn("未发现已知漏洞", result.detail)

    def test_pip_audit_offline_is_a_gap_not_a_failure(self) -> None:
        """离线时审计根本没跑成：既不算通过，也不能写成「失败」。"""
        verify = load_verify_module()
        result = verify._finalize_deps(
            make_outcome("pip-audit", "ERROR: connection refused")
        )
        self.assertTrue(result.gap)
        self.assertFalse(result.passed)
        self.assertIn("未真正执行", result.detail)

    def test_pip_audit_broken_environment_points_at_reinstall(self) -> None:
        """环境被删文件要与网络问题分开：实测杀软会误删 cyclonedx/model/vulnerability.py。"""
        verify = load_verify_module()
        raw = (
            "Traceback (most recent call last):\n"
            '  File "cyclonedx/model/bom.py", line 55, in <module>\n'
            "    from .vulnerability import Vulnerability\n"
            "ModuleNotFoundError: No module named 'cyclonedx.model.vulnerability'"
        )
        result = verify._finalize_deps(make_outcome("pip-audit", raw))
        self.assertTrue(result.gap)
        self.assertIn("uv tool install pip-audit --upgrade", result.detail)
        self.assertNotIn("离线", result.detail)

    def test_pip_audit_unknown_failure_lists_causes_without_guessing(self) -> None:
        """认不出原因时只列可能项，不得硬猜成某一个。"""
        verify = load_verify_module()
        result = verify._finalize_deps(make_outcome("pip-audit", "ERROR: boom"))
        self.assertTrue(result.gap)
        self.assertIn("常见原因", result.detail)
        self.assertNotIn("杀软", result.detail)

    def test_ruff_fallback_select_covers_ai_prone_rules(self) -> None:
        """B/UP/DTZ 专拦模型从训练数据里带出的过时写法与时区裸 datetime。"""
        verify = load_verify_module()
        selected = set(verify.RUFF_SELECT.split(","))
        self.assertTrue({"B", "UP", "DTZ"} <= selected)


@unittest.skipIf(not GIT, "需要 git 才能构造临时仓库")
class ValidateCliTest(CliTestCase):
    """仓内自检脚本的回归。"""

    def copy_repo_inputs(self) -> Path:
        """复制自检所需的仓库输入到临时目录。"""
        root = self.tmp / "copy"
        root.mkdir()
        for name in ("skills", "scripts"):
            shutil.copytree(REPO_ROOT / name, root / name)
        shutil.copy(REPO_ROOT / "README.md", root / "README.md")
        shutil.copy(REPO_ROOT / "TEMPLATE-roles.md", root / "TEMPLATE-roles.md")
        return root

    def rewrite_skill(self, root: Path, name: str, old: str, new: str) -> Path:
        """改写临时仓库里某个技能的 SKILL.md，返回该文件路径。"""
        target = root / "skills" / name / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        self.assertIn(old, text)
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return target

    def test_repository_passes_strict(self) -> None:
        code, out = self.run_cli(VALIDATE, REPO_ROOT, "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("verify: 通过", out)

    def test_unrecognized_invocation_value_warns(self) -> None:
        """`disable-model-invocation: yes` 语义不确定，必须告警而不是静默当成「可自动」。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                "disable-model-invocation: true", "disable-model-invocation: yes"
            ),
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertIn("取值存疑(yes)", out)
        self.assertIn("语义不确定", out)
        strict_code, _ = self.run_cli(
            root / "scripts" / "validate.py", root, "--strict"
        )
        self.assertEqual(code, 0)
        self.assertEqual(strict_code, 1)

    def test_unknown_frontmatter_field_warns(self) -> None:
        """拼错的字段名会被静默忽略：`disable-model-invocationn` 会把仅手动技能变成「可自动」。"""
        root = self.copy_repo_inputs()
        self.rewrite_skill(
            root,
            "ccccc",
            "disable-model-invocation: true",
            "disable-model-invocationn: true",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 1, out)
        self.assertIn("disable-model-invocationn", out)
        self.assertIn("未识别", out)

    def test_block_scalar_description_is_error(self) -> None:
        """`description: >-` 会被单行解析器读成字面量 `>-`，长度校验随之失效，必须报错。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        rewritten = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                rewritten.extend(["description: >-", "  学习最近 5 次提交的格式"])
            else:
                rewritten.append(line)
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("块标量", out)

    def test_compatibility_over_limit_is_error(self) -> None:
        """`compatibility` 的 500 字符上限写在 CONTRIBUTING 里，超了必须报错。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        line = next(
            item
            for item in target.read_text(encoding="utf-8").splitlines()
            if item.startswith("compatibility:")
        )
        self.rewrite_skill(
            root, "change-linter", line, 'compatibility: "' + "x" * 501 + '"'
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("compatibility 长度 501 超过 500", out)

    def test_license_field_warns(self) -> None:
        """本仓库约定不写 license（根 LICENSE 兜底），出现即提醒，且不重复报成未知字段。"""
        root = self.copy_repo_inputs()
        self.rewrite_skill(root, "ccccc", "metadata:", "license: MIT\nmetadata:")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 0, out)
        self.assertIn("不要写 license 字段", out)
        self.assertNotIn("未识别", out)
        strict_code, strict_out = self.run_cli(
            root / "scripts" / "validate.py", root, "--strict"
        )
        self.assertEqual(strict_code, 1, strict_out)

    def test_compatibility_block_scalar_is_error(self) -> None:
        """`compatibility: >-` 与 description 一样会绕过 500 上限，必须报错。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        rewritten = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.startswith("compatibility:"):
                rewritten.extend(["compatibility: >-", "  " + "x" * 600])
            else:
                rewritten.append(line)
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("compatibility 疑似 YAML 块标量", out)

    def test_empty_invocation_value_warns(self) -> None:
        """`disable-model-invocation:` 空值会被静默当成「可自动」，必须告警并在清单里标出。"""
        root = self.copy_repo_inputs()
        self.rewrite_skill(
            root,
            "ccccc",
            "disable-model-invocation: true",
            "disable-model-invocation:",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 0, out)
        self.assertIn("是空值", out)
        self.assertIn("取值存疑(空值)", out)
        strict_code, strict_out = self.run_cli(
            root / "scripts" / "validate.py", root, "--strict"
        )
        self.assertEqual(strict_code, 1, strict_out)

    def test_markdown_link_dead_pointer_is_error(self) -> None:
        """`[x](references/missing.md)` 这类链接形态同样要查，不能只看反引号。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n见 [坏链接](references/missing.md)。\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 1, out)
        self.assertIn("references/missing.md", out)
        self.assertIn("不存在", out)

    def test_template_placeholder_pointers_are_ignored(self) -> None:
        """模板里的 `<name>` 占位符不是真引用：照模板新建技能后，自检不能因此判红。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n详细规则 → `references/<name>.md`\n辅助脚本 → `scripts/<name>.py`\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("不存在", out)

    def test_frontmatter_comment_line_is_ignored(self) -> None:
        """模板里 `# disable-model-invocation: true` 是注释，不能报成未知字段。"""
        root = self.copy_repo_inputs()
        self.rewrite_skill(
            root,
            "ccccc",
            "metadata:",
            "# 注释行：metadata 说明\nmetadata:",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("未识别", out)

    def test_trailing_comment_after_value_is_ignored(self) -> None:
        """行尾注释不能混进字段值：`version: "X.Y.Z"  # 递增` 仍应通过格式校验。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if item.startswith("  version:"))
        target.write_text(
            text.replace(line, line + "   # 随内容改动递增"), encoding="utf-8"
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("必须写成 X.Y.Z", out)

    def test_comment_only_metadata_value_keeps_subkey(self) -> None:
        """`metadata:   # 主数据` 仍是空值：下一层子键必须保留，不能误报缺 version。"""
        root = self.copy_repo_inputs()
        self.rewrite_skill(root, "ccccc", "\nmetadata:", "\nmetadata:   # 主数据")
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("缺少 metadata.version", out)

    def test_comment_only_description_is_reported_missing(self) -> None:
        """`description:   # TODO 待补` 等于没写描述，必须报缺失而不是放过。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        rewritten = [
            "description:   # TODO 待补" if line.startswith("description:") else line
            for line in target.read_text(encoding="utf-8").splitlines()
        ]
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("缺少非空 description", out)

    def test_quoted_value_with_gt_prefix_is_not_block_scalar(self) -> None:
        """单行引号串以 `>=` 开头是合法的，不能判成块标量反过来要求改写。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        line = next(
            item for item in text.splitlines() if item.startswith("compatibility:")
        )
        target.write_text(
            text.replace(line, 'compatibility: ">= Python 3.11; requires uv"'),
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("块标量", out)

    def test_pointer_anchor_is_normalized(self) -> None:
        """`references/x.md#L10` 的锚点不参与文件判定，两种写法都不许误报。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n分级见 [规则](references/lint-levels.md#L10) 与 `references/lint-levels.md#L10`。\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("不存在", out)

    def test_dot_slash_pointer_is_checked(self) -> None:
        """`./references/...` 是等价写法，死链同样要报。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n见 [死链](./references/missing.md)。\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("references/missing.md", out)
        self.assertIn("不存在", out)

    def test_dot_slash_existing_pointer_passes(self) -> None:
        """`./references/...` 指向真实文件时，不得误报。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n见 [规则](./references/lint-levels.md)。\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 0, out)
        self.assertNotIn("不存在", out)

    def test_dead_file_pointer_is_error(self) -> None:
        """SKILL.md 引用了不存在的 references/ 文件时必须报错，不能让 --strict 全绿。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        target.write_text(
            target.read_text(encoding="utf-8")
            + "\n详细规则见 `references/missing.md`。\n",
            encoding="utf-8",
        )
        code, out = self.run_cli(root / "scripts" / "validate.py", root, "--strict")
        self.assertEqual(code, 1, out)
        self.assertIn("references/missing.md", out)
        self.assertIn("不存在", out)

    def test_bad_version_format_is_error(self) -> None:
        """`metadata.version` 必须是 X.Y.Z；不绑定具体版本号，只改格式。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if item.startswith("  version:"))
        target.write_text(text.replace(line, '  version: "1.0"'), encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("metadata.version", out)

    def test_missing_version_warns(self) -> None:
        """缺失只告警：非 strict 退 0；--strict 下 warning 仍按失败处理。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        line = next(item for item in text.splitlines() if item.startswith("  version:"))
        target.write_text(text.replace(f"metadata:\n{line}\n", ""), encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 0, out)
        self.assertIn("缺少 metadata.version", out)
        strict_code, strict_out = self.run_cli(
            root / "scripts" / "validate.py", root, "--strict"
        )
        self.assertEqual(strict_code, 1, strict_out)

    def test_duplicate_description_quoted_then_block_scalar_is_error(self) -> None:
        """重复 description：先合法引号串、后裸块标量，不能被前一处标记放过。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        rewritten = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                rewritten.extend(
                    [
                        'description: "第一行正常描述"',
                        "description: >-",
                        "  第二行块标量",
                    ]
                )
            else:
                rewritten.append(line)
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("块标量", out)

    def test_duplicate_description_block_scalar_then_quoted_is_error(self) -> None:
        """反向顺序同样要报：任一处是裸块标量即记录，后一处合法也救不回来。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "ccccc" / "SKILL.md"
        rewritten = []
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.startswith("description:"):
                rewritten.extend(
                    [
                        "description: >-",
                        "  第一行块标量",
                        'description: "第二行正常描述"',
                    ]
                )
            else:
                rewritten.append(line)
        target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("块标量", out)

    def test_block_scalar_on_non_text_fields_has_no_length_hint(self) -> None:
        """metadata / allowed-tools 的裸块标量要报，但不能建议「加引号」或提长度上限。"""
        root = self.copy_repo_inputs()
        target = root / "skills" / "change-linter" / "SKILL.md"
        text = target.read_text(encoding="utf-8")
        text = text.replace("metadata:", "metadata: >-", 1)
        text = text.replace("allowed-tools:", "allowed-tools: >-", 1)
        target.write_text(text, encoding="utf-8")
        code, out = self.run_cli(root / "scripts" / "validate.py", root)
        self.assertEqual(code, 1, out)
        self.assertIn("metadata 疑似 YAML 块标量", out)
        self.assertIn("allowed-tools 疑似 YAML 块标量", out)
        self.assertNotIn("绕过长度校验", out)
        self.assertIn("按映射或清单写成单行", out)


def main(argv: list[str] | None = None) -> int:
    """运行全部用例：无相关改动早退，慢测默认跳过并显式计数。"""
    args = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in args
    unknown = [arg for arg in args if arg != "--force"]
    if unknown:
        print(f"忽略未知参数: {' '.join(unknown)}（只支持 --force）", flush=True)
    if not force and not CS_SLOW:
        reason = skip_if_nothing_changed()
        if reason is not None:
            print(reason, flush=True)
            return 0
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    slow = count_slow_tests(suite)
    skipped_slow = 0 if CS_SLOW else slow
    if skipped_slow:
        print(f"已跳过 {skipped_slow} 条慢测，用 CS_SLOW=1 全跑", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(
        f"跳过 {len(result.skipped)} 条"
        f"（慢测 {skipped_slow} 条，环境跳过 {len(result.skipped) - skipped_slow} 条）",
        flush=True,
    )
    if not result.wasSuccessful():
        return 1
    head_proc = _git("rev-parse", "HEAD")
    if head_proc is not None and head_proc.returncode == 0:
        record_passed_run(head_proc.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
