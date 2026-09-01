# ProContract-Next:四公理核与受治继任 RSI 原型(设计稿)

日期:2026-09-01
状态:设计稿,待 principal 审阅
证据基础:`~/findings.md`(opencode/codex 双实现深度核查,2026-09-01)

---

## 0. 升华的出发点:核查告诉了我们什么

三代谱系(Python Harness → opencode TS → codex Rust)收敛出一个不变的本质:

> 执行者不可自证完成;只有确定性权威可认定状态转移;被接受的废止恢复责任。

同时留下三个未消化的事实:

1. **v7 四格实验**:ProContract 外壳单独为负(-4.55pp),execution policy 单独弱正(+1.34pp/+61% token),**外壳×policy 交互为正**(+3.42pp 且更省)。Entr 拆分:policy 单独 +26.62pp。
   → **能力住在 policy 里;外壳是纯完整性开销,除非它喂养 policy 学习回路。**
2. **两边共享的最大债**:执行语义(ReplayPolicy argv/timeout)泄入规范核;证据缺世界坐标(Amber:Python 3.12 replay 过、3.10 评测语法错误)。
   → **证据是世界索引的:E(subject, policy, environment, evaluator, time)。**
3. **方法论教训反复兑现**:内部 assurance 全过 ≠ OOD 效用;手工 held-out 小套件屡次选错官方最优;预注册 gate 失败后残留默认路径("Known impurity")。
   → **冻结裁决 + gate 物理生效,不能靠纪律。**

因此升华方向不是"更强的外壳",而是:**把外壳缩到公理最小(完整性),把全部能力放进可学习的 policy 平面(智能),用外壳自身的废止公理为 policy 继任提供回滚(RSI 安全性)。**

---

> **落地状态(2026-09-01,branch procontract-next):** §1.1 U2 三层机械化已全部落地
> (institution crate 拆分、宪法元测试、62 变体类型化拒绝);U1 落地两个子项:
> replay 证据环境坐标(digest 必填 + 可选 pin)与 capture_policy_hash 入主体坐标。
> U1 的 ε 全抽象(EvidencePolicy 取代结构化 ReplayPolicy)、U3 薄外壳、U4 与 §2/§4.2
> 为后续计划。

## 1. ProContract⁰:四公理核

现有 codex 版有 9-10 条宪法不变量。可压缩为四条公理,其余全部是推论或 well-formedness:

| 公理 | 内容 | 吸收的原不变量 |
|---|---|---|
| **A1 垄断(Monopoly)** | 义务的公认状态只经 `transition` 改变;每类命令绑定一个权威角色;executor 角色没有任何结算动词 | I1 拒绝保持、I3 剩余权、I4 不可自证 |
| **A2 精确(Exactness)** | 每条认定性命令绑定完整坐标向量,失配即拒;fencing = 坐标精确性在时间维上的表现 | I5 坐标完整、I8 依赖不可变、I9 修订围栏 |
| **A3 守恒(Conservation)** | outstanding 只能经授权 discharge(证据在精确坐标上支持,且机械证据不可兼任 attestation)或 release 终结;quiet 是"作用域内无 outstanding"的导出谓词 | I2 义务守恒、I6 证据从属、I10 frontier-quiet |
| **A4 废止(Defeasance)** | 被接受的 defeater 在坐标 c 上原子地撤销 c 及其活跃依赖闭包的当前支持、恢复有主的 outstanding;历史只追加 | I7 责任闭包 |

一句话内核逐句映射:*Executors propose*(A1 否认 executor 动词);*evidence supports*(A2 + 世界索引证据);*authority settles*(A3);*accepted defeat restores responsibility*(A4)。

**Kernel 准入测试保留**(codex 的做法):任何要进核的概念必须给出"移除它的最短反例"。四公理各自的反例已在两仓库实验日志中真实出现过。

### 1.1 结构升级(每条对应一个已核查的缺陷)

**U1. 证据坐标抽象化,replay 请出 kernel。**
Kernel 只认识:

```
ε = (contract, revision, specHash, subjectHash,
     evidencePolicyHash, capturePolicyHash,
     environmentDigest, evaluatorDigest,
     evidenceHash, verdict ∈ {support, defeat}, authority)
```

Replay、评测容器、人审 rubric、证明器全部是 L2 验证器适配器,产出对 `evidencePolicyHash` 的有限证词。claim class 声明必需的坐标分量;环境敏感的 claim 缺 `environmentDigest` 匹配/桥接证书即不可 discharge。
→ 同时清偿:codex 的 ReplayPolicy-in-kernel 债、capture limits 不入坐标债、replay 环境盲债;opencode 的 replay 策略入 specHash 债。Amber 教训从"事故记录"升格为宪法条款。

**U2. 纯度三层机械化。**
- 编译期:kernel crate/package 依赖恰为 serde+sha2(codex 现状是 sqlx/tempfile 同 crate,纯度靠纪律);
- 测试期:宪法元测试(import 白名单 + 禁词表,移植 opencode 的最漂亮一手);
- 审计期:类型化拒绝枚举 + 全射测试(每个拒绝变体 ↦ 恰一条公理或 well-formedness 类),把 codex "64 处自由字符串逐行人肉对账"变成机器事实。

**U3. 薄外壳定律(Thin Envelope,v7 的经验教训成为设计定律)。**
外壳在执行者上下文内的运行时足迹趋近于零:一次性 brief + 准入时命名一次行动 affordances;预算在模型之下强制;无背诵、无倒计时。全部制度力量集中在三个边界:准入(admission)、效果门(effect gate)、结算(settlement)。**外壳的每一个上下文 token 都必须自证其存在**——因为 v7 证明了外壳主效应为负。

**U4. 宿主耦合 = 单个泛化钩子。**
沿 codex 的 ExecutionAdmission 路线:宿主 core 不认识 ProContract 之名。第三替换测试(换 harness 不改 reducer)成为编译事实。

### 1.2 分层(最终形态)

```
L0 结算核        纯代数,四公理,~500 行,编译期封闭
L1 机构          原子账本 + hash 链 + actor 认证 + quiet 快照
L2 验证器适配器   replay / 评测容器 / 人审 / 证明器 → 有限证词(ε 坐标)
L3 执行适配器     session / lease / budget / admission(薄外壳)
L4 policy 平面   执行策略、选择器、编译器 —— 全部可变、可学习、可继任
```

---

## 2. 本质 RSI 原型:受治继任回路(Governed Succession Loop)

### 2.1 中心命题(从 v7 数据升华)

**能力在 policy,完整性在 settlement;RSI = 在冻结裁决下的 policy 继任治理。**

外壳的价值主张从"让单次任务更好"改写为"让 policy 学习可安全复利":外壳生产可归因的证据 → 证据喂养 policy 选择 → policy 提升能力 → 外壳保证提升可回滚。外壳只通过它使能的学习回路收回自己的成本。交互项(envelope×policy)不再是尴尬的实验注脚,而是机制本身。

### 2.2 对象(全部复用四公理核,不加新 kernel 状态)

- **Policy**:内容寻址工件,带谱系(训练 cohort、生成器 ID、候选版本)。
- **Evaluation Contract**:普通合约,claim = "候选 P 在冻结 manifest M 下优于在任者 P*"。只能由配对运行证据在精确坐标(manifest hash、任务集 hash、复制数、环境摘要)上 discharge。**预注册尾部回归 gate 是 M 的一部分**;gate 失败 → Evaluation 不 discharge → 晋升物理不可能(不存在 opencode "Known impurity" 式的残留路径,因为晋升只读已 discharge 的 Evaluation Contract)。
- **Selection Contract**:继任行为本身。requires 边指向候选 policy 工件与其 Evaluation Contract;principal 批准。discharge = 候选成为未来合约的在任者。
- **在任者登记簿(incumbent register)**:系统内唯一可变指针。只被已 discharge 的 Selection Contract 改变;全序(签发序);原子换。

### 2.3 回路(四权分立:生成/评估/选择/结算)

```
生成器(任意智能,可自改)
    → 候选 policy(内容寻址、冻结)
冻结裁决器(确定性脚本,即 pro-contract-rsi.ts 的一般化)
    → 预注册 manifest 下的配对运行 → verdict
Evaluation Contract discharge(kernel,ε 坐标绑定)
Selection Contract(principal 批准)
    → register 原子更替
未来合约经 requires 边继承在任 policy
后续负证据 → challenge → 依赖闭包自动撤销 Selection 的支持
    → register 回滚至前任
```

**关键洞察:RSI 安全性不需要任何新机制——回滚就是 A4 废止公理在在任者层的实例。** 晋升后在新任务上回归的 policy 被 challenge,依赖闭包撤销 Selection Contract 的支持,登记簿回滚。同一条公理,抬升一层。

**Meta^n 截断**:选择器与生成器自身也是 policy,受同一制度管辖——第 n 层 policy 由第 n-1 层的冻结 gate 晋升;不动点是 kernel + 根评测器 + principal。**一切可变物可自我改进;一切规范物不可自我修订。** 纯自授权的继任不继承前任的"授权"语义——它开启新的规范政权(codex succession 规范的要点),因此 principal 批准不可省略。

### 2.4 "本质"的证明义务:每个组件都有已观测的反例

对 RSI 设计自身应用 kernel 准入测试——移除任一组件,两仓库的实验日志里已有现成反例:

| 移除 | 已观测的反例 |
|---|---|
| 冻结 manifest | held-out 小套件屡次选错官方最优(HTMLq/Hex/Jq);gate-shopping |
| 配对运行/复制 | v7 每格单候选、基线事后生成 → 只能自评 development 级 |
| ε 坐标绑定 | Amber:环境换掉,同 hash 可执行文件的证据静默失效 |
| 废止闭包 | 晋升后的回归无法回滚(ripsecrets:单个负样本删掉有效检测器 -28pp 却无制度记录) |
| principal 批准 | Rhit:worker 重命名 root reference 顶替,整个 campaign 作废 |
| 内容寻址谱系 | codex /tmp 权威工件流失,v5 证据永久不可升级为 confirmation |
| gate 物理生效 | opencode 四任务 confirmation 失败但被拒 policy 残留默认路径 |

这就是"本质"的含义:**再删一件东西,安全性或可改进性就断,而且断法在日志里已经发生过。**

### 2.5 可证伪协议(让"效果"可以被正当主张)

- 主假设(预注册):ProContract 内,selector-on vs selector-off(policy 继承),带复制,不相交 confirmation 集。(因为 v7 说价值在交互项。)
- 次假设:薄外壳预算——外壳上下文 token ≤ 任务 token 的固定百分比。
- 全部报告 calibration 与 confirmation 两层;gate 失败物理阻断默认路径采纳。

---

## 3. 落地路线(三案)

**方案 A(推荐)**:以 codex 原生版为基座演化——kernel 已最接近极小。改造:crate 拆分(U2 编译期封闭)、类型化拒绝枚举、ε 坐标泛化(U1,删 ReplayPolicy 出 kernel);移植 opencode 的宪法元测试与确定性裁决器(rsi.ts → Rust);opencode 保留为第二 harness,兑现协议自身的第 7 条交付项(证明非单 harness 专属)。
- 优点:改动集中在已最小的核上;保留 64 守卫对账传统。
- 代价:opencode 侧要跟进 ε 坐标以保持互操作。

**方案 B(终态)**:独立中立 kernel 仓库(便携 plane + daemon),两个 harness 均为适配器。opencode 规范自己写着这是终态("portable kernel with a durable daemon")。
- 优点:最干净;第三替换测试天然成立。
- 代价:迁移成本最高,短期减慢实验节奏。

**方案 C(最小增量)**:不动两个 kernel,只在 opencode 上先建 RSI 平面(rsi.ts、contract policy 配置已存在)。
- 优点:最快出实验数据。
- 代价:kernel 债原样保留,ε 坐标缺失使 Amber 类失效仍可能静默发生。

推荐 **A,以 B 为声明终态**:核足够小,A 会自然收敛到 B。

---

## 4. 外部证据:Recuris(arXiv 2608.24876)的批判性取舍

Recuris = 递归经验-工作记忆演化:M_k = (E 技能记忆, W 工作状态 schema, ρ 调用策略, C 完成谓词);任务内 propose→check→commit 的受核状态更新;结构化轨迹 Γ;固定定位器把失败归属到四组件之一;固定 gate 在 dev 集上裁决补丁;有界递归(基座模型/Meta-Agent/定位器/gate 固定,只演化 M_k)。

### 4.1 独立汇聚(增强 ProContract 信心的部分)

- **微观不可自证**:Recuris 的核心机制"仅当观察支持时才把目标从 pending 转为 done——用显式完成谓词而非模型自身的成功声明",就是 A1 公理在工作记忆尺度上的重现。
- **有界递归 = 我们的 Meta^n 截断**:它的"演化仅发生在外部化记忆层,规范组件固定"与"一切可变物可自我改进、一切规范物不可自我修订"是同一原则的两次独立发现。
- **最强的汇聚证据**:两个独立 Meta-Agent 实现(Claude Code vs DeepSeek Harness)演化收敛到相同组件族——**授权跟踪、执行门控、反升级技能**。被学习出来的 policy 自发重新发明了 ProContract 的制度原语。这支持"制度原语是吸引子"的判断。
- **WM≫EM 消融**(仅 WM +23.9 vs 仅 EM +2.0):紧凑受核工作状态才是长视界增益来源,技能堆积几乎无效。

### 4.2 采纳(四项,全部落在 L2/L4,kernel 零改动)

1. **结构化尝试轨迹(attempt trace)作为诊断证据**。Recuris:失败定位准确率 结果单独 13.0% → 原始轨迹 37.0% → 结构化轨迹 64.8%;"非事件(未调用的技能)仅在机制事件中可观察"。ProContract 的账本只记制度事件,不记 propose→check→commit 链。采纳:定义内容寻址的尝试轨迹工件 schema(状态、affordance 调用与**非调用**、动作、观察、提议更新、核验裁决、提交更新),由 L3 生成、hash 绑定进 handoff,作为 L4 继任回路生成器的失败归因输入。**取舍**:轨迹是 executor 产物(不可信),永远只是 policy 平面的诊断证据,绝不是结算证据,绝不进 kernel。
2. **policy 的组件类型化**。Recuris 把失败归属到 z∈{E,W,ρ,C} 并做组件级补丁。采纳:policy 工件携带组件分类,Evaluation manifest 可按组件 gate 补丁。**取舍**:组件分类是 policy 平面词汇,不进 kernel;且 ProContract 补上 Recuris 缺的东西——principal 批准 + 废止回滚(Recuris 自认"gate 仅验证即时退化,长期积累漂移未考虑";废止闭包正是那个答案)。
3. **薄外壳定律修正:thin ≠ empty**。v7 说外壳主效应为负;Recuris 说*状态接地的紧凑上下文*强烈为正(最长任务 +32.2 点)。综合:外壳的上下文足迹应是**受核状态投影,零叙事**——outstanding 义务、当前 standing、被接受的挑战摘要,以紧凑结构呈现;不是"什么都不给",更不是背诵条款。
4. **非事件记录**:executor 从未调用 report_blocked/revision 等 affordance 本身入轨迹,成本近零、归因价值高。

### 4.3 拒绝(取舍的"舍")

- **不引入其信任锚**:Recuris 没有结算制度——"done"仍是 harness 内部的,gate 决策自托管,无 principal、无对既往晋升的废止。其被接纳补丁曾破坏 9.5% 已解决 dev 任务(重跑同包 25.9%)。它的演化回路只能作为 L4 的一个生成器策略,不能替代 L0-L2。
- **不做任务内演化**:其单任务适应学习贡献仅 +2.3 点(p=0.774),重试预算解释了全部收益——与 ProContract"不允许合约内自评循环"的立场一致。
- **不接受 dev-集-即-gate**:10-14 任务的 dev 集 + 已知破坏率,弱于 ProContract 的预注册复制 confirmation + 尾部回归 gate。学习出的完成谓词(C 类补丁)不得核证自己 cohort 的晋升——Evaluation 的证据政策固定在 n-1 层/根评测器。

## 5. 声明纪律(自我约束)

本设计的每一条主张标注:
- 四公理核的压缩性:**设计主张**,需 refinement 证明(TLA+ 或参考模型)佐证"其余不变量可导出";
- 薄外壳定律:**由 v7 单实验(development 级)动机**,需预注册复制确认;
- RSI 回路安全性:**结构主张**(公理实例化),不主张能力必然提升;
- "本质性"(2.4 表):基于已观测反例的**必要性论证**,不是充分性证明。

不主张:验证器构念效度、对抗性物理非绕过、无条件活性、开放式递归改进。
