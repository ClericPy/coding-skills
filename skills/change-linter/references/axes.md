# 两个正交轴：`--security` 与 `--deps`

L1–L4 是**类型检查深度**的累进梯（取最高适用者）。安全扫描与依赖审计跟类型深度无关，由**改动的性质**触发，因此单独成轴、不编号——否则「只改了一个依赖」也会被要求跑 `mypy --strict`。

**何时读本文件**：本次改动命中任一轴（安全敏感面 / 依赖清单或锁文件）时读；纯 L 级改动不必读。判级与轴判定都在流程第 1 步一次完成。

| 轴 | 触发条件 | 命令 |
| --- | --- | --- |
| **`--security`** | 改动碰了安全敏感面：认证授权 / 输入校验 / 子进程 / 反序列化 / 加密哈希 / 密钥处理 / SQL 拼接 / `eval`·`exec` | `bandit --format json --severity-level medium --confidence-level medium <本次改动的 .py>` |
| **`--deps`** | 依赖清单或锁文件变更：`requirements*.txt` / `pyproject.toml` / `uv.lock` / `poetry.lock` / `Pipfile.lock` | `pip-audit --format json --progress-spinner off --strict` + 依赖来源（见下） |

三条实现口径：

1. **判定不看退出码**：bandit 命中即非零；pip-audit 的非零同时表示「有漏洞」与「跑挂了」。两者都解析 JSON 后自行裁决，与复杂度检查同一原则。
2. **bandit 只扫本次改动的 .py**，不传 `-r .`——全仓扫描会把存量问题一起倒出来，而本技能的契约是「只校验本次改动」。代价是 `.bandit` 配置只在 `-r` 时自动加载，项目级 bandit 配置不生效；`--severity-level medium --confidence-level medium` 用来兜住最常见的低危噪音（如测试文件里的 `B101 assert_used`）。
3. **pip-audit 必须能确定依赖来源**：有 `uv.lock` / `poetry.lock` / `Pipfile.lock` 时用 `--locked <项目目录>`，否则找 `requirements*.txt` 用 `-r`；两者都没有就明确报「未校验」并退 1。**绝不裸跑 pip-audit**——它审计的是自己所在的隔离环境，会输出「没发现漏洞」的假绿（实测裸跑只收集到它自己的 28 个包）。

报告头写成 `后置校验 L2 + S + D`；只有依赖变更、没有 `.py` / `.sh` 改动时写成 `后置校验 D`（此时 L 级其实什么都没跑，故不写）。`--deps` 需要联网（默认查 PyPI 漏洞库），离线或服务不可用时该轴记为**未校验**：不算通过，也不算失败。

安装命令、两轴的调用示例与逐项缺失策略见 `references/lint-levels.md`。