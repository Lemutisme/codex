# 全量 Luna/max 首轮故障复盘：授权完整性不是上下文完整性

记录日期：2026-10-13。本文是实验后追加的研究记录，不修改已封存的协议、代码或结果。
**当前结论：真实接续未跑通；修复尚未实现；不应继续原样扩大试验。**

## 1. 已发生的事实

- 实验：`procontract-succession-full-20261013`，200 个官方实例，仅新版 successor 臂。
- Controller：`d05e1f5a8e4a98b5c342528bf2d4181b4e63eab4`。
- Native：`84f3f1e38b34ff18812c4cac11280288aa4ca38c`。
- Plan SHA256：`b30f3d8d44cdf067353a63d533f69ef5808a00465cbb8d82f77b332752498ace`。
- `gpt-5.6-luna / max`，4 路并发，每题总上限 18,000 秒；研究角色为 0。
- 已启动 5 题，2 题有效评分，3 题基础设施/接续失败；195 题未启动。
- 调度器已 `stopped`，没有存活的本轮任务容器，终态没有 cleanup errors。
  已预留 90,000 秒，未预留 3,510,000 秒；这是预算分配，不是实际耗时或账单。

| 实例 | 官方功能评分 | 合同结果 | 后继预留 / 实际 rollout |
| --- | --- | --- | --- |
| `bensadeh__tailspin.6278437` | 未评分 | `not_verified / no_handoff` | 1 / 0 |
| `jonas__tig.8334123` | 未评分 | `not_verified / no_handoff` | 1 / 0 |
| `sharkdp__hexyl.2e26437` | 884/906 = 97.57% | `not_verified / insufficient_evidence` | 0 / 0 |
| `rs__jplot.2a54bcc` | 400/583 = 68.61% | `not_verified / insufficient_evidence` | 0 / 0 |
| `ogham__dog.721440b` | 未评分 | `not_verified / no_handoff` | 1 / 0 |

两个已评分实例的均值 83.09% **不是全量成绩**。三题失败不填 0，195 题未启动不算失败。
所有五题均未 Support，实际后继执行次数为 0；不能据此宣称接续收益或 RSI 收益。
单臂、无研究角色、无跨题学习，且已有作者历史曝光；也不构成盲测或因果对照。

## 2. 已定位的根因与尚未定位的症状

### A. 接续把受限指令摘录当成了完整授权的唯一来源

三题都在 `Issue → Propose → Defeat → successor reservation` 后报同一错误：

> owner instructions are incomplete; cannot authorize a fresh executor

原始用户任务消息为 4,501 UTF-8 bytes。上游 guardian 的 root-message 上限为
900 个近似 token，保留的是 3,600-byte 的截断摘录，并标记 `complete=false`。
这不是模型总结，也不等于原始授权已经丢失。`successor.rs` 只检查 retained context
的完整性，没有从可审计的原始来源恢复完整指令，因此在创建 child session 之前拒绝。

直接证据：tailspin 的压缩 checkpoint 保存了同一用户消息 ID、3,600-byte 摘录和
`complete=false`；tig 和 dog 没有发生 compaction 也报同一错误。
因此不能把故障归咎于运行太久或 compaction 本身。
三题均只留下一个 pending reservation，没有 successor rollout；预留成功不是执行成功。

**安全检查拒绝不完整授权是正确的，消费方依赖错误才是 bug。** 不能通过删除检查、
把 `complete` 改成 true、缩短任务限制、或简单增大摘要阈值来修复。

### B. 高功能分数没有建立责任契约的证据闭环

hexyl 和 jplot 的 canonical grader 可以评价冻结提交，但内部验收报告均为
`0 of 0 qualified sealed checks`，而支持条件要求至少 100 个合格检查和足够的成功路径。
它们没有被误标为 Support，这一边界保住了；但证据生成到合格检查的链路没有闭合。
目前只确认了零合格检查这一症状，**尚未定位它在生成、装配、执行或资格判定的哪一步**。
不能把外部官方分数回灌为内部证明，更不能降低原验收门槛来追认成功。

## 3. 本质 insight

1. **授权存储与模型上下文必须分离。** 上下文可截断，责任依据不能靠摘要重建。
   需要独立、可审计、有版本/来源身份的完整任务与用户约束；交接时按原始顺序绑定
   最新约束及已验证回复。模型可见投影仍受硬上限约束，不能变成无限历史注入。
   原始 intake 也不能单独取代后续用户修改；无法证明完整性时继续 fail closed。
2. **责任 kernel 要保护“能否证明”，不只保护“不乱宣称”。** 拒绝伪造 Support
   必不可少，但系统还必须有生成有效证据的可达路径。证据不足不是候选已被证伪。
3. **恢复必须按故障归属路由。** 候选被 Defeat 才修候选；证据不足应进入有限的
   证据修复流程；授权缺口应恢复权威来源；生命周期未知必须隔离/停止。
   这些是待实现的恢复策略，不能全部伪装成“再来一个 executor”。
4. **持久化状态不是行为见证。** `reserved`、`started`、`handoff`、`exited`、
   `verified` 应分别留证；已预留但启动前被拒绝，也不同于启动后生命周期未知。
   状态细分不能退款、自动重放或改写这次已经花掉的 reservation。
5. **短 fixture 只证明它覆盖的路径。** “Make answer.txt contain ready.” 的真实
   native/Docker fixture 通过，不能推出普通长度的 benchmark 指令也能交接。
   真正的 E2E 测试应复制真实配置与边界，并见证关键状态转换，而不只是进程存在。
6. **RSI 的对象应是有因果诊断的策略变更。** 这里暴露的是授权传递和证据链问题，
   不是加几段反思提示词能补救的。候选升级应针对明确失效机制、可证伪预测与独立
   回归门槛；本轮没有研究调用、策略采用或后继执行，不能命名为已获益的 TTRL/RSI。

## 4. 修复落点与验收门槛（未完成）

下列 Rust 路径相对于 `codex-rs/`；优先复用既有权威来源 API，不扩张通用 core。

| 问题 | 当前位置 | 修复/验证要求 |
| --- | --- | --- |
| 摘录与授权混用 | `core/src/context_manager/history_user_authorization.rs::record_retained_message`；`core/src/guardian/mod.rs`；`ext/pro-contract/src/controller/successor.rs::run` | 保留上游有界摘录语义；从完整来源建立交接授权，带来源身份、最新修订与完整性校验 |
| 预留与实际启动混淆 | `ext/pro-contract/src/controller/runtime/succession.rs`；`scripts/procontract_succession_binding.py` | 在可行时预检确定性启动条件；分清 admission rejection、已启动和未知退出；仍保留原 deadline、一次 Issue、不可退款 |
| 零合格验收证据 | `ext/pro-contract/src/controller/decision.rs::mechanical_verdict`；`scripts/procontract_benchmark_runner.py::settings` | 沿生成/装配/执行/资格判定定位首个断点，测试完整证据链；不得降低 sealed 门槛或读取官方测试来补证据 |
| 验证与真实配置脱节 | `scripts/test_procodex_native.py`；`scripts/test_procontract_sweep.py` | 使用真实任务长度与 benchmark 配置，强制 Defeat，并观察新 session 真正执行和再次独立验收 |
| 终态可观测性不足 | `scripts/procontract_sweep.py::run` | `supervisor.json` 最后停在 draining、`terminal.json` 才是 stopped；应统一终态并保留首个 fatal，避免后来的失败覆盖首因 |

后续验证应依次通过，不能拿“计划会做”当成已经通过：

- [ ] **免费确定性预检**：真实 4,501-byte 指令、超出摘录阈值的约束、尾部禁止项；
  指令顺序与来源不能丢失，越过硬上限必须显式拒绝，不能静默截断授权。
- [ ] **无模型 native E2E**：强制原候选 Defeat；压缩前/后、新用户约束/取消、恢复后
  分别验证新 session ID、实际 rollout、一次 Issue、不重置预算、确认退出后再捕获。
- [ ] **独立证据链测试**：真实配置下生成并执行非空合格检查；缺证据不 Support，
  evidence repair 与 artifact repair 分开，所有修复仍受明确预算限制。
- [ ] **有限真实 canary**：在明确版本和授权下，见证一次真正的后继执行/交付/再验收，
  不以功能得分代替契约通过，不重跑择优；再决定是否扩大覆盖。
- [ ] **RSI 收益验证另立门槛**：若要声称 RSI，须有可审计策略变更、实际采用见证、
  研究成本与独立对照/前瞻结果；不能拿本次单臂成绩替代。

## 5. 保留有效设计，纠正过度外推

调度器在 tig 首次失败后停止新 admission，等待已启动任务结束并清理；dog 是在
jplot 先完成后、tig 失败之前补入的第五槽，不是故障后的重跑。
一次性预算、无退款、无替换、未评分不填 0、后继 token 不重复累计的边界保留。
但终态机制挡住了进一步损失，不代表接续机制已经成功。

原生短 fixture 确实通过；200 槽假任务 supervisor 测试也确实通过。
组合 Python 预检为 87 通过、6 个旧 study-launch fixture setup errors（缺工作树 debug
store 二进制），不能写成 93 通过；这六项没有执行断言，也不能被当作本次根因证据。
历史验证 receipt 保留不改，本文补充其真实覆盖边界。

## 6. 证据与续跑边界

公开的脱敏标量与私有证据 SHA256 见
[`procontract_sweep_outcome_20261013.json`](procontract_sweep_outcome_20261013.json)。
私有根目录是 `~/run-artifacts/procontract-succession-full-20261013/`；原始 trace、提交、
参考程序、测试内容和凭证都不随本记录上传。摘要只用于匹配留存证据，不代替独立复现。

本次只记录和推送 insight，不更改安装版、冻结 controller、旧结果或预算账本，也不
启动新推理。195 个未启动名额不等于允许抹掉已停止实验后原地续跑；任何后续执行都
必须明确绑定修复版本、剩余/新预算和原失败记录，不能悄悄改计划后当作同一次全量结果。
