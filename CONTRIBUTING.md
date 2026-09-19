# 贡献指南

本仓库是一个 Agent Skills 集合，通过 [`npx skills add`](https://github.com/vercel-labs/skills) 分发。
新增或修改技能时，请遵守下面的硬规则；改完必须跑仓库自检。

## 目录结构

```
coding-skills/
├── skills/<name>/SKILL.md     技能本体，平铺一层
│   ├── references/            可选：按需读取的详细文档
│   └── scripts/               可选：技能调用的辅助脚本
├── templates/                 骨架与示例，不参与技能发现
│   ├── SKILL.md.tmpl          新技能起点
│   ├── AGENTS.md              AGENTS.md 成稿（可整份采用）
│   └── install-prompt.md      批量安装技能与工具链的提示词（整段粘贴给 agent）
├── scripts/validate.py        仓库自检
├── tests/                     回归测试（不随技能分发）
│   ├── test_verify.py         脚本行为
│   └── test_install.py        安装行为（需 npx + 网络）
└── README.md                  技能索引（必须与磁盘一致）
```

## 硬规则

1. **技能必须平铺**在 `skills/<name>/SKILL.md`，不得出现更深层级。
2. **仓库根目录禁止放 `SKILL.md`** —— CLI 会让它遮蔽全部子技能（除非调用方显式传 `--full-depth`）。
3. **`skills/` 下不得有以 `.` 或 `_` 开头的目录** —— `skills/.curated`、`skills/.experimental`、`skills/.system` 是 CLI 的保留目录，其他 `.`/`_` 开头的目录会被当作技能扫描。这也是模板放在 `templates/` 而不是 `skills/_template/` 的原因。
4. **目录名必须等于 frontmatter 里的 `name`**，且为 kebab-case（1–64 字符）。
5. **改了 `.py` / `.sh` 必须跑 `change-linter`** 完成分级校验，未通过或工具缺失时不得声称完成。

## frontmatter 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | kebab-case，1–64 字符，必须与所在目录名一致；不匹配会导致技能被丢弃 |
| `description` | 是 | 非空，≤1024 字符；缺失或超长会导致技能被丢弃 |
| `disable-model-invocation` | 否 | 置 `true` = **仅手动调用**；省略 = 除手动外**还会被模型自动触发** |
| `license` | 否 | 本仓库约定**不写**：由根 `LICENSE`（MIT）统一兜底 |
| `compatibility` | 否 | ≤500 字符的环境要求声明（开放标准字段）。强环境依赖的技能应写，如 change-linter / ttttt / wwwww |
| `argument-hint` | 否 | Claude Code 扩展：`/` 补全时的参数提示（如 `"<tmux会话名> [user@host]"`）；其他 harness 忽略，无害 |
| `allowed-tools` | 否 | Claude Code 扩展（实验性）：预授权工具列表。官方推荐 `Bash(${CLAUDE_SKILL_DIR}/scripts/x.py *)` 让自带脚本免权限弹窗；**只给无副作用的脚本技能用** |
| `metadata` | 否 | 自由元数据；本仓库暂未使用 |

### 调用方式怎么选

- **仅手动**：交互式、有副作用的动作（提交、接管终端、验收归档）。写 `disable-model-invocation: true`，`description` 是给人看的说明，可写全职责与红线。
- **可自动触发**：应当在特定时机被模型自己想起的动作（如改完代码后的分级校验）。**不要**写该字段，且 `description` 必须写清**触发场景**——它是唯一的自动触发依据。中英双语写触发词能覆盖两种提问方式。

判断依据很简单：如果「模型自己决定调用它」会造成不可预期的副作用，就设为仅手动。

## references/ 与 scripts/

- **`references/*.md`**：SKILL.md 只留流程与契约，把大段规则、清单、表格下沉到这里，并在 SKILL.md 里写明**何时读取**。SKILL.md 正文超过 500 行时自检会给出 warning。
- **`scripts/*.py`**：技能要执行的机械步骤（如发现改动文件、跑外部工具）。脚本不要写仓库，级别判定这类判断题留在 SKILL.md 里由模型完成。脚本自身的后置校验至少 L2。
  - **调用写成 `uv run --no-project "$SKILL_DIR/scripts/x.py"`**（`SKILL_DIR="${ZCODE_SKILL_DIR:-${CLAUDE_SKILL_DIR}}"`，由 harness 展开自己的技能目录变量）。uv 自带 Python，所以一条命令跨全平台，**不要为不同系统各写一个启动器**，也不依赖系统上有没有 `python`。
  - **禁止**写 `python scripts/x.py` 这类相对路径：Bash 的 cwd 是用户项目目录，不是技能目录。
  - 整个技能目录（含 `scripts/`、`references/`）都会随 `npx skills add` 一起安装，所以脚本里不要写死本机绝对路径。

## 新增技能 checklist

1. `mkdir skills/<name>`，并把 `templates/SKILL.md.tmpl` 复制为 `skills/<name>/SKILL.md`。
2. 填 `name`（与目录同名）与 `description`；按上面的原则决定是否写 `disable-model-invocation`。
3. 需要时添加 `references/` 或 `scripts/`，并在 SKILL.md 中说明何时使用。
4. 在 `README.md` 技能表里加一行，**链接必须是 `[name](./skills/<name>/SKILL.md)`** 这个形式——自检靠它核对索引。
5. 跑 `uv run --no-project scripts/validate.py`，必须通过。
6. 若改动了 `.py` / `.sh`，调用 `change-linter` 技能完成分级校验。
7. 在 `CHANGELOG.md` 顶部「未发布」段落补一条本次变更（提交时并入当日日期段落）。条目格式：`## YYYY-MM-DD` 日期段 + `- **HH:MM** \`前缀:\` 摘要`，同日多条按时间倒序，前缀与提交信息保持一致。

## 自检与测试

```bash
uv run --no-project scripts/validate.py            # 打印技能清单与问题
uv run --no-project scripts/validate.py --strict   # warning 也视为失败
uv run --no-project tests/test_verify.py           # 脚本行为回归
uv run --no-project tests/test_install.py          # 安装行为回归（离线自动跳过）
```

`tests/` 下的用例都在临时项目里跑真实 CLI，只断言输出与退出码，因此**改了脚本行为或安装约定就要同步更新用例**。测试不放进技能目录——技能目录会被 `npx skills add` 整包分发给用户。

安装相关的实测结论（落点、符号链接、`--all` 的问题）见 README 的 Quickstart 说明。

自检覆盖：根目录 `SKILL.md`、目录平铺层级、`.`/`_` 开头目录、`name` 与目录名一致性与 kebab-case、`description` 非空与长度、SKILL.md 正文行数、README 索引双向一致与重复条目。

自检**只打印**每个技能的调用方式，不强制它必须手动或自动——两种都是合法设计。

`validate.py` 的 frontmatter 解析是手写单行解析，不支持多行 YAML 块（`|`）等写法——本仓库约定 `name` / `description` 一律写成单行引号字符串。发布前可用官方参考校验器做交叉验证：`uvx --from skills-ref agentskills validate ./skills/<name>`。注意：它按开放标准六字段校验，会把 `disable-model-invocation` / `argument-hint` 等 Claude Code 扩展字段报为 unexpected——**这是预期行为**（本仓库经 `npx skills add` 分发，主流 harness 普遍接受扩展字段），只有六字段（name/description/license/compatibility/metadata/allowed-tools）内的告警才算真问题。
