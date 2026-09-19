# 批量安装 AI 技能 / 插件（Skills + MCP）

> 用法：把本文件整段粘贴给 AI 编程工具（claude-code / codex / opencode 等），由它按下面步骤逐项执行。
> 所有命令里出现的 `<AGENTS>` 都来自你第 0 步选出来的智能体列表，多 agent 时展开成多个 `--agent` 参数。

## 分类总览（先分清类型，别装错地方）

| 条目                     | 类型         | 安装方式                        |
| ---------------------- | ---------- | --------------------------- |
| 更新 skills CLI          | 基础工具       | npx                         |
| i-have-adhd            | skill      | `npx skills add`（绑定 agent）  |
| Mattpocock Skills      | skill      | `npx skills add`（绑定 agent）  |
| repomix --mcp          | MCP server | npx 启动，写 MCP 配置             |
| chrome-devtools-mcp    | MCP server | npx 启动，写 MCP 配置             |
| anysearch              | HTTP MCP   | 写 MCP 配置（需 API key）         |
| codegraph              | 工具 + MCP   | 安装脚本 / npm 全局，`serve --mcp` |
| agent-browser          | CLI + skill | npm 全局 / brew / cargo + `npx skills add` |
| rtk                    | 系统工具       | winget / brew / 脚本          |
| ClericPy/coding-skills | skill      | `npx skills add`（绑定 agent）  |
| skill-creator          | skill      | `npx skills add`（绑定 agent）  |
| caveman                | skill      | `npx skills add`（绑定 agent）  |

> 规则：**skill 类一律用 `npx skills add` 安装并绑定 agent，不要写进 MCP 配置，也不要走 winget**；只有上面标了 MCP 的条目才写 MCP 配置；winget 只用于 rtk（且仅当用户在 Windows 且装有 winget）。

---

## 第 0 步：先问我要绑定哪些智能体（必须先做，弹窗/多选框）

在执行任何安装命令之前，**先用弹窗或多选框问我**要把 skills 绑定到哪些智能体：

- **默认勾选**：`claude-code`、`codex`、`opencode`（三个都预选中）。
- 再给一个**自定义输入框**，允许我手填其它智能体名。
- 如果我在自定义框里输入的内容**包含空格**（例如 `cursor opencode`），就按多个 agent 处理，按空格拆开。
- 把最终确认的 agent 列表记为 `AGENTS`（例如 `claude-code codex opencode`）。

**后续所有 `--agent` 命令都按这个列表展开**：只绑一个就写 `--agent opencode`；绑多个就**重复写多个 `--agent`**，例如：

```bash
npx skills add <仓库> --skill <名> --agent opencode --agent claude-code --agent codex -g -y
```

> 不要只绑第一个、不要漏绑、不要把空格串当成一个 agent 名。

---

## 第 1 步：先更新 skills CLI 到最新

**简介**：`skills` 是统一的多智能体 skill 安装器（npx skills）。先自检版本、再全局更新一次已装的 skills，避免后面装到旧版。

```bash
npx -y skills@latest --version
npx skills update -g
```

---

## 第 2 步：i-have-adhd（skill）

**简介**：一个本地 prompt 风格 skill（`ayghri/i-have-adhd`），无需密钥、无需联网，帮容易分心的用户保持专注、减少跑偏，ADHD 友好。属于 skill，用 npx skills 安装并绑定 agent。

```bash
npx skills add ayghri/i-have-adhd --agent <AGENTS> -g -y
```

---

## 第 3 步：Mattpocock Skills（skill）

**简介**：Matt Pocock（Total TypeScript 作者）自用的工程化 skills 集合，把「开工前反复盘问需求（grill-me）、TDD、Bug 诊断、架构重构、code review」等资深工程师习惯固化成可复用命令，主打 TypeScript / 全栈。仓库：<https://github.com/mattpocock/skills>。属于 skill，用 npx skills 安装并绑定 agent。

```bash
npx skills@latest add mattpocock/skills --agent <AGENTS> -g -y
```

> 安装时把 `setup-matt-pocock-skills` 这个子 skill 一并选上；装完后在每个仓库跑一次 `/setup-matt-pocock-skills` 完成初始化。
> 注意：Claude Code 若已用 `claude plugins install mattpocock-skills` 装过，就不要再用 npx skills 装，避免重复。

---

## 第 4 步：Repomix（MCP server）

**简介**：把整个代码仓库打包成单个 XML 文件喂给 LLM 做分析；`--mcp` 让它以 MCP server 常驻运行，AI 可直接调用工具打包本地目录或远程 GitHub 仓库、并在打包结果里检索。仓库：<https://github.com/yamadashy/repomix>。这是 MCP 条目，启动方式如下。

**Windows / macOS / Linux 通用**（推荐 npx 免安装）：

```bash
npx -y repomix --mcp
```

跨平台安装方式（按需二选一）：

```bash
# npm 全局（跨平台）
npm install -g repomix

# macOS 额外可选 brew
brew install repomix
```

写进 MCP 配置（stdio）：

```json
{
  "mcpServers": {
    "repomix": { "command": "npx", "args": ["-y", "repomix", "--mcp"] }
  }
}
```

---

## 第 5 步：chrome-devtools-mcp（MCP server）

**简介**：Google 官方 MCP server（仓库 <https://github.com/ChromeDevTools/chrome-devtools-mcp>），让 AI 驱动真实 Chrome：点击/填表/键盘、DOM 检查、性能 trace、Lighthouse 审计。`--autoConnect` 表示自动连接**已经在运行的** Chrome（144+），复用我当前的登录态、Cookie 和已打开标签页（需先在 Chrome 打开 `chrome://inspect/#remote-debugging` 启用远程调试）。这是 MCP 条目。

**Windows / macOS / Linux 通用**（npx 即可，前置 Node.js LTS + Chrome 144+）：

```bash
npx -y chrome-devtools-mcp@latest --autoConnect
```

写进 MCP 配置：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"]
    }
  }
}
```

---

## 第 6 步：AnySearch MCP（HTTP MCP，需要 API Key）

**简介**：面向 AI Agent 的实时联网搜索 MCP（Web / 金融 / 学术 / 安全 / 法律 / 代码等垂直域 + 网页正文提取）。无 key 也能匿名用、仅速率更低；有 key 走 `Authorization: Bearer`。控制台申请 key：<https://anysearch.com/console/api-keys>。这是 HTTP 远程 MCP，需要弹窗问 key。

**做法**：

1. **弹窗问我要 AnySearch API Key**（形如 `as_sk_...`）。
2. **优先写环境变量引用，不要一上来就写明文**。先在系统里把 key 导出成变量（Windows：`setx ANYSEARCH_API_KEY <key>` 后**新开终端**；macOS / Linux：写 shell profile），再按目标 agent 的语法引用它：
   - **Claude Code**：`.mcp.json` 里 `"Authorization": "Bearer ${ANYSEARCH_API_KEY}"`。支持 `${VAR}` 与 `${VAR:-默认值}`，在 `command` / `args` / `env` / `url` / `headers` 中都会展开；变量没导出又没写默认值时配置会直接解析失败，别把裸 `${VAR}` 留在配置里。
   - **Codex CLI**：`~/.codex/config.toml` 里 `bearer_token_env_var = "ANYSEARCH_API_KEY"`。Codex 没有 `${}` 占位符，靠这个键指定「token 存在哪个变量」；固定值的头走 `http_headers`，值取自环境变量的头走 `env_http_headers`。CLI 只提供 `codex mcp add <名字> --url <url> --bearer-token-env-var ANYSEARCH_API_KEY`，自定义头需手改 config.toml。
   - **OpenCode**：`opencode.json` 里 `"Authorization": "Bearer {env:ANYSEARCH_API_KEY}"`。用 `{env:VAR}` 占位符；注意字段是 `mcp` 段 + `"type": "remote"`，不是 `mcpServers`。
   - 不确定就按 agent 名去查它自己的 MCP 文档，别把一个 agent 的语法套到另一个上。

   顺带一提：`X-Anysearch-Client: mcp/1.0.0` 是固定值、不是密钥，写死即可。

3. **目标 agent 不支持变量引用时退回明文**：例如 ZCode 的 HTTP MCP 只收静态 headers（官方文档未提供占位符展开），此时把真实 key 写进配置，并同时告诉我三件事——这份配置文件从此含密钥、不要提交到 git、权限收紧到本人可读；作用域能选 user 级就别选项目级。我若明确不接受明文，就别写 `Authorization` 头，走匿名模式（无 key 也能用，只是速率更低）。
4. 通用明文写法（仅在上一步回退时使用，`<ANYSEARCH_API_KEY>` 处填真实 key）：

```json
{
  "mcpServers": {
    "anysearch": {
      "type": "http",
      "url": "https://api.anysearch.com/mcp",
      "headers": {
        "Authorization": "Bearer <ANYSEARCH_API_KEY>",
        "X-Anysearch-Client": "mcp/1.0.0"
      }
    }
  }
}
```

Claude Code 等价命令行（想用变量引用就把 header 写成 `Authorization: Bearer ${ANYSEARCH_API_KEY}`，写入后按上面 Claude Code 的展开规则解析）：

```bash
claude mcp add --transport http anysearch https://api.anysearch.com/mcp --scope user --header "Authorization: Bearer <ANYSEARCH_API_KEY>" --header "X-Anysearch-Client: mcp/1.0.0"
```

5. **验证**：装完用 `claude mcp list` / `codex mcp list` / `opencode mcp list` 看 anysearch 是否连上；连不上先确认变量在当前进程里可见（改完环境变量要新开终端或重启 agent），仍不行再退回明文。写出配置不等于装成功。

---

## 第 7 步：codegraph（工具 + MCP）

**简介**：本地优先的代码智能工具，Rust 内核 + Tree-sitter + SQLite 把代码库建成语义知识图谱，让 Claude Code / Cursor / Codex 等 agent「零扫描」理解代码，带文件监听自动增量同步。仓库：<https://github.com/colbymchenry/codegraph>。`serve --mcp` 是以 stdio MCP server 方式把图谱查询能力暴露给 agent。先装工具，再起 MCP。

**安装**：

```powershell
# Windows（PowerShell 脚本，优先）
irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex
```

```bash
# macOS / Linux（官方安装脚本，优先）
curl -fsSL https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.sh | sh
```

```bash
# 跨平台备选（有 Node.js 时）
npm i -g @colbymchenry/codegraph
```

装完初始化 + 起 MCP：

```bash
codegraph install        # 自动往各 agent 写 MCP 配置（在项目里再 codegraph init 建图谱）
codegraph serve --mcp    # 以 stdio MCP server 运行
```

---

## 第 8 步：agent-browser（CLI + skill）

**简介**：Vercel Labs 出品的 AI 浏览器自动化 CLI（Rust 内核，token 高效），后台常驻 Node daemon 驱动 Chrome for Testing，提供 accessibility tree 快照、点击/填表/截图/网络拦截/cookie 管理。仓库：<https://github.com/vercel-labs/agent-browser>。装 CLI，再装配套 skill 教 agent 怎么用它；**不写 MCP 配置**（它自带 `agent-browser mcp` 子命令，本清单不启用）。

**安装 CLI**：

```bash
# 跨平台推荐（npm 全局）
npm install -g agent-browser
agent-browser install        # 首次运行：下载 Chrome for Testing
```

```bash
# macOS 额外可选
brew install agent-browser
```

```bash
# 或 Rust 源码安装
cargo install agent-browser
```

```bash
# Linux 额外系统依赖
agent-browser install --with-deps
```

**安装 skill**（薄发现层，只教 agent 认识 agent-browser 并转去 CLI 取运行时说明）：

```bash
npx skills add vercel-labs/agent-browser --agent <AGENTS> -g -y
```

> 详细用法由 CLI 自己提供：`agent-browser skills get core`（`--full` 带完整命令参考），另有 electron / slack / dogfood 等专项。

---

## 第 9 步：RTK（Rust Token Killer，系统工具）

**简介**：Rust 写的 CLI 代理层，夹在 AI 助手和真实命令之间——AI 照常跑 `git status` / `rg` / `vitest` / `tsc`，RTK 把冗长 stdout/stderr 压缩成机器可读摘要回灌模型，一次会话约省 80% token，不改命令副作用和退出码。仓库：<https://github.com/rtk-ai/rtk>。这是系统工具，不是 skill，也不写 MCP 配置。

**安装**（Windows 优先 winget，仅当用户装有 winget）：

```powershell
# Windows（winget，优先；包名已确认）
winget install rtk-ai.rtk
```

```bash
# macOS / Linux（brew，优先）
brew install rtk-ai/tap/rtk
```

```bash
# 或 macOS / Linux 一键脚本
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
```

```bash
# 或 cargo（必须带 git URL，避免装错同名包）
cargo install --git https://github.com/rtk-ai/rtk --branch master rtk
```

**hook 到 Claude Code**（注册成 PreToolUse hook，让 AI 发起的每条 Bash 命令自动走 RTK 压缩）：

```bash
rtk hook claude
```

> 官方等价命令是 `rtk init`（按项目）或 `rtk init --global`（全局写 settings.json），与 `rtk hook claude` 二选一即可，别重复执行；若 `rtk init` 不认识你的 agent，改用 hook 方式即可。
> 验证：`rtk --version` 能出版本，`rtk gain` 能看到节省仪表盘。

---

## 第 10 步：ClericPy/coding-skills（skill）

**简介**：中文 Python 开发者 ClericPy 个人维护的一组编码 skills 集合，含 7 个技能：`ccccc`（规范化提交）、`ppppp`（提示词调制）、`ttttt`（tmux 终端接管）、`wwwww`（openspec change 全流程）、`yyyyy`（变更验收）、`code-review-expert`（代码审查）、`change-linter`（L1–L4 分级后置校验，唯一可自动触发）。属于 skill，用 npx skills 安装并绑定 agent。

> ⚠️ 两个坑：①`npx skills update` 是**更新**命令，只对已装过的技能生效，**不会首次安装**，没装过要先 `add`；②`update` 只认**技能名**，不认仓库 slug——写 `npx skills update ClericPy/coding-skills -g` 会输出 `No installed skills found matching:` 并**静默无操作**（实测退出码 0）。
> ③个别技能 update 可能报失败，重跑一次 `add` 幂等覆盖即可，不会产生重复。

```bash
# 首次安装（按第 0 步选的 agents 绑定）
npx skills add ClericPy/coding-skills --agent <AGENTS> -g -y

# 之后升级：整表升级，或按技能名单独升级
npx skills update -g -y
npx skills update ccccc change-linter -g -y
```

> 装完用 `npx skills list` 核对清单；技能用途与调用方式见仓库 README 的技能表。

---

## 第 11 步：skill-creator（skill）

**简介**：Anthropic 官方 skills 仓库（<https://github.com/anthropics/skills>）里的 `skill-creator`，引导你走完「明确意图 → 写草稿 → 建测试 → 并行评测 → 按反馈迭代」的完整 skill 开发生命周期，用来创建和改进新 skill。属于 skill，用 npx skills 安装并绑定 agent。

```bash
npx skills add anthropics/skills --skill skill-creator --agent <AGENTS> -g -y
```

---

## 第 12 步：caveman（JuliusBrussee/caveman，skill）

**简介**：热门技能（作者 Julius Brussee），把 AI 回复压缩成「穴居人式」极简短句，砍掉约 65%–75% 输出 token 同时保持技术准确（代码、命令、报错原文不动），自带 `/caveman-commit`、`/caveman-review`、`/caveman-stats`。仓库：<https://github.com/JuliusBrussee/caveman>。属于 skill，用 npx skills 安装并绑定 agent。

```bash
npx skills add JuliusBrussee/caveman --skill caveman --agent <AGENTS> -g -y
```

---

## 执行要求

1. **第 0 步没确认 agent 列表之前，不要执行任何带 `--agent` 的命令。**
2. **类型别搞混**：标为 skill 的条目（i-have-adhd、Mattpocock、ClericPy/coding-skills、skill-creator、caveman、agent-browser）一律 `npx skills add`，**不要**写成 MCP 配置或 winget（agent-browser 另有 CLI，用 npm / brew / cargo 装，同样**不要**写 MCP 配置）；标为 MCP 的条目（repomix、chrome-devtools-mcp、anysearch、codegraph serve --mcp）才写 MCP 配置；winget 只用于 rtk（Windows 且装有 winget 时）。
3. 需要 key 的只有第 6 步 anysearch：**停下来弹窗问我要 key**，拿到后**先按目标 agent 的语法写环境变量引用**，该 agent 不支持（如 ZCode 的静态 headers）才退回明文并告知我「配置文件已含密钥」；任何情况下都不要留着 `<ANYSEARCH_API_KEY>` 占位符就当完成。
4. 每个条目装完用一行输出告诉我结果（成功 / 失败 / 已存在），失败的把报错贴出来，不要静默跳过。
5. 命令以本文件给出的为准，不要自行换成别的工具或参数。
6. 注意有些技能或工具已经安装过了，不要出现重复。
