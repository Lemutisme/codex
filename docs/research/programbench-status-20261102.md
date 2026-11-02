# ProgramBench completion status, 2026-11-02

## 11:48 UTC update: solving finished, Pandoc scored, age recovered

All solver attempts have ended. Pandoc scored **1205/5214 = 23.11%**, with its
full feedback vector and raw evaluator hash independently checked. Other completed
first admissions include i3-style 533/539 (98.89%), tuc 1162/1196 (97.16%), gping
294/338 (86.98%), gdu 922/1161 (79.41%), fselect 2211/3115 (70.98%), go-critic
303/493 (61.46%), Miller 5611/14637 (38.33%) and pueue 115/638 (18.03%). These are
artifact results under the recorded conditions; they do not all indicate the same
strategy or infrastructure mechanism.

Age's solver had finished, but its earlier container-removal wait did not confirm
absence, so no submission was frozen. At this inspection the relevant containers
were absent and the retained server shutdown was confirmed. A separately recorded
postsolve operation packaged that stopped workspace and obtained **449/676 =
66.42%**. Its original failure remains unchanged, as do the six-hour start/deadline
and 1949 recorded requests. No model inference was repeated.

The current strict-completeness projection is **197/200 scores, mean 76.2252%**;
the same-task Vals reference mean is 68.3823%, with different request resources.
All jobs are now stopped. Three entries retain `needs_repair`: jsonschema, SQLite
and the separate stgit retry. SQLite exhausted the supplied evaluation allocation.

### Scoring convention needs a separate, explicit account

Jsonschema and the independent stgit retry have complete published result files,
correct fixed denominators, matching artifact receipts, no top-level/branch errors,
and no strict rejection reason except `not_run`. Jsonschema's recorded pytest
invocation stops after a candidate assertion failure under its supplied fail-fast
policy. Stgit's dynamic subcommand enumeration omits expected cases.

The unmodified, pinned `programbench.submission.score_instance` computes:

| Artifact | Passed / eligible | Scorer value | Explicit `not_run` records |
| --- | ---: | ---: | ---: |
| jsonschema first attempt | 1766/2932 | 60.23% | 1089 |
| stgit independent retry | 938/1488 | 63.04% | 50 |

Both evaluation attempts give the same respective values. The scoring function
maps statuses other than `passed` to false; the additional campaign validator
separately rejects any `not_run`. Thus lack of a score in the strict projection
is not the same as inability to calculate the benchmark-defined scalar. Do not
describe these as missing interpreter/environment failures, erase the scalar, or
claim the unexecuted tests were actually observed failures. Score convention,
execution completeness and infrastructure state need distinct fields.

This pass retains the scorer reconciliation separately rather than silently
rewriting pre-existing strict flags/aggregates. The stgit value is still a separate
second solver attempt, not a replacement for its first attempt. SQLite additionally
has branch-execution failures, so the `not_run`-only reconciliation does not certify
its measurement. These distinctions should guide the final benchmark report and
prevent an extra local completeness rule from manufacturing further solver work.

Evidence is in `/data/ProContract/procontract-status-20261102-1141/`, including
`pandoc-score-audit.json`, `age-recovery-audit.json` and
`official-scoring-reconciliation.json`. Original raw results were not overwritten.

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
