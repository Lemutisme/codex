# Strategy context and general execution capabilities

This change applies the trajectory lessons without expanding the responsibility kernel.
The kernel crate is unchanged. Strategy remains prompt/context; the harness implements
the capabilities and actual task grants it uses.

## Delivered mechanisms

- `work_method.md` is a replaceable member of the context bundle, alongside worker
  prompts. Its actual text is hashed in producer identities and reaches the root's first
  request and successor context. Strategy injection no longer waits for contract intake.
- `publish_progress({request_id, review: true})` requests diagnosis even when checks fail
  or the checking method cannot produce a result. It retains scoped findings and gaps;
  it does not propose a candidate, issue Support, or settle the responsibility. Reopening
  an ID reuses that exact request. New diagnosis requests acquire their own observation
  basis; artifact-check reuse binds the policy, environment and harness identity.
- `--input NAME=FILE` provisions named read-only files outside mutable outputs. Snapshots
  retain modes and identity and remain available to executors, checks and permitted
  computations, including successors. Deleting the original host source after provisioning
  does not change the task's retained input. Capability metadata does not claim that an
  executor actually read or understood the file.
- Successor/publication count ceilings are optional. Fresh launcher tasks use the original
  deadline, without default 3/8 limits; explicit limits and existing grants remain binding.
  Deadline enforcement does not depend on enabling the progress tool. Remaining resource
  facts accompany publication results. Unchanged artifact bytes alone no longer constitute
  a hard-coded reason to prohibit a successor.
- New evidence settings do not invent quantitative acceptance criteria. Owner-supplied
  cutoffs are enforced. Historical policies retain their numeric values and missing-field
  defaults; new absent cutoffs serialize as explicit null and round-trip without acquiring
  a legacy default. Preparation failures remain observations, not automatic evidence of
  candidate defects. An absent numeric gate does not itself authorize Support.
- Reference observations retain stable channels. Variation in one channel does not erase
  the other observations. A bounded timeout is local to its case; the overall action/task
  deadline remains the resource bound. There is no global five-hang cancellation rule.

The strategy text directs preservation of usable inputs, discriminating observations,
coherent repairs, runnable regressions, diagnosis of stagnation, and honest handoffs.
There are no task-ID branches or program-specific normalizers in these mechanisms.

## Validation and scope

The development run retains source snapshots, failed attempts and qualification receipts
under `/data/ProContract/strategy-harness-evolution-20261018`.

Before real-model evaluation, 36 kernel, 186 extension, and 41 store tests passed;
19 Python tests passed; the production build and targeted Clippy passed. Actual Docker
testing verifies that a timed-out invocation does not cancel the next valid case.
Twenty-one native app-server/code-mode/Docker scenarios passed, including new tests for
requested diagnosis after a failed check, custom strategy context, input write/unlink
denial, input survival after source deletion, and successor continuity. The native test
caught a first-request strategy-injection defect; its failed run and the correction remain
recorded rather than being replaced by a later pass.

Fresh code, data and theory E2E tasks were frozen separately from the completed official
ProgramBench cohort. They use the same default strategy and mechanisms, Luna/max, frozen
inputs, one attempt each, and separate grading of retained delivery. Their actual outcomes
belong in the validation report, not in the earlier benchmark scores.

## Real-model results and what they establish

The three attempts on `13fce01e1` are complete. Each used the actual ProCodex entrypoint,
native app-server and code-mode execution, the same bundled strategy, GPT-5.6-Luna/max,
network-isolated Docker tools, and an original shared 900-second/1000-request allocation.
These are small diagnostics, not ProgramBench instances or leaderboard measurements.
All 250 frozen plan files still match their hashes. Original results remain unchanged.
There is no matched native baseline in this cohort, so the scores do not estimate a causal
performance gain or establish success on arbitrary long-horizon tasks.

| New task | Retained artifact result | Model requests | Internal Support |
|---|---|---:|---|
| Integer interval union | 40/40 frozen external cases | 64 | No: absence text was treated as an evidence gap |
| Revision ledger totals | 31/31 frozen external cases | 112 | No: same protocol problem |
| Weighted block projection | 6/6 rubric items in assistant mathematical review | 41 | Yes |

The mathematical assessment is a separate reading of the frozen proof, not formal machine
verification or independent human review. It verifies the quotient for zero weights,
well-defined linear projection, orthogonality, Pythagoras, equality conditions and the
explicit nonuniform-weight counterexample. The original pending-review result is retained;
`manual-review.json` records this later qualification and its artifact hash.

The data trajectory provides a concrete success beyond the small test score. Public checks
passed an initial implementation using ambient Decimal precision. Formal review identified
an actual exactness failure and supplied counterexamples. A successor under the same
deadline changed aggregation to integer cents. Separate posthoc checks reproduce an initial
sum of `0.99` where the exact answer is `0.00`, and confirm the repaired answer. Those checks
are labeled posthoc; they do not alter the frozen 31-case score. The decisive operation was
falsifying an implementation assumption, not raising an evidence-count threshold.

Two diagnostic reviews reached their local 120-second assessment limit, with interrupted
gateway streams. Their method limitations were retained and did not erase the artifacts.
One formal reviewer response also needed the existing protocol correction for duplicate
coverage. These observations preclude a claim of zero mechanical errors in this cohort.
All three app servers shut down normally and all natural deliveries were retained.

The absence-field defect was fixed separately in `21b7e4437`. The protocol now defines empty
lists/strings as absence and nonempty `missing` as an actual unresolved evidence gap, in
both schema and reviewer context. This convention participates in the policy identity.
There is no task-specific phrase normalization, no replacement of a real gap with Support,
and no retrospective change to a run's internal status. The 67 affected worker tests,
targeted production Clippy, formatting and native build pass.

A separate new consecutive-run encoding task on `21b7e4437` delivered 32/32 frozen cases
in 206.6 seconds and 28 requests. The absence fields were correct. Its original internal
result remains unsupported: the host rejected a check-receipt citation for an execution
obligation solely because it was not the `host_observations` document. The root trajectory
had run the checks; independently, the native checker receipt contained the configured
command and successful result. The gate prevented the reviewer from using that receipt.

The follow-on correction recognizes host check receipts as process evidence within their
actor/time scope. The summary identifies checker actions on the frozen candidate after
capture, with command output remaining untrusted data. It does not attest earlier executor
actions or comprehension. Artifact claims and fresh computations still cannot stand in for
past actions. This changes evidence transport/protocol, not the obligation or kernel; the
reviewer must still judge whether an observation establishes the requested action. The
policy identity changes with this protocol. All 188 extension tests pass. Native and live
reviewer controls are qualified separately, without rerunning any original solve.

## General lessons and remaining boundaries

The transferable relation is: retain the subject and observation conditions, make a useful
observation possible, let strategy interpret it, and carry the resulting work under the
original responsibility and grant. Domains provide the tests, assumptions and proof steps;
they do not add kernel branches. Result quality, evidence availability and permission to
settle remain separate facts.

The supplied strategy already asks for runnable regression memory. The ledger successor
executed precision checks but delivered only its implementation and summary, without a
reusable regression file. Prompt availability therefore does not establish reliable strategy
adherence. This is a strategy evaluation issue, not a reason to make every task produce a
test file or satisfy another universal kernel gate.

The fixed local assessment slice also remains visible migration work: useful reviews can
outlive it while the task still has resources. Any future change should expose resource
allocation through the capability interface and retain cancellation/accounting. Increasing
another hidden constant would not resolve ownership of that decision. This release does
not claim to have completed that migration.

The legacy automatic Principal still performs intake, contract preparation and its
existing formal handoff workflow. This change makes strategy context and requested
diagnostic capabilities concrete; it does not claim that all old orchestration has already
moved into context. Further workflow migration must expose minimal composable operations
instead of introducing another mandatory planner, fixed workflow, or universal gate.
