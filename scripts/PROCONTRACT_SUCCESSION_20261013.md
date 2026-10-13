# 同一责任，新的执行 session

后续实测补充：下面的短任务机制测试通过，不代表真实 benchmark 接续已经跑通。
2026-10-13 全量首轮暴露了长指令摘录导致的启动拒绝与验收证据缺口，见
[全量故障复盘](PROCONTRACT_SWEEP_RETRO_20261013.md)。历史测试 receipt 不回写为失败或成功推广证明。

## 原则

`did_not_pass` 是候选交付失败，不是责任解除。执行会话可以替换，原始任务、
合同身份、验收条件、失败产物和总授权不能因此重置。新会话的价值是重新判断
失败假设，而不是把同一份 transcript 再跑一遍。

```text
原始任务 / 原始预算 → Issue（一次）
  → executor A → 冻结候选 A → 独立验证 → Defeat
  → 原子预留 successor 名额
  → 新会话 B：原始要求 + 当前用户约束 + 最近失败事实 + 剩余预算
       判断假设 / 设计辨别实验 / 继续修复或重写任务文件
  → 确认 B 已停止 → 冻结候选 B → 同一合同再次验证
  → Support，或继续交接，或明确记录预算/基础设施阻塞
```

Support 仍不是自动 Discharge。模型总结“完成”、session 退出和责任结清保持区分。
重新实现不意味着清空项目；runtime 不执行 reset、删除未知文件或覆盖历史产物。

## 实现位置

- `controller/succession_budget.rs`：在原始 intake 建立 deadline 与有限名额；
  reservation 在推理前原子落盘。session IDs、失败摘要、计数留在原账本。
- `pro-contract-store/src/store/ledger.rs::compare_exchange_record`：并发竞争者不能
  覆盖已有 reservation。重启时未确认生命周期的 pending 不重放、不退款。
- `controller/successor.rs`：使用 Core `spawn_internal_session`，不是 fork 旧历史。
  继承父任务的授权、agent budget、模型和容器环境；不加载旧 transcript 或记忆。
  禁止递归 ProContract/collaboration。后台执行不会自动批准额外权限。
- `controller/runtime/succession.rs`：父 runtime 始终拥有合同。新 session 只做执行，
  不能自行签约、改验收或结清；结束后由父 runtime 捕获并检查。
- `controller/decision.rs`：详细 diff 之前列出失败检查索引，明确细节只是例子。
  不再允许最前面的同类症状占满全部反馈；提示保留 stdin/TTY/flag 的成立条件。

每个上下文分片最多 768 UTF-8 bytes，包最多 64,000 bytes；不裁掉原始任务来凑上限。
最近三轮失败产物摘要与反馈进入新会话，执行者自己的总结明确标记为不可信声明。
这提供了可审计的经验继承，不证明模型一定正确吸取了教训，也不是权重训练。

## 边界与停止条件

- 授权 max_sessions 和从初次 intake 开始的绝对 deadline，不随会话更新。
  留出独立检查、review 和 capture 的时间后才允许启动执行。
- 候选明确被 Defeat 才进入自动新会话。验收器无证据、权限问题、错误环境、
  签约失败等不是可伪装成普通失败的信号；它们仍明确阻塞，不能无限重试。
- 两次新会话都交回同一个失败产物时停止无进展重试，责任仍 outstanding。
- 新的父线程输入或停止信号会取消并等待 successor 退出，避免两个执行者写同一工作区。
- 没有原始 grant 的旧合同不能在 resume 时凭空得到新预算。旧实验和 frozen 分支不改写。
- 原始交互回合仍受已有 host 的生命周期控制；这个 deadline 控制自动 succession，
  不把普通用户正在进行的交互回合偷偷变成新的强制超时任务。
- 新执行者是内部 native session。`procodex status` 的 `succeeding` 状态能看到活动
  session；现有 TUI 不会展开它的逐条工具轨迹，不将它冒充 UI 完整升级。

## 使用

新 ProCodex launcher 默认允许最多 3 个后继会话，自动交接窗口为原始 intake 后 4 小时：

```bash
procodex -C /path/to/project --check 'your-test-command'
procodex -C /path/to/project --successor-sessions 2 --task-seconds 7200
procodex -C /path/to/project --successor-sessions 0  # 保留旧的单次同会话 repair
procodex -C /path/to/project status
```

原生 settings 的 `succession` 为显式可选字段；没有该字段的历史 benchmark profile
仍保持旧行为。`procodex_config.configure` 也默认不发 grant，CLI 显式传入。
参数范围：0～16 个后继会话（0 禁用），60～86,400 秒。授权变更不会增加已存在任务的
持久化 grant。review-only 模式仍依赖 reviewer 判断，显式 `--check` 更容易复核。

## 验证范围

控制器回归覆盖多代新会话、一次 Issue、多次 Propose/Defeat、经验继承、恢复后预算
不重置、用户输入取消并等待旧执行者。原生 fixture 使用 localhost scripted provider
和真实 Docker / native executor，要求观察到新 context、旧合同与独立 Support。

这些验证是机制正确性，不是 ProgramBench 净收益。本次不复用已耗尽的 benchmark
预算，不因新机制而重评分旧提交，也不启动付费模型实验。

提交应按持久化 grant、fresh-session capability、runtime 接续、launcher/native fixture
拆为可审查阶段；不把该闭环改动混入用户主工作树已有的 UI/API 改动。
