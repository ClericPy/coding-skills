# 更新日志

本项目所有可见变更按时间倒序记录于此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
条目以 `HH:MM` 标注提交时间，未提交的改动先归入「未发布」，随当次提交并入日期段落。

## 2026-09-20

- **21:02** `docs:` install-prompt 三处补强：①开头加「先查已装清单、已装且能用的条目直接跳过」，执行要求第 6 条改为可执行的「先查再装」检查命令；②第 0 步补 DSH 说明——它不是 `--agent` 合法取值（实测 `-a dsh` 报 `Invalid agents: dsh`），DSH 固定读 `~/.agents/skills`，对应 CLI 的 `universal` 键（实测 `-a universal` 落点 `.agents/skills`），或走多 agent 布局的实体目录；③第 5 步 chrome-devtools-mcp 改为「只装不启用」（DSH 用 `disabled: true`，无禁用开关的 harness 写到备用位置，真启用时优先 `--slim`），执行要求新增第 7 条。

- **00:55** `docs:` 全仓去掉 ZCode 提及：README（简介、英文段、Quickstart 安装示例改用 `<agent>` 占位并给出 claude-code / codex / opencode 取值、安装落点、AGENTS.md 落点）、CONTRIBUTING（校验器扩展字段说明、脚本调用约定注释）、install-prompt（AnySearch 回退处改为「有些 harness」）、CHANGELOG 历史条目改写；测试夹具改用 `-a claude-code` 与 `.claude/skills`（`claude-code` 为 CLI 认的键，安装回归 6 例实测通过）。功能性回退变量 `ZCODE_SKILL_DIR` 按决定保留，仅去掉其解释文字里的 ZCode 表述。
- **00:52** `test:` 修掉本机长期红的 `test_shellcheck_runs_when_available`：它只判 shellcheck 是否存在，而 L1 的 `.sh` 分支以 bash 为准，本机缺 bash 时根本不进入 shellcheck，断言必然落空——补上 bash 前置并说明理由。
- **00:32** `docs:` yyyyy 收敛为验收闸门：新增「边界」节（只判能不能收/能不能发，需要深审时提示用户手动 `/code-review-expert`，不调用其它技能，不翻历史旧账），第 2 条收窄为「只拦明显问题」；新增六条闸门检查（证据锚定、配套同步、依赖与锁文件、发布面、静默破坏类疑点不得默默放过、测试与 linter 报过的不重复挑），总结须写明覆盖/跳过/待确认；description 与 README 技能表同步。
- **00:21** `docs:` code-review-expert 吸收外部开源 CR 工具的评审纪律（仅借鉴工程判断，文本与示例均自研、无逐字引用）：四维度扩为六维度（新增「性能与资源成本」「兼容性与行为变更」，维度一补依赖锁文件 / CI 权限 / 配置漂移），每个维度补「不报」豁免；门禁补四条口径（受保护主题不适用证据不全即丢弃、先落实事实来源、低价值≠错误、不重复静态工具结论）；流程补只评新增行 / 默认不读的文件 / 语义分组 / 大改动先风险定位（≥50 行单文件或 ≥100 行一组）/ 超预算受控截断须显式声明；定级补线上兼容破坏 Blocker、性能与依赖 Major、受保护主题五类清单与「不可验证≠错误」。
- **00:12** `docs:` install-prompt 第 6 步补 DSH 的变量引用写法与两个实测坑：`~/.dsh/cordis.patch.yml` 用 ``Authorization: !!js "`Bearer ${process.env.ANYSEARCH_TOKEN}`"``（外层双引号必须保留，漏掉会让整个 patch 层解析失败、该层所有 MCP 行一起消失）；先设变量再重启 dsh（运行中热重载只会算出 `Bearer undefined`）；验收不能用 shell echo（DSH 按 `/KEY|PASSWORD|SECRET|TOKEN/i` 从子进程擦除这类变量），改用 `dsh --profile web --dump-config` 搜不到 `as_sk_` 加实际搜一次，写坏了用 `--dump-default-config` 诊断；变量名统一为 `ANYSEARCH_TOKEN`。

## 2026-09-19

- **23:46** `docs:` install-prompt 第 6 步（AnySearch）改为「先试环境变量、不支持再退回明文」：补 Claude Code `${VAR}`（未导出且无默认值会解析失败）/ Codex `bearer_token_env_var`、`env_http_headers` / OpenCode `{env:VAR}` 三种写法，明文回退时要求告知「配置文件含密钥、别提交 git、收紧权限」，并给匿名模式出口与 `mcp list` 验证步骤；执行要求第 3 条同步。
- **23:39** `docs:` install-prompt 的 agent-browser 改为「CLI + skill」两段安装（npm/brew/cargo 装 CLI，`npx skills add vercel-labs/agent-browser` 装配套 skill），删除 `agent-browser mcp` 启动段与执行要求 MCP 清单中的该项；分类总览、执行要求类型说明同步。README 工具链清单保留 agent-browser。

## 2026-09-17

- **22:20** `docs:` install-prompt 默认绑定 agent 定为 claude-code / codex / opencode（opencode 经 CLI 注册表核实为合法键）。
- **22:16** `fix:` change-linter 修复 per-file-ignores 假阳性：校验子进程改用配置所在目录为工作目录并传相对路径（ruff 按相对工作目录匹配豁免规则，绝对路径 + cwd 偏移会让 `tests/**` 之类豁免静默失效）；新增回归用例覆盖「项目外调用」与「子目录调用」两场景；lint-levels.md 补行为说明。
- **22:23** `docs:` 纠正 README 安装落点说明（此前误称全局安装都落 `~/.agents/skills/`）：命令式 `-g -a <agent>` 落在 agent 目录，交互式/多 agent 才走通用目录 + 链接布局；补 skills.sh 收录 404 说明；CONTRIBUTING 补 CHANGELOG 条目格式（日期段 + HH:MM + 前缀）。
- **21:51** `docs:` 模板再次同步作者全局规范（4862 → 5450 字符）：新增「求简优先序」（YAGNI→复用→标准库→原生→已装依赖→一行→最小实现）、「Bug 修复追根因」（先 grep 调用者、共享路径单点修复）、「验证分工」补最小可运行自检要求、「严格禁止」补禁无边界抽象条；细化推荐标注规则、授权提交流程措辞、CR 授权表述与「求简不丢信息」的删解释原则。
- **21:51** `docs:` README 补三块内容——「批量安装工具链」（install-prompt 独立成节）、「更新与卸载」（list/update/remove 生命周期命令 + 快照式安装说明）、安装落点说明（实体在 `~/.agents/skills/`、agent 目录为 JUNCTION，无需开发者模式）；英文段补升级/卸载一行。修正 install-prompt 第 10 步：`update` 只认技能名不认仓库 slug（实测原写法静默无操作、退出码 0），并补技能清单。
- **21:43** `docs:` 新增 `templates/install-prompt.md`（批量安装技能与工具链的提示词，可整段粘贴给 agent）；README/CONTRIBUTING 索引同步。

## 2026-09-14

- **21:53** `docs:` 模板同步作者全局规范最新版（4338 → 4862 字符）：新增「指令优先」「压缩边界」「措辞一致」，重写授权分级/代做边界/远程执行与输出规范，去除全部 `§` 交叉引用；`@RTK.md` 为本机 include，分发版不收录。
- **20:26** `docs:` 模板与全局规范瘦身并优化「远程执行」条：改为「本地脚本直送（`tr -d '\r'` 去 CRLF）+ 跨终端 MSYS 路径改写提示」；权限红线/输出规范/搜索优先级压缩措辞，两文件各省 288 字符。
- **20:09** `fix:` change-linter 不重复跑测试：分工段明确本技能只做静态分级校验、不执行测试套件；汇报契约改为已跑过的测试直接引用结论、不得重跑，未跑过才运行必要用例。
- **00:49** `docs:` 模板收窄两处过度请示（权限红线补豁免、四步法补连续执行出口）；删除头部定位注，正文零元话语、整份复制即用；README 采纳指引补项目级使用要点。

## 2026-09-13

- **21:04** `docs:` 新增 CHANGELOG.md 并纳入贡献 checklist；模板 §7 降级为调用 CR 技能即授权分级执行；code-review-expert 输出契约改为按档位给修复建议。
- **19:32** `docs:` ccccc 改为「调用即授权」，模板提交红线同步降级（本地 commit 可在用户发起的提交流程中代执行）。
- **19:26** `docs:` 修订 6 个技能的安全红线与 frontmatter：ttttt 增加发键确认纪律与临时脚本通道，wwwww 明确变基冲突「先自主裁决、拿不准才问人」语义，code-review-expert 明确预授权生效边界，全部手动技能 description 补 manual-only 标注，frontmatter 增补 `compatibility` / `argument-hint` / `allowed-tools` 字段。
- **19:26** `feat:` change-linter 校验能力增强：新增 `--project-scope` 全项目类型检查、项目 ruff 配置优先（存在时不再套用默认参数）、shellcheck 集成（存在才跑）、已删除文件不再送检、中文文件名修复；新增对应回归用例。
- **19:26** `docs:` 模板「未读不改」补冲突重读规则、CONTRIBUTING 校验流程与字段表修订、README 补英文段落与依赖工具说明。
- **01:20** `feat:` 迁移 6 个斜杠命令（ccccc / ppppp / ttttt / wwwww / yyyyy 及 rrrrr 并入 yyyyy）为仅手动调用的技能。
- **01:20** `feat:` 新增 change-linter 技能：L1–L4 分级后置校验脚本 `verify.py`（纯标准库，git 自动发现改动文件，工具缺失显式降级）。
- **01:20** `feat:` 新增 code-review-expert 技能：四维度审查清单 + Blocker/Major/Minor 三档定级锚点，≥80% 置信度门禁。
- **01:20** `docs:` 重写 README（安装矩阵、技能索引、依赖工具）、新增 CONTRIBUTING 与 `templates/`（SKILL.md 骨架 + AGENTS.md 示例）。
- **01:20** `test:` 新增 `scripts/validate.py` 仓库自检与 `tests/test_install.py` 安装行为回归（字节级一致性、调用方式保留、幂等）。

## 2026-09-12

- **20:51** Initial commit：仓库初始化。
