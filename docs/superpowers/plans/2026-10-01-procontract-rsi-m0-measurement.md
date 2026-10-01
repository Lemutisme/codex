# ProContract RSI M0 (Measurement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every later RSI number trustworthy. That means:
- pinned evaluator epochs;
- labels attached to the exact judged subject;
- immutable experiment events with producer identities;
- sealed pools;
- null sentinels;
- a resumable batch runner;
- an estimand-exact M0 report;
- a gated corpus v0 of about 30 dev Rust instances × {ON, OFF}.

**Architecture:**
- **Storage crate.** The institution's storage primitives (hashing, terms, capture, blobs, ledger) move into a new
  crate, `codex-pro-contract-store`, which does not depend on `codex-core`. The crate gains persisted subjects,
  append-only hash-chained experiment events, and a small `pro-contract-store` CLI.
- **Extension.** It writes its research data (intake, draft, issue, verification) as experiment events carrying
  producer identities, and binds the reviewer identity into certificates.
- **Python scripts.**
  - The runner is generalized to any Rust instance.
  - New scripts pin the evaluator, label materialized subjects, split sealed pools, orchestrate batches, and compute the
    M0 estimands.
  - A fake evaluator makes failure modes testable without Docker or a model.

**Tech Stack:** Rust (sqlx/SQLite, serde, clap, tokio), Python 3.13 stdlib (unittest, sqlite3, tarfile,
concurrent.futures), ProgramBench CLI, Docker.

**Spec:** `docs/superpowers/specs/2026-09-30-procontract-rsi-design.md`. This plan implements §10 (M0) and the parts of
§3.5/§3.6 that M0 needs. The essential spec is `docs/superpowers/specs/2026-09-29-procontract-essential-design.md`.

## Global Constraints

**Containers and data hygiene**
- Never weaken container security. Inference and check containers keep `--network none` and `--user 1000:1000`. Never
  use `--privileged`, `SYS_ADMIN`, `seccomp=unconfined` or `apparmor=unconfined`.
- The model credential and `CODEX_HOME` never enter a container.
- Never open ProgramBench `tests.json`, test blobs or anything under a `tests/test*` path. Pool code reads only the
  `repository`, `language` and `difficulty` keys of `task.yaml`.
- Packaging excludes `./executable` and `./target` (`tar --anchored --exclude=./executable --exclude=./target`, owner and
  group 0, numeric owner).

**Measurement semantics**
- Labels attach to the exact judged subject. A Support is never transferred to a run-end recapture, even when the bytes
  match. Identical bytes are never joined by hash alone.
- Research data goes to experiment events. The `records` table keeps only operational status.
- Every experiment event carries producer identities. A Label carries its evaluator epoch.
- M0 instances are Rust only (`language: rs`, 107 instances).
- Frozen M0 protocol:
  - an evaluator branch error gets up to 2 re-evaluations of the same package;
  - a crashed run gets 1 rerun;
  - after that, the row is `invalid`;
  - missing and invalid rows are reported per arm and never dropped;
  - 4 corpus instances per arm are run twice;
  - pool ratios are dev/select/confirm = 40/30/30 over non-seen instances, with an operator-held salt;
  - every dev instance used in the corpus is marked exposed.

**Operations**
- The corpus launch (Task 13) needs the user's explicit approval of the run count and budget. Task 12 ends by asking
  for it.
- Long runs are launched detached (`setsid nohup …`), because background tool commands are stopped after 2 h.
- Never push without the user's explicit OK.

**Repo rules (AGENTS.md)**
- Rust:
  - run tests with `just test -p <crate>`, never `cargo test`;
  - then `just fmt` and `just fix -p <crate>` (both in `codex-rs/`); run `just bazel-lock-update` from the repo root
    after any `Cargo.toml` or `Cargo.lock` change;
  - modules under 500 LoC; new test modules go in sibling `*_tests.rs` files with `#[path = …]`;
    `pretty_assertions::assert_eq`;
  - no `expect`/`unwrap` in non-test code;
  - inline `format!` args;
  - `/*param*/` comments on opaque literal arguments;
  - no single-use helper functions.
- Python:
  - no `__future__`;
  - stdlib `unittest`, run as `cd scripts && python3 -m unittest <module>`;
  - `uv run --frozen --project scripts ruff format …` and `ruff check …`.

## Review Focus

1. **The run hits its deadline mid-turn.** The executor is interrupted, so there is no judged subject. The final
   workspace must still be captured and labelled, and the report must count the run in its arm's totals (Task 8 test
   `test_label_run_labels_final_workspace_without_judgments`).
2. **An instance has a persistent evaluator branch error.** csview fails branch `efa8c407dbe3` on every package,
   including the null package. It must be classified as known via the null sentinel and labelled valid, not retried
   into `invalid` (Task 7 test `test_known_branch_error_from_null_sentinel_is_valid`).
3. **The agent wrote a file the host cannot read** (for example a 0600 file owned by uid 1000). Capture fails, and the
   run must get an invalid label with the reason, never a silent drop (Task 8 test
   `test_unreadable_workspace_gives_an_invalid_label`).
4. **An instance's Docker images are missing and the pull fails.** `prepare` fails fast, the batch marks that run
   `invalid` with the reason, and it continues with the other runs (Task 10 test
   `test_failed_prepare_is_invalid_and_the_batch_continues`).
5. **Two batch processes on the same batch directory.** The second refuses to start (Task 10 test
   `test_second_batch_process_refuses`).

---

## File structure

```
codex-rs/pro-contract-store/                 NEW crate codex-pro-contract-store (no codex-core)
  Cargo.toml, BUILD.bazel
  src/lib.rs                                  re-exports
  src/hashing.rs, hashing_tests.rs            moved from ext; digest_of fails loudly
  src/terms.rs                                moved; + CapturePolicy::standard
  src/capture.rs, capture_tests.rs            moved; + persist_manifest, load_subject
  src/store/mod.rs, blobs.rs, blobs_tests.rs  moved
  src/store/ledger.rs, ledger_tests.rs        moved; + subjects table, bind_subject, subject_binding
  src/store/experiments.rs, experiments_tests.rs   NEW: append-only experiment events
  src/cli.rs, cli_tests.rs                    NEW: CLI logic
  src/bin/pro_contract_store.rs               NEW: thin clap main
codex-rs/ext/pro-contract/
  Cargo.toml                                  depend on the store crate; drop sqlx/sha2
  src/lib.rs                                  re-export the store crate's API
  src/controller/identity.rs                  NEW: harness sha256 + Identities assembly
  src/controller/runtime.rs                   persist subjects; write events; reviewer identity in evaluator digest
  src/controller/ports.rs                     + worker_identity()
  src/controller/decision.rs                  residual keeps head and tail
  src/checks.rs                               log() keeps head and tail (PRELUDE const)
  src/workers/{mod,drafter,reviewer}.rs       bounded_head_tail; policy_digest(); reviewer cap and omission rule
scripts/
  procontract_benchmark_runner.py             generalized instance/images; turn statuses; silent-lane stop; no __future__
  procontract_store.py                        NEW: wrapper over the pro-contract-store CLI
  procontract_evaluation.py                   NEW: pins/epoch, packaging, evaluation with retries, labels
  procontract_pools.py                        NEW: seen-list, sealed salted split
  procontract_batch.py                        NEW: plan / run / null / status, reconciliation, lock
  procontract_m0_report.py                    NEW: estimands, clustered CIs, revalidation, costs, noise
  testing/fake_programbench.py                NEW: fake `programbench eval`
  testing/fake_runner.py                      NEW: fake runner for batch tests
  test_procontract_{store,evaluation,pools,batch,m0_report}.py   NEW
  test_procontract_benchmark_runner.py        extended
```

---

### Task 1: Extract the `codex-pro-contract-store` crate; `digest_of` fails loudly

**Files:**
- Create: `codex-rs/pro-contract-store/Cargo.toml`, `codex-rs/pro-contract-store/BUILD.bazel`,
  `codex-rs/pro-contract-store/src/lib.rs`
- Move (`git mv`) from `codex-rs/ext/pro-contract/src/` to `codex-rs/pro-contract-store/src/`: `hashing.rs`,
  `hashing_tests.rs`, `terms.rs`, `capture.rs`, `capture_tests.rs`, `store/` (mod.rs, blobs.rs, blobs_tests.rs,
  ledger.rs, ledger_tests.rs)
- Modify: `codex-rs/Cargo.toml` (member and workspace dependency), `codex-rs/ext/pro-contract/Cargo.toml`,
  `codex-rs/ext/pro-contract/src/lib.rs`, `codex-rs/pro-contract-store/src/hashing.rs`,
  `codex-rs/pro-contract-store/src/hashing_tests.rs`

**Interfaces:**
- Produces: crate `codex_pro_contract_store`, which re-exports everything the extension previously exported from these
  modules (`digest_of`, `BlobStore`, `Ledger`, `LedgerError`, `EventRecord`, `CapturePolicy`, `Terms`, `Requirement`,
  `OutOfScope`, `EvidencePolicy`, `EvidenceClass`, `DifferentialCase`, `Subject`, `Manifest`, `Entry`, `EntryKind`,
  `CaptureError`, `capture`, `materialize`) plus `LEDGER_FILE`. The extension keeps its old paths through `pub use`.

- [ ] **Step 1: Move the files and create the crate**

```bash
cd codex-rs
mkdir -p pro-contract-store/src
git mv ext/pro-contract/src/hashing.rs ext/pro-contract/src/hashing_tests.rs ext/pro-contract/src/terms.rs \
  ext/pro-contract/src/capture.rs ext/pro-contract/src/capture_tests.rs pro-contract-store/src/
git mv ext/pro-contract/src/store pro-contract-store/src/store
```

`codex-rs/pro-contract-store/Cargo.toml`:

```toml
[package]
edition.workspace = true
license.workspace = true
name = "codex-pro-contract-store"
version.workspace = true

[lib]
name = "codex_pro_contract_store"
path = "src/lib.rs"
doctest = false

[lints]
workspace = true

[dependencies]
codex-pro-contract = { workspace = true }
codex-state = { workspace = true }
serde = { workspace = true, features = ["derive"] }
serde_json = { workspace = true }
sha2 = { workspace = true }
sqlx = { workspace = true }
thiserror = { workspace = true }
tokio = { workspace = true, features = ["fs"] }

[dev-dependencies]
codex-utils-absolute-path = { workspace = true }
pretty_assertions = { workspace = true }
tempfile = { workspace = true }
tokio = { workspace = true, features = ["macros", "rt-multi-thread"] }
```

`codex-rs/pro-contract-store/BUILD.bazel`:

```python
load("//:defs.bzl", "codex_rust_crate")

codex_rust_crate(
    name = "pro-contract-store",
    crate_name = "codex_pro_contract_store",
)
```

`codex-rs/pro-contract-store/src/lib.rs`:

```rust
//! The ProContract institution's storage primitives: domain-separated hashing, contract terms,
//! workspace capture, the content-addressed blob store, and the SQLite ledger. Free of
//! `codex-core`, so that operator tools and a protected institution service can link it directly.

mod capture;
mod hashing;
mod store;
mod terms;

pub use capture::CaptureError;
pub use capture::Entry;
pub use capture::EntryKind;
pub use capture::Manifest;
pub use capture::Subject;
pub use capture::capture;
pub use capture::materialize;
pub use hashing::digest_of;
pub use store::blobs::BlobStore;
pub use store::ledger::EventRecord;
pub use store::ledger::LEDGER_FILE;
pub use store::ledger::Ledger;
pub use store::ledger::LedgerError;
pub use terms::CapturePolicy;
pub use terms::DifferentialCase;
pub use terms::EvidenceClass;
pub use terms::EvidencePolicy;
pub use terms::OutOfScope;
pub use terms::Requirement;
pub use terms::Terms;
```

In `codex-rs/Cargo.toml`, add `"pro-contract-store",` to `[workspace] members`, next to `"pro-contract",`. Add the
workspace dependency next to `codex-pro-contract`:

```toml
codex-pro-contract-store = { path = "pro-contract-store" }
```

In `codex-rs/ext/pro-contract/Cargo.toml`, add `codex-pro-contract-store = { workspace = true }`. Remove `sha2` and
`sqlx`; only the moved modules used them. Check with
`grep -rn "sqlx::\|sha2::\|use sqlx\|use sha2" ext/pro-contract/src`, which must print nothing.

In `codex-rs/ext/pro-contract/src/lib.rs`:
- delete `mod capture;`, `mod hashing;`, `mod store;` and `mod terms;`;
- replace each `pub use capture::…`, `pub use hashing::…`, `pub use store::…` and `pub use terms::…` line with the same
  item from `codex_pro_contract_store`, for example `pub use codex_pro_contract_store::BlobStore;`;
- keep the extension-owned exports (`checks::…`, `controller::…`, `settings::…`, `workers::…`) unchanged.

Internal `crate::BlobStore` / `crate::capture` paths keep resolving through these re-exports.

- [ ] **Step 2: Build both crates and run the moved tests**

Run: `cd codex-rs && just test -p codex-pro-contract-store && just test -p codex-pro-contract-extension`
Expected: both pass. The two counts add up to 75, the extension's previous total.

- [ ] **Step 3: Write the failing test for loud serialization failure**

Append to `codex-rs/pro-contract-store/src/hashing_tests.rs`:

```rust
struct Unserializable;

impl Serialize for Unserializable {
    fn serialize<S: serde::Serializer>(&self, _serializer: S) -> Result<S::Ok, S::Error> {
        Err(serde::ser::Error::custom("refused"))
    }
}

#[test]
#[should_panic(expected = "canonical JSON for test failed: refused")]
fn a_value_that_cannot_be_serialized_fails_loudly() {
    digest_of("test", &Unserializable);
}
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd codex-rs && just test -p codex-pro-contract-store -- hashing`
Expected: FAIL. `a_value_that_cannot_be_serialized_fails_loudly` does not panic, because today the empty-bytes
fallback hashes the prefix.

- [ ] **Step 5: Make `digest_of` panic with the domain and the error**

In `codex-rs/pro-contract-store/src/hashing.rs`, replace the serialization lines:

```rust
    // A serialization failure is a programming error: hashing the prefix alone would make
    // different values collide silently.
    let json = serde_json::to_vec(value)
        .unwrap_or_else(|error| panic!("canonical JSON for {domain} failed: {error}"));
```

- [ ] **Step 6: Run the store and extension tests**

Run: `cd codex-rs && just test -p codex-pro-contract-store && just test -p codex-pro-contract-extension`
Expected: PASS, with one more test than in Step 2.

- [ ] **Step 7: Lock files, format, lint, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-store && just fix -p codex-pro-contract-extension
cd .. && just bazel-lock-update
git add -A codex-rs/pro-contract-store codex-rs/ext/pro-contract codex-rs/Cargo.toml codex-rs/Cargo.lock MODULE.bazel.lock
git commit -m "refactor(pro-contract): extract the institution store into codex-pro-contract-store

Hashing, terms, capture, blobs and the ledger move into a crate without
codex-core, so operator tools and a protected service can link them;
digest_of now fails loudly instead of hashing the prefix alone."
```

---

### Task 2: Persisted, resolvable subjects

**Files:**
- Modify: `codex-rs/pro-contract-store/src/capture.rs`, `codex-rs/pro-contract-store/src/capture_tests.rs`,
  `codex-rs/pro-contract-store/src/terms.rs`, `codex-rs/pro-contract-store/src/store/ledger.rs`,
  `codex-rs/pro-contract-store/src/store/ledger_tests.rs`, `codex-rs/pro-contract-store/src/lib.rs`,
  `codex-rs/ext/pro-contract/src/controller/runtime.rs`, `codex-rs/ext/pro-contract/src/controller/automation_tests.rs`

**Interfaces:**
- Consumes: Task 1's crate.
- Produces:
  - `pub fn persist_manifest(subject: &Subject, store: &BlobStore) -> Result<Digest, CaptureError>`
  - `pub fn load_subject(store: &BlobStore, manifest: &Digest, subject_hash: &Digest) -> Result<Subject, CaptureError>`
  - `CaptureError::Corrupt(String)`
  - `pub struct SubjectBinding { pub manifest: Digest, pub capture_policy: Digest }`
  - `Ledger::bind_subject(&self, subject_hash: &Digest, binding: &SubjectBinding) -> Result<(), LedgerError>`
  - `Ledger::subject_binding(&self, subject_hash: &Digest) -> Result<Option<SubjectBinding>, LedgerError>`
  - `CapturePolicy::standard(excluded_paths: Vec<String>) -> CapturePolicy` (version 1, 4 MiB per file, 256 MiB total)

- [ ] **Step 1: Write the failing store tests**

Append to `codex-rs/pro-contract-store/src/capture_tests.rs` (the module is already `#[cfg(all(test, unix))]`):

```rust
#[test]
fn a_persisted_manifest_resolves_to_the_same_subject() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let root = dir.path().join("ws");
    std::fs::create_dir_all(root.join("src"))?;
    std::fs::write(root.join("src/main.rs"), "fn main() {}\n")?;
    let store = BlobStore::open(&dir.path().join("blobs"))?;
    let policy = CapturePolicy::standard(Vec::new());
    let subject = capture(&root, &policy, &store).map_err(std::io::Error::other)?;

    let manifest = persist_manifest(&subject, &store).map_err(std::io::Error::other)?;
    let reopened = BlobStore::open(&dir.path().join("blobs"))?;
    let loaded = load_subject(&reopened, &manifest, &subject.subject_hash).map_err(std::io::Error::other)?;

    assert_eq!(loaded, subject);
    Ok(())
}

#[test]
fn a_manifest_that_is_not_the_claimed_subject_is_rejected() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let root = dir.path().join("ws");
    std::fs::create_dir_all(&root)?;
    std::fs::write(root.join("a.txt"), "a")?;
    let store = BlobStore::open(&dir.path().join("blobs"))?;
    let subject = capture(&root, &CapturePolicy::standard(Vec::new()), &store).map_err(std::io::Error::other)?;
    let manifest = persist_manifest(&subject, &store).map_err(std::io::Error::other)?;

    let other = Digest::of(b"another subject");
    let result = load_subject(&store, &manifest, &other);

    assert!(matches!(result, Err(CaptureError::Corrupt(_))), "{result:?}");
    Ok(())
}
```

Add `use super::persist_manifest;`, `use super::load_subject;` and `use codex_pro_contract::Digest;` to that file's
imports if they are absent.

Append to `codex-rs/pro-contract-store/src/store/ledger_tests.rs`:

```rust
#[tokio::test]
async fn a_subject_binding_survives_reopening_and_rejects_rebinding() {
    let dir = tempfile::tempdir().expect("tempdir");
    let subject = Digest::of(b"subject");
    let binding = SubjectBinding {
        manifest: Digest::of(b"manifest"),
        capture_policy: Digest::of(b"policy"),
    };
    {
        let ledger = ledger(dir.path()).await;
        ledger.bind_subject(&subject, &binding).await.expect("bind");
        ledger.bind_subject(&subject, &binding).await.expect("identical rebind is a no-op");
    }
    let reopened = ledger(dir.path()).await;

    assert_eq!(reopened.subject_binding(&subject).await.expect("read"), Some(binding.clone()));
    let different = SubjectBinding {
        manifest: Digest::of(b"other manifest"),
        capture_policy: binding.capture_policy,
    };
    assert!(matches!(
        reopened.bind_subject(&subject, &different).await,
        Err(LedgerError::Corrupt(_))
    ));
}
```

Here `ledger(dir)` is the existing helper at the top of `ledger_tests.rs`. Add `use super::SubjectBinding;`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd codex-rs && just test -p codex-pro-contract-store`
Expected: compile errors for the missing `persist_manifest`, `load_subject`, `CapturePolicy::standard` and
`SubjectBinding`.

- [ ] **Step 3: Implement persistence**

In `codex-rs/pro-contract-store/src/terms.rs`, add to `impl CapturePolicy`, creating the impl if absent:

```rust
impl CapturePolicy {
    /// The capture policy every ProContract capture uses: version 1, 4 MiB per file, 256 MiB in total.
    pub fn standard(excluded_paths: Vec<String>) -> Self {
        Self {
            version: 1,
            excluded_paths,
            max_file_bytes: 4 << 20,
            max_total_bytes: 256 << 20,
        }
    }
}
```

In `codex-rs/pro-contract-store/src/capture.rs`, add a variant to `CaptureError`:

```rust
    #[error("subject record is corrupt: {0}")]
    Corrupt(String),
```

and the functions:

```rust
/// Stores the subject's canonical manifest as a blob, so that the subject can later be resolved
/// from its hash alone.
pub fn persist_manifest(subject: &Subject, store: &BlobStore) -> Result<Digest, CaptureError> {
    let bytes = serde_json::to_vec(&subject.manifest)
        .map_err(|error| CaptureError::Corrupt(error.to_string()))?;
    store.put(&bytes).map_err(io_error("manifest"))
}

/// Reads a persisted manifest back and checks that it is exactly the claimed subject.
pub fn load_subject(
    store: &BlobStore,
    manifest: &Digest,
    subject_hash: &Digest,
) -> Result<Subject, CaptureError> {
    let bytes = store.get(manifest).map_err(io_error("manifest"))?;
    let manifest: Manifest =
        serde_json::from_slice(&bytes).map_err(|error| CaptureError::Corrupt(error.to_string()))?;
    let actual = digest_of("subject_manifest", &manifest);
    if actual != *subject_hash {
        return Err(CaptureError::Corrupt(format!(
            "manifest describes subject {actual}, not {subject_hash}"
        )));
    }
    Ok(Subject {
        manifest,
        subject_hash: *subject_hash,
    })
}
```

In `codex-rs/pro-contract-store/src/store/ledger.rs`, append to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS subjects (
    subject_hash TEXT PRIMARY KEY NOT NULL,
    manifest TEXT NOT NULL,
    capture_policy TEXT NOT NULL
);
```

and add:

```rust
/// Where a captured subject's manifest is stored and under which capture policy it was taken.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SubjectBinding {
    pub manifest: Digest,
    pub capture_policy: Digest,
}

impl Ledger {
    /// Binds a subject hash to its persisted manifest. Rebinding identically is a no-op;
    /// rebinding differently is corruption.
    pub async fn bind_subject(
        &self,
        subject_hash: &Digest,
        binding: &SubjectBinding,
    ) -> Result<(), LedgerError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)?;
        if let Some(found) = read_binding(&mut *tx, subject_hash).await? {
            return if found == *binding {
                Ok(())
            } else {
                Err(LedgerError::Corrupt(format!(
                    "subject {subject_hash} is already bound to another manifest"
                )))
            };
        }
        sqlx::query("INSERT INTO subjects (subject_hash, manifest, capture_policy) VALUES (?, ?, ?)")
            .bind(subject_hash.to_string())
            .bind(binding.manifest.to_string())
            .bind(binding.capture_policy.to_string())
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        tx.commit().await.map_err(storage)
    }

    pub async fn subject_binding(
        &self,
        subject_hash: &Digest,
    ) -> Result<Option<SubjectBinding>, LedgerError> {
        let mut connection = self.pool.acquire().await.map_err(storage)?;
        read_binding(&mut *connection, subject_hash).await
    }
}

async fn read_binding(
    connection: &mut sqlx::SqliteConnection,
    subject_hash: &Digest,
) -> Result<Option<SubjectBinding>, LedgerError> {
    let row = sqlx::query("SELECT manifest, capture_policy FROM subjects WHERE subject_hash = ?")
        .bind(subject_hash.to_string())
        .fetch_optional(connection)
        .await
        .map_err(storage)?;
    row.map(|row| {
        let manifest: String = row.try_get("manifest").map_err(storage)?;
        let capture_policy: String = row.try_get("capture_policy").map_err(storage)?;
        Ok(SubjectBinding {
            manifest: parse_digest(&manifest)?,
            capture_policy: parse_digest(&capture_policy)?,
        })
    })
    .transpose()
}
```

`read_binding` is called from both methods, so it is not a single-use helper. In `lib.rs`, export `persist_manifest`,
`load_subject` and `store::ledger::SubjectBinding`.

- [ ] **Step 4: Run the store tests**

Run: `cd codex-rs && just test -p codex-pro-contract-store`
Expected: PASS, including the three new tests.

- [ ] **Step 5: Write the failing extension test (judged subjects are bound)**

In `codex-rs/ext/pro-contract/src/controller/automation_tests.rs`, extend
`late_issue_verifies_the_artifact_frozen_at_handoff`. After `assert!(contract.support.is_some(), …)`, add:

```rust
    let judged = contract.support.expect("support").coordinate.subject_hash;
    let binding = lane.ledger.subject_binding(&judged).await.expect("binding read");
    assert!(binding.is_some(), "the judged subject must be resolvable from its hash");
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd codex-rs && just test -p codex-pro-contract-extension -- late_issue`
Expected: FAIL with "the judged subject must be resolvable from its hash".

- [ ] **Step 7: Persist every capture in the lane**

In `codex-rs/ext/pro-contract/src/controller/runtime.rs`:
- replace the `CapturePolicy { version: 1, … }` construction in `ThreadRuntime::new` with
  `CapturePolicy::standard(profile.excluded_paths.clone())`;
- replace `capture_workspace` with:

```rust
    async fn capture_workspace(&self) -> Result<Subject, String> {
        let root = self.profile.workspace_host_root.clone();
        let policy = self.capture_policy.clone();
        let store = self.store.clone();
        let task = tokio::task::spawn_blocking(move || {
            let subject = capture(&root, &policy, &store)?;
            let manifest = persist_manifest(&subject, &store)?;
            Ok::<_, codex_pro_contract_store::CaptureError>((subject, manifest))
        });
        let (subject, manifest) = match tokio::time::timeout(CAPTURE_TIMEOUT, task).await {
            Ok(Ok(Ok(captured))) => captured,
            Ok(Ok(Err(error))) => return Err(error.to_string()),
            Ok(Err(error)) => return Err(format!("capture task failed: {error}")),
            Err(_) => return Err("capture exceeded its time cap".to_string()),
        };
        let binding = SubjectBinding {
            manifest,
            capture_policy: digest_of("capture_policy", &self.capture_policy),
        };
        self.ledger
            .bind_subject(&subject.subject_hash, &binding)
            .await
            .map_err(|error| error.to_string())?;
        Ok(subject)
    }
```

Import `codex_pro_contract_store::persist_manifest` and `codex_pro_contract_store::SubjectBinding`. The extension
crate already depends on the store crate.

- [ ] **Step 8: Run the extension tests**

Run: `cd codex-rs && just test -p codex-pro-contract-extension`
Expected: PASS (all tests).

- [ ] **Step 9: Format, lint, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-store && just fix -p codex-pro-contract-extension
git add -A codex-rs/pro-contract-store codex-rs/ext/pro-contract
git commit -m "feat(pro-contract): persist captured subjects so they resolve from their hash"
```

---

### Task 3: Append-only experiment events

**Files:**
- Create: `codex-rs/pro-contract-store/src/store/experiments.rs`,
  `codex-rs/pro-contract-store/src/store/experiments_tests.rs`
- Modify: `codex-rs/pro-contract-store/src/store/mod.rs` (`pub(crate) mod experiments;`),
  `codex-rs/pro-contract-store/src/store/ledger.rs` (make `pool` `pub(super)`; run the experiments schema in `open`;
  add the `LedgerError::InvalidEvent` variant), `codex-rs/pro-contract-store/src/lib.rs`

**Interfaces:**
- Produces:
  - `pub enum ExperimentKind { Assignment, Intake, Draft, Issue, Verification, Capture, Execution, Label, Correction }`
    (serde `snake_case`)
  - `pub struct Identities { pub harness: Option<String>, pub policies: BTreeMap<String, Digest>, pub model: Option<String>, pub effort: Option<String>, pub evaluator_epoch: Option<Digest> }`
  - `pub struct ExperimentEvent { pub kind: ExperimentKind, pub identities: Identities, pub body: serde_json::Value }`
  - `pub struct ExperimentRecord { pub seq: i64, pub event: ExperimentEvent, pub prev_hash: Digest, pub hash: Digest }`
  - `Ledger::append_experiment(&self, event: &ExperimentEvent) -> Result<ExperimentRecord, LedgerError>`
  - `Ledger::experiments(&self) -> Result<Vec<ExperimentRecord>, LedgerError>`
  - `Ledger::verify_experiment_chain(&self) -> Result<(), LedgerError>`
  - `LedgerError::InvalidEvent(String)`

**Why canonicalization matters:** the workspace enables serde_json's `preserve_order` feature in some builds
(`tui/Cargo.toml`). Hashing a raw `Value` would then depend on which binary wrote the event. Bodies are therefore
rebuilt with sorted keys before they are hashed or stored.

- [ ] **Step 1: Write the failing tests** (`experiments_tests.rs`)

```rust
use std::collections::BTreeMap;

use codex_pro_contract::Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::ExperimentEvent;
use super::ExperimentKind;
use super::Identities;
use crate::Ledger;
use crate::LedgerError;

async fn ledger(dir: &std::path::Path) -> Ledger {
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(dir).expect("absolute tempdir"),
    );
    Ledger::open(&sqlite, dir).await.expect("open ledger")
}

fn identities() -> Identities {
    Identities {
        harness: Some("ab".repeat(32)),
        policies: BTreeMap::from([("reviewer".to_string(), Digest::of(b"reviewer"))]),
        model: Some("gpt-5.6-luna".to_string()),
        effort: Some("max".to_string()),
        evaluator_epoch: None,
    }
}

fn event(kind: ExperimentKind, body: serde_json::Value) -> ExperimentEvent {
    ExperimentEvent { kind, identities: identities(), body }
}

#[tokio::test]
async fn events_append_in_order_and_chain() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;

    let first = ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({"run_id": "r1"})))
        .await
        .expect("append");
    let second = ledger
        .append_experiment(&event(ExperimentKind::Execution, json!({"run_id": "r1"})))
        .await
        .expect("append");

    assert_eq!((first.seq, second.prev_hash), (1, first.hash));
    assert_eq!(ledger.experiments().await.expect("list"), vec![first, second]);
    ledger.verify_experiment_chain().await.expect("chain verifies");
}

#[tokio::test]
async fn events_cannot_be_updated_or_deleted() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({})))
        .await
        .expect("append");
    let pool = sqlx::SqlitePool::connect(&format!(
        "sqlite://{}",
        dir.path().join(crate::LEDGER_FILE).display()
    ))
    .await
    .expect("raw pool");

    let update = sqlx::query("UPDATE experiment_events SET kind = 'label'").execute(&pool).await;
    let delete = sqlx::query("DELETE FROM experiment_events").execute(&pool).await;

    assert!(update.is_err() && delete.is_err(), "{update:?} {delete:?}");
}

#[tokio::test]
async fn a_label_needs_its_evaluator_epoch_and_verification_needs_policies() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    let mut no_policies = event(ExperimentKind::Verification, json!({}));
    no_policies.identities.policies.clear();

    let label = ledger.append_experiment(&event(ExperimentKind::Label, json!({}))).await;
    let verification = ledger.append_experiment(&no_policies).await;

    assert!(matches!(label, Err(LedgerError::InvalidEvent(_))), "{label:?}");
    assert!(matches!(verification, Err(LedgerError::InvalidEvent(_))), "{verification:?}");
}

#[tokio::test]
async fn body_key_order_does_not_change_the_hash() {
    let dir_a = tempfile::tempdir().expect("tempdir");
    let dir_b = tempfile::tempdir().expect("tempdir");
    let a: serde_json::Value = serde_json::from_str(r#"{"b": 1, "a": {"y": 2, "x": 3}}"#).expect("json");
    let b: serde_json::Value = serde_json::from_str(r#"{"a": {"x": 3, "y": 2}, "b": 1}"#).expect("json");

    let first = ledger(dir_a.path()).await
        .append_experiment(&event(ExperimentKind::Assignment, a)).await.expect("append");
    let second = ledger(dir_b.path()).await
        .append_experiment(&event(ExperimentKind::Assignment, b)).await.expect("append");

    assert_eq!(first.hash, second.hash);
}

#[tokio::test]
async fn a_forged_row_breaks_the_chain() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({})))
        .await
        .expect("append");
    let pool = sqlx::SqlitePool::connect(&format!(
        "sqlite://{}",
        dir.path().join(crate::LEDGER_FILE).display()
    ))
    .await
    .expect("raw pool");
    sqlx::query(
        "INSERT INTO experiment_events (kind, event_json, prev_hash, hash) VALUES ('label', '{}', ?, ?)",
    )
    .bind("00".repeat(32))
    .bind("11".repeat(32))
    .execute(&pool)
    .await
    .expect("raw insert");

    assert!(matches!(
        ledger.verify_experiment_chain().await,
        Err(LedgerError::Corrupt(_))
    ));
}
```

`sqlx` is already a dependency. `codex-utils-absolute-path` and `tempfile` are dev-dependencies.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd codex-rs && just test -p codex-pro-contract-store -- experiments`
Expected: compile errors, because the `experiments` module does not exist yet.

- [ ] **Step 3: Implement `experiments.rs`**

```rust
//! Append-only, hash-chained research events (RSI spec §3.5). Unlike `records`, these are never
//! updated or deleted: SQLite triggers reject both, and the chain detects forged rows.

use std::collections::BTreeMap;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sqlx::Row;

use super::ledger::Ledger;
use super::ledger::LedgerError;
use crate::digest_of;

pub(crate) const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS experiment_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    event_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS experiment_events_no_update
BEFORE UPDATE ON experiment_events
BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS experiment_events_no_delete
BEFORE DELETE ON experiment_events
BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END;
";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExperimentKind {
    Assignment,
    Intake,
    Draft,
    Issue,
    Verification,
    Capture,
    Execution,
    Label,
    Correction,
}

/// What produced an event. Every event carries one.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Identities {
    /// SHA-256 of the harness executable, when a harness produced the event.
    pub harness: Option<String>,
    /// Judgment policy digests by name (`drafter`, `reviewer`, `check_pipeline`).
    pub policies: BTreeMap<String, Digest>,
    pub model: Option<String>,
    pub effort: Option<String>,
    /// Required on labels.
    pub evaluator_epoch: Option<Digest>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentEvent {
    pub kind: ExperimentKind,
    pub identities: Identities,
    /// Kind-specific content, owned by its writer (the extension or the runner).
    pub body: Value,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExperimentRecord {
    pub seq: i64,
    pub event: ExperimentEvent,
    pub prev_hash: Digest,
    pub hash: Digest,
}

/// Rebuilds objects with sorted keys, so the encoding does not depend on serde_json features.
fn canonical(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let sorted: BTreeMap<&String, Value> =
                map.iter().map(|(key, value)| (key, canonical(value))).collect();
            Value::Object(sorted.into_iter().map(|(key, value)| (key.clone(), value)).collect())
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical).collect()),
        other => other.clone(),
    }
}

fn validate(event: &ExperimentEvent) -> Result<(), LedgerError> {
    let invalid = |message: &str| Err(LedgerError::InvalidEvent(message.to_string()));
    match event.kind {
        ExperimentKind::Label | ExperimentKind::Correction
            if event.identities.evaluator_epoch.is_none() =>
        {
            invalid("a label or correction must carry its evaluator epoch")
        }
        ExperimentKind::Verification
            if event.identities.policies.is_empty() || event.identities.model.is_none() =>
        {
            invalid("a verification must carry its policy digests and model")
        }
        _ => Ok(()),
    }
}

fn chain_hash(prev_hash: &Digest, event: &ExperimentEvent) -> Digest {
    digest_of("experiment_event", &(prev_hash, event))
}

impl Ledger {
    pub async fn append_experiment(
        &self,
        event: &ExperimentEvent,
    ) -> Result<ExperimentRecord, LedgerError> {
        validate(event)?;
        let event = ExperimentEvent {
            body: canonical(&event.body),
            ..event.clone()
        };
        let encoded = serde_json::to_string(&event)
            .map_err(|error| LedgerError::Corrupt(error.to_string()))?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|error| LedgerError::Storage(error.to_string()))?;
        let prev_hash = sqlx::query_scalar::<_, String>(
            "SELECT hash FROM experiment_events ORDER BY seq DESC LIMIT 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(|error| LedgerError::Storage(error.to_string()))?
        .map(|hex| {
            Digest::parse_hex(&hex)
                .ok_or_else(|| LedgerError::Corrupt(format!("invalid digest {hex}")))
        })
        .transpose()?
        .unwrap_or(Digest::from_bytes([0; 32]));
        let hash = chain_hash(&prev_hash, &event);
        let kind = serde_json::to_value(event.kind)
            .ok()
            .and_then(|kind| kind.as_str().map(str::to_string))
            .unwrap_or_default();
        let seq = sqlx::query(
            "INSERT INTO experiment_events (kind, event_json, prev_hash, hash) VALUES (?, ?, ?, ?)",
        )
        .bind(&kind)
        .bind(&encoded)
        .bind(prev_hash.to_string())
        .bind(hash.to_string())
        .execute(&mut *tx)
        .await
        .map_err(|error| LedgerError::Storage(error.to_string()))?
        .last_insert_rowid();
        tx.commit()
            .await
            .map_err(|error| LedgerError::Storage(error.to_string()))?;
        Ok(ExperimentRecord {
            seq,
            event,
            prev_hash,
            hash,
        })
    }

    pub async fn experiments(&self) -> Result<Vec<ExperimentRecord>, LedgerError> {
        let rows = sqlx::query(
            "SELECT seq, event_json, prev_hash, hash FROM experiment_events ORDER BY seq",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(|error| LedgerError::Storage(error.to_string()))?;
        rows.into_iter()
            .map(|row| {
                let get = |column: &str| -> Result<String, LedgerError> {
                    row.try_get(column)
                        .map_err(|error| LedgerError::Storage(error.to_string()))
                };
                let digest = |hex: String| {
                    Digest::parse_hex(&hex)
                        .ok_or_else(|| LedgerError::Corrupt(format!("invalid digest {hex}")))
                };
                Ok(ExperimentRecord {
                    seq: row
                        .try_get("seq")
                        .map_err(|error| LedgerError::Storage(error.to_string()))?,
                    event: serde_json::from_str(&get("event_json")?)
                        .map_err(|error| LedgerError::Corrupt(error.to_string()))?,
                    prev_hash: digest(get("prev_hash")?)?,
                    hash: digest(get("hash")?)?,
                })
            })
            .collect()
    }

    /// Recomputes the chain; any forged, reordered or edited row is corruption.
    pub async fn verify_experiment_chain(&self) -> Result<(), LedgerError> {
        let mut expected_prev = Digest::from_bytes([0; 32]);
        for record in self.experiments().await? {
            if record.prev_hash != expected_prev
                || record.hash != chain_hash(&record.prev_hash, &record.event)
            {
                return Err(LedgerError::Corrupt(format!(
                    "experiment event {} breaks the chain",
                    record.seq
                )));
            }
            expected_prev = record.hash;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "experiments_tests.rs"]
mod tests;
```

The forged-row test inserts `'{}'` as `event_json`. That fails to deserialize, which is also reported as `Corrupt`, so
the assertion holds.

In `ledger.rs`:
- make the field `pub(super) pool: SqlitePool`;
- in `open`, after the existing schema, run
  `sqlx::raw_sql(super::experiments::SCHEMA).execute(&pool).await.map_err(storage)?;`;
- add to `LedgerError`:

```rust
    #[error("experiment event is invalid: {0}")]
    InvalidEvent(String),
```

In `lib.rs`, export `store::experiments::{ExperimentEvent, ExperimentKind, ExperimentRecord, Identities}`, one `pub use`
per line.

- [ ] **Step 4: Run the tests**

Run: `cd codex-rs && just test -p codex-pro-contract-store`
Expected: PASS. All 5 experiment tests pass along with the earlier ones.

- [ ] **Step 5: Format, lint, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-store
git add -A codex-rs/pro-contract-store
git commit -m "feat(pro-contract): add append-only, hash-chained experiment events"
```

---

### Task 4: The extension writes research events with identities; reviewer identity in certificates

**Files:**
- Create: `codex-rs/ext/pro-contract/src/controller/identity.rs`
- Modify:
  - `codex-rs/ext/pro-contract/src/controller/mod.rs` (`pub(crate) mod identity;`)
  - `codex-rs/ext/pro-contract/src/controller/ports.rs`
  - `codex-rs/ext/pro-contract/src/controller/runtime.rs`
  - `codex-rs/ext/pro-contract/src/controller/automation_tests.rs`
  - `codex-rs/ext/pro-contract/src/workers/drafter.rs`
  - `codex-rs/ext/pro-contract/src/workers/reviewer.rs`

**Interfaces:**
- Consumes: Task 3 (`ExperimentEvent`, `ExperimentKind`, `Identities`, `Ledger::append_experiment`,
  `Ledger::experiments`).
- Produces:
  - `pub(crate) struct WorkerIdentity { pub model: Option<String>, pub effort: Option<String> }`
  - `Ports::worker_identity(&self) -> WorkerIdentity`
  - `drafter::policy_digest() -> Digest`
  - `reviewer::policy_digest() -> Digest`
  - `identity::harness_sha256() -> Option<String>`
  - `identity::identities(worker: &WorkerIdentity, check_pipeline: Option<Digest>) -> Identities`
- **Event bodies** (the runner and the report read these field names):
  - Intake `{thread_id, text, base_subject, capture_policy}`
  - Draft `{thread_id, message}`
  - Issue `{contract_id, terms, evidence_policy, capture_policy}`
  - Verification `{contract_id, generation, subject_hash, verdict: "support"|"defeat"|"not_verified", detail, receipts, check_error, review}`
- **Certificate change:** `evaluator_digest = digest_of("evaluator", &(receipts.evaluator_digest, reviewer::policy_digest(), &worker.model, &worker.effort))`.

- [ ] **Step 1: Write the failing automation tests**

In `automation_tests.rs`:
- add a `worker_model: &'static str` field to `FakePorts`, initialized to `"model-a"` in `FakePorts::new`;
- implement the new port method:

```rust
    fn worker_identity(&self) -> WorkerIdentity {
        WorkerIdentity {
            model: Some(self.worker_model.to_string()),
            effort: Some("max".to_string()),
        }
    }
```

Add `use super::super::ports::WorkerIdentity;` and `use codex_pro_contract_store::ExperimentKind;`, then the tests:

```rust
#[tokio::test]
async fn a_verification_is_an_immutable_event_with_identities() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    lane.wait_for("supported").await;

    let events = lane.ledger.experiments().await.expect("events");
    let kinds: Vec<ExperimentKind> = events.iter().map(|record| record.event.kind).collect();
    assert_eq!(
        kinds,
        vec![
            ExperimentKind::Intake,
            ExperimentKind::Draft,
            ExperimentKind::Issue,
            ExperimentKind::Verification
        ]
    );
    let verification = &events[3].event;
    assert_eq!(verification.body["verdict"], "support");
    assert_eq!(verification.identities.model.as_deref(), Some("model-a"));
    assert!(verification.identities.policies.contains_key("reviewer"));
    assert!(verification.identities.policies.contains_key("check_pipeline"));
    let record: Option<serde_json::Value> = lane
        .ledger
        .record("verification", "anything")
        .await
        .expect("records read");
    assert_eq!(record, None);
}

#[tokio::test]
async fn the_reviewer_model_is_part_of_the_certificates_evaluator() {
    let mut digests = Vec::new();
    for model in ["model-a", "model-b"] {
        let mut ports = FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]);
        ports.worker_model = model;
        let lane = lane(ports).await;
        lane.runtime.intake(INTAKE.to_string()).await;
        lane.wait_for("working").await;
        lane.executor_turn("turn-1", "done").await;
        lane.wait_for("supported").await;
        let contract = lane.contract().await.expect("contract");
        digests.push(contract.support.expect("support").coordinate.evaluator_digest);
    }

    assert_ne!(digests[0], digests[1]);
}
```

Update `only_the_first_human_turn_is_intake` to read events instead of the `intake` record:

```rust
    let intakes: Vec<String> = lane
        .ledger
        .experiments()
        .await
        .expect("events")
        .into_iter()
        .filter(|record| record.event.kind == ExperimentKind::Intake)
        .map(|record| record.event.body["text"].as_str().unwrap_or_default().to_string())
        .collect();
    assert_eq!(intakes, vec![INTAKE.to_string()]);
```

Import `pretty_assertions::assert_ne`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd codex-rs && just test -p codex-pro-contract-extension -- controller::runtime`
Expected: compile error, because `worker_identity` is not a member of `Ports`.

- [ ] **Step 3: Implement**

`controller/ports.rs`: add the type and the trait method (with doc comment), and implement it for `CodexPorts`:

```rust
/// The model and effort the hidden workers actually use.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct WorkerIdentity {
    pub model: Option<String>,
    pub effort: Option<String>,
}

    /// The model and effort hidden workers run with; part of every judgment's identity.
    fn worker_identity(&self) -> WorkerIdentity;

    fn worker_identity(&self) -> WorkerIdentity {
        WorkerIdentity {
            model: self.worker.model.clone().or_else(|| self.config.model.clone()),
            effort: self.worker.reasoning_effort.clone().or_else(|| {
                self.config
                    .model_reasoning_effort
                    .as_ref()
                    .map(|effort| format!("{effort:?}").to_lowercase())
            }),
        }
    }
```

`controller/identity.rs`:

```rust
//! Producer identities for experiment events: which harness, policies and model made a record.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use codex_pro_contract::Digest;
use codex_pro_contract_store::Identities;
use sha2::Digest as _;

use super::ports::WorkerIdentity;
use crate::workers::drafter;
use crate::workers::reviewer;

/// SHA-256 of the running harness executable, computed once.
pub(crate) fn harness_sha256() -> Option<String> {
    static HARNESS: OnceLock<Option<String>> = OnceLock::new();
    HARNESS
        .get_or_init(|| {
            let bytes = std::env::current_exe()
                .and_then(std::fs::read)
                .ok()?;
            Some(format!("{:x}", sha2::Sha256::digest(bytes)))
        })
        .clone()
}

pub(crate) fn identities(worker: &WorkerIdentity, check_pipeline: Option<Digest>) -> Identities {
    let mut policies = BTreeMap::from([
        ("drafter".to_string(), drafter::policy_digest()),
        ("reviewer".to_string(), reviewer::policy_digest()),
    ]);
    if let Some(check_pipeline) = check_pipeline {
        policies.insert("check_pipeline".to_string(), check_pipeline);
    }
    Identities {
        harness: harness_sha256(),
        policies,
        model: worker.model.clone(),
        effort: worker.effort.clone(),
        evaluator_epoch: None,
    }
}
```

This re-adds `sha2 = { workspace = true }` to the extension's `Cargo.toml`. Then run `just bazel-lock-update`.

`workers/drafter.rs` and `workers/reviewer.rs`: each gets

```rust
/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest() -> codex_pro_contract::Digest {
    crate::digest_of("drafter_policy", &(INSTRUCTIONS, schema()))
}
```

with domain `"reviewer_policy"` in `reviewer.rs`.

`controller/runtime.rs`:
- add `fn identities(&self, check_pipeline: Option<Digest>) -> Identities { identity::identities(&self.ports.worker_identity(), check_pipeline) }`;
- add the append helper used by all four writers:

```rust
    async fn record_event(&self, kind: ExperimentKind, check_pipeline: Option<Digest>, body: serde_json::Value) {
        let event = ExperimentEvent { kind, identities: self.identities(check_pipeline), body };
        if let Err(error) = self.ledger.append_experiment(&event).await {
            tracing::warn!("pro_contract could not record {kind:?}: {error}");
        }
    }
```

- replace each research `put_record` with `record_event`:
  - in `intake`, `put_record("intake", …)` becomes
    `self.record_event(ExperimentKind::Intake, /*check_pipeline*/ None, json!({"thread_id": self.thread_id.to_string(), "text": text, "base_subject": base.subject_hash, "capture_policy": digest_of("capture_policy", &self.capture_policy)})).await;`
  - in `draft`, `put_record("draft", …)` becomes
    `self.record_event(ExperimentKind::Draft, None, json!({"thread_id": self.thread_id.to_string(), "message": message})).await;`
  - in `issue`, the two `put_record("terms"/"evidence_policy", …)` calls become
    `self.record_event(ExperimentKind::Issue, None, json!({"contract_id": contract_id.0, "terms": terms, "evidence_policy": policy, "capture_policy": digest_of("capture_policy", &self.capture_policy)})).await;`
  - in `verify`, the `put_record("verification", …)` call becomes a `record_event(ExperimentKind::Verification, checks.as_ref().ok().map(|receipts| receipts.evaluator_digest), json!({...}))`. The body is: `contract_id`, `generation`, `subject_hash`, `verdict` (`"support"` for `Verdict::Support`, `"defeat"` for `Verdict::Defeat { .. }`, `"not_verified"` for `Verdict::NotVerified { .. }`), `detail` (the residual or reason, or `""`), `receipts` (`checks.as_ref().ok()`), `check_error` (`checks.as_ref().err().map(ToString::to_string)`), `review` (`review.as_ref().and_then(|review| review.as_ref().ok())`).
- in `support`, compute the evaluator digest with the reviewer identity:

```rust
        let worker = self.ports.worker_identity();
        let evaluator_digest = digest_of(
            "evaluator",
            &(receipts.evaluator_digest, reviewer::policy_digest(), &worker.model, &worker.effort),
        );
```

  and use `evaluator_digest` in the `Coordinate`.
- leave `record_status` (the `status` record) as the only `put_record` caller.

`ReviewVerdict` and `CheckReceipts` must derive `Serialize`; add it to `ReviewVerdict` and its parts if missing.

- [ ] **Step 4: Run the extension tests**

Run: `cd codex-rs && just test -p codex-pro-contract-extension`
Expected: PASS, including the two new tests and the updated intake test.

- [ ] **Step 5: Format, lint, lock, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-extension && cd .. && just bazel-lock-update
git add -A codex-rs/ext/pro-contract codex-rs/Cargo.lock MODULE.bazel.lock
git commit -m "feat(pro-contract): record research data as events with producer identities

Intake, draft, issue and verification become immutable experiment
events carrying harness, policy and model identities; the reviewer's
policy, model and effort join the check pipeline in the certificate's
evaluator digest. Only operational status stays in records."
```

---

### Task 5: Measurement-relevant fixes in checks, residuals and review

**Files:**
- Modify: `codex-rs/ext/pro-contract/src/checks.rs`, `checks_tests.rs`, `src/workers/mod.rs`, `src/workers/reviewer.rs`,
  `src/workers/reviewer_tests.rs`, `src/controller/decision.rs`, `src/controller/decision_tests.rs`
- Create: `codex-rs/ext/pro-contract/src/workers/mod_tests.rs` (`#[cfg(test)] #[path = "mod_tests.rs"] mod tests;`
  in `workers/mod.rs`)

**Interfaces:**
- Produces: `pub(crate) fn bounded_head_tail(text: &str, cap: usize) -> String` (keeps `cap / 2` bytes from each end
  and notes how many were omitted); `pub(crate) const PRELUDE: &str` in `checks.rs`, the shell functions shared by every
  pipeline script.

- [ ] **Step 1: Write the failing tests**

`workers/mod_tests.rs`:

```rust
use pretty_assertions::assert_eq;

use super::bounded_head_tail;

#[test]
fn head_and_tail_survive_and_the_omission_is_stated() {
    let text = format!("HEAD{}TAIL", "x".repeat(1000));

    let bounded = bounded_head_tail(&text, 40);

    assert!(bounded.starts_with("HEAD"), "{bounded}");
    assert!(bounded.ends_with("TAIL"), "{bounded}");
    assert!(bounded.contains("bytes omitted"), "{bounded}");
}

#[test]
fn short_text_is_unchanged() {
    assert_eq!(bounded_head_tail("short", 40), "short");
}
```

Append to `checks_tests.rs`:

```rust
#[test]
fn a_failure_log_keeps_its_head_and_its_tail() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let log = dir.path().join("build.log");
    std::fs::write(&log, format!("FIRST\n{}\nLAST-ERROR\n", "noise\n".repeat(2000)))?;
    let output = std::process::Command::new("bash")
        .arg("-c")
        .arg(format!("{}\nlog build {}", super::PRELUDE, log.display()))
        .output()?;
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(stdout.contains("@@LOG build FIRST"), "{stdout}");
    assert!(stdout.contains("@@LOG build LAST-ERROR"), "{stdout}");
    assert!(stdout.contains("bytes omitted"), "{stdout}");
    Ok(())
}
```

Append to `reviewer_tests.rs`:

```rust
#[test]
fn the_prompt_respects_the_evidence_cap_and_says_what_to_do_about_omissions() {
    let huge = "x".repeat(super::super::PROMPT_EVIDENCE_CAP * 2);
    let terms = Terms {
        intake_text: huge.clone(),
        requirements: vec![],
        out_of_scope: vec![],
    };
    let input = ReviewInput {
        terms: &terms,
        check_summary: &huge,
        candidate_view: &huge,
    };

    let prompt = prompt(&input);

    assert!(prompt.len() <= super::super::PROMPT_EVIDENCE_CAP + 8_000, "{}", prompt.len());
    assert!(prompt.contains("omitted"), "the prompt must say what to do when file contents are omitted");
}
```

Use the file's existing imports (`ReviewInput`, `prompt`, `Terms`) and add any that are missing.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd codex-rs && just test -p codex-pro-contract-extension -- workers checks`
Expected: compile errors for `bounded_head_tail` and `PRELUDE`.

- [ ] **Step 3: Implement**

`workers/mod.rs`:

```rust
/// Keeps the first and last `cap / 2` bytes; errors usually sit at the end of a log.
pub(crate) fn bounded_head_tail(text: &str, cap: usize) -> String {
    if text.len() <= cap {
        return text.to_string();
    }
    let head = text.floor_char_boundary(cap / 2);
    let tail = text.ceil_char_boundary(text.len() - cap / 2);
    format!(
        "{}\n[... {} bytes omitted ...]\n{}",
        &text[..head],
        tail - head,
        &text[tail..]
    )
}
```

`checks.rs`: move the prelude out of `pipeline_script` into a constant. Keep every existing line, and replace the
`log()` function with a head-and-tail version:

```rust
/// Shell functions shared by every pipeline script.
pub(crate) const PRELUDE: &str = "set -u
emit() { printf '@@PC %s %s\\n' \"$1\" \"$2\"; }
log() { size=$(wc -c < \"$2\"); if [ \"$size\" -le 4000 ]; then cat \"$2\"; else head -c 2000 \"$2\"; printf '\\n[... %s bytes omitted ...]\\n' \"$((size - 4000))\"; tail -c 2000 \"$2\"; fi | awk -v prefix=\"@@LOG $1 \" '{ print prefix $0 }'; }
step() { log_file=$1; shift; timeout \"$STEP_TIMEOUT\" \"$@\" > \"$log_file\" 2>&1; rc=$?; if [ $rc -eq 124 ]; then { echo \"timed out after $STEP_TIMEOUT s\"; cat \"$log_file\"; } > \"$log_file.t\"; mv \"$log_file.t\" \"$log_file\"; fi; return $rc; }
for tool in 'rustc --version' 'cargo --version' 'uname -srm'; do printf '@@ENV %s\\n' \"$($tool 2>&1 | head -n 1)\"; done
export CARGO_NET_OFFLINE=true
";
```

`pipeline_script` then starts with `let mut script = String::from(PRELUDE);`, followed by the existing
`STEP_TIMEOUT=` line.

`controller/decision.rs`: in the failure residual, replace `bounded(failure.detail.trim_end(), 600)` with
`bounded_head_tail(failure.detail.trim_end(), 600)`.

`workers/reviewer.rs`: change the candidate share to `PROMPT_EVIDENCE_CAP * 7 / 16`. The shares now sum to exactly 1:
1/8 + 1/8 + 1/16 + 1/4 + 7/16. Append to `INSTRUCTIONS`:

```text
If the candidate view says file contents were omitted and a requirement depends on them, answer cannot_judge and name the omitted files in missing.
```

- [ ] **Step 4: Run the extension tests**

Run: `cd codex-rs && just test -p codex-pro-contract-extension`
Expected: PASS. The gated Docker tests still pass when run with
`PRO_CONTRACT_TEST_IMAGE=programbench/wfxr_1776_csview.8ac4de0:task_cleanroom`.

- [ ] **Step 5: Format, lint, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-extension
git add -A codex-rs/ext/pro-contract
git commit -m "fix(pro-contract): keep log tails, bound the review prompt, rule on omitted files"
```

---

### Task 6: The `pro-contract-store` CLI

**Files:**
- Create: `codex-rs/pro-contract-store/src/cli.rs`, `codex-rs/pro-contract-store/src/cli_tests.rs`,
  `codex-rs/pro-contract-store/src/bin/pro_contract_store.rs`
- Modify: `codex-rs/pro-contract-store/Cargo.toml` (adds `clap` with `derive`, `codex-utils-absolute-path` as a normal
  dependency, and tokio `macros` and `rt`), `codex-rs/pro-contract-store/src/lib.rs` (`pub mod cli;`)

**Interfaces:**
- Consumes: Tasks 2–3.
- Produces, for the Python wrapper:

```
pro-contract-store capture --store DIR --root PATH [--exclude P]...   → stdout {"subject_hash","manifest","capture_policy"}
pro-contract-store materialize --store DIR --subject HEX --dest DIR   → exit 0; exit 1 with an error on stderr
pro-contract-store append --store DIR   (an ExperimentEvent JSON on stdin) → stdout {"seq","hash"}
pro-contract-store events --store DIR   → stdout: a JSON array of {"seq","event","prev_hash","hash"}
pro-contract-store verify --store DIR   → exit 0 when the experiment chain verifies, else 1
```

`--store DIR` holds `ledger_1.sqlite` and `blobs/` (for example `CODEX_HOME/pro_contract`). Capture uses
`CapturePolicy::standard`.

- [ ] **Step 1: Write the failing tests** (`cli_tests.rs`)

```rust
use pretty_assertions::assert_eq;
use serde_json::json;

use super::append_command;
use super::capture_command;
use super::events_command;
use super::materialize_command;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test]
async fn capture_then_materialize_round_trips_after_reopening() -> TestResult {
    let dir = tempfile::tempdir()?;
    let root = dir.path().join("ws");
    std::fs::create_dir_all(&root)?;
    std::fs::write(root.join("main.rs"), "fn main() {}\n")?;
    std::fs::write(root.join("executable"), "reference")?;
    let store = dir.path().join("store");

    let captured = capture_command(&store, &root, &["executable".to_string()]).await?;
    std::fs::write(root.join("main.rs"), "changed after capture\n")?;
    let dest = dir.path().join("out");
    materialize_command(&store, &captured.subject_hash, &dest).await?;

    assert_eq!(std::fs::read_to_string(dest.join("main.rs"))?, "fn main() {}\n");
    assert!(!dest.join("executable").exists());
    Ok(())
}

#[tokio::test]
async fn materializing_an_unknown_subject_fails() -> TestResult {
    let dir = tempfile::tempdir()?;
    let unknown = codex_pro_contract::Digest::of(b"unknown").to_string();

    let result = materialize_command(&dir.path().join("store"), &unknown, &dir.path().join("out")).await;

    assert!(result.is_err());
    Ok(())
}

#[tokio::test]
async fn appended_events_are_listed() -> TestResult {
    let dir = tempfile::tempdir()?;
    let store = dir.path().join("store");
    let event = json!({
        "kind": "assignment",
        "identities": {"harness": null, "policies": {}, "model": null, "effort": null, "evaluator_epoch": null},
        "body": {"run_id": "r1"}
    });

    let appended = append_command(&store, &event.to_string()).await?;
    let listed = events_command(&store).await?;

    assert_eq!(appended.seq, 1);
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].event.body["run_id"], "r1");
    Ok(())
}
```


- [ ] **Step 2: Run them to verify they fail**

Run: `cd codex-rs && just test -p codex-pro-contract-store -- cli`
Expected: compile errors, because the `cli` module does not exist.

- [ ] **Step 3: Implement `cli.rs` and the binary**

`cli.rs`:

```rust
//! Logic behind the `pro-contract-store` operator CLI, which the Python runner uses to capture,
//! materialize and record against the same store the extension writes.

use std::path::Path;

use codex_pro_contract::Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Serialize;

use crate::BlobStore;
use crate::CapturePolicy;
use crate::ExperimentEvent;
use crate::ExperimentRecord;
use crate::Ledger;
use crate::SubjectBinding;
use crate::capture;
use crate::digest_of;
use crate::load_subject;
use crate::materialize;
use crate::persist_manifest;

pub type CliResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Debug, Serialize)]
pub struct Captured {
    pub subject_hash: String,
    pub manifest: String,
    pub capture_policy: String,
}

#[derive(Debug, Serialize)]
pub struct Appended {
    pub seq: i64,
    pub hash: String,
}

#[derive(Debug, Serialize)]
pub struct ListedEvent {
    pub seq: i64,
    pub event: ExperimentEvent,
    pub prev_hash: String,
    pub hash: String,
}

async fn open(store: &Path) -> CliResult<(Ledger, BlobStore)> {
    std::fs::create_dir_all(store)?;
    let absolute = AbsolutePathBuf::from_absolute_path(std::fs::canonicalize(store)?)?;
    let ledger = Ledger::open(&SqliteConfig::from_sqlite_home(absolute), store).await?;
    let blobs = BlobStore::open(&store.join("blobs"))?;
    Ok((ledger, blobs))
}

pub async fn capture_command(store: &Path, root: &Path, excluded: &[String]) -> CliResult<Captured> {
    let (ledger, blobs) = open(store).await?;
    let policy = CapturePolicy::standard(excluded.to_vec());
    let subject = capture(root, &policy, &blobs)?;
    let manifest = persist_manifest(&subject, &blobs)?;
    let capture_policy = digest_of("capture_policy", &policy);
    ledger
        .bind_subject(&subject.subject_hash, &SubjectBinding { manifest, capture_policy })
        .await?;
    Ok(Captured {
        subject_hash: subject.subject_hash.to_string(),
        manifest: manifest.to_string(),
        capture_policy: capture_policy.to_string(),
    })
}

pub async fn materialize_command(store: &Path, subject: &str, dest: &Path) -> CliResult<()> {
    let subject_hash = Digest::parse_hex(subject).ok_or("subject is not a digest")?;
    let (ledger, blobs) = open(store).await?;
    let binding = ledger
        .subject_binding(&subject_hash)
        .await?
        .ok_or_else(|| format!("subject {subject} is not bound in this store"))?;
    let subject = load_subject(&blobs, &binding.manifest, &subject_hash)?;
    std::fs::create_dir_all(dest)?;
    materialize(&subject, &blobs, dest)?;
    Ok(())
}

pub async fn append_command(store: &Path, event_json: &str) -> CliResult<Appended> {
    let event: ExperimentEvent = serde_json::from_str(event_json)?;
    let (ledger, _) = open(store).await?;
    let record = ledger.append_experiment(&event).await?;
    Ok(Appended { seq: record.seq, hash: record.hash.to_string() })
}

pub async fn events_command(store: &Path) -> CliResult<Vec<ListedEvent>> {
    let (ledger, _) = open(store).await?;
    Ok(ledger
        .experiments()
        .await?
        .into_iter()
        .map(|record: ExperimentRecord| ListedEvent {
            seq: record.seq,
            event: record.event,
            prev_hash: record.prev_hash.to_string(),
            hash: record.hash.to_string(),
        })
        .collect())
}

pub async fn verify_command(store: &Path) -> CliResult<()> {
    let (ledger, _) = open(store).await?;
    ledger.verify_experiment_chain().await?;
    Ok(())
}

#[cfg(test)]
#[path = "cli_tests.rs"]
mod tests;
```

`src/bin/pro_contract_store.rs`:

```rust
use std::io::Read;
use std::path::PathBuf;

use clap::Parser;
use clap::Subcommand;
use codex_pro_contract_store::cli;

#[derive(Parser)]
#[command(about = "Operator access to a ProContract store")]
struct Args {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    Capture {
        #[arg(long)]
        store: PathBuf,
        #[arg(long)]
        root: PathBuf,
        #[arg(long = "exclude")]
        exclude: Vec<String>,
    },
    Materialize {
        #[arg(long)]
        store: PathBuf,
        #[arg(long)]
        subject: String,
        #[arg(long)]
        dest: PathBuf,
    },
    Append {
        #[arg(long)]
        store: PathBuf,
    },
    Events {
        #[arg(long)]
        store: PathBuf,
    },
    Verify {
        #[arg(long)]
        store: PathBuf,
    },
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> cli::CliResult<()> {
    match Args::parse().command {
        Command::Capture { store, root, exclude } => {
            println!("{}", serde_json::to_string(&cli::capture_command(&store, &root, &exclude).await?)?);
        }
        Command::Materialize { store, subject, dest } => {
            cli::materialize_command(&store, &subject, &dest).await?;
        }
        Command::Append { store } => {
            let mut event = String::new();
            std::io::stdin().read_to_string(&mut event)?;
            println!("{}", serde_json::to_string(&cli::append_command(&store, &event).await?)?);
        }
        Command::Events { store } => {
            println!("{}", serde_json::to_string(&cli::events_command(&store).await?)?);
        }
        Command::Verify { store } => cli::verify_command(&store).await?,
    }
    Ok(())
}
```

Add to `Cargo.toml`:

```toml
[[bin]]
name = "pro-contract-store"
path = "src/bin/pro_contract_store.rs"
```

and to `[dependencies]`:

```toml
clap = { workspace = true, features = ["derive"] }
codex-utils-absolute-path = { workspace = true }
```

Change the normal-dependency tokio line to `features = ["fs", "macros", "rt"]`. Export `persist_manifest`,
`load_subject` and `SubjectBinding` if Task 2 did not already. `ExperimentEvent` must derive `Serialize`, which it does
(Task 3).

- [ ] **Step 4: Run the tests and build the binary**

Run: `cd codex-rs && just test -p codex-pro-contract-store && cargo build -p codex-pro-contract-store --bin pro-contract-store`
Expected: tests PASS. `target/debug/pro-contract-store --help` lists capture, materialize, append, events and verify.

- [ ] **Step 5: Format, lint, lock, commit**

```bash
cd codex-rs && just fmt && just fix -p codex-pro-contract-store && cd .. && just bazel-lock-update
git add -A codex-rs/pro-contract-store codex-rs/Cargo.lock MODULE.bazel.lock
git commit -m "feat(pro-contract): add the pro-contract-store operator CLI"
```

---

### Task 7: Evaluator pins, labelling with retries, and a fake evaluator (Python)

**Files:**
- Create: `scripts/procontract_store.py`, `scripts/procontract_evaluation.py`, `scripts/testing/fake_programbench.py`,
  `scripts/test_procontract_store.py`, `scripts/test_procontract_evaluation.py`

**Interfaces:**
- Consumes: Task 6's CLI. Tests locate it through `PRO_CONTRACT_STORE_BIN`, default
  `<repo>/codex-rs/target/debug/pro-contract-store`.
- Produces:
  - `procontract_store`: `capture(store: Path, root: Path, excluded: list[str]) -> dict`,
    `materialize(store: Path, subject: str, dest: Path) -> None`,
    `append(store: Path, kind: str, identities: dict, body: dict) -> dict`, `events(store: Path) -> list[dict]`,
    `identities(harness: str | None = None, model: str | None = None, effort: str | None = None, evaluator_epoch: str | None = None) -> dict`.
  - `procontract_evaluation`:
    - `current_pins(programbench: Path, instance: str, hf_cache: Path, image_id) -> dict`
    - `epoch(pins: dict) -> str` (64-hex sha256 of canonical JSON)
    - `PinDrift(Exception)`, `check_pins(pinned: dict, current: dict) -> None`
    - `parse_eval(eval_json: Path, log_text: str, instance: str) -> dict`
    - `classify(outcome: dict | None, known_branch_errors: set[str]) -> str` (`"valid"` | `"retry"`)
    - `evaluate_package(package: Path, instance: str, work: Path, programbench_cmd: list[str], programbench: Path, hf_revision: str, known_branch_errors: set[str], attempts: int = 3) -> dict`
    - `null_package(dest: Path) -> Path`
    - `label_key(run_id: str, subject: str, role: dict, evaluator_epoch: str) -> str`

**Label body**, a contract for Tasks 8, 10 and 11:

```json
{"label_key": "...", "run_id": "...", "instance": "...", "subject_hash": "...",
 "role": {"kind": "judged", "contract_id": "...", "generation": 1, "verdict": "support"}
       | {"kind": "final_workspace"} | {"kind": "null_sentinel"},
 "outcome": {"solved": false, "score": "99", "resolved": 348, "total": 354,
             "statuses": {"passed": 348, "failure": 3}, "branch_errors": ["efa8c407dbe3"]} | null,
 "validity": "valid" | "invalid", "reason": "", "attempts": 1}
```

- [ ] **Step 1: Write the fake evaluator**

`scripts/testing/fake_programbench.py`:

```python
#!/usr/bin/env python3
"""A stand-in for `programbench eval` with scripted outcomes.

Set FAKE_PROGRAMBENCH_PLAN to a JSON file
`{"<instance>": [{"score": "99", "solved": false, "branch_errors": [], "crash": false}, ...]}`.
Attempt n uses entry n; the last entry repeats. Each run records the submitted members into
`<dir>/<instance>/fake-seen.json`.
"""

import json
import os
import sys
import tarfile
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "eval":
        print("fake_programbench supports only `eval`", file=sys.stderr)
        return 2
    eval_dir = Path(args[1])
    instance = args[args.index("--filter") + 1].strip("^$").replace("\\.", ".")
    plan = json.loads(Path(os.environ["FAKE_PROGRAMBENCH_PLAN"]).read_text())
    counter = Path(os.environ["FAKE_PROGRAMBENCH_PLAN"] + f".{instance}.count")
    attempt = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(attempt + 1))
    steps = plan[instance]
    step = steps[min(attempt, len(steps) - 1)]
    if step.get("crash"):
        print("evaluator crashed", file=sys.stderr)
        return 1
    instance_dir = eval_dir / instance
    with tarfile.open(instance_dir / "submission.tar.gz") as archive:
        seen = {
            member.name: archive.extractfile(member).read().decode(errors="replace")
            for member in archive.getmembers()
            if member.isfile()
        }
    (instance_dir / "fake-seen.json").write_text(json.dumps(seen))
    resolved = 10 if step["solved"] else 9
    (instance_dir / f"{instance}.eval.json").write_text(
        json.dumps(
            {
                "test_results": [{"name": f"t{i}", "status": "passed" if i < resolved else "failure"} for i in range(10)],
                "test_branch_errors": {branch: "results_read_failed" for branch in step["branch_errors"]},
            }
        )
    )
    score = "✅" if step["solved"] else step["score"]
    print(f" {instance}    {score}  fake")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing tests**

`scripts/test_procontract_store.py`:

```python
import os
import tempfile
import unittest
from pathlib import Path

import procontract_store as store


class StoreWrapperTest(unittest.TestCase):
    def test_capture_materialize_and_events_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "ws")
            root.mkdir()
            Path(root, "main.rs").write_text("fn main() {}\n")
            Path(root, "executable").write_text("reference")
            st = Path(tmp, "store")

            captured = store.capture(st, root, ["executable"])
            Path(root, "main.rs").write_text("mutated\n")
            store.materialize(st, captured["subject_hash"], Path(tmp, "out"))
            store.append(st, "assignment", store.identities(), {"run_id": "r1"})

            self.assertEqual(Path(tmp, "out", "main.rs").read_text(), "fn main() {}\n")
            self.assertFalse(Path(tmp, "out", "executable").exists())
            self.assertEqual([e["event"]["body"]["run_id"] for e in store.events(st)], ["r1"])


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    unittest.main()
```

`scripts/test_procontract_evaluation.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import procontract_evaluation as evaluation

FAKE = [sys.executable, str(Path(__file__).parent / "testing" / "fake_programbench.py")]
INSTANCE = "owner__tool.abc1234"


def write_plan(tmp: str, steps: list[dict]) -> None:
    plan = Path(tmp, "plan.json")
    plan.write_text(json.dumps({INSTANCE: steps}))
    os.environ["FAKE_PROGRAMBENCH_PLAN"] = str(plan)


def package(tmp: str) -> Path:
    workspace = Path(tmp, "pkg-src")
    workspace.mkdir(exist_ok=True)
    Path(workspace, "compile.sh").write_text("#!/bin/sh\n")
    dest = Path(tmp, "submission.tar.gz")
    evaluation.package(workspace, dest)
    return dest


class PinTest(unittest.TestCase):
    def test_epoch_is_stable_and_drift_is_refused(self):
        pins = {"programbench_head": "a", "uv_lock_sha256": "b", "hf_revision": "c", "images": {"task": "d"}}
        self.assertEqual(evaluation.epoch(pins), evaluation.epoch(dict(reversed(list(pins.items())))))
        self.assertEqual(len(evaluation.epoch(pins)), 64)
        with self.assertRaises(evaluation.PinDrift):
            evaluation.check_pins(pins, {**pins, "hf_revision": "changed"})


class EvaluateTest(unittest.TestCase):
    def evaluate(self, tmp, steps, known=frozenset()):
        write_plan(tmp, steps)
        return evaluation.evaluate_package(
            package(tmp), INSTANCE, Path(tmp, "work"), FAKE, Path(tmp), "rev", set(known)
        )

    def test_a_clean_evaluation_is_valid_on_the_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(tmp, [{"score": "99", "solved": False, "branch_errors": []}])
        self.assertEqual((result["validity"], result["attempts"], result["outcome"]["score"]), ("valid", 1, "99"))

    def test_a_new_branch_error_is_retried_then_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(tmp, [{"score": "99", "solved": False, "branch_errors": ["b1"]}])
        self.assertEqual((result["validity"], result["attempts"]), ("invalid", 3))

    def test_a_transient_branch_error_recovers_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp,
                [
                    {"score": "99", "solved": False, "branch_errors": ["b1"]},
                    {"score": "99", "solved": False, "branch_errors": []},
                ],
            )
        self.assertEqual((result["validity"], result["attempts"]), ("valid", 2))

    def test_known_branch_error_from_null_sentinel_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(
                tmp, [{"score": "100", "solved": False, "branch_errors": ["efa8c407dbe3"]}], {"efa8c407dbe3"}
            )
        self.assertEqual((result["validity"], result["attempts"]), ("valid", 1))

    def test_an_evaluator_crash_counts_as_an_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.evaluate(tmp, [{"crash": True}, {"score": "✅", "solved": True, "branch_errors": []}])
        self.assertEqual((result["validity"], result["attempts"], result["outcome"]["solved"]), ("valid", 2, True))


class LabelKeyTest(unittest.TestCase):
    def test_label_keys_separate_roles_with_identical_bytes(self):
        judged = {"kind": "judged", "contract_id": "c", "generation": 1, "verdict": "support"}
        final = {"kind": "final_workspace"}
        self.assertNotEqual(
            evaluation.label_key("r", "s", judged, "e"), evaluation.label_key("r", "s", final, "e")
        )


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    unittest.main()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd scripts && PRO_CONTRACT_STORE_BIN=$PWD/../codex-rs/target/debug/pro-contract-store python3 -m unittest test_procontract_store test_procontract_evaluation`
Expected: `ModuleNotFoundError` for `procontract_store` and `procontract_evaluation`.

- [ ] **Step 4: Implement `procontract_store.py`**

```python
"""Python access to a ProContract store through the `pro-contract-store` CLI, so that hashing,
capture and the experiment chain have exactly one implementation."""

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BIN = REPO / "codex-rs" / "target" / "debug" / "pro-contract-store"


def store_bin() -> str:
    return os.environ.get("PRO_CONTRACT_STORE_BIN", str(DEFAULT_BIN))


def _run(args: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(
        [store_bin(), *args], input=stdin, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"pro-contract-store {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def identities(
    harness: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    evaluator_epoch: str | None = None,
) -> dict:
    return {
        "harness": harness,
        "policies": {},
        "model": model,
        "effort": effort,
        "evaluator_epoch": evaluator_epoch,
    }


def capture(store: Path, root: Path, excluded: list[str]) -> dict:
    args = ["capture", "--store", str(store), "--root", str(root)]
    for path in excluded:
        args += ["--exclude", path]
    return json.loads(_run(args))


def materialize(store: Path, subject: str, dest: Path) -> None:
    _run(["materialize", "--store", str(store), "--subject", subject, "--dest", str(dest)])


def append(store: Path, kind: str, identities: dict, body: dict) -> dict:
    event = {"kind": kind, "identities": identities, "body": body}
    return json.loads(_run(["append", "--store", str(store)], stdin=json.dumps(event)))


def events(store: Path) -> list[dict]:
    if not (store / "ledger_1.sqlite").exists():
        return []
    return json.loads(_run(["events", "--store", str(store)]))
```

- [ ] **Step 5: Implement `procontract_evaluation.py`**

```python
"""Evaluator pins, packaging and labelling of exact subjects (RSI spec §10, M0).

Labels attach to materialized subjects, never to live workspaces. Evaluation follows the frozen
M0 protocol: up to 2 re-evaluations for branch errors that the instance's null sentinel does
not explain, then `invalid`."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import procontract_store as store

ATTEMPTS = 3  # one evaluation plus up to 2 re-evaluations
SUBMISSION_EXCLUDED = ["./executable", "./target"]
HF_REF = "datasets--programbench--ProgramBench-Tests/refs/main"


class PinDrift(Exception):
    pass


def epoch(pins: dict) -> str:
    return hashlib.sha256(json.dumps(pins, sort_keys=True).encode()).hexdigest()


def current_pins(programbench: Path, instance: str, hf_cache: Path, image_id) -> dict:
    head = subprocess.run(
        ["git", "-C", str(programbench), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    base = f"programbench/{instance.replace('__', '_1776_')}"
    return {
        "programbench_head": head,
        "uv_lock_sha256": hashlib.sha256((programbench / "uv.lock").read_bytes()).hexdigest(),
        "hf_revision": (hf_cache / HF_REF).read_text().strip(),
        "images": {"task_cleanroom": image_id(f"{base}:task_cleanroom"), "task": image_id(f"{base}:task")},
    }


def check_pins(pinned: dict, current: dict) -> None:
    if pinned != current:
        changed = sorted(key for key in set(pinned) | set(current) if pinned.get(key) != current.get(key))
        raise PinDrift(f"evaluator pins drifted: {changed}")


def package(workspace: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    excludes = [f"--exclude={path}" for path in SUBMISSION_EXCLUDED]
    subprocess.run(
        ["tar", "--owner=0", "--group=0", "--numeric-owner", "--anchored", *excludes,
         "-czf", str(dest), "-C", str(workspace), "."],
        check=True,
    )


def null_package(dest: Path) -> Path:
    source = dest.parent / "null-src"
    source.mkdir(parents=True, exist_ok=True)
    (source / "compile.sh").write_text("#!/bin/sh\nprintf '#!/bin/sh\\nexit 1\\n' > executable\nchmod +x executable\n")
    package(source, dest)
    return dest


def parse_eval(eval_json: Path, log_text: str, instance: str) -> dict:
    data = json.loads(eval_json.read_text())
    statuses: dict[str, int] = {}
    for result in data.get("test_results") or []:
        statuses[result["status"]] = statuses.get(result["status"], 0) + 1
    match = re.search(rf"^\s*{re.escape(instance)}\s+(✅|\d+)", log_text, re.MULTILINE)
    score = match.group(1) if match else None
    errors = data.get("test_branch_errors") or {}
    return {
        "solved": score == "✅",
        "score": score,
        "resolved": statuses.get("passed", 0),
        "total": sum(statuses.values()),
        "statuses": statuses,
        "branch_errors": sorted(errors) if isinstance(errors, dict) else sorted(errors),
    }


def classify(outcome: dict | None, known_branch_errors: set[str]) -> str:
    if outcome is None or outcome["score"] is None:
        return "retry"
    return "retry" if set(outcome["branch_errors"]) - known_branch_errors else "valid"


def evaluate_package(
    package_path: Path,
    instance: str,
    work: Path,
    programbench_cmd: list[str],
    programbench: Path,
    hf_revision: str,
    known_branch_errors: set[str],
    attempts: int = ATTEMPTS,
) -> dict:
    outcome = None
    for attempt in range(1, attempts + 1):
        eval_dir = work / f"attempt-{attempt}"
        (eval_dir / instance).mkdir(parents=True, exist_ok=True)
        shutil.copy(package_path, eval_dir / instance / "submission.tar.gz")
        log = eval_dir / "eval.log"
        with log.open("w") as out:
            done = subprocess.run(
                [*programbench_cmd, "eval", str(eval_dir), "--filter", f"^{re.escape(instance)}$",
                 "-w", "1", "-b", "1", "--docker-cpus", "4"],
                cwd=programbench, stdout=out, stderr=subprocess.STDOUT,
                env={**os.environ, "PROGRAMBENCH_HF_REVISION": hf_revision}, check=False,
            )
        eval_json = eval_dir / instance / f"{instance}.eval.json"
        outcome = parse_eval(eval_json, log.read_text(), instance) if done.returncode == 0 and eval_json.exists() else None
        if classify(outcome, known_branch_errors) == "valid":
            return {"outcome": outcome, "validity": "valid", "reason": "", "attempts": attempt}
    reason = "evaluator failed" if outcome is None else f"branch errors {outcome['branch_errors']}"
    return {"outcome": outcome, "validity": "invalid", "reason": reason, "attempts": attempts}


def label_key(run_id: str, subject: str, role: dict, evaluator_epoch: str) -> str:
    return hashlib.sha256(json.dumps([run_id, subject, role, evaluator_epoch], sort_keys=True).encode()).hexdigest()
```


- [ ] **Step 6: Run the tests**

Run: `cd codex-rs && cargo build -p codex-pro-contract-store --bin pro-contract-store && cd ../scripts && PRO_CONTRACT_STORE_BIN=$PWD/../codex-rs/target/debug/pro-contract-store python3 -m unittest test_procontract_store test_procontract_evaluation`
Expected: OK (9 tests).

- [ ] **Step 7: Lint and commit**

```bash
cd scripts && uv run --frozen --project . ruff format procontract_store.py procontract_evaluation.py testing/fake_programbench.py test_procontract_store.py test_procontract_evaluation.py && uv run --frozen --project . ruff check procontract_store.py procontract_evaluation.py testing/fake_programbench.py test_procontract_store.py test_procontract_evaluation.py
cd .. && git add scripts && git commit -m "feat(scripts): pin the evaluator and evaluate exact packages with the M0 retry protocol"
```

---

### Task 8: Generalize the runner; label a run's judged and final subjects

**Files:**
- Modify: `scripts/procontract_benchmark_runner.py`, `scripts/test_procontract_benchmark_runner.py`,
  `scripts/procontract_evaluation.py`, `scripts/test_procontract_evaluation.py`

**Interfaces:**
- Consumes: Task 7.
- Produces:
  - in the runner: `cleanroom_image(instance) -> str`, `task_image(instance) -> str`,
    `ensure_images(instance) -> None` (pulls missing images; raises on failure),
    `lane_silent(arm, status, first_completion_at, now, limit=600.0) -> bool`, `rollout_costs(codex_home: Path) -> dict`,
    `TurnTracker.statuses: list[str]`;
  - in `procontract_evaluation`: `label_run(run_dir, batch_store, run_id, instance, evaluator_epoch, programbench_cmd, programbench, hf_revision, known_branch_errors, identities) -> list[dict]`,
    which returns the Label bodies it appended.

- [ ] **Step 1: Write the failing tests**

Append to `test_procontract_benchmark_runner.py`:

```python
class InstanceTest(unittest.TestCase):
    def test_images_follow_programbench_naming(self):
        self.assertEqual(
            runner.cleanroom_image("wfxr__csview.8ac4de0"),
            "programbench/wfxr_1776_csview.8ac4de0:task_cleanroom",
        )
        self.assertEqual(runner.task_image("a__b.c"), "programbench/a_1776_b.c:task")


class SilentLaneTest(unittest.TestCase):
    def test_on_arm_without_status_ten_minutes_after_handoff_is_silent(self):
        self.assertFalse(runner.lane_silent("on", None, None, 1000.0))
        self.assertFalse(runner.lane_silent("on", None, 100.0, 699.0))
        self.assertTrue(runner.lane_silent("on", None, 100.0, 700.0))
        self.assertFalse(runner.lane_silent("on", {"resting": False}, 100.0, 9999.0))
        self.assertFalse(runner.lane_silent("off", None, 100.0, 9999.0))


class TurnStatusTest(unittest.TestCase):
    def test_completed_turn_statuses_are_recorded(self):
        tracker = runner.TurnTracker("t")
        tracker.observe({"method": "turn/completed", "params": {"threadId": "t", "turn": {"id": "1", "status": "interrupted"}}})
        self.assertEqual(tracker.statuses, ["interrupted"])


class CostTest(unittest.TestCase):
    def test_rollout_costs_split_executor_and_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp, "sessions", "2026", "10", "01")
            sessions.mkdir(parents=True)
            usage = {"input_tokens": 10, "cached_input_tokens": 4, "output_tokens": 2, "reasoning_output_tokens": 1, "total_tokens": 12}
            for name, source in [("rollout-a.jsonl", "vscode"), ("rollout-b.jsonl", {"internal": "extension_worker"})]:
                Path(sessions, name).write_text(
                    json.dumps({"type": "session_meta", "payload": {"source": source}}) + "\n"
                    + json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": usage}}}) + "\n"
                )
            costs = runner.rollout_costs(Path(tmp))
        self.assertEqual(costs["executor"]["total_tokens"], 12)
        self.assertEqual((costs["workers"]["total_tokens"], costs["worker_rollouts"]), (12, 1))

    def test_the_runner_has_no_future_import(self):
        self.assertNotIn("from __future__", Path(runner.__file__).read_text())
```

Append to `test_procontract_evaluation.py`:

```python
import procontract_store as store


class LabelRunTest(unittest.TestCase):
    def run_dir_with_judgment(self, tmp: str) -> tuple[Path, str]:
        run_dir = Path(tmp, "run")
        workspace = run_dir / "workspace"
        workspace.mkdir(parents=True)
        Path(workspace, "answer.txt").write_text("judged")
        run_store = run_dir / "codex-home" / "pro_contract"
        captured = store.capture(run_store, workspace, ["executable", "target", ".git"])
        store.append(
            run_store,
            "verification",
            {**store.identities(model="m"), "policies": {"reviewer": "00" * 32}},
            {"contract_id": "c1", "generation": 1, "subject_hash": captured["subject_hash"], "verdict": "support"},
        )
        Path(workspace, "answer.txt").write_text("edited after freezing")
        return run_dir, captured["subject_hash"]

    def label(self, tmp, run_dir, steps, known=frozenset()):
        write_plan(tmp, steps)
        return evaluation.label_run(
            run_dir, Path(tmp, "batch-store"), "r1", INSTANCE, "ee" * 32, FAKE, Path(tmp), "rev", set(known),
            store.identities(),
        )

    def test_the_judged_subject_is_labelled_from_its_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, judged = self.run_dir_with_judgment(tmp)
            labels = self.label(tmp, run_dir, [{"score": "99", "solved": False, "branch_errors": []}])
            seen_file = run_dir / "labels" / judged / "eval" / "attempt-1" / INSTANCE / "fake-seen.json"
            seen = json.loads(seen_file.read_text())
        roles = sorted(label["role"]["kind"] for label in labels)
        self.assertEqual(roles, ["final_workspace", "judged"])
        self.assertEqual(seen["./answer.txt"], "judged")

    def test_label_run_labels_final_workspace_without_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            Path(run_dir, "workspace").mkdir(parents=True)
            Path(run_dir, "workspace", "main.rs").write_text("x")
            labels = self.label(tmp, run_dir, [{"score": "70", "solved": False, "branch_errors": []}])
        self.assertEqual([label["role"]["kind"] for label in labels], ["final_workspace"])

    def test_labelling_twice_does_not_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir, _ = self.run_dir_with_judgment(tmp)
            self.label(tmp, run_dir, [{"score": "99", "solved": False, "branch_errors": []}])
            again = self.label(tmp, run_dir, [{"score": "99", "solved": False, "branch_errors": []}])
            labels = [e for e in store.events(Path(tmp, "batch-store")) if e["event"]["kind"] == "label"]
        self.assertEqual((again, len(labels)), ([], 2))

    def test_a_missing_subject_gives_an_invalid_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            Path(run_dir, "workspace").mkdir(parents=True)
            run_store = run_dir / "codex-home" / "pro_contract"
            store.append(
                run_store, "verification", {**store.identities(model="m"), "policies": {"reviewer": "00" * 32}},
                {"contract_id": "c1", "generation": 1, "subject_hash": "ab" * 32, "verdict": "defeat"},
            )
            labels = self.label(tmp, run_dir, [{"score": "70", "solved": False, "branch_errors": []}])
        judged = [label for label in labels if label["role"]["kind"] == "judged"]
        self.assertEqual((judged[0]["validity"], "not bound" in judged[0]["reason"]), ("invalid", True))

    def test_unreadable_workspace_gives_an_invalid_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp, "run")
            secret = Path(run_dir, "workspace", "secret")
            secret.parent.mkdir(parents=True)
            secret.write_text("x")
            secret.chmod(0)
            try:
                labels = self.label(tmp, run_dir, [{"score": "70", "solved": False, "branch_errors": []}])
            finally:
                secret.chmod(0o600)
        self.assertEqual((labels[0]["validity"], labels[0]["outcome"]), ("invalid", None))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts && PRO_CONTRACT_STORE_BIN=$PWD/../codex-rs/target/debug/pro-contract-store python3 -m unittest test_procontract_benchmark_runner test_procontract_evaluation`
Expected: AttributeErrors (`cleanroom_image`, `lane_silent`, `rollout_costs`, `label_run`) and the future-import test
failing.

- [ ] **Step 3: Implement**

**Runner** (`procontract_benchmark_runner.py`):
- Delete `from __future__ import annotations`.
- Add the helpers:

```python
def cleanroom_image(instance: str) -> str:
    return f"programbench/{instance.replace('__', '_1776_')}:task_cleanroom"


def task_image(instance: str) -> str:
    return f"programbench/{instance.replace('__', '_1776_')}:task"


def ensure_images(instance: str) -> None:
    for image in (cleanroom_image(instance), task_image(instance)):
        present = subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0
        if not present:
            subprocess.run(["docker", "pull", image], check=True)


def lane_silent(arm: str, status: dict | None, first_completion_at: float | None, now: float, limit: float = 600.0) -> bool:
    """The ON lane never wrote a status record long after the executor handed off."""
    return arm == "on" and status is None and first_completion_at is not None and now - first_completion_at >= limit


def rollout_costs(codex_home: Path) -> dict:
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
    totals = {"executor": dict.fromkeys(keys, 0), "workers": dict.fromkeys(keys, 0), "worker_rollouts": 0}
    for path in sorted((codex_home / "sessions").rglob("rollout-*.jsonl")):
        source, usage = None, None
        for line in path.open():
            record = json.loads(line)
            payload = record.get("payload", {})
            if record.get("type") == "session_meta":
                source = payload.get("source")
            elif record.get("type") == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
                usage = payload["info"]["total_token_usage"]
        worker = isinstance(source, dict) and source.get("internal") == "extension_worker"
        totals["worker_rollouts"] += 1 if worker else 0
        for key in keys:
            totals["workers" if worker else "executor"][key] += (usage or {}).get(key, 0)
    return totals
```

- In `TurnTracker`, add `self.statuses: list[str] = []` and, in the `turn/completed` branch,
  `self.statuses.append(params["turn"].get("status", "unknown"))`.
- `main`:
  - drop the `INSTANCE` and `CLEANROOM_IMAGE` defaults;
  - make `--instance` required;
  - make `--image` default to `None`;
  - after parsing, set `args.image = args.image or cleanroom_image(args.instance)` and default `args.run_dir` to
    `ARTIFACTS / "runs" / f"{args.instance}-{args.arm}"`;
  - remove the `evaluate` subcommand (labelling now lives in `procontract_evaluation.label_run`, called by the batch).
- `prepare` calls `ensure_images(args.instance)` before the `docker run`.
- `run`:
  - record `first_completion_at = time.monotonic()` when `turns.completed` first becomes 1;
  - in the status poll, `if lane_silent(args.arm, status, first_completion_at, now): summary["stopped"] = "no_status_record"; break`;
  - add `turn_statuses=turns.statuses` and `cost=rollout_costs(home)` to `summary.update(...)`.

**Evaluation** (`procontract_evaluation.py`): add `label_run`:

```python
CAPTURE_EXCLUDED = ["executable", "target", ".git"]


def label_run(
    run_dir: Path,
    batch_store: Path,
    run_id: str,
    instance: str,
    evaluator_epoch: str,
    programbench_cmd: list[str],
    programbench: Path,
    hf_revision: str,
    known_branch_errors: set[str],
    identities: dict,
) -> list[dict]:
    """Labels every judged subject and the final workspace of one run; returns the new labels."""
    run_store = run_dir / "codex-home" / "pro_contract"
    existing = {
        event["event"]["body"].get("label_key")
        for event in store.events(batch_store)
        if event["event"]["kind"] == "label"
    }
    targets: list[tuple[dict, str | None, str]] = []
    for event in store.events(run_store):
        body = event["event"]["body"]
        if event["event"]["kind"] == "verification":
            role = {"kind": "judged", "contract_id": body["contract_id"], "generation": body["generation"], "verdict": body["verdict"]}
            targets.append((role, body["subject_hash"], ""))
    try:
        final = store.capture(run_store, run_dir / "workspace", CAPTURE_EXCLUDED)["subject_hash"]
        store.append(batch_store, "capture", identities, {"run_id": run_id, "subject_hash": final, "purpose": "final_workspace"})
        targets.append(({"kind": "final_workspace"}, final, ""))
    except RuntimeError as error:
        targets.append(({"kind": "final_workspace"}, None, f"capture failed: {error}"))
    results: dict[str, dict] = {}
    labels = []
    for role, subject, failure in targets:
        key = label_key(run_id, subject or "", role, evaluator_epoch)
        if key in existing:
            continue
        if subject is None:
            result = {"outcome": None, "validity": "invalid", "reason": failure, "attempts": 0}
        elif subject not in results:
            source = run_dir / "labels" / subject / "source"
            try:
                shutil.rmtree(source, ignore_errors=True)
                store.materialize(run_store, subject, source)
                archive = run_dir / "labels" / subject / "submission.tar.gz"
                package(source, archive)
                results[subject] = evaluate_package(
                    archive, instance, run_dir / "labels" / subject / "eval", programbench_cmd, programbench,
                    hf_revision, known_branch_errors,
                )
            except RuntimeError as error:
                results[subject] = {"outcome": None, "validity": "invalid", "reason": str(error), "attempts": 0}
            result = results[subject]
        else:
            result = results[subject]
        body = {"label_key": key, "run_id": run_id, "instance": instance, "subject_hash": subject, "role": role, **result}
        store.append(batch_store, "label", {**identities, "evaluator_epoch": evaluator_epoch}, body)
        labels.append(body)
    return labels
```

When `subject` is set but materialization fails, the CLI's error message contains "is not bound in this store", which
satisfies the missing-subject test. Bytes evaluated once per distinct subject are reused across roles. Each role still
gets its own Label with its own key; nothing is joined by hash alone.

- [ ] **Step 4: Run the tests**

Run: `cd scripts && PRO_CONTRACT_STORE_BIN=$PWD/../codex-rs/target/debug/pro-contract-store python3 -m unittest test_procontract_benchmark_runner test_procontract_evaluation test_procontract_store`
Expected: OK. In the existing runner tests, update the `app_server_command` and CodexHome tests only if their
signatures changed; they should not.

- [ ] **Step 5: Lint and commit**

```bash
cd scripts && uv run --frozen --project . ruff format . && uv run --frozen --project . ruff check procontract_*.py test_procontract_*.py testing
cd .. && git add scripts && git commit -m "feat(scripts): label each run's judged and final subjects; generalize the runner to any Rust instance"
```

---

### Task 9: Sealed pools and the seen-list

**Files:**
- Create: `scripts/procontract_pools.py`, `scripts/test_procontract_pools.py`

**Interfaces:**
- Produces:
  - `seen_ids(paths: list[Path], known: set[str]) -> set[str]`
  - `split(tasks: list[dict], seen: set[str], salt: str, ratios: tuple[int, int, int]) -> dict` returning
    `{"dev": [...], "select": [...], "confirm": [...]}`
  - `commitment(salt: str, ids: list[str]) -> str`
  - CLI: `seen --tasks-dir T --scan P... --out F`
  - CLI: `split --tasks-dir T --language rs --seen F --salt-file S --ratios 40,30,30 --public-out F --sealed-out F`
- Only `task.yaml` is read, and only `repository`, `language` and `difficulty`. The scan skips any path containing
  `tests`.

- [ ] **Step 1: Write the failing tests**

```python
import tempfile
import unittest
from pathlib import Path

import procontract_pools as pools


def task(i: int, difficulty: str = "easy") -> dict:
    return {"id": f"o{i}__r{i}.abc{i:04d}", "repository": f"o{i}/r{i}", "language": "rs", "difficulty": difficulty}


class SplitTest(unittest.TestCase):
    def test_split_is_deterministic_stratified_and_seen_goes_to_dev(self):
        tasks = [task(i, "easy" if i % 2 else "hard") for i in range(40)]
        seen = {tasks[0]["id"], tasks[1]["id"]}

        first = pools.split(tasks, seen, "salt", (40, 30, 30))
        second = pools.split(tasks, seen, "salt", (40, 30, 30))
        other = pools.split(tasks, seen, "other-salt", (40, 30, 30))

        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertTrue(seen <= set(first["dev"]))
        self.assertEqual(sorted(first["dev"] + first["select"] + first["confirm"]), sorted(t["id"] for t in tasks))
        # 19 non-seen tasks per stratum: dev round(7.6)=8, select round(5.7)=6, confirm 5.
        self.assertEqual((len(first["select"]), len(first["confirm"])), (12, 10))

    def test_commitments_hide_lists_but_bind_them(self):
        self.assertNotIn("o1", pools.commitment("salt", ["o1__r1.abc0001"]))
        self.assertNotEqual(pools.commitment("salt", ["a"]), pools.commitment("salt", ["b"]))


class SeenTest(unittest.TestCase):
    def test_seen_ids_come_from_artifacts_but_never_from_tests_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "report.md").write_text("ran wfxr__csview.8ac4de0 and junk__x.zzzzzzz")
            Path(tmp, "tests").mkdir()
            Path(tmp, "tests", "list.json").write_text("sharkdp__hexyl.1234567")
            found = pools.seen_ids([Path(tmp)], {"wfxr__csview.8ac4de0", "sharkdp__hexyl.1234567"})
        self.assertEqual(found, {"wfxr__csview.8ac4de0"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts && python3 -m unittest test_procontract_pools`
Expected: `ModuleNotFoundError: procontract_pools`.

- [ ] **Step 3: Implement `procontract_pools.py`**

```python
#!/usr/bin/env python3
"""Seen-list and sealed, salted pool split (RSI spec §10 item 6).

Reads only `repository`, `language` and `difficulty` from `task.yaml`; never `tests.json`."""

import argparse
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

import yaml

ID = re.compile(r"[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+\.[0-9a-f]{7}")
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".tex", ".csv", ".log"}
MAX_SCAN_BYTES = 5 << 20


def load_tasks(tasks_dir: Path, language: str) -> list[dict]:
    tasks = []
    for path in sorted(tasks_dir.glob("*/task.yaml")):
        data = yaml.safe_load(path.read_text())
        if data.get("language") == language:
            tasks.append(
                {"id": path.parent.name, "repository": data["repository"], "language": data["language"],
                 "difficulty": data.get("difficulty") or "unknown"}
            )
    return tasks


def seen_ids(paths: list[Path], known: set[str]) -> set[str]:
    found: set[str] = set()
    for root in paths:
        for path in [root] if root.is_file() else root.rglob("*"):
            if "tests" in path.parts or not path.is_file() or path.suffix not in TEXT_SUFFIXES:
                continue
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            found |= set(ID.findall(path.read_text(errors="ignore"))) & known
    return found


def _rank(salt: str, repository: str) -> str:
    return hashlib.sha256(f"{salt}\0{repository}".encode()).hexdigest()


def split(tasks: list[dict], seen: set[str], salt: str, ratios: tuple[int, int, int]) -> dict:
    result: dict[str, list[str]] = {"dev": [], "select": [], "confirm": []}
    strata: dict[str, list[dict]] = {}
    for task in tasks:
        if task["id"] in seen:
            result["dev"].append(task["id"])
        else:
            strata.setdefault(task["difficulty"], []).append(task)
    total = sum(ratios)
    for difficulty in sorted(strata):
        ranked = sorted(strata[difficulty], key=lambda task: _rank(salt, task["repository"]))
        dev_n = round(len(ranked) * ratios[0] / total)
        select_n = round(len(ranked) * ratios[1] / total)
        result["dev"] += [t["id"] for t in ranked[:dev_n]]
        result["select"] += [t["id"] for t in ranked[dev_n : dev_n + select_n]]
        result["confirm"] += [t["id"] for t in ranked[dev_n + select_n :]]
    return {name: sorted(ids) for name, ids in result.items()}


def commitment(salt: str, ids: list[str]) -> str:
    return hashlib.sha256(f"{salt}\0{json.dumps(sorted(ids))}".encode()).hexdigest()


def _salt(path: Path) -> str:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        os.chmod(path, 0o600)
    return path.read_text().strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seen = sub.add_parser("seen")
    seen.add_argument("--tasks-dir", type=Path, required=True)
    seen.add_argument("--scan", type=Path, nargs="+", required=True)
    seen.add_argument("--out", type=Path, required=True)
    sp = sub.add_parser("split")
    sp.add_argument("--tasks-dir", type=Path, required=True)
    sp.add_argument("--language", default="rs")
    sp.add_argument("--seen", type=Path, required=True)
    sp.add_argument("--salt-file", type=Path, required=True)
    sp.add_argument("--ratios", default="40,30,30")
    sp.add_argument("--public-out", type=Path, required=True)
    sp.add_argument("--sealed-out", type=Path, required=True)
    args = parser.parse_args()
    known = {path.parent.name for path in args.tasks_dir.glob("*/task.yaml")}
    if args.command == "seen":
        args.out.write_text(json.dumps(sorted(seen_ids(args.scan, known)), indent=2) + "\n")
        return
    tasks = load_tasks(args.tasks_dir, args.language)
    salt = _salt(args.salt_file)
    ratios = tuple(int(part) for part in args.ratios.split(","))
    pools = split(tasks, set(json.loads(args.seen.read_text())), salt, ratios)
    args.sealed_out.parent.mkdir(parents=True, exist_ok=True)
    args.sealed_out.write_text(json.dumps(pools, indent=2) + "\n")
    os.chmod(args.sealed_out, 0o600)
    public = {
        "language": args.language,
        "ratios": ratios,
        "dev": pools["dev"],
        "counts": {name: len(ids) for name, ids in pools.items()},
        "commitments": {name: commitment(salt, pools[name]) for name in ("select", "confirm")},
        "difficulty": {task["id"]: task["difficulty"] for task in tasks if task["id"] in pools["dev"]},
    }
    args.public_out.write_text(json.dumps(public, indent=2) + "\n")


if __name__ == "__main__":
    main()
```

PyYAML is available to the system `python3` (it already read `task.yaml` during planning). If it is not, run the
pools CLI with `uv run --with pyyaml python3 …`.

- [ ] **Step 4: Run the tests**

Run: `cd scripts && python3 -m unittest test_procontract_pools`
Expected: OK (3 tests).

- [ ] **Step 5: Lint and commit**

```bash
cd scripts && uv run --frozen --project . ruff format procontract_pools.py test_procontract_pools.py && uv run --frozen --project . ruff check procontract_pools.py test_procontract_pools.py
cd .. && git add scripts && git commit -m "feat(scripts): add the sealed, salted pool split and the seen-list"
```

---

### Task 10: Batch orchestrator with reconciliation

**Files:**
- Create: `scripts/procontract_batch.py`, `scripts/testing/fake_runner.py`, `scripts/test_procontract_batch.py`

**Interfaces:**
- Consumes: Tasks 7–9, and the runner CLI (`prepare|run`).
- Produces:
  - `plan_runs(dev: list[str], difficulty: dict[str, str], n: int, duplicates: int, seed: int) -> list[dict]` with run
    fields `run_id`, `instance`, `arm`, `repeat` and `order`;
  - `next_action(state: dict, protocol: dict) -> str`, returning `"prepare"`, `"run"`, `"label"`, `"done"` or
    `"invalid"`;
  - `BatchLock(batch_dir)`, a context manager that raises `RuntimeError` when the batch is already locked;
  - the CLI: `plan`, `run`, `null` and `status`.
- **Frozen protocol** in `batch.json` (Global Constraints):

```json
{"retries": {"eval_branch_error": 2, "run_crash": 1}, "duplicates_per_arm": 4,
 "pool_ratios": [40, 30, 30], "exposure": "every corpus instance"}
```

- **Run state file** `runs/<run_id>/state.json`:
  `{"phase": "planned|prepared|ran|labelled|invalid", "attempt": 1, "reason": ""}`

- [ ] **Step 1: Write the failing tests**

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import procontract_batch as batch

PROTOCOL = {"retries": {"eval_branch_error": 2, "run_crash": 1}, "duplicates_per_arm": 4}


class PlanTest(unittest.TestCase):
    def test_plan_is_seeded_balanced_and_duplicates_four_instances_per_arm(self):
        dev = [f"o{i}__r{i}.abc{i:04d}" for i in range(40)]
        difficulty = {i: ("easy" if n % 2 else "hard") for n, i in enumerate(dev)}

        runs = batch.plan_runs(dev, difficulty, 30, 4, seed=7)

        self.assertEqual(runs, batch.plan_runs(dev, difficulty, 30, 4, seed=7))
        self.assertEqual(len(runs), 30 * 2 + 4 * 2)
        self.assertEqual(sorted(r["order"] for r in runs), list(range(len(runs))))
        repeats = [r for r in runs if r["repeat"] == 2]
        self.assertEqual(sorted({(r["arm"]) for r in repeats}), ["off", "on"])
        self.assertEqual(len(repeats), 8)


class ReconcileTest(unittest.TestCase):
    def test_actions_follow_the_state_machine_and_crash_budget(self):
        self.assertEqual(batch.next_action({"phase": "planned", "attempt": 1}, PROTOCOL), "prepare")
        self.assertEqual(batch.next_action({"phase": "prepared", "attempt": 1}, PROTOCOL), "run")
        self.assertEqual(batch.next_action({"phase": "ran", "attempt": 1}, PROTOCOL), "label")
        self.assertEqual(batch.next_action({"phase": "labelled", "attempt": 1}, PROTOCOL), "done")
        self.assertEqual(batch.next_action({"phase": "running", "attempt": 1}, PROTOCOL), "prepare")
        self.assertEqual(batch.next_action({"phase": "running", "attempt": 2}, PROTOCOL), "invalid")


class LockTest(unittest.TestCase):
    def test_second_batch_process_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            with batch.BatchLock(Path(tmp)):
                with self.assertRaises(RuntimeError):
                    with batch.BatchLock(Path(tmp)):
                        pass


class RunBatchTest(unittest.TestCase):
    def setUp(self):
        for name in ("FAKE_RUNNER_FAIL_PREPARE", "FAKE_RUNNER_CRASH_ONCE"):
            os.environ.pop(name, None)

    def test_failed_prepare_is_invalid_and_the_batch_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            runs = [
                {"run_id": "r-bad", "instance": "bad__img.0000000", "arm": "on", "repeat": 1, "order": 0},
                {"run_id": "r-ok", "instance": "ok__img.0000000", "arm": "off", "repeat": 1, "order": 1},
            ]
            fake = [sys.executable, str(Path(__file__).parent / "testing" / "fake_runner.py")]
            os.environ["FAKE_RUNNER_FAIL_PREPARE"] = "bad__img.0000000"
            labelled = []

            batch.run_batch(batch_dir, runs, PROTOCOL, fake, label=lambda run, run_dir: labelled.append(run["run_id"]), parallel=1)

            state = {r["run_id"]: json.loads(Path(batch_dir, "runs", r["run_id"], "state.json").read_text()) for r in runs}
        self.assertEqual(state["r-bad"]["phase"], "invalid")
        self.assertIn("prepare failed", state["r-bad"]["reason"])
        self.assertEqual((state["r-ok"]["phase"], labelled), ("labelled", ["r-ok"]))

    def test_a_crashed_run_is_rerun_once_in_a_fresh_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp)
            runs = [{"run_id": "r1", "instance": "x__y.0000000", "arm": "on", "repeat": 1, "order": 0}]
            fake = [sys.executable, str(Path(__file__).parent / "testing" / "fake_runner.py")]
            os.environ["FAKE_RUNNER_CRASH_ONCE"] = str(Path(tmp, "crashed"))

            batch.run_batch(batch_dir, runs, PROTOCOL, fake, label=lambda run, run_dir: None, parallel=1)

            state = json.loads(Path(batch_dir, "runs", "r1", "state.json").read_text())
        self.assertEqual((state["phase"], state["attempt"]), ("labelled", 2))


if __name__ == "__main__":
    unittest.main()
```

`scripts/testing/fake_runner.py`:

```python
#!/usr/bin/env python3
"""Stands in for procontract_benchmark_runner.py in batch tests."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    command = sys.argv[1]
    args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
    run_dir = Path(args["--run-dir"])
    if command == "prepare":
        if os.environ.get("FAKE_RUNNER_FAIL_PREPARE") == args["--instance"]:
            print("image pull failed", file=sys.stderr)
            return 1
        (run_dir / "workspace").mkdir(parents=True, exist_ok=True)
        return 0
    marker = os.environ.get("FAKE_RUNNER_CRASH_ONCE")
    if marker and not Path(marker).exists():
        Path(marker).write_text("crashed")
        return 1
    (run_dir / "run.json").write_text(json.dumps({"turns_completed": 1, "turn_statuses": ["completed"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts && python3 -m unittest test_procontract_batch`
Expected: `ModuleNotFoundError: procontract_batch`.

- [ ] **Step 3: Implement `procontract_batch.py`**

```python
#!/usr/bin/env python3
"""M0 batch orchestration: a seeded plan, detached execution, batch-level reconciliation.

Launch long batches detached: `setsid nohup python3 procontract_batch.py run ... &`.
"Resumable" means batch-level reconciliation: completed runs are kept; interrupted attempts
are recorded and charged against the frozen crash budget (one rerun)."""

import argparse
import fcntl
import json
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROTOCOL = {
    "retries": {"eval_branch_error": 2, "run_crash": 1},
    "duplicates_per_arm": 4,
    "pool_ratios": [40, 30, 30],
    "exposure": "every corpus instance",
}


def plan_runs(dev: list[str], difficulty: dict[str, str], n: int, duplicates: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    strata: dict[str, list[str]] = {}
    for instance in sorted(dev):
        strata.setdefault(difficulty.get(instance, "unknown"), []).append(instance)
    chosen: list[str] = []
    for name in sorted(strata):
        quota = round(n * len(strata[name]) / len(dev))
        chosen += rng.sample(strata[name], min(quota, len(strata[name])))
    chosen = sorted(chosen)[:n]
    while len(chosen) < n:
        chosen.append(rng.choice(sorted(set(dev) - set(chosen))))
    doubled = set(rng.sample(sorted(chosen), duplicates))
    runs = [
        {"run_id": f"{instance}-{arm}-{repeat}", "instance": instance, "arm": arm, "repeat": repeat}
        for instance in chosen
        for arm in ("on", "off")
        for repeat in ((1, 2) if instance in doubled else (1,))
    ]
    order = list(range(len(runs)))
    rng.shuffle(order)
    for run, position in zip(runs, order):
        run["order"] = position
    return sorted(runs, key=lambda run: run["order"])


def next_action(state: dict, protocol: dict) -> str:
    phase = state["phase"]
    if phase in ("planned",):
        return "prepare"
    if phase == "prepared":
        return "run"
    if phase == "ran":
        return "label"
    if phase in ("labelled", "invalid"):
        return "done" if phase == "labelled" else "invalid"
    # Interrupted mid-prepare or mid-run: charge the crash budget.
    return "prepare" if state["attempt"] <= protocol["retries"]["run_crash"] else "invalid"


class BatchLock:
    def __init__(self, batch_dir: Path):
        self.path = batch_dir / ".lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.handle.close()
            raise RuntimeError(f"batch {self.path.parent} is already running") from error
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def _state(run_dir: Path) -> dict:
    path = run_dir / "state.json"
    return json.loads(path.read_text()) if path.exists() else {"phase": "planned", "attempt": 1, "reason": ""}


def _save(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(json.dumps(state, indent=2) + "\n")


def drive(run: dict, batch_dir: Path, protocol: dict, runner_cmd: list[str], label, extra_args: list[str]) -> dict:
    run_root = batch_dir / "runs" / run["run_id"]
    state = _state(run_root)
    while True:
        action = next_action(state, protocol)
        attempt_dir = run_root / f"attempt-{state['attempt']}"
        if action in ("done", "invalid"):
            if action == "invalid" and state["phase"] != "invalid":
                state.update(phase="invalid", reason=state.get("reason") or "run crashed twice")
                _save(run_root, state)
            return state
        if action == "prepare":
            if state["phase"] not in ("planned",):
                state["attempt"] += 1
                attempt_dir = run_root / f"attempt-{state['attempt']}"
            state["phase"] = "preparing"
            _save(run_root, state)
            done = subprocess.run(
                [*runner_cmd, "prepare", "--arm", run["arm"], "--instance", run["instance"], "--run-dir", str(attempt_dir), *extra_args],
                capture_output=True, text=True, check=False,
            )
            if done.returncode != 0:
                state.update(phase="invalid", reason=f"prepare failed: {done.stderr.strip()[-500:]}")
                _save(run_root, state)
                return state
            state["phase"] = "prepared"
        elif action == "run":
            state["phase"] = "running"
            _save(run_root, state)
            done = subprocess.run(
                [*runner_cmd, "run", "--arm", run["arm"], "--instance", run["instance"], "--run-dir", str(attempt_dir), *extra_args],
                capture_output=True, text=True, check=False,
            )
            if done.returncode != 0 or not (attempt_dir / "run.json").exists():
                _save(run_root, state)
                continue
            state["phase"] = "ran"
        elif action == "label":
            label(run, attempt_dir)
            state["phase"] = "labelled"
        _save(run_root, state)


def run_batch(batch_dir: Path, runs: list[dict], protocol: dict, runner_cmd: list[str], label, parallel: int, extra_args: list[str] = ()) -> list[dict]:
    with BatchLock(batch_dir):
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            return list(pool.map(lambda run: drive(run, batch_dir, protocol, runner_cmd, label, list(extra_args)), runs))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--pools", type=Path, required=True)
    plan.add_argument("--batch-dir", type=Path, required=True)
    plan.add_argument("--n", type=int, default=30)
    plan.add_argument("--seed", type=int, required=True)
    plan.add_argument("--codex-bin", type=Path, required=True)
    plan.add_argument("--prompt", type=Path, required=True)
    plan.add_argument("--programbench", type=Path, default=Path.home() / "ProgramBench")
    run = sub.add_parser("run")
    run.add_argument("--batch-dir", type=Path, required=True)
    run.add_argument("--parallel", type=int, default=4)
    run.add_argument("--deadline-secs", type=int, default=5 * 3600)
    null = sub.add_parser("null")
    null.add_argument("--batch-dir", type=Path, required=True)
    status = sub.add_parser("status")
    status.add_argument("--batch-dir", type=Path, required=True)
    args = parser.parse_args()
    {"plan": cmd_plan, "run": cmd_run, "null": cmd_null, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
```

Add the four commands to the same file. The extra top-level imports are `hashlib`, `os` and `shutil`, plus:

```python
import procontract_benchmark_runner as runner
import procontract_evaluation as evaluation
import procontract_store as store

OPERATOR = Path.home() / ".procontract-operator"
ARCHIVE = Path.home() / ".procontract-archive"  # outside ~/run-artifacts, out of any cleanup's reach
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
PROGRAMBENCH_CMD = ["uv", "run", "programbench"]


def _image_id(image: str) -> str:
    return subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True, check=True
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _phase_counts(states: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for state in states:
        counts[state["phase"]] = counts.get(state["phase"], 0) + 1
    return counts


def cmd_plan(args) -> None:
    pools = json.loads(args.pools.read_text())
    runs = plan_runs(pools["dev"], pools["difficulty"], args.n, PROTOCOL["duplicates_per_arm"], args.seed)
    instances = sorted({run["instance"] for run in runs})
    pins = {}
    for instance in instances:
        runner.ensure_images(instance)
        subprocess.run([*PROGRAMBENCH_CMD, "blob", "sync", instance], cwd=args.programbench, check=True, capture_output=True)
        pins[instance] = evaluation.current_pins(args.programbench, instance, HF_CACHE, _image_id)
    args.batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": PROTOCOL, "seed": args.seed,
        "codex_bin": str(args.codex_bin.resolve()), "codex_sha256": _sha256(args.codex_bin),
        "prompt": str(args.prompt.resolve()), "prompt_sha256": _sha256(args.prompt),
        "programbench": str(args.programbench), "pins": pins, "runs": runs,
    }
    (args.batch_dir / "batch.json").write_text(json.dumps(manifest, indent=2) + "\n")
    identities = store.identities(harness=manifest["codex_sha256"], model=runner.MODEL, effort=runner.EFFORT)
    for run in runs:
        store.append(args.batch_dir / "store", "assignment", identities, {**run, "pool": "dev", "seed": args.seed})
    OPERATOR.mkdir(parents=True, exist_ok=True)
    exposed_path = OPERATOR / "exposed.json"
    exposed = set(json.loads(exposed_path.read_text())) if exposed_path.exists() else set()
    exposed_path.write_text(json.dumps(sorted(exposed | set(instances)), indent=2) + "\n")


def cmd_null(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    programbench = Path(manifest["programbench"])
    known = {}
    for instance, pins in sorted(manifest["pins"].items()):
        work = args.batch_dir / "null" / instance
        archive = evaluation.null_package(work / "submission.tar.gz")
        # The null's own branch errors define the instance's known errors, so one attempt suffices.
        result = evaluation.evaluate_package(
            archive, instance, work / "eval", PROGRAMBENCH_CMD, programbench, pins["hf_revision"], set(), attempts=1
        )
        if result["outcome"] is not None:
            result.update(validity="valid", reason="")
        known[instance] = (result["outcome"] or {}).get("branch_errors", [])
        evaluator_epoch = evaluation.epoch(pins)
        role = {"kind": "null_sentinel"}
        body = {"label_key": evaluation.label_key("null", instance, role, evaluator_epoch), "run_id": None,
                "instance": instance, "subject_hash": None, "role": role, **result}
        store.append(args.batch_dir / "store", "label", store.identities(evaluator_epoch=evaluator_epoch), body)
    (args.batch_dir / "known_branch_errors.json").write_text(json.dumps(known, indent=2) + "\n")


def cmd_run(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    known = json.loads((args.batch_dir / "known_branch_errors.json").read_text())
    programbench = Path(manifest["programbench"])
    batch_store = args.batch_dir / "store"
    identities = store.identities(harness=manifest["codex_sha256"], model=runner.MODEL, effort=runner.EFFORT)

    def label(run: dict, run_dir: Path) -> None:
        pins = manifest["pins"][run["instance"]]
        evaluation.check_pins(pins, evaluation.current_pins(programbench, run["instance"], HF_CACHE, _image_id))
        summary = json.loads((run_dir / "run.json").read_text())
        store.append(batch_store, "execution", identities,
                     {"run_id": run["run_id"], "instance": run["instance"], "arm": run["arm"], "repeat": run["repeat"], **summary})
        evaluation.label_run(
            run_dir, batch_store, run["run_id"], run["instance"], evaluation.epoch(pins), PROGRAMBENCH_CMD,
            programbench, pins["hf_revision"], set(known.get(run["instance"], [])), identities,
        )
        source = run_dir / "codex-home" / "pro_contract"
        archive = ARCHIVE / args.batch_dir.name / run["run_id"]
        if source.exists() and not archive.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, archive, copy_function=os.link)

    runner_cmd = [sys.executable, str(Path(__file__).parent / "procontract_benchmark_runner.py")]
    extra = ["--codex-bin", manifest["codex_bin"], "--prompt", manifest["prompt"], "--deadline-secs", str(args.deadline_secs)]
    states = run_batch(args.batch_dir, manifest["runs"], manifest["protocol"], runner_cmd, label, args.parallel, extra)
    print(json.dumps(_phase_counts(states), indent=2))


def cmd_status(args) -> None:
    manifest = json.loads((args.batch_dir / "batch.json").read_text())
    by_arm: dict[str, list[dict]] = {}
    for run in manifest["runs"]:
        by_arm.setdefault(run["arm"], []).append(_state(args.batch_dir / "runs" / run["run_id"]))
    print(json.dumps({arm: _phase_counts(states) for arm, states in sorted(by_arm.items())}, indent=2))
```

A `PinDrift` raised inside `label` propagates out of the pool and stops the batch. The run stays `ran`, so the next
launch reconciles and relabels it after the operator restores the pins.

**Order on a real batch:** `plan` → `null` → `run`.

- [ ] **Step 4: Run the tests**

Run: `cd scripts && python3 -m unittest test_procontract_batch`
Expected: OK (5 tests).

- [ ] **Step 5: Lint and commit**

```bash
cd scripts && uv run --frozen --project . ruff format procontract_batch.py testing/fake_runner.py test_procontract_batch.py && uv run --frozen --project . ruff check procontract_batch.py testing/fake_runner.py test_procontract_batch.py
cd .. && git add scripts && git commit -m "feat(scripts): add the M0 batch orchestrator with reconciliation and a batch lock"
```

---

### Task 11: The M0 report and estimands

**Files:**
- Create: `scripts/procontract_m0_report.py`, `scripts/test_procontract_m0_report.py`

**Interfaces:**
- Consumes: the Label, Execution and Assignment events (Task 10) and the run stores' Verification events (Task 4).
- Produces:
  - `estimands(rows: list[dict], nulls: dict[str, float], seed: int = 0) -> dict`
  - `clustered_ci(values: dict[str, list[float]], seed: int, resamples: int = 2000) -> tuple[float, float, float]`
    returning point, low and high
  - the CLI: `report --batch-dir D --out REPORT-M0.md` and `revalidate --batch-dir D`
- **Row shape** for `estimands`:
  `{"task", "arm", "run_id", "role": "judged"|"final_workspace", "verdict": "support"|"defeat"|"not_verified"|None, "validity", "solved": bool|None, "score": float|None, "validated": bool|None, "cost_total": int}`

**Estimands** (spec §10 item 11):
- `solved_by_arm`: final-workspace labels counted per arm (valid / invalid / missing reported separately).
- `p_solved_given_supported`: judged rows with `verdict == "support"` and `validity == "valid"`.
- `missed_defect_rate`: 1 − p_solved_given_supported, over the same denominator.
- `validated_defeats`: judged defeats whose counterexample reproduced (`validated is True`) ÷ judged defeats that were
  checked.
- `disagreement`: defeated and solved ÷ valid defeats. This is not a false-defeat rate.
- `excluded`: counts of invalid and unknown rows.
- `score_above_null`: mean of `score − null[task]` per arm.
- Every proportion carries a 95 % CI from a bootstrap that resamples tasks.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

import procontract_m0_report as report


def row(task, arm, role, verdict=None, solved=False, validity="valid", score=80.0, validated=None):
    return {"task": task, "arm": arm, "run_id": f"{task}-{arm}", "role": role, "verdict": verdict,
            "validity": validity, "solved": solved, "score": score, "validated": validated, "cost_total": 10}


class EstimandTest(unittest.TestCase):
    def test_estimands_use_the_specified_denominators(self):
        rows = [
            row("a", "on", "judged", "support", solved=True),
            row("b", "on", "judged", "support", solved=False),
            row("c", "on", "judged", "defeat", solved=True, validated=True),
            row("d", "on", "judged", "support", validity="invalid", solved=None),
            row("a", "on", "final_workspace", solved=True, score=100.0),
            row("a", "off", "final_workspace", solved=False, score=90.0),
        ]
        result = report.estimands(rows, {"a": 67.0}, seed=1)

        self.assertEqual(result["p_solved_given_supported"]["point"], 0.5)
        self.assertEqual(result["p_solved_given_supported"]["n"], 2)
        self.assertEqual(result["missed_defect_rate"]["point"], 0.5)
        self.assertEqual(result["disagreement"]["point"], 1.0)
        self.assertEqual(result["validated_defeats"]["point"], 1.0)
        self.assertEqual(result["excluded"]["invalid"], 1)
        self.assertEqual(result["solved_by_arm"], {"on": {"solved": 1, "valid": 1, "invalid": 0}, "off": {"solved": 0, "valid": 1, "invalid": 0}})
        self.assertEqual(result["score_above_null"]["on"], 33.0)

    def test_clustered_ci_is_deterministic_and_brackets_the_point(self):
        values = {"a": [1.0, 1.0], "b": [0.0], "c": [1.0]}
        point, low, high = report.clustered_ci(values, seed=3)
        self.assertEqual((point, low, high), report.clustered_ci(values, seed=3))
        self.assertTrue(low <= point <= high)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd scripts && python3 -m unittest test_procontract_m0_report`
Expected: `ModuleNotFoundError: procontract_m0_report`.

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""M0 report: estimands with task-clustered bootstrap CIs (RSI spec §10 item 11)."""

import argparse
import json
import random
import statistics
import subprocess
from pathlib import Path

import procontract_store as store


def clustered_ci(values: dict[str, list[float]], seed: int, resamples: int = 2000) -> tuple[float, float, float]:
    flat = [v for vs in values.values() for v in vs]
    point = sum(flat) / len(flat)
    rng = random.Random(seed)
    tasks = sorted(values)
    means = []
    for _ in range(resamples):
        sample = [v for task in (rng.choice(tasks) for _ in tasks) for v in values[task]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return point, means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]


def _proportion(rows: list[dict], predicate, seed: int) -> dict:
    values: dict[str, list[float]] = {}
    for row in rows:
        values.setdefault(row["task"], []).append(1.0 if predicate(row) else 0.0)
    if not values:
        return {"point": None, "low": None, "high": None, "n": 0}
    point, low, high = clustered_ci(values, seed)
    return {"point": point, "low": low, "high": high, "n": sum(len(v) for v in values.values())}


def estimands(rows: list[dict], nulls: dict[str, float], seed: int = 0) -> dict:
    valid = [r for r in rows if r["validity"] == "valid" and r["solved"] is not None]
    judged = [r for r in valid if r["role"] == "judged"]
    supported = [r for r in judged if r["verdict"] == "support"]
    defeats = [r for r in judged if r["verdict"] == "defeat"]
    checked_defeats = [r for r in defeats if r["validated"] is not None]
    finals = [r for r in rows if r["role"] == "final_workspace"]
    by_arm = {}
    for arm in sorted({r["arm"] for r in finals}, reverse=True):
        arm_rows = [r for r in finals if r["arm"] == arm]
        by_arm[arm] = {
            "solved": sum(1 for r in arm_rows if r["validity"] == "valid" and r["solved"]),
            "valid": sum(1 for r in arm_rows if r["validity"] == "valid"),
            "invalid": sum(1 for r in arm_rows if r["validity"] != "valid"),
        }
    above_null = {}
    for arm in by_arm:
        gaps = [r["score"] - nulls[r["task"]] for r in finals if r["arm"] == arm and r["validity"] == "valid" and r["score"] is not None and r["task"] in nulls]
        above_null[arm] = statistics.fmean(gaps) if gaps else None
    p = _proportion(supported, lambda r: r["solved"], seed)
    missed = dict(p, point=None if p["point"] is None else 1 - p["point"],
                  low=None if p["high"] is None else 1 - p["high"], high=None if p["low"] is None else 1 - p["low"])
    return {
        "solved_by_arm": by_arm,
        "p_solved_given_supported": p,
        "missed_defect_rate": missed,
        "validated_defeats": _proportion(checked_defeats, lambda r: r["validated"], seed),
        "disagreement": _proportion(defeats, lambda r: r["solved"], seed),
        "excluded": {"invalid": sum(1 for r in rows if r["validity"] != "valid"),
                     "unknown": sum(1 for r in rows if r["validity"] == "valid" and r["solved"] is None)},
        "score_above_null": above_null,
    }
```

Add the loader, the revalidation, noise, costs and the CLI to the same file:

```python
def _score(score: str | None) -> float | None:
    if score == "✅":
        return 100.0
    return float(score) if score and score.isdigit() else None


def load_rows(batch_dir: Path) -> tuple[list[dict], dict[str, float]]:
    events = [record["event"] for record in store.events(batch_dir / "store")]
    assignments = {e["body"]["run_id"]: e["body"] for e in events if e["kind"] == "assignment"}
    costs = {e["body"]["run_id"]: e["body"].get("cost", {}) for e in events if e["kind"] == "execution"}
    revalidation = batch_dir / "revalidation.json"
    validated = json.loads(revalidation.read_text()) if revalidation.exists() else {}
    rows, nulls = [], {}
    for event in events:
        if event["kind"] != "label":
            continue
        body = event["body"]
        outcome = body.get("outcome") or {}
        role = body["role"]
        if role["kind"] == "null_sentinel":
            if _score(outcome.get("score")) is not None:
                nulls[body["instance"]] = _score(outcome.get("score"))
            continue
        run = assignments.get(body["run_id"], {})
        cost = costs.get(body["run_id"], {})
        rows.append({
            "task": body["instance"], "arm": run.get("arm"), "repeat": run.get("repeat", 1), "run_id": body["run_id"],
            "role": role["kind"], "verdict": role.get("verdict"), "validity": body["validity"],
            "solved": outcome.get("solved") if body["validity"] == "valid" else None,
            "score": _score(outcome.get("score")),
            "validated": validated.get(f"{body['run_id']}:{role.get('contract_id')}:{role.get('generation')}"),
            "cost_total": cost.get("executor", {}).get("total_tokens", 0) + cost.get("workers", {}).get("total_tokens", 0),
        })
    return rows, nulls


def revalidate(batch_dir: Path) -> dict:
    """Re-runs each defeat's recorded pipeline; validated when every originally failing step fails again."""
    results: dict[str, bool] = {}
    for record in store.events(batch_dir / "store"):
        event = record["event"]
        role = event["body"].get("role", {})
        if event["kind"] != "label" or role.get("kind") != "judged" or role.get("verdict") != "defeat":
            continue
        key = f"{event['body']['run_id']}:{role['contract_id']}:{role['generation']}"
        if key in results:
            continue
        attempt = sorted((batch_dir / "runs" / event["body"]["run_id"]).glob("attempt-*"))[-1]
        run_store = attempt / "codex-home" / "pro_contract"
        original = set()
        for run_event in store.events(run_store):
            body = run_event["event"]["body"]
            if (run_event["event"]["kind"] == "verification" and body["contract_id"] == role["contract_id"]
                    and body["generation"] == role["generation"] and body.get("receipts")):
                original = {step["step"] for step in body["receipts"]["steps"] if step["outcome"] == "fail"}
        work = run_store / "work" / role["contract_id"].replace("/", "_").replace(".", "_") / str(role["generation"])
        image = f"programbench/{event['body']['instance'].replace('__', '_1776_')}:task_cleanroom"
        output = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--user", "1000:1000",
             "-v", f"{work / 'candidate'}:/candidate:ro", "-v", f"{work / 'candidate.pipeline'}:/pc:ro",
             "--entrypoint", "bash", image, "/pc/pipeline.sh"],
            capture_output=True, text=True, timeout=1800, check=False,
        ).stdout
        failing = {line.split()[1] for line in output.splitlines() if line.startswith("@@PC ") and line.split()[2] == "fail"}
        results[key] = bool(original) and original <= failing
    (batch_dir / "revalidation.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def noise(rows: list[dict]) -> dict:
    finals = {(r["task"], r["arm"], r["repeat"]): r for r in rows if r["role"] == "final_workspace" and r["validity"] == "valid"}
    pairs = [(finals[(t, a, 1)], finals[(t, a, 2)]) for (t, a, rep) in finals if rep == 2 and (t, a, 1) in finals]
    if not pairs:
        return {"pairs": 0}
    return {
        "pairs": len(pairs),
        "solved_agreement": statistics.fmean(1.0 if x["solved"] == y["solved"] else 0.0 for x, y in pairs),
        "mean_abs_score_diff": statistics.fmean(abs((x["score"] or 0) - (y["score"] or 0)) for x, y in pairs),
    }


def costs(rows: list[dict]) -> dict:
    result = {}
    for arm in sorted({r["arm"] for r in rows if r["arm"]}):
        values = sorted(r["cost_total"] for r in rows if r["arm"] == arm and r["role"] == "final_workspace")
        if values:
            result[arm] = {"median": statistics.median(values), "p90": values[int(0.9 * (len(values) - 1))]}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--batch-dir", type=Path, required=True)
    rep.add_argument("--out", type=Path, required=True)
    val = sub.add_parser("revalidate")
    val.add_argument("--batch-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "revalidate":
        print(json.dumps(revalidate(args.batch_dir), indent=2))
        return
    rows, nulls = load_rows(args.batch_dir)
    result = {**estimands(rows, nulls, seed=0), "costs": costs(rows), "noise": noise(rows), "null_floors": nulls}
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# M0 report", ""]
    for name, value in result.items():
        lines += [f"## {name}", "", "```json", json.dumps(value, indent=2), "```", ""]
    args.out.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `cd scripts && python3 -m unittest test_procontract_m0_report`
Expected: OK (2 tests).

- [ ] **Step 5: Lint and commit**

```bash
cd scripts && uv run --frozen --project . ruff format procontract_m0_report.py test_procontract_m0_report.py && uv run --frozen --project . ruff check procontract_m0_report.py test_procontract_m0_report.py
cd .. && git add scripts && git commit -m "feat(scripts): add the M0 report with task-clustered estimands"
```

---

### Task 12: Build, pin, split, smoke — then stop for corpus approval

**Files:** none in the repo. Artifacts go to `~/run-artifacts/procontract-rsi-m0-20261001/` and the operator store
`~/.procontract-operator/`.

- [ ] **Step 1: Run every test suite touched by M0**

```bash
cd codex-rs && just test -p codex-pro-contract && just test -p codex-pro-contract-store && \
  PRO_CONTRACT_TEST_IMAGE=programbench/wfxr_1776_csview.8ac4de0:task_cleanroom just test -p codex-pro-contract-extension && \
  cargo build -p codex-pro-contract-store --bin pro-contract-store
cd ../scripts && PRO_CONTRACT_STORE_BIN=$PWD/../codex-rs/target/debug/pro-contract-store python3 -m unittest \
  test_procontract_benchmark_runner test_procontract_store test_procontract_evaluation test_procontract_pools \
  test_procontract_batch test_procontract_m0_report
```

Expected: all pass. Paste the summary lines into the ledger.

- [ ] **Step 2: Rebuild the musl harness at this commit** (version v0 for the corpus)

```bash
bash ~/run-artifacts/procontract-essential-20260930/musl/build-codex-musl.sh > ~/run-artifacts/procontract-rsi-m0-20261001/build.log 2>&1
```

Edit `root=` in a copy of the script so that it builds `~/codex-worktrees/procontract-rsi`, and save the copy as
`~/run-artifacts/procontract-rsi-m0-20261001/build-codex-musl.sh`. Expected: `rc=0`, and two sha256 lines recorded.

- [ ] **Step 3: Seen-list and sealed pools**

```bash
cd scripts
uv run --with pyyaml python3 procontract_pools.py seen --tasks-dir ~/ProgramBench/src/programbench/data/tasks \
  --scan ~/run-artifacts ~/ICLR_paper/contents --out ~/run-artifacts/procontract-rsi-m0-20261001/seen.json
uv run --with pyyaml python3 procontract_pools.py split --tasks-dir ~/ProgramBench/src/programbench/data/tasks \
  --language rs --seen ~/run-artifacts/procontract-rsi-m0-20261001/seen.json \
  --salt-file ~/.procontract-operator/salt --public-out ~/run-artifacts/procontract-rsi-m0-20261001/pools.json \
  --sealed-out ~/.procontract-operator/pools-sealed.json
```

Expected:
- `pools.json` lists dev (seen instances included) and counts for select and confirm, plus commitments;
- the sealed file has mode 0600;
- `wfxr__csview.8ac4de0` is in dev.

- [ ] **Step 4: Smoke: one dev instance end to end, ON arm, real evaluator**

- Plan a 1-instance batch: `procontract_batch.py plan --n 1 --seed 1 …` into `…/smoke-batch`, then manually reduce
  `batch.json` `runs` to the single ON run.
- Then run `null`, then `run --parallel 1`, detached with `setsid nohup`.

Expected:
- the run reaches `labelled`;
- `pro-contract-store events --store …/smoke-batch/store` shows assignment, capture, execution and label events;
- the run store shows intake, draft, issue and verification events with identities;
- every judged label's role carries contract id and generation;
- `pro-contract-store verify` succeeds on both stores.

- [ ] **Step 5: Report the smoke, then STOP and ask for corpus approval**

Write `~/run-artifacts/procontract-rsi-m0-20261001/SMOKE.md` with the events seen, the labels, the cost and the wall
time. Then ask the user to approve the corpus: "about 30 dev Rust instances × {ON, OFF} plus 8 duplicate runs
(≈68 runs, 25–60 min and 30–70 M mostly-cached tokens each), parallel 4". Do not start Task 13 without explicit
approval.

---

### Task 13 (gated on approval): Corpus v0 and the M0 report

- [ ] **Step 1: Plan, null sentinels, launch detached**

```bash
cd scripts && B=~/run-artifacts/procontract-rsi-m0-20261001/corpus
python3 procontract_batch.py plan --pools ~/run-artifacts/procontract-rsi-m0-20261001/pools.json --batch-dir $B \
  --n 30 --seed 20261001 --codex-bin <musl codex from Task 12> --prompt ~/run-artifacts/procontract-essential-20260930/task-prompt.txt
python3 procontract_batch.py null --batch-dir $B
setsid nohup python3 procontract_batch.py run --batch-dir $B --parallel 4 > $B/run.log 2>&1 < /dev/null &
```

Expected: `batch.json` records the frozen protocol, pins, seed and 68 runs; the null labels exist; the batch is running.

- [ ] **Step 2: Monitor until every run is `labelled` or `invalid`**

Run `python3 procontract_batch.py status --batch-dir $B` periodically. If the process dies, re-launching the same
command reconciles; the lock prevents double launches.

- [ ] **Step 3: Revalidate defeats, write the report**

```bash
python3 procontract_m0_report.py revalidate --batch-dir $B
python3 procontract_m0_report.py report --batch-dir $B --out ~/run-artifacts/procontract-rsi-m0-20261001/REPORT-M0.md
```

Expected: the report has every §10 item 11 estimand with n and a CI, the excluded counts, costs, and noise from the 8
duplicates. Record the measured noise. It sizes M2–M4.
