# 分级校验命令与工具

本文件是 L1–L4 分级规范与工具命令的落点（从 `AGENTS.md` 搬来），外加 `verify.py` 的用法。**级别由模型判定**，脚本只按传入级别执行。

## 分级与命令

| Level | 场景                                          | 校验                                                        | 备注                    |
| ----- | ------------------------------------------- | --------------------------------------------------------- | --------------------- |
| L1    | 独立脚本（不会被 import / 调用的一次性脚本）                 | Python: ruff check + ruff format --check; Bash: `bash -n` | 纯文档/注释/格式/空白变更也视为 L1  |
| L2    | 包内变更 / 会被 import / 调用的文件（含新增文件）                | L1 + ty + pyrefly                                         | 被 import / 调用的文件至少 L2 |
| L3    | 跨模块交互 / 公共接口或类型签名变更                         | L1 + L2 + pyright                                         | —                     |
| L4    | 大规模重构 / 核心模块 / 类型系统大范围变动                    | L1 + L2 + L3 + mypy                                       | —                     |

裁决规则：

1. 取最高适用 Level，场景不命中方可跳过
2. 判定后打印 `后置校验 L<N>`，并行运行全部适用命令，汇总结果
3. 工具缺失输出 `<tool>: not found, skipped`，不阻塞

```bash
# FILES 由脚本自动发现，或用 --files 显式传入

# ---- L1 ----
ruff check --select E,F,W,I,S,PERF --ignore W291,W293,E203 --line-length 120 <FILES>
ruff format --check <FILES>

# ---- L2 ----
ty check <FILES>
pyrefly check <FILES>

# ---- L3 ----
pyright <FILES>

# ---- L4 ----
mypy --strict <FILES>
```

## 工具安装（仅 uv）

```bash
uv tool install ruff --upgrade
uv tool install ty --upgrade
uv tool install mypy --upgrade
uv tool install pyright --upgrade
uv tool install pyrefly --upgrade
```

`uv` 自身缺失时无法用上述命令补齐，需用户先自行安装 uv。

## 用法

```bash
# Bash 的 cwd 必须是你的项目目录（改动发现依赖它）
SKILL_DIR="${ZCODE_SKILL_DIR}"   # 未展开时改用 ${CLAUDE_SKILL_DIR} 或本技能 base directory

uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L2                    # 自动发现改动的 .py/.sh
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L1 --files a.py       # 显式指定文件
uv run --no-project "$SKILL_DIR/scripts/verify.py" --probe                       # 只打印工具清单
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L3 --fast             # 使用项目缓存换速度
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L2 --install-missing  # 经用户同意后安装缺失工具
```

`uv` 自带 Python，因此不依赖系统上有没有 `python`，**也不需要为不同系统各写一个启动器**。只有 uv 不可用时才退回系统解释器：Windows 优先 `py -3`（`python` 常是 Microsoft Store 占位程序，存在 ≠ 可用），其他系统用 `python3`。

`py_compile` 兜底由**运行本脚本的解释器**执行。经 `uv run` 调用时用的是 uv 受管的版本，可能与你的项目目标版本不同 —— 例如 3.13 不认识 3.14 的 t-string 语法，会把正确的文件误报成语法错误。失败详情里会带上解释器版本，便于判断。

- **改动文件发现**：`git status --porcelain` ∪ `git diff --name-only HEAD`，过滤 `.py` / `.sh`。
- **缓存隔离**：默认给带缓存的工具使用**按进程隔离的临时缓存目录**，避免多处并发调用互相污染；`--fast` 改用项目缓存换取增量速度。
- **退出码**：`0` 通过；`1` 失败（任何校验命令失败，或 `ruff` 缺失）。

## 缺失工具策略

| 缺失项 | 处理 |
| --- | --- |
| `ruff` | **硬失败**，退出码 1，不得降级放过；此时改用 Python 自带的 `py_compile` 保住语法底线 |
| `ty` / `pyrefly` / `pyright` / `mypy` | 该级降级执行，显式打印「该级未真正校验」 |
| `uv` | 报告「缺少 uv，无法安装校验工具链」，不尝试安装 |
| `bash`（存在 `.sh` 改动时） | 该文件跳过 `bash -n` 并显式标注 |
