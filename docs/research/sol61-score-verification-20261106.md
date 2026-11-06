# Sol score verification, 2026-11-06

Operational audit: `/data/ProContract/programbench-score-audit-20261106/`.
The user requested direct score reporting and continued grading verification.

## Recomputed results

At15:51 UTC, the original cohort had196 ended jobs and165 published usable scores.
All165 recomputed exactly with the pinned official `score_instance` function:
89.614205% mean over these165 tasks,89 tasks at least95%, and10 fully resolved.
The retained Dog calibration also recomputed exactly at1254/1300,96.461538%.
Original, independent retry and calibration results remain separate.

The audit checks the original per-test vector, active branches and ignored tests,
fixed fixture identities, published pass/total counts, archive/receipt hashes and
the first protocol-ordered usable evaluation. It does not run candidate tests or
solver inference and does not change published campaign scores. Defined scores
with `not_run` remain visible; execution completeness is a separate observation.

The official submission aggregate over the full200 denominator is also retained
in the audit as a distinct field (`mean_score=0.7393` at this checkpoint). It is
not the mean over165 scored tasks. This explicit denominator prevents confusing
the evolving submission total with the quality of already measured artifacts.

## Remaining measurement failures

The31 ended jobs without a usable published score are not one failure class:

-23 have `compile_failed`, with missing `compile.sh`; the official scorer's raw
  zero remains in their records. These selected cases are in the independent retry
  queue. A candidate build failure must not be called a grader infrastructure fault.
-Five reject a special archive member during extraction: masscan, dutree, xplr,
  pls and Broot.
-Felix fails on an archive path length; Oha failed at writer closure/capture.
-Age compiled successfully but failed to retain official test-scope receipts.

The audit preserves these distinctions. No archive member or failed test was
silently removed to obtain a score.

## Continuous verification

`audit_scores.py --watch` observes the original Sol cohort, the37 independent
retries and the retained calibration. Newly published score records trigger
official recomputation and a retained case receipt/event. It runs as
`procontract-programbench-score-audit-20261106.service`, polling every30 seconds
and exiting after both solver cohorts are terminal. It neither starts another
benchmark job nor changes admission capacity or solver allocations.

Six controls use retained real outcomes: a full-score positive, a wrong published
scalar, a wrong artifact binding, a changed eligible denominator, an incomplete
but defined Jsonschema score, and a compile-failure zero. All pass. This is an
operational measurement observer outside the kernel and task-solving strategy;
it does not establish an automatic RSI subscription or promote code changes.
