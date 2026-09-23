# 更新日志

本项目所有可见变更按时间倒序记录于此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
条目以 `HH:MM` 标注提交时间，未提交的改动先归入「未发布」，随当次提交并入日期段落。

## 2026-09-23

- **23:29** `feat:` change-linter 新增两个与 L1–L4 **正交**的轴：`--security`（bandit 源码安全扫描）与 `--deps`（pip-audit 依赖漏洞审计）。两轴由**改动的性质**触发而非类型检查深度，因此不并入级别编号——做成 L5 会让「只改了一个依赖」也被迫跑 `mypy --strict`。①**bandit 只把本次改动的 `.py` 当 target**（不传 `-r .`），存量噪音在源头就不进报告；代价是 `.bandit` 配置不自动加载，改用 `--severity-level medium --confidence-level medium` 兜住低危噪音。②**pip-audit 必须能确定依赖来源**（`uv.lock`/`poetry.lock`/`Pipfile.lock` → `--locked`，否则 `requirements*.txt` → `-r`），两者都没有就报未校验并退 1；**绝不裸跑**——实测裸跑只收集到它自己隔离环境的 28 个包，并输出「没发现漏洞」的假绿。③两者都**解析 JSON 自行裁决、不看退出码**（bandit 命中即非零；pip-audit 的非零同时表示「有漏洞」与「跑挂了」）。④给 `CheckOutcome` 加 `gap` 通道，把「这条校验没跑成」与「失败」分开，未真正执行的校验一律不算通过。⑤报告头写成 `后置校验 L1 + S + D`；只改 lock 文件、没有 `.py`/`.sh` 改动时写 `后置校验 D`（此时 L 级什么都没跑，不能写成「L1 通过」）。pip-audit 解析不出 JSON 时按输出内容区分「环境被删文件」（实测杀软会误杀 `cyclonedx/model/vulnerability.py`，它在导入链上，删了连 `-f json` 都起不来）与「离线跑不通」；**认不出原因只列可能项，不硬猜**。SKILL.md 与 references/lint-levels.md 同步：新增「两个正交轴」节、工具安装两条、缺失策略两行、用法两例。

- **23:29** `test:` change-linter 用例 **23 → 37**（新增 14 例）。黑盒 4 例验证两轴的接线与报告口径：`--security --deps` 时报告头为 `后置校验 L1 + S + D`；有 `.py` 但无 lock / requirements 时打印「依赖轴未校验」并退 1；**只改 `uv.lock`、没有任何 `.py`/`.sh` 改动时写 `后置校验 D` 且不得出现 `后置校验 L1`**；只有 `.sh` 改动时 `--security` 报「安全轴未校验」。进程内 10 例验证判定口径：bandit 命中渲染出 `a.py:3 B324`、清白通过、**自身报错原样保留不被改写成「通过」**；`_extract_json` 容噪（前后夹日志仍能取出对象）；pip-audit 漏洞 ID 去重（同一 ID 重复列出是常态，原样打印会把一行撑成一屏）、清白通过、离线记 `gap`、**环境被删文件与网络问题分开提示**、认不出原因时只列可能项不硬猜；断言 `RUFF_SELECT` 含 `B`/`UP`/`DTZ`。两轴的真实链路另用 PATH shim 转发 `uvx` 与装好后的真工具各跑通一次（bandit 报 B324、pip-audit 报 requests/idna/urllib3 三个依赖漏洞）。

- **23:29** `docs:` ①**code-review-expert 新增第七维度「逻辑正确性」**：静默错值、条件与分支（布尔取反 / `and`·`or` 混用 / `<` 与 `<=` / 缺 `else`）、金额与时间（float 记账、裸 `datetime.utcnow()`）、边界计数（off-by-one、分页窗口）、早退与短路。这一类**静态工具全抓不到**，而此前定级里早有「正确性 → Blocker」、维度清单里却没有对应行，是既有的不对称；六维度顺延为七维度，README / SKILL.md / 自检段共 4 处字样同步。②散点补齐：维度一加「依赖与包的真实性」（核 import / 方法 / 包是否真实存在，幻觉包名会被抢注投毒）与「测试全绿 ≠ 正确 + 大量 mock 是依赖过复杂的信号」；维度三（架构）加「分层归属与 Fit」与「副作用边界」（构造函数碰外部系统会向上传染，让所有下游被迫 mock）；维度四安全性补缺授权检查 / 不安全默认 / `eval`·`exec` 用于外部输入，并发补共享可变状态与锁序死锁，基础规范补语义重复。③**AGENTS §3 新增「形式优先序」**（数据/查表 > 纯函数 > 类；组合优于继承；副作用收在最外层薄壳 `functional core, imperative shell`；构造函数不碰外部系统；类只在需要持有状态或表与纯函数表达不了时才用），吸收 *Functionally Zen* 的 2/4/5/6 四条信条。④**处理它与既有条目的冲突**——这一步比新增本身更重要：原 §5「新增逻辑通过类/接口扩展」是竞争条款，改为「分支变体禁止 if/else 堆砌；具体形式按「形式优先序」选」，让选形只剩 §3 一个裁决者；code-review-expert 的 SOLID 两处限定为「只针对已有的类」，防止 reviewer 机械套 SOLID 反过来要求建类。全仓复扫后只剩 4 处提到类/接口，各管一段（选形 / 建不建文件 / 跨模块边界 / 禁令与豁免）。⑤**新增 `.gitattributes`**（`* text=auto eol=lf`）：仓库内容本来就已是 23/23 LF，但靠的是本机 system 级 `core.autocrlf=true`，换台机器（`autocrlf` 未设或 `false`）就会把 CRLF 提交进 index；加它把这件事从「看机器脸色」变成「仓库自己说了算」。⑥README 同步：技能表两行 + 「依赖工具」补 `bandit` / `pip-audit` 两条（此前后者漏了）。

## 2026-09-22

- **22:58** `docs:` 模板 AGENTS 二轮瘦身：**4988 → 4869 字符（相对原版 5563 累计 −12.5%；字节 12963 → 11311）**。①§8 检索优先级由「章首句 + 三条编号列表」并成一行优先级链（`sg` > `rg` > `repomix`），一节省 116 字符——删掉的只是 ast-grep 的 `-l <lang> -p '<pattern>'` 参数、`（定义/调用/实现）` 与配置后缀名这类同类举例，三个工具的用途与 repomix 的禁用范围全在；②§3 求简优先序去掉 ①②③ 圈码与「写新代码前按序判定」「以上皆否才」，顺序改由箭头链表达；③§1「歧义不私自定」、§4「验证分工」、§7 代码审查、§9 默认选型、§10「压缩边界」「措辞一致」「代码不重贴」逐条收措辞。**本轮把三条先前被判「可删」、复核后确认有独有增量的内容接回**：（a）「单文件 typo / 格式调整不走此流程，直接执行」补进 §4「复杂任务四步法」末尾——原「先理解再修改」的另一半是分级门槛，此前文件只写了大改动要怎样、从未写小改动豁免，模型遇到一个 typo 也会走四步法；（b）「思考聚焦」压成关键词链 `读既有实现与约定 → 推演边界与失败模式 → 评估影响面` 恢复为 §4 首条，「推演边界与失败模式」无任何其它条目覆盖；（c）金句「为简化辩护的散文本身即复杂度回流」接回 §10「求简不丢信息」尾部——它是规则本身（防止写散文论证自己省字省得对），不是理由。核对结论：**规则条目零净丢失**（顶层条目 51 → 47，差额构成是 §8 三条并成一行散文 −3、删「先理解再修改」条 −1，其内容由上述 +22 字承载），限定词、否定词、阈值与四个 Windows 触发词全部在位；剩余删减仅同类举例约 178 字符。本地副本 `~/.dsh/AGENTS.md`（符号链接 → 云盘 `CLAUDE.md`）同文同步。

- **22:40** `docs:` 模板 AGENTS 逐条确认后瘦身：**5563 → 4988 字符（−10.3%），字节 12963 → 11528**。做法是先给出每条规则的「原始 / 改后 / 改动原因」对照，再由作者逐条裁定砍、缩或不动。**砍 2 条**：①「先理解再修改」——已被「歧义不私自定」（歧义先问）与「复杂任务四步法」（先理清逻辑）覆盖，同一件事第三次出现；②「思考聚焦」——描述模型内部思考本就在做的事，无可执行约束，属纯 no-op。**缩 19 条**：§1「歧义不私自定」「授权分级」（五条命令举例砍到 `rm -rf` / `git push --force` 两条代表）「代做边界」与远程执行四个子条；§2「pip install 探测」「全局工具复用」；§3「求简优先序」（七级阶梯的「是否覆盖」重复三遍已收敛）「未读不改」；§4「严禁主观臆断」「验证分工」；§5「强制后置校验」「提交格式」；§6 未请求的抽象（末句改为引用 §5 的「跨模块注入」，保留限定语「不在此限」）；§7 代码审查；§8 检索优先级章首句与 ast-grep 条（删 pattern 示例，保留 `$VAR` / `$$$` 语义）；§10「压缩边界」「措辞一致」「代码不重贴」。**余 27 条经确认原样不动**，四个真踩坑触发词（`两次解析` / `脏文件名` / `假 exit 1` / `非登录 shell`）与「否定与限定词不得省略，省掉即反转语义」这条元规则全留。方法论结论：逐条确认版最终只 −10%，整篇重写版能到 −27%——差的那 17% 不是措辞水分，而是被作者确认保留的规则本身的体积。本地副本 `~/.dsh/AGENTS.md`（符号链接 → 云盘 `CLAUDE.md`）同文同步。

## 2026-09-21

- **22:45** `feat:` change-linter 三项增强 + 全链有效性实测：①新增 C901 复杂度检查（L1 起随 ruff 跑，独立成 `complexity` 记录）——**本次改动碰过的函数卡 8，同一次改动没碰过的存量函数放宽到 12**，区间取自 `git diff -U0 HEAD`，未跟踪文件整file算新代码，取不到 diff 时按存量口径；阈值判定在脚本内完成，不交给 ruff 退出码，通过时也打印「存量容忍 N 处」。②`bash` 探测加 Git for Windows 常见路径回退（`%ProgramFiles%\Git\bin\bash.exe` 等）——本机 Git 装了但 bin 不在 PATH，此前所有 `.sh` 改动都是「无法校验」，shellcheck 白装。③`--files` 加存在性预检，不再把 `E902 系统找不到指定的文件` 抛给用户。测试补 5 个用例（复杂度三态、`--files` 预检、bash 回退探测），`tests/test_verify.py` 23 例全绿，其中 shellcheck 用例从「永久 skip」变为真跑。新规则首先抓到脚本自身：`verify.py` 的 `_changed_line_ranges`（10）与 `_finalize_complexity`（9）超限，已拆出 `_spans_from_diff` / `_file_spans` / `_parse_complexity_findings` / `_classify_complexity` 四个小函数，复检 0 处新代码超限。
- **22:45** `docs:` ccccc 提交粒度条由「不必拆太细」改为可判据的宁粗勿碎（同需求/同主题合成一次，判据是 reviewer 能否一次看懂，默认一个需求一次提交）；AGENTS §1「禁静默决策」补弹窗规则（弹窗只放一行内的简短选项，背景与细节先写进对话正文）。本地副本同文同步。
- **22:07** `docs:` 模板 AGENTS 的「远程执行」由 434 字符长句改为触发式规则并压缩到 5 条判据（388 字符）：**指令含引号 / 反斜杠 / 换行 / `$` / 反引号 / `&&`·`|`·重定向 → 一律改走脚本文件**，只有无上述字符的单行只读命令可直接发；保留行尾 LF、退出码先取、非登录 shell 三条判据，删除 Cygwin 吞 CR 与 `MSYS_NO_PATHCONV` 等历史表述。§3 增「写文件行尾」（Python 写仓库文件须显式 `newline="\n"` 或 `write_bytes`，实测默认在 Windows 会把整文件翻成 CRLF）；§4 增「读文件编码」（PS 5.1 裸 `Get-Content` 按 ANSI 解码 UTF-8 无 BOM 会乱码吞行）。本地副本（`~/.dsh/AGENTS.md` 符号链接指向的 `CLAUDE.md`）同文同步，两份 SHA256 一致。

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
