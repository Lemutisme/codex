# Test-time learning feedback: retained facts before update policy

The user delegated E2E implementation to one Astra xhigh agent and retained the
parent's ProgramBench trajectory-analysis role. Research/design records and the
delegation brief were committed at `454b2ba00`; implementation is isolated in
`worktrees/procontract-rsi-e2e-20261031` on `feat/procontract-rsi-e2e-20261031`.
The agent task is `/root/rsi_e2e_implementation`. This parent record is analysis
input, not an installed learner or a change to the frozen 200-case campaign.

At approximately 19:01 UTC on 2026-10-31, the cohort has 129 terminal jobs, 120
valid local scores, four active solvers and 67 queued tasks. Its local mean is
76.3091%; the frozen Vals matched-task reference is 67.6791%, with different
request resources and the previously recorded evaluation-condition qualification.
The apparent grading row for dutree remains a terminal driver failure.

## A reusable research-only feedback view

`/data/ProContract/procontract-test-time-learning-20261031/export_feedback.py`
produces `feedback-view.json` and `feedback-summary.json` from terminal job/result
records. The view preserves 129 terminal records: 120 recorded quality outcomes,
nine unavailable quality values, six pre-admission failures and the dutree missing
terminal-result case. It does not touch live solvers or original scores.

The fields keep these facts separate:

- Recorded canonical quality and its eligible denominator, when available.
- Actual job/solver/measurement state, interruption and cleanup observations.
- Original resource grant, elapsed work and observed request consumption.
- Source/result/version identities and visibility restricted to post-run research.
- Known measurement conditions, including the grader-default network limitation.

No unavailable measurement becomes zero. No fixed weighting combines quality,
cost, execution failure and internal Support into a generic reward. Interpreting
these facts for the user's intended improvement is research strategy work.

The intended test-time learning/RSI loop can update scoped knowledge, prompts,
skills and harness versions through task-time feedback. Model weights need not
change; do not claim weight-space RL unless implemented. The current fixed-version
campaign supplies observations. A separate, explicitly versioned adaptive stream
is needed to study online policy changes without corrupting this campaign's scope.

## New contrast: ngrrram and argc

The stopped-run archives, exact decisions/assessments, eligible test groups and
original result bindings are retained in `new-episodes.json` in the artifact root.

| Case | Recorded external result | Internal evidence | What follows |
|---|---:|---|---|
| ngrrram | 300/303 = 99.01% | Final verification records 6/24 qualified sealed comparisons passing, but the check pipeline is incomplete and its action timed out with confirmed shutdown | Strong delivered quality coexists with a method/execution failure; the partial internal tally is not whole-task reward |
| argc | 576/995 = 57.89% | Recorded sealed comparisons improve from 93/114 to 107/114; the final pipeline is complete | Improvement on that fixed internal sample is real, but does not establish broad external coverage or equal score gain |

Ngrrram records two interruption snapshots followed by successor choices, and later
reaches a useful artifact. Its final check consumes approximately 180 seconds before
timeout. The stopped run ends around 203.79 minutes, leaving part of the original
six-hour allocation unused. This is another instance for H1's operation-outcome and
continuation analysis; no score gain from recovering that time is asserted.

Argc's final external residuals include completion generation, generated builds and
evaluation/environment semantics. Its continuing internal residual families include
compgen.zsh, environment binding, generation and runner paths. Local parser/error
repairs may be useful while larger capability families remain unresolved. The
counts do not alone establish whether later work was wasted or which implementation
change would improve the external outcome.

## Implications for automated credit assignment

An observation should be credited to the action, subject and conditions that
produced it, rather than to whichever narrative or version happened to be most
recent. Assess what was available to the executor before its choice; post-run
hidden feedback can inform research without becoming information the prior solver
is retrospectively assumed to have known.

Use these distinctions when interpreting feedback:

| Signal | Useful interpretation | Unsupported shortcut |
|---|---|---|
| High external score, internal timeout | Preserve the artifact success and investigate execution/measurement separately | Negative task-quality reward merely because Support is absent |
| Internal comparisons improve | Credit those scoped observations and inspect remaining gaps | Assume an equal improvement on all user-facing behavior |
| Measurement unavailable | Retain the failure, conditions and costs; investigate the missing capability | Treat it as zero-quality model output or refund the attempt |
| Different observed behavior after a change | Trace subject, invocation and dependencies | Attribute every change to the newest prompt or code patch |
| Analysis finds no useful change | Retain knowledge or incumbent under the task's objective | Require a patch to manufacture apparent progress |

This view is supplied to the delegated implementer as evidence and an input example.
It does not prescribe a research stage sequence, retry count, test threshold or
kernel reward state. Existing H1–H3 and S1–S3 directions remain the organizing
mechanisms. The delegated agent is qualifying operational E2E first; a synthetic
control's successful adoption will remain distinct from useful adaptation on fresh
real tasks.

See [the delegation brief](procontract-rsi-delegation-20261031.md),
[E2E architecture](procontract-rsi-e2e-architecture-20261031.md), and
[evolution register](procontract-evolution-register.md).
