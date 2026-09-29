# ProContract (essential): invisible settlement integrity for Codex — Design

- Date: 2026-09-29
- Status: DRAFT for Principal review
- Base: upstream `openai/codex` `26dd19ef4` (branch `procontract-essential`). Design-relevant source was re-checked
  against `c248f6d48`; the 24 later upstream commits only add tracing to turn input and turn phases and make config
  refresh compare-and-swap (`ConfigRefreshOutcome::Stale`), which is a precedent for the admission permit of §3.3.
- Authority: the user is the Principal of this design. Sections 1–6 below were approved section by section in
  conversation; this document is the written form of that agreement and is itself subject to review.
- Co-review: Claude drafted; gpt-6-astra (reasoning effort max) reviewed each section adversarially against upstream
  source (rounds 1–4). Accepted corrections are folded in; the review record is listed in Appendix A.

## 0. Summary

When a user asks Codex for substantive repository work, ProContract silently places that work under a contract. The
model's "done" becomes a proposal, not a fact. An automatic Principal that is isolated from the executing model
freezes acceptance terms before it sees any candidate, verifies the candidate against those terms, and — if the
candidate fails — challenges it so the model keeps working. The user sees each answer with an honest assurance label.
Only the human settles: an explicit accept, or moving on after the support was shown, discharges the contract, and any
later complaint reopens it.

The one-sentence kernel: **executors propose; evidence supports; authority settles; accepted defeat restores
responsibility.**

## 1. Goals, non-goals, success criteria

### 1.1 Goals

1. **Invisible activation.** No `/contract` ritual. The host decides when work warrants a contract.
2. **Settlement integrity.** The executor can never certify its own completion. Only the human discharges.
3. **Honest assurance.** Every status shown to the user states exactly what was checked and how.
4. **Minimal footprint.** Zero new executor tools; in the executor's context, at most one bounded brief per terms
   revision and one bounded residual per automatic repair; no contract logic in core.
5. **Record for later RSI.** Every policy, prompt, model, attempt, abstention and human act is versioned and recorded,
   without building any policy-succession machinery now.

### 1.2 Non-goals (v1)

- Headless surfaces: `codex exec`, the TypeScript SDK and the Python SDK never receive contracts in v1.
- Remote environments, submodules, non-Cargo mechanical checks, cross-attempt build caches.
- Subcontracts, dependency DAGs, sealed challenges, policy succession, RSI.
- Human-authored evidence ("I reviewed it myself") as a substitute for automated support.
- System-level non-bypass against a same-user adversary outside Codex's managed sandbox.

### 1.3 Success criteria

1. Kernel axioms are mechanically tested (tests, not proofs): reference-model property tests and per-guard mutation
   tests pass.
2. One end-to-end test through the real app-server with a mocked Responses server and a simulated trusted TUI
   connection covers: request → intake → draft → Issue → edits → candidate → check fails → repair → pass → supported →
   next human message with receipt → discharged.
3. Questions, chat, and trivial edits do not produce contracts on a frozen triage corpus within preregistered
   issuance, latency and cost ceilings.
4. With the feature off, fresh threads without contracts behave identically to upstream: no additional requests,
   items or notifications. Turning the feature off stops issuance and automation; it never erases existing
   obligations or removes the human's read and decide access to them.
5. Release gates in §8 pass before any cohort enablement.

## 2. Principles

### 2.1 Four axioms

| Axiom | Statement |
|---|---|
| A1 Monopoly | Recognized duty state changes only through the pure `transition`. Every command kind is bound to one authority role. The executor role has no settlement verb. |
| A2 Exactness | Every recognizing command binds a complete coordinate; any mismatch rejects. Fencing is exactness over time. |
| A3 Conservation | Outstanding duty ends only by human discharge on current support at the exact coordinate, or by human release. "Quiet" is derived, never stored. |
| A4 Defeasance | An accepted defeater atomically withdraws current support (and a discharge that relied on it), restoring outstanding duty. History is append-only. |

**Kernel admission test.** A concept enters the kernel only if removing it produces a concrete counterexample
(self-certification, substituted subject, stale support crossing a defeat, silently erased duty, unauthorized
weakening). Everything else is workflow and lives in the extension.

### 2.2 Thin envelope

The executor-visible footprint must justify every token. Development-grade evidence from earlier native experiments
showed the envelope alone costing quality while envelope × execution policy helped; capability lives in the policy
plane, the envelope is integrity overhead. Therefore: no executor tools, no countdowns, no recitation of terms beyond one
bounded brief.

### 2.3 Evidence is world-indexed

Evidence supports a claim only relative to a subject, a capture policy, an evidence policy, an environment, and an
evaluator. A local pass in one environment does not transfer to another (the "Amber" lesson: Python 3.12 replay passed,
a 3.10 target failed).

### 2.4 Claim discipline

- A hash chain detects accidental corruption; it does not prevent tampering by a writer.
- "Supported" means the frozen evidence policy was satisfied at an exact coordinate. It is not proof of correctness and
  is never a utility label.
- Implicit settlement relies on a standing interpretation convention chosen by the user ("moving on after support was
  shown means acceptance"), not on a logical inference from the user's next message.
- A4 restores responsibility; it does not undo side effects.

## 3. Architecture

### 3.1 Authority map

| Role | Held by (provenance) | Kernel verbs |
|---|---|---|
| Issuer | The human owner, or the automatic Principal as delegate under the standing grant "feature enabled on a trusted interactive connection" | Issue (human or delegate provenance); Revise (human provenance required) |
| Executor | The main-thread model | Propose (implicit: a successful, bound turn end) |
| Verifier | The automatic Principal's verification workers | Support, Defeat |
| Settler | The human only | Discharge, Challenge, Release |

Roles are what the kernel binds (A1: one role per command kind). *Human* and *delegate* are provenance attributes
carried by the authenticated command, not additional roles.

**Implicit settlement rule.** An implicit act may discharge only a contract that currently holds support at the exact
coordinate that was presented to the human. It can never release a contract, override a defeat, or substitute for
missing support.

### 3.2 Components

| Component | Crate | Responsibility |
|---|---|---|
| Kernel | `codex-rs/pro-contract` (`codex-pro-contract`) | Pure reducer; dependencies exactly `serde`, `sha2`, `thiserror` |
| Extension | `codex-rs/ext/pro-contract` (`codex-pro-contract-extension`) | Ledger, subject store, check runner, automatic Principal workers, controller lanes, executor adapter |
| Protocol | `codex-rs/app-server-protocol` | Experimental v2 contract notification, list/read/decide RPCs, generic `clientAttestations` |
| App-server | `codex-rs/app-server` | Install the extension; forward its events; trusted-origin checks |
| TUI | `codex-rs/tui` | Status indicator, verdict cells, receipts at the submit gesture, optional `/contract` |

### 3.3 Generic host changes (no contract logic in core)

1. **Internal worker source.** A generic `InternalSessionSource` variant for extension-owned hidden workers, so that
   they are excluded from client listing and access (`core/src/thread_manager.rs` filters on
   `SessionSource::is_internal`). `ThreadSource::Feature(String)` alone does not hide a thread.
2. **Extension event forwarding.** The app-server `ExtensionEventSink` forwards extension events to typed
   notifications instead of dropping them (`app-server/src/extensions.rs`).
3. **Human input observation, sequence and attestations.** A generic hook through which extensions observe **every**
   human input — turn start, steer, and queued dispatch — before it is recorded, with a server-assigned monotonic input
   sequence (steering does not create a new turn id) and a non-model-visible, per-input metadata carrier for client
   attestations. `TurnInputContributor` alone is insufficient: it runs once per turn and does not see steered input.
4. **Conditional continuation admission.** One admission permit covers every revocation source, validated atomically
   with the reservation inside core's admission critical section: the expected previous turn id, the expected input
   sequence (taken from the authorized work binding, never re-read at submission time), and a synchronous eligibility
   predicate supplied by the caller (for example "not Plan mode, no active goal, not interrupted since binding").
   Today `continue_turn_if_idle` checks only the active turn and `last_started_turn_id`, and it explicitly permits Plan
   mode (`core/src/session/turn_input.rs`, `core/src/codex_thread.rs`), so it cannot enforce these on its own.
5. **Trusted interactive origin.** Contract presentation is honored only for host-trusted connection origins (the
   in-process `codex-tui`), following the existing user-verification precedent in
   `app-server/src/request_processors/initialize_processor.rs`.

Upstream already provides what else is needed: `ThreadManager::start_thread_until` with `SessionIsolation::Isolated`
(and, since `c248f6d48`, an explicit `IsolatedSessionExtensions` registry for isolated sessions),
`CodexThread::continue_turn_if_idle`, `InternalModelContextFragment`, world-state sections with `render_diff`, and the
single extension install path in `app-server/src/extensions.rs` used by every surface.

### 3.4 End-to-end flow

```
human input ─► [human control lane] ordered, durable: relations to existing contracts
            └► [automation lane]   intake (sync: verbatim input + base snapshot) ─► draft (async, frozen view)
                                   ─► Issue(terms) ─► brief appears to executor
executor works ─► bound successful turn end ─► terminal record ─► candidate snapshot ─► Propose
  ─► verification: checks on fresh copies + review on a pristine copy
       Support ─► assurance label on that answer ─► next human act with receipt ─► Discharge (defeasible)
       Defeat  ─► repair (≤ 1 by default) via atomic admission ─► executor continues ─► new candidate
       cannot_judge / budget exhausted / blocker ─► shown to the human; duty stays outstanding
```

## 4. Kernel

### 4.1 State

```text
Contract {
  id, owner,                       // owner = stable responsibility owner (the human), never a worker
  revision: u32,
  terms_hash, capture_policy_hash, evidence_policy_hash,   // bound at Issue / Revise
  standing: Outstanding | Discharged | Released,
  generation: u64,                 // monotonic fence; never reset
  candidate: Option<{ generation, subject_hash }>,    // work-binding details are extension audit metadata
  support:   Option<{ certificate_digest, coordinate }>,   // immutable once set
  settlement: Option<{ attestation_digest, coordinate }>,
  version: u64,                    // incremented by every accepted command
}

transition(state, AuthenticatedCommand) -> Accepted(state', events) | Rejected(reason)   // rejection: state unchanged
```

`AuthenticatedCommand` carries the contract id, the expected `version`, the actor's authenticated role, and the
payload. The kernel checks role binding and exactness; it cannot authenticate transport. The host supplies trusted
actors.

### 4.2 Coordinate

```text
e = (contract, revision, terms_hash, generation, subject_hash,
     capture_policy_hash, evidence_policy_hash,
     environment_digest, evaluator_digest, evidence_hash)
```

The first seven fields must equal the contract's stored bindings and current candidate. `environment_digest`,
`evaluator_digest` and `evidence_hash` are assertions of the authenticated verifier, recorded verbatim. Policy
*coverage* (did the certificate satisfy the whole evidence policy) is validated by the extension before it submits
`Support`; the kernel only binds identities.

### 4.3 Commands and guards

| Command | Role | Accepted when | Effect | Counterexample if removed |
|---|---|---|---|---|
| Issue | Issuer (human or delegate provenance) | id unused | Outstanding, revision 1 | — |
| Propose | Executor | Outstanding | generation+1; candidate set; support cleared | settled subject never handed off |
| Support | Verifier | Outstanding; candidate present; no support; the coordinate's first seven fields equal the stored bindings and the current candidate | support set | — |
| Defeat | Verifier | target = the exact current candidate `(generation, subject_hash)` of an Outstanding contract, or the exact settlement coordinate of a Discharged contract | Outstanding; support, candidate and settlement cleared; generation+1 | stale support crossing a defeat; a defeated discharge left standing |
| Challenge | Settler | same exact-target rule as Defeat | same as Defeat | wrong settlement cannot restore responsibility |
| Discharge | Settler | Outstanding; support present and equal to the receipt's coordinate | Discharged; settlement recorded | self-certification; settling unseen or stale support |
| Release | Settler | Outstanding | Released | duty silently erased |
| Revise | Issuer (human provenance required) | Outstanding | revision+1; new policy bindings; candidate and support cleared; generation+1 | terms silently weakened |

Global guards: expected `version` must match, and every accepted command increments it; `Released` is terminal (every
command rejected); `Discharged` accepts only `Defeat` and `Challenge`; a support certificate underlying a discharge can
never be replaced. Every rejection is a variant of a typed `Rejection` enum tagged with the axiom (A1–A4) or
`WellFormed` it protects.

**Retries never reach the reducer.** The ledger performs a durable idempotency lookup before running the reducer and
its compare-and-swap: an identical retry returns the originally committed result without a new transition; the same
key with a different payload rejects.

### 4.4 Not in the kernel

Verification procedure, escalation reasons, retry counters, budgets, resume, triage, drafting, check semantics,
environment equivalence, visibility of challenges, UI states. The UI states (§7) are projections of kernel state plus
extension job state.

### 4.5 Subcontracts (future formulation, not built)

- Dependencies are on **support certificates**: "this parent support consumes that exact child support certificate."
  Parenthood is organizational metadata; only consumed support drives invalidation.
- A parent needs its own evidence for composition at its own subject.
- Parent readiness requires children *supported*, not discharged. One human acceptance of the root authorizes an
  atomic batch discharge of the exact supported in-scope subtree, recorded as a settlement manifest.
- A defeated child certificate invalidates the active reverse-dependency closure, including discharged ancestors that
  relied on it; unrelated siblings are untouched.
- No delegated interior discharge: no model ever settles.
- v1 ships roots only. With roots only, removing graph support yields no counterexample, so the DAG does not enter the
  kernel until subcontracts are built.

## 5. Evidence

**Principle.** A missing or truncated *required* evidentiary link yields `cannot_judge`, never support. Irrelevant or
deliberately excluded diagnostics do not invalidate otherwise complete evidence.

### 5.1 Custody

- Certification is available only when the executor runs under a Codex-managed sandbox (read-only or workspace-write)
  in a local environment. Under `danger-full-access` (`SandboxEnforcement::Disabled`) or an external sandbox, no
  contract is issued: a same-user executor could forge the ledger, and an "unprotected" label cannot protect itself.
- **One layout.** All verifier state — the SQLite ledger with its WAL and SHM files, the blob store, evidence
  artifacts, materialized copies and worker directories — lives under `CODEX_HOME/pro_contract/`, outside every
  executor's writable roots. Custody checks cover all of it.
- **Custody is store-wide.** If Codex observes a custody break for the store — any session sharing this
  `CODEX_HOME` running under `danger-full-access`, or an approved escalation granting write access to
  `CODEX_HOME/pro_contract/` — every certificate issued before the break is quarantined: a quarantined certificate
  supports **neither explicit nor implicit** discharge until trustworthy re-verification produces a new certificate
  (anything else would recreate the evidence override of §4.3). Quarantine must survive restarts, so its authority
  cannot live only in controller memory or only in the possibly tampered store; where it is anchored is a slice-0
  custody finding (§12). Tampering by a same-user process outside Codex remains a non-goal (§1.2).
- Check processes and review workers run with **restricted read** as well as write: the live workspace, the ledger,
  credentials, rollouts and unrelated host paths are denied. Upstream's default read-only policy grants root read
  (`protocol/src/permissions.rs`), so an explicit restricted profile with `FileSystemAccessMode::Deny` entries is
  required. Network is off.

### 5.2 Subject capture and store

- **Scope (v1):** local environment; repository-edit claims. Answer prose and external side effects are not part of
  the subject.
- **Frozen at intake, before capture:** tracked membership and every ignore source. Inclusion = tracked files
  (including tracked-but-ignored) ∪ untracked files not ignored by the intake-time rules. Editing `.gitignore` cannot hide
  new files.
- **Bytes:** raw file bytes, no git filters. Entry types and modes recorded. Symlinks are recorded as content (their
  target string) and never followed; a target outside the workspace rejects the capture. Submodules are excluded in v1;
  a claim that requires submodule content is `cannot_judge`.
- **Store:** an extension-owned SHA-256 content-addressed blob store plus a versioned canonical manifest binding
  lossless path, entry type, mode, length and SHA-256 digest. `subject_hash = SHA-256(manifest)`. No git object store
  and no alternates: the store is independent of the user repository and its garbage collection.
- **Rehash every capture.** A stat cache is only a hint for storage deduplication, never proof of unchanged content.
- **Limits:** per-file size cap and total size/time caps are part of the capture policy. Exceeding a cap or any capture
  error means no subject; an intake that exceeds its time cap abstains and is logged.
- **What the subject is.** Support is a statement about the constructed immutable artifact, not about a point-in-time
  view of the live workspace; upstream offers no stable filesystem view. The relation to the delivered workspace is
  established by a verification pass after construction (re-hash of every included entry) and is claimed only as of
  that pass. A mismatch, including detected torn reads from background writers, means the capture is retried once, then
  abstains. Same-metadata changes that complete between the two passes are not claimed to be detected.

### 5.3 Checks (v1: one Cargo adapter)

- **Classification at Issue.** The Cargo adapter classifies the base before the evidence policy is frozen. A project
  it cannot verify mechanically — git dependencies (the Codex workspace itself has them), out-of-workspace path
  dependencies, missing registry archives, or check commands that the user's execution policy forbids or would
  require approval for — is classified at Issue, and under breadth B the contract is issued `review_only` where the
  claim permits. A class frozen as `checks_and_review` is never downgraded at runtime; adapter failure after Issue is
  `cannot_judge`.
- **Selection.** The drafter selects checks from the adapter's candidates; the selection, argv, timeouts and
  applicability rules are frozen in the evidence policy.
- **Execution restrictions.** Checks honor the user's and the repository's execution restrictions (execpolicy rules).
  Running inside a sandbox is not approval — the raw exec helper ignores approval-related fields
  (`core/src/exec.rs`) — so a check never runs a command the thread's policy would forbid or escalate, and checks never
  request escalation.
- **Execution.** Every check runs on a fresh materialization of the subject from the store, with a fresh target
  directory, `cargo test --locked --offline`, network off, an environment allowlist and restricted read. No
  cross-attempt build cache.
- **Dependency import.** Dependencies are imported as archives: each `.crate` archive from the user's registry cache
  is copied into the verifier store and its SHA-256 is checked against the `Cargo.lock` checksum; expanded sources and
  registry metadata are never taken from the user's directories. Imported archives are immutable shared inputs; each
  attempt gets its own writable `CARGO_HOME` state built from them. A missing archive is `cannot_judge`, never a
  fallback to ambient directories.
- **Frozen evaluator coverage.** After Issue, the adapter enumerates test case identities on the base copy
  (`-- --list`) under already-frozen selection rules; enumeration never chooses criteria after seeing candidate
  results. At verification the candidate must contain every base case (unless the frozen applicability rule, decided
  before any candidate exists, marks it removable) and every selected case must pass. Zero discovered cases fail.
  Coverage equality is not evaluator integrity: an executor can weaken an assertion without changing a case id.
- **Two evaluation lanes.**
  1. *Frozen evaluator lane.* Evaluator files that are separable from production code (for Cargo: files under
     `tests/`, `benches/` and declared fixtures) are frozen by content at Issue. At verification their **base**
     versions are overlaid onto the candidate's production files and run. A same-id weakened assertion in such a file
     therefore cannot hide the original defect. The overlay and the resulting tested inputs are recorded.
  2. *Candidate lane.* The candidate's own tests (including new ones) run as separate, separately identified
     evidence.
  Applicability of lane 1 is decided at Issue: if the requested change legitimately alters a frozen evaluator file,
  the drafter must mark it inapplicable under a rule frozen before any candidate exists, or the change requires a
  human-origin Revise.
- **Evaluator-selection machinery.** Frozen test files alone do not freeze an evaluator: `Cargo.toml` target
  declarations (`[[test]]`, `[[bench]]`, `test = false`, `harness = false`, `required-features`), dev-dependencies,
  `.cargo/config.toml`, profile and feature settings, `build.rs`, and `cfg` gates can redirect or disable evaluation
  without touching a protected byte or a case id. Lane 1 therefore also validates that the candidate's effective
  evaluator configuration — the resolved set of test targets, harness flags, enabled features and relevant build
  settings — equals the base's for every frozen target. The comparator is conservative: unknown or uninspectable
  configuration is never "equal" (this is not a general Rust semantic-equivalence project). A difference makes lane 1
  `cannot_judge` for that target unless a frozen applicability rule covers it. The certificate records exactly which base evaluator files ran against
  which candidate production inputs under which effective configuration.
- **Limited mechanical coverage is disclosed.** Inline evaluator code that is not separable from production code
  (Rust `#[cfg(test)]` modules in `src/`) cannot be frozen this way. Its changes are mandatory review findings, and the
  assurance carries `frozenOracle: full | partial | none`. `partial` and `none` are shown to the human; they are
  limited mechanical coverage, not immutable-oracle verification.
- **Aggregation.** A single run per check. Timeout or infrastructure failure is `cannot_judge`. At most one
  infrastructure retry if the frozen policy allows it; every attempt is recorded and disclosed in the certificate, and
  attempt records survive restarts, so crashes cannot turn into retry-until-green.
- **Diagnosis only.** When a check fails, it may be re-run on the base copy to report whether the failure pre-existed.
  This never waives a required pass.
- **Environment digest.** Measured toolchain identity (resolved `rustc`/`cargo` binaries and versions), OS/arch,
  `Cargo.lock` digest, the seeded dependency set, the effective sandbox profile, and custody status.

### 5.4 Semantic review

- A hidden isolated worker (generic internal source, fresh history, explicit isolated extension set) with read-only
  access to a **pristine** materialization of the subject — never a copy that checks have run in. Network off; no MCP,
  subagents, hooks or memories. Strict JSON output via the turn's output schema.
- Inputs, each bounded with an omission manifest and bounded retrieval: the verbatim human intake and later human
  revisions, the numbered requirements, the base→candidate diff, and check receipts. **Never** the executor's
  transcript or final message.
- Output: `support{requirement → evidence references}` with full coverage required, `defeat{requirement, location,
  counterexample, residual}`, or `cannot_judge{missing}`. Malformed or truncated output is `cannot_judge`. Evidence
  references are validated deterministically. The residual addresses unmet frozen requirements only, never new goals.

### 5.5 Support certificate and evidence classes

- `checks_and_review`: every selected check passed under the frozen rule, coverage holds, and review supports.
- `review_only`: declared at Issue when no adapter applies (the user chose breadth "B"); review supports with full
  coverage. Labeled "review supported · not executed". A runtime claim that the policy declared executable can never
  become review-only.
- The certificate binds the coordinate `e`, all attempt ids, the review record, and the worker identities
  (model, effort, prompt version).

### 5.6 Ledger and durability

- `CODEX_HOME/pro_contract/ledger_1.sqlite` (with its WAL and SHM files), extension-owned (the
  `ext/agent-message-board` pattern, `BEGIN IMMEDIATE`):
  events (canonical JSON, versioned canonical hashing, hash chain), contract projection, durable jobs, attempts, human
  inputs.
- One transaction per accepted command writes the event, the projection and any job transitions, checks the expected
  version, and records the idempotency key.
- Evidence artifacts are published (content-addressed, fsynced) **before** a transaction references them; orphan
  artifacts after an aborted transaction are tolerated and collected later. Recovery validates every referenced
  artifact and never reconstructs quiet by dropping damaged records. Intentional erasure (§6.6) is recorded as an
  explicit `erased` event per artifact, so recovery distinguishes it from corruption.
- Durable jobs carry leases and fences; on restart the controller reconciles already-started work (for example, a
  repair turn that was submitted but not acknowledged) with thread history before retrying, and preserves spent
  budgets.

## 6. Controller: the automatic Principal

The controller has two lanes. **Human control is durable and ordered and is never cancelled. Automation is scheduled
and cancellable.**

### 6.0 Activation

Contracts are issued only when all hold (otherwise abstain and log the reason):

- feature `pro_contract` enabled;
- the connection is a host-trusted interactive origin (in-process `codex-tui`) **and** it declared the contract
  presentation capability;
- the thread is persistent and root (not a subagent, review, or internal thread);
- not in Plan mode; no active `/goal`;
- executor sandbox is managed and the environment is local (§5.1);
- intake capture succeeds within its caps.

Activation conditions gate **issuance** only. They never gate processing of human control acts on existing contracts.

### 6.1 Human control lane

- **Two moments per human act.**
  - *Admission* happens at ingress — `turn/start`, `turn/steer`, and the dispatch of a queued item. The host assigns
    a server-ordered input sequence number and an immutable act id; the act (content digest and receipts) is
    persisted and automation fences advance before any processing.
  - *Dispatch* happens when the act is delivered to the model: the start of a turn, or the consumption of a steer.
    Execution binding and, for turn starts, intake capture (§6.2) refer to the same act id.
- **Queue semantics.** Enqueueing is not admission. A queued item is admitted when it is dispatched, with the content
  it is dispatched with. A committed content edit or resubmission of a queued item is a new gesture: the TUI
  re-freezes receipts for the edited content. Merely reordering an unchanged item preserves its original receipt set;
  it never mints receipts for support presented after the item was submitted. Upstream preserves `client_id` across
  queue edits (`ext/queue/src/service.rs`), so `client_id` is never used as act identity. No act is processed twice,
  and a receipt never attaches to text it was not frozen with.
- Receipts are frozen by the TUI at the **human submit gesture** and bound to: connection origin and owner, thread,
  contract id, the immutable support id actually rendered, the displayed assurance class, and the client message id.
  Queued input that predates a presentation carries no receipt for it.
- Explicit TUI decisions (`accept`, `reopen`, `release`) map directly to kernel commands; no model is involved, and they
  remain available during model outages and after any budget is exhausted.
- Natural-language inputs pass through a **tool-free human-intent stage** that sees only the authenticated input, its
  receipts, and bounded records of the contracts it may refer to (including discharged ones when referenced). It never
  reads repository content. It proposes relations — `accept`, `dispute(quote)`, `revise(requirements')`,
  `continue` (an answer to a question or a request to keep going), `neutral`, `ambiguous` — which the host validates
  (quotes must occur in the actual input; quoted logs or hypotheticals are not challenges) before issuing kernel
  commands.
- **The intent stage is bounded, not immortal.** At most two attempts within a deadline and a token cap. On failure the
  act gets a durable `unresolved` outcome: nothing is discharged or challenged on its behalf, the act stays recorded in
  order, and explicit decisions remain available.
- Precedence: dispute and revision outrank acceptance; mixed or ambiguous input discharges nothing; one topic change
  never accepts a backlog; an earlier unresolved human act on the same contract blocks implicit acceptance.
- Implicit discharge requires: a receipt for the contract's current support and displayed assurance class, no earlier
  unresolved act on it, a high-precision `accept` (explicit or moving on to unrelated new work), and no dispute,
  correction, cancellation or scope-change signal.
- Human acts are processed strictly in input order; a later input may add work but never erases an earlier act.
- A dispute about a contract that has no candidate (the executor is still working) is not a kernel challenge — there
  is nothing to defeat; it is ordinary steering of the executor.
- **Work authorization.** A human act that dispatches a turn and that the intent stage relates to contract C as
  `dispute`, `revise` or `continue` binds that turn to C and opens a new work episode (§6.2 step 4). An explicit
  `reopen` decision restores responsibility but starts no work by itself; work resumes with the next human act related
  to C. Challenge restores responsibility; it never authorizes unsolicited repair on its own.

### 6.2 Automation lane

1. **Intake (synchronous, in `TurnInputContributor`, at the dispatch of a turn-start act).** Steered acts never start
   new issuance in v1; they are handled by the human control lane only. A deterministic rule prefilter runs first (no
   model). If it passes: freeze ignore sources and tracked membership, capture the base snapshot within its time cap,
   and persist the intake record keyed by the act id (verbatim input, base subject, capture policy, input sequence).
   Intake contributes **no** fragments to the executor's context.
2. **Draft (asynchronous, one hidden worker call).** Inputs: the frozen intake, bounded human-approved context needed to
   resolve references ("do option two"), and read-only access to a pristine base materialization. Never the executor's
   live work. Output (strict JSON): `none` or `new_contract{requirements[], evidence_class, checks, applicability rules,
   evaluator paths}`. Unresolvable references produce a clarification request, not invented requirements.
3. **Issue.** The delegate issues on the owner's behalf. The executor then sees one world-state section — at most 512
   tokens: numbered requirements and evidence class; no budgets, no countdown — at its next sampling step; unchanged
   terms render nothing new. If the executor's turn ended before Issue, the same terminal-status and binding checks run
   against the ended turn.
4. **Work binding and episodes.** A binding `(contract, revision, act id, input sequence, turn id, host epoch)` is
   extension audit metadata, not kernel state. A turn is bound to contract C only when it was dispatched by the intake
   act that issued C, or by a human act the intent stage related to C (§6.1 work authorization). The relation is
   resolved before any candidate from that turn is promoted; an unresolved relation leaves the turn unbound. An
   automatic repair turn belongs to its episode and gets a new binding carrying the repair's own turn id (it does not
   copy the previous turn's binding). Only a bound turn produces a candidate; an unrelated later turn
   never proposes for an older contract. A **work episode** opens at Issue and at every work-authorizing human act. Its
   automatic-repair allowance (default 1) is per episode and is never reset by `Propose`, by a repair, or by a restart.
5. **Terminal record and candidate.** At turn stop the extension copies a terminal record from the turn store before
   the store is dropped: turn id, act id, input sequence, final message id, structured question signals, and the
   **actual turn outcome** (`completed`, `aborted(reason)` or `error`). The idle cause alone is insufficient: upstream
   reports `Completed` for every abort reason other than `Interrupted` and `BudgetLimited` (`core/src/tasks/mod.rs`).
   On idle, a bound, eligible contract whose terminal record says `completed` captures the candidate and proposes it.
   Every other outcome produces no candidate; "turn ended" is not a successful handoff.
   **Questions never block evidence; they block automatic repair.** Upstream cannot tell a required clarification from
   an optional follow-up: native async questions (`request_user_input` messages carrying `questions`, phase
   `FinalAnswer`, delivery `Async`) return immediately and carry no "required" flag. So a candidate is verified even
   when the executor asked something. While any question from the bound turn is unanswered, or the final prose is
   judged uncertain by a deterministic rule, a **hold** is recorded and no automatic repair is submitted. Questions do
   not bypass missing permissions or unresolved requirements. A hold ends at the next human act on the thread, at an
   explicit dismissal in `/contract`, or at a Revise or reopen; a heuristic never creates a hold that only the heuristic
   can clear. The verification outcome and the hold are independent dimensions (§7.1): "did not pass" and "waiting on
   you" can both be true. The human's reply is processed by the human control lane.
6. **Verify.** §5 pipeline → `Support`, `Defeat`, or `cannot_judge` (no kernel command; the contract stays outstanding
   with a stated reason).
7. **Repair.** After `Defeat`, if the episode's repair allowance remains, no hold is active, and eligibility holds,
   reserve a durable repair id and submit through conditional continuation admission (§3.3 item 4): the candidate's
   turn id as the expected previous turn, the **episode binding's** input sequence as the expected sequence, and the
   controller's eligibility predicate. The body is an `InternalModelContextFragment` with source `pro_contract`, capped
   at 512 tokens before construction, containing only the residual of unmet frozen requirements. When the allowance is
   exhausted, the contract is shown as "did not pass" with the residual.

### 6.3 Fencing and ordering

| Situation | Rule |
|---|---|
| A complaint followed quickly by another message | The complaint is never discarded as stale; human acts are processed in order before automation effects are promoted. |
| New human input during verification | Automatic effects are fenced at ingress. Pending human relations are applied before any verification result is promoted. |
| Repair races input, interrupt, Plan mode, goal activation, or a permission/environment change | One admission permit (§3.3 item 4) covers every revocation source and is validated atomically with the reservation; the expected input sequence comes from the work binding, so intervening input can never be blessed. There is no check-then-submit window. |
| Restart after repair submission | Reconcile the durable repair id with thread history before retrying; spent budgets persist. |
| Revise during a check | Stale results are rejected by revision, generation and version; they are archived as history and never rebound. |

Evidence validity is separate from scheduling. An unrelated later input does not invalidate evidence about an
unchanged coordinate; after human relations are processed, such evidence may still support that earlier answer — without
launching repair. A SQLite transaction is never held across an awaited core submission.

### 6.4 Budgets and accounting

- One automatic repair per work episode by default (§6.2 step 4); a per-contract cumulative automation budget (tokens
  and wall time) covering the intent stage, drafting, enumeration, checks, review, retries and repairs, each
  attributed separately.
- Safety ceilings (not latency targets): intent stage two attempts within 30 s, drafting 60 s, review 300 s, per-check
  timeouts from the frozen policy.
- Every worker input has a hard token cap. Any single model-visible or worker-facing item that can exceed 1K tokens is
  flagged for the repository's additional P0 review (`AGENTS.md`, "Model visible context").
- Isolated workers do not inherit the parent's extension registry, so their token usage is accounted explicitly. Use
  `IsolatedSessionExtensions` with a minimal allowlisted registry (accounting only), never the parent registry under a
  new wrapper.
- Metrics from day one: intake latency, issuance rate, abstention reasons, cost per contract, defeat and `cannot_judge`
  rates, human disputes after support, releases, reopen-after-discharge.

### 6.5 Modes

- Active `/goal` at intake: abstain. A goal created after Issue suspends automation for that contract (no verification
  or repair on goal-driven idles); the duty stays outstanding and is labeled. Future: goal completion becomes a
  candidate, with `/goal` keeping scheduling and budget ownership; never two competing continuation controllers.
- Plan mode: abstain; switching to Plan mode fences automation. `continue_turn_if_idle` permits Plan-mode continuation,
  so the controller's own eligibility gate enforces this.
- Subagent, review and internal threads: never.

### 6.6 Thread lifecycle

- **Fork.** Contracts never transfer: a forked thread starts with no contracts and no certificates. Copied history is
  not authority.
- **Revert** (`thread/revert` rewinds history, not files). Ledger records are unaffected; nothing is released; a
  candidate bound to a reverted turn remains historical.
- **Archive.** No effect on contracts.
- **Delete.** Plain thread deletion (`thread/delete`) is not settlement consent and releases nothing. Outstanding
  contracts of a deleted thread become **tombstones**: their normative skeleton (ids, standing, hashes, versions,
  decisions) is retained as outstanding, while human content (verbatim intake, diffs, review text, check output) is
  deleted under the same privacy rule as the thread and recorded as erased (§5.6). Owners discover tombstones through
  `thread/contract/list` with `filter: tombstoned` (no live thread required) and release them through
  `thread/contract/decide` `release`, naming the exact contract and version. Nothing is ever reconstructed as quiet
  from missing records.

## 7. Surfaces

### 7.1 App-server protocol (v2, experimental per field)

New methods and fields are gated individually with `#[experimental]`; existing `turn/start` and `turn/steer` remain
stable for clients that do not opt in. All payloads use camelCase tagged unions.

- **Notification `thread/contract/updated`** — small and thread-scoped:
  `{threadId, eventSeq, subject}` where `subject` is either
  `{type: "intake", intakeId, state: drafting | abstained{reason} | issued{contractId}}` (drafting is intake state; it
  never appears as an outstanding contract) or
  `{type: "contract", contractId, version, standing, verification, hold, assurance, summary}`.
  Two independent dimensions: `verification` ∈ `none | checking | supported | didNotPass | notVerified{reason}` and
  `hold` ∈ `none | waiting{blocker}`; `standing` covers `discharged` and `released`. `assurance` carries the evidence
  class and `frozenOracle: full | partial | none` (§5.3). `summary` is a terse, bounded string. Requirements and
  evidence are fetched on demand. Notifications never
  carry verifier prompts, reasoning, full logs, environment inventories or private paths.
- **Delivery** is authorized, thread-scoped and filtered to connections that declared the capability. The goal sink's
  fallback broadcast (`app-server/src/extensions.rs`) is not copied.
- **Reconciliation.** Every contract has a `version`; every event has a thread-monotonic `eventSeq`. Clients subscribe,
  then snapshot with a watermark, suppress duplicates, and recover gaps through `list`/`history`. Notifications are not
  the database.
- **`thread/contract/list`** `{threadId?, filter: unsettled | all | tombstoned, cursor, limit}` → current views +
  `nextCursor` + watermark. `threadId` is required except with `tombstoned`, which lists the authenticated owner's
  tombstones from deleted threads (§6.6).
- **`thread/contract/history`** `{threadId, contractId?, cursor, limit}` → paged presentation records (assessments and
  decisions, each with a stable event id and a turn anchor), used to restore verdict cards on resume.
- **`thread/contract/read`** `{threadId, contractId, evidenceCursor, limit}` → requirements and redacted evidence
  receipts; separately authorized.
- **`thread/contract/decide`** `{threadId, contractId, expectedVersion, idempotencyKey, decision}` with
  `decision` ∈ `{type: "accept", supportId}` | `{type: "reopen", supportId | settlementId}` | `{type: "release"}`.
  Admitted through the ordered human lane; owner and thread authorization are checked in addition to origin trust. The
  same key with a different payload rejects; duplicates never replay effects; the response returns the committed
  result and version.
- **`clientAttestations`** on `turn/start`, `turn/steer` and queued items: a bounded, versioned list of tagged claims,
  v1 only `{type: "contractSupportPresented", contractId, supportId, assurance}`. Origin, owner, thread and message
  identity come from the trusted envelope, never from the claim. A contract-specific validator checks each claim. The
  carrier never enters model context; the private intent stage receives only normalized, host-validated presentation
  facts.
- **`initialize.capabilities.contractPresentation`**, honored only for trusted origins.
- Regenerate JSON/TypeScript schemas and the Python SDK generated types; test clients that did not opt in.

### 7.2 TUI

- **Indicator.** Plain words, no jargon: "Checking…", "Checks passed · review supported", "Review supported · not
  executed", "Not verified: <reason>", "Did not pass: <residual summary>", "Waiting on you: <blocker>". Collaboration-mode
  indicators take precedence. A goal and an outstanding contract can coexist (§6.5 suspends automation, not the
  obligation); the goal indicator takes precedence and the contract indicator shows "paused for goal". When mechanical
  coverage is limited, the indicator says so ("tests partly editable").
- **Cards.** One card per substantive verdict or settlement event (supported, did not pass, not verified, accepted,
  reopened, released) — not per workflow step. Each card is anchored to its answer's turn; a delayed card names the
  earlier answer it concerns. Codex's owned transcript supports replacement (`tui/src/transcript_view/mutations.rs`),
  so a card may be updated in place there; native terminal scrollback stays append-only. Assurance remains visible
  after settlement ("Accepted · review supported · not executed").
- **Receipts.** A presentation is recorded only after the card, including its assurance qualifier, is visibly displayed
  in the active view — not when received, inserted, measured or painted offscreen. The receipt is frozen at the submit
  gesture and preserved through queueing and retries. Rendering a historical or revoked card never mints a receipt for
  current support.
- **Repair turns** show a one-line header ("Checks found an issue — continuing (1/1)"); the residual itself stays hidden
  model context.
- **Resume.** Presentation records from `thread/contract/history` are joined onto loaded history after the anchored
  turn, following the existing completion-metadata projection (`tui/src/app/history_pagination.rs`). Nothing is
  injected into model history and no assistant messages are manufactured.
- **`/contract`** — an optional inspector in the existing menu style: unsettled and settled contracts, with accept,
  reopen, release and details. Released is terminal.

### 7.3 Configuration

- Feature `pro_contract`: `Stage::UnderDevelopment`, default off.
- `[pro_contract]`: `repair_attempts` (default 1), the cumulative automation budget, capture caps. Worker models,
  efforts and prompts are extension defaults, versioned and recorded, not public per-role knobs in v1.
- Configuration changes never relabel existing evidence. Regenerate `core/config.schema.json`.

## 8. Testing and release gates

Mocked-model tests establish plumbing, not verifier or intent-classifier reliability; only §8.5 speaks to reliability
and benefit.

### 8.1 Kernel

- Property tests over random command sequences against an independently expressed reference model.
- Every rejected command leaves the state byte-identical.
- Mutation tests targeting each constitutional guard: removing the guard makes a named counterexample test fail.
- Dependency whitelist test on `codex-pro-contract` (exactly `serde`, `sha2`, `thiserror`).

### 8.2 Extension units

- Capture: tracked-but-ignored files, git filters, symlinks (inside and outside), `.gitignore` edits after intake,
  submodule exclusion, caps, same-metadata content edits, concurrent modification during capture.
- Store and manifest encoding; artifact publication ordering.
- Check runner: fresh copies, restricted read and write, network off, zero-case failure, coverage, frozen-lane overlay,
  evaluator-selection machinery changes (`Cargo.toml` target flags, `.cargo/config.toml`, features, `build.rs`) →
  lane 1 `cannot_judge`; timeout and infrastructure failure → `cannot_judge`; persisted attempts; archive import with
  checksum mismatch; classification of git-dependency projects as `review_only` at Issue.
- Weakened-assertion attacks, split by what must catch them: in a **separable** evaluator file the attack must fail
  mechanically (lane 1); in an **inline** `#[cfg(test)]` module detection depends on semantic review, and the
  certificate must report `frozenOracle: partial`.
- Ledger: atomicity, expected version, idempotency (duplicate and conflicting payloads), crash between artifact
  publication and commit, recovery.
- Human lane ordering and precedence; automation lane binding and fencing.

### 8.3 Integration through the real app-server

- Use the real in-process connection path (as in `app-server/tests/suite/conversation_summary.rs`), not a test-only
  trust bypass. Mock **model responses only**: executor tool calls edit a real temporary Cargo repository, and the
  actual capture, evaluator, sandbox, ledger, admission and RPC paths produce every verdict.
- Inspect outbound model requests: no attestations in executor inference; no executor narration in verification
  inputs; the correct frozen base; a bounded repair residual.
- Scenarios:
  - the happy path of §1.3;
  - a question-only turn → no contract; a required clarification and an optional follow-up both verify, neither
    triggers automatic repair while unanswered, and the view reports both dimensions (e.g. `didNotPass` and
    `waiting`) at once;
  - two successive failed candidates within one work episode → exactly one automatic repair; a `continue` from the
    human opens a new episode with a fresh allowance;
  - a turn aborted for a reason other than interrupt (reported as `Completed` idle) → no candidate;
  - a steered input → no new issuance; a queued item edited after a presentation → its old receipt is not used;
  - "thanks, but broken" → challenge; a complaint followed immediately by an unrelated task → the complaint is
    processed first;
  - steering during repair admission; interrupt; switch to Plan mode; goal activation;
  - duplicate decisions, conflicting idempotency payloads, stale accept and release, cross-thread and cross-owner
    receipt replay, a non-capable subscriber, dropped and reordered notifications, reconnect during support and during
    revocation;
  - a forged capability from an untrusted origin → no contracts; remote environment and `danger-full-access` →
    abstain;
  - crash the controller around artifact publication and around repair submission, restart on the same storage, and
    assert the reconstructed kernel state and the number of spawned repairs;
  - flag off → parity for fresh threads.

### 8.4 TUI

- A real event-loop test: a verdict is displayed → viewport eligibility → submit and queue → the emitted attestation is
  inspected → server-side settlement. Snapshots alone cannot prove this chain.
- Snapshot tests for every indicator state and card, including clipping of "not executed", background threads,
  overlays, scrolling, resize and replay.

### 8.5 Release gates (before any cohort enablement)

1. The adversarial suite: forged capability; queued pre-presentation input; "thanks, but broken"; complaint then
   unrelated task; late Issue after abort; optional async question; steering during repair admission; crash after
   repair submission; forged cache success; dependency mutation after hashing; a test rewriting the review copy;
   zero-test success; same-id weakened assertion in a separable file (must fail mechanically) and in an inline module
   (review-dependent, reported as partial coverage); evaluator redirection through `Cargo.toml` or
   `.cargo/config.toml`; same-metadata source edits; verifier defeat after human discharge; plain thread deletion
   (must not release);
   Python-3.12-versus-3.10-style environment mismatch.
2. A frozen mixed triage corpus (questions, edits, Plan-mode, trivial changes) with preregistered issuance, latency and
   cost ceilings and an eligible-task coverage floor; every intake and abstention is in the denominators.
3. A preregistered, randomized, equal-budget comparison against native Codex on a frozen task corpus, with
   policy/model/config versions and thresholds frozen before a disjoint confirmation set. Report false support, false
   defeat, acceptance-classification errors (separately from verifier errors), tail latency, total cost including all
   hidden inference, checks and repairs, and independently evaluated outcome quality, stratified by evidence class,
   with uncertainty bounds. "Supported" is never the utility label.
4. The controlled experiment is not production enablement, and the gate may conclude "do not ship".

## 9. What v1 records for later RSI

Nothing in v1 selects, promotes or adopts policies. It records, from day one:

- immutable versions of every policy, prompt, model and effort used by intake, the intent stage, drafting, review and
  each adapter;
- coordinates and artifact provenance for every candidate and certificate;
- every attempt, abstention, `cannot_judge`, defect and repair, with costs and latencies;
- human-act provenance (receipts, decisions, disputes) and later reversals;
- cohort and randomization identifiers for controlled evaluation;
- explicit privacy and retention rules for exportable evidence.

"Supported" and implicit acceptance are signals, not ground-truth labels. Independent outcome evaluation and failed
adoption gates are preserved.

## 10. Deferred (explicitly out of v1)

- Subcontracts and support-certificate dependencies (§4.5).
- Human-authored evidence: needs policy-bound semantics (it cannot satisfy a frozen `must_pass`), a re-proposal path
  after `Defeat`, and distinct evidence and attestation records.
- `codex exec` and SDK surfaces, which need completion semantics that wait for supported or escalated states.
- Remote environments; submodules; additional adapters (npm with an integrity-verified offline cache, pytest); a sound
  action cache keyed on the full input closure.
- `/goal` integration (goal completion as a candidate).
- Sealed challenges; policy succession and RSI.
- An always-on router model; summaries of all outstanding contracts in prompts.

## 11. Open questions for planning

1. The exact shape and name of the generic internal worker source in `codex-protocol`.
2. The core shape of the human-input observation hook (admission at start, steer and queued dispatch), its input
   sequence and attestation carrier, and the conditional continuation admission (§3.3 items 3–4).
3. The synchronization protocol that linearizes automation admission against external eligibility writers (goal
   activation, permission and environment changes). A synchronous predicate evaluated under core's admission lock only
   reads state; it does not serialize those writers. Slice 0 must establish a shared linearization point, not merely
   show that the predicate can read goal state (the goal extension exposes `GoalService`/`GoalRuntimeHandle`;
   extensions do not see each other's events).
4. Restricted-read sandbox support per platform (Linux, macOS seatbelt, Windows); a platform without it abstains.
5. The source of the stable owner identity (account versus local user).
6. The privacy and retention rule for tombstoned human content (§6.6) and for exportable evidence (§9).
7. Default worker models and efforts, and the concrete ceilings to preregister for §8.5.

## 12. Delivery order

The spec is larger than one implementation plan. Risk is retired first, then the feature is grown as vertical slices,
each with its own plan, its own integration tests, and a green tree:

0. **Feasibility spikes (throwaway code, findings recorded):** the owner identity source; a prototype of the
   admission boundary (human-input observation, input sequence, conditional continuation) with concrete results for
   revocation races and the linearization protocol of §11 item 3; actual restricted-read custody on each supported
   platform, including where restart-safe quarantine authority is anchored and how custody loss is recovered; one
   offline Cargo fixture with real registry dependencies through archive import, the conservative configuration
   comparator and both evaluation lanes. Findings may send parts of this spec back for revision.
1. **Kernel** — `codex-pro-contract`: state, coordinate, commands, typed rejections, reference-model property tests,
   guard mutation tests, dependency whitelist.
2. **Walking skeleton (vertical)** — only the host changes the happy path needs, ledger and capture, the Cargo adapter
   and review worker, the automation lane happy path, a minimal notification and TUI card, and an end-to-end test
   through the real in-process app-server that ends at **supported** (request → intake → draft → Issue → edits →
   candidate → check fails → repair → pass → supported). No institutional test bypass stands in for settlement.
3. **Human control lane** — admission and dispatch, receipts, the intent stage, implicit discharge, `decide`, with the
   real TUI event-loop test (§8.4); this slice completes the §1.3 scenario through human settlement.
4. **Evidence hardening** — frozen-evaluator lane and machinery validation, store-wide custody quarantine,
   classification at Issue, execution restrictions, with their adversarial tests.
5. **Fencing and recovery** — every revocation source in the admission permit, work episodes, holds, crash and restart
   reconciliation, with the corresponding integration tests.
6. **Surfaces completeness** — `list`/`history`/`read`, reconnection, the `/contract` inspector, snapshots.
7. **Expanded adversarial coverage** — the full suite of §8.5 item 1 beyond what earlier slices already added.
8. **Controlled evaluation** — §8.5 items 2–4, planned and preregistered separately.

## Appendix A. Review record

Stored outside the repository in `~/scratch/procontract-essential/` (Codex session
`01a0eb9b-f292-7b93-85fb-88d6009a7a33`):

| Round | Scope | Files |
|---|---|---|
| Brief | Context, Section 1, drafts of S2–S6, subcontracts | `astra-brainstorm-brief-20260929.md` |
| 1 | S1 critique, subcontracts, S2–S6 | `astra-review-20260929.md` |
| 2 | Kernel fixes, evidence custody | `astra-round2-s2-s3-20260929.md`, `astra-review-round2-20260929.md` |
| 3 | Two-lane controller | `astra-round3-s4-20260929.md`, `astra-review-round3-20260929.md` |
| 4 | Surfaces, tests, cross-section consistency | `astra-round4-s5-s6-20260929.md`, `astra-review-round4-20260929.md` |
| 5 | Whole written spec: 6 blocking, 5 should, 1 nit — all accepted | `astra-round5-spec-20260929.md`, `astra-review-round5-20260929.md` |
| 6 | Confirmation: 5 resolved, 1 partial (left to slice 0); 1 new blocking, 3 should, 1 nit — all accepted; verdict "ready for planning from slice 0" | `astra-round6-confirm-20260929.md`, `astra-review-round6-20260929.md` |
