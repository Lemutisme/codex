# ProContract: native progress and delivery evidence, 2026-10-17

Implementation follows [the original design](procontract-progress-authority-design-20261017.md).
Qualification artifacts are retained under
`/data/ProContract/progress-evolution-validation-20261017`.
This is mechanism qualification and a bounded synthetic model experiment, not a new
ProgramBench cohort, a COLT result, or evidence of improvement over the Vals leaderboard.

## Architectural result

Responsibility, working evidence, execution authority and acceptance remain distinct.
`publish_progress` captures a coherent snapshot during a native turn and retains public
feedback without advancing the settlement kernel. Native successors can publish under the
original grant. A fresh session, polling, recovery or a repeated request cannot renew that
grant. Unknown effects remain explicit and prevent acceptance/automatic continuation.

Executable progress uses public checks; formal handoff retains independent review.
ReviewOnly progress uses bounded local review and preserves unsupported requirements.
The original deadline now interrupts and awaits the actor's shutdown, including its owned
background processes. Output limits act before transport encoding. These changes leave
ordinary execution in Codex rather than introducing a second model loop.

Delivery evidence now includes the actual final response, subject/turn binding and original
hash/length. A successor's 1200-byte continuation summary cannot stand in for its final
response. A 64 KiB head/tail retention bound explicitly marks truncation, and truncated text
cannot supply positive review coverage. The reviewer can read the actual check invocation,
bounded successful output, exact baseline entry equality and retained publication history.
An executor's final claims remain assertions to assess, not independent proof.

## Why the earlier real runs failed

Both earlier runs used GPT-5.6-Luna / max, the same interval-merging prompt, a 300-second
original grant, and fixed external tests. Both immutable delivered artifacts passed 10/10.

| Attempt | Artifact | Internal acceptance | Diagnosed limitation |
| --- | --- | --- | --- |
| `live-luna-smoke` | 10/10 | `reviewer_unable` | Progress unnecessarily consumed full review; serial 512-byte evidence reads exhausted review time |
| `live-luna-smoke-v2` | 10/10 | `reviewer_unable` | Reviewer lacked actual test command/success output and the user-facing final explanation |
| `live-luna-smoke-v3` | 10/10 | `reviewer_unable` | Corrected evidence was available; review timed out under the original grant |

The first failure led to checks-only executable progress, preparation notifications and
4096-byte evidence pages. The second led to the delivery artifact and complete check context.
No failure is erased or relabeled as successful acceptance. The third run completed its
root turn, published twice and delivered the immutable artifact. It retained one Issue and
one Propose, with no Support, Discharge or Release. Wall time was 290.38 seconds, including
the original grant's cleanup reserve. The configured and recorded model/effort remained
GPT-5.6-Luna / max. Across all three development runs, artifact correctness on the ten fixed
tests is 3/3; successful internal acceptance is **0/3**. No further paid retry was launched.

The third root turn took about 124 seconds. The reviewer then had about 165 seconds under
the same original deadline. It made six index calls and received the complete catalog,
including actual final response, successful test receipts and baseline equality. After the
last tool result, about 136 seconds passed without another completed model output before
cancellation. The retained logs do not distinguish model inference from provider waiting.
They do establish that the reviewer never read the document bodies in that attempt. The
native scripted tests verify those bodies are accessible and correctly bound; this does
not establish reliable real-model consumption or acceptance latency.

Thus the missing-evidence defects are fixed, while real-model acceptance within this short
budget remains unqualified. A timeout remains unknown rather than fabricated Support.
This tiny synthetic task does not establish long-horizon performance.

## Validation results

| Check | Result | Retained evidence |
| --- | --- | --- |
| Kernel / store / extension unit and Docker-enabled tests | 36 + 39 + 175 passed | `rust-v8-fixed.log` |
| Exec-server library, UID 1000 | 382 passed | `exec-server-unprivileged.log` |
| Python adapter / config / ownership / collection regressions | 59 passed | `python-qualified.log` |
| Final-build native scenarios | 14/14 passed | `native-qualified-v9-results.json` |
| Targeted production Clippy, warnings denied | Passed | `clippy-qualified.log` |
| Formatting / final native build | Passed | `fmt-qualified.log`, `build-9.log` |
| Accepted WebSocket integration | 7 passed | `exec-server-integration-v8.log` |
| Expanded exec-process integration | 46 passed, 4 failed, 10 ignored | same integration log |

Final native scenarios cover actual root/successor response transport, same-turn repair,
output exhaustion and continued protocol operation, theory partial evidence, successor
publication, original-deadline heartbeat cessation, frozen binary computation, partial
review, reactive PTY dialogue, interrupted checks/replay, restart, scoped review and long
original-request succession. These use real app-server/code-mode/Docker paths and scripted
providers. Source/binary hashes are recorded in `qualification-source-v9.json`; the local
release provenance verifies the corresponding committed source. The final production
change after the full Rust run only collapses a nested condition for Clippy; the final
native matrix and real-model run use the rebuilt binary.

The broader suite is **not fully green**. Four shell-snapshot sandbox scenarios failed as
root (transport recovery, capture counts and a read-only profile path). Repeating these as
UID 1000 reports capability skips because user namespaces are unavailable; those skips
are not passes. Attribution of these four failures to this change is unproven. A broader
all-target Clippy invocation also reports three findings in files byte-identical to the
baseline (`inspection_grant_tests.rs` and `message_processor.rs`); targeted production
Clippy passes. These limitations prevent any claim of universal zero mechanical errors.

Development failures are retained separately, including the exact-byte CAS fault-fixture
correction, the deadline status race, the response retention marker boundary, and the
native test's unavailable `TextEncoder` assumption. Reports are never overwritten to
convert an earlier failure into success.

## Evaluator qualification

Final evidence: `evaluator-preflight/collection-final/qualification/readiness.json`.
The official bootstrap, frozen grader dependencies and collection qualified **1114 eligible
tests across 12 mdbook branches**. Collected identities exactly match frozen metadata after
official exclusions. No model solves or old candidates were evaluated.

Earlier development attempts are preserved. Full scoring of a failing null sentinel was
unsuitable for readiness and exhausted its finite allowance. Collection with the null
sentinel also failed: module imports can probe the executable. The final probe exercises
the ordinary null build, then uses the frozen image's reference only for collection. The
reference is extracted from a never-started container into host-only scratch; the official
compile environment deliberately removes the original image workspace. Collected test
bodies do not run, while imports may execute reference probes. Ordinary candidate scoring
does not use this substitution.

Optional grader requirements are operator-pinned exact versions from a frozen offline
wheelhouse. Installation occurs after candidate hashing, followed by hash revalidation.
There is no bs4/mdbook-specific behavior in the kernel or controller. Readiness proves
bootstrap and exact collection; formal submissions still require the full validator.

## Boundaries

- Capture requires one exclusively provisioned workspace executor. External host writers
  and simultaneous threads sharing that workspace are outside its guarantee.
- Raw output, process duration and Docker logs are bounded. Aggregate writable workspace
  quotas are not implemented.
- Retained evidence improves observability; it cannot mechanically certify a mathematical
  proof, completeness of exploration, or correctness outside the applicable evidence policy.
- Support does not authorize automatic Discharge/Release.
- Earlier experimental artifacts remain tied to their original binaries. No leaderboard
  improvement or universal zero-error claim follows from these checks.
