# State-transition research design

**Status: FUTURE / proposed specification.** The [proposal](state-transition-proposal.md)
defines the scientific claims. MUST, SHOULD, and MAY below govern a future
prototype; they do not describe functionality added by this documentation.
Repository integration points were inspected at `7f0ffe58c8`.

## 1. Deliverable and trust boundary

The first implementation is an offline, replayable research harness under a
proposed `scripts/state_transition/` package, following `scripts/pyproject.toml`.
Use Python standard-library records, JSON, hashing, and SQLite initially.
Separate private record/reducer, view, replay, and evaluation code only as
needed; no service, new Rust dependency, or generic belief-graph framework is
required. Learning dependencies are a later, separately reviewed change.

The harness implements a finite candidate-evaluation workflow, not general
ProContract settlement or production deployment. Its actor can request tools
and simulated register updates, but cannot write authoritative tables, issue
validator receipts, or alter the evaluator. A simulator-owned mutation channel
provides complete mediation for this experiment only.

Trusted inputs are the frozen simulator, authenticated authority events,
versioned validators, transaction code, and artifact identity function.
Agent text and tool narration are observations, not authority. Hashes establish
identity, not semantic truth. Missing dependencies invalidate a guarantee even
when every stored hash matches.

### Synthetic environment contract

The first task has two candidate IDs and one incumbent. A finite joint latent
state assigns each candidate quality (`improves` / `does_not_improve`) and
measurement integrity (`clean` / `tainted`). The task manifest supplies the
prior and finite observation likelihood tables; these are evaluator inputs,
not additional model context. Small state spaces permit posterior enumeration.

The action vocabulary is inspect, evaluate on a named split, audit, fetch,
wait, defer, and request adoption. Each action has a declared integer cost,
duration, observation alphabet, and state-transition table. A bounded logical
clock delivers delayed results and authorized withdrawal events. Public state
contains delivered observations, artifact identities, obligations, operations,
and remaining budget; it never includes latent quality/integrity labels.

The manifest fixes a finite horizon and utility for correct adoption, unsafe
or non-improving adoption, and retaining the incumbent, minus execution costs.
Normative eligibility is a separate finite predicate over delivered evidence.
No coefficient, likelihood, action rule, or deadline is tuned on the holdout.
Additional fixtures cover AND/OR support and delayed information queries;
production experiments are not required to have this finite model.

## 2. Durable records and derived views

An append-only SQLite event table is the source of truth. Commit each admitted
event and its materialized projection atomically. A graph is a rebuildable
index over records, not a second authoritative database.

Proposed logical records, with schema versions and finite serialized sizes:

```text
Event: run_id, sequence, event_id, kind, authenticated_actor,
       payload_ref, payload_digest, previous_event_digest, schema_version
Artifact: artifact_id, content_digest, artifact_kind, producer_event,
          input_artifact_ids, environment_id, capture_policy_id
Claim: claim_id, predicate_kind, scope, subject_coordinates, rule_version
Support: support_id, claim_id, scope, subject_id, validator_id,
         rule_version, support_revision, premise_refs, created_at_sequence
Obligation: obligation_id, scope, issuer, revision, required_predicate,
            deadline, lifecycle_state
Operation: operation_id, idempotency_key, request_event, pinned_inputs,
           status, result_ref
Decision: decision_id, prefix_sequence, view_id, policy_id,
          candidate_set_id, selected_action, task_spec_id
Checkpoint: checkpoint_id, prefix_sequence, environment_snapshot_ref,
            policy_id, model_id, tool_versions, randomness_manifest,
            pending_operations, authority_snapshot, replay_eligibility
```

Use explicit tagged variants for event payloads, optional deadlines, and result
states. IDs resolve to immutable versions, never an ambiguous `latest` alias.
Counters for sequence/revision/budget are integers. Hash canonical JSON with a
versioned domain separator; encode numerical scores using a declared finite
representation and reject NaN/infinity. Object equality is semantic, not
dependent on map insertion order.

Each reference to mutable support additionally pins its support revision.
Artifact identity includes the capture policy; skipped files, external reads,
and unrecorded inputs make capture incomplete rather than silently exact.
Limit every event envelope to 16 KiB; store larger fixture payloads by reference
in a size-limited local artifact store. Run manifests MUST set total storage,
event-count, and traversal limits. Exceeding them produces an explicit incomplete
run, not silent history deletion.

Keep three edge kinds distinct:

- `read` / `produced`: instrumented execution provenance;
- `supports`: an authorized finite rule over exact premises;
- `estimated_effect`: a measurement reference with intervention and uncertainty,
  never inferred from the first two edge kinds alone.

Time/version-unrolled provenance and support links MUST be acyclic. A support
record is one AND clause; multiple records for a claim are OR alternatives.
An unsupported claim is not automatically false. An LLM-suggested dependency
is tagged inferred and cannot satisfy a protected support requirement.

## 3. Update semantics and invariants

The reducer consumes the current projection and one authenticated event.
Every new decision record, including a rejection, advances the log sequence;
only admitted requests change the protected domain projection. Rejections
record a bounded reason. Duplicate event IDs with identical payloads return
the original receipt without another transition; conflicting reuse is rejected.
On restart, verify record hashes, replay the ordered log, and compare the
materialized projection.

Supported event families are artifact/result registration, validator support,
support withdrawal, obligation transition, operation transition, and simulated
incumbent compare-and-swap. Every family has a frozen actor policy. Text from a
tool cannot create an issuer event. Inferred support is never upgraded merely
because it appears in a later model summary.

Support checking at sequence `s` follows:

```text
supported(claim, s):
    find a support record for the exact claim and scope
    require its validator/rule/subject coordinates to be applicable at s
    require no authorized withdrawal of that support at s
    require every premise in that record to be supported at s
    accept if any complete support record passes
```

Raw artifact existence is a leaf predicate, not proof of evaluation validity.
Leaf rule checks MUST distinguish report existence from admissible measurement.
Memoize within one snapshot. Cycles, missing premises, or exhausted traversal
budgets return `indeterminate`, which cannot authorize a protected action.
Evaluate OR alternatives before rejecting a claim; one withdrawn path need not
defeat an independent valid path. Return `supported` for any valid path,
`unsupported` only if all paths are checked and fail, and `indeterminate` when
remaining unknown paths could change the answer. Structural sharing avoids
eagerly enumerating all combinations of supports.

Withdrawal appends an event; it does not rewrite a report or prior decision.
Reverse edges mark dependent cached results dirty. Correctness comes from
rechecking the chosen support path at commit, not from asynchronous cache
invalidation completing in time.

For simulated adoption, perform the following in one write transaction:

1. Resolve the requested candidate, expected incumbent generation, task rule,
   and authority revision against the current sequence.
2. Validate the exact comparative result, current support, obligations, and
   remaining resource authorization. Reject stale or indeterminate input.
3. Commit the incumbent reference, generation increment, decision event, and
   selected evidence coordinates, or commit no replacement.

A stale view is not a permit. Revocation and adoption are ordered by this
transaction boundary. A revocation delivered after an adoption cannot prevent
the past action; it marks current support as withdrawn and opens recovery.

Operation statuses are `planned`, `running`, `succeeded`, `failed`,
`outcome_unknown`, and `cancelled`. Timeout after dispatch produces
`outcome_unknown`, not failure. Cancellation acknowledgement is required before
claiming cancellation; results are matched by operation and pinned versions.
Retries/reconciliation use the same payload-bound idempotency key; the simulator
deduplicates effects and rejects a different payload reusing that key.
Resource reservations prevent concurrent overspend; uncertain operations keep
their reservation until reconciled or explicitly accounted as consumed.
No branch deletion undoes a side effect. The initial harness simulates effects;
real deployments require separate reconciliation/compensation semantics.

Required invariant: a committed protected action has an authorized, applicable
support path at its linearization point. This says nothing about unknown
defeaters, verifier truth, task optimality, or unmediated external channels.

## 4. Decision-view compiler

Logical interface:

```text
compile_view(snapshot_sequence, goal_id, candidate_set_id, budget, selector)
    -> DecisionView | ProjectionOverflow | IncompleteState
DecisionView: view_id, source_sequence, goal_id, policy_id, selector_id,
              selected_refs, rendered_fragments, token_count, omitted_count
```

Build a view from one consistent snapshot, never from mixed ledger versions.
Candidate-generation rules are frozen across comparisons; include information
actions such as fetch support, reevaluate, audit, and defer. Read authorization
applies to all selected references. Fetching is a charged observation/action,
not free access to a hidden full-history oracle.

The deterministic baseline reserves space for task identity, applicable
obligation/authority status, budgets, pending effects, and explicit uncertainty.
It then selects active candidates and their nearest applicable evidence using
stable ordering. Return overflow rather than silently dropping protected
status. The external gate remains authoritative even when a view omits detail.
All comparison arms use the same overflow, fetch, and gate behavior.

Token accounting includes metadata, instructions, and tool-result text using
a pinned tokenizer. Each newly injected fragment has a hard 768-token cap and
the aggregate view obeys the manifest budget. Larger payloads remain external;
bounded references and charged reads expose them when needed. Lossless
statistics may replace records only under a named, tested update rule.
Summary records retain their member references and applicability conditions.
Withdrawal requires a valid inverse update or recomputation; if neither fits
the work budget, mark the summary unknown rather than retaining a stale belief.

First learned-selector experiment:

1. Use tiny prefixes containing at most eight optional records. Enumerate
   their eligible subsets, retaining the mandatory header. This is a bounded
   teacher, not a scalable general subset solver.
2. Have a frozen reader choose an action from each rendered view. Score that
   choice with independent continuation-value estimates from the full prefix;
   select the cheapest view within the preregistered loss margin relative to
   the highest-valued admissible action in the declared candidate set. Use
   disjoint search/confirmation samples when those values are sampled.
3. Fit a small inclusion scorer using prefix-available record kinds, ages,
   scopes, support status, and dependency features. Resolve selection under
   the token budget with deterministic ties. Record ambiguous teacher labels.
4. Evaluate the resulting choices and task rollouts on disjoint instances.
   Never expose suffix labels, hidden simulator state, or holdout outcomes as
   selector inputs. Charge enumeration and reader calls as offline cost.

Actual-use ancestry is auxiliary supervision only. Test delayed queries,
alternative branches, and revisions that need information absent from the
realized successful path. A selector trained under one policy must be
reevaluated when the downstream policy changes. Teacher queries fix one
reference continuation, including its input-construction rule. End-to-end
rollouts with another selector induce another policy and are reported separately;
one-step teacher agreement is not an end-to-end policy guarantee.

## 5. Counterfactual replay and allocation

Logical interface:

```text
measure(checkpoint_id, candidate_set_id, reference_rule, frozen_policy_id,
        estimand, continuation_count, randomness_plan)
    -> CreditEstimate | ReplayIneligible
CreditEstimate: intervention_ids, estimand, policy_id, reference_rule,
                replicate_returns, mean_difference, uncertainty, cost
```

A checkpoint restores environment artifacts, persistent memory, authority,
resource state, pending work, tool versions, routing, and policy/model
configuration. Eligibility records each source as restored, correctly
resampled, or unsupported. Any causally relevant unsupported source forbids
an exact-replay claim. A text prefix alone is not an environment checkpoint.

Restore the same pre-decision checkpoint for each admissible alternative;
replace that action and let the frozen continuation policy make new downstream
decisions. Never splice the factual suffix onto an alternative or assume its
dependency graph covers newly taken branches. Repeat using the declared
conditional randomness law. Fixed common seeds are optional variance reduction,
not a substitute for correct marginal distributions.

Tag estimates as checkpoint-conditioned or information-conditioned. The
latter requires posterior averaging, which the finite simulator can enumerate;
record posterior weights without revealing latent states to the reader.
Monte Carlo counts and intervals concern sampling error, not missing-state bias.
Return differences against one fixed alternative are not automatically
advantages against the behavior policy's expected action value.

The first allocator ranks decision points by changed support, unresolved
dependencies, and action reversibility, reserving a manifest-defined nonzero
share for uniformly sampled points. The control uses uniform allocation at
matched compute, not merely matched rollout counts. Record selection
probabilities. Evaluation uses an independent audit sample and independent
high-budget reference continuations, not the allocator's own samples as truth.

No policy-gradient update is in the first slice. A later learner must account
for nonuniform selection and adaptive stopping or explicitly abandon unbiased
gradient claims. Graph ancestry, centrality, Shapley allocation, and potential
shaping are not substituted for measured intervention effects.

## 6. Worked transition and executable acceptance cases

Fixture sequence: register candidate `m8`, dataset `d3`, and evaluator `e2`;
run a pinned evaluation; register its report and a validator-issued selection
support; compile a view; deliver an authorized withdrawal targeting `d3`'s
evaluation admissibility; request adoption using the old view.

Expected result: retain the report and old view, reject adoption, identify the
broken support path, and expose reevaluation/defer as possible next actions.
If an independently admissible report supports the exact same selection claim,
that path can authorize a fresh attempt. If adoption preceded withdrawal,
preserve the adoption event and mark recovery outstanding instead of rewriting
the incumbent's history as if no adoption happened.

Required tests for the first implementation:

- Ordered event replay reproduces the complete projection; duplicate delivery
  and crash injection do not create double commits or missing event/projection
  pairs.
- Forged authority, wrong candidate/evaluator identity, stale generation, and
  invalid support each reject without protected-state mutation.
- Both withdrawal/adoption orderings are deterministic; delayed old tool
  results remain historical records and cannot resurrect withdrawn support.
- AND premises and OR alternatives handle withdrawal without treating loss of
  support as falsity or revoking an independent witness.
- Timeout, retry, cancellation, and reservation accounting preserve unknown
  effects and cannot duplicate a simulated external operation.
- A view and every fragment obey their budgets; overflow and missing state are
  explicit. No future audit or suffix-derived label appears in prefix inputs.
- The two-bit delayed-query fixture exposes the gap between a clairvoyant cut
  and an online-achievable view; jointly necessary and redundant evidence
  exercise alternative paths.
- Replay restores declared inputs and lets downstream branches diverge;
  unsupported external state yields ineligibility, never an invented effect.
- An exhaustively enumerable hidden-state fixture distinguishes checkpoint-
  and information-conditioned values; reference sampling is independent.
- Cost and outcome reports retain failures, rejected actions, censored runs,
  teacher generation, graph work, and replay costs.

These are required future tests, not claims that this documentation ran them.

## 7. Evaluation artifact and progression gates

A run manifest MUST pin source and dirty-state identity, task generator and
splits, exposure history, utility/cost function, authority rules, tool/model/
policy/tokenizer versions, selector/allocator IDs, candidate generation,
estimand, seeds, budgets, replicate counts, reference protocol, uncertainty
procedure, noninferiority margin, and stopping rule. Missing preregistration
fields prevent a confirmation run; development runs are labeled separately.

Store manifests, immutable event/artifact references, views, checkpoint
eligibility, intervention schedules, raw returns, and aggregate reports in a
durable result bundle following [evidence custody](pro-contract-evidence.md).
Use private synthetic inputs first. Do not publish credentials, user prompts,
or raw tool payloads; if redaction removes a relevant replay input, mark that
export ineligible rather than claiming exact public reproducibility.

Implementation order and exit conditions:

1. **Deterministic harness:** record/reduce/project/replay and all acceptance
   cases above. No learned components or native deployment.
2. **Frozen-policy study:** match utility margins and cost accounting across
   baselines; test H1/H2 separately and their factorial combination. Stop the
   corresponding hypothesis when its simpler baseline matches it.
3. **Learned views/allocation:** add only after the teacher/reference protocol
   passes leakage and estimator checks. Require held-out quality/cost benefit
   including training amortization; otherwise retain deterministic selection.
4. **Optional native adapter:** proceed only if the preceding stages justify
   it. Policy training, general semantic DAG recovery, and succession remain
   separately reviewed work, not prerequisites for the first useful result.

## 8. Codex and ProContract integration constraints

Existing ownership, not new functionality promised by this spec:

- `codex-rs/pro-contract/src/kernel.rs` and `ledger.rs` own normative transitions
  and persistence. Do not put benchmark reward, learned relevance, or graph
  attribution in this kernel.
- `codex-rs/ext/pro-contract/` owns execution binding and evidence replay.
  Its finite replay checks are not counterfactual environment restoration.
- `ExecutionAdmissionContributor` in `codex-rs/ext/extension-api/` is an existing
  mediated admission boundary. Its payload is sensitive and must not be logged;
  capture research metadata through separately authorized instrumentation.
- Native context fragments belong in `codex-rs/core/src/context/` and implement
  `ContextualUserFragment`. Keep substantive graph/learning code outside core.

An optional adapter must append bounded, versioned context updates without
rewriting model history or resetting client sessions to force a new view.
The research harness's fresh-reader inputs are not permission to replace a
production transcript. Larger-than-1k-token individual fragments require P0
manual review; this design's 768-token cap avoids introducing one by default.

This stage changes no CLI, config, app-server schema, rollout format, or native
settlement semantics. Any later API change must use experimental app-server v2
conventions and regenerated fixtures; integration tests must cover public APIs,
context updates, resume, and foreign exec environments. Legacy rollouts without
the required records are marked replay-ineligible, not guessed into completeness.
No incumbent register is added to ProContract here; see the separate
[FUTURE succession design](pro-contract-succession.md).
