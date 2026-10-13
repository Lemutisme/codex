# Decision-relevant state transitions for long-horizon agents

**Status: FUTURE / research proposal.** No implementation or experimental
result is claimed by this document. The companion [design](state-transition-design.md)
specifies the first executable experiment, not a production API.

## Research question

For a specified task family, continuation policy, and intervention family,
can structured execution history support a smaller decision representation
without materially changing action-value differences, and can its recorded
dependencies reduce the cost of estimating those differences?

The proposed contribution is a measured representation and computation
tradeoff, not a universal memory replacement. A state-transition kernel is
an enforcement mechanism; learning which information matters remains a
separate research problem. Sharing records between these mechanisms is
useful, but their joint benefit must be demonstrated.

## Motivation and competing explanations

An experiment reports 92% accuracy. A later audit finds leakage in the exact
dataset version used. The report remains an accurate record of what the tool
returned, but it may no longer support model selection. Correct retrieval of
the report alone is insufficient. Conversely, an action gate can reject a
stale promotion without helping the agent choose its next experiment.

This example motivates three distinctions:

- Persistence records what happened; current support determines which
  recorded evidence can justify a particular decision now.
- An execution dependency explains where an artifact came from; an evidence
  dependency states a checked support rule; neither alone identifies an
  intervention effect.
- Action admissibility and action value are different. An authorized action
  may be wasteful, and a blocked action does not demonstrate a smarter policy.

These ingredients have precedents in belief-state filtering, truth
maintenance, build systems, database provenance, and runtime verification.
Their combination is not itself a novelty claim. Strong alternatives include
retrieval with current-version metadata, deterministic active-object views,
event-log replay, and direct counterfactual continuation without graph guidance.

## Objects and scope

Use distinct names rather than calling every representation "state":

- `H_t`: the agent-observable interaction prefix, including delivered audit
  and authority events. Undelivered world changes are not known facts.
- `D_t`: a durable, versioned provenance and support graph reconstructed from
  authenticated events. It need not fit in the model context.
- `M_t`: the materialized operational projection: active objects, support,
  obligations, budgets, and pending operations at an event sequence.
- `C_t`: a budgeted decision view compiled from `M_t` and authorized reads of
  `D_t`. Its token budget is not a bound on total storage.
- `K_t`: a replay checkpoint, potentially including evaluator-only hidden
  environment state. It is not interchangeable with `C_t` or `H_t`.

An unknown environment mechanism may require a belief or sufficient statistic,
not a selection of historical nodes. For repeated Bernoulli observations with
a fixed Beta prior, success/failure counts summarize predictive uncertainty;
the observations inform a latent cause rather than cause future outcomes.
Such a summary must have an explicit update rule and retained provenance.

"Causal frontier" is a candidate interpretation of a decision view, not a
claim that a separator can be recovered from an arbitrary execution DAG.
The first experiment uses instrumented dependencies and finite typed support
rules; free-form semantic dependency recovery is a later, separate uncertainty.

## Formal target and its limits

For a fixed goal, histories can be grouped by their future outcome laws under
comparable admissible continuation policies. This is a useful idealization,
related to predictive states and state abstraction, not a learning algorithm.
An incrementally maintainable quotient also needs equal action admissibility
and successor closure for common supported observations:

$$
h\sim h'\quad\Longrightarrow\quad hao\sim h'ao.
$$

Equality of terminal outcome distributions alone does not establish that
closure. Nor does the existence of a quotient establish finite size,
identifiability, or efficient learning. A changed goal or policy family can
require distinctions that an earlier abstraction discarded.

The empirical target is narrower. Fix a continuation policy $\pi$, utility
$J$, and a declared query family $\mathcal Q$ of prefixes and admissible
actions. Policy identity includes downstream input construction, not just
model weights. Let $\phi(H)=C$ and define:

$$
Q^\pi(h,a)=\mathbb E[J\mid H=h,\operatorname{do}(a),\pi],
\qquad
\Delta^\pi(h;a,a_0)=Q^\pi(h,a)-Q^\pi(h,a_0).
$$

If a representation and value estimator satisfy, on that family,

$$
\sup_{(h,a)\in\mathcal Q}
|Q^\pi(h,a)-\widehat Q^\pi(\phi(h),a)|\le\epsilon,
$$

then pairwise credit error is at most $2\epsilon$ when both actions belong to
that family.
This is a conditional triangle-inequality bound, not a new theorem or an
available engineering guarantee. Finite test samples establish only measured
error on the tested distribution. A bound for $Q^\ast$ would instead concern
optimal continuations and cannot substitute for this policy-specific premise.

Two distinctions constrain any proposed unification:

1. Histories with identical future control consequences may have different
   past contributions. Future sufficiency does not imply retrospective
   attribution sufficiency. Retain the historical graph and replay archive
   separately; do not promise one minimal representation for both.
2. A hindsight cut can exploit information unavailable online. If a later
   random query asks for either of two earlier bits, the realized suffix needs
   only one bit, but an online representation cannot know which one. Used-node
   ancestry is an auxiliary label, not sufficient supervision by itself.

Shared representation is therefore a hypothesis about useful reuse of
identities, features, and dependencies, not an equivalence between control
state and a causal explanation of the past.

## Falsifiable hypotheses

**H1 — decision-view efficiency.** At matched task conditions and identical
authority checks, a dependency-aware view preserves action value and task
utility within a preregistered margin while reducing decision-context cost
relative to strong budget-matched retrieval and active-object baselines.

**H2 — replay allocation.** At matched total measurement cost, dependency-guided
selection of decision points estimates policy-conditioned action differences
more accurately than uniform/random allocation and a learned critic. It may
fail when useful alternatives are absent from the realized graph.

**H3 — useful coupling.** Sharing learned representation features between view
selection and replay allocation improves their quality/cost tradeoff beyond
separately optimized components. This is optional: H1 and H2 do not imply H3.

Evidence invalidation and permission checks are held constant across these
comparisons. Lower violation rates caused only by adding an execution gate
are not evidence for H1 or H2.

## First study

Start with a replayable synthetic research workflow: inspect candidate
artifacts, run costly development/holdout evaluations, audit evidence, choose
an alternative, defer, or request a simulated incumbent update. Include delayed
revocation, competing support paths, pending results, and hidden reliability.
The simulated register update is not deployment or implemented ProContract
succession. Invalid admission and unknown external effects remain distinct.

Freeze task generation, the downstream policy, evaluator, authority rules,
candidate action generation, and split identities before collecting labels.
Use instrumented graph records first, so parser errors do not obscure the
representation question. The [design](state-transition-design.md) defines a
deterministic baseline and a bounded subset-search teacher before learning.

Measure these two estimands separately:

- **Checkpoint-conditioned effect:** continuation return with the realized
  hidden environment state held fixed and future noise sampled correctly.
- **Information-conditioned decision value:** expectation over hidden states
  consistent with the agent's prefix, using an exact finite posterior in the
  synthetic environment. Do not feed those states to the agent.

Unlimited continuations from one fixed hidden state do not generally estimate
the second quantity. Also, neither quantity is individual responsibility under
a fixed realization of every future random variable.

The utility must reward appropriate acceptance or rejection and charge real
evaluation costs. If it rewards only promotion, faithfully estimated credit
can penalize a useful audit. Adding an information bonus would change the
objective rather than repair that estimator. Reusable information is valuable
only relative to a declared later-task distribution and evaluation horizon.

## Comparisons and measurements

Run a factorial comparison of view selection and replay allocation. Include:

- recent history and retrieval with current validity/version metadata;
- a deterministic active-object/support view at the same token budget;
- full-history model input as a practical baseline, not an optimal oracle;
- uniform/random counterfactual allocation and a critic trained on the same
  permitted training data;
- dependency-guided allocation with a nonzero random exploration component;
- learned view selection only after deterministic baselines are reproducible.

Report task utility and completion, action-ranking error, checkpoint-level
decision loss, stale-evidence attempts versus actual commits, unjustified
rejection/defer rates, and recovery latency. Report credit MSE/rank correlation
against independent high-budget references with their uncertainty and
test-retest floor. Human graph agreement is not causal ground truth; report
critical omitted dependencies separately from average edge fidelity.

Account for input/output tokens, cached tokens, graph construction, teacher
generation, storage, tool computation, replay, and wall time. Separate online
costs from offline training and report any amortization assumption. Fresh
budgeted-reader experiments do not establish savings in Codex's append-only
production context lifecycle.

Preregister split identities, replicates, confidence procedure, noninferiority
margin, cost criterion, and stopping rule in the run manifest before holdout
execution. Use independent reference rollouts, retain failures and censored
runs, and split by task family/artifact lineage rather than adjacent prefixes.

## Decision gates and non-goals

Proceed to policy learning only after the frozen-policy study identifies a
representation or replay-allocation benefit. Proceed to a Codex adapter only
after replay integrity, privacy, and bounded-context requirements are met.

- If active-object rules match a learned selector, retain the simpler rules.
- If random replay matches graph guidance, reject the H2 efficiency claim.
- If compression improves decisions but harms attribution, keep separate
  representations rather than imposing a joint bottleneck.
- If gains disappear after full cost accounting or authority-matched controls,
  report the null result rather than a generalized state-management benefit.

Not claimed: universal finite sufficient state; automatic semantic truth;
causal identification from DAG topology; physical rollback from log edits;
monotonic self-improvement; or a guarantee inherited merely from ProContract.
The control plane checks declared authority and evidence conditions. The
learning plane estimates value and cannot modify its own evaluator or admission
rules within a comparison.

## Repository relationship and prior work

[ProContract](pro-contract.md) remains the normative specification. Its
[implementation mapping](pro-contract-implementation.md) and
[evidence custody rules](pro-contract-evidence.md) are reference boundaries.
[Witnessed succession](pro-contract-succession.md) is FUTURE; this proposal
does not promote its register or commands to implemented status.

Primary sources checked for the discussion, with deliberately limited claims:

- [Invariant Causal Prediction for Block MDPs (2020)](https://proceedings.mlr.press/v119/zhang20t.html)
  connects causal features and abstraction under structured environment and
  observation assumptions, not arbitrary agent POMDPs.
- [RUDDER (2019)](https://papers.nips.cc/paper_files/paper/2019/hash/16105fb9cc614fc29e1bda00dab60d41-Abstract.html)
  studies return redistribution; redistribution is not evidence validity.
- [GraphGPO (2026)](https://proceedings.mlr.press/v306/cheng26e.html)
  uses a cross-rollout state-transition graph and goal-distance advantages,
  rather than identifying effects from an evidence DAG.
- [SearchAtlas v1 (2026)](https://arxiv.org/html/2609.10901v1)
  reconstructs evidential search graphs with fallible semantic attribution;
  its limitations include invisible internal dependencies and inference cost.
- [C3 v4 (2026)](https://arxiv.org/html/2603.06859v4)
  defines when traces restore an interventional continuation law and estimates
  credit by replay. Hidden state and Monte Carlo error remain explicit limits.

These sources motivate comparisons, not a completed novelty search or proof
that the proposed coupling is necessary.
