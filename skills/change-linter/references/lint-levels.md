# 分级校验命令与工具

本文件是 L1–L4 分级规范与工具命令的落点，外加 `verify.py` 的用法。**级别由模型判定**，脚本只按传入级别执行。

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
3. 工具缺失按下方「缺失工具策略」处理：`ruff` 硬失败，类型检查器降级并显式标注，均不得视为通过

```bash
# FILES 由脚本自动发现，或用 --files 显式传入

# ---- L1 ----
ruff check --select E,F,W,I,S,PERF --ignore W291,W293,E203 --line-length 120 <FILES>
ruff format --check <FILES>
ruff check --select C901 --config lint.mccabe.max-complexity=8 --output-format concise <FILES>   # 复杂度，见下
bash -n <SH_FILES>

# ---- L2 ----
ty check <FILES>
pyrefly check <FILES>

# ---- L3 ----
pyright <FILES>

# ---- L4 ----
mypy --strict <FILES>
```

### 复杂度（C901）双阈值

随 ruff 一起跑，阈值由脚本二次裁决，**不交给 ruff 的退出码**：

| 函数归属 | 阈值 | 判定 |
| --- | --- | --- |
| 本次改动碰过的函数（def 行落在新增/修改行区间内） | **>8** | 拦下 |
| 同一次改动里没碰过的存量函数 | **>12** | 拦下 |
| 存量函数落在 8~12 | — | 放过，报告里记为「存量容忍」 |

- 区间来自 `git diff -U0 HEAD` 的块头；未跟踪的新文件整file按新代码算。
- 取不到 diff（非 git 仓库、路径不在仓库内、改动已提交）时**一律按存量口径 12**，避免把老函数误判成新代码制造噪音。
- 该检查独立成一条 `complexity` 记录，与 ruff 的风格检查分开显示，通过时也会打印「存量容忍 N 处」。

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
SKILL_DIR="${ZCODE_SKILL_DIR:-${CLAUDE_SKILL_DIR}}"   # 由 harness 展开自己的技能目录变量；都未展开时直接填本技能 base directory

uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L2                    # 自动发现改动的 .py/.sh
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L1 --files a.py       # 显式指定文件
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L3 --project-scope    # 公共接口变更：类型工具扫整个项目
uv run --no-project "$SKILL_DIR/scripts/verify.py" --probe                       # 只打印工具清单
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L3 --fast             # 使用项目缓存换速度
uv run --no-project "$SKILL_DIR/scripts/verify.py" --level L2 --install-missing  # 经用户同意后安装缺失工具
```

- **`--project-scope`**：类型工具（ty/pyrefly/pyright/mypy）的检查对象从改动文件扩大到整个项目目录，ruff 与 `bash -n` 仍只查改动文件。用于 L3/L4 公共接口 / 跨模块变更——单文件检查抓不到「改签名破坏下游调用方」；会连带扫出项目存量类型错误，汇报时须区分存量与本次引入。
- **复杂度检查**：随 ruff 一起跑（L1 起），阈值与豁免规则见上方「复杂度（C901）双阈值」。
- **ruff 兜底参数**：`--select/--ignore/--line-length` 仅在项目未自带 ruff 配置时传入；项目根有 `pyproject.toml`（含 `[tool.ruff]`）或 `ruff.toml` 时自动以项目配置为准，脚本会显式打印这一让位。**复杂度那条不受此让位影响**：它固定带 `--select C901` 与 `max-complexity`，否则项目配置一存在就会查不到复杂度。

`uv` 自带 Python，因此不依赖系统上有没有 `python`，**也不需要为不同系统各写一个启动器**。只有 uv 不可用时才退回系统解释器：Windows 优先 `py -3`（`python` 常是 Microsoft Store 占位程序，存在 ≠ 可用），其他系统用 `python3`。

`py_compile` 兜底由**运行本脚本的解释器**执行。经 `uv run` 调用时用的是 uv 受管的版本，可能与你的项目目标版本不同 —— 例如 3.13 不认识 3.14 的 t-string 语法，会把正确的文件误报成语法错误。失败详情里会带上解释器版本，便于判断。

- **改动文件发现**：`git status --porcelain` ∪ `git diff --name-only HEAD`，过滤 `.py` / `.sh`。
- **缓存隔离**：默认给带缓存的工具使用**按进程隔离的临时缓存目录**，避免多处并发调用互相污染；`--fast` 改用项目缓存换取增量速度。
- **工作目录与相对路径**：检测到项目自带 ruff 配置时，校验子进程以**配置所在目录**为工作目录，传给工具的文件路径也相对化。ruff 的 `per-file-ignores` 按「文件相对工作目录的路径」匹配——工作目录与配置目录错位（如在子目录里调用、或用绝对路径）会让 `tests/**` 之类豁免静默失效，表现为成片 S101 假阳性。找不到配置时先按 cwd 上溯，仍无则按首个目标文件所在目录上溯。
- **退出码**：`0` 通过（含改动仅为删除文件、无适用校验对象的空跑）；`1` 失败（任何校验命令失败、`ruff` 缺失或无适用改动）。

## 缺失工具策略

| 缺失项 | 处理 |
| --- | --- |
| `ruff` | **硬失败**，退出码 1，不得降级放过；此时改用 Python 自带的 `py_compile` 保住语法底线 |
| `ty` / `pyrefly` / `pyright` / `mypy` | 该级降级执行，显式打印「该级未真正校验」 |
| `uv` | 报告「缺少 uv，无法安装校验工具链」，不尝试安装 |
| `bash`（存在 `.sh` 改动时） | 先按 PATH 探测，找不到再回退到 Git for Windows 的常见安装位置（`%ProgramFiles%\Git\bin\bash.exe` 等）；两处都没有时该级判为未校验并显式标注「没有任何校验被真实执行」 |
| `shellcheck`（可选增强） | 存在则对 `.sh` 加跑静态检查（发现即判失败）；缺失仅提示，不影响通过与否，也不自动安装。补装方式：`uv tool install shellcheck-py`（PyPI 再打包，自带官方二进制，装完可执行名是 `shellcheck`） |
| `--files` 指定的路径不存在 | 预检后直接报「--files 找不到文件」并给出「相对当前工作目录解析」的提示，不把 `E902 系统找不到指定的文件` 这种误导读者的报错抛给用户 |
