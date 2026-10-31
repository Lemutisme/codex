# Reflection pass: correct the interpretation before adding another rule

2026-10-27. Analysis and record only; the user's deferred-repair instruction remains
in force. At admission to this pass the cohort still had 25 completed cases and
four active cases. No new completed instance was available. This pass revisits
four of the fifteen previously inspected cases; it does not increase that count.

The earlier records are linked from
[the general strategy proposal](procontract-general-strategy-20261026.md).
The main new contribution is a negative finding: several apparent rollback stories
are not supported by the actual commit, delivery and supplied-context records.

## 1. Audit of apparent workspace rollback

Artifact root: `/data/ProContract/procontract-reflection-20261027`.

- `handoff-claim-audit.json` retains each statement, its original session hash/line,
  the preceding delivery, initial tool outputs and reconstructed successor context.
- `SUMMARY.json` records selection criteria, counts and scope limitations.
- `audit_handoffs.py` reproduces the extraction without executing a candidate/model.

A keyword search of the two existing commentary indexes selected twelve statements
in elfcat, dust, dua and tinycc. Manual reading distinguishes eleven explicit claims
that the current commit differs from, or is older than, the previous handoff claim,
and one ambiguous description of an "earlier committed snapshot". The ambiguous
statement is not counted as an explicit mismatch assertion.

For all twelve selected statements:

1. The commit named as current appears in initial native tool output from that session.
2. It is the same commit named in the immediately preceding retained delivery.
3. The previous-executor-claim field in the context supplied to the successor agrees
   with that retained delivery and contains the same commit.

Examples:

| Task | Claimed current commit | Actual previous delivery | Supplied previous claim | Later statement |
|---|---|---|---|---|
| elfcat, 03:51 UTC | `3d17aad` | `3d17aad` | `3d17aad` | "not the claimed later commit" |
| dua, 21:39 UTC | `912a46e` | `912a46e` | `912a46e` | "older than the last handoff claim" |
| dust, 22:57 UTC | `f96f428` | `f96f428` | `f96f428` | "not the later claimed hash" |
| tinycc, 18:32 UTC | `5938df5` | `5938df5` | `5938df5` | "not the later claimed commit" |

These records contradict the asserted discrepancy with the immediately preceding
commit claim. They do not prove equality of all untracked files, external services,
runtime state or behavior, and do not rule out unrelated regressions. This was a
targeted audit of suspicious narratives, not a random sample or an estimate of
their prevalence over all handoffs.

The inspected successor path captures work after shutdown and inherits the existing
execution environment; it does not restore an older workspace snapshot in this
path. Together with the matching facts above, there is no basis here for adding
a new "workspace rollback" defect to the confirmed harness repair list.

The earlier analyses preserved these comments as agent statements rather than
asserting a rollback mechanism. This follow-up supplies the factual correction
needed before a later reader or automated lesson extractor mistakes those comments
for confirmed state loss.

## 2. Available truth did not guarantee correct use of it

The reconstructed context packets contain 55,247–62,993 characters, spread across
72–83 transport fragments. These are character counts, not token counts. The
immediately preceding delivery claim is only a few hundred characters. For example,
one elfcat packet has approximately 28,277 characters in requirements, 10,421 in
current owner instructions, 7,037 in original_task, 6,683 in strategy and 4,420 in
recent assessments/selected work. The correct current commit information is present.

Three explanations remain worth separating:

| Hypothesis | Existing evidence | Discriminating future check |
|---|---|---|
| Suspicion-oriented wording encourages unsupported discrepancy narratives | Claims are explicitly labeled untrusted; comments repeatedly infer a mismatch contradicted by available facts | Hold facts/capabilities fixed and compare neutral provenance wording with the current wording |
| Current facts are difficult to use amid a large, fragmented historical context | Measured context sizes and fragment counts; correct claim field is present | Compare a concise current-state view plus references while preserving all actual owner instructions and access to detail |
| The statement is a communication error without a harmful change of plan | Several of the same sessions proceed to useful new probes and actual repairs | Track whether the false claim changes action selection, unnecessary work or delivered quality, separately from narrative correctness |

These are explanations to test, not established causes. Context size alone does
not prove overload. Fewer instructions alone do not prove improvement. Matching
commits do not make every new check unnecessary. A new experiment can reveal a real
defect even when the story motivating it is wrong.

The concrete strategy requirement is to distinguish authority from evidence use.
An untrusted assistant statement cannot create permissions or certify correctness,
but "untrusted" does not mean false. A claim supported by the actual delivery and
current tool observation should not be discarded merely because its author was
another executor. Use the evidence for the claim it establishes and retain its
conditions; ask a new question where information is actually missing.

## 3. Reflection on our own analysis method

The same discipline applies to trajectory analysis and later self-improvement:

- A final score is an observed outcome under a particular evaluator. It does not
  identify which method caused it. A low score on a difficult task is not proof
  that every local improvement was wasted; a high score is not proof that every
  audit or successor was useful.
- A model's diagnosis is a hypothesis unless corroborated by the relevant trace.
  Converting "the checkout rolled back" into a harness repair without the commit
  audit above would have expanded code to solve an unestablished problem.
- Code explaining a possible mechanism is not proof that the mechanism occurred.
  The publication cancellation defects have matching lifecycle records; the
  underlying code-mode host-exit cause is still unresolved. Keep that distinction.
- Repeated observations of the same defect add confidence about its recurrence,
  but should not create a new permanent strategy instruction for every program.
- Lack of evidence in a reviewer view is not proof that an action never happened.
  Conversely, executor confidence is not a substitute for a missing required record.

Maintain observations, interpretations and proposed changes as separate research
objects, and record counterevidence or narrowed conclusions as well as confirmations.
This does not require manual approval for every lesson or an additional kernel
truth state. The current scripts already automate some factual joins; interpreting
causes and selecting useful experiments remains reasoning work.

## 4. Consolidate the lessons into three mechanisms

The previous notes contain several variants of the same underlying issues. The
later strategy revision should consolidate them rather than append all prose to
every prompt.

| Mechanism | Strategy responsibility | Harness responsibility | Kernel boundary |
|---|---|---|---|
| Select work that advances the user's outcome | Compare implementation, information/capability acquisition, investigation, review, delivery and waiting against current important unknowns | Expose actual capabilities, retained results and resource observations | No domain workflow, progress score or empirical threshold |
| Preserve and use applicable knowledge | Interpret observations under their versions/conditions, reconcile conflicts, reuse supported facts, retain useful methods and assets | Store/read results with identities, conditions and changes; make the relevant state available | Existing evidence and responsibility relations; no claim that model comprehension follows from tool delivery |
| Continue responsibility across operation boundaries | Choose a next action, changed method, wait or rest under the original authority | Finalize/reconcile operations, preserve partial work, retain selected dispatch/wake state and enforce real limits | An attempt ending does not settle the task; no new retry transition or mandatory task deadline |

These mechanisms accommodate coding, theory, research and connected operations.
They do not require one linear plan→check→review→repair sequence. Broad resources
expand the available methods; choosing and integrating them still matters. A task
can have no hard deadline while producing useful milestones and selected waits.

The current kernel already provides the relevant responsibility and evidence
semantics for these observed issues. The most concrete unfinished implementation
is harness continuity. The most concrete strategy question is how the effective
context makes current facts, task scope and meaningful alternatives usable.

## 5. Candidate direction, not a new pile of prompts

A short shared strategy could convey the following, with task-appropriate domain
methods supplied only when useful:

> Advance the user's intended result under the original authority and actual limits.
> Choose the next useful action using current work, applicable observations,
> important uncertainties and available capabilities. Preserve results and the
> means to continue. Reuse evidence within its scope; update the relevant judgment
> when new observations or conditions change it. After a local failure, distinguish
> known outcomes from unresolved effects and choose continuation, another method,
> waiting or delivery accordingly. Use user time expectations to organize useful
> milestones without inventing a hard task deadline.

This is a design sketch, not an installed prompt or validated improvement. Existing
prompts already express many of these ideas. The audit suggests that simply adding
"check the actual state" again is unlikely to address the whole problem: the model
had just checked it. A clearer current-state context, evidence relations and fewer
competing instructions should be tested as separate changes.

Do not turn every important action into another required planner/reviewer call.
Do not treat all historical observations as current findings. Keep exact owner
constraints available without copying equivalent descriptions into every field.
Prioritize the state needed for the current decision, with access to retained detail.

## 6. How to test the proposed simplification later

Use the exact retained handoff input as one diagnostic replay input, then add fresh
controls. Compare original context, a state-focused context with the same authority
and capabilities, and any wording change separately. Keep Luna/max fixed. Include
an actual commit mismatch and an unchanged commit with changed external conditions
so that a policy cannot pass merely by always declaring continuity.

Measure the accuracy of state claims, the usefulness of selected work and whether
relevant checks are preserved. Such replay diagnoses context use; it does not
establish end-to-end task quality. Subsequent ProContract E2E comparisons on a fixed
repaired harness must test final/intermediate results, resource use and transfer
to connected or open-ended tasks. No replay or new model run was launched here.

The consolidated repair record remains
[publication lifecycle and continuity](procontract-publication-lifecycle-20261026.md).
This audit adds no confirmed workspace rollback defect and changes no frozen result.
