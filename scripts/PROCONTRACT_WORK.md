# ProContract: responsibility, working evidence, and replaceable execution

This implementation follows `8c2a1bc1e` (evidence preparation and original-authority
recovery). It changes the native execution method and working-evidence path. Old
frozen releases and benchmark results do not describe this version's performance.

## The unit of continuity

A task persists; an executor is one bounded attempt to advance it. The host owns
the original authorization, contract, artifacts, evidence and remaining grant.
Neither conversation history nor an executor's summary is the responsibility's
source of truth.

Four responsibilities compose the system:

| Layer | Owns | May not decide |
| --- | --- | --- |
| Kernel and store | Roles, current subject and policy coordinates, support, discharge, release | Which experiment to try or whether a model is intelligent |
| Working evidence | Retained observations, exact available public receipts, registered counterexamples | New authority, policy changes, or task completion |
| Controller | Evidence preparation, capture, verification, continuation and explicit blockage | Inferring missing evidence or silently renewing a grant |
| Codex adapter | Native worker/session creation, context transport, tools, cancellation and confirmed exit | Issuing or discharging from a successor session |

The OpenCode V2 contribution is the separation between persistent responsibility
and replaceable execution. R2 contributes an operational method: consequential
unresolved observations choose discriminating experiments, coherent repairs and
replays of the original invocation and affected controls. Codex contributes the
explicit distinction between a proposed candidate, evidential support, and an
authorized settlement. These contributions do not require test-time RSI.

## Implemented behavior

`controller/ports.rs` describes the execution boundary; `native.rs` and
`successor.rs` implement it using Codex. `work.rs` constructs public evidence and
folds registered public check outcomes. `archive.rs` reads the existing immutable
verification journal and content-addressed blobs. `evidence_tool.rs` adapts that
reader to Codex, including an explicitly restricted extension registry for fresh
isolated executors. It does not enable the contract controller inside a successor.

Every verification retains a public projection before its verdict can advance
the contract. Its hash is bound into the verification event, together with the
contract, candidate generation and subject. A Defeat now identifies that committed
verification event, rather than only a shortened residual string. If evidence or
its journal cannot be committed, the controller records infrastructure blockage
and grants no Support or new executor on that result.

The model-facing `contract_read_evidence` tool has three operations:

- `index`: page through the task's retained verification records.
- `read`: recover exact UTF-8 pages of a handle from that index.
- `frontier`: list registered public checks with a failed observation and no later
  complete passing replay under the same contract revision and evidence policy.

Read access is bound by the host to one contract. The model cannot select a path,
read arbitrary blobs, or retrieve another contract's evidence. Public check
invocations and received details survive compaction, restart and more than three
successor summaries. Sealed case identities, invocations and individual outputs
are excluded before the projection is stored. Recall does not rerun a command.

The frontier is deliberately mechanical. A later green result closes only the
same registered check; omitted and unqualified checks do not erase older failures.
Results fold by candidate generation, so a late superseded verification does not
override a newer replay. The controller refuses Support while retained public
checks still lack a complete passing replay. This is a necessary consistency
condition, not a claim that registered checks cover the task.

Candidate judgment and evidence readiness are distinct. A failed public check
can defeat the candidate while the sealed reference observations are insufficient.
The Defeat is retained, and the evidence blockage is recorded separately; the
controller does not spend another executor repairing an evidence-production
failure. Existing authority, cancellation, confirmed shutdown and intake-time
budget rules still govern any continuation.

The native long-input regression exposed a necessary dependency distinction:
cases skipped after a failed build previously appeared as failed, qualified
observations even though neither program ran. They now report `blocked`. They
neither support nor defeat a behavioral claim. A build repair may continue when
the blocked checks could restore the frozen evidence minimum; an independently
insufficient reference path still blocks continuation. This optimistic feasibility
test authorizes only a bounded repair, never Support. Original failed fixtures
are retained separately from the final successful validation.

The fixed working method is supplied to the original executor after admission
and to fresh successors. It asks the executor to retain runnable probes and live
hypotheses in task-owned workspace files. The host captures those files with the
candidate. Summaries point to evidence; they do not replace it. The recent budget
lesson preview is retained for compatibility and repeated-artifact detection,
but the complete public verification history has a separate durable source.

## Deliberate boundaries

- The public archive preserves the checker's available receipts, not arbitrary
  executor tool streams. Check details already have a 4,000-byte capture limit;
  omission markers are retained and the boundary is described in every record.
- The frontier does not judge natural-language hypotheses, infer repairs from
  changed files, or automatically add tests to the frozen evidence policy.
- Review findings remain readable in the archive. They are not reduced to
  mechanically resolved check IDs.
- Historical events without public projections are not retroactively presented
  as complete public evidence. Their existing recovery and residual behavior
  remains available; new verifications produce the new records.
- The controller remains a Codex extension. The domain and adapter boundary is
  explicit, but this change does not introduce a cross-harness framework, a Pi
  backend, or a replacement model loop.
- Support remains within-reach evidence. Human settlement rights are retained.

## Validation

The regression suite exercises retained evidence beyond residual bounds and
three summaries, Unicode and NUL round trips, restart, task scoping, sealed
non-disclosure, damaged evidence, a late old verifier, and an unrelated green
batch that must not erase an earlier counterexample. It also verifies that a
candidate Defeat with an evidence blockage does not schedule another executor.

The native succession fixture requires an actual isolated Codex successor to
call `contract_read_evidence`, recover the original failed build receipt, repair
the workspace, exit, and reach Support through the same contract. It runs through
app-server, code-mode and Docker using a localhost scripted provider. Its result
is mechanism evidence, not a real-model performance or RSI result.

See `/data/ProContract/work-validation-20261015/REPORT.md` for the completed
commands and results from this checkout.

Recorded on 2026-10-15: 213 Rust tests passed (kernel 36, extension 138, store 39),
the changed build-blockage check also passed against an actual Docker container,
and package formatting plus Clippy with warnings denied passed. Three native
fixtures passed: short-request succession with evidence recall, 5,040-byte
request succession with evidence recall, and process restart followed by another
handoff under the same contract. All used local scripted provider responses;
no real-model or ProgramBench performance result was produced.
