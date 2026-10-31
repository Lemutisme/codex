# Time-only cohort status and new triage observations

2026-10-28, approximately 03:54 UTC. Frozen solver `c68db7c00` remains unchanged.
This is a status/triage record, not a completed analysis of the 21 newly ended
trajectories or an implementation change. The user's consolidated-repair deferral
remains in force.

- 46/200 attempts ended; 45 valid canonical scores; four solving; 150 queued.
- Valid-subset mean 76.8637%; Vals on those same 45 tasks 70.8302% under different
  request resources. Thirty-one higher and fourteen lower. This is not the full
  leaderboard result or a matched-compute superiority claim.
- Each task still has the original shared six-hour deadline and no request ceiling.
- Fifteen ended with the unresolved-publication message. Some other stops concern
  reviewer/selector interruptions or inspection shutdown. A class label alone does
  not establish how much task time was lost; twenty ended near the six-hour limit.
- The supervisor is live. No preparation failure is recorded in this cohort.

New strong results include clog-cli 99.65%, nnn 98.11%, nomino 98.08%, shellharden
93.15%, hck 92.87%, gowsdl 91.30% and tailspin 91.21%. New weaker outcomes include
dog 37.77%, ast-grep 37.29%, sox 42.56% and wrapcheck 43.75%. These results remain
valid regardless of internal Support or unresolved execution-lifecycle defects.

## DuckDB currently has no valid score

The solver used 3235 requests and approximately six hours. Its submission remains
frozen at SHA-256 `cc69257257c123250b20553d5f0e72156b05459f15d77396ec52be382b7ec4be`.
Both evaluator processes exited zero and retained raw result files, but result
validation rejected them before computing the canonical score:

| Attempt | Raw JSON bytes | Evaluator elapsed seconds |
|---|---:|---:|
| 1 | 707,262,431 | 2140.11 |
| 2 | 707,265,609 | 2177.02 |

`evaluator/scripts/campaign_evaluate.py` has a 32 MiB JSON parsing limit and a
256 MiB artifact-hashing limit. `validate_evaluation` returns early with
`oversize_eval_json` and `hash_unavailable:artifact_size_limit`; the outer adapter
then also reports `canonical_denominator_mismatch:0`. That zero reflects unprocessed
data, not an observed zero-test submission or zero correctness score.

The actual evaluator receipts separately retain raw-file SHA-256 values. The raw
files and both attempts are preserved. Evaluator exit zero alone does not prove
every expected test or schema invariant is valid; that still requires processing
the result. No score is invented, filled with zero, or included in the 45-case mean.

Later repair should preserve exact eligible identities, exclusions, duplicates and
schema checks while handling large artifacts with suitable resource use. Prefer
validating retained frozen results before considering another evaluation. The solver
must not be resumed, and no fixed-size rejection should be reinterpreted as an
artifact-quality verdict. No parser/limit or score was changed in this status pass.

## Two new observations for the existing strategy/harness analysis

- Direnv ends at about 80 minutes with a valid 680/849 = 80.09% result. Its status
  includes path-dependent internal differences: reference SelfPath/hooks name
  `/inputs/executable`, while the candidate names `/tmp/pc-bin/executable`.
  Strategy explicitly chooses rest after judging the remaining differences to be
  invocation-path differences. This is a concrete candidate for testing equivalent
  observation conditions. The status explanation does not establish the cause of
  all 169 external failures or prove that no other useful work was available.
- Wrapcheck ends at about 30 minutes with a valid 210/480 = 43.75% result. Internal
  fixtures intended to exercise Go analysis instead record `go` missing from PATH
  on both reference and candidate, with different error text. A subsequent selector
  transport error ends continuation. This reinforces the earlier distinction
  between exercising a setup-failure path and the intended capability. The origin
  of the missing tool/path still needs qualification; no denominator changes follow.

These observations are added to the analysis backlog. They do not install a new
strategy or change the already recorded kernel/harness/strategy ownership boundaries.

Status and scoped raw records are saved in
`/data/ProContract/procontract-status-20261028/`. Live full results remain at
`/data/ProContract/programbench-full-timeonly-20261025/REPORT.md`.

## Update at approximately 21:24 UTC

67 jobs have ended: 65 completed solver attempts and two preparation failures.
There are 64 valid scores, four active solver cases and 129 queued cases. The
valid-subset mean is 74.9716%; Vals on the same 64 tasks is 66.7197% under different
request resources, with 45 higher and 19 lower results. DuckDB remains unscored.

Hex is the first perfect result, 823/823. All eligible feedback entries pass and
the raw result hash matches the bound score record. It used 2799 requests and
359.88 solver minutes. Loop is 709/710 = 99.86%. Their strong artifact results are
retained without inferring which strategy choices caused them. Detailed analysis
of these new success trajectories remains work to do.

New preparation failures, before any solver admission:

- jsonschema: the readiness comparison reports `missing=0, extra=845` test identities.
- i3-style: pytest reports `No module named '_pc_collection_probe'`; the subsequent
  scope-receipt copy fails because the probe did not complete.

Original preparation logs and diagnostics are preserved. These are evaluator
integration/collection failures to investigate, not low model scores. No preparation
retry, source change or denominator amendment was performed in this status pass.
The recurring unresolved-publication ending now appears in 23 solver attempts.

The snapshot and verified perfect-score record are saved as `cohort-status-2124.json`
and `perfect-score-audit-2124.json` under the status artifact directory above.

The subsequent [preparation root-cause audit](programbench-preparation-rootcause-20261028.md)
identifies a discovery/catalogue mismatch in jsonschema and script-side PYTHONPATH
replacement in i3-style. A minimal plugin-import control reproduces the latter.
These findings narrow the earlier triage; the frozen campaign remains unchanged.
