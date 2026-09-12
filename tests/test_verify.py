#!/usr/bin/env python
"""change-linter 与仓内自检的黑盒回归用例。

在临时 git 仓库里跑真实的 CLI，只断言外部可观察的行为（输出与退出码），
不依赖内部实现细节。

放在仓库根 `tests/` 而不是技能目录内 —— 技能目录会被 `npx skills add` 整包分发给用户。
只用标准库，直接运行即可：
    uv run --no-project tests/test_verify.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "skills" / "change-linter" / "scripts" / "verify.py"
VALIDATE = REPO_ROOT / "scripts" / "validate.py"
GIT = shutil.which("git") or ""

CLEAN_PY = "x = 1\n"
BAD_PY = "import os\n\n\nx = 1\n"
BAD_SYNTAX_PY = "def f(:\n    pass\n"


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
            (repo / filename).write_text(content, encoding="utf-8")
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
        skill_dir = repo / ".zcode" / "skills" / "change-linter"
        (skill_dir / "scripts").mkdir(parents=True)
        installed = skill_dir / "scripts" / "verify.py"
        shutil.copy(VERIFY, installed)
        code, out = self.run_cli(installed, repo, "--level", "L1")
        self.assertIn("已排除本技能自身文件 1 个", out)
        self.assertEqual(code, 0)


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
