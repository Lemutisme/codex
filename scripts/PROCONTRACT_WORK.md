# ProContract: responsibility, working evidence, and replaceable execution

The current implementation extends the durable task, scoped judgments and frozen
computations with publication during an active turn and enforcement of the original
task grant. It preserves the pure settlement kernel. Older frozen benchmark results
remain attached to their original binaries; they do not measure this version's performance.

Architecture ownership follows [kernel / harness / strategy](../docs/PROCONTRACT_LAYERS.md).
**Strategy** is prompt/skill/context-level instruction, including workflow orchestration.
**Harness** is agent-control/tool code implementing the necessary capabilities and actual
execution constraints. Keep both essential and decoupled from the responsibility kernel.
The components below describe the present implementation; existing hard-coded workflow
choices are migration work, not a reason to assign those choices to harness.

## The unit of continuity

A task persists; an executor is one bounded attempt to advance it. The host owns
the original authorization, contract, artifacts, evidence and remaining grant.
Neither conversation history nor an executor's summary is the responsibility's
source of truth.

The current implementation composes these responsibilities:

| Layer | Owns | May not decide |
| --- | --- | --- |
| Strategy context | Task reasoning, choice and composition of experiments, checks, diagnosis, repair and handoff | New execution authority or the truth of unobserved effects |
| Kernel and store | Roles, current subject and policy coordinates, support, discharge, release | Which experiment to try or whether a model is intelligent |
| Working evidence | Retained observations, exact available public receipts, registered counterexamples | New authority, policy changes, or task completion |
| Controller mechanisms | Prepare/capture evidence, invoke verification, execute continuation and report concrete limits | Task-solving workflow choices, inferring missing evidence, or silently renewing a grant |
| Codex adapter | Native worker/session creation, context transport, tools, cancellation and confirmed exit | Issuing or discharging from a successor session |

The OpenCode V2 contribution is the separation between persistent responsibility
and replaceable execution. R2 contributes an operational method: consequential
unresolved observations choose discriminating experiments, coherent repairs and
replays of the original invocation and affected controls. Codex contributes the
explicit distinction between a proposed candidate, evidential support, and an
authorized settlement. These contributions do not require test-time RSI.

## Implemented behavior

Frozen terms now have a derived obligation catalog. Existing acceptance requirement IDs
remain unchanged; the host assigns collision-free IDs to execution constraints. Each
entry retains its source quote, inference status and artifact/execution scope. IDs are
stable within the frozen terms hash; no continuity is inferred across a revision. This
view does not rewrite historical terms or create another source of authority. The
versioned assessment protocol and frozen evidence policy govern admissible evidence.

Review response schemas enumerate exactly the current catalog IDs. The legacy wire field
`requirement_id` refers to an obligation of either scope. Missing execution evidence is a
scoped gap, and a valid partial judgment retains independent coverage and findings.
Execution findings do not themselves authorize an artifact repair: they remain explicit
`execution_constraint` blockers. Artifact counterexamples outside that scope can still
direct an already-authorized repair while the blocker remains. This does not assert that
all execution obligations are irreparable; it avoids inventing a repair permission or
pretending an artifact rewrite changes the past.

Native `contract_read_evidence` calls retain bounded access observations. A prepared
response records the immutable source, exact UTF-8 range/hash and native caller identity.
A separate lifecycle receipt records completed, unsuccessful, failed, blocked or aborted
completion. Missing completion remains unknown, including after restart. Code-mode
invocation identity includes the cell and nested call; both root and successor adapters
record the same semantics. The task has one persisted allowance of 4096 access receipts;
new sessions cannot reset it. Raw command/tool payloads are not copied into this journal.

Formal and progress assessments receive a `host_observations` document frozen at their
own capture boundary. It includes publication ordering, access receipts and bounded
baseline entry comparison, with explicit omissions. Later completions cannot change an
earlier assessment. This proves native tool completion, not model rendering or
comprehension; endpoint equality does not prove no intervening edits. It is not a full
execution monitor and makes no absence claim about network, installation or arbitrary
external effects. Unsupported obligations remain gaps. An executor's final response
cannot self-certify execution coverage.

A malformed review may receive one protocol correction in the same isolated reviewer
session, with the same evidence object, citations, read/computation allowances and original
deadline. A durable reservation precedes correction dispatch; rejected and final responses
are retained separately. Valid negative/unknown judgments do not trigger this correction.
Exhaustion remains unknown. A certificate binds the committed verification event, which
links the complete observation document. Its source basis also commits to the observation
document and delivered response, so identical artifact bytes cannot conceal different
execution-evidence sources. The pure settlement kernel is unchanged.

`publish_progress({request_id})` pauses the provisioned executor, captures immutable
workspace bytes, confirms resume, then assesses the snapshot. It retains public working
evidence without proposing a candidate or changing the contract. Executable tasks receive
public check results; ReviewOnly tasks retain bounded local review. Formal handoff still
requires the full applicable acceptance policy and independent review. Sealed cases never
enter adaptive publication feedback.

The original intake binds a durable publication grant. Reopening a request returns its
receipt; artifact checks with identical subject, policy, environment and harness identity
may reuse the prior assessment. A new diagnostic request freezes its own observation basis.
A reservation
without resolved effects blocks acceptance and further automatic execution. Recovery may
reconcile a committed assessment, but never assumes an interrupted dispatch did not run.
Publication records are available through `index` and `read`; they do not alter the formal
candidate frontier or mint new authority. Fresh successors inherit only scoped publication
and evidence access, under the original grant and their admitted execution slice.

New `procodex` tasks enable this capability by default (`--no-progress` opts new tasks out).
Existing task settings and grants are preserved. The native configuration is:

```json
"progress": {
  "executor_label": "procontract.task=<provisioner identity>",
  "assessment_secs": 120
}
```

Count ceilings and `executor_slice_secs` are optional explicit grants. New launchers
inherit the original task deadline without inventing publication/session counts or a
30-minute executor window. Admission does not subtract an estimate of future verification
work: allocating time to implementation and assessment belongs to strategy. A successor
packet distinguishes its effective executor deadline from the original task deadline;
an explicitly configured local allowance never renews or replaces the original grant.
Existing grants remain binding on resume. `publish_progress({request_id, review: true})` requests diagnosis even when
checks fail or the checking method is unavailable. The response carries remaining-budget
facts. Diagnosis retains its findings and gaps without granting Support or settling.

Named `--input NAME=FILE` attachments are snapshotted outside mutable outputs and mounted
read-only for execution, checks and enabled computations. Their original modes, identities
and usable paths survive successor sessions. A supplied `--strategy DIR` selects context
files; it does not change the original task grant.

This first capture adapter requires exactly one exclusively provisioned workspace
executor. It verifies the label, exact mount and lifecycle before pausing. External host
editors and multiple threads writing the same workspace are outside this capture contract.
Original deadlines clamp preparation, verification and continuations. Expiry interrupts
and awaits the task's native actor shutdown, then records exhaustion or unresolved cleanup;
it does not delete containers by workspace label. Zero successor sessions still permits a
finite original task grant.

The trusted exec-server startup limits each process to 32 MiB of raw emitted output and
1800 seconds, and each executor to 256 MiB of raw output. Output accounting happens before
transport encoding and spans all reads; polling cannot renew it. Native resource failures
survive reconnect/read/closure. Docker logs rotate at 16 MiB × 2. These are specific bounds;
there is no aggregate writable-workspace filesystem quota.

Delivery now retains the actual native final response as a separate immutable artifact,
bound to its workspace subject and turn. Continuation summaries remain bounded and cannot
substitute for that response. The host records original byte count/hash and a 64 KiB retained
head/tail limit. Truncation is explicit and cannot provide positive review coverage. The
reviewer can assess a requested final explanation; its claims are not independent proof.
Successful check output and the actual host-configured command are also retained. Frozen
evidence pages are 4096 UTF-8 bytes with an 8192-byte response bound; complete request/terms
reads and citation validation remain required. Baseline equality reports exact entry bytes
and mode, not semantic equivalence.

`controller/ports.rs` describes the execution boundary; `native.rs` and
`successor.rs` implement it using Codex. `work.rs` constructs public evidence and
folds registered public check outcomes. `archive.rs` reads the existing immutable
verification journal and content-addressed blobs. `evidence_tool.rs` adapts that
reader to Codex, including an explicitly restricted extension registry for fresh
isolated executors. It does not enable the contract controller inside a successor.

Every verification retains a public projection before its verdict can advance
the contract. Its hash is bound into the verification event, together with the
contract, candidate generation and subject. A Defeat now identifies that committed
verification event, rather than only a shortened residual string. If evidence or
its journal cannot be committed, the controller records infrastructure blockage
and grants no Support or new executor on that result.

The model-facing `contract_read_evidence` tool has three operations:

- `index`: page through the task's retained verification records.
- `read`: recover exact UTF-8 pages of a handle from that index.
- `frontier`: list registered public checks with a failed observation and no later
  complete passing replay under the same contract revision and evidence policy.

Read access is bound by the host to one contract. The model cannot select a path,
read arbitrary blobs, or retrieve another contract's evidence. Public check
invocations and received details survive compaction, restart and more than three
successor summaries. Sealed case identities, invocations and individual outputs
are excluded before the projection is stored. Recall does not rerun a command.

The frontier is deliberately mechanical. A later green result closes only the
same registered check; omitted and unqualified checks do not erase older failures.
Results fold by candidate generation, so a late superseded verification does not
override a newer replay. The controller refuses Support while retained public
checks still lack a complete passing replay. This is a necessary consistency
condition, not a claim that registered checks cover the task.

Candidate judgment and evidence readiness are distinct. A failed public check
can defeat the candidate while sealed reference observations are insufficient.
The Defeat and the evidence blockage are retained separately. The controller may
repair the observed candidate failure under its existing finite grant; the blocker
still forbids Support after that repair. A blocker without an actionable Defeat
does not schedule another solver. Authority, cancellation, confirmed shutdown and
intake-time budgets govern every continuation.

Review scope disputes identify affected requirement IDs. An unaffected finding
can direct repair while the dispute still blocks Support; a disputed finding
cannot. The host renders only individually bound findings when scope is disputed,
excluding the reviewer's unstructured residual. Legacy unscoped disputes retain
their conservative stop behavior. The controller never silently edits terms to
remove a dispute or treats an omitted requirement as new repair authority.

The native long-input regression exposed a necessary dependency distinction:
cases skipped after a failed build previously appeared as failed, qualified
observations even though neither program ran. They now report `blocked`. They
neither support nor defeat a behavioral claim. The same rule applies after the
candidate timeout guard: skipped cases are blocked, not fabricated executions.
Build repair and evidence sufficiency require no optimistic dependency heuristic;
they are independently recorded facts. Original failed fixtures are retained
separately from successful validation.

Task admission is an immutable intake receipt committed before model-authored
terms. Completed executions commit task-scoped artifact deliveries even if a
drafter declines or evidence preparation fails. Deliveries bind the original
intake, exact subject, turn and execution epoch; later appends from an older epoch
cannot replace a newer handoff. Recovery restores admission without redrafting or
renewing a grant. The benchmark adapter can materialize these delivered bytes for
external grading independently of internal judgment, while retaining process exit,
successor accounting and original authorization checks.

Issue freezes both terms and the actual evidence basis. Preparation failure is
an explicit optional field in the hashed policy, never an empty successful suite.
Before Issue, the host executes the sealed invocations against the reference and
records calibration observations, including individually stable channels. New policies
have no implicit numeric cutoffs: the review strategy assesses the retained evidence.
Explicit owner-supplied criteria retain their blocking meaning; historical policies keep
their original values and hashes. A failed preparation is retained as a method observation,
not silently turned into a successful suite. Runtime checks still establish their own evidence;
calibration does not establish coverage or make a later check unnecessary.

Invocations can explicitly request a controlling PTY with fixed dimensions and
terminal input. Text stdin stays a separate file stream; null stdin attaches it
to the terminal. Terminal stdout/stderr are one raw byte stream, with no terminal
emulation or normalization. An optional ordered `dialogue` of literal `{expect, send}`
exchanges waits for actual output, including triggers spanning read boundaries, before
replying. All declared exchanges must finish; process exit alone cannot satisfy a missing
exchange. Ordinary input remains independent of terminal replies. This is a bounded
protocol capability, not a complete terminal emulator or an arbitrary timing language.
Adapter errors and incomplete reference receipts remain explicit. A proof/document ReviewOnly policy with
no executable checks uses its frozen evidence catalog without starting a container;
its receipts explicitly state that no program was executed.

Executable check capabilities belong to the host profile. New drafts cannot turn
an arbitrary self-test obligation into a Rust/Cargo requirement: the model's old
`candidate_tests` switch is no longer requested or adopted. Requested self-tests
remain terms to be evidenced and reviewed; an operator can supply their actual
command in the existing build/check command. Historical frozen policies retain
their original explicit Cargo-test behavior and hashes.

The replaceable `work_method.md` strategy is supplied from the original executor's first
request, independently of contract admission, and to fresh successors. It asks the executor to retain runnable probes and live
hypotheses in task-owned workspace files. The host captures those files with the
candidate. Summaries point to evidence; they do not replace it. The recent budget
lesson preview is retained as context,
but the complete public verification history has a separate durable source.
The method keeps counterexamples, unexamined cases/interactions and unsupported
assumptions distinct. An empty failure queue does not end discovery; concrete
experiments or derivations may still advance a consequential unresolved claim.
These are execution instructions, not a mechanical certificate of coverage or
novelty, and their own digest is recorded alongside the worker policies.

The reference-observation handoff preserves the normalized invocation JSON,
including stdin, fixture contents, environment and terminal input. Per-case byte
allowances and explicit omission markers keep large examples from hiding later
ones. Request catalogs also state their mechanical completeness and consecutive
span count; a sentence crossing span boundaries does not mean text is missing.
The final worker packet preserves short evidence sections in full before sharing
remaining space among large sections, so retaining more documentation does not
truncate a small, otherwise complete observation.

Differential invocations use a common isolated Python standard-library supervisor
for actual pipes and PTYs (the check image must provide Python 3.9 or newer).
Only the target receives case environment variables. Timeout and exec failure
are observed independently of the target's exit status; 124 and 137 are not magic
timeout codes. Process groups are closed at invocation end. These later input and
invocation changes are validated separately from experiments frozen at 24e14c2c9;
those experiments and their performance labels are not rewritten.

## Continuous observations and scoped judgments

A check batch can stop while retaining complete earlier checks. Each host action writes
its original binding and start record before dispatch, streams bounded stdout/stderr into
a durable journal, and records completion, failure, timeout or unknown lifecycle separately
from the observations. Journals are unique and are never overwritten as a retry. A start
without a completion is not evidence that the action did not execute. Process groups and
owned containers are cleaned on deadline/cancellation; unconfirmed shutdown prevents
automatic candidate repair based on that run.
This also applies to inspection actions: a recovered unknown shutdown or an unreadable
action journal blocks Support and continuation while preserving any local review.

Only complete protocol records in the expected case order can become check receipts.
Unfinished trailing records, missing calls and corrupt sequences cannot produce passes.
A complete individual public counterexample can authorize an existing bounded repair
even when another check timed out. An individual complete passing replay closes only
that same registered counterexample. Whole-task Support still requires its full applicable
policy and no outstanding blockers. Legacy records without individual completeness keep
their old whole-pipeline interpretation.

Reference observations retain partial batches and their execution status. Repeated reference
timeouts, exec failures or incomplete dialogues stop further equivalent spending; remaining
checks are unobserved/blocked. A successful help call or a stable error does not establish
normal-operation coverage. Check images resolve to immutable local identities, and metadata
operations share the finite check allowance.

Reviews can return `partial`: positive coverage, concrete findings, scoped `gaps` and any
unscoped uncertainty coexist. Unknown requirements remain unknown, conflicting judgments
are rejected, and positive citations are resolved against frozen evidence even in a partial
review. Full local judgments are retained in the task's public evidence archive. Only
unaffected findings direct repair; an unavailable attachment does not erase an independent
proof or turn its lack of inspection into success.

## Frozen evidence computation

`procodex --review-compute` explicitly enables bounded Python inspections in the configured
check image. It keeps the existing task/home and succession history. The equivalent native
setting is:

```json
"review_execution": {
  "max_calls": 8,
  "timeout_secs": 30,
  "max_output_bytes": 65536
}
```

Without this grant, artifact review remains read-only text inspection and starts no
computation container. With it, the native reviewer gets `inspect_evidence` alongside
`read_evidence`. The model names frozen file IDs and requirement IDs, not host paths or
mounts. Selected files are mounted read-only as `/evidence/file-N`; Python may use isolated
`/tmp` scratch. The existing local image supplies libraries: the capability does not install
NumPy, SymPy or other dependencies or fetch data. The container has no network, dropped
capabilities, no new privileges, bounded memory/process/CPU use, and no host credentials.

Each computation preserves its selected input hashes, Python program, image identity,
execution receipt, bounded output and capture limits. A program exit or numeric observation
is not an automatic proof. Failed/truncated computations cannot be cited as positive coverage;
reviewers must distinguish failed methods from candidate counterexamples and finite checks
from universal arguments. Complete computation documents and action receipts are linked by
the host into the task archive, even when the review itself cannot finish. Only explicitly
linked, subject-matching documents are readable through `contract_read_evidence`.

A persisted grant binds subject, terms and capability. Reservations precede validation and
dispatch; restart, malformed requests and failures do not refund calls or renew the original
deadline. Completed documents can be reopened with validated identities. An unresolved
prior action blocks another computation until reconciled. A new worker does not acquire a
new grant merely because its context is fresh.

The current implementation rechecks new candidate versions conservatively. It does not
infer a complete mathematical dependency graph, implement arbitrary irreversible external
transactions, or automatically repair an unavailable service. It supplies reusable evidence,
judgment and lifecycle boundaries on which those domain-specific methods can operate.

## Deliberate boundaries

- The public archive preserves the checker's available receipts, not arbitrary
  executor tool streams. Check details already have a 4,000-byte capture limit;
  omission markers are retained and the boundary is described in every record.
- The frontier does not judge natural-language hypotheses, infer repairs from
  changed files, or automatically add tests to the frozen evidence policy.
- Review findings remain readable in the archive. They are not reduced to
  mechanically resolved check IDs.
- Historical events without public projections are not retroactively presented
  as complete public evidence. Their existing recovery and residual behavior
  remains available; new verifications produce the new records.
- The controller remains a Codex extension. The domain and adapter boundary is
  explicit, but this change does not introduce a cross-harness framework, a Pi
  backend, or a replacement model loop.
- Support remains within-reach evidence. Human settlement rights are retained.

## Evaluator capability before inference

The canonical ProgramBench adapter runs `ready` before its first paid inference marker.
Its registry and source/image/wheel hashes bind a single durable 600-second collection
reservation. Restart may reuse a completed receipt but cannot replay an unknown dispatch
or renew the deadline. Host-only diagnostics and hidden test identities stay in the grading
domain; the readiness receipt exposes aggregate counts and hashes.

The probe exercises an ordinary null build and dependency setup, then collects tests with
the frozen image's reference executable. Collection can execute import-time probes such as
`--help`; collected test bodies do not run. Exact eligible test identities must equal the
official frozen metadata. This qualifies bootstrap and collection, not candidate quality or
all runtime dependencies. Formal scoring retains the official assertions, fixed denominator
and ordinary candidate executable validation.

Optional `grader_requirements` are exact, operator-pinned Python package versions installed
offline from the frozen wheelhouse after candidate compilation/hash. The adapter verifies
the stashed candidate hash again afterward. The extension and kernel contain no package-
or benchmark-specific repair rules. Grader dependencies cannot be chosen by a solver.

Official ignore entries can name pytest collector modules, including modules that failed
to import when the catalogue was produced. The adapter resolves those exact module
identities before import in both readiness and scoring. Installing a grader dependency
therefore cannot accidentally reactivate the children of an excluded module. Ordinary
leaf exclusions remain in the official scorer; a similarly named module, unignored import
failure, missing eligible test or changed denominator is not waived. Scope receipts and
the adapter/plugin hashes are retained with the grader evidence. No task IDs, guessed
name prefixes, new ignore entries or modified test assertions implement this rule.

Optional `grader_assets` pins a grader-only archive, its SHA-256, environment values and
relative PATH additions. Toolchains and dependency caches are installed only after the
candidate has compiled and been hashed; its hash is checked again afterward. These
resources are not mounted into solver containers. Preparation can use the network, but
actual test execution uses the pinned resources offline. Archive permissions must allow
installation in the evaluator's restricted container; preparation failures remain visible.

The test-runtime adapter records each setup/call/teardown outcome and attempt number.
After a failure report is rendered, it releases finished traceback-frame locals and
reclaims unreachable objects before the next attempt. This prevents a retained exception
from keeping otherwise-unreachable sockets alive across official retries. Live fixture
resources, test assertions, retry counts, timeouts and worker scheduling are unchanged.
Collection and valid score aggregation do not establish fixture execution readiness;
qualification must also inspect actual execution outcomes. A fixture error is not
automatically a candidate defect or permission to change the eligible denominator.

Reviewer wire output uses one judgment per assessed obligation, with local observations
stored separately. A supported judgment requires an issued evidence citation; a defeated
judgment retains counterexamples and may also retain unknowns. Unresolved observations
do not create support. The host derives the aggregate conclusion and binds support
citations to their original scope. Old review records remain readable without silently
normalizing contradictory legacy support claims. This changes the harness interface;
workflow choices and empirical testing advice remain in the strategy policies.

Formal host observations also retain the delivery capture receipt, its turn/subject
binding and original response-capture state. An available captured response can establish
the act of submitting a final response, while its assertions remain unverified claims.
Progress snapshots carry no final-delivery receipt, and absent/unavailable response states
are preserved. Execution support still requires scoped host observations or check receipts;
the message body does not become evidence that its claimed actions occurred.

An inspection's `requirements` records the inquiry's declared targets. It does not
restrict reuse of its observed facts to those labels. A completed, untruncated computation
over the same frozen subject may inform another obligation in the same frozen terms;
the reviewer must justify relevance. Subject identity, successful completion, resolved
effects and execution-versus-artifact provenance remain enforced. Citation errors identify
the affected obligation and citation so correction need not erase unrelated valid support.

## Validation

The 2026-10-17 E2E evolution and all development failures are recorded separately in
[`procontract-progress-e2e-20261017.md`](../docs/research/procontract-progress-e2e-20261017.md).
The mdbook capability preflight qualified all **1114 eligible tests across 12 branches**,
with no model calls or candidate scoring. This does not update any earlier ProgramBench,
COLT or Vals performance result.

Continuous-work qualification on 2026-10-16 passed **240 Rust tests** (kernel 36,
store 39, extension 165), **53 Python regressions**, **12 real pipe/PTY tests**,
formatting, Clippy with warnings denied, and native builds. Docker-enabled Rust
tests exercised frozen NPZ computation, isolation, failure/truncation refusal,
durable grants, cancellation and process-group cleanup. Fault injection verified
that an unresolved or damaged inspection journal blocks both Support and automatic
repair while retaining the independent local review.

Seven native app-server/code-mode/Docker scenarios passed on the final package:
frozen binary computation, partial review and bounded repair, reactive dialogue
through a fresh successor, interrupted checks retaining a failure and its passing
replay, process restart, scoped terms disputes, and long original-request succession.
The ledger audit verified one responsibility, preserved original grants, explicit
remaining gaps, subject-bound computation handles, and no automatic Discharge.
All provider responses were local scripted fixtures; no real-model inference,
ProgramBench score or COLT quality improvement was measured.

Commands, exact binary/source identities, retained failed attempts and limitations:
[`continuous-work-validation-20261016/REPORT.md`](/data/ProContract/continuous-work-validation-20261016/REPORT.md).

The regression suite exercises retained evidence beyond residual bounds and
three summaries, Unicode and NUL round trips, restart, task scoping, sealed
non-disclosure, damaged evidence, a late old verifier, and an unrelated green
batch that must not erase an earlier counterexample. It also verifies that a
candidate Defeat can receive a bounded repair while its independent evidence
blockage persists and continues to forbid Support.

The native succession fixture requires an actual isolated Codex successor to
call `contract_read_evidence`, recover the original failed build receipt, repair
the workspace, exit, and reach Support through the same contract. It runs through
app-server, code-mode and Docker using a localhost scripted provider. Its result
is mechanism evidence, not a real-model performance or RSI result.

See `/data/ProContract/work-validation-20261015/REPORT.md` for the completed
commands and results from the preceding `37468af98` implementation.

Recorded on 2026-10-15: 213 Rust tests passed (kernel 36, extension 138, store 39),
the changed build-blockage check also passed against an actual Docker container,
and package formatting plus Clippy with warnings denied passed. Three native
fixtures passed: short-request succession with evidence recall, 5,040-byte
request succession with evidence recall, and process restart followed by another
handoff under the same contract. All used local scripted provider responses;
no real-model or ProgramBench performance result was produced.
