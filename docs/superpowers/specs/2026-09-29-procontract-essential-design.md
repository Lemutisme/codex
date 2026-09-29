# ProContract (essential): invisible settlement integrity for Codex — Design

- Date: 2026-09-29
- Status: DRAFT for Principal review
- Base: upstream `openai/codex` `c248f6d48` (branch `procontract-essential`)
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
4. **Minimal footprint.** Zero new executor tools; at most one bounded brief and one bounded residual in the executor's
   context; no contract logic in core.
5. **Record for later RSI.** Every policy, prompt, model, attempt, abstention and human act is versioned and recorded,
   without building any policy-succession machinery now.

### 1.2 Non-goals (v1)

- Headless surfaces: `codex exec`, the TypeScript SDK and the Python SDK never receive contracts in v1.
- Remote environments, submodules, non-Cargo mechanical checks, cross-attempt build caches.
- Subcontracts, dependency DAGs, sealed challenges, policy succession, RSI.
- Human-authored evidence ("I reviewed it myself") as a substitute for automated support.
- System-level non-bypass against a same-user adversary outside Codex's managed sandbox.

### 1.3 Success criteria

1. Kernel axioms are machine-checked: reference-model property tests and per-guard mutation tests pass.
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

| Role | Held by | Kernel verbs |
|---|---|---|
| Issuer | The human owner; the automatic Principal as delegate under the standing grant "feature enabled on a trusted interactive connection" | Issue; Revise only with a human-origin receipt |
| Executor | The main-thread model | Propose (implicit: a successful, bound turn end) |
| Verifier | The automatic Principal's verification workers | Support, Defeat |
| Settler | The human only | Discharge, Challenge, Release |

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
4. **Continuation admission fence.** `continue_turn_if_idle` additionally rejects when the input sequence has advanced
   past an expected value, making repair admission atomic with respect to newly arrived human input.
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
  candidate: Option<{ generation, subject_hash, binding_digest }>,
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
| Issue | Human or Delegate | id unused | Outstanding, revision 1 | — |
| Propose | Executor | Outstanding | generation+1; candidate set; support cleared | settled subject never handed off |
| Support | Verifier | Outstanding; candidate present; no support; coordinate matches bindings and candidate; identical retry is a no-op | support set | — |
| Defeat | Verifier | (Outstanding with candidate at the stated generation) or (Discharged whose settlement coordinate matches) | Outstanding; support, candidate and settlement cleared; generation+1 | stale support crossing a defeat; a defeated discharge left standing |
| Challenge | Human | Outstanding with candidate, or Discharged | same as Defeat | wrong settlement cannot restore responsibility |
| Discharge | Human | Outstanding; support present and equal to the receipt's coordinate | Discharged; settlement recorded | self-certification; settling unseen or stale support |
| Release | Human | Outstanding | Released | duty silently erased |
| Revise | Human-origin Issuer | Outstanding | revision+1; new policy bindings; candidate and support cleared; generation+1 | terms silently weakened |

Global guards: expected `version` must match; `Released` is terminal (every command rejected); `Discharged` accepts
only `Defeat` and `Challenge`; a support certificate underlying a discharge can never be replaced. Every rejection is a
variant of a typed `Rejection` enum tagged with the axiom (A1–A4) or `WellFormed` it protects.

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
- An approved escalation that grants write access to verifier state voids certification for that contract.
- All verifier state (ledger, subject store, evidence store, materialized copies, caches) lives under
  `CODEX_HOME/pro_contract/`, outside the executor's writable roots.
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
- **Consistency:** after hashing, a second metadata pass detects concurrent modification (background processes can
  outlive a turn); detected change means the capture is retried once, then abstains.

### 5.3 Checks (v1: one Cargo adapter)

- **Selection.** The drafter selects checks from the Cargo adapter's candidates at Issue; the selection, argv,
  timeouts and applicability rules are frozen in the evidence policy. The evidence class (`checks_and_review` or
  `review_only`) is frozen too: adapter failure at runtime cannot downgrade a class.
- **Execution.** Every check runs on a fresh materialization of the subject from the store, with a fresh target
  directory, `cargo test --locked --offline`, network off, an environment allowlist and restricted read. Dependencies
  come from a verifier-private `CARGO_HOME` seeded from the user's registry cache; Cargo verifies each crate against the
  `Cargo.lock` checksum. Git or out-of-workspace path dependencies are `cannot_judge` in v1. No cross-attempt build
  cache.
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
  human-origin Revise. Inline evaluator code that is not separable from production code (Rust `#[cfg(test)]` modules
  in `src/`) cannot be frozen this way; changes to it are mandatory review findings and the certificate states that
  lane 1 did not cover them.
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

- `CODEX_HOME/pro_contract_1.sqlite`, extension-owned (the `ext/agent-message-board` pattern, `BEGIN IMMEDIATE`):
  events (canonical JSON, versioned canonical hashing, hash chain), contract projection, durable jobs, attempts, human
  inputs.
- One transaction per accepted command writes the event, the projection and any job transitions, checks the expected
  version, and records the idempotency key.
- Evidence artifacts are published (content-addressed, fsynced) **before** a transaction references them; orphan
  artifacts after an aborted transaction are tolerated and collected later. Recovery validates every referenced
  artifact and never reconstructs quiet by dropping damaged records.
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

- Every human input — `turn/start`, `turn/steer`, or a queued item — receives a server-ordered input sequence number and
  is persisted before any processing.
- Receipts are frozen by the TUI at the **human submit gesture** and bound to: connection origin and owner, thread,
  contract id, the immutable support id actually rendered, the displayed assurance class, and the client message id.
  Queued input that predates a presentation carries no receipt for it.
- Explicit TUI decisions (`accept`, `reopen`, `release`) map directly to kernel commands; no model is involved.
- Natural-language inputs pass through a **tool-free human-intent stage** that sees only the authenticated input, its
  receipts, and bounded records of the contracts it may refer to (including discharged ones when referenced). It never
  reads repository content. It proposes relations — `accept`, `dispute(quote)`, `revise(requirements')`, `neutral`,
  `ambiguous` — which the host validates (quotes must occur in the actual input; quoted logs or hypotheticals are not
  challenges) before issuing kernel commands.
- Precedence: dispute and revision outrank acceptance; mixed or ambiguous input discharges nothing; one topic change
  never accepts a backlog; an earlier unresolved human act on the same contract blocks implicit acceptance.
- Implicit discharge requires: a receipt for the contract's current support and displayed assurance class, no earlier
  unresolved act on it, a high-precision `accept` (explicit or moving on to unrelated new work), and no dispute,
  correction, cancellation or scope-change signal.
- Human acts are processed strictly in input order; a later input may add work but never erases an earlier act.
- A dispute about a contract that has no candidate (the executor is still working) is not a kernel challenge — there
  is nothing to defeat; it is ordinary steering of the executor.
- Challenge restores responsibility; it does not by itself authorize immediate unsolicited repair.

### 6.2 Automation lane

1. **Intake (synchronous, in `TurnInputContributor`).** Only for inputs carrying human `UserInput`. A deterministic
   rule prefilter runs first (no model). If it passes: freeze ignore sources and tracked membership, capture the base
   snapshot within its time cap, and persist the intake record (verbatim input, base subject, capture policy, input
   sequence). Intake contributes **no** fragments to the executor's context.
2. **Draft (asynchronous, one hidden worker call).** Inputs: the frozen intake, bounded human-approved context needed to
   resolve references ("do option two"), and read-only access to a pristine base materialization. Never the executor's
   live work. Output (strict JSON): `none` or `new_contract{requirements[], evidence_class, checks, applicability rules,
   evaluator paths}`. Unresolvable references produce a clarification request, not invented requirements.
3. **Issue.** The delegate issues on the owner's behalf. The executor then sees one world-state section — at most 512
   tokens: numbered requirements and evidence class; no budgets, no countdown — at its next sampling step; unchanged
   terms render nothing new. If the executor's turn ended before Issue, the same terminal-status and binding checks run
   against the ended turn.
4. **Work binding.** Automation work is bound to `(contract, revision, input sequence, turn id, host epoch)`. Only a
   turn bound to the contract can produce its candidate; an unrelated later turn never proposes for an older contract.
5. **Terminal record and candidate.** At turn stop the extension copies a terminal record from the turn store (turn id,
   input sequence, final message id, structured question signals) before the store is dropped. On idle with cause
   `Completed` and a bound, eligible contract, capture the candidate and `Propose`. "Turn ended" is not a successful
   handoff; `Interrupted` and `Failed` produce no candidate.
   **Questions never block evidence; they block automatic repair.** Upstream cannot tell a required clarification from
   an optional follow-up: native async questions (`request_user_input` messages carrying `questions`, phase
   `FinalAnswer`, delivery `Async`) return immediately and carry no "required" flag. So a candidate is verified even
   when the executor asked something, but while any question from the bound turn is unanswered, or the final prose is
   judged uncertain by a deterministic rule, no automatic repair is submitted. The verdict is shown next to the
   question and the human's reply is processed by the human control lane.
6. **Verify.** §5 pipeline → `Support`, `Defeat`, or `cannot_judge` (no kernel command; the contract stays outstanding
   with a stated reason).
7. **Repair.** After `Defeat`, if the repair budget remains (default 1) and scheduling eligibility holds, reserve a
   durable repair id and submit through atomic admission: `continue_turn_if_idle` with the candidate's turn as
   `expected_previous_turn_id` and the current input sequence as the expected sequence (§3.3 item 4). The body is an
   `InternalModelContextFragment` with source `pro_contract`, capped at 512 tokens before construction, containing only
   the residual of unmet frozen requirements. When the budget is exhausted, the contract is shown as "did not pass
   verification" with the residual.

### 6.3 Fencing and ordering

| Situation | Rule |
|---|---|
| A complaint followed quickly by another message | The complaint is never discarded as stale; human acts are processed in order before automation effects are promoted. |
| New human input during verification | Automatic effects are fenced at ingress. Pending human relations are applied before any verification result is promoted. |
| Repair races input, interrupt, Plan mode, or goal activation | Epoch validation and submission go through the single atomic admission step; there is no check-then-submit window. |
| Restart after repair submission | Reconcile the durable repair id with thread history before retrying; spent budgets persist. |
| Revise during a check | Stale results are rejected by revision, generation and version; they are archived as history and never rebound. |

Evidence validity is separate from scheduling. An unrelated later input does not invalidate evidence about an
unchanged coordinate; after human relations are processed, such evidence may still support that earlier answer — without
launching repair. A SQLite transaction is never held across an awaited core submission.

### 6.4 Budgets and accounting

- Default one repair per candidate cycle; per-contract cumulative automation budget (tokens and wall time) covering
  drafting, enumeration, checks, review, retries and repairs, each attributed separately.
- Safety ceilings (not latency targets): drafting 60 s, review 300 s, per-check timeouts from the frozen policy.
- Isolated workers do not inherit the parent's extension registry, so their token usage is accounted explicitly
  (via an explicit isolated extension set or the worker's own usage events).
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
- **Delete.** Deleting a thread is an explicit human act: its outstanding contracts are released with reason
  `thread_deleted`, recorded in the ledger. Nothing is ever reconstructed as quiet from missing records.

## 7. Surfaces

### 7.1 App-server protocol (v2, experimental per field)

New methods and fields are gated individually with `#[experimental]`; existing `turn/start` and `turn/steer` remain
stable for clients that do not opt in. All payloads use camelCase tagged unions.

- **Notification `thread/contract/updated`** — small and thread-scoped:
  `{threadId, eventSeq, subject}` where `subject` is either
  `{type: "intake", intakeId, state: drafting | abstained{reason} | issued{contractId}}` (drafting is intake state; it
  never appears as an outstanding contract) or
  `{type: "contract", contractId, version, standing, workflow, assurance, summary}`.
  `workflow` ∈ `working | checking | supported | notVerified{reason} | didNotPass | waiting{blocker} | discharged |
  released`; `summary` is a terse, bounded string. Requirements and evidence are fetched on demand. Notifications never
  carry verifier prompts, reasoning, full logs, environment inventories or private paths.
- **Delivery** is authorized, thread-scoped and filtered to connections that declared the capability. The goal sink's
  fallback broadcast (`app-server/src/extensions.rs`) is not copied.
- **Reconciliation.** Every contract has a `version`; every event has a thread-monotonic `eventSeq`. Clients subscribe,
  then snapshot with a watermark, suppress duplicates, and recover gaps through `list`/`history`. Notifications are not
  the database.
- **`thread/contract/list`** `{threadId, filter: unsettled | all, cursor, limit}` → current views + `nextCursor` +
  watermark.
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
  indicators take precedence; otherwise the contract indicator is shown (goal and contract never coexist, §6.5).
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
  same-id weakened-assertion attack, timeout and infrastructure failure → `cannot_judge`, persisted attempts.
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
  - a question-only turn → no contract; a required clarification and an optional follow-up both verify, and neither
    triggers automatic repair while unanswered;
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
   zero-test success; same-id weakened assertion; same-metadata source edits; verifier defeat after human discharge;
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
2. The core shape of the human-input observation hook (start, steer, queued dispatch), its input sequence and
   attestation carrier, and the matching `continue_turn_if_idle` fence.
3. Restricted-read sandbox support per platform (Linux, macOS seatbelt, Windows); a platform without it abstains.
4. The source of the stable owner identity (account versus local user).
5. Default worker models and efforts, and the concrete ceilings to preregister for §8.5.

## 12. Delivery order

The spec is larger than one implementation plan. It is delivered as ordered slices, each with its own plan and each
leaving the tree green:

1. **Kernel** — `codex-pro-contract`: state, coordinate, commands, typed rejections, reference-model property tests,
   guard mutation tests, dependency whitelist.
2. **Generic host changes** — §3.3 items 1–5, each independently useful and free of contract vocabulary.
3. **Extension foundation** — ledger, durability protocol, SHA-256 subject store and capture, custody checks.
4. **Evidence** — the restricted sandbox profile, the Cargo adapter with both evaluation lanes, the review worker,
   certificates.
5. **Controller** — human control lane, automation lane (intake, draft, Issue, binding, candidate, verify, repair),
   fencing, budgets, thread lifecycle.
6. **Protocol and app-server** — §7.1.
7. **TUI** — §7.2 and §7.3.
8. **End-to-end and adversarial tests** — §8.3, §8.4 and the adversarial suite of §8.5 item 1.
9. **Controlled evaluation** — §8.5 items 2–4, planned and preregistered separately.

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
