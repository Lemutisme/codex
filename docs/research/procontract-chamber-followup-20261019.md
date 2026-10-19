# Chamber after the admission repair

The first Chamber solve after adapter commit `2c6a67e03` is complete. Agent runtime
`bdf04e61d` and the strategy bundle were unchanged. GPT-5.6-Luna/max used 358 shared
requests and 39.58 minutes within the original six-hour/1000-request offline grant.
The first official evaluation scored **1346/1748 (77.00%)**, versus the retained Vals
Luna/max row of 87.87%. Internal Support was false; the native terminal class was
`reviewer_unable`, with zero repairs and no successors.

The scope repair resolved the earlier pre-inference blocker: an explicitly ignored
pytest module must be excluded at its actual collector scope before import/expansion.
Applying an exact leaf-only filter after collection lost that meaning. Both readiness
and ordinary grading now use the same generic module-resolution mechanism. The kernel,
solver runtime, official assertions and eligible denominator did not change.

## Artifact and review findings

There are real candidate defects: 136 nonpasses in the four named backend mock modules,
39 completion-named tests, and further failures including service/key/tag validation and
import/environment behavior. Secrets Manager, S3 and S3-KMS resolve to an unavailable
backend; completion emits placeholders. The candidate does implement and probe SSM
against a local endpoint, so it is not simply an untested local-store substitute.

Useful SSM differential experiments were performed, but the executor deleted its mock
server source and later tried to run it again. That comparison observed connection
refusal rather than successful backend execution. No runnable regression suite or mock
source remained in the submission. Public checks (40 plus build) all passed; broad
passing observations still left distinct behavior families unimplemented.

The formal reviewer found completion/backend defects, but twice placed the same broad
obligation in both `coverage` and `findings`. The parser treats coverage as complete
obligation support, rejects the response, and the controller rests in `reviewer_unable`.
Actionable raw findings were retained but not admitted to repair. The protocol blocked
this repair path with 642 requests remaining; the score effect of repairing that path
has not been measured. There is no matched native-Codex ablation.

Accounting reconciles 242 executor, six preparation, 41 diagnostic-review and 68 formal
review requests, plus one incomplete stream. Diagnostic review returned no completed
judgment. The formal reviewer lacked facts already known elsewhere: the compile script
was 0755, the executor committed `7eea2e4`, and the host enforced resource/isolation bounds.

## Qualification limit

The structurally valid official result includes **19 identified fixture failures**:
16 analytics tests tried to download Go 1.23.0 while offline; three local HTTP fixtures
could not bind fixed ports. All 19 already appeared with identical messages in the
negative control. Qualification confirmed collection and score aggregation but did not
separate fixture execution failure from candidate failure. The earlier assertion of
complete grader readiness was too broad.

Keep 1346/1748 as the original raw result. Do not remove tests, adjust the denominator,
claim a corrected score, or treat this as an environment-clean leaderboard comparison.
These failures do not erase the separately observed implementation defects.

## General ownership

No new progress/responsibility kernel invariant is justified here. Harness work concerns
scoped observation transport, a review interface separating evidence from conclusions,
preservation of usable partial results and precise errors, host-fact receipts, and
fixture execution qualification. A failed assessment should remain inspectable to its
caller without either fabricating Support or embedding a universal stop/retry policy.

Strategy work concerns discriminating experiments, successful external interactions,
retained executable regression memory and allocation of review/repair effort. A custom
local interface can aid exploration but cannot establish compatibility with the original
interface. Workflow decisions belong to prompt/skill/context; enforcement of the actual
grant and execution capabilities belongs to harness.

This document records lessons, not implementation of those follow-ups. Full evidence,
failure IDs, review blobs, request attribution, reproducible read-only analysis and
integrity checks are under `/data/ProContract/programbench-chamber-20261019/` in
`post-run-analysis.{md,json}` and `analyze_completed.py`. All 546 current and 602
predecessor frozen files and original result/submission/evaluation hashes are unchanged.
