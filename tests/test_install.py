#!/usr/bin/env python
"""技能安装的黑盒回归用例。

在临时项目里真跑 `npx skills add`，断言安装落点、产物完整性、幂等性与调用方式是否被保留。
需要 npx 与网络：任一不可用时整个类自动跳过（离线开发不受影响）。

放在仓库根 `tests/` 而不是技能目录内 —— 技能目录会被 `npx skills add` 整包分发。
运行：uv run --no-project tests/test_install.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
NPX = shutil.which("npx") or ""
GIT = shutil.which("git") or ""

ALL_SKILLS = (
    "ccccc",
    "change-linter",
    "code-review-expert",
    "ppppp",
    "ttttt",
    "wwwww",
    "yyyyy",
)

CLI_TIMEOUT_SECONDS = 240


def _skills_cli_available() -> bool:
    """探测 skills CLI 是否可用；无 npx 或离线时返回 False。"""
    if not NPX:
        return False
    try:
        proc = subprocess.run(  # noqa: S603
            [NPX, "-y", "skills", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


@unittest.skipIf(not GIT, "需要 git 才能构造临时项目")
class InstallCliTest(unittest.TestCase):
    """`npx skills add` 的安装行为回归。"""

    @classmethod
    def setUpClass(cls) -> None:
        if not _skills_cli_available():
            raise unittest.SkipTest("skills CLI 不可用（缺 npx 或离线），跳过安装测试")

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="coding-skills-install-"))
        # 传零参可调用对象：addCleanup 的 *args/**kwargs 转发会让类型检查器误判 rmtree 签名
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def new_project(self, name: str = "proj") -> Path:
        """建一个临时 git 项目。"""
        project = self.tmp / name
        project.mkdir()
        subprocess.run(  # noqa: S603
            [GIT, "init", "-q"], cwd=str(project), capture_output=True, check=True
        )
        return project

    def skills_cli(self, cwd: Path, *args: str) -> tuple[int, str]:
        """调用 skills CLI；参数由本测试构造，npx 为解析后的绝对路径。"""
        proc = subprocess.run(  # noqa: S603
            [NPX, "-y", "skills", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def add(self, cwd: Path, *args: str) -> tuple[int, str]:
        """从本仓库安装技能。"""
        return self.skills_cli(cwd, "add", str(REPO_ROOT), *args, "-y")

    def test_list_reports_all_skills(self) -> None:
        code, out = self.skills_cli(self.tmp, "add", str(REPO_ROOT), "--list")
        self.assertEqual(code, 0, out)
        for name in ALL_SKILLS:
            self.assertIn(name, out, f"--list 未列出 {name}")

    def test_single_agent_install_copies_all_skills(self) -> None:
        project = self.new_project()
        code, out = self.add(project, "-a", "zcode")
        self.assertEqual(code, 0, out)
        installed = project / ".zcode" / "skills"
        self.assertEqual(
            sorted(p.name for p in installed.iterdir()), sorted(ALL_SKILLS)
        )
        for name in ALL_SKILLS:
            skill_file = installed / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"{name}/SKILL.md 缺失")
            self.assertFalse(
                skill_file.is_symlink(), f"{name} 应为真实拷贝而非符号链接"
            )
        self.assertTrue(
            (project / "skills-lock.json").is_file(), "缺少 skills-lock.json"
        )

    def test_installed_files_match_source_byte_for_byte(self) -> None:
        """安装不得改写任何文件（含 frontmatter）。"""
        project = self.new_project()
        code, out = self.add(project, "-a", "zcode")
        self.assertEqual(code, 0, out)
        for name in ALL_SKILLS:
            with self.subTest(skill=name):
                self.assert_same_tree(
                    SKILLS_DIR / name, project / ".zcode" / "skills" / name
                )

    def test_invocation_mode_survives_install(self) -> None:
        """装完后 6 个仅手动、1 个可自动的划分必须原样保留。"""
        project = self.new_project()
        code, out = self.add(project, "-a", "zcode")
        self.assertEqual(code, 0, out)
        installed = project / ".zcode" / "skills"
        manual = (installed / "ccccc" / "SKILL.md").read_text(encoding="utf-8")
        automatic = (installed / "change-linter" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("disable-model-invocation: true", manual)
        self.assertNotIn("disable-model-invocation", automatic)

    def test_reinstall_is_idempotent(self) -> None:
        project = self.new_project()
        self.assertEqual(self.add(project, "-a", "zcode")[0], 0)
        code, out = self.add(project, "-a", "zcode")
        self.assertEqual(code, 0, out)
        installed = project / ".zcode" / "skills"
        self.assertEqual(
            sorted(p.name for p in installed.iterdir()), sorted(ALL_SKILLS)
        )

    def test_single_skill_install(self) -> None:
        project = self.new_project()
        code, out = self.add(project, "--skill", "ccccc", "-a", "zcode")
        self.assertEqual(code, 0, out)
        installed = project / ".zcode" / "skills"
        self.assertEqual([p.name for p in installed.iterdir()], ["ccccc"])

    def assert_same_tree(self, source: Path, installed: Path) -> None:
        """逐文件字节级比对两个目录。"""
        source_files = sorted(
            p.relative_to(source) for p in source.rglob("*") if p.is_file()
        )
        installed_files = sorted(
            p.relative_to(installed) for p in installed.rglob("*") if p.is_file()
        )
        self.assertEqual(source_files, installed_files)
        for relative in source_files:
            self.assertEqual(
                (source / relative).read_bytes(),
                (installed / relative).read_bytes(),
                f"{relative} 内容与源不一致",
            )


def main() -> int:
    """运行全部用例。"""
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
