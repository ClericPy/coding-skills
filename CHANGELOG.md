# 更新日志

本项目所有可见变更按时间倒序记录于此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
条目以 `HH:MM` 标注提交时间，未提交的改动先归入「未发布」，随当次提交并入日期段落。

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
