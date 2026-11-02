# ProgramBench completion status, 2026-11-02

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
