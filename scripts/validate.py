#!/usr/bin/env python
"""coding-skills 仓库自检。

先打印技能清单（技能 → frontmatter name → 调用方式），再检查仓库结构、
frontmatter 规范与 README 索引一致性。

检查仅覆盖“机械事实”，不强制调用方式 —— 手动与自动都是合法选择。

退出码：
    0  没有 error（--strict 下也没有 warning）
    1  存在 error，或 --strict 下存在 warning
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"
README_NAME = "README.md"

MANUAL_FIELD = "disable-model-invocation"

# 该字段只认 true / false：其他拼写（yes / on / 1）在不同 harness 上解析结果可能不一致
INVOCATION_VALUES: frozenset[str] = frozenset({"true", "false"})

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
BODY_MAX_LINES = 500
INDEX_PATTERN = re.compile(r"\./skills/([^/)\s]+)/SKILL\.md")

ERROR = "error"
WARNING = "warning"

MANUAL_LABEL = "仅手动"
AUTO_LABEL = "可自动"


@dataclass(frozen=True)
class Skill:
    """一个技能的解析结果。"""

    directory: str
    path: Path
    name: str | None
    description: str | None
    manual_only: bool
    manual_value: str | None
    body_lines: int


@dataclass(frozen=True)
class Problem:
    """一条检查结果。"""

    severity: str
    message: str


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """解析文件首个 `---` 块，止于下一个 `---`。

    只取顶格的 `key: value`：正文里的 `---` 分隔线不会影响结果，
    缩进的子键（如 metadata 的内容）会被跳过。未闭合时返回 None。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line or line[0].isspace():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
            cleaned = cleaned[1:-1]
        fields[key.strip()] = cleaned
    return None


def body_line_count(text: str) -> int:
    """返回 frontmatter 之后正文的行数；没有 frontmatter 时返回全文行数。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return len(lines)
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return len(lines) - index - 1
    return len(lines)


def load_skill(path: Path) -> Skill:
    """读取一个 SKILL.md 并解析出基本信息。"""
    text = path.read_text(encoding="utf-8-sig")
    fields = parse_frontmatter(text) or {}
    manual_value = fields.get(MANUAL_FIELD) or None
    return Skill(
        directory=path.parent.name,
        path=path,
        name=fields.get("name") or None,
        description=fields.get("description") or None,
        manual_only=manual_value is not None and manual_value.lower() == "true",
        manual_value=manual_value,
        body_lines=body_line_count(text),
    )


def collect_skills(skills_root: Path) -> tuple[list[Skill], list[Problem]]:
    """收集 skills/ 下的技能，同时报告结构性错误。"""
    problems: list[Problem] = []
    skills: list[Skill] = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith((".", "_")):
            problems.append(
                Problem(
                    ERROR,
                    f"{SKILLS_DIRNAME}/{entry.name}/: 目录名不得以 . 或 _ 开头（会被 CLI 当作技能扫描）",
                )
            )
            continue
        skill_file = entry / SKILL_FILENAME
        if not skill_file.is_file():
            problems.append(
                Problem(ERROR, f"{SKILLS_DIRNAME}/{entry.name}/: 缺少 {SKILL_FILENAME}")
            )
            continue
        skills.append(load_skill(skill_file))
    return skills, problems


def check_layout(repo_root: Path, skills_root: Path) -> list[Problem]:
    """检查根目录遮蔽与嵌套层级。"""
    problems: list[Problem] = []
    if (repo_root / SKILL_FILENAME).is_file():
        problems.append(
            Problem(ERROR, f"根目录存在 {SKILL_FILENAME}：会遮蔽全部子技能，必须删除")
        )
    for found in sorted(skills_root.rglob(SKILL_FILENAME)):
        relative = found.relative_to(skills_root)
        if len(relative.parts) - 1 > 1:
            problems.append(
                Problem(
                    ERROR,
                    f"{found.relative_to(repo_root).as_posix()}: 技能必须平铺在 {SKILLS_DIRNAME}/<name>/ 下",
                )
            )
    return problems


def check_skill(skill: Skill) -> list[Problem]:
    """检查单个技能的 frontmatter 规范。"""
    problems: list[Problem] = []
    label = f"{SKILLS_DIRNAME}/{skill.directory}/{SKILL_FILENAME}"
    if skill.name is None:
        problems.append(Problem(ERROR, f"{label}: frontmatter 缺少 name"))
    else:
        if skill.name != skill.directory:
            problems.append(
                Problem(ERROR, f"{label}: name（{skill.name}）必须与目录名一致")
            )
        if not NAME_PATTERN.match(skill.name) or len(skill.name) > NAME_MAX_LENGTH:
            problems.append(
                Problem(
                    ERROR,
                    f"{label}: name 必须是 kebab-case 且不超过 {NAME_MAX_LENGTH} 字符",
                )
            )

    if not skill.description:
        problems.append(Problem(ERROR, f"{label}: frontmatter 缺少非空 description"))
    elif len(skill.description) > DESCRIPTION_MAX_LENGTH:
        problems.append(
            Problem(
                ERROR,
                f"{label}: description 长度 {len(skill.description)} 超过 {DESCRIPTION_MAX_LENGTH} 字符",
            )
        )

    if (
        skill.manual_value is not None
        and skill.manual_value.lower() not in INVOCATION_VALUES
    ):
        problems.append(
            Problem(
                WARNING,
                f"{label}: {MANUAL_FIELD} 取值 {skill.manual_value!r} 语义不确定，请写成 true 或 false"
                "（yes / on / 1 等写法在不同 harness 上可能被解析成相反的结果）",
            )
        )

    if skill.body_lines > BODY_MAX_LINES:
        problems.append(
            Problem(
                WARNING,
                f"{label}: 正文 {skill.body_lines} 行超过 {BODY_MAX_LINES} 行，考虑拆到 references/",
            )
        )
    return problems


def check_readme_index(repo_root: Path, skills: list[Skill]) -> list[Problem]:
    """双向核对 README 索引与磁盘技能。"""
    readme = repo_root / README_NAME
    if not readme.is_file():
        return [Problem(ERROR, f"缺少 {README_NAME}，无法核对技能索引")]
    listed = INDEX_PATTERN.findall(readme.read_text(encoding="utf-8-sig"))
    on_disk = {skill.directory for skill in skills}

    problems: list[Problem] = [
        Problem(ERROR, f"{README_NAME}: 索引了不存在的技能 {name}")
        for name in sorted(set(listed) - on_disk)
    ]
    problems.extend(
        Problem(
            ERROR,
            f"{README_NAME}: 缺少技能索引条目 ./{SKILLS_DIRNAME}/{name}/{SKILL_FILENAME}",
        )
        for name in sorted(on_disk - set(listed))
    )
    problems.extend(
        Problem(WARNING, f"{README_NAME}: 技能 {name} 被索引 {count} 次")
        for name, count in sorted(Counter(listed).items())
        if count > 1
    )
    return problems


def print_inventory(skills: list[Skill]) -> None:
    """打印技能清单；取值无法识别时显式标出，不冒充「可自动」。"""
    print(f"技能清单（{len(skills)}）:")
    for skill in skills:
        if (
            skill.manual_value is not None
            and skill.manual_value.lower() not in INVOCATION_VALUES
        ):
            mode = f"取值存疑({skill.manual_value})"
        else:
            mode = MANUAL_LABEL if skill.manual_only else AUTO_LABEL
        print(f"  {skill.directory:<20} name={skill.name or '(缺失)':<20} {mode}")
    print()


def print_problems(problems: list[Problem]) -> None:
    """打印检查结果。"""
    for problem in problems:
        prefix = "ERROR" if problem.severity == ERROR else "WARN "
        print(f"{prefix} {problem.message}")
    if problems:
        print()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="coding-skills 仓库自检")
    parser.add_argument("--strict", action="store_true", help="把 warning 也视为失败")
    return parser.parse_args(argv)


def _force_utf8_stdout() -> None:
    """在 Windows 控制台强制 UTF-8 输出，避免非 ASCII 标记触发编码错误。"""
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """入口。"""
    args = _parse_args(argv)
    _force_utf8_stdout()

    repo_root = REPO_ROOT
    skills_root = repo_root / SKILLS_DIRNAME
    if not skills_root.is_dir():
        print(f"ERROR 缺少 {SKILLS_DIRNAME}/ 目录")
        return 1

    skills, problems = collect_skills(skills_root)
    problems.extend(check_layout(repo_root, skills_root))
    for skill in skills:
        problems.extend(check_skill(skill))
    problems.extend(check_readme_index(repo_root, skills))

    errors = [item for item in problems if item.severity == ERROR]
    warnings = [item for item in problems if item.severity == WARNING]

    print_inventory(skills)
    print_problems(problems)
    print(
        f"合计: {len(skills)} 个技能，{len(errors)} 个 error，{len(warnings)} 个 warning"
    )
    if errors or (args.strict and warnings):
        print("verify: 未通过")
        return 1
    print("verify: 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
