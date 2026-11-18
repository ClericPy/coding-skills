"""把 references/roles/*.md 拼成仓库根的 TEMPLATE-roles.md。

内容真源是 skills/role-factory/references/roles/ 下的六个文件；
本脚本只做拼接与写盘，不做任何改写。
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
ROLES_DIR = SKILL_DIR / "references" / "roles"
TARGET = REPO_ROOT / "TEMPLATE-roles.md"

ROLE_ORDER = ("总管", "专家", "DevOps", "QA", "助理", "BotBuilder")

HEADER = (
    "<!-- 本文件由 skills/role-factory/scripts/build_roles.py 生成；"
    "内容源是 skills/role-factory/references/roles/*.md，改内容请改那里后重跑脚本。 -->"
)

PREAMBLE = (
    "角色：总管 + 3 个职能角色（专家 / DevOps / QA）+ 两个可选（助理 / BotBuilder）。"
)


def render() -> str:
    """返回 TEMPLATE-roles.md 应有内容（不写盘，供校验脚本复用）。"""
    required = [ROLES_DIR / f"{name}.md" for name in ROLE_ORDER]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"缺少角色文件: {', '.join(missing)}")
    parts = [PREAMBLE]
    parts.extend(path.read_text(encoding="utf-8").strip("\n") for path in required)
    return HEADER + "\n\n" + "\n\n".join(parts) + "\n"


def main() -> int:
    if not TARGET.is_file():
        print(
            f"未找到 {TARGET}：本脚本只重新生成已存在的文件，避免在技能安装副本里误写。",
            file=sys.stderr,
        )
        return 2
    text = render()
    TARGET.write_bytes(text.encode("utf-8"))
    print(f"已生成 {TARGET.name}: {len(text)} 字符 / {text.count(chr(10))} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
