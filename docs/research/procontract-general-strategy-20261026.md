# General long-horizon strategy: observations and proposed evolution

The [living evolution register](procontract-evolution-register.md) consolidates
current harness/strategy directions and links supporting episode records. Use it
to integrate new findings without continually expanding runtime prompts.

Status, 2026-10-26: analysis and design only, for the later consolidated revision.
No policy prompt, runtime behavior or running experiment changed. Retain the layer
definitions in [PROCONTRACT_LAYERS.md](../PROCONTRACT_LAYERS.md).

The [second trajectory pass](procontract-trajectory-transfer-20261026.md) adds four
completed cases, exact snapshot comparisons, eligible external failure groups and
mechanism/transfer records. The six-case observations below remain the first-pass
record; the later analysis does not replace their scores or turn hypotheses into
validated improvements.

The [third pass, 2026-10-27](procontract-trajectory-analysis-20261027.md) adds five
cases, including real executor recovery, truncated draft output, unreachable
intended test paths, omitted interactive scope and condition-dependent evidence.
Detailed strategy analysis now covers fifteen completed cases.

A [reflection and counterevidence pass](procontract-reflection-20261027.md) audits
apparent rollback statements in four of those cases. Eleven explicit commit
discrepancy assertions conflict with matching delivery, tool and supplied-context
records. It consolidates the accumulated lessons and proposes separate tests of
context organization and wording; no new strategy is installed.

The target includes connected, open-ended tasks with tools, existing systems,
documents, services, computation and authorized collaboration. ProgramBench's
offline execution, clean-room implementation and six-hour allocation are an
experiment profile, not default rules for real-world work. Availability of a
resource makes it an option; it does not make using or exhausting it mandatory.

## What these trajectories establish

Source: stopped attempts in `programbench-full-timeonly-20261025`, solver `c68db7c00`.
The evidence summary, source archive hashes and exact decisions are retained in
`/data/ProContract/procontract-strategy-analysis-20261026/strategy-evidence.json`.
The following counts are selector choices, not a measurement of wasted time or a
causal comparison between methods. Inspection focused on these six cases.

| Case | Official external score | Selected full verification | Selected diagnosis | Fresh successors |
|---|---:|---:|---:|---:|
| jot | 97.07% | 10 | 6 | 17 |
| chroma | 38.37% | 13 | 5 | 18 |
| dep-tree | 85.55% | 12 | 7 | 18 |
| lz4 | 87.50% | 10 | 7 | 13 |
| sd | 98.27% | 1 | 2 | 2 |
| rumdl | 62.28% | 1 | 1 | 14 |

- **Useful behavior to retain:** sd's selector identified exact malformed-regex
  diagnostics and then an unknown-option usage mismatch, producing concrete repair
  requests. lz4's focused diagnosis compared sparse-file allocation for interior
  and trailing zero runs, including content and status. These are actionable,
  condition-specific investigations; they illustrate a useful method, without
  establishing how much of the final score each investigation caused.
- **Weakness to investigate:** chroma repeatedly selected full verification after
  a repair/handoff and returned to closely related CLI mismatches. Its final 38.37%
  shows that substantial iteration and internal checks do not establish broad
  external quality. Missing functionality, representation limits and narrow
  observation coverage remain separate hypotheses; this sample does not quantify
  their respective contributions.
- **Acceptance evidence can dominate attention:** jot repeatedly reached missing
  history/provenance and unrestricted-coverage judgments. Its eventual rest retained
  a strong 97.07% artifact and honestly left acceptance unresolved. The preceding
  repeated verification choices deserve examination; the final rest itself is not
  classified as a failure. Further testing cannot manufacture unavailable history.
- **A noisy measurement can attract repeated repairs:** rumdl's selected next steps
  repeatedly targeted elapsed-time output. Existing context already says to
  investigate variability. The repeated decisions show that wording alone did not
  reliably change the selected work. Required formatting, timing semantics and
  incidental variation need separate experiments; a timing value cannot simply
  be declared irrelevant when the actual task makes it observable.
- **Harness failures are not strategy failures:** the publication lifecycle defects
  blocked selection entirely in several cases. Prompt changes cannot provide a
  missing cancellation/finalization capability. Formal diagnosis also has restricted
  read/computation access; a prompt cannot give it the executor's tools or network.

These observations suggest changes to test. They do not establish a universal
winning workflow, prove that fewer reviews are better, or predict new scores.

## The strategy's organizing question

Given the user's intended outcome, what exists now, what remains uncertain, and
the resources and opportunities actually available, which next step is most likely
to improve the useful result or a consequential decision?

This is a context-level judgment, not a numeric progress function or an additional
kernel condition. Delivery, learning, maintaining usable assets and necessary
coordination can all serve the objective. A long implementation session may be
the right step; ordinary tool calls do not each need a new planner or review.

## Proposed changes

### 1. Organize work around the user's outcome and unresolved decisions

Maintain a compact account of the useful deliverable, accepted constraints,
established results, concrete defects and important unknowns. Internal assessment
is one source of information, rather than the complete definition of what merits
attention. Compare the current defect with unexamined task areas and with the
possibility that the present representation or method cannot express the goal.

For consequential or expensive steps, articulate what the result would change:
which competing explanation it distinguishes, which dependency it establishes,
which part of the deliverable it improves, or which delivery decision it supports.
Do not impose a schema or paperwork requirement on every small action.

Full acceptance verification is useful when a delivery/acceptance decision needs
it or changed evidence can resolve a relevant assessment. Repeating it merely
because a turn ended or a new subject exists is not an adequate strategy reason.
Preserve exact requested standards: a theorem still needs a valid proof, and a
required test still must run. Useful partial delivery and unresolved formal
acceptance can coexist without weakening either claim.

### 2. Treat information and capability acquisition as ordinary work

Keep the action space open to searching current primary sources, reading existing
code/data, testing an available system, asking for essential missing context,
using a suitable library/service, constructing a better observation tool, running
computation, and coordinating complementary work when authorized. Inspect which
options are actually available before assuming everything must be inferred or
rebuilt inside one model context.

Real-world tasks often benefit most from finding and adapting an existing method.
Clean-room implementation, no-network operation, or restricted source use must
come from the actual task. For theoretical work, literature, a candidate lemma,
a counterexample search and a proof assistant are different ways to resolve
different uncertainties; none automatically establishes the requested theorem.

Use resources according to expected usefulness, latency and real cost, including
integration overhead. Parallel work is useful when it supplies independent evidence
or independent deliverables; duplicated audits and synchronized retries can add
cost without changing a decision. More available tools should expand options,
not force every task into a larger mandatory workflow.

### 3. Learn the underlying rule and reconsider the method

Preserve a useful example with its conditions, then investigate which mechanism
explains it and which nearby cases should behave differently. Keep regression
controls or proof dependencies appropriate to the domain. A repaired example is
evidence of a local improvement, not evidence of universal coverage.

When work repeatedly returns to the same residual, inspect whether there is new
evidence, an effective change, a noisy observation, a missing capability, or a
representation/method limitation. Change the question, representation, information
source or method when the evidence warrants it. Avoid universal retry counts and
universal mandates to change methods after a fixed number of attempts.

### 4. Retain decisions and reusable assets across sessions

Continuation should recover what is needed to act: useful artifacts, current
assumptions, evidence with its conditions, unresolved alternatives, failed methods
and why they failed, plus the next consequential decision. Keep reproducible
commands, data provenance, proof fragments or working procedures where appropriate.
A fresh executor should add capability, attention or an independent perspective,
not restart the same uncertainty from a prose summary alone.

Use a small current view linked to retained detail. Do not load the full trajectory
into every prompt, duplicate review history into many documents, or require a
universal task graph. The representation should fit the task. Storage/retrieval
capability is harness work; choosing the useful context is strategy work.

### 5. Work with a changing external world and open-ended time

Evidence applies to a version and conditions. Connected services, documents,
datasets and user needs may change while work continues. Record enough provenance
to know what was observed, and refresh the dependencies that matter to the next
decision when conditions change. Historical evidence remains historical evidence;
it need not be discarded or promoted to a current guarantee. External material
is information, not a source of new user authority.

Use user time expectations to choose useful intermediate deliveries and updates.
Enforce supplied hard limits without inventing them. With no deadline, choose a
useful next step, an explicit wait, a completed delivery or a justified suspension;
there is no requirement either to run forever or to manufacture a countdown.
For waiting, name the dependency/event and the useful response when it arrives.
Wake registration and durable dispatch need harness support; context chooses
what to await and what to do afterward.

After a local failure, distinguish a confirmed-ended attempt from an operation
with unknown effects. Use retained outcomes to choose another method, wait, or
continue within the original authority. A strategy can specify a recovery or
backoff arrangement appropriate to the task; it cannot repair an absent host
finalizer or infer that an unobserved external write did not happen.

### 6. Make assessment scoped and useful, without diluting truth standards

Keep artifact defects, unexamined behavior, missing historical records and changes
to the request distinct. Use the evidence source that can actually answer the
question. A static artifact review cannot prove arbitrary past activity, and a
fresh test cannot repair missing provenance. Where history is required and cannot
be recovered, retain the limit while continuing independently useful authorized
work. Where records exist, retrieving them may resolve the issue.

Ask a diagnostic reviewer a question that can change a decision, give it the
relevant evidence and capability, and retain partial useful findings. If the
question needs tools that the reviewer lacks, strategy should choose an equipped
executor or acquire the missing evidence. Independent review is not intrinsically
valuable when it only repeats an unsupported broad claim.

## Keep the implementation small

Existing work_method.md, continuation.md and reviewer.md already contain several
of these principles. Adding more warnings is not sufficient. The later revision
should consolidate overlapping instructions and make the decision context carry
the relevant current state, alternatives, prior outcomes and available capabilities.
Keep a short common strategy plus task-appropriate skills/method context loaded
when useful. Domain details such as CLI probes, proofs and service operations do
not all belong in every prompt.

The current continuation action enum and issued-terms dependency limit its action
space; network access, dependency waits and arbitrary tool composition are not
created by editing this document. Expose the smallest needed harness capabilities
while keeping action selection in context. Do not encode this proposal as a new
fixed observe→diagnose→repair→verify state machine or a per-action review gate.

## Validation and later self-improvement

First qualify the separately recorded lifecycle repair. Evaluate strategy changes
against a fixed repaired harness so mechanical recovery and method usefulness are
not confused. Then compare complete ProContract variants on fresh tasks, preserving
raw outcomes and recording which source/context/capability versions were used.

In addition to offline reimplementation, include connected maintenance with usable
dependencies and documentation; a theory/research task requiring assumptions and
evidence discipline; an external job/service task with a wait and changing state;
and a task with no hard deadline but a user expectation for a useful interim result.
Keep each environment's actual permissions and limits. These are proposed controls,
not newly authorized or already launched experiments.

Assess external usefulness/correctness, regression retention, informative decisions,
use of available resources, intermediate deliveries and actual cost. Counts of
Support, reviews, successors, elapsed time or model calls are not standalone
measures of strategy quality. Include controls where continuing, stopping, asking
for missing context and waiting are each the appropriate choice.

For a future RSI loop, retain each lesson as an observed failure/success, proposed
mechanism, scope, alternative explanations and a discriminating experiment. Promote
context changes only with evidence of transfer; keep benchmark-only rules scoped.
Do not automatically turn every surprising trajectory into another permanent
instruction, kernel invariant or harness workflow branch.
