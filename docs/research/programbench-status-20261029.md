# Time-only cohort status, 2026-10-29

Snapshot at approximately 22:24 UTC. Frozen solver and running experiment remain
unchanged; this pass records status and limited triage, not new implementation or
a full analysis of all newly completed trajectories.

- 91/200 jobs ended: 88 solver attempts and three pre-admission preparation failures.
- 87 valid scores; DuckDB remains unscored because large-result validation failed.
- Four solving; 105 queued. Supervisor live; admissions not paused.
- Valid-subset mean 73.7295%; Vals on those same 87 tasks 65.7778% under different
  request resources. Sixty-three higher and twenty-four lower results.
- Hex remains the sole perfect result, 823/823. Loop is 709/710, csview 334/335,
  and clog-cli 573/575. New htmlq is 1436/1455 = 98.69%.
- Thirty-two solver attempts ended with the unresolved-publication message.
  This count alone does not quantify lost task time or final-score effects.

Other new strong results include hush 94.34%, entr 94.03%, pixterm 93.02%,
the_silver_searcher 91.24% and rustowl 90.83%. Lower new outcomes include chafa
23.56%, ditaa 41.05%, samtools 46.18% and solar 48.18%. The changing completed
subset is not a new-version comparison; these outcomes remain in the aggregate.

## New preparation failure: pueue

The readiness runner attempts a Cargo build in `/workspace/pueue`. Its log reports
failure obtaining `async-trait` from index.crates.io because the network is isolated.
The scope receipt is consequently absent; the later receipt-copy error is secondary.
The solver never starts. Existing preparation failures are jsonschema and i3-style.

This belongs with H2's offline evaluator capability qualification. The effective
dependency availability/cache lookup must be checked; this log does not distinguish
missing cached content from an incorrect cache search path. Do not enable solver
network access, change test assertions or count this as a model-quality failure.
No setup repair or retry was performed in this pass.

## Additional scoped observations

- Gomplate stops after 27.75 minutes with 1552/2926 = 53.04%. The draft is rejected
  because case `datasource-env` has an invalid environment variable; no contract is
  issued. This is another pre-Issue continuation boundary to inspect alongside zstd.
  The exact rejected variable and the reason for its validation remain unexamined.
- Astaxie/bat rests by strategy choice after 146.45 minutes and scores 675/1091 =
  61.87%. Its status says internal checks pass and remaining gaps concern unavailable
  evidence. This merits later comparison of internal coverage with external residuals;
  the status alone does not prove that more work would have improved its score.

These refine existing lifecycle/observation/strategy directions rather than adding
case-specific workflow rules. New success and failure trajectories have not all
been deeply analyzed. The user-directed consolidated repair is still deferred.

Snapshot and scoped raw evidence:
`/data/ProContract/procontract-status-20261029/cohort-status.json` and `triage.json`.
See [the evolution register](procontract-evolution-register.md) for consolidated work.
