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

Fresh code, data and theory E2E tasks are prepared separately from the completed official
ProgramBench cohort. They use the same default strategy and mechanisms, Luna/max, frozen
inputs, one attempt each, and separate grading of retained delivery. Their actual outcomes
belong in the validation report, not in the earlier benchmark scores.

The legacy automatic Principal still performs intake, contract preparation and its
existing formal handoff workflow. This change makes strategy context and requested
diagnostic capabilities concrete; it does not claim that all old orchestration has already
moved into context. Further workflow migration must expose minimal composable operations
instead of introducing another mandatory planner, fixed workflow, or universal gate.
