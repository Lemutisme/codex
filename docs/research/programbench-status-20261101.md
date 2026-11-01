# ProgramBench status and stopped-trajectory triage, 2026-11-01

## 20:48 UTC update: queue admitted, third perfect result

There are now **166 valid scores**, mean **76.9996%**; the same-task Vals reference
mean is 68.9095%, under its different request resources. The uninterrupted valid
subset contains 163 scores, mean 76.6678%. All 200 original case slots have been
attempted at preparation: no unstarted queue remains. Fourteen solver processes
and one grader remain live; 19 terminal cases lack a valid score (11 preparation
failures, three finalization failures and five invalid/unavailable evaluations).
Thus 185 terminal job records still must not be reported as 185 scored solves.

**Cmatrix is the third perfect artifact: 506/506.** All 506 eligible feedback
entries were checked as passing, and the retained raw evaluator hash matches its
bound result. Hex (823/823) and zip-password-finder (680/680) remain perfect.
Cmatrix used 2668 requests and its six-hour allocation. Its internal Support stayed
false; that does not negate the independently verified artifact result. This pass
does not claim to have isolated the strategy's causal contribution to its score.

| Recent recorded quality | Passed / eligible | Percent |
| --- | ---: | ---: |
| zoxide | 519/531 | 97.74% |
| lua | 1178/1338 | 88.04% |
| oranda | 340/767 | 44.33% |
| jplot | 479/583 | 82.16% |
| ffmpeg | 263/3041 | 8.65% |

Jplot stopped after 24.25 minutes with one incomplete acceptance pipeline and an
action timeout. Its observed external quality is still 82.16%. FFmpeg stopped
after 116.41 minutes with unresolved publication effects and has substantial
remaining behavioral failures. Neither observation establishes the score gain
that extra execution would have produced. They add to the existing H1 lifecycle
record while keeping behavior coverage separate from mechanical stopping.

Git-trim is a live-process anomaly: its last model request was about 114 minutes
old at inspection. The lane reports resting/not_verified with unresolved prior
publication, while the driver has no completed root turn. The frozen `is_done`
requires a completed inactive root turn, so this state cannot terminate through
its ordinary rest condition. The latest ledger records a successor return and
captured task delivery. The exact missing-completion mechanism remains unresolved;
process existence is not evidence of productive work. Its original six-hour
deadline remains in force, with about 81 minutes left; no restart or renewal was
performed. PHP has ended solving and is still within its separate four-hour
grading allocation.

Host memory remains plentiful: approximately 156 GiB available, load about six on
60 CPUs, and disk free about 63 GiB. Three new OOM kills at 20:40–20:41 all hit
512-MiB cgroup limits. The retained kernel count is now 57, all `CONSTRAINT_MEMCG`,
with no global OOM kill found. This continues the scoped-limit conclusion of the
[memory audit](programbench-memory-audit-20261101.md).

Artifacts: `/data/ProContract/procontract-status-20261101-2048/` contains the live
snapshot, the perfect-score audit, new kernel events, stopped cmatrix/jplot
ledger extracts and a consistent read-only SQLite snapshot of git-trim's ledger.
The fixed cohort received no new strategy, runtime code or score feedback.

## Earlier 04:15 UTC inspection

At 04:15 UTC the restored scheduler is live, all four job processes are live and
their model-request timestamps continue advancing. There are **127 valid scores**,
four solvers, 59 queued cases and ten cases without a valid score. The 137 terminal
job records are not 137 successfully scored solves. No renewed shared-dependency
failure cascade was observed. Approximately 192 GiB remains available.

The valid-score mean is **76.5309%**, versus 68.1606% for the same tasks in the
retained Vals Luna/max reference. The 124 uninterrupted valid scores average
76.0834%. The cohort remains incomplete; Vals has different request resources and
the previously recorded evaluation-condition limits still apply. Missing values
are not filled with zero. Hex and zip-password-finder remain the two perfect cases.

Ripgrep and dupl have about 35 and 37 minutes left in their original allocations;
tig and ripsecrets have about 221 and 342. Their actual allocator profiles remain
GPT-5.6-Luna/max, 21600 seconds and no request ceiling. No solver was restarted or
given a new allocation during this inspection.

| Newly terminal case | Local result | Vals reference | Observed stop |
| --- | ---: | ---: | --- |
| serpl | 335/417 = 80.34% | 64.75% | Successor context rejected after 97.37 minutes, 620 requests |
| dropbear | 482/667 = 72.26% | 75.11% | Pending publication after 197.26 minutes, 1627 requests |
| stgit | Unavailable: incomplete eligible outcome set | 58.79% | Pending publication after 163.25 minutes, 1584 requests; two invalid grading attempts |

## Serpl: a useful decision that the transport could not execute

Ledger event 434 records a concrete PTY counterexample: after a particular
search/input/navigation sequence, the candidate replaces file contents while the
reference leaves them unchanged. Event 435 selects a successor with the exact
reproducer and intended repair. Event 436 reserves it under the original deadline;
event 437 rejects admission before any successor turn starts because its context
packet exceeds the byte bound. This is not evidence that strategy chose rest or
had no useful next action.

`controller/successor.rs::packet` rejects serialized context above 64,000 bytes.
The full packet includes current owner context in addition to the work packet.
The specific dominant contributor was not reconstructed in this pass. The same
limit remains in the newly merged development branch; RSI's synthetic operational
qualification does not establish that this limitation was fixed.

This extends H3: keep essential instruction/authorization context available while
exposing retained evidence through suitable views/retrieval. A recoverable context
assembly problem should become an actionable result. Blindly truncating owner
instructions or raising one constant is not a general resolution. Strategy still
chooses what evidence and repair context is useful. Serpl's 80.34% artifact result
remains a positive outcome despite this early mechanical stop.

## Dropbear/stgit: lifecycle and behavior require distinct explanations

Both terminal statuses report unresolved prior publication effects. Stgit's ledger
ends with a reserved publication and captured progress snapshot, then a successor
return and task delivery; there is no completed publication assessment afterward.
These are further frozen-version H1 observations. The development branch has
qualified action-ownership/finalization controls, but these new exact trajectories
have not been replayed under it, so no recovered score gain is claimed.

Dropbear has 185 failed eligible assertions. Twenty retained failure messages
explicitly include `Connection corrupted` during SSH interaction. Many test names
concern authentication, PTY and forwarding; those names do not establish separate
failures in each named subsystem when transport may fail earlier. The precise
packet/crypto defect remains unlocated. Preserve the 482 passes and investigate the
first consequential protocol divergence rather than deriving a diagnosis from
group labels or treating the lifecycle interruption as the cause of every failure.

## Stgit: candidate behavior also broke test discovery

Both original evaluator attempts fail while importing
`eval/tests/test_subcommand_dispatch.py`. Its module-level setup invokes the actual
candidate with `completion list commands --style name-only`. The candidate rejects
`--style name-only`, so the module's assertion fails before parameterized test
collection. The canonical result lists 59 `not_run` cases, one unexpected module
error and a denominator mismatch. This is **not another missing interpreter or an
unexplained evaluator outage**: the first observed failure is unsupported candidate
CLI behavior, with a further measurement consequence because discovery depends on
that behavior.

The invalid record contains 834 recorded passes and reports a total of 1489, while
the pinned official eligible total is 1488; its `pass_rate` is null. Do not publish
834/1489 as a valid whole-instance score,
remove missing tests or invent their outcomes. Retain both attempts and the frozen
submission. General H2 work must distinguish candidate-caused discovery failure
from environmental unavailability while preserving the official eligible set and
grading semantics. Neither changing the kernel nor silently resuming the solver
would resolve that measurement contract.

Evidence: `/data/ProContract/procontract-status-20261101/` contains the live-status
snapshot, `new-episodes.json` with original result/submission/feedback hashes,
copied stopped ledgers and selected events. This inspection added no new model
requests, score retries, runtime edits or feedback to active solvers. The RSI
implementation remains opt-in in development; this cohort still runs its original
frozen package.
