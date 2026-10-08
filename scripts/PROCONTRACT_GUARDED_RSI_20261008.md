# Adopted-producer closure, not an improvement claim

This increment adds `--stream-mode guarded` to the existing Host. It does not replace
the ProContract kernel or change the default `explore` stream. The trusted kernel,
evaluator, model weights and authority rules remain fixed; the versioned object is the
execution policies, research-method policies and bounded executable harness program.

## One closed cycle

```text
serve V0 -> observe feedback -> analyst/challenger/researcher V0 -> propose V1
probe V1 -> analyst/challenger V0 -> fixed release gate
         -> paired fresh confirmation of V1 against V0 -> authorized adoption
serve V1 -> analyst/challenger/researcher V1 -> propose V2 -> ...
```

A probe is an experimental execution, not permission to serve or research. The old
incumbent evaluates the probe's research signature. An unadopted exploration head
cannot become the next production researcher. Explicit adoption waits without buying
new work. Rejection keeps the incumbent; invalid execution/evaluation halts the phase
without changing its frozen assignment. The source reservation remains spent.

Each assignment records phase, candidate, incumbent and incumbent ledger sequence.
The active adoption must still be discharged: Challenge/Withdraw can revoke an
incumbent without appending a new selection, so sequence equality alone is insufficient.
Resume repairs interrupted publication/ledger and adoption/phase handoffs without
another paid invocation. Complete version directories are staged and renamed before
registration. The first experiment document is hash-bound; an alternate explanation
cannot overwrite it. Interrupted or drifted source bundles fail closed.

Method-only candidates are deliberately deferred: task twins cannot demonstrate that a
new researcher learns better. A bundled P/M/H adoption certifies the tested task-level
criterion, **not an isolated M benefit**. Proving a better updater still needs a matched,
budgeted comparison of the descendants it produces on held-out task families. Recursion
means the adopted updater actually creates its successor; it does not imply that each
generation improves, or that the method has learned a generally better learning rule.

## Canonical evidence remains canonical

`procontract_canonical.py` ports the previous study's canonical adapter and removes its
three-task hardcoded allowlist. An operator supplies a bounded registry with absolute
resource paths, source/HF revisions, exact cleanroom image IDs and fixed eligible-case
counts. Registry bytes are externally SHA-256 pinned. Candidate code cannot select it.
After `freeze`, canonical CLI commands require `--pins-sha256` as well as the registry
identity. Evaluator/score children receive the same exact pins hash and reject drift
before doing work. Preflight also requires every active branch's offline test blob;
a partial blob manifest is not sufficient evidence of readiness.

The metric remains the fixed eligible-test denominator, with skipped cases nonpassed
and branch errors invalid. Do not switch to the generic adapter to obtain fresh tasks:
its skipped-case denominator differs. A campaign declaring canonical evaluation cannot
silently fall back to a generic adapter on resume. Known exposed repositories cannot be
in the confirmation pool; commits of one repository cannot straddle development and
confirmation. This does not establish unknown pretraining exposure or empirical task
independence.

The cached score binds task, submission, raw evaluation, feedback, registry, pins,
adapter and evaluator epoch. Host additionally checks the requested version/task/purpose
and allowed attempt directory. A self-consistent result for another task cannot be
substituted. Before first adoption, the supported evaluator/environment identities must
still match. An already settled adoption remains an immutable historical decision.

Evaluator launch allowances are claimed durably before process dispatch. An unknown
claimed launch cannot buy a second attempt; a late bound worker completion may reconcile
the original attempt. Only a known invalid completion can consume the second evaluator
allowance on the same archive. Source archives publish by atomic rename, not the mere
existence of an output pathname after a failed tar command. This is fail-closed recovery,
not proof of exactly-once execution under all machine/storage failure modes.

## Live entry, only after operator preparation

Use the new native `procontract_rsi.py` CLI, **not** the previous study's
`setup/run_study.py`: that launcher freezes the old Host/adapter, disables releases and
also includes Astra. This increment does not supply a completed pinned live launcher.

Required initialization options, in addition to the normal runtime and task inputs:

```text
--model gpt-5.6-luna --effort max
--canonical-registry <absolute registry path>
--canonical-registry-sha256 <operator-pinned registry SHA-256>
--canonical-pins-sha256 <operator-pinned pins SHA-256>
--stream-mode guarded --instances <stream list> --batch 1
--release-every 1 --sealed <independent reserve> --task-attempts 1
--task-deadline-secs 18000 --parallel 1
--analysis-deadline-secs 3600 --research-deadline-secs 3600
```

Adoption defaults to explicit. Use `presumed` only under the principal's predeclared
adoption convention; it does not bypass confirmation. Set the pool size, number of
paired confirmation tasks, wins and minimum delta before observing results. The example
offline fixture thresholds are not an empirically justified live-study design.

At least four declared stream tasks are needed to witness the third phase's adopted
researcher proposing V2: the final stream batch only analyzes, never generates a
successor that cannot be tested. A successful five-phase run can demonstrate two
adoptions and V2 serving. Failed candidates need not produce this shape and must not be
rescued by changing the pool, order or gate after inspecting evidence.

One task allocation is `purpose × version × task`, with a maximum of five inference
hours, not five hours for the whole study. Four confirmation tasks give candidate and
incumbent eight separate allocations. Research and analysis costs are separate. Analyst
and challenger each have their existing bounded attempt allowances. `--research-steps`
is a legacy campaign limit, not a guarded-stream spending cap: the live manifest must
bound phases, research calls, confirmation allocations and total authorized spending.
Deadline cleanup tails do not provide a hard real-time guarantee.

Before any paid entry, freeze and verify all Host/runner/interpreter scripts and seed
policies; Codex, its code-mode host and store binaries; both Python environments; task
prompt, task order, sealed reserve, gates and budgets; exact research image ID; provider
configuration (not secret values); canonical registry, adapter, pins, fixtures, wheels
and test blobs. Old three-task pins cannot be reused unchanged. Pinning only the adapter
does not seal the entire runtime. Exact image-ID preparation must inspect the local
image rather than fetching unrelated legacy tags.

## Evidence and limits

The persisted guarded smoke uses real Host/store transactions, the bounded interpreter
and production DeliveryBudget with deterministic task/research/transport peers. Its toy
scores are declared as 0.5/0.6/0.7 as a function of an exercised steering decision. It
records V0 -> V1 -> V2, adoption before V1 serving/research, role/H identities and resume
without additional work. These are synthetic routing tests, not ProgramBench results.

There has been no new authenticated Luna inference or Docker execution in this
restricted environment. The earlier native protocol smoke accepted configuration but
did not start a model turn. Live canonical evaluation, model-generated P/M/H changes,
independent confirmation and adopted-version continuation remain unverified. No causal
RSI gain, generalized research-method gain, weight-updating TTRL or latest-upstream
Codex integration is established by this increment.
