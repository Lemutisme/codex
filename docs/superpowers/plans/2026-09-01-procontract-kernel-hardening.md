# ProContract Kernel Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ProContract 结算核硬化为"编译期封闭的纯 crate + 机器审计的类型化守卫 + 世界索引证据坐标",清偿核查报告与 specs/pro-contract-next.md 中登记的四项核级债务。

**Architecture:** 拆出 `codex-pro-contract-institution` crate 承载全部不纯代码(sqlx ledger + 文件系统 subject 捕获),使 kernel crate 依赖恰为 serde/serde_json/sha2/thiserror;宪法元测试锁死该边界;`Decision::Rejected { reason }` 线格式不变,内部改为类型化 `Rejection` 枚举并全射映射到四公理;ReplayResult 增加 environment 坐标(Amber 修复),SubjectCoordinate 增加 capture_policy_hash(捕获策略入主体身份)。

**Tech Stack:** Rust(codex-rs workspace,edition/lints 继承 workspace),sqlx/SQLite(仅 institution crate),`just write-app-server-schema` 再生成协议 schema。

**Spec:** `specs/pro-contract-next.md`(§1.1 U1/U2 是本计划范围;§2 RSI 平面与 §4.2 Recuris 采纳项属后续计划,不在本计划内)

## Global Constraints

- 工作目录:worktree `/home/duozhou/codex/.claude/worktrees/procontract-next`,分支 `procontract-next`,基线 f888ee6bd(kernel 12/0 + extension 8/0 全绿)。
- 测试命令一律带 `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target`(复用主 checkout 编译缓存)并加 `--offline`,在 `codex-rs/` 目录下运行。
- `Decision`、`Transition`、`LedgerEvent` 的 serde 线格式**不得改变**(账本与 DTO 兼容);拒绝理由字符串**逐字保留**现状。
- 每个 task 结束时:`cargo test -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension --offline` 必须全绿后才 commit。
- commit message 风格沿用仓库现状:`refactor(pro-contract): ...` / `feat(pro-contract): ...` / `test(pro-contract): ...`,结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 涉及 `app-server-protocol/src/protocol/v2/pro_contract.rs` 的类型变更后,必须运行 `just write-app-server-schema`(等价 `cargo run -p codex-app-server-protocol --bin write_schema_fixtures`)并提交生成物。

---

### Task 1: 拆出 codex-pro-contract-institution crate(编译期纯度)

**Files:**
- Create: `codex-rs/pro-contract-institution/Cargo.toml`
- Create: `codex-rs/pro-contract-institution/src/lib.rs`
- Create: `codex-rs/pro-contract-institution/src/ledger.rs`(自 `pro-contract/src/ledger.rs` 整体移入)
- Create: `codex-rs/pro-contract-institution/src/capture.rs`(自 `pro-contract/src/subject.rs` 移入不纯部分:`SubjectStore`、`Manifest`、`ManifestEntry`、`EntryKind`、`CapturedSubject`、`CaptureLimits`、`SubjectError` 的捕获类变体与全部 fs 逻辑)
- Create: `codex-rs/pro-contract-institution/src/ledger_tests.rs`、`src/capture_tests.rs`(自 `pro-contract/src/{ledger_tests,subject_tests}.rs` 移入)
- Modify: `codex-rs/pro-contract/src/subject.rs`(仅保留纯类型:`ArtifactPath`、`ArtifactSpec`、`SubjectCoordinate` 与新的 `ArtifactPathError`)
- Modify: `codex-rs/pro-contract/src/lib.rs`(删除 ledger/store 导出)
- Modify: `codex-rs/pro-contract/Cargo.toml`(依赖减为 serde/serde_json/sha2/thiserror)
- Modify: `codex-rs/Cargo.toml`(workspace members 增加 `pro-contract-institution`)
- Modify: `codex-rs/ext/pro-contract/Cargo.toml` 与 `src/{lib,replay,tool,principal,tests,replay_integration_tests,binding_tests}.rs` 的 import
- Modify: `codex-rs/app-server/src/request_processors/pro_contract_processor.rs` 的 import(若其使用 Ledger/QuietSnapshot/SubjectStore)

**Interfaces:**
- Consumes: 现有 `codex_pro_contract::{Ledger, LedgerError, LedgerEvent, QuietSnapshot, SubjectStore, CapturedSubject, CaptureLimits, SubjectError}`。
- Produces: 新 crate `codex_pro_contract_institution`,导出上述全部符号;`codex_pro_contract` 保留导出 `ArtifactPath, ArtifactSpec, SubjectCoordinate, ArtifactPathError` 及全部 kernel/spec 符号。`SubjectError` 中 `InvalidArtifactPath`/`DuplicateArtifactPath` 两个变体改由 kernel crate 的 `ArtifactPathError` 承担,institution 的 `SubjectError` 通过 `#[from] ArtifactPathError` 包装。

- [ ] **Step 1: 新建 crate 骨架与 Cargo 接线**

`codex-rs/pro-contract-institution/Cargo.toml`:

```toml
[package]
name = "codex-pro-contract-institution"
version.workspace = true
edition.workspace = true
license.workspace = true

[lib]
name = "codex_pro_contract_institution"
path = "src/lib.rs"
doctest = false

[lints]
workspace = true

[dependencies]
codex-pro-contract = { workspace = true }
ignore = { workspace = true }
serde = { workspace = true, features = ["derive"] }
serde_json = { workspace = true }
sha2 = { workspace = true }
sqlx = { workspace = true }
tempfile = { workspace = true }
thiserror = { workspace = true }

[dev-dependencies]
anyhow = { workspace = true }
pretty_assertions = { workspace = true }
tokio = { workspace = true, features = ["macros", "rt-multi-thread"] }
```

在 `codex-rs/Cargo.toml` 的 `[workspace.members]` 里紧邻 `"pro-contract"` 增加 `"pro-contract-institution"`;在 `[workspace.dependencies]` 里增加 `codex-pro-contract-institution = { path = "pro-contract-institution" }`(参照现有 `codex-pro-contract` 条目的写法)。

- [ ] **Step 2: 移动 ledger.rs(纯机械)**

`git mv pro-contract/src/ledger.rs pro-contract-institution/src/ledger.rs`;同样移动 `ledger_tests.rs`。把文件头的 `use crate::Command;` 等改为 `use codex_pro_contract::Command;`(共 5 个:Command、Decision、State、Transition、transition)。`#[path]` 测试挂载沿用原样。

- [ ] **Step 3: 拆分 subject.rs**

kernel 侧 `pro-contract/src/subject.rs` 保留(逐字保留现有实现):`ArtifactPath`(含 `new`/`as_str`)、`ArtifactSpec`(含 `new`/`paths`)、`SubjectCoordinate`。新增纯错误类型替代原 SubjectError 的前两个变体:

```rust
#[derive(Debug, Error)]
pub enum ArtifactPathError {
    #[error("artifact path is not a normalized relative path: {0}")]
    InvalidArtifactPath(String),
    #[error("artifact paths must be unique")]
    DuplicateArtifactPath,
}
```

`ArtifactPath::new` 与 `ArtifactSpec::new` 的返回类型改为 `Result<_, ArtifactPathError>`。

institution 侧 `pro-contract-institution/src/capture.rs` 移入其余全部:`CaptureLimits`(含 Default)、`CapturedSubject`、`SubjectStore`、`Manifest`、`ManifestEntry`、`EntryKind`、`SubjectError`(删去前两个变体,新增 `#[error(transparent)] Path(#[from] codex_pro_contract::ArtifactPathError)`)、全部捕获/物化逻辑。`subject_tests.rs` 移入并按新路径修 import;其中只测纯类型(ArtifactPath 规范化、ArtifactSpec 去重)的用例留在 kernel crate(新建 `pro-contract/src/subject_tests.rs` 挂载)。

- [ ] **Step 4: 更新两个 crate 的 lib.rs**

`pro-contract/src/lib.rs`:删除 `mod ledger; mod subject;` 中 ledger 行与 `pub use ledger::*`、`pub use subject::{CaptureLimits, CapturedSubject, SubjectError, SubjectStore}` 四行导出;保留并新增 `pub use subject::ArtifactPathError;`。crate 顶部文档注释追加一句:“Impure institution adapters (SQLite ledger, filesystem subject capture) live in `codex-pro-contract-institution`.”

`pro-contract-institution/src/lib.rs`:

```rust
//! Institution adapters for ProContract: the durable SQLite ledger and the
//! filesystem subject store. Impure by design; the pure settlement kernel
//! lives in `codex-pro-contract`.

mod capture;
mod ledger;

pub use capture::CaptureLimits;
pub use capture::CapturedSubject;
pub use capture::SubjectError;
pub use capture::SubjectStore;
pub use ledger::Ledger;
pub use ledger::LedgerError;
pub use ledger::LedgerEvent;
pub use ledger::QuietSnapshot;
```

- [ ] **Step 5: kernel crate 依赖收缩**

`pro-contract/Cargo.toml` `[dependencies]` 收缩为:

```toml
serde = { workspace = true, features = ["derive"] }
serde_json = { workspace = true }
sha2 = { workspace = true }
thiserror = { workspace = true }
```

`[dev-dependencies]` 收缩为 `pretty_assertions`(tokio/anyhow 随 ledger 测试移走;若 kernel_tests 用到则保留 anyhow)。

- [ ] **Step 6: 修复下游 import 并编译**

`ext/pro-contract/Cargo.toml` 增加 `codex-pro-contract-institution = { workspace = true }`;`app-server/Cargo.toml` 同理(若报错才加)。全局替换消费点(已勘察的文件清单):`ext/pro-contract/src/{lib,replay,tool,principal,tests,replay_integration_tests,binding_tests}.rs`、`app-server/src/request_processors/pro_contract_processor.rs` 中 `use codex_pro_contract::{Ledger,LedgerError,LedgerEvent,QuietSnapshot,SubjectStore,CapturedSubject,CaptureLimits,SubjectError}` → `use codex_pro_contract_institution::…`。

Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo check -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension -p codex-app-server --offline`
Expected: 编译通过(以编译器为向导逐个修完残余 import)。

- [ ] **Step 7: 全量测试**

Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo test -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension --offline`
Expected: kernel 7 例 + subject 纯类型若干例、institution(ledger 1 + capture 4)、extension 8 例全部 PASS,总数与基线 20 持平(测试只迁移不删减)。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(pro-contract): split impure institution adapters into codex-pro-contract-institution"
```

---

### Task 2: 宪法元测试(测试期锁死纯度)

**Files:**
- Create: `codex-rs/pro-contract/tests/constitution.rs`

**Interfaces:**
- Consumes: Task 1 之后的 kernel crate 源码布局(`src/{lib,kernel,kernel_validation,spec,subject}.rs`,Task 3 后增加 `rejection.rs`——本测试用目录遍历而非硬编码文件清单,天然覆盖新文件)。
- Produces: 无对外接口;此测试是后续所有 task 的守门员。

- [ ] **Step 1: 写测试(先写,预期立即通过——它锁的是 Task 1 的成果;若失败说明 Task 1 没拆干净)**

```rust
//! Constitutional meta-test: the settlement kernel crate must stay pure.
//! Import whitelist + banned-token scan, in the spirit of the OpenCode
//! implementation's pro-contract-constitution.test.ts.

use std::fs;
use std::path::Path;

const ALLOWED_DEPENDENCIES: [&str; 4] = ["serde", "serde_json", "sha2", "thiserror"];

const BANNED_TOKENS: [&str; 14] = [
    "std::fs",
    "std::io",
    "std::net",
    "std::process",
    "std::thread",
    "std::time",
    "std::env",
    "SystemTime",
    "Instant",
    "tokio",
    "sqlx",
    "tempfile",
    "rand",
    "ignore::",
];

#[test]
fn kernel_dependencies_are_exactly_the_whitelist() {
    let manifest = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"))
        .expect("read Cargo.toml");
    let deps_section = manifest
        .split("[dependencies]")
        .nth(1)
        .expect("dependencies section")
        .split("[dev-dependencies]")
        .next()
        .expect("dependencies body");
    let declared: Vec<&str> = deps_section
        .lines()
        .filter_map(|line| {
            let name = line.split('=').next()?.trim();
            (!name.is_empty() && !name.starts_with('[') && !name.starts_with('#'))
                .then_some(name)
        })
        .collect();
    assert_eq!(declared, ALLOWED_DEPENDENCIES, "kernel dependency drift");
}

#[test]
fn kernel_sources_contain_no_banned_tokens() {
    let src = Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/src"));
    let mut checked = 0;
    for entry in fs::read_dir(src).expect("read src") {
        let path = entry.expect("entry").path();
        if path.extension().is_none_or(|extension| extension != "rs") {
            continue;
        }
        let source = fs::read_to_string(&path).expect("read source");
        for token in BANNED_TOKENS {
            assert!(
                !source.contains(token),
                "banned token `{token}` in {}",
                path.display()
            );
        }
        checked += 1;
    }
    assert!(checked >= 5, "expected kernel sources, found {checked}");
}
```

注意:`kernel_tests.rs` 等 `#[cfg(test)]` 挂载文件也在 `src/` 下、同样被扫描——测试代码同样不许碰 IO,这是有意为之(kernel 测试应是纯断言)。若现有 kernel_tests 里有违禁 token,把该测试改写为纯形式而不是放宽白名单。

- [ ] **Step 2: 运行验证**

Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo test -p codex-pro-contract --offline --test constitution`
Expected: 2 passed。若 FAIL:回 Task 1 补拆,不修改白名单。

- [ ] **Step 3: Commit**

```bash
git add pro-contract/tests/constitution.rs
git commit -m "test(pro-contract): add constitutional purity meta-test"
```

---

### Task 3: 类型化 Rejection 枚举(审计期机械化)

**Files:**
- Create: `codex-rs/pro-contract/src/rejection.rs`
- Modify: `codex-rs/pro-contract/src/kernel.rs`(reject 闭包与全部 64 个调用点)
- Modify: `codex-rs/pro-contract/src/kernel_validation.rs`(`invalid_spec` 返回 `Option<Rejection>`)
- Modify: `codex-rs/pro-contract/src/lib.rs`(导出 `Axiom, RejectionClass, Rejection`)
- Modify: `codex-rs/specs/../specs/pro-contract-implementation.md`(见 Task 6,此处不动文档)

**Interfaces:**
- Consumes: kernel.rs 现有 64 个 `reject("…")` 调用点(逐字理由字符串)。
- Produces: `codex_pro_contract::rejection::{Axiom, RejectionClass, Rejection}`;`Rejection::class(&self) -> RejectionClass`、`Rejection::reason(&self) -> String`(逐字等于旧字符串)。`Decision::Rejected { reason: String }` 线格式不变。

- [ ] **Step 1: 写失败测试(先行)**

在 `rejection.rs` 底部(`#[cfg(test)] mod tests`)写:

```rust
#[test]
fn every_rejection_maps_to_exactly_one_class_and_keeps_legacy_reason() {
    // 黄金字符串表:与 2026-08-31 审计的 kernel 拒绝理由逐字一致。
    let golden: &[(&str, RejectionClass)] = &[
        ("only the issuer may issue the contract", RejectionClass::Constitutional(Axiom::Monopoly)),
        ("issuer and executor must be distinct", RejectionClass::Constitutional(Axiom::Monopoly)),
        ("specification hash does not match", RejectionClass::Constitutional(Axiom::Exactness)),
        // …… 每个变体一行,完整表在 Step 2 的枚举定义中给出
    ];
    for (reason, class) in golden {
        let rejection = Rejection::from_reason_for_test(reason);
        assert_eq!(&rejection.reason(), reason);
        assert_eq!(&rejection.class(), class);
    }
    assert_eq!(golden.len(), Rejection::VARIANT_COUNT);
}
```

Run: `cargo test -p codex-pro-contract rejection --offline` → Expected: FAIL(类型不存在)。

- [ ] **Step 2: 实现 Rejection 枚举(完整变体表)**

`rejection.rs` 核心结构:

```rust
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Axiom {
    Monopoly,     // A1: 认定垄断/角色权威
    Exactness,    // A2: 坐标精确/围栏
    Conservation, // A3: 义务守恒/证据从属
    Defeasance,   // A4: 废止闭包
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RejectionClass {
    Constitutional(Axiom),
    WellFormedness,
    FailClosed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Rejection { /* 每个不同理由一个变体 */ }
```

变体 → (理由字符串, class) 完整映射(**理由逐字来自现 kernel.rs/kernel_validation.rs**;class 判定原则:角色/权威→Monopoly,revision/hash/subject/coordinate/fence→Exactness,结算与证据前置→Conservation,challenge 语义→Defeasance,输入形状→WellFormedness,"state is inconsistent"→FailClosed):

| 变体名 | 理由(逐字) | class |
|---|---|---|
| IssueRequiresIssuer | only the issuer may issue the contract | Monopoly |
| IssuerExecutorDistinct | issuer and executor must be distinct | Monopoly |
| SpecHashMismatch | specification hash does not match | Exactness |
| EmptyIdentity | contract identity and scope must be non-empty | WellFormedness |
| EmptyGoalOrClaim | contract goal and evidence claim must be non-empty | WellFormedness |
| NonPositiveBudget | contract budget and attempt limits must be positive | WellFormedness |
| InvalidAuthorityEntries | contract authority entries must be unique and non-empty | WellFormedness |
| ReplayArtifactsMismatch | replay artifacts must match contract artifacts | Exactness |
| EmptyReplayPolicy | replay policy must not be empty | WellFormedness |
| InvalidReplayChecks | replay checks are invalid | WellFormedness |
| EmptyProtectedHashes | protected replay hashes must be non-empty | WellFormedness |
| ContractExists | contract already exists | Exactness |
| SelfRequirement | contract cannot require itself | Exactness |
| RequirementNotFound | required contract not found | Exactness |
| RequirementCoordinateMismatch | required contract coordinate does not match | Exactness |
| RequirementReleased | required contract was released | Exactness |
| ContractNotFound | contract not found | Exactness |
| InstitutionActorRequired | institution command requires institution actor | Monopoly |
| ChallengeRequiresIssuer | only the issuer may challenge verification | Monopoly |
| ChallengeDuringRevision | verification cannot be challenged while a revision is pending | Exactness |
| NotAwaitingAdjudication | contract is not awaiting adjudication | Defeasance |
| ChallengeCoordinateMismatch | challenge coordinate does not match | Exactness |
| InvalidChallengeEvidence | challenge evidence is invalid | Defeasance |
| ExecutorChallengeNeedsSummary | executor-visible challenge requires a summary | Defeasance |
| SealedChallengeHasSummary | sealed challenge cannot include a summary | Defeasance |
| DependencyStateInconsistent | contract dependency state is inconsistent | FailClosed |
| AlreadySettled | contract is already settled | Conservation |
| NotActiveAtRevision | contract is not active at this revision | Exactness |
| HandoffDuringRevision | handoff is blocked while a revision is pending | Exactness |
| HandoffSpecMismatch | handoff does not match the contract specification | Exactness |
| ReplayEvidenceRequired | replay evidence is required | Conservation |
| ReplayNotConfigured | replay evidence is not configured | Conservation |
| ReplayCoordinateMismatch | replay coordinate does not match | Exactness |
| StateInconsistent | contract state is inconsistent | FailClosed |
| InvalidBlockedReport | blocked report is invalid | WellFormedness |
| PetitionRequiresExecutor | only the executor may petition for revision | Monopoly |
| InvalidPetition | revision petition is invalid | WellFormedness |
| InvalidRevisionCoordinate | proposed revision coordinate is invalid | Exactness |
| NoPendingRevision | no revision petition is pending | Exactness |
| RevisionDecisionMismatch | revision decision coordinate does not match | Exactness |
| RequiredByOutstanding { dependent_id: String } | contract is required by outstanding contract: {dependent_id} | Conservation |
| NotDormantAtRevision | contract is not dormant at this revision | Exactness |
| CannotActivate | contract cannot activate | Exactness |
| TriggerNotReady | contract trigger is not ready | Exactness |
| RequirementNotEvidenced | required contract is not evidenced | Conservation |
| ResumeRequiresIssuer | only the issuer may resume an escalated contract | Monopoly |
| ResumeCoordinateMismatch | resume coordinate does not match | Exactness |
| PendingRevisionFence | contract has a pending revision | Exactness |
| InvalidEscalation | escalation coordinate is invalid | WellFormedness |
| ReleaseRequiresIssuer | only the issuer may release with a reason | Monopoly |
| ReleaseCoordinateMismatch | release coordinate does not match | Exactness |
| NoHandoff | contract has not been handed off | Conservation |
| NotAwaitingVerification | contract is not awaiting verification | Exactness |
| AttestRequiresIssuer | only the issuer may attest settlement | Monopoly |
| AttestationCoordinateMismatch | attestation coordinate does not match | Exactness |
| AttestationExists | attestation already exists | Exactness |
| ReplayDoesNotSupportDischarge | replay evidence does not support discharge | Conservation |
| ReplayCannotDoubleAsAttestation | replay evidence does not support independent discharge | Conservation |

(58 个变体;`VARIANT_COUNT: usize = 58` 常量 + 编译期 match 保证 `class()`/`reason()` total。`from_reason_for_test` 仅 `#[cfg(test)]`,由 golden 表反查。)

`kernel.rs` 改造:`let reject = |rejection: Rejection| Transition { state: state.clone(), decision: Decision::Rejected { reason: rejection.reason() }, command: command.clone() };`,全部 64 个调用点换成对应变体;`invalid_spec` 返回 `Option<Rejection>`;两个 `format!` 调用点换成 `Rejection::RequiredByOutstanding { dependent_id: dependent.id.clone() }`。

- [ ] **Step 3: 补审计守恒测试**

在 `tests/constitution.rs` 追加:

```rust
#[test]
fn rejection_sites_match_the_audited_count() {
    let kernel = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/src/kernel.rs"))
        .expect("read kernel.rs");
    let sites = kernel.matches("reject(").count() - 1; // 减去闭包定义行
    assert_eq!(sites, 64, "rejection site drift: update the audit before the count");
}
```

- [ ] **Step 4: 全量测试并验证理由字符串零漂移**

Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo test -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension --offline`
Expected: 全绿——现有 kernel_tests 断言的是 reason 字符串,零漂移即通过;任何一条失败都说明变体 Display 打错字,修枚举不修测试。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(pro-contract): typed rejection vocabulary mapped to constitutional axioms"
```

---

### Task 4: 证据环境坐标(Amber 修复)

**Files:**
- Modify: `codex-rs/pro-contract/src/spec.rs`(ReplayPolicy)
- Modify: `codex-rs/pro-contract/src/kernel.rs`(ReplayResult、ReportReady、Discharge)
- Modify: `codex-rs/pro-contract/src/rejection.rs`(2 个新变体)
- Modify: `codex-rs/pro-contract/src/kernel_tests.rs`(新用例)
- Modify: `codex-rs/ext/pro-contract/src/replay.rs`(计算 environment digest)
- Modify: `codex-rs/ext/pro-contract/src/{tool,tests,replay_integration_tests}.rs`(构造点)
- Modify: `codex-rs/app-server-protocol/src/protocol/v2/pro_contract.rs`(DTO)+ `just write-app-server-schema`
- Modify: `codex-rs/app-server/src/request_processors/pro_contract_processor.rs`(映射)

**Interfaces:**
- Consumes: Task 3 的 `Rejection`。
- Produces: `ReplayPolicy.environment: Option<String>`(期望摘要;None=记录模式)、`ReplayResult.environment_digest: String`(必填非空)。ext 提供 `pub(crate) fn environment_digest(checks: &[ReplayCheck]) -> String`。新增拒绝变体:`ReplayEnvironmentUnnamed`("replay evidence must name its environment", Conservation)、`ReplayEnvironmentMismatch`("replay environment coordinate does not match", Exactness)。

- [ ] **Step 1: 写失败的 kernel 测试(Amber 反例)**

`kernel_tests.rs` 新增(沿用现有测试的构造 helper):

```rust
#[test]
fn replay_environment_is_a_settlement_coordinate() {
    // policy.environment = Some("env-a") 而 result.environment_digest = "env-b"
    // → ReportReady 拒绝 "replay environment coordinate does not match"。
    // result.environment_digest = "" → 拒绝 "replay evidence must name its environment"。
    // 摘要一致 → 走通 ReportReady 与 Discharge。
}
```

(具体构造复用文件内既有的 spec/draft/issue/activate helper;三个断言分支都要写。)
Run: `cargo test -p codex-pro-contract replay_environment --offline` → Expected: FAIL(字段不存在,编译错)。

- [ ] **Step 2: kernel 实现**

- `spec.rs` `ReplayPolicy` 追加字段 `pub environment: Option<String>`(serde 默认参与序列化——**注意:这改变 spec_hash 的输入空间;旧 JSON 无该字段将 decode 失败,这是有意 fail-closed,迁移属适配器责任**)。
- `kernel.rs` `ReplayResult` 追加 `pub environment_digest: String`。
- ReportReady 的 `(Some(policy), Some(result))` 分支追加:

```rust
if result.environment_digest.is_empty() {
    return reject(Rejection::ReplayEnvironmentUnnamed);
}
if let Some(expected) = &policy.environment
    && &result.environment_digest != expected
{
    return reject(Rejection::ReplayEnvironmentMismatch);
}
```

- Discharge 的 replay 校验块(现 692-705 行)追加相同两条(对 `handoff.replay`)。
- `kernel_validation.rs` `invalid_spec` 追加:`replay.environment` 为 `Some` 时必须非空,否则复用 `InvalidReplayChecks`?不——新增专属变体不必要,用 `EmptyReplayPolicy` 也不对;追加到 `InvalidReplayChecks` 语义不符。做法:`Some("")` 归入新变体 `ReplayEnvironmentUnnamed`(同一字符串语义成立)。

- [ ] **Step 3: 适配器实现**

`ext/pro-contract/src/replay.rs` 增加:

```rust
/// v1 environment digest: OS + arch + best-effort `--version` first line of
/// each distinct check interpreter. Coarse but real; refinement is registered
/// in specs/pro-contract-next.md §1.1 U1.
pub(crate) fn environment_digest(checks: &[ReplayCheck]) -> String {
    use sha2::Digest;
    let mut probes: Vec<String> = checks
        .iter()
        .filter_map(|check| check.argv.first())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .map(|argv0| {
            let output = std::process::Command::new(argv0)
                .arg("--version")
                .output()
                .ok()
                .filter(|output| output.status.success())
                .map(|output| String::from_utf8_lossy(&output.stdout).lines().next().unwrap_or_default().to_string())
                .unwrap_or_default();
            format!("{argv0}={output}")
        })
        .collect();
    probes.sort();
    let manifest = serde_json::json!({
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
        "probes": probes,
    });
    format!("{:x}", sha2::Sha256::digest(manifest.to_string()))
}
```

replay 运行处在构造 `ReplayResult` 时填入 `environment_digest: environment_digest(&policy.checks)`(成功、失败、超时三条路径都要填——负证据同样需要环境坐标)。compiler 侧(`compiler.rs`/`tool.rs` 构造 ReplayPolicy 处)填 `environment: None`(记录模式;pin 是 issuer 的显式选择)。

- [ ] **Step 4: DTO 与 schema**

`app-server-protocol/src/protocol/v2/pro_contract.rs`:`ProContractReplayPolicy` 追加 `pub environment: Option<String>`;若存在 `ProContractReplayResult`/handoff 镜像则追加 `environment_digest`。`pro_contract_processor.rs` 补映射。
Run: `just write-app-server-schema` → 提交生成物。

- [ ] **Step 5: 全量测试**

Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo test -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension -p codex-app-server-protocol --offline`
Expected: 全绿(既有 ext 测试构造 ReplayResult 处按编译错误补 `environment_digest` 字段,用 `environment_digest(&[])` 或字面量)。Task 3 的 site-count 测试同步更新:ReportReady +2、Discharge +2,共 64→68;常量以实际 `grep -c 'reject(' kernel.rs` 为准。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(pro-contract): bind replay evidence to an environment coordinate"
```

---

### Task 5: capture_policy_hash 入主体坐标

**Files:**
- Modify: `codex-rs/pro-contract/src/subject.rs`(SubjectCoordinate)
- Modify: `codex-rs/pro-contract/src/kernel.rs`(ReportReady 非空校验)+ `rejection.rs`(1 个新变体)
- Modify: `codex-rs/pro-contract-institution/src/capture.rs`(计算与 Manifest v3)
- Modify: `codex-rs/ext/pro-contract/src/{tool,tests,replay_integration_tests}.rs` 构造点
- Modify: `codex-rs/app-server-protocol/src/protocol/v2/pro_contract.rs`(ProContractSubject)+ schema 再生成

**Interfaces:**
- Consumes: Task 1 的 capture.rs、Task 3 的 Rejection。
- Produces: `SubjectCoordinate.capture_policy_hash: String`;institution `CaptureLimits::policy_hash(&self) -> String` = sha256 of `{"manifest_version":3,"max_entries":…,"max_normal_file_bytes":…,"max_total_bytes":…,"symlinks":"reject","oversized_normal_files":"skip"}`;Manifest `version: 3` 且含 `capture_policy_hash`。新拒绝变体 `SubjectCapturePolicyUnbound`("subject capture policy is unbound", Exactness)。

- [ ] **Step 1: 失败测试** —— kernel_tests 新增:ReportReady 的 subject `capture_policy_hash` 为空 → 拒绝;institution capture_tests 断言两次同 limits 捕获产生相同 `capture_policy_hash`、改 limits 则变。Run → FAIL(编译错)。
- [ ] **Step 2: 实现** —— 按 Interfaces 所列;`SubjectStore::capture` 在生成 `SubjectCoordinate` 时填入 `self.limits.policy_hash()`,Manifest 序列化含该 hash(参与 subject hash 输入,即坐标绑定是真绑定)。
- [ ] **Step 3: 修复下游构造点与 DTO,schema 再生成,全量测试**(site-count 68→69,以实际 grep 为准)。
- [ ] **Step 4: Commit** `feat(pro-contract): bind capture policy into subject identity`

---

### Task 6: 规范同步与收尾

**Files:**
- Modify: `specs/pro-contract.md`(claim 表:capture policy PARTIAL→IMPLEMENTED(bound);evidence 环境坐标 NOT CLAIMED→PARTIAL(replay 记录+可选 pin);guard taxonomy 段指向 rejection.rs 为机器事实)
- Modify: `specs/pro-contract-implementation.md`(64 行审计表替换为"变体→class 映射以 `pro-contract/src/rejection.rs` 为唯一事实源 + constitution.rs 守卫 site count"说明;保留历史表为附录)
- Modify: `specs/pro-contract-next.md`(§1.1 标注 U2 全部落地、U1 落地环境坐标与 capture hash 两个子项,其余登记为后续)

- [ ] **Step 1: 改三份 spec**(实事求是:只声明已实现的,新的 PARTIAL 边界写明——environment digest 是粗粒度 v1、pin 为记录模式默认关闭)。
- [ ] **Step 2: 终验** —— Run: `CARGO_TARGET_DIR=/home/duozhou/codex/codex-rs/target cargo test -p codex-pro-contract -p codex-pro-contract-institution -p codex-pro-contract-extension -p codex-app-server-protocol --offline` + `cargo clippy -p codex-pro-contract -p codex-pro-contract-institution --offline -- -D warnings`。Expected: 全绿。
- [ ] **Step 3: Commit** `docs(pro-contract): record kernel hardening and evidence coordinates`

---

## 范围外(后续计划,按 specs/pro-contract-next.md)

- ε 全抽象(EvidencePolicy kind/policy_hash 取代结构化 ReplayPolicy 于 kernel)——与 RSI Evaluation 证据一并做,避免两次 DTO 断裂。
- RSI 受治继任回路(Evaluation/Selection Contract 模式 + incumbent register + 确定性裁决器)。
- Recuris 采纳项:尝试轨迹 schema(L3 工件)、受核状态投影(薄外壳)、非事件记录。
