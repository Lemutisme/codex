# Finite RSI acceptance: coverage is not merit

This revision is for new scopes and plans only. Terminal studies and the withdrawn
four-run random supplement are not reopened. It does not authorize paid inference.

## Two explicitly frozen selection modes

- `deployment`: sample the recorded cost-aware bandit distribution, including hold.
- `coverage`: episode 0 probes seed/research; episode 1 probes the immediately
  preceding **admitted and witnessed** successor/research. From episode 2, sample
  normally. If no child was admitted, record `coverage_unavailable` and use normal
  selection; do not extend the prefix or replace the failed task.

The operator declares the mode before inference. A forced coverage probe has
actual propensity 1 and no random draw; the counterfactual deployment distribution
is recorded separately. Its observed return can update the selector, but it is
not an on-policy sample from the deployment-only experiment. Coverage scores do
not estimate natural-deployment benefit. The growing-pool heuristic has no claimed
regret bound. The stable incumbent never changes on a probe or acknowledgement.

## Failure domains

Only a trusted, known-clean-exit, no-contract episode with **no research claim**
may be closed as a contained failure. Runtime and trace cleanup must complete
before the pilot supplies the bound receipt. The allocation stays spent, quality
stays unknown, selection weights do not receive a fake zero, and the trial's
bounded reason is available to later research. An unresolved process, violated
budget/identity, corrupt state, or unclassified exception still stops the campaign.
Ambiguous steering consumes its attempt without admitting a child; it is not a
reason to retry. A contained failure is not a new retry allowance.

A failure closure and a reward are mutually exclusive terminal records. An
independent next task may start only after a terminal record; the same episode
cannot be resampled, rescored or reclassified. Failed cases stay in the planned
matrix and any aggregate report, not silently dropped from performance means.

## Completion criteria, fixed before running

1. Mechanism: two generation-linked research calls, actual P consumption, actual
   changed-H decision evidence, independent post-submission feedback changing the
   selector, and successor M actually used to generate another successor.
2. Safety/lifecycle: frozen contract and budget, known cleanup, no promotion on
   ACK, no candidate installation after uncertain dispatch, no hidden retries.
3. Evaluation: every planned slot has a scored result or explicit failure/unknown;
   emit PASS / FAIL / NOT_RUN for the evidence gates. Finishing with a failure is
   not a success claim and does not authorize extending the experiment.
4. Benefit: report matched-budget differences and all costs separately. Zero or
   negative benefit is a finished finding, not a reason to add runs. Method-only
   and harness-only claims require their respective ablations.

Native tests using a local scripted model provider validate transport and control
mechanics, not model competence or RSI benefit. Headless acceptance is not evidence
that the installed interactive `procodex` entrypoint is complete. No default local
installation is changed by this revision.
