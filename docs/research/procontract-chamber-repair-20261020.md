# Chamber repair: actual grants and scoped evidence

The `907392eff` strict Chamber attempt scored **1625/1748 (92.96%)**, versus the retained
Vals Luna/max row of 87.87%. It used 1000 shared provider requests and 130.61 minutes,
within the original six-hour/1000-request/offline grant. First official grading was valid,
with no known Go-build or port-conflict fixture failures. It is a disclosed development
task, not a fresh holdout, official leaderboard submission or causal native ablation.

| Observation, retained separately | Score |
|---|---:|
| Original bdf artifact, original grader | 77.00% |
| Same artifact under repaired grader | 77.92% |
| d785 retest | 81.24% |
| 907 retest | 92.96% |

Compared with the same-grader d785 artifact, 213 eligible tests improved and eight
regressed, a net gain of 205 tests (+11.73 pp). Much of the gain is in Secrets Manager,
S3/S3-KMS, environment behavior and validation. Internal Support was false, but the
artifact improvement is real and its official score remains valid.

## General repairs

- `d78546321` separates local review observations from exclusive per-obligation judgments,
  exposes captured file metadata, and adds pinned grader-only resources and observable
  retry cleanup. Assertions, official exclusions and the eligible denominator stay fixed.
- `ae22d30ec` exposes the host's delivery-action receipt without treating the response's
  own assertions as execution proof. Live Luna positive/negative controls passed with
  zero protocol corrections.
- `907392eff` removes implicit executor windows and guessed verification reservation.
  Successors inherit the exact original deadline unless an explicit local allowance is
  provided. Old code stopped a native 75-second control around 44 seconds; corrected
  code completed it around 58 seconds, while actual deadline cancellation remained intact.
- `55e395e5b` keeps inquiry labels as provenance rather than authority boundaries. A
  completed observation about one frozen subject can inform another original obligation.
  Subject identity, completed effects and execution-history distinctions remain enforced;
  errors identify their obligation/citation. Native old/new reuse controls and an actual
  Docker computation control passed. This later fix was not hot-applied to the scored run.

The d785 attempt exposed the deadline bug at 85.89 minutes and 736 requests: a default
1800-second successor window was incorrectly called original-task expiry, despite about
4h34m and 264 requests remaining. Its 81.24% score and failed termination remain recorded.
The 907 attempt crossed that old window, handed off, and ended at the actual request cap.

All changes are in harness/tool execution or strategy context. The pure
progress/responsibility kernel did not change. No task-specific exception, new acceptance
threshold, mandatory planner, score selection or denominator adjustment implements these
repairs.

## Lessons still to act on

The final 123 nonpasses include all 47 SSM mock tests. The implementation recognizes
standard AWS endpoint variables but misses the application-specific configuration entry
used by those tests. This demonstrates that implemented protocol logic can be unreachable
under required invocation conditions. Configuration aliases/precedence and successful
stateful paths need discriminating observations before declaring coverage.

Neither submission retained runnable regression helpers. The eight regressions underline
the value of preserving both motivating counterexamples and affected passing controls.
This belongs to strategy, supported by harness persistence and replay capabilities.

Four diagnostics consumed 148 completed requests without final judgments. Formal review
consumed 143 requests and provided only aggregate sealed mismatch counts, without replay
inputs; public checks progressed to 41/41 and the same internal suite rose 94/108 to
104/108. Resource cost, actionable feedback and partial assessment retention remain
harness/strategy concerns. They are not new kernel invariants.

Drafting also promoted permissions/recommended testing into obligations. Preserve the
user's normative force: permission is not duty, and evidence useful to a reviewer is not
automatically an additional deliverable owed by the executor.

Accounting reconciles 996 completed requests (executor 215, successors 484, preparation
six, formal review 143, diagnostics 148) plus four incomplete charged streams. All completed
identities are Luna/max. Two formal citation corrections recovered; the later inquiry-label
fix addresses one observed cause. Do not claim universal zero-error execution from these
finite controls.

Full records and failure analysis are in
`/data/ProContract/programbench-chamber-grant-retest-20261019/post-run-analysis.{md,json}`.
All 557 current and 1707 predecessor frozen-file entries were verified unchanged. Original
submissions, grades and stop reasons remain separate; no candidate was edited or rescored
during analysis. Owned solver/grader processes and the dedicated Docker daemon stopped.
