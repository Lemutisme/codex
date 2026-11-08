# Invocation observations and independent artifact measurement

Independent branch `experiment/procontract-invocation-outcomes-20261108`, based on e45aa9927. No running/frozen cohort, pilot2 input, main checkout or deployment is changed by this implementation. Its validation uses local HTTP, SQLite and data controls without model calls or containers.

## Change

`procontract_benchmark_gateway.py` appends `request_observations` to its SQLite database. Legacy `requests` schema/rows and status/terminal/usage/failure behavior remain readable. Old requests are not backfilled. New dispatch records retain selected thread/turn/session metadata as observed transport identity, not authority. Error observations carry actual upstream connect/send/read, downstream write or response-validation phase, exception type, timestamp and independently observed original-deadline/gateway-owner-shutdown flags. Original exception facts survive even when the legacy final failure field records task_deadline. Secondary downstream failure while sending an upstream error is retained separately.

A gateway owner shutdown flag is not a specific reviewer cancellation receipt. An ordinary downstream disconnect is not automatically a deliberate cancellation or a provider error. The adapter must join native role/turn/operation receipts when interpreting it.

`scripts/procontract_invocation_outcomes.py` is the isolated v3 outcome module:

1. `classify_execution`: request/role/turn facts and explicit source-bound cancellation correlations. It never equates response.completed with main-turn completion, never ignores all BrokenPipe, and never hides provider503/response.failed under an arbitrary completed root turn. Legacy origin stays unknown.
2. `artifact_measurement_available` / `measure_artifact_if_safe`: an already admitted grader callback may measure a complete frozen artifact after effects closed and environment qualification, independent of solver classification. Unknown writers/incomplete capture do not get a measurement. This supplies no grant or workflow policy.
3. `measurement_result`: retains observed/passed/expected and returns value=None until every expected test is observed and measurement effects closed. The old1/9 or1/10 skipped-private result cannot become a quality percentage.
4. `protocol_adjudication`: separate trusted host/owner decision, bound to execution digest, admitted authority ref and source refs. This lets a source-bound adjudication restore comparability for old ledgers without inventing their failure origin. `needs_review` is not a permanent veto. The existing host protocol may admit ordinary outcomes through `default_eligible`; no new per-case human click is required. The module does not create kernel adoption authority; the existing selection/adoption boundary still applies.

## Integration boundary

The module is implemented and tested independently; it has NOT been spliced into frozen pilot2. A future adapter replaces the old gate `effects and inference_validity.valid and artifact` with the safe-artifact callback, records execution classification alongside it, and passes separately adjudicated protocol eligibility into measurement admissibility. The actual root-owned same-artifact recovery remains an independent measurement record.

Do not silently convert every infrastructure-affected case to a comparable model result. Measure safely where possible, then preserve the experiment protocol decision (eligible/ineligible/needs_review), original failures, usage gaps and explicit grants. Retrying or starting new work remains the harness strategy library's choice. Tasks without deadlines keep deadline=None.

## Two source-bound regressions

`testdata/invocation-outcomes/pilot2_cases.json` contains minimal request/cancellation records from the exact original operation directories for cases90c23ebeaabbb244 and9c980b85ac543ec6. It includes source file/record hashes, no private grading inputs. A first extraction using task-name glob selected another later operation and was rejected by missing expected session; extraction was corrected to exact operation IDs. No originals changed.

Both cases retain reviewer cancellation/closed-publication→root response continuation→original deadline, main turn failed and legacy phase absent. Tests confirm safe measurement eligibility, no fabricated score for skipped tests, and separate trusted-review eligibility without changing legacy origin. Fixture owner decisions are tests, not modifications of live protocol adjudications or scoring.

## Validation

- Original gateway suite:16 tests including local HTTP, allocator/no-deadline and response handling.
- New outcome tests:14 controls, covering raw/provider failures, wrong-role/no-closure evidence, original deadlines, no deadline, unknown/incomplete capture, partial measurement, source-bound owner review and explicit grader callback.
- New transport tests:4 controls with deterministic mock connect/send/read/write failures and additive legacy schema behavior; underlying HTTP smoke remains in original suite.
- Real retained-case regression:1 test with both exact original cases.

These are HTTP/SQLite/pure controls, not paid-model or native end-to-end qualification. The facts interface is general; neither the gateway nor the outcome module chooses retry counts, wait thresholds, research sequence or a universal task deadline.

The experiment owner independently reran all35 controls. Separately admitted,
artifact-only recoveries measured the two unchanged pilot2 artifacts at9/9 and
10/10, including all17 previously skipped private checks, with zero new model
calls. Original outcomes, errors and adoption records remain unchanged. The
corrected two-instance fresh comparison is18/18 versus18/18, not a quality gain.
The append-only projection and source hashes are retained at
`/data/ProContract/rebuttal-20261107/experiment-runs/rsi-e2e-pilot2/reporting-corrections/20261108T010155006072Z/MEASURED_SUMMARY.json`.
