# Third trajectory pass: reachable behavior, representations and continuity

2026-10-27. Analysis only; fixes remain deferred under the user's instruction to
record the evidence and repair it together later. No runtime, prompt, solver,
graded submission, original grant or score changed.

At the 01:16 UTC snapshot, the independent time-only cohort had 25/200 completed
cases, 25 valid canonical scores, four solving and 171 queued. The completed-subset
mean was 74.4197%; Vals Luna/max on those same tasks was 68.2456%, with different
request resources. Seventeen results were higher and eight lower. No preparation
failure or invalid score was present. The new five-case subset changes the aggregate;
the solver version has not changed, so this is not a new-version regression result.

| Newly completed case | Canonical score | Requests | Solve minutes | Ending |
|---|---:|---:|---:|---|
| tinycc | 302/1978 = 15.27% | 3002 | 359.83 | Original time allocation approximately consumed |
| oha | 661/892 = 74.10% | 3021 | 359.89 | Original time allocation approximately consumed |
| dua | 638/709 = 89.99% | 2089 | 239.42 | Publication left pending |
| dust | 479/584 = 82.02% | 3089 | 354.84 | Publication has an unconfirmed inspection shutdown |
| zstd | 1106/2038 = 54.27% | 536 | 100.22 | Draft worker output truncated; no Issue or continuation |

This extends the previous ten-case strategy analysis to fifteen inspected cases.
The purposeful sample supports mechanism diagnosis, not a randomized comparison
or a claim about the unfinished full corpus. Valid good results remain good, and
the remaining failures remain in their original denominators.

## Evidence record

Artifact root: `/data/ProContract/procontract-trajectory-analysis-20261027`.

- `cohort-status.json`: timestamped cohort snapshot, separate from live summaries.
- `episodes-evidence.json`: canonical eligible outcomes, source archive hashes,
  exact choices and assessments, delivered source identities and manifest changes.
- `diagnostics.json`: publication state, internal check receipts, worker outcomes,
  output-truncation facts and native host errors.
- `trace-excerpts.json`: selected commentary/tool/event records with original
  session path, SHA-256 and line number. Commentary alone is a claim, not proof.
- `commentary-index.json` and `turn-errors.json`: searchable observations.
- `findings.json`: new or refined lessons, with prior lesson links and transfer checks.
- `analyze.py` and `diagnose.py`: read-only extraction of stopped-run facts.

Official analysis uses canonical-feedback identities and confirms each denominator.
Raw evaluator output includes excluded tests and is not counted directly. Hidden
post-run feedback stays outside active solver contexts. No new paid runs or altered
evaluations were used for this analysis.

## 1. Zstd: large experimental data broke the planning envelope

The drafting worker started at 21:15:36 UTC on October 26. At 21:29:09 it ended
with `max_output_tokens`. Its retained response contains 208,256 characters and
32,726 literal `\u0000` sequences. It is invalid JSON, ending in an unfinished
Unicode escape inside the file text of a case named `decompress-valid`.

This is an output-size boundary of one response, not the removed request-count
ceiling. The case schema already provides `text` plus `repeat` for compact repeated
fixture data, and that response uses `repeat` in earlier cases. The immediate
failure is therefore not simply absence of a way to represent repetition. Also,
calling a zero-filled file `decompress-valid` does not establish that it is a
working compressed input. Compact encoding alone would not establish its validity.

The executor continued independently until 22:55:25, roughly 100 minutes into
the original six hours, and produced the 54.27% submission. The ledger contains
intake, reference observation, probe and task delivery, but no Draft, Issue or
continuation decision. `controller/runtime.rs::draft` turns a draft-worker error
directly into `abstained`; the current selection path still requires issued terms.
No damaged JSON should be admitted as valid terms, but that restriction need not
erase the original authorized task's ability to continue.

General lessons to test:

- Separate the purpose of a planning message from the bulk data used by an
  experiment. Use available compact generation or retained references where
  suitable; validate that the generated material exercises the intended path.
- A partially failed auxiliary operation should retain its actual outcome and
  leave an inspectable disposition for the underlying work. Planning, tool output
  and verification can each fail without deciding the value of retained work.
- Preserve independently valid products of an operation without admitting an
  invalid obligation envelope or inventing new authority. The appropriate retry,
  narrower request, alternative method or wait remains a strategy choice.

The context-level representation choice is strategy work. Durable outcome handling
and decision access before Issue are harness work, already part of the unfinished
continuity design. The kernel needs no special transition for a large JSON reply.

## 2. Oha supplies a real-model continuity success

Oha's root executor ended at 15:53:38 with the same provider reason,
`max_output_tokens`. Its ledger records interrupted_snapshot at event 13,
work_ready at 14 and a successor choice at 15. It then continued under the same
grant, using 3021 requests overall, and ran for approximately six hours.

This is concrete evidence that the existing executor-interruption path works in
a real model trajectory. It does not identify the counterfactual score without
recovery. Zstd shows the remaining role/stage asymmetry: the same broad output
failure on the draft worker does not reach an equivalent next decision.

Record this with the lifecycle repair, rather than adding separate retry rules for
root, reviewer and drafter errors. A consistent operation outcome and original
authority should be available to the appropriate continuation strategy at each
boundary. Some unknown effects still require actual reconciliation; confirmed
worker failure is not a new resource grant or a task success claim.

## 3. Tinycc: passing case names concealed an unreachable intended path

All eight recorded full-verification runs report 39/39 public comparisons passing.
Only 17 of those reference invocations exit zero. In particular, all ten public
`run-*` comparisons return reference exit 1. The frozen `run-hello` source includes
stdio and returns zero after printing, so its observed failure is not evidence
that the intended successful compile/run behavior was exercised.

Early executor tool output at 15:08:11–15:08:23 records missing `runmain.o`,
`libtcc1.a` and `stddef.h` on normal reference invocations. Other paths, including
compile-only and some no-standard-library/relocatable paths, do work. The passing
comparisons are real agreement on observed behavior; their coverage is narrower
than names such as run-hello suggest. Whether the missing runtime originated in
the supplied image or reference provisioning needs separate qualification; this
analysis does not attribute it to binary relocation or change the evaluator.

There is also a concrete implementation limit. The final `tcc.py` uses a small
regex-based function/expression recognizer and ELF writer. Unknown identifiers in
its constant evaluator become zero; unsupported assembly instructions may become
NOP placeholders. The canonical result includes 0/83 in the codegen test group,
2/75 run-mode, and 1/60 linking. Those groups include diagnostics as well as
execution, so their totals are not counts of one specific compiler defect.

The internal sealed tally improves from 30/81 to 62/81. This is genuine improvement
on that internal sample, coexisting with a 15.27% external result. Neither fact
should erase the other. The late choice to repair include_next addresses a real
residual, but broad compiler semantics remain limited.

Transfer: when defining a useful end-to-end slice, identify the actual outcome it
must reach. A failed login does not exercise the protected operation, an empty
dataset does not exercise a scientific pipeline, and a proof that parses has not
necessarily established its claim. Check the relevant conditions when uncertain;
do not add a universal minimum-success count or dismiss failure-path evidence.

Strategy should consider whether improving the observation environment or the
implementation's representation changes the attainable outcome more than another
local patch. Harness should expose actual conditions and preserve reference
capabilities. The cost/benefit of a larger compiler implementation in six hours is
not established by this single case.

## 4. Dua: preserve good mechanisms and keep partial scope explicit

Dua achieves 89.99%, with a substantive standalone traversal implementation. Early
observations distinguish allocated blocks, apparent size, inode deduplication,
symlinks encountered inside a directory and explicitly supplied symlink roots.
The source uses inode identity and st_blocks rather than relying only on path
spelling or logical byte length. These are useful condition-specific mechanisms.

Its initial strategy statement says the likely judging surface is non-interactive
disk usage. The final `run_interactive` parses arguments/help but always returns
`Interactive mode requires a connected terminal`; it does not test whether a
terminal is connected or implement the UI. Canonical interactive groups include
0/16, 0/15, 0/5 and 0/5. This is a concrete unimplemented interface, not an invalid
overall result. Prioritizing a partial result can be sensible, but the omitted
interface must remain visible in the working model of the task.

At 21:40:55 the executor finds that `--threads 999` succeeds with no input roots,
while previously recorded explicit-root cases fail. It narrows the behavior and
requests a review of the remaining environmental uncertainty. The final helper
still embeds a threshold of 999 for the cases where it is called. This supports
a question about generalization across input and resource conditions; it does
not establish a universal reference thread limit or why every observed pool failed.

Transfer: distinguish task requirements from assumptions about the easiest or most
likely environment. A web/API view does not cover a UI, and a batch tool interface
does not remove an interactive requirement. Available PTY/browser/network/database
capabilities can change how to investigate a missing path. Observations made under
resource exhaustion should retain those conditions instead of silently becoming
an application-wide law. Finite user scope and explicit priorities remain valid
reasons to deliver a partial or intentionally narrow implementation.

## 5. Failure location and conflicting evidence guide the next experiment

Oha's canonical database group has 32 failed tests, but 30 fail through
CalledProcessError before later database assertions. Similarly, 37 of 41 rate-group
failures and 36 of 38 request-group failures include that early process failure.
Several invocations use public URLs. The final source does contain database and
rate-scheduling implementations. Therefore these group labels alone cannot
establish that every database/rate feature is absent or broken at its own stage.
Request implementation and environment availability remain alternative causes;
no result is removed, normalized or declared invalid on that basis.

At 20:52:47 the oha executor reports repeated current reference observations that
return zero and write reports, contradicting an earlier request to impose exit 101
on transport failures. It retains the disagreement instead of blindly adding the
rule. Dua similarly investigates the input dependence of the thread-pool failure.
These are useful strategy behaviors: reconstruct relevant conditions and obtain
an observation that can distinguish explanations. They do not prove the earlier
observation was fabricated or that the latest observation applies universally.

Transfer to a connected long task: locate the failing stage, preserve its partial
results, and test the earliest unresolved dependency. A payment pipeline's final
failure does not identify the payment processor if authentication never succeeded;
a research result can fail because of data selection rather than the estimator.
Changing services and resource availability make time/version/condition bindings
especially useful. History should inform the next choice without overriding new
applicable evidence by recency or authority of the speaker alone.

## 6. Existing lifecycle defects recur; their scope is recorded accurately

- Dua's final publication 28 has no progress_assessed record. The caller reports
  `cell 41 belongs to a stale code-mode host generation` at 21:45:22, followed by
  the unresolved-publication error. A contemporaneous worker records host exit 0.
  This confirms another host-generation interruption but does not yet establish
  the host's underlying exit cause or shared-lifetime hypothesis.
- Dust's publication 44 has a completed assessment with `effects_resolved=false`,
  reviewer timeout and one inspection action still recorded Running with shutdown
  unconfirmed. It repeats the earlier cancellation/finalization failure. Its
  354.84-minute stop leaves only about five minutes, so the lost opportunity is
  materially different from a task stopped at one hour.

The 25-case snapshot now has 12 publication-blocked endings, plus caps-log's
confirmed action timeout, tparse's reviewer transport failure and zstd's draft
failure. Nine cases approximately use their full original allocation and jot
rests by strategy choice. Keep artifact quality and execution defects separate.

## Refinement of the general strategy proposal

This pass strengthens existing lessons about observation preconditions, attention
beyond a visible residual, transfer scope and usable evidence. It adds concrete
planning-envelope and environment-condition examples rather than another mandatory
workflow for each program.

For general tasks, maintain enough context to answer: what outcome is wanted,
which parts are actually usable, which path an observation reached, which conditions
make it applicable, which dependency or representation currently limits progress,
and which available resource can change the next decision. That resource may be a
document, tool, service, library, computation, collaborator or a later external
event. Absence of a deadline does not require endless activity; useful delivery,
continuation, waiting and completion should follow the task and its actual limits.

When planning output is large, retain/generate data through suitable capabilities
and keep the selected operation independently recoverable. When feedback is sparse
or conditional, describe the observed scope without shrinking the user's request.
When evidence conflicts, choose a discriminating observation. These are strategy
judgments, with no universal sample, retry, response-length or review-count rule
added to the kernel.

Later validation should include a malformed or truncated planner result while the
executor has useful work; an environment where a superficially passing test never
reaches its intended path; a real interactive success path; changed external service
conditions; and a task where existing resources remove the need for reimplementation.
Use the fixed repaired harness to compare strategy variants, retaining controls
where further exploration is unnecessary. No such new experiments were launched
in this pass.

## Subsequent interpretation audit

The [reflection pass](procontract-reflection-20261027.md) checks several executor
comments about an older checkout against native delivery/tool/context records.
The named commits match the immediately preceding delivery; those comments must
not be treated as confirmed workspace rollback. This does not alter the scores,
observed capability gaps or lifecycle findings above.
