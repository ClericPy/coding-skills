# coding-skills

个人编码工作流技能集，面向 ZCode / Claude Code 等支持 Agent Skills 的工具。

[![skills.sh](https://skills.sh/b/ClericPy/coding-skills)](https://skills.sh/ClericPy/coding-skills)

> 徽章指向 skills.sh 的技能目录页：收录由 CLI 的安装遥测触发（有人 `npx skills add` 过才会建索引），收录前页面显示 404，属正常现象，不影响仓库与本地安装。

## English

A personal coding-workflow skill collection for ZCode / Claude Code and any tool that reads the Agent Skills format, distributed via `npx skills add`. Requires Node.js with `npx` available.

```bash
npx skills add ClericPy/coding-skills --list                              # preview only
npx skills add ClericPy/coding-skills -g -a zcode -y                      # install all (user scope)
npx skills add ClericPy/coding-skills -a zcode -y                         # install into the current repo
npx skills add ClericPy/coding-skills -a zcode --skill change-linter -y   # install a single skill
```

Skills: **ccccc** (normalized git commits) · **ppppp** (prompt modulator, 10 templates) · **ttttt** (tmux terminal co-pilot) · **wwwww** (openspec change flow) · **yyyyy** (change acceptance & archive) · **code-review-expert** (senior-level code review) · **change-linter** (L1–L4 post-edit checks, auto-triggered)

Details in the Chinese sections below. Installed copies are snapshots: refresh them with `npx skills update -g -y` (or re-run `add`), remove with `npx skills remove <name>`.

## Quickstart

```bash
# 预览仓库里的技能（只列出，不安装）
npx skills add ClericPy/coding-skills --list

# 全局安装全部技能到 ZCode（→ ~/.zcode/skills/<name>/）
npx skills add ClericPy/coding-skills -g -a zcode -y

# 项目级安装（→ <repo>/.zcode/skills/<name>/，可随仓库提交、共享给团队）
npx skills add ClericPy/coding-skills -a zcode -y

# 只装某一个技能
npx skills add ClericPy/coding-skills -a zcode --skill change-linter -y
```

装好后用 `/技能名` 调用，例如 `/ccccc`、`/code-review-expert`。

> **别用 `--all`。** 实测它会把技能散进多个 agent 目录（本机出现 `.agents/skills/` 与 `agent/skills/` **两份完整真实副本**，其余目录放符号链接），而且具体落点取决于本机检测到了哪些 agent，不稳定。要可预测就显式指定 `-a <agent>`。
>
> **安装落点**（实测两种布局，取决于装法）：① 命令式 `-g -a <agent>`——技能直接落进该 agent 的目录，ZCode 即 `~/.zcode/skills/<name>/`（本机实测此路径下生成技能目录，且不出现 `~/.agents/skills/`）；② 交互式安装或多 agent——实体统一放通用目录 `~/.agents/skills/<name>/`，各 agent 目录里放链接指向它（Windows 上是 **JUNCTION**，无需开发者模式）。两种布局装的都是**快照**，不跟随源仓库更新，见下方「更新与卸载」。

## 技能

| 技能 | 用途 | 调用名 | 调用方式 |
| --- | --- | --- | --- |
| [**ccccc**](./skills/ccccc/SKILL.md) | 按公司严格规范生成并创建 Git 提交：复用已有 ID 字段、描述 ≤200 字不换行、单次新增 ≤500 行、绝不 push | `/ccccc` | 仅手动 |
| [**ppppp**](./skills/ppppp/SKILL.md) | 提示词调制器：按场景判定表匹配 10 个模板并填充占位符，只输出调制后的提示词，不回答原问题 | `/ppppp` | 仅手动 |
| [**ttttt**](./skills/ttttt/SKILL.md) | ⚠️ 接管 tmux 会话执行终端操作：「看-想-做」闭环，含 base64 防转义通道与破坏性命令确认 | `/ttttt` | 仅手动 |
| [**wwwww**](./skills/wwwww/SKILL.md) | 执行 openspec change 全流程：Worktree 隔离 → 实现自测 → 验收 → 存档 → 提交 → rebase + merge --ff-only 合并 | `/wwwww` | 仅手动 |
| [**yyyyy**](./skills/yyyyy/SKILL.md) | 验收进行中的变更（spec 变更或 openspec change，自动判断）：文档代码对齐、测试全过，通过后存档清理 | `/yyyyy` | 仅手动 |
| [**code-review-expert**](./skills/code-review-expert/SKILL.md) | 资深架构师级 Code Review 与 Spec 验收：六维度审查（契约与环境、架构设计、健壮性与并发、可观测性、性能成本、向后兼容），仅报 ≥80% 置信度问题并分 Blocker/Major/Minor 三档 | `/code-review-expert` | 仅手动 |
| [**change-linter**](./skills/change-linter/SKILL.md) | 改动 Python / Shell 后判定并执行 L1–L4 分级后置校验，并如实报告工具缺失导致的未校验缺口 | `/change-linter` | 可自动触发 |

**仅手动** = 只能由你在 `/` 菜单里主动调用；**可自动触发** = 模型也会在合适时机自己调用（同时仍可手动调用）。

> ⚠️ **ttttt** 能向真实终端发键、经 ssh 操作远程机器：破坏性命令必须先经你确认，密码类交互有专门约束（绝不拼进命令行、拒绝 `sudo -S`），详见其 SKILL.md 的「安全防线」。

## 批量安装工具链（可选）

[`templates/install-prompt.md`](./templates/install-prompt.md) 是一份**整段粘贴给 AI 编程工具**的安装提示词：它先问你把技能绑到哪些 agent，再按条目分别用 `npx skills add`（skill 类）、MCP 配置（MCP 类）、包管理器（系统工具类）安装，不会把 skill 装成 MCP。除本仓库的 7 个技能外，还覆盖几套常用第三方 skill、MCP server 与 CLI 工具（repomix、chrome-devtools、anysearch、codegraph、agent-browser、rtk 等）——用不到的条目删掉即可。

## 更新与卸载

技能是**快照式安装**，装完不会自动跟随本仓库更新，需要手动刷新：

```bash
npx skills list                  # 列出已安装的技能及其 agent
npx skills update -g -y          # 升级全局全部技能到最新
npx skills update ccccc -g -y    # 只升级指定的几个
npx skills update -p -y          # 只升级项目级（在项目目录内执行）
npx skills remove <技能名>        # 卸载（按提示选择作用域）
```

只想刷新单个技能、或 `update` 报失败时，重跑一次 `npx skills add` 即可——幂等覆盖，不会产生重复。

## 采用同款全局规范（可选）

[`templates/AGENTS.md`](./templates/AGENTS.md) 是作者在用的全局工程规范（与 `change-linter` 技能联动），可整份采用。想要同款：把它复制到 `~/.zcode/AGENTS.md`（或项目根 `AGENTS.md`），再按项目裁剪；用作项目级时按 [agents.md](https://agents.md) 标准建议补构建/测试命令、项目约定与安全注意事项；**已有配置时先对比合并，不要直接覆盖**——全局规范是每个人自己的东西，技能不会也不会替你装它。

## 依赖工具

`change-linter` 需要下列工具（用 uv 安装）。缺失时该技能会**报告缺口并询问一次**是否安装，**不会静默安装**：

```bash
uv tool install ruff --upgrade
uv tool install ty --upgrade
uv tool install mypy --upgrade
uv tool install pyright --upgrade
uv tool install pyrefly --upgrade
uv tool install shellcheck-py   # 可选：.sh 静态检查增强（shellcheck 官方二进制的 PyPI 再打包）
```

若连 `uv` 自身都没有，需要先自行安装 uv，否则无法补齐工具链。其余 6 个技能不依赖这些工具。

## 贡献

新增或修改技能前先读 [CONTRIBUTING.md](./CONTRIBUTING.md)，改完必须通过自检与测试：

```bash
uv run --no-project scripts/validate.py     # 结构、frontmatter、README 索引一致性
uv run --no-project tests/test_verify.py    # change-linter 与自检脚本的回归用例
uv run --no-project tests/test_install.py   # 安装行为回归（需 npx + 网络，离线自动跳过）
```

仓库变更按日记录在 [CHANGELOG.md](./CHANGELOG.md)。

## License

[MIT](./LICENSE)
