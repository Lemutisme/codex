# RSI after the structural migration

This is the migration design after optional task lifetimes and explicit request
context. It is not an enabled campaign or a claim that automatic self-improvement
has been validated. The existing RSI implementation and historical campaigns are
unchanged.

## The smallest reusable structure

An improvement is ordinary work on an identified version, with observations that
can support a scoped claim and an authorized decision about adoption. It does not
need a second responsibility kernel. The durable objects are:

| Object | Meaning |
| --- | --- |
| Version | Exact effective strategy, harness build, model configuration and lineage |
| Observation | Artifact/trajectory/check outcome, subject, conditions and provenance |
| Experiment | A frozen assignment connecting versions, tasks, environment and measurement |
| Decision | A scoped interpretation and authorized adoption against an expected current version |

Hypotheses, predicted mechanisms, counterexamples and unresolved questions are
strategy-authored context attached to these objects. The harness can validate
references and execute the selected operations; it cannot infer that an empirical
lesson is universally true.

Task quality, protocol/execution validity, internal Support, and adoption are
separate facts. An externally correct artifact remains useful when internal
review fails. Conversely, internal Support does not establish comparative
improvement. Preserve unsuccessful runs and their actual conditions alongside
successes; a retry is a new recorded attempt, not a replacement result.

## Reuse and replacement

| Existing code | Reuse | Change before reuse |
| --- | --- | --- |
| `procontract_rsi.Host.register` | Immutable version bytes, manifests, lineage, crash reconciliation | Separate version storage from `Host`; version the effective-context schema |
| `Host.measure`, runner, experiment journal | Isolated execution, retained outputs, model/evaluator/environment identities | Accept an explicit experiment assignment rather than choosing tasks/workflow internally |
| `procontract_succession.confirmation_plan`, `record_run` | Durable assignment, recovery without another solve | Remove assumptions about fixed task counts, two attempts and universal score gates from generic operations |
| `procontract_succession.adopt` and store transaction | Expected-incumbent checks, authorization, atomic adoption and idempotent receipt | Keep the decision policy external and bind its identity and evidence |
| Trajectory/archive readers | Scoped retrieval of real observations and failed attempts | Expose views as tools without requiring a particular analysis role sequence |
| `Host.step`, `stream_step`, `learn` | Historical behavior remains readable/replayable | Replace scheduling with context-level strategy calling operations |
| `procontract_release.advance` | Persisted release intent and resumption | Separate this from every-N-batches selection and insight/signature gates |

Do not migrate `NOISE_FLOOR = 0.087`, `PRIOR_RESCUE = (1, 10)`, the mandatory
analyst/challenger sequence or `harness.json` workflow predicates into the new
generic harness. They describe particular research policies. A policy may still
choose paired experiments or independent criticism when useful, with its reasons
and limits explicit in context. A statistical tool may compute an estimate;
choosing its assumptions and interpreting it remains strategy work.

The old `BUNDLE_FILES` and `TASK_FILES` omit `work_method.md`, which now affects task
execution. Merely adding it to the old lists would alter historical version/twin
meaning. Introduce a new manifest schema that captures the actual resolved
contexts, including fallbacks, work method and referenced skills. Preserve old
IDs, manifests and reports; associate a new version with its historical parent.
Record task-solving context separately from self-study context so changing the
research method cannot inherit an unearned task-performance claim.

## Operations instead of a workflow interpreter

The next harness interface should expose a small set of operations over existing
stores and runners:

- Read retained versions, observations and experiment state by identity.
- Snapshot/register the selected effective context or harness build.
- Submit an explicit experiment assignment, inspect it, cancel it, or resume its
  retained execution. Dispatch uses a durable request ID; uncertain dispatch is
  reconciled before replay.
- Record an interpretation linked to exact observations, including contradictory
  evidence and applicability limits.
- Adopt a selected version using existing authorization, the expected incumbent
  revision and a frozen decision basis. Recall an already committed receipt;
  reject a stale decision without selecting a replacement automatically.

These are conceptual interfaces to extract from existing code, not implemented
commands. The assignment describes inputs, resources and measurements, not a
program saying which research step must follow which result.

The coordinating agent receives these operations and a replaceable research
prompt/skill. It can analyze successful and failed trajectories, propose a
minimal change, choose discriminating controls, interpret results and request
adoption. It can also retain a useful finding without changing the implementation.
No fixed number of critics, experiments, iterations or minutes is required by the
kernel. Explicit benchmark/resource/adoption rules remain binding.

## Automatic operation and continuation

Automation means the ordinary agent executes this research responsibility using
the operations above. A launcher can resume pending work from persisted state;
it need not encode a research sequence. User time expectations guide the strategy's
intermediate deliveries and priorities. A hard deadline is optional, independently
of cancellation and any actual compute or request allocation.

When waiting for an external outcome, input or resource, retain the unresolved
question and stop active execution until the relevant event arrives. Lack of a
deadline does not require busy polling or a permanent model process. Resumption
uses the same responsibility, original experiment assignment and recorded effects.
This event-driven research runner is still to be implemented; today's native
adapter supports interrupted task resumption, not arbitrary unattended campaigns.

For adoption, use the user's standing authorization where supplied. Binding a
decision to the expected incumbent is a consistency operation, not a requirement
to ask the user at every iteration. A candidate cannot enlarge its own editing,
evaluation or deployment authority.

## Incremental implementation and evidence

1. Extract the version/experiment/adoption operations while retaining a legacy
   adapter for old campaigns. Add the effective-context manifest and keep legacy
   hashes stable.
2. Supply one research strategy as context. It chooses workflow through the same
   tool interface as any other task; do not add another `Host.step` in disguise.
3. Run a complete improvement episode: retained real trajectories → explicit
   hypothesis/change → frozen control and fresh evaluation → retained conclusion
   → authorized adoption or retention of the incumbent. Track all attempts and
   actual model/compute use. Score-specific benchmark rules belong to that profile.
4. Interrupt during dispatch and adoption, resume without duplicated work or
   renewed resources, and verify stale decisions cannot replace newer versions.
   Change the research context without changing the harness to demonstrate the
   intended separation.

That episode establishes operational automation. Repeated improvements on fresh
tasks, with controlled comparisons and costs, are needed to claim useful RSI.
Neither one green test nor one adopted version demonstrates general self-improvement.
