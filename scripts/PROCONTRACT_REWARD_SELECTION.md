# Reward-driven controller learning, revision 2

This supersedes ACK-driven experimental succession for **new studies only**. The
old source, lineages, terminal runs and installed `procodex` remain unchanged.

## Principles before mechanisms

The immutable kernel decides what is permitted and what counts as evidence. The
learning system decides which permitted behavior receives scarce execution and
research resources. Auditing a mutation does not make it an improvement.

- **Optimize a return, not the number of modifications.** Preserve unchanged and
  no-research alternatives. Reward must actually alter the action distribution.
- **Credit what was selected.** An action selects an initial controller P/M/H and
  either `research` or `hold`. Its return includes its whole ensuing trajectory,
  including any in-task generated update. It is not a sample of the child alone.
- **Experiment without pretending to certify.** The stable incumbent stays seed.
  A candidate can enter a bounded exploration pool after a completed native input
  witness; ACK does not change merit, selection weights, or the incumbent.
- **Learn from imperfect attribution.** A mixed trajectory is real bandit feedback,
  not a causal component ablation. Neither discard it nor label it isolated gain.
- **Charge research.** Research mode reserves 900 seconds from execution capacity;
  hold mode retains that capacity. Actual researcher/native/grading service times
  are also reported and affect utility. Never invent missing usage or dollar cost.
- **Methods earn their place through execution.** M is an optimizer program used
  to produce descendants. Changing M text is not evidence of improving M. A later
  selected descendant must actually invoke the inherited M; its full return is
  observational method evidence, not matched-budget method-only attribution.
- **Predictions are observable.** Predict canonical pass fraction or observed
  command failure fraction with a direction and threshold. Missing exit statuses
  make the latter unknown. Command count is activity, not semantic progress;
  fewer commands/errors alone do not establish task improvement.
- **Scope transfer.** Share statistics only inside a pinned study with identical
  model/effort, task contract/dependency policy, evaluator and budget profile.
  Heterogeneous tasks are still confounded; no task-conditioned generalization or
  superiority is inferred from three returns.

## Executable learning rule

A version is `(P, M, H)`. The pool has at most 8 versions and two actions per
version, `research` and `hold`. A reserved episode records the entire distribution,
selected action, propensity, random draw and pre-update state digest before paid
I/O. No unresolved episode may be resampled or bypassed.

For action a with accumulated importance-weighted loss L:

```
p(a) = (1 - epsilon) softmax(-eta L)[a] + epsilon / |A|
q = resolved / fixed_total
c = min(1, (native_seconds + researcher_seconds + grading_seconds) / episode_budget)
u = (q - lambda c + lambda) / (1 + lambda)
L[a_selected] += (1 - u) / (p(a_selected) + gamma)
```

Frozen values: eta=.3, epsilon=.2, gamma=.05, lambda=.1. This is an
**Exp3-IX-style bandit over whole controllers**, not gradient RL over model
weights. Concurrent native/research time is deliberately charged additively as
service time; native cleanup time is included. Wall time, tokens, and money are
not interchangeable. Report unclipped times as well as clipped cost fraction.

The growing pool uses an explicit optimistic prior: a newly admitted controller
starts with the smallest existing cumulative loss and **zero samples**. This is
an exploration policy, not a positive pseudo-reward. There is no claimed textbook
regret bound for this growing, adaptively generated pool. At capacity, candidates
remain recorded but cannot expand the action space.

`hold` uses P without invoking M or changing P in-task; H is dormant. `research`
uses P and the bounded H trigger, invokes M once, then can apply one child P
through fenced steering. Therefore changing H and research cost can affect the
selected policy's full return. M/H component superiority is not separately known.
A poorly performing researcher reduces its controller's future probability even
when its proposal is rejected. Unknown infrastructure outcomes do not become zero
quality; they close the study without retries. Functional return does not certify
all submission constraints or ProContract support.

## State, execution and proof locations

- `procontract_online_selection.py`: fixed learning rule, scope, bounded pool,
  sampling, cost-adjusted feedback, measurable prediction assessment.
- `procontract_online_lineage.py`: atomic reservation/claim/update events and
  protocol isolation. Selection mode never updates `current` on dispatch.
- `procontract_online_runtime.py`: selected program/budget execution, counters,
  no-tool research, H interpreter, protected phases and one fenced attempt.
- `procontract_online_pilot.py`: post-submission canonical reward, host-measured
  evidence and matching total budgets; no frozen-arm feedback enters the learner.
- `procontract_online_plan.py`: new protocol, fixed learning profile, immutable
  sources and fresh authorization. Legacy lineages cannot be silently migrated.

The fixed learning rule is part of this experiment's kernel. M proposes changes to
research strategy; H changes bounded checkpoint decisions, not arbitrary harness
source. The system does **not** yet learn its own bandit update algorithm, task
representation, global runtime implementation, or model weights.

## Validation ladder and honest stopping conditions

1. Deterministic integration: reward changes selection, poor research loses mass,
   hold restores execution capacity, missing feedback leaves statistics unchanged,
   ACK cannot promote, a witnessed child has no sample yet, and later research
   consumes its inherited M. Synthetic returns are never ProgramBench results.
2. Local native mock-provider E2E: check actual request consumption and no tools in
   the researcher. These are real harness tests but not real-model learning gains.
3. Fresh authorized ProgramBench pilot: Luna/max, three prospectively ordered
   instances, up to 5h each including grading/research; no replacement runs or
   lottery-seed shopping. Three adaptive runs test operation; six paired runs can
   give a small descriptive comparison against frozen ProContract. Old leaderboard
   scores are context only. Historical operator exposure remains disclosed.

Sampling may choose hold or revisit an old controller. Do not override the draw to
manufacture recursion or spend another run because the pilot lacked a desired
witness. Report actual stages reached. Genuine policy learning can occur without
winning; a changed selection probability is not itself measured RSI benefit.
