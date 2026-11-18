# coding-skills

个人编码工作流技能集，面向 Claude Code 等支持 Agent Skills 格式的工具，通过 `npx skills add` 分发。

[![skills.sh](https://skills.sh/b/ClericPy/coding-skills)](https://skills.sh/ClericPy/coding-skills)（徽章页由安装遥测触发收录，收录前显示 404 属正常）

## 仓库结构

| 路径 | 作用 | 随技能分发 |
| --- | --- | --- |
| `skills/<name>/` | 技能本体：`SKILL.md` + 可选 `references/`、`scripts/`，平铺一层 | 是 |
| `TEMPLATE-SKILL.md` | 新技能起点，复制为 `skills/<name>/SKILL.md` 再填 frontmatter | 否 |
| `TEMPLATE-AGENTS.md` | 作者在用的全局工程规范成稿，可整份采用 | 否 |
| `TEMPLATE-install-prompt.md` | 批量安装技能与工具链的提示词，整段粘贴给 agent | 否 |
| `TEMPLATE-roles.md` | 六角色（总管 / 专家 / DevOps / QA + 可选助理 / BotBuilder）的提示词，由 role-factory 技能的 references 生成（勿手改） | 否 |
| `scripts/validate.py` | 仓库自检：frontmatter、目录层级、引用存在性、README 索引 | 否 |
| `tests/` | 回归测试（`test_verify.py` 脚本行为，`test_install.py` 安装行为） | 否 |
| `CONTRIBUTING.md` | 新增/修改技能的硬规则与 frontmatter 字段表 | 否 |
| `CHANGELOG.md` | 按时间倒序的变更记录 | 否 |

## 安装

```bash
npx skills add ClericPy/coding-skills --list                               # 只预览，不安装
npx skills add ClericPy/coding-skills -g -a <agent> -y                    # 全局安装全部技能
npx skills add ClericPy/coding-skills -a <agent> --skill change-linter -y  # 只装一个
```

`<agent>` 是 harness 名（`claude-code` / `codex` / `opencode` 等，全部取值见 `npx skills add --help`）；要装进多个 harness 就重复 `-a`；项目级安装去掉 `-g`。装好后用 `/技能名` 调用，例如 `/ccccc`。

**别用 `--all`**：实测它会把技能散进多个 agent 目录、落点取决于本机检测到哪些 agent，不稳定；要可预测就显式指定 `-a`。**安装落点**有两种：命令式 `-g -a <agent>` 直接落进该 agent 自己的 skills 目录；交互式或多 agent 时实体统一放 `~/.agents/skills/<name>/`，各 agent 目录里放链接（Windows 上是 JUNCTION，无需开发者模式）。两者都是**快照**，不跟随本仓库更新。

## English

A personal coding-workflow skill collection for Claude Code and any tool that reads the Agent Skills format, distributed via `npx skills add` (commands above). Installed copies are snapshots: refresh with `npx skills update -g -y`, remove with `npx skills remove <name>`.

## 技能

| 技能 | 用途 | 调用名 | 调用方式 |
| --- | --- | --- | --- |
| [**ccccc**](./skills/ccccc/SKILL.md) | 按公司严格规范生成并创建 Git 提交：复用已有 ID 字段、描述 ≤200 字不换行、单次新增 ≤500 行、绝不 push | `/ccccc` | 仅手动 |
| [**ppppp**](./skills/ppppp/SKILL.md) | 提示词调制器：按场景判定表匹配 10 个模板并填充占位符，只输出调制后的提示词，不回答原问题 | `/ppppp` | 仅手动 |
| [**ttttt**](./skills/ttttt/SKILL.md) | ⚠️ 接管 tmux 会话执行终端操作：「看-想-做」闭环，含 base64 防转义通道与破坏性命令确认 | `/ttttt` | 仅手动 |
| [**wwwww**](./skills/wwwww/SKILL.md) | 执行 openspec change 全流程：Worktree 隔离 → 实现自测 → 验收 → 存档 → 提交 → rebase + merge --ff-only 合并 | `/wwwww` | 仅手动 |
| [**yyyyy**](./skills/yyyyy/SKILL.md) | 验收进行中的变更（spec 变更或 openspec change，自动判断）：文档代码对齐、测试全过、闸门检查，通过后存档清理。只做闸门，深审请手动 `/code-review-expert` | `/yyyyy` | 仅手动 |
| [**code-review-expert**](./skills/code-review-expert/SKILL.md) | 资深架构师级 Code Review 与文档审验：代码走七维度，提示词文档走文本与提示词判据；只报 ≥80% 置信度问题并分 Blocker/Major/Minor 三档，文档类只出报告、不改被审文件 | `/code-review-expert` | 仅手动 |
| [**change-linter**](./skills/change-linter/SKILL.md) | 改动 Python / Shell 后判定并执行 L1–L4 分级后置校验，另可叠加源码安全扫描与依赖漏洞审计两个正交轴，并如实报告工具缺失导致的未校验缺口 | `/change-linter` | 可自动触发 |
| [**role-factory**](./skills/role-factory/SKILL.md) | 建 Bot / 改角色指令 / 搭团队时出角色提示词：查重、备份旧指令、按项目裁剪，产出可直接粘贴的 instructions（默认带来源行）；只出文本，建 Bot 仍由 Main Bot 做 | `/role-factory` | 可自动触发 |

**仅手动** = 只能由你在 `/` 菜单里主动调用；**可自动触发** = 模型也会在合适时机自己调用。**ttttt** 能向真实终端发键、经 ssh 操作远程机器，破坏性命令必须先经你确认（详见其 SKILL.md「安全防线」）。

## 批量安装工具链（可选）

[`TEMPLATE-install-prompt.md`](./TEMPLATE-install-prompt.md) 是一份**整段粘贴给 AI 编程工具**的安装提示词：先问你把技能绑到哪些 agent，再按条目分别用 `npx skills add`（skill 类）、MCP 配置（MCP 类）、包管理器（系统工具类）安装，不会把 skill 装成 MCP。除本仓库 8 个技能外，还覆盖几套常用第三方 skill、MCP server 与 CLI 工具（repomix、chrome-devtools、anysearch、codegraph、agent-browser 等），用不到的条目删掉即可。

## 采用同款全局规范（可选）

[`TEMPLATE-AGENTS.md`](./TEMPLATE-AGENTS.md) 是作者在用的全局工程规范（与 `change-linter` 联动），可整份采用：复制到 harness 的全局指令位置（如 `~/.claude/AGENTS.md` 或项目根 `AGENTS.md`）再按项目裁剪；用作项目级时按 [agents.md](https://agents.md) 标准补构建/测试命令与安全注意事项。**已有配置先对比合并，不要直接覆盖**。

## 更新与卸载

技能是快照式安装，不跟随本仓库更新：

```bash
npx skills update -g -y          # 升级全局全部技能
npx skills remove <技能名>        # 卸载（按提示选作用域）
```

只想刷新单个技能或 `update` 报失败时，重跑一次 `npx skills add` 即可——幂等覆盖，不会产生重复。

## 依赖工具

`change-linter` 依赖 ruff / ty / mypy / pyright / pyrefly（可选 shellcheck、bandit、pip-audit）。逐项安装命令见 [references/lint-levels.md](./skills/change-linter/references/lint-levels.md)，工具缺失时的处理见其 SKILL.md「缺失工具的处理」；缺工具时该技能只报告缺口并询问一次，**不会静默安装**。其余 7 个技能不依赖这些工具。

## 贡献

新增或修改技能前先读 [CONTRIBUTING.md](./CONTRIBUTING.md)，改完必须通过自检与测试：

```bash
uv run --no-project scripts/validate.py     # 结构、frontmatter、README 索引一致性
uv run --no-project tests/test_verify.py    # change-linter 与自检脚本的回归用例
uv run --no-project tests/test_install.py   # 安装行为回归（需 npx + 网络，离线自动跳过）
```

新增技能时在技能表加一行，链接指向 `./skills/` 下该技能目录的 `SKILL.md`（写法见 CONTRIBUTING 第 4 步）——自检靠它核对索引。仓库变更按日记录在 [CHANGELOG.md](./CHANGELOG.md)。

## License

[MIT](./LICENSE)
