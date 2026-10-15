# ProContract：取证与继任授权的基础修复

2026-10-15。修复分支：`fix/procontract-evidence-succession-20261015`；基线：`5e2ca724361f055f394d6d765f8055e8e662c604`。原工作区保持原状，改动位于独立 worktree。

原始三实例实跑中，hexyl 和 tig 的继任授权失败，任务没有完成接续协议，评分器因此拒绝评分；未评分不等于零分。三个实例还都在 probe 失败后签发了 `sealed=0 / min_qualified=100` 的合同。原始结果见[诊断报告](/data/ProContract/live-diagnostic-20261015/REPORT.md)。

## 修复内容

1. **在最终 prompt 上统一计算输入预算。** 96,000 字节包含策略、各段标签和截断标记。先保留任务请求的预算，再分配文档、help 和 observations 的剩余空间；UTF-8 截断不会突破字节上限。超过固定策略预算时返回 `InputBudget`，不再误报为模型输出错误。
2. **保证传输后正文仍然完整。** 原生验证发现旧的 7KB context 分片会被 Core 的 1,000 approximate-token 限制再次截短，连策略正文也可能丢失。分片改为 3,500 字节，并通过实际 `AdditionalContextUserFragment` 渲染器验证拼回后的字节一致性。没有扩大 Core 的通用上下文限制。
3. **显式处理取证失败。** 探索、封存阶段的 schema 分别限制最多 30、300 条。对解析、数量错误最多纠正重试一次；传输、超时和输入预算错误不重试。参考观察失败保留阶段和原因。失败不能转成空成功结果；适用 sealed 验证时，少于最低 qualified 数量的 suite 不能进入 Issue。只有 reference、没有 candidate 的 review 路径不受该数量门槛限制。
4. **把完整授权原文与 reviewer 摘录分开。** Host 在首次接收完整文本时保留原文，绑定同一来源、版本和接收顺序，并随 checkpoint 和 rollback 一起保存或删除。rollout 的原文哈希支持重启回放；内容被截短或改变后，旧哈希不能证明完整性。继任上下文使用完整用户文本，保持后续限制和 verified answers 的顺序；派发前、启动后再次检查授权版本，并保留取消及退出等待。
5. **区分准入拒绝与未知执行生命周期。** 启动前拒绝记录为 `successor_rejected`，清理 pending，但不退还已花费名额。无法确认执行者已退出的错误继续保持 pending。评分器仍要求预留数与实际 rollout 数一致，本次没有降低评分准入要求。

相关实现：[prober.rs](../../codex-rs/ext/pro-contract/src/workers/prober.rs)、[packet.rs](../../codex-rs/ext/pro-contract/src/workers/packet.rs)、[runtime.rs](../../codex-rs/ext/pro-contract/src/controller/runtime.rs)、[successor.rs](../../codex-rs/ext/pro-contract/src/controller/successor.rs)、[授权捕获](../../codex-rs/core/src/context_manager/history_user_authorization.rs)、[保留上下文](../../codex-rs/history/src/retained_context.rs)。

## 验证

304 项 Rust 测试通过：ProContract 131，history 37，Guardian context 44，Core history 92。覆盖超量输出、空 suite、失败恢复上限、实际分片渲染、Unicode、原文回放、篡改或缩短副本、compaction、checkpoint、rollback、后续限制、取消等待及拒绝后的预算记账。

另外执行了两项真实 native/app-server/Docker 集成测试；模型响应由 localhost 固定脚本提供，没有调用真实模型服务。

| 场景 | 关键输入 | 结果 |
|---|---|---|
| 长请求、超大文档、超量探索 | 5,040 字节任务；116,100 字节文档；首次 exploration 返回 125 条 | 一次纠正重试后取得 suite；同一合同从 Defeat 经一个真实 successor 到 Support；pending 为空 |
| 普通请求接续 | 短任务，review-only，无 reference/candidate sealed 验证 | 同一合同从 Defeat 经一个真实 successor 到 Support；pending 为空 |

长场景实际发给模型的 probe 正文经分片重组为 **95,996–95,997 字节**，未发生 Core 的二次截断。该集成 fixture 使用 `/bin/echo` 和文件断言，配置 sealed 最低数量为 **4**，实际签发 4 条；它验证机制，不模拟 ProgramBench 的最低 100 条或功能覆盖。两例账本的命令序列都是 `issue → propose → defeat → propose → support`，每例只预留、启动一个 successor。一个 successor 发出两次模型 HTTP 请求，不能把请求数当作执行者数量。

所有最终原生事件中的 harness SHA-256 均与本次构建的 Codex 二进制一致。未改动的 `codex-code-mode-host` 和 store helper 来自已核对的基线 release；[包清单](/data/ProContract/repair-validation-20261015/package-manifest.json)保存二进制和源代码差异哈希。测试镜像固定为 `python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`，运行容器关闭网络。

验证过程中的缺少配套程序、跨分片字段断言，以及二次截断的发现均保留在独立中间产物中；最终结果只取 `native-long` 和 `native-short`。最终证据：[native-results.json](/data/ProContract/repair-validation-20261015/native-results.json)、[离线审计脚本](/data/ProContract/repair-validation-20261015/audit.py)、[长场景日志](/data/ProContract/repair-validation-20261015/native-long.log)、[短场景日志](/data/ProContract/repair-validation-20261015/native-short.log)。测试容器和专用 Docker 均已退出。

## 边界

数量可行性是 Issue 的必要条件，不证明 suite 的覆盖充分或 reference 行为稳定。正式验证仍须检查 qualified 数量、成功路径比例和候选行为。

原文存储仍遵守现有有界保留规则：原文超过序列化单记录预算、先前限制被驱逐、历史来源缺失、非文本原文无法完整恢复或 verified answers 不完整时，继任仍拒绝。旧的 incomplete checkpoint 不会凭初始 intake 或相似文本被追认完整。

本轮完成源码修复与机制回归，没有重新运行三道 ProgramBench 的完整真实模型解题和官方评分，也没有 RSI 干预。因此不产生新的 ProgramBench 分数或 RSI 收益结论。
