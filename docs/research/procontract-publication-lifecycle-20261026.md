# Publication lifecycle: recorded defects, repair deferred

User decision, 2026-10-26: record the findings first; repair them together later.
This document changes no executable code, policy prompts, frozen cohort or scores.

Evidence: `/data/ProContract/procontract-publication-rootcause-20261026/REPORT.md`
and `evidence-summary.json`, extracted from stopped attempts in
`programbench-full-timeonly-20261025`. Scope: the 12 execution-related early stops
among the 18 completed cases in the previously reported snapshot. The solver was
`c68db7c00a26057621b5a0d54a27e55d6969b1e7`.

## Confirmed defects

| Observation | Cases | Mechanism |
|---|---|---|
| Publication assessed with an inspection still recorded Running | lazygit, fzf, run, monolith, sd, eureka | Reviewer deadline drops the inspection future; cancellation cleanup does not persist the action's terminal lifecycle result |
| Pending publication without its final assessment | mdbook, gotests | Executor HTTP 503 interrupts the waiting caller; all recorded actions for that publication have confirmed shutdown |
| Pending publication after code-mode host disconnect | rumdl, felix | Caller loses its host generation; all recorded actions for that publication have confirmed shutdown; exact host-exit cause remains unknown |
| Confirmed action timeout stops the whole task | caps-log | A roughly 180-second check pipeline timeout becomes Infrastructure/resting with about 237 minutes still available |
| Reviewer transport failure stops the whole task | tparse | ExecutionInterrupted from formal review bypasses continuation, despite confirmed shutdown of recorded check/inspection actions |

`runtime/progress.rs::progress_ready` can finish the last accounting write when an
already resolved `progress_assessed` document exists. It cannot reconcile missing
publication completion, unresolved execution receipts, or a later cleanup result.
Selection and restore call this gate before strategy can choose further work.
Formal verification separately admits only certain NotVerified classes to the
selector, turning known local failures into task-wide resting.

The cancellation test currently asserts a Running receipt even after the process
is killed. The recovery test asserts that an unresolved publication remains blocked.
Those checks cover non-replay and honest uncertainty but omit eventual recovery
after effects/lifetime become knowable. The implementation needs both properties.

## Consolidated repair scope

Keep this work together with the unfinished continuity design in
[procontract-interruption-continuation-20261024.md](procontract-interruption-continuation-20261024.md),
rather than adding an exception for each observed error string.

- Harness owns durable operation and resource identities, execution, cancellation,
  cleanup, terminal observations and recovery. Caller/transport lifetime must not
  be the sole owner of an admitted operation's finalization.
- Keep operation result, confirmed lifetime/effect status, responsibility and
  scheduling disposition distinct. Confirmed failure can permit a fresh decision
  without becoming success, Support, rollback or a renewed resource grant.
- Reconcile publication from retained suboperation facts. Do not clear pending
  merely because an error looks transient. Actual unresolved effects constrain
  conflicting operations at their relevant scope.
- Feed usable partial outcomes and recoverable interruptions to strategy. Strategy
  chooses continuation, diagnosis, a different method, waiting or rest. Durable
  decisions and wake/dispatch are harness capabilities, not a second workflow engine.
- Cover executor, reviewer, selector, tool host and process-restart boundaries.
  Preserve user cancellation, owner epochs, all spent resources and real limits;
  ordinary tasks retain the option of no hard deadline.

Qualification must include native cancellation during inspection, publication
caller loss, code-mode host loss, confirmed check timeout, reviewer 503, and process
loss during finalization/decision persistence. Check retained partial work, original
allocation, no duplicated uncertain action, and a subsequent authorized decision.

Kernel semantics require no benchmark-specific additions. Existing valid external
scores remain valid. No repaired performance gain or recovery implementation is
claimed by this record.

Strategy analysis is recorded separately in
[procontract-general-strategy-20261026.md](procontract-general-strategy-20261026.md).

## Follow-up observations, 2026-10-27

The [third trajectory pass](procontract-trajectory-analysis-20261027.md) records
two more publication endings: dua loses its code-mode host generation with
publication 28 pending; dust's publication 44 retains a Running inspection after
reviewer timeout. The host-exit cause is still unresolved. Dust stops at 354.84
minutes, so do not equate its lost time with much earlier failures.

Zstd adds a confirmed pre-Issue continuity gap. Its drafter response grows to
208,256 characters while expanding zero-filled test data and ends with
max_output_tokens and invalid JSON. The existing case representation already
supports repetition. Draft failure is directly mapped to abstained; the executor
continues to its first delivery, but no strategy decision follows despite remaining
task time. Preserve the original admission and useful work without admitting the
truncated response as terms. Include this boundary in the consolidated repair.

Oha supplies a positive real-model control: root max_output_tokens interruption
is followed by interrupted_snapshot, work_ready and successor selection, and the
same grant continues to about six hours. This validates use of the implemented root
path without proving a counterfactual score gain or closing the other role boundaries.

Tinycc's observed missing runtime/header files also require later reference-capability
qualification. The record confirms those failed reference paths; it does not establish
whether image contents or provisioning caused them. Do not convert that investigation
into an unverified relocation diagnosis or a post-hoc denominator change.
