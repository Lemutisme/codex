# Luna/Sol and Vals valid-run comparison

Analysis artifacts: `/data/ProContract/programbench-luna-sol-vals-analysis-20261106/`.
Primary report: `REPORT.md`; primary data: `valid-view.json`.

The user requested that API/settings failures be repaired and repeated, with
actual valid-instance counts reported instead of presenting every terminal job
as a completed evaluation. Existing raw records and first-attempt aggregates are
unchanged. The effective view selects declared replacement attempts, including
lower results; it does not maximize old/new scores.

| Matched valid tasks | ProContract mean | Vals mean | ≥95% tasks, ours/Vals | Full, ours/Vals |
|---|---:|---:|---:|---:|
| Luna,197 |76.2296%|68.0822%|35/18|3/0|
| Sol,175 |89.7697%|85.8731%|94/79|11/5|

The Sol view contains163 cases outside the reviewed37-case terminal API incident,
plus12 completed independent retries. Eight retained-artifact score recoveries
are complete, and Dog uses its separately verified same-artifact measurement.
Twenty-five incident cases remain in execution/queue. The12 scored retry terminal
records have no runtime failure or gateway rejection.

Luna retains the official first Jsonschema scalar as historical evidence and uses
the later user-authorized Jsonschema/stgit attempt results in the effective view.
SQLite lacks a valid measurement; Tparse's terminal503 and Dog's confirmed grading
network failure are excluded. These observations remain in their original files.
Luna's newer Jsonschema59.07% is used rather than choosing the older60.23%.

On173 common valid cases, the Sol combination averages89.7032% against76.5448%
for the Luna combination, with163 wins,2 ties and8 losses.

Vals' public page and datasets were fetched afresh, updated2026-11-05. Three public
Sol trajectories—Chroma, fastText and Revive—were retrieved and verified against
their declared uncompressed hashes. Their actual actions/returns were inspected;
no public trajectory was inserted into a solver context. This adds a concrete
comparison to the earlier local Astra trajectory study.

## Verified go-critic regression

The new14.6045% is a valid implementation failure, not a terminal API failure.
A retained development executable did not match the graded executable, so the
diagnostic rebuilt the frozen archive in the recorded environment first. The
rebuild exactly matched graded SHA256
`eb4bc1dd1f76284da9a372bba45af2cdc9ebc9a33f723392af5bd89b11dd3d11`.

That binary checks a Go1.21 module successfully, but rejects a Go1.24 module.
The environment's ordinary `go list` automatically selects cached Go1.24 and
succeeds. The candidate's `loader.go:65` overrides `GOTOOLCHAIN=local`, forcing
Go1.21 and producing the explicit module-version error. The diagnostic made no
model call and did not edit the submitted program. Its exact subject, environment
and results are retained in `go-critic-diagnostic/result.json`.

The transferable lesson is to validate runtime dependency-selection assumptions
and shared input boundaries; do not classify a candidate's own configuration bug
as external infrastructure failure. This reinforces the existing strategy scope
and actual-subject binding findings without adding a kernel rule.
