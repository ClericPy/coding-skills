# 贡献指南

本仓库是一个 Agent Skills 集合，通过 [`npx skills add`](https://github.com/vercel-labs/skills) 分发。
新增或修改技能时，请遵守下面的硬规则；改完必须跑仓库自检。

格式以 [Agent Skills 规范](https://agentskills.io/specification) 为准（`name` / `description` / `license` / `compatibility` / `metadata` / `allowed-tools` 六个标准字段）；本仓库在此之上只加仓库级约定：不写 `license`（根 LICENSE 兜底）、`description` 与 `name` 写成单行引号字符串、`metadata.version` 必须写 `X.Y.Z`、额外接受 `disable-model-invocation` 与 `argument-hint` 两个 Claude Code 扩展字段。

## 目录结构

```
coding-skills/
├── TEMPLATE-AGENTS.md          全局工程规范成稿（可整份采用）
├── TEMPLATE-install-prompt.md  批量安装技能与工具链的提示词（整段粘贴给 agent）
├── TEMPLATE-roles.md           六个角色（总管 / 专家 / DevOps / QA + 可选助理 / BotBuilder）的提示词（整段粘贴进 Bot）
├── TEMPLATE-SKILL.md           新技能起点（复制为 skills/<name>/SKILL.md）
├── skills/<name>/SKILL.md      技能本体，平铺一层
│   ├── references/             可选：按需读取的详细文档
│   └── scripts/                可选：技能调用的辅助脚本
├── scripts/validate.py         仓库自检
├── tests/                      回归测试（不随技能分发）
│   ├── test_verify.py          脚本行为
│   └── test_install.py         安装行为（需 npx + 网络）
└── README.md                   技能索引（必须与磁盘一致）
```

## 硬规则

1. **技能必须平铺**在 `skills/<name>/SKILL.md`，不得出现更深层级。
2. **仓库根目录禁止放 `SKILL.md`** —— CLI 会让它遮蔽全部子技能（除非调用方显式传 `--full-depth`）。
3. **`skills/` 下不得有以 `.` 或 `_` 开头的目录** —— `skills/.curated`、`skills/.experimental`、`skills/.system` 是 CLI 的保留目录，其他 `.`/`_` 开头的目录会被当作技能扫描。这也是模板放根目录并统一 `TEMPLATE-` 前缀的原因：既不进 `skills/` 扫描，也不会被 harness 当成项目指令加载。
4. **目录名必须等于 frontmatter 里的 `name`**，且为 kebab-case（1–64 字符）。
5. **改了 `.py` / `.sh` 必须跑 `change-linter`** 完成分级校验，未通过或工具缺失时不得声称完成。
6. **单一真源 + 薄适配**：同一内容只写一处——角色原文在 `references/roles/`，`TEMPLATE-roles.md` 由脚本生成、禁止手改；不同 harness 的差异写成指向真源的薄配置，正文一律不复制。复制出来的第二份没有校验盯着，改一处漏一处。
7. **技能目录整包分发**：可执行测试与场景文件（`test_*.py`、`*_test.py`、`conftest.py`、`test_scenarios.yaml`）放仓库根 `tests/`，放进技能目录会被装进用户副本，自检直接报错；人读的 `TEST.md` 断言清单属于文档，允许留在技能目录。缓存目录不查——本机跑测试就会生成，安装 CLI 也不会带上它们。

## frontmatter 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | kebab-case，1–64 字符，必须与所在目录名一致；不匹配会导致技能被丢弃 |
| `description` | 是 | 非空，≤1024 字符；缺失或超长会导致技能被丢弃 |
| `disable-model-invocation` | 否 | 置 `true` = **仅手动调用**；置 `false` 或省略 = 除手动外**还会被模型自动触发**（`description` 里可再收窄成点名唤醒） |
| `license` | 否 | 本仓库约定**不写**：由根 `LICENSE`（MIT）统一兜底 |
| `compatibility` | 否 | ≤500 字符的环境要求声明（开放标准字段）。强环境依赖的技能应写，如 change-linter / ttttt / wwwww |
| `argument-hint` | 否 | Claude Code 扩展：`/` 补全时的参数提示（如 `"<tmux会话名> [user@host]"`）；其他 harness 忽略，无害 |
| `allowed-tools` | 否 | 开放标准字段（实验性，各 harness 支持程度不一）：预授权工具列表。官方推荐 `Bash(${CLAUDE_SKILL_DIR}/scripts/x.py *)` 让自带脚本免权限弹窗；**只给无副作用的脚本技能用** |
| `metadata` | 否 | 目前只认 `version`（`X.Y.Z`，随技能内容改动递增）：缺失告警、格式错报错。用于判断快照式安装的副本是哪一版 |

### 调用方式怎么选

- **仅手动**：交互式、有副作用的动作（提交、接管终端）。写 `disable-model-invocation: true`，`description` 是给人看的说明，可写全职责与红线。
- **点名唤醒**：动作有副作用、但希望被用户或其它 Bot 按名字唤起（如验收归档、深度代码评审）。写 `disable-model-invocation: false`，并在 `description` 末尾限定：仅在消息里出现 `[[技能名]]` 形式的点名（含直接写出全名），或角色指令明确写了按该名加载时调用，其余情形不主动使用。
- **可自动触发**：应当在特定时机被模型自己想起的动作（如 role-factory 的造角色流程）。**不要**写该字段，且 `description` 必须写清**触发场景**——它是唯一的自动触发依据。中英双语写触发词能覆盖两种提问方式。

判断依据很简单：如果「模型自己决定调用它」会造成不可预期的副作用，就设为仅手动，或退一步用点名唤醒收窄触发面。

## references/ 与 scripts/

技能按三层加载，判断"什么内容该放哪一层"只看下面这张表：

| 层 | 内容 | 何时进上下文 | 约束 |
| --- | --- | --- | --- |
| 1. metadata | `name` + `description` | 常驻 | 只用于决定"要不要加载这个技能"，所以 description 必须写清触发场景 |
| 2. SKILL.md 正文 | 判断 + 流程 + 何时读哪里 | 技能触发时整份加载 | 超过 500 行自检报 warning |
| 3. `references/`、`scripts/` | 规则表、命令清单、长篇解释、可执行脚本 | 按需 | 长度不设限；脚本可以只执行、不读源码 |

推论：正文里凡是"背下来也没用、只在某一步才用得上"的内容一律下沉到第 3 层，正文只留指针。

- **`references/*.md`**：SKILL.md 只留流程与契约，把大段规则、清单、表格下沉到这里，并在 SKILL.md 里写明**何时读取**。SKILL.md 正文超过 500 行时自检会给出 warning。
  - **标注载荷时机**：引用要写清它在流程第几步用，别只写文件名——例如 `详细规则 → references/dimensions.md（流程第 2 步：逐维度审查）`。只给文件名会让模型一次性把全部 references 读完，第 3 层的意义就没了。
  - 单个 reference 超过 300 行时，在里面自己加一节目录（例：`skills/code-review-expert/references/prompt-failure-modes.md`，394 行）。`skills/ppppp/references/templates.md` 只有 249 行、未到阈值，仅作目录写法参考。
- **`scripts/*.py`**：技能要执行的机械步骤（如发现改动文件、跑外部工具）。脚本不要写仓库，级别判定这类判断题留在 SKILL.md 里由模型完成。脚本自身的后置校验至少 L2。
  - **脚本当黑盒**：SKILL.md 里必须写明「先跑 `--help`，源码只在它跑不动时读」。自带脚本动辄上千行（`change-linter` 的 `verify.py` 约 1400 行），整份读进上下文就为了跑一条命令，是纯浪费。
  - **调用写成 `uv run --no-project "$SKILL_DIR/scripts/x.py"`**（`SKILL_DIR="${ZCODE_SKILL_DIR:-${CLAUDE_SKILL_DIR}}"`，由 harness 展开自己的技能目录变量）。uv 自带 Python，所以一条命令跨全平台，**不要为不同系统各写一个启动器**，也不依赖系统上有没有 `python`。
  - **禁止**写 `python scripts/x.py` 这类相对路径：Bash 的 cwd 是用户项目目录，不是技能目录。
  - 整个技能目录（含 `scripts/`、`references/`）都会随 `npx skills add` 一起安装，所以脚本里不要写死本机绝对路径。

## 新增技能 checklist

1. `mkdir skills/<name>`，并把 `TEMPLATE-SKILL.md` 复制为 `skills/<name>/SKILL.md`。
2. 填 `name`（与目录同名）与 `description`；按上面的原则决定是否写 `disable-model-invocation`；补 `metadata.version`（首次 `"1.0.0"`，之后随内容改动递增）。
3. 需要时添加 `references/` 或 `scripts/`，并在 SKILL.md 中说明何时使用；高频、易说错口径的技能再补一份 `TEST.md`——5–8 条人工核对断言（该出现什么、不该出现什么、什么情形必须停下问），给评审用，不自动跑。
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

`tests/` 下的用例都在临时项目里跑真实 CLI，只断言输出与退出码，因此**改了脚本行为或安装约定就要同步更新用例**。测试不放进技能目录——技能目录会被 `npx skills add` 整包分发给用户；`TEST.md` 是人读的断言清单，不受此限（自检只拦可执行测试与缓存）。

自检还会报两类 warning：正文超过 500 行、或正文超过约 24,000 字节。字节口径是给中文正文兜底的——同样 100 行，中文字节数常是英文的两倍，行数看不出差别；24,000 是经验参考值，不是硬上限，超了先判断要不要下沉到 `references/`。

安装相关的实测结论（落点、符号链接、`--all` 的问题）见 README 的 Quickstart 说明。

自检覆盖：根目录 `SKILL.md`、目录平铺层级、`.`/`_` 开头目录、`name` 与目录名一致性与 kebab-case、`description` 非空与长度、多行块标量拦截（任意顶层字段，含引号判断；同一字段重复写时，任一处是裸块标量即报错）、`license` 字段提醒、未知字段白名单、`compatibility` 长度、`metadata.version` 格式、SKILL.md 正文行数、`references/`·`scripts/` 引用存在性（反引号与 markdown 链接两种写法都查，`#` 锚点与 `./` 前缀先归一化，含 `<...>` 的模板占位符跳过）、README 索引双向一致与重复条目。

自检**只打印**每个技能的调用方式，不强制它必须手动或自动——两种都是合法设计。

`validate.py` 的 frontmatter 解析是手写单行解析，不支持多行 YAML 块（`|`）等写法——本仓库约定 `name` / `description` 一律写成单行引号字符串。发布前可用官方参考校验器做交叉验证：`uvx --from skills-ref agentskills validate ./skills/<name>`。注意：它按开放标准六字段校验，会把 `disable-model-invocation` / `argument-hint` 等 Claude Code 扩展字段报为 unexpected——**这是预期行为**（本仓库经 `npx skills add` 分发，主流 harness 普遍接受扩展字段），只有六字段（name/description/license/compatibility/metadata/allowed-tools）内的告警才算真问题。
