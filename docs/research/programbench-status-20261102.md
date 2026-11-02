# ProgramBench completion status, 2026-11-02

## 02:44 UTC update

The original scheduler has drained and exited: 200 terminal job records, including
179 valid scores. Crowbook is the latest valid artifact at **592/807 = 73.36%**;
its complete eligible feedback vector was checked. Including the eight recovered
same-artifact scores, the first-attempt projection now has **187/200 valid scores**,
mean **76.8748%**, with a same-task Vals reference mean of 68.8626% under different
request resources. Perfect artifacts remain three.

The completion scheduler is live with twelve solvers (the eleven first admissions
and the separate stgit retry) plus SQLite grading. All solver request timestamps
are advancing. Pandoc has used about 291 of its 360 minutes and 2517 requests;
its deadline remains 03:53:30 UTC and it has no canonical score yet. There are no
jobs waiting for initial admission. The host retains about 152 GiB available RAM
and 486 GiB free disk.

SQLite's first repaired evaluation still hit the original 3600-second batch-command
limit twice in branch `4ee128ddea8e`; subsequent diagnostic aggregation found the
stopped container unavailable. Its first outcome remains invalid (13245 `not_run`
entries), and the original protocol's second evaluation is in progress. No command
limit, scoring allocation, test grouping or denominator was changed to manufacture
completion. The retained prefix of completed work is distinct from a complete
eligible result vector; coarse batch termination still needs investigation under
the existing lifecycle/evidence-retention directions.

The duplicate-admission count remains three. Crowbook's newly published valid
terminal result was not put on the completion list, providing a live transition
check after the scheduler repair. Evidence is retained in
`/data/ProContract/procontract-status-20261102-0244/`.

## Earlier 02:04 UTC snapshot

At 02:04 UTC the original first attempts plus declared same-artifact scoring
recovery have **186/200 valid scores**, averaging **76.8937%**. The retained Vals
reference for that same subset averages 68.8391%; request resources and recorded
measurement conditions differ. The independent stgit retry remains excluded from
this first-attempt aggregate. Hex, zip-password-finder and cmatrix remain the
three perfect artifacts.

All eleven previously unstarted cases are now actually solving. Pandoc has no
score yet; its original six-hour deadline is 03:53:30 UTC. The original cohort's
last solver is crowbook, approaching its deadline. The completion queue also has
SQLite's retained-artifact evaluation and the independent stgit retry running.
Thirteen solver processes and one grader are live across the two queues; there
are no remaining jobs waiting for admission. Recent requests continue advancing.
The host has about 156 GiB available RAM and 561 GiB free disk.

## Recovered observations

Eight formerly unavailable artifact scores are now valid, without new solver
inference for those artifacts:

| Case | Passed / eligible | Percent |
| --- | ---: | ---: |
| DuckDB | 1354/5649 | 23.97% |
| jq | 5044/6072 | 83.07% |
| dutree | 495/641 | 77.22% |
| hashcards | 955/1019 | 93.72% |
| dstask | 1180/1278 | 92.33% |
| datasurgeon | 410/502 | 81.67% |
| PHP | 2196/14288 | 15.37% |
| git-trim | 426/509 | 83.69% |

The high recovered scores demonstrate the value of retaining stopped work despite
lifecycle failures. The low recovered scores are also useful measurements; they
were not zero-filled or removed. These recoveries improve measurement completeness,
not the original candidate programs. They do not by themselves establish a solver
or strategy quality gain. SQLite is still being measured under its original scoring
limits.

## Corrected duplicate discovery

The completion scheduler mistakenly admitted three additional scoring jobs:
doxygen, diffr and melody already had valid results. No solver was rerun. Their
repeated counts exactly match the established results (79/229, 557/606 and
1014/1205), so correcting the projection leaves the current mean and denominator
unchanged. The redundant jobs consumed approximately **682 seconds** in total;
their artifacts, costs and original records remain retained.

The admission decision had read an asynchronous report. That view can briefly
lag a newly published terminal result; the older recovery report also writes an
intermediate view before adding doxygen's earlier supplemental score. A terminal
job record paired with that transient view looked like a failed measurement.

Discovery now reads the original published RESULT and the earlier recovery's
published RESULT. It rechecks immediately before admission and again at worker
entry. Reporting preserves the established score and marks redundant measurements
explicitly; it never promotes a later duplicate merely because that value is
newer or higher. The scheduler was replaced while all twelve active completion
solver allocations retained their exact original starts/deadlines. No task budget
was reset and no raw result was overwritten.

Five driver controls pass, including deliberately stale projections, a prior
recovery result, worker-entry rechecking and a duplicate with an artificially
higher score that must not replace the established score. Evidence, source hashes,
before/after projections and allocation checks are retained at
`/data/ProContract/procontract-status-20261102-0200/`.

This is an H1/H3 lesson: a derived view is useful context, but it cannot substitute
for authoritative operation/outcome records when admitting more work. The existing
kernel semantics remain sufficient. The repair is in the experiment scheduler and
its result projection; the frozen solver package and strategy remain unchanged.

Live completion status is in
`/data/ProContract/programbench-completion-20261101/STATUS.json`; the combined
projection is `COMBINED_RESULTS.json`. Historical duplicate measurements remain
visible as `redundant_measurement` and are excluded from the recovery count.
