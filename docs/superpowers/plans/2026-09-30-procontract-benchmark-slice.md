# ProContract Benchmark Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the essential ProContract mechanism end to end on ProgramBench `wfxr__csview.8ac4de0` with
`gpt-5.6-luna` at `max`, ON and OFF, under the evaluation profile.

**Architecture:** Pure kernel crate (done) + one extension crate that hosts the institution (SQLite ledger, SHA-256
store), the automation lane (intake → draft → Issue → frozen candidate → container check pipeline + review → Support
or Defeat → one repair) and the executor brief, installed in the app-server behind `Feature::ProContract`. A host-side
Python runner prepares the cleanroom, drives `codex app-server` over stdio with a network-less container environment,
waits for a resting state, packages the submission and runs the official evaluation.

**Tech Stack:** Rust 1.95 (`codex-core`, `codex-extension-api`, `sqlx`/SQLite via `codex-state`), Docker, Python 3
(runner), ProgramBench (`uv run programbench`).

**Spec:** `docs/superpowers/specs/2026-09-29-procontract-essential-design.md` (§4 kernel, §5 evidence, §6.2 automation
lane, §13 evaluation profile). Findings: `docs/superpowers/plans/2026-09-30-procontract-slice0-findings.md`.

## Global Constraints

- Kernel `codex-pro-contract` depends exactly on `serde`, `sha2`, `thiserror`.
- No contract logic in `codex-core`; host changes are generic (spec §3.3).
- Never weaken host or Docker security: no `--privileged`, `SYS_ADMIN`, `seccomp=unconfined`, `apparmor=unconfined`.
- Inference and check containers run `--network none`, `--user 1000:1000`; the credential and `CODEX_HOME` never
  enter a container.
- The executor's context gets at most one live brief (≤ 512 tokens) and one residual per repair (≤ 512 tokens); both
  are `InternalModelContextFragment`s with source `pro_contract`.
- Workers (drafter, reviewer) are hidden, isolated, tool-less threads with no environment; their prompts are bounded
  (hard cap 60 000 characters of evidence per prompt) and their outputs use strict JSON schemas (every property
  required, `additionalProperties: false`).
- Extension settings live in `CODEX_HOME/pro_contract/settings.json`, not in `config.toml`.
- Both arms use the same binary (musl build), the same prompt
  (`~/run-artifacts/procontract-essential-20260930/task-prompt.txt`, SHA-256 `502f07f8…`), the same model, effort and
  deadline; only `features.pro_contract` differs.
- Packaging excludes the reference `executable`; tar with `--owner=0 --group=0 --numeric-owner`.
- Use `just test -p <crate>` and `just fix -p <crate>`; `just fmt` with `~/.cargo/bin` on `PATH`.

## Review Focus

- The drafter returns `none` for a clear implementation request → the ON arm silently degrades to OFF; the run must
  record the abstention reason so the report cannot mistake it for a ProContract run.
- The check container cannot build the candidate (no `compile.sh`, or `compile.sh` fails) → verification must end as
  a Defeat with the build log tail as residual, not as `cannot_judge`, because building is a frozen requirement.
- The repair turn itself fails to start (`NotSubmitted`) → the contract must rest as `didNotPass` instead of waiting
  forever; the runner must not hang.
- The executor's turn ends while drafting is still running → the frozen artifact from `on_turn_stop` must be used by
  the late Issue, never a later capture.
- A worker returns malformed JSON or times out → `cannot_judge`/abstain with a recorded reason, never a fabricated
  verdict.

---

## File structure

```
codex-rs/pro-contract/                     (done: kernel)
codex-rs/features/src/lib.rs               + Feature::ProContract (UnderDevelopment, default off)
codex-rs/core/config.schema.json           regenerated
codex-rs/protocol/src/protocol.rs          + InternalSessionSource::ExtensionWorker (+ exhaustive matches)
codex-rs/ext/pro-contract/
  Cargo.toml, BUILD.bazel
  src/lib.rs                install(), crate docs
  src/settings.rs           Settings (settings.json), EvaluationProfile, CheckEnvironment, WorkerSettings
  src/hashing.rs            versioned canonical hashing of typed records
  src/terms.rs              Terms, Requirement, EvidencePolicy, CheckSpec, CapturePolicy
  src/store/blobs.rs        SHA-256 content-addressed blob store
  src/store/ledger.rs       SQLite ledger: kernel commands, events, idempotency, status, intakes
  src/capture.rs            capture(root, policy) → Subject; materialize(subject, dest)
  src/checks.rs             container check pipeline: script, run, receipts, environment digest
  src/workers/runtime.rs    hidden isolated worker: start, one strict-JSON turn, deadline, shutdown
  src/workers/drafter.rs    drafter prompt, schema, Draft
  src/workers/reviewer.rs   reviewer prompt, schema, ReviewVerdict
  src/controller/mod.rs     ProContractExtension: contributor impls, per-thread state
  src/controller/eligibility.rs
  src/controller/automation.rs  intake → draft → Issue; idle → propose → verify → support/defeat → repair
  src/controller/brief.rs   world-state section and residual fragments
  *_tests.rs                unit tests next to each module
codex-rs/app-server/src/extensions.rs      install the extension
scripts/procontract_benchmark_runner.py    host runner (ON/OFF)
scripts/test_procontract_benchmark_runner.py
```

## Tasks

### Task 1: Kernel — DONE (`b40791530`)

34 tests (per-guard counterexamples, reference-model differential over 80 000 random steps, dependency whitelist);
9 manual guard mutations all killed.

### Task 2: Generic host changes

**Files:** `features/src/lib.rs`, `core/config.schema.json`, `protocol/src/protocol.rs`, exhaustive matches reported
by the compiler (`cli/src/doctor/thread_inventory.rs`, …), app-server TypeScript schema.

- [ ] Add `Feature::ProContract` (`key: "pro_contract"`, `Stage::UnderDevelopment`, `default_enabled: false`) after
  `AgentMessageBoard` in the enum and the `FEATURES` array; run `just write-config-schema`.
- [ ] Add `InternalSessionSource::ExtensionWorker` (serde `extension_worker`) with a doc comment ("hidden worker thread
  owned by an extension"); fix every exhaustive match the compiler reports; run `just write-app-server-schema`.
- [ ] Tests: `just test -p codex-features`, `just test -p codex-protocol`, `just test -p codex-core config_schema`.
- [ ] Commit `feat: add pro_contract feature flag and extension worker session source`.

### Task 3: Extension scaffold, settings, hashing, terms, blob store, capture

**Interfaces produced:**
- `Settings::load(codex_home: &Path) -> Result<Option<Settings>>` (missing file → `None`).
- `hashing::digest_of<T: Serialize>(domain: &str, value: &T) -> Digest` = SHA-256 of `"pro_contract/v1/{domain}\0"`
  followed by `serde_json::to_vec(value)`.
- `BlobStore::open(root) / put(bytes) -> Digest / get(digest) -> Vec<u8>` (files at `blobs/ab/<hex>`; verified on read).
- `capture(root: &Path, policy: &CapturePolicy, store: &BlobStore) -> Result<Subject, CaptureError>`;
  `Subject { manifest: Manifest, subject_hash: Digest }`; `Manifest { version: 1, entries: Vec<Entry> }`;
  `Entry { path: String, kind: File{mode, len, digest} | Symlink{target} }`.
- `materialize(subject: &Subject, store: &BlobStore, dest: &Path) -> Result<()>`.

- [ ] Tests first (`capture_tests.rs`): excluded paths never captured; `.gitignore` edits do not hide files; symlinks
  recorded, not followed; a file changed between the hash pass and the verification pass → `CaptureError::Unstable`;
  a file over `max_file_bytes` → `CaptureError::TooLarge`; capture then materialize round-trips bytes and modes;
  identical trees hash identically, one changed byte changes `subject_hash`.
- [ ] Implement; `just test -p codex-pro-contract-extension`; commit.

### Task 4: Ledger

**Interfaces produced:** `Ledger::open(dir) -> Result<Ledger>`;
`Ledger::apply(command: AuthenticatedCommand, idempotency_key: &str) -> Result<Contract, LedgerError>` (idempotent
retry returns the committed result; conflicting payload under the same key → `LedgerError::IdempotencyConflict`;
kernel rejection → `LedgerError::Rejected(Rejection)`); `Ledger::contract(id)`, `Ledger::record_status(thread_id,
contract_id, Status)` / `Ledger::status(thread_id)`; `Ledger::record_intake(...)`, `Ledger::record_artifact(...)`.
Events are hash-chained (`prev_hash`, `hash`) and written in the same `BEGIN IMMEDIATE` transaction as the projection.

- [ ] Tests first (`ledger_tests.rs`): apply issue → propose → support → discharge persists and reloads identically;
  a rejected command changes nothing; an identical retry returns the original result without a new event; a
  conflicting retry is rejected; the event chain links (`hash(prev) == next.prev_hash`).
- [ ] Implement with `codex_state::SqliteConfig::open_read_write_pool`; test; commit.

### Task 5: Workers (drafter, reviewer)

**Interfaces produced:** `WorkerRuntime::run_json<T: DeserializeOwned>(parent: &CodexThread-derived Config, prompt:
String, schema: Value, deadline: Duration) -> Result<T, WorkerError>` (isolated hidden thread: `SessionIsolation::
Isolated`, `InternalSessionSource::ExtensionWorker`, `ThreadSource::Feature("pro_contract")`, `environments:
Some(vec![])`, `ToolPolicy { allowed_tools: Some(vec![]) }`, approval `Never`, features off as in Guardian's
`build_reviewer_config`, strict schema); `drafter::prompt(...)`, `drafter::schema()`, `Draft`;
`reviewer::prompt(...)`, `reviewer::schema()`, `ReviewVerdict { verdict: Support|Defeat|CannotJudge, findings,
residual, terms_gap }`.

- [ ] Tests first: prompt builders stay within the cap and include the verbatim intake; schemas are strict (every
  property required, no additional properties); parsing accepts exact JSON and rejects anything else as
  `WorkerError::Malformed`.
- [ ] Implement runtime modeled on `ext/guardian-v2/src/sync_reviewer/mod.rs` and
  `ext/guardian-reviewer/src/execution.rs` (wait for `TurnComplete` of our turn id; `Op::Interrupt` on deadline;
  `shutdown_and_wait`); test; commit.

### Task 6: Container check pipeline

**Interfaces produced:** `checks::pipeline_script(policy: &EvidencePolicy) -> String` (ordered: build →
candidate tests → differential cases; each step prints a machine-readable result line);
`checks::run(env: &CheckEnvironment, subject_dir: &Path, policy) -> Result<CheckReceipts, CheckError>`;
`CheckReceipts { steps: Vec<StepReceipt>, environment_digest: Digest, evaluator_digest: Digest }`.

- [ ] Tests first: script generation is deterministic and quotes arguments safely; result-line parsing; a gated
  integration test (runs only when `PRO_CONTRACT_TEST_IMAGE` is set) that runs a tiny Rust candidate in the cleanroom
  image and gets pass/fail receipts.
- [ ] Implement with `docker run --rm --network none --user 1000:1000 -v <copy>:/candidate`; test; commit.

### Task 7: Controller (automation lane + brief)

- [ ] Tests first (`eligibility_tests.rs`, `automation_tests.rs` with fakes for workers and checks): eligibility
  abstains without the evaluation grant, with MCP servers or hooks configured, or with a non-configured environment;
  a draft of `none` records `abstained{reason}`; late Issue uses the frozen artifact; Defeat with allowance → one
  repair; second Defeat → `didNotPass`; `cannot_judge` → `notVerified`; repair `NotSubmitted` → `didNotPass`.
- [ ] Implement contributors: `TurnInputContributor` (intake), `TurnLifecycleContributor` (turn start/stop/error
  records, artifact freezing in `on_turn_stop`), `ThreadLifecycleContributor` (`on_thread_start` settings and
  eligibility; `on_thread_idle` promotion and verification), `ContextContributor` (brief world-state section with a
  retained-fragment matcher on the current contract and revision); repair via `continue_turn_if_idle`.
- [ ] Test; commit.

### Task 8: App-server wiring

- [ ] Install in `app-server/src/extensions.rs` gated by `config.features.enabled(Feature::ProContract)`; add the
  dependency; `just test -p codex-app-server` for the extension-install smoke; commit.

### Task 9: Runner

- [ ] Tests first (`scripts/test_procontract_benchmark_runner.py`): packaging excludes `executable` and tars with
  numeric owner 0; status polling decides resting states; config writers produce the expected files.
- [ ] Implement `scripts/procontract_benchmark_runner.py prepare|run|evaluate --arm on|off`; commit.

### Task 10: Smoke, then ON and OFF

- [ ] Build musl binaries; smoke the ON arm on a 10-minute synthetic task in the cleanroom image; inspect ledger,
  verdicts and brief/residual in the rollout.
- [ ] Run ON and OFF on `wfxr__csview.8ac4de0`; evaluate both; write
  `~/run-artifacts/procontract-essential-20260930/REPORT.md` (scores, ✅, contract trace, costs, limitations).
