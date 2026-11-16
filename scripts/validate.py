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
LICENSE_FIELD = "license"
VERSION_FIELD = "metadata.version"

# 该字段只认 true / false：其他拼写（yes / on / 1）在不同 harness 上解析结果可能不一致
INVOCATION_VALUES: frozenset[str] = frozenset({"true", "false"})

# 开放标准字段 + Claude Code 扩展字段；表外的顶层字段一律视为拼写错误（license 单列警告）
KNOWN_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "compatibility",
        "metadata",
        "allowed-tools",
        "argument-hint",
        MANUAL_FIELD,
    }
)

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME_MAX_LENGTH = 64
DESCRIPTION_MAX_LENGTH = 1024
COMPATIBILITY_MAX_LENGTH = 500
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
BODY_MAX_LINES = 500
INDEX_PATTERN = re.compile(r"\./skills/([^/)\s]+)/SKILL\.md")
# SKILL.md 里引用自带文件的两种写法（反引号与 markdown 链接），目标必须真实存在；
# 含 `<...>` 的是模板占位符、`#` 之后是锚点、`./` 是等价前缀，判定前统一归一化
POINTER_PATTERN = re.compile(
    r"`((?:\./)?(?:references|scripts)/[^`\s]+)`"
    r"|\]\(((?:\./)?(?:references|scripts)/[^)\s]+)\)"
)
BLOCK_SCALAR_MARKS = (">", "|")

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
    compatibility: str | None
    version: str | None
    unexpected_fields: tuple[str, ...]
    has_license: bool
    text: str
    manual_present: bool
    block_scalars: tuple[str, ...]


@dataclass(frozen=True)
class Problem:
    """一条检查结果。"""

    severity: str
    message: str


def strip_quotes(value: str) -> tuple[str, bool]:
    """取出字段值，返回 `(值, 原始值是否被成对引号包住)`。

    整段就是注释时返回空串——否则 `parent` 会被清空（子键丢失），
    或让只有注释的 description 通过非空校验。
    """
    if value.startswith("#"):
        return "", False
    if len(value) >= 2 and value[0] in "\"'" and value[0] in value[1:]:
        return value[1 : value.index(value[0], 1)], True
    return value.split(" #", 1)[0].rstrip(), False


def parse_top_level(
    line: str, fields: dict[str, str], block_scalars: set[str]
) -> str | None:
    """解析一行顶格字段；值为空时返回它作为子键父层级的键名。

    裸块标量（未加引号、以 `>` 或 `|` 开头）在这里**当场**记入集合，不靠事后
    推测：同一字段重复出现时，无论先后顺序，只要有一处是裸块标量就留下记录。
    """
    key, separator, value = line.partition(":")
    if not separator:
        return None
    field = key.strip()
    cleaned, was_quoted = strip_quotes(value.strip())
    fields[field] = cleaned
    if not was_quoted and cleaned[:1] in BLOCK_SCALAR_MARKS:
        block_scalars.add(field)
    return field if not cleaned else None


def parse_child(line: str, fields: dict[str, str], parent: str) -> None:
    """解析一行缩进子键，写成 `parent.key`。"""
    key, separator, value = line.strip().partition(":")
    if separator:
        cleaned, _ = strip_quotes(value.strip())
        fields[f"{parent}.{key.strip()}"] = cleaned


def parse_frontmatter(text: str) -> tuple[dict[str, str], frozenset[str]] | None:
    """解析文件首个 `---` 块，止于下一个 `---`。

    顶格行收作顶层字段；紧跟其后的缩进行收作该字段的子键（`metadata.version`
    这类，写成 `metadata.version`），用于校验版本号。整行 `#` 注释与行尾注释都
    会丢掉。返回值第二项是「出现过裸块标量」的顶层字段集合：块标量只可能在未
    加引号的值上，且任一处出现即算（重复定义时后一处合法也救不回来）。

    这里仍是手写单行解析，不是 YAML：`description: >-` 这类块标量会被原样读成
    字面量 `">-"`，由 check_fields 单独拦下。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    block_scalars: set[str] = set()
    parent: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields, frozenset(block_scalars)
        if not line or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            if parent is not None:
                parse_child(line, fields, parent)
            continue
        parent = parse_top_level(line, fields, block_scalars)
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
    parsed = parse_frontmatter(text)
    fields, block_scalars = parsed if parsed is not None else ({}, frozenset())
    manual_present = MANUAL_FIELD in fields
    manual_value = fields.get(MANUAL_FIELD) or None
    unexpected = tuple(
        sorted(
            key
            for key in fields
            if "." not in key and key not in KNOWN_FIELDS and key != LICENSE_FIELD
        )
    )
    return Skill(
        directory=path.parent.name,
        path=path,
        name=fields.get("name") or None,
        description=fields.get("description") or None,
        manual_only=manual_value is not None and manual_value.lower() == "true",
        manual_value=manual_value,
        body_lines=body_line_count(text),
        compatibility=fields.get("compatibility") or None,
        version=fields.get(VERSION_FIELD) or None,
        unexpected_fields=unexpected,
        has_license=LICENSE_FIELD in fields,
        text=text,
        manual_present=manual_present,
        block_scalars=tuple(sorted(block_scalars)),
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


def check_identity(skill: Skill) -> list[Problem]:
    """name 与 description 的必填、格式与长度。"""
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
    return problems


def check_invocation(skill: Skill) -> list[Problem]:
    """disable-model-invocation 的存在性与取值语义。"""
    if not skill.manual_present:
        return []
    label = f"{SKILLS_DIRNAME}/{skill.directory}/{SKILL_FILENAME}"
    if not skill.manual_value:
        return [
            Problem(
                WARNING,
                f"{label}: {MANUAL_FIELD} 是空值，无法判定语义，将被当成「可自动触发」；"
                "请显式写 true（仅手动）或 false（可自动）",
            )
        ]
    if skill.manual_value.lower() in INVOCATION_VALUES:
        return []
    return [
        Problem(
            WARNING,
            f"{label}: {MANUAL_FIELD} 取值 {skill.manual_value!r} 语义不确定，请写成 true 或 false"
            "（yes / on / 1 等写法在不同 harness 上可能被解析成相反的结果）",
        )
    ]


def check_fields(skill: Skill) -> list[Problem]:
    """compatibility、license、未知字段与 metadata.version 的规范。"""
    problems: list[Problem] = []
    label = f"{SKILLS_DIRNAME}/{skill.directory}/{SKILL_FILENAME}"
    problems.extend(
        Problem(
            ERROR,
            f"{label}: {field} 疑似 YAML 块标量（值以 > 或 | 开头），"
            "本仓库只支持单行引号字符串，多行写法会绕过长度校验"
            "（加引号写成单行字符串即可通过）",
        )
        for field in skill.block_scalars
    )

    if (
        skill.compatibility is not None
        and len(skill.compatibility) > COMPATIBILITY_MAX_LENGTH
    ):
        problems.append(
            Problem(
                ERROR,
                f"{label}: compatibility 长度 {len(skill.compatibility)} 超过 {COMPATIBILITY_MAX_LENGTH} 字符",
            )
        )

    if skill.has_license:
        problems.append(
            Problem(
                WARNING,
                f"{label}: 不要写 {LICENSE_FIELD} 字段——由根 LICENSE（MIT）统一兜底",
            )
        )

    problems.extend(
        Problem(
            WARNING,
            f"{label}: 未识别的 frontmatter 字段 {field_name!r}，疑似拼写错误"
            "（拼错的 disable-model-invocation 会被静默当成「可自动触发」）",
        )
        for field_name in skill.unexpected_fields
    )

    if skill.version is None:
        problems.append(
            Problem(
                WARNING,
                f'{label}: 缺少 {VERSION_FIELD}，建议从 "1.0.0" 起并随改动递增',
            )
        )
    elif not VERSION_PATTERN.match(skill.version):
        problems.append(
            Problem(
                ERROR,
                f"{label}: {VERSION_FIELD} 必须写成 X.Y.Z（实际 {skill.version!r}）",
            )
        )
    return problems


def check_body(skill: Skill) -> list[Problem]:
    """正文行数上限。"""
    if skill.body_lines <= BODY_MAX_LINES:
        return []
    label = f"{SKILLS_DIRNAME}/{skill.directory}/{SKILL_FILENAME}"
    return [
        Problem(
            WARNING,
            f"{label}: 正文 {skill.body_lines} 行超过 {BODY_MAX_LINES} 行，考虑拆到 references/",
        )
    ]


def check_skill(skill: Skill) -> list[Problem]:
    """检查单个技能的 frontmatter 规范。"""
    return [
        *check_identity(skill),
        *check_invocation(skill),
        *check_fields(skill),
        *check_body(skill),
    ]


def normalize_pointer(target: str) -> str:
    """把引用目标归一化成技能目录下的相对路径：去掉锚点与 `./` 前缀。"""
    return target.split("#", 1)[0].removeprefix("./")


def check_pointers(skill: Skill) -> list[Problem]:
    """核对 SKILL.md 里引用的 references/ scripts/ 文件是否真实存在（反引号与链接两种写法）。"""
    label = f"{SKILLS_DIRNAME}/{skill.directory}/{SKILL_FILENAME}"
    targets = {
        normalize_pointer(target)
        for group in POINTER_PATTERN.findall(skill.text)
        for target in group
        if target and "<" not in target
    }
    return [
        Problem(ERROR, f"{label}: 引用的 {target} 不存在")
        for target in sorted(targets)
        if not (skill.path.parent / target).is_file()
    ]


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
        if skill.manual_present and not skill.manual_value:
            mode = "取值存疑(空值)"
        elif (
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
        problems.extend(check_pointers(skill))
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
