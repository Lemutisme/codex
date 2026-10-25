# Interruption and continuing responsibility

Analysis dated 2026-10-24. The design below preceded implementation; the dated
implementation update at the end identifies what has since landed and what has
not. Source inspected at `95c57b5fd` (solver cohort: `554356947`).
No solver was resumed and no benchmark outcome was changed during this analysis.

## Observed failures

Cohort: `/data/ProContract/programbench-work-selection-replication-20261024`.

| ProContract attempt | Stop | Requests spent | External result |
|---|---|---:|---|
| genact | Root response stream failed while status was drafting | 19/1000 | Compilation failed; no valid score |
| FFmpeg | Successor response incomplete: max_output_tokens | 385/1000 | 209/3041 (6.87%) |
| rustowl | Successor response stream failed | 529/1000 | 511/589 (86.76%) |

FFmpeg and rustowl stopped at about 67 minutes of their original six-hour grants.
Their successor shutdowns were confirmed, reservations were cleared, and no
session-count limit was present. Upstream faults explain the interrupted attempts;
the controller and driver explain why those attempts ended the whole run. These
records do not establish why the provider stream failed or what further work
would have scored. Rustowl's good external score remains good without Support.

## Source-level cause

- `controller/successor.rs` waits for successor shutdown and returns Interrupted.
- `controller/runtime/succession.rs` clears the pending reservation, then maps
  Interrupted to not_verified and returns before capturing the interrupted work
  or invoking the continuation strategy.
- `controller/runtime.rs` makes not_verified set Phase::Resting. Root failure
  similarly ends at executor_stopped; promote requires a completed handoff.
- `controller/runtime/continuation.rs` takes a Handoff with an issued contract,
  terms and assessment context. The decision entry point therefore cannot cover
  all admitted work, including the pre-Issue root failure seen in genact.
- The cohort's `on/run_case.py:100` ends on resting; line 104 independently ends
  on a failed root turn, even while the contract is still drafting.
- `scripts/test_procodex_native.py:952` verifies interruption, rest and recovery
  after restart plus a new user turn saying to continue. It does not test
  autonomous continuation without additional user input.
- `codex-api/src/sse/responses.rs` turns max_output_tokens into a stream error;
  the successor interface then retains an error string. A response-length stop
  and a disconnected transport need distinct observations for strategy.

The implementation preserves responsibility after interruption, but its scheduling
path depends on a completed handoff or another user turn. Persistence alone does
not provide autonomous continuation. Refusing to replay an uncertain operation
must not prevent a fresh decision using retained state and remaining authority.

## Minimal general repair

Keep responsibility, execution outcome, artifact assessment and scheduling
disposition distinct. An unsuccessful attempt says nothing by itself about task
completion, artifact correctness or the usefulness of another action.

1. Harness records a common execution outcome for roots, successors and workers:
   attempt/turn identity, known stop cause, shutdown/effect status, retained work
   references and actual spent resources. Preserve available structured provider
   reasons. Confirmed stopping permits capturing partial work without claiming
   a handoff, successful action, Propose or Support.
2. Generalize the continuation input from an assessed Handoff to admitted task
   context plus current observations and authorized capabilities. Issued terms
   and assessments are optional context. Before Issue, execution still uses the
   original intake and grants; formal acceptance continues to require its actual
   bindings. Do not fabricate acceptance obligations to make recovery possible.
3. Persist a pending strategy decision at the execution boundary. Deliver it to
   the existing context-level strategy under the original authorization. A
   selector interruption must leave the decision pending, rather than erase the
   task's ability to continue. Repeated delivery must not repeat dispatched work;
   use existing decision identities, reservations and owner epochs to fence it.
   Re-dispatching a decision is distinct from replaying a tool's uncertain effects.
4. Strategy chooses continuation, a fresh executor, diagnosis, checks, waiting or
   rest from available capabilities. Transport failures and output-length stops
   can call for different methods. Retry/backoff and workflow choices belong in
   strategy; the harness executes them and enforces actual allocation and owner
   cancellation. No universal retry count or mandatory review before resumption.
5. Expose an explicit run disposition to the outer driver. An interrupted action
   or momentarily idle controller is not enough to freeze and grade the run.
   Deliberate strategy rest/wait, owner cancellation, completion, actual hard
   limits and unresolved execution ownership retain their distinct meanings.

This is harness/strategy work. The kernel already retains the outstanding
responsibility and needs no retry transition. Resource consumption is not refunded;
deadlines are not renewed; absent deadlines remain absent. Known cancellation
prevents automatic continuation. Concrete unresolved effects are reconciled at
their affected scope before conflicting work; unrelated retained evidence stays
usable. No additional general evidence threshold is introduced.

## Required validation before another scored cohort

Use the native app-server and fault-injected response stream, with real file/tool
effects and no injected user instruction to continue. Cover root failure before
Issue, successor failure after a write, output truncation and selector failure.
Each must reach another authorized decision and produce a checked final artifact
when the chosen strategy continues. Verify process restart at the recorded-outcome
and pending-decision boundaries without duplicate dispatch or renewed grants.

Control cases must preserve owner cancellation, exhausted grants, optional task
deadlines and unresolved executor ownership. Evidence from an older snapshot must
not silently certify newly captured work. The runner must stay alive for pending
continuation and freeze only at its declared run-ending boundary.

Then qualify with real GPT-5.6-Luna/max ProContract-only E2E and fresh benchmark
attempts under declared resources. Keep existing graded attempts frozen. Native
Codex comparison, if separately requested, must actually enable and verify /goal.

## Deeper refinement: continuity at every execution boundary

The previous proposal is necessary but incomplete: a persisted pending decision
does not itself wake a strategy, and another selector call does not itself produce
useful work. The architectural target is continuity of authorized work across
execution boundaries, with useful method selection remaining in strategy.

Keep four views independent rather than extending one combined phase enum:

| View | Question | Ownership |
|---|---|---|
| Responsibility | What remains owed, under which terms and authority? | Existing kernel and original admission |
| Work and evidence | What exists, what was observed, and under which conditions? | Harness stores references; strategy/verifiers interpret them |
| Execution | What was admitted/dispatched, what stopped, and what effects are known? | Harness |
| Scheduling | What action was selected, or what event is being awaited? | Strategy chooses; harness persists and drives it |

Outstanding responsibility is compatible with waiting, cancellation of a specific
execution or a useful partial delivery. Support does not measure comparative task
quality. An interrupted attempt is compatible with a good retained artifact.
Receipt of the original task already provides an admission identity before Issue;
do not introduce a second kernel or duplicate settlement state to cover that case.

### A concrete continuity property

Every admitted, unfinished execution intention should have an inspectable
disposition: an active attempt, pending authorized dispatch/decision, a declared
wait with its wake condition, or an explicit suspension/end reason. An accidental
empty control path must not silently become the end of the task.

This is a conditional execution guarantee, not a guarantee that arbitrary tasks
are solvable or that an unavailable service eventually recovers. It requires:

- Commit an observed outcome and the resulting pending work coherently, either in
  one transaction or through a reconstructible projection of committed records.
  A process crash between two independent writes must not lose the continuation.
- Register the action identity and ownership before dispatch. After an uncertain
  dispatch, reconcile that attempt rather than treating absent output as proof
  of nonexecution. Idempotent control records do not imply exactly-once external
  side effects; tool-specific receipts or idempotency capabilities matter.
- A pending decision has a real wake/dispatch mechanism. Selector failure retains
  the undecided input; it is not a selected rest. Retry timing or a wait follows
  the strategy's previously selected recovery arrangement under the original
  grants, without asking another failing selector to authorize itself recursively.
- User input/cancellation supersedes stale actions through the existing owner
  revision/epoch. Late results remain historical observations and cannot dispatch
  superseded work. Recovery never creates fresh authority or refunds usage.
- Waiting is not run completion. The host can release a process while retaining
  the selected wait and resume on its event. A benchmark's actual deadline still
  ends that attempt; ordinary tasks do not need a synthetic lifetime or polling
  countdown to make this mechanism work.

The event mechanism should drive operations already selected by context-level
strategy. It must not grow a second configurable workflow interpreter. A strategy
can choose a sustained executor session; each tool call need not trigger another
model selector, reviewer or full workspace capture. Reads of frozen work need not
serialize with unrelated execution. Capture requires a meaningful consistency
boundary, not an invented claim that every external effect is transactional.

### Decision access is part of decoupling

Moving the selector prompt out of code leaves workflow coupling if code only
invokes it after completed handoffs or acceptance outcomes. Expose relevant
execution outcomes at normal completion, failure, resumption and selected waits,
including work before formal terms are available. Preserve action-specific
capabilities instead of forcing all workers into one broad executor interface.

The strategy's input should describe admitted task context, current work and
observations, actual permissions/resources and offered operations. Evidence can
refer to old snapshots without certifying the current one. A broad unavailable
acceptance claim must not hide a usable local counterexample or an independently
authorized next action.

The current generated brief in `controller/decision.rs:545` still says that ending
the turn hands the workspace to an independent verifier, while continuation.md
allows check, diagnosis, execution or rest. This is a concrete context inconsistency
to remove in the migration. Version the resolved effective context, including
generated brief/transport text; changing only policy-file hashes misses such code
contributions. Initial drafting/probing and protocol correction remain documented
workflow coupling, not new precedents.

### Retain useful work without turning memory into a gate

The general asset is a reproducible result with its conditions and provenance:
for example a CLI counterexample and probe, or a lemma with assumptions and proof.
The strategy chooses the domain representation. The harness retains and retrieves
it; it does not require every task to use a proof graph or a progress score.

New versions do not erase old observations. Exact reuse requires compatible subject,
inputs and evaluation conditions; reuse across changed dependencies must state its
basis. A historical success may guide a new experiment without being promoted to
current acceptance. An unsuccessful experiment can improve the next decision even
when artifact bytes and aggregate score do not change.

Avoid pushing the whole history into each prompt. Provide bounded views with links
to retained detail, and account for real storage/transport resources explicitly.
`controller/observations.rs` currently has a lifetime limit of 4096 evidence-access
receipts. It did not cause this cohort's stops, but it is a separate long-horizon
limit to examine. Replace accidental lifetime gates through storage/paging/resource
design as appropriate; do not simply remove operational size or memory bounds.

### Evolve capability and method separately

Autonomous recovery restores the opportunity to improve; it does not prove that
more execution improves the result. Rustowl's focused protocol experiments are a
useful positive example. FFmpeg's low external coverage despite passing public
checks shows why strategy must compare known defects with unobserved functionality.
These are scoped observations, not proof that a universal diagnosis sequence wins.

Use three separate validation questions:

1. Does a chosen action remain executable across failures, without lost work,
   stale dispatch, duplicated uncertain effects or changed grants?
2. Does a strategy use the retained state to select informative work, adapt its
   method and preserve earlier gains? A deterministic scripted strategy can test
   the first question; real-model trajectories are needed for this one.
3. Does the change improve external task quality and resource use on fresh tasks?
   Measure outcomes over the run when available, not only duration, calls or the
   number of Support events. Fault recovery tests alone cannot answer this.

For self-improvement, reuse the ordinary task mechanism and the existing RSI
structure proposal. A candidate change has a stated mechanism, exact version,
predicted observable effect, controls and fresh evaluation. Causal attribution
should distinguish harness correctness, strategy usefulness and artifact quality.
Old/new ProContract comparisons suffice; native Codex is not needed by default.
Adoption remains a separate authorized operation bound to the expected incumbent.
Automatic analysis and experiments do not themselves establish improvement or
authorize unrequested adoption. No fixed experiment count or score threshold is
added to the kernel.

Implementation order: first complete one native path from interrupted action to
durable observation, strategy decision, execution and independent artifact check;
then generalize it to pre-Issue work, workers and process restart. Remove obsolete
phase-driven endings and contradictory context as those paths migrate. Validate
strategy usefulness separately, then reuse the stable execution substrate for RSI.
This refinement adds no runtime implementation, new run or claimed performance gain.

## Implementation update, 2026-10-25

The first native execution path is implemented in the development checkout:

- `WorkSnapshot` replaces the handoff-only internal representation. Capture source
  includes an interruption, separate from delivery and in-turn publication.
- A failed root retains its captured work; when existing preparation completes,
  it reaches strategy selection. A failed successor is joined before its changed
  workspace is captured. The actual failed turn identity and reason are retained.
- Both paths use the existing context-level selector. It can check, diagnose,
  verify, continue or rest using the original capabilities and grant. No automatic
  executor retry sequence, new attempt ceiling or additional review gate is added.
- Interrupted work has a readable public evidence record and no fabricated
  delivery. Check/diagnosis do not Propose; selected verification proposes the
  observed subject once and preserves the original acceptance policy.
- Owner epoch checks reject a late interruption for a newer turn. Actual owner
  cancellation and unknown executor lifetime do not acquire automatic replay.
- The generated executor brief now describes selectable work rather than promising
  an automatic reviewer after every turn. The shared benchmark stop predicate is
  covered by a failed-root/active-lane regression. Frozen cohort drivers and raw
  results remain unchanged; new drivers must use the shared predicate rather than
  retain their former unconditional failed-root exit.

The pure kernel and store are unchanged. This is a bounded migration, not completion
of every design above: decisions still require issued terms, selector interruption
still rests, and controller process loss still requires explicit resumption. No
durable autonomous wake queue or RSI coordinator is claimed.

Validation artifacts and the final qualification outcome are recorded under
`/data/ProContract/procontract-interruption-repair-20261025/REPORT.md`. They include
Rust regression, Clippy, Python checks and native app-server/container/tool E2E with
a scripted fault-injecting provider. They are not new real-model benchmark scores.
