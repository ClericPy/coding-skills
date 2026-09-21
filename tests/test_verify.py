#!/usr/bin/env python
"""change-linter 与仓内自检的黑盒回归用例。

在临时 git 仓库里跑真实的 CLI，只断言外部可观察的行为（输出与退出码），
不依赖内部实现细节。

放在仓库根 `tests/` 而不是技能目录内 —— 技能目录会被 `npx skills add` 整包分发给用户。
只用标准库，直接运行即可：
    uv run --no-project tests/test_verify.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "skills" / "change-linter" / "scripts" / "verify.py"
VALIDATE = REPO_ROOT / "scripts" / "validate.py"
GIT = shutil.which("git") or ""

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

    def test_project_scope_catches_downstream_breakage(self) -> None:
        """--project-scope 让类型工具扫整个项目：改签名破坏的下游调用方必须被扫出。

        默认只查改动文件——a.py 改了签名、clean 的 caller.py 不在检查范围，漏报；
        项目级扫描时 caller.py 的存量类型错误被暴露。
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
        return root

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


def main() -> int:
    """运行全部用例。"""
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
