# ProContract ON/OFF 最终验证结果（2026-10-12）

**已完成获批的剩余两次运行与评分；一胜一负，稳定净收益未成立。**

本报告接续[早先的交接快照](PROCONTRACT_BRANCHES_20261012.md)。原 sox 失败记录不改写，
只在显式授权的 continuation 中执行原预算里尚未启动的 peco 和 silver_searcher。
机器结果、成本、摘要和离线核验收据见
[procontract_vanilla_results_20261012.json](procontract_vanilla_results_20261012.json)。

## 1. 所有原始名额的结果

ON 为历史固定策略 ProContract；OFF 为相同 native binary 关闭 ProContract 和 RSI。
均为 `gpt-5.6-luna / max`，每题上限 5 小时（执行 4 小时、评分 1 小时）。

| 实例 | ProContract ON | Vanilla/OFF | ON − OFF |
|---|---:|---:|---:|
| sox (`chirlu__sox.42b3557`) | 569/1196 = 47.58% | 凭据过期，无有效分数 | 未知 |
| peco (`peco__peco.4e58dad`) | 891/1215 = 73.33% | 729/1215 = 60.00% | **+13.33 pp** |
| silver_searcher (`ggreer__the_silver_searcher.a61f178`) | 724/1004 = 72.11% | 896/1004 = 89.24% | **−17.13 pp** |

仅对 **2 个有效配对**汇总：

- 任务宏平均：ON **72.72%**，OFF **74.62%**；ON 低 **1.90 pp**。
- 合并用例：ON **1615/2219 = 72.78%**，OFF **1625/2219 = 73.23%**；ON 低 **0.45 pp**。
- 原 3 题的 OFF 宏平均只能界定为 **[49.75%, 83.08%]**，不能确定相对 ON 的方向。
  这只是缺失值的数学边界，不是补分或置信区间。

sox 原运行 2854 秒后发生 `401 Expired Key`；不填 0、不评分其部分产物、不替换或重跑。
两项配对中的 ON 合同终态均为 `did_not_pass`。这些是功能测试结果，
不是合同结清、依赖规则全面合规或 responsibility kernel 效益的认证。

## 2. 完成定义与结论分层

| 判断 | 状态 | 精确含义 |
|---|---|---|
| 本次 continuation 执行与评分 | **完成** | 获批的两项均已评分、进程退出、证据归档 |
| OFF 控制验收 | **PASS** | 两项均观察到 ProContract OFF、无研究、评分存在 |
| 离线产物一致性核验 | **PASS** | 原评分、提交和二进制摘要、配对条件、成本与汇总一致 |
| 原三题全部具有配对分数 | **否** | sox 仍缺失；continuation 的 PASS 不覆盖该缺口 |
| 稳定 ProContract 净收益 | **NOT_ESTABLISHED** | 一胜一负，两个有效配对的宏平均略低 |
| Responsibility kernel / RSI 收益 | **未由本轮证明** | 功能分数不能替代机制证据；本轮没有 RSI 调用 |

因此不是“验证永远未完成”：**获批工作已经完成，收益假设没有被证实。**
也不能从两个异质实例、每组一次的结果反推出 ProContract 普遍有害。

## 3. 实际成本，而非只看相同上限

| 实例 / 模式 | Native 秒数 | 评分秒数 | 两项合计秒数 |
|---|---:|---:|---:|
| peco OFF | 1471 | 1784.62 | 3255.62 |
| peco ON | 2323 | 852.15 | 3175.15 |
| silver_searcher OFF | 2981 | 243.95 | 3224.95 |
| silver_searcher ON | 1767 | 343.62 | 2110.62 |

两个有效配对合计：OFF native **4452 秒**、评分 **2028.58 秒**；
ON native **4090 秒**、评分 **1195.77 秒**。这些是记录的运行组件时间，非账单金额。
Token 明细含执行者与内部 worker，保存在机器结果中；未核实价格，不估算货币成本。

ON 每题还有 2 次内部 worker rollout；OFF 为 0。两个实例中，得分更高的一方均有
更长的 native 时间和更多记录 token；但评分时间并非同方向。这是后续调度诊断线索，
不是“多用时间导致提升”的因果证明，也不是等实际计算量消融。

JSON 另保留既有选择器的成本效用指标及公式。这是离线描述性重算，
不是新在线学习更新，不把它当作原始通过率。

## 4. 可比性与版本边界

- 已核对配对镜像、任务提示、固定 P、native binary、模型/effort、执行上限一致；
  evaluator 与分母沿用原冻结协议。是**跨批次、每题每组一次**的比较。
- OFF 仍有研究用固定 seed P，不是未经配置的 upstream 默认 Codex。
  ON 包含整个 ProContract 工作流，不是只开关一层记账、保持额外计算不变的消融。
- ON 来自 `procontract-rsi-coverage-more-20261011` 的 frozen arms，
  控制器 `dbc0b5241d7f9b5f2d4d6eadfc88259e4027a032`。
- 双方 native 来源 `d434ba042f9391615abca9e16d103192a5e4ef93`，二进制 SHA-256
  `a770ff8b4db51341d7d562e2fdd94789a49d4b7e4e64c11a4425cdb0185473bf`。
- Continuation 控制器 `7ee8b663331fa8ddc470ac1e13a82fd6d0c38d4e` 只增加凭据准入及
  未启动名额的共享预算续跑管理，没有替换 benchmark native。
- 日常推荐 `procontract/recommended` 的 resume 修复版 `4669bf71cd` **不在这次 ON 重测内**。
  本次不升级本机安装，也不改动冻结里程碑。
- 作者历史曝光仍需披露；不称 globally unseen，不作为官方 leaderboard 提交。

## 5. 生命周期闭合与开发教训

原预算与 continuation 共用一份账本：**3 次任务 / 0 次研究 / 54,000 分配秒**。
三个名额分别是失败的 sox、已评分的 peco、已评分的 silver_searcher；剩余名额与
可分配秒数均为 0。这不表示实际花满 54,000 秒；未用完的单次分配不退款重购。

核验时两个研究范围内运行容器均为 0；三个 native 进程均已退出，trace mount 已释放，
私有 trace archive 已保留并校验摘要。进程返回 0 不覆盖 sox 模型回合的鉴权失败。
旧研究的终结记录摘要未变，没有以继续工作为名重写旧 verdict。

这次修复的是：启动前要求已知凭据寿命覆盖完整任务加 300 秒，并将通过校验的同一
凭据交给 native；每题重查。它排除了本轮已知过期风险，不等于实现运行中热轮换，
也无法保证凭据不会被提前撤销。59 个相关 Python 测试及真实 native OFF scripted-provider
凭据注入回归已通过；它们是控制机制测试，不是额外付费模型样本。

下一步研发优先级应是预算内的义务/进展调度与可验证的继续条件，
而不是先扩大 RSI 搜索或声称责任流程自动带来质量提升。要判定该诊断，仍需预先定义
可比较的消融与新的独立预算；**本报告没有启动或承诺任何追加运行。**

原始研究目录名：`procontract-vanilla-control-20261011` 与
`procontract-vanilla-continuation-20261012`。公开分支为
`procontract/vanilla-continuation-20261012`。公开内容仅含代码、汇总、摘要与开发经验，
不含凭据、参考程序、提交内容或原始轨迹。
