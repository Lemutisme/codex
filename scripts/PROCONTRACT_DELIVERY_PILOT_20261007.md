# Luna-only：从可靠交付到方法与 runtime 自改

## 当前状态与第一小步

基线为 `53b4b010811f1727d93b7b21347e8f81cfa14638`。本轮只用
`gpt-5.6-luna / max`，任务预算仍为 18,000 秒；不启动 Astra。

**A1 已实现的是可选的预算收敛提醒，不是完整 checkpoint 机制，更不是新的 E2E 成绩。**
源码在授权可写目录的独立副本中修改，未改受保护的集成工作树或 Git。
当前 Docker socket 访问被拒绝，因此尚未启动真实模型或评估。

给既有 runner 的 `run` 命令显式增加：

```text
--delivery-reserve-secs 3600 --deadline-secs 18000
```

预留窗口内，Host 最多发送一次小于 1 KiB 的 `turn/steer`，绑定当前 executor 的
`expectedTurnId`。默认 reserve=0 不改变模型上下文。检查／审查阶段不发提醒；
过期不发；错误或超时不重试。RPC 等待不超过剩余预算或 10 秒，队列等待也按剩余时间截断。

`run.json.delivery_budget` 区分未尝试、接收确认、错误和超时。
接收提醒不等于正常 handoff，更不等于验证通过；仍沿用原有 native 状态与外部评分。
该选项是 runner 的显式 `run` 参数，**尚未自动接入 RSI campaign 或 canonical driver**。
不得以为改了 runner 就已启用处理组；正式 driver 必须传参并留存实际加载见证。

一小时窗口是待验证的设计选择，不保证 checks、review 和 repair 的最坏耗时能全部容纳。
既有 hard-deadline interrupt／关闭进程仍可能产生清理尾延迟；本改动不声称解决严格进程终止上限。

## A2：先复用原生证据，再增加能力

下一小步应复用 native capture、CAS manifest、verification event 和 subject binding，
而不是解析 shell 日志推测哪个程序被检查过。

```text
正常 handoff → 固定源码 subject → 私有副本构建和检查
    → subject-bound verification → 预先固定的交付选择 → CAS 导出与原子打包
```

- 原生 verification 外层已经绑定源码；裸 `CheckReceipts` 不足以确定源码身份。
- 明确区分 build-only、public-checked、candidate-tests-checked；缺失检查不能算成功。
- 先实现 `final` 的证据匹配审计，再单独测试 `last_checked_fallback`，不默默改变提交物。
- fallback 只按预授权的公开／自检规则选取，不能用 sealed 或 canonical 分数选版本。
- 记录最终 subject、选中 subject、verification 引用、环境与策略身份、选择规则和 archive hash。
- 同时绑定 evaluator 的启动／终态记录与 package、pins、raw evaluation hash，拒绝不匹配缓存。
- 这保证“交付的是检查过的源码”，不是通用二进制认证；任意 build 命令的产物闭包仍是独立问题。

目前只有 Completed turn 才进入正常 handoff。不能周期性 interrupt，再假定 lane 会自动恢复。
长 turn 内主动 checkpoint 需要独立的 typed 入口、并发语义和预算规则，另拆阶段。

## Luna 诊断实验约束

沿用 fx → cheat → hush 三题已曝光诊断集；不把它们当确认集。
固定各题上轮实际执行的 policy、模型、native binary、任务 prompt、镜像和 canonical evaluator。
这一阶段暂停在线 policy 更新，避免把策略改变与交付机制混在一起。只跑新版处理组；
旧数据只作描述性参照，不将历史对照包装成配对因果实验。

A1 先测正常 handoff、native 终态、提醒是否实际接收、截止尾延迟及完整成本。
A2 再加入最终源码／回执匹配率、未检查修改、checkpoint 时间和选择原因。
两阶段都保留外部质量；更早宣告完成不自动算成功，未完成或检查失败不能重标为通过。
不得在 5 小时外补模型调用完成收尾，不得按隐藏分数重跑或挑产物。

本轮最多三个新任务 episode。学习角色暂不运行；此前三题分数不覆盖本轮结果。
正式启动前必须完成参数贯通与 pinned v6 协议 smoke；离线 fake-server 测试不能代替这一步。
新任务族验证应至少涵盖 CLI 重实现、已有仓库修复与结构化产物生成，分别报告，
不能因为 ProgramBench 三题改善就宣称 general-task 收益。

## B：研究方法自改——比较产生后继的能力

保留通用教训：观测必须能区分假设；修改会使旧检查失效；研究应能撤回归因；
证据不可访问时增加 reviewer 没有帮助；失败尝试与学习成本必须计入预算。
这些先是工程假设，不是已经证明的跨任务增益。

冻结相同的执行策略 E、runtime H、原始观察 O、先验知识 K 和总研究预算 B。
旧方法 M0 与新方法 M1 分别执行 Analyst → Challenger → Researcher，
各产生一个冻结的执行后继，再在相同新任务上配对评估。
方法候选阶段只允许改 `research.md / analyst.md / challenger.md`；
比较后继生产能力时冻结方法，仅允许输出执行策略，不继续无限自改。

每个 trial 使用独立 store/cache namespace，缓存身份包含 method hash 与输入快照。
现有 `analyze()` 按观察覆盖复用结果，不能直接拿它对照同证据上的两个不同方法。
候选数、重试和总成本必须相等约束；失败不可免费重来。
方法-only 版本复用旧执行分数并不能证明方法改善；必须评价它产生的后继。

## C：runtime 自改——先开放一个无采纳权的组件

第一个目标建议是有界状态／证据选择 sidecar：输入固定 schema 的有限观察，输出建议，
由固定 Host 验证并决定是否使用。它不能改 evaluator、预算、访问权限、交付身份或采纳规则。
这是可执行 harness 组件自改，不是 unrestricted binary RSI。

候选代码必须经无凭据 builder、固定工具链和资源限额构建；候选运行环境不得访问
宿主凭据、Docker socket、确认集或权威 ledger。当前 app-server 继承模型凭据的启动方式
不能直接用于候选 binary。哈希链不提供进程隔离。

先固定 E、M 对照 H0/H1，独立核验能力边界，再比较新任务质量与完整成本。
运行 H1 获得真实反馈、再由新系统产生后继，才能验证代码级递归通路。
ProContract 继续管理证据与采纳权；任何候选不得给自己签发成功。

## 离线验证范围

新增行为覆盖：单次 fenced steering、禁用路径、阶段门控、过期与超时、不匹配回执、
实际 runner 的正常完成／拒绝／截止路径，以及真实 request 方法的亚秒级队列等待。
使用 fake app-server／时钟，不执行模型、Docker 或 hidden evaluator。
源码证据绑定和候选 runtime 隔离仍属后续实现，不能从这些测试推导已经完成。
