# ProContract 实现与新实例评测检查点

记录日期：2026-10-17。实现已提交为 `7995605fa94bd3901c4990131df7d392aa6cb8c4`；本检查点只保存评测事实与来源，不改变实现、原始实验或评分资格。

## 已交付实现

保留责任内核，增加逐项检查回执、局部审查、持久化有界宿主动作、反应式 PTY 对话、冻结证据计算与不可续期的计算授权。详见 [PROCONTRACT_WORK.md](../../scripts/PROCONTRACT_WORK.md)。此前通过 240 项 Rust 测试、53 项 Python 回归、12 项真实 pipe/PTY 测试和 7 个使用脚本 provider 的原生集成场景，以及格式、Clippy 和构建检查。这些验证说明所测机制的行为，不保证任意真实任务成功。

## 实际结果与资格

三个任务均使用 GPT-5.6-Luna / max，每题一次模型求解，原生预算 14,400 秒，外部评分预算另计 3,600 秒。最多三个后继共享原始授权；RSI 关闭；冻结证据计算统一开启（8 次、每次最多 30 秒、报告上限 64 KiB）。实际均只有一次 Issue，没有后继求解。

| 任务 | 观察通过数 | 观察分数 | Vals 同题 Luna/max | 资格 |
| --- | ---: | ---: | ---: | --- |
| `parcel-bundler__lightningcss.aa2ed1e` | 1790/2828 | 63.295615% | 61.42% | 原评测有效；4 小时预算中断后的工作区评分，无自然交付 |
| `rust-lang__mdbook.37273ba` | 897/1114 | 80.520646% | 65.08% | 同一冻结产物的独立依赖恢复评测；原评测仍无效 |
| `mookid__diffr.2152742` | 562/606 | 92.739274% | 89.60% | 原评测有效；预算中断；一次人工资源干预 |

原批次有效评分覆盖 2/3，计入单列的恢复评测后为 3/3。Fully Resolved 为 0，Almost Resolved（至少 95%）为 0。上述带不同资格标记的产物宏平均为 78.851845%，Vals 同三题平均为 72.033333%；不能解释为干净自主批次、完整榜单成绩或 ProContract 的因果收益。没有实现零机械错误。

任务在查看对应分数前按固定 SHA-256 顺序选取，排除最近的 hexyl/jplot/tig；历史接触标记仍保留。“新实例”不是整个项目从未接触。没有同期原生 Codex 对照。Vals 的 harness、6 小时预算、动作限制、后端及评测条件未与本次完全对齐。

## 关键故障与已观察边界

1. **执行者普通命令未受完整资源边界保护。** diffr 的错误 Python 探针产生失控输出，已观察 Docker 日志前缀达到 13,158,324,778 字节。模型可见输出虽有上限，底层传输日志仍无上限。清理约 36 GiB 可再生 Cargo 增量缓存后，仅对已核实所属的探针进程组发送 SIGINT；原模型会话和截止时间继续，没有语义反馈或预算续期。须保留人工干预资格。
2. **有工作但没有及时进入独立反馈。** lightningcss、diffr 首轮持续到 4 小时，RPC 终态为 interrupted；原生进程退出 0 不等于任务成功。末次保存 phase=working 不表示仍在运行。冻结诊断配置的 delivery_reserve_secs=0，且无自动交付提示。不能在无对照时认定长首轮由 ProContract 引起。
3. **最坏耗时预留阻止了有余量的继续工作。** mdbook 在约 180.2 分钟自然交付。内部检查耗时 40.507 秒，发现真实候选反例；此时原授权仍余 3,597 秒，但后继准入要求预留 4,260 秒（检查上限 1,800＋审查上限 2,400＋开销 60），因此没有后继。上次检查实耗不能当作未来完整审查的保证。
4. **评测能力预检不完整。** mdbook 两次原评测均退出 0，但缺少声明依赖 bs4，产生 7 个 collection-error 伪条目和 222 个 not_run。735/1121 从未是有效分数，原结果保持 infrastructure_failed。第三次调用是单列恢复：相同提交、相同重建可执行文件、相同评测源码和断言，仅在编译与哈希确认后安装声明的评测依赖。恢复完成仍在原评分窗口内，不能称为一次干净评测。
5. **审计覆盖也是有限的。** 部分私有原始请求 trace 达到 1 GiB tmpfs 上限，观察器报告 unknown/final_observer_failed。常规 rollout、账本、交付与评分证据分别保留；不能声称完整原始请求审计或实际账单。原分析脚本的过窄假设及失败记录保留，修正仅作用于分析。

研究所属的容器、原生进程、观察器挂载和 daemon 已停止；无后续付费求解或评分待办。

## 可复核来源

完整材料位于本机 [/data/ProContract/programbench-new-instances-20261017](/data/ProContract/programbench-new-instances-20261017/REPORT.md)。原始目录不纳入源码仓库；本提交不包含隐藏测试、二进制、密钥或模型原始轨迹。便于搬移后校验的汇总与来源 SHA-256 保存在 [checkpoint JSON](procontract-programbench-checkpoint-20261017.json)。哈希只能识别已有文件，不能代替未保存的原始观察。

- [完整结果报告](/data/ProContract/programbench-new-instances-20261017/REPORT.md)
- [带资格结果](/data/ProContract/programbench-new-instances-20261017/QUALIFIED-RESULTS.json)
- [最终审计](/data/ProContract/programbench-new-instances-20261017/final-audit.json)
- [预算决策](/data/ProContract/programbench-new-instances-20261017/mdbook-budget-decision.json)
- [输出失控事件](/data/ProContract/programbench-new-instances-20261017/RUNAWAY-OUTPUT-INCIDENT.md)
- [mdbook 恢复审计](/data/ProContract/programbench-new-instances-20261017/evaluation-recovery-mdbook/audit.json)

后续设计需分别处理执行资源、可评估进展、授权分配和取证能力。上述事实尚不能证明某一种调度或角色组合提高了求解质量。
