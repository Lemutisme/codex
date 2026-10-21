# Preserve independent review results and separate task limits from executor choice

A bad support citation used to reject an entire otherwise readable review. In the
October 21 ProgramBench retest, both trdsql and lnav stopped with remaining time
and requests even though their final reviewers had supplied new behavior
counterexamples. This revision retains independently valid judgments and makes
rejected support explicit. It also fixes a native continuation defect discovered
while testing the change: adding a deadline could disable an already authorized
same-thread repair when fresh executors were prohibited.

The pure responsibility kernel and store are unchanged. No benchmark attempt was
resumed, no score was replaced, and no automatic recovery or RSI coordinator was
introduced.

## Evidence from the completed runs

The original retest used `ec425914c`, GPT-5.6-Luna/max, six hours and 1000 shared
provider requests per task, and offline task containers. Results remain:

- trdsql: 1069/1312 (81.48%), versus 1059/1312 previously. Its final corrected
  review cited a static computation for an execution-scoped `process:9`, causing
  rejection of the entire response. The same response contained concrete JSON
  query counterexamples.
- lnav: 151/989 (15.27%), versus 224/989 previously. Its final correction still
  used `citation_id=e426` instead of `e426`; independently reported shell-command
  and rotated-path counterexamples were consequently unavailable for repair.
- scc: the model expanded repetitive fixture text into a roughly 1 MB incomplete
  tool call, reaching 128,000 output tokens. The submitted archive lacked
  `compile.sh`; both evaluations of that fixed archive failed to build. The
  adapter marks this invalid. It is an unsuccessful delivery, not a valid test
  score and not a sample to omit.

Both requested diagnoses timed out and retained no explicit checkpoint. A source
audit also found recommended workflows promoted to process obligations, and an
artifact dependency constraint treated as a claim about past execution. These
are representation and strategy problems, not reasons to add kernel thresholds.

The external score changes are observations across independent implementations,
not a causal ablation. In particular, lnav's public checks all passed while its
eligible SQL tests fell from 24/30 to 4/30. Local feedback convergence does not
establish interface coverage.

## Changes and boundaries

| Layer | Change | Preserved boundary |
| --- | --- | --- |
| Harness review adapter | Resolve each support binding separately; replace rejected claims with obligation-scoped gaps while retaining independent support, observations and findings | No guessed citation IDs, accepted unissued citations, artifact proof of historical actions, or false whole-task Support |
| Harness protocol | The response schema specifies exact citation syntax and separates it from explanatory observations | Issuance, subject binding and evidence scope still require host validation |
| Harness tool transport | Optional structured dynamic-tool results reach code mode as objects; ProContract supplies this representation explicitly | Legacy text remains text; the bridge never guesses whether arbitrary tool text should be parsed as JSON |
| Harness evidence reads | Invalid arguments do not spend the bounded evidence-page allowance | Successful reads remain counted; original action and task limits remain in force |
| Harness persistence | Retain raw and resolved review responses plus rejected-support records; checkpoints report local rejection and remain idempotent | A checkpoint is not final acceptance or settlement |
| Harness continuation | A deadline-only allocation with zero fresh sessions retains the separately authorized local repair allowance | The original deadline and accounting remain; an exhausted nonzero successor grant does not create extra local attempts |
| Strategy context | Classify result properties, execution actions and advice by their meaning; focus diagnosis before expanding a source audit; retain useful partial observations; generate large fixtures programmatically | No task IDs, benchmark-specific output normalization, mandatory sample count or universal timeout |

Malformed JSON, ambiguous identities and contradictory judgments still reject
the response envelope. A local citation failure now has a smaller effect: its
positive coverage is removed and the reason becomes an explicit gap. Other
judgments can proceed through the existing repair path. A gap can never count
toward Support.

The existing single same-session protocol correction is retained; this revision
does not add retries. If the corrected response still has local binding errors,
its independent findings remain usable. Whole-response corruption, interruption
or unconfirmed shutdown retain their separate failure behavior. These mechanisms
do not yet constitute a replaceable autonomous recovery strategy.

The native continuation regression had an independent baseline control: the
previous qualified binary failed the same finite-deadline case. The configuration
stored task lifetime in `succession`; the controller interpreted the existence of
that allocation as a choice to launch a successor. With `max_sessions=0`, it
rested instead of using the existing repair allowance. The fix distinguishes
fresh-executor authorization from task resource accounting, checks the remaining
original allocation, and fences stale repair dispatch after owner input.

## Engineering validation

- 216 extension Rust tests pass, including partial binding rejection without
  false support, independent finding retention, checkpoint idempotency, and a
  finite original grant that permits local repair but no new executor.
- A targeted Codex core test verifies structured values reach code mode while
  legacy JSON-looking text and direct model-visible content remain unchanged.
- Targeted Clippy with warnings denied and production binary builds pass.
- 12 Python configuration tests pass, including preservation of original limits
  and task identity across reopening and strategy changes.
- Ten final-build native controls pass: structured evidence paging with recovery from invalid
  arguments, malformed local citation through real
  review/repair with and without a task deadline; same-session protocol correction;
  unresolved malformed envelopes without additional retries; ordinary partial
  review repair; open-ended succession; deadline shutdown of running effects;
  actual frozen computation and cross-obligation citation use.
- An eleventh final-build native E2E passes, verifying checkpoint persistence across timeout, continuation
  without replaying unchanged checks, and fresh checks after the subject changes.

The local-binding fault controls deliberately leave the second obligation
unsupported. The first artifact is actually repaired; the contract records one
Issue and `propose, defeat, propose`, with no Support. The finite control retains
its 120-second deadline and zero fresh launches. This verifies useful progress
without laundering the remaining gap.

Initial test failures, the baseline continuation failure and the first Clippy
rejections remain in separate logs. The two new parser/control regressions were
not addressed by raising limits or suppressing tests.

## Real-model E2E observations

Two independent synthetic tasks are separately frozen, with one solve each. All
model roles use GPT-5.6-Luna/max; task containers are offline. Native and gateway
task deadlines are absent. Each qualification supervisor has a declared
1800-second watchdog, separate from task semantics. These are engineering
qualifications, not ProgramBench scores or evidence of a leaderboard gain.

The transaction-store task exercises nested transactions, compare-and-swap,
atomic batches and continued execution after errors. Its delivered artifact
passed all 32 frozen external scenarios (802 operations), using 16 requests in
about 353 seconds. The drafter encountered an upstream model-capacity error
before Issue, so there was no ProContract review/repair cycle and internal
Support is false. The artifact result is valid; the initialization failure is
also retained. This run used the initial build before the separately discovered
deadline-only continuation fix.

The intermediate-build interval-algebra task includes a requested focused independent
diagnosis and 209 frozen external checks, including very large coordinates.
Its delivered artifact passed 209/209 with a zero process exit and no extra output
lines, using 36 requests in about 520 seconds. Its requested diagnosis was focused,
but the model-selected 30-second allocation timed out without an explicit checkpoint.
Formal review returned a protocol-valid unresolved result and internal Support is
false. This does not invalidate the successful artifact result.

Inspecting that final review exposed another concrete transport defect. The model
used `const r = await tools.read_evidence(...)`, then `r.eof` and `r.next_offset`.
The dynamic-tool bridge returned a JSON **string**, not an object. The first page
was readable as displayed text, but the loop's next cursor became undefined; the
model sent repeated requests without an offset and exhausted the 4096-call read
allowance. It then could not read terms or computation results and described every
obligation as unresolved. This was not evidence that the delivered calculator was
bad or that ordinary software acceptance required a new proof threshold.

The final transport change adds an optional structured result to the internal
dynamic-tool response. Code mode receives that explicit object; direct consumers
retain the original text view. Other tools opt in rather than having their text
silently reinterpreted. ProContract supplies the same bounded object in both views.
The same pagination pattern is exercised by a native regression, and malformed
arguments no longer consume evidence pages. Neither successful inference attempts
nor dispatched computations are refunded.

A separately frozen post-run control reuses the existing interval artifact and
recorded draft in a new read-only diagnostic task. Its drafter and executor are
scripted; only the reviewer uses real Luna/max. It requests the focused difference
question with a 300-second assessment allocation and a separate 450-second supervisor
watchdog. This is an interface qualification with developer exposure, not a new
solve, a resumed benchmark attempt, a causal latency comparison or a replacement
score. This control completed in about 170 seconds with 14 real Luna/max requests,
all completed. It retained two explicit checkpoints and its final partial review
passed protocol validation on the first submission; the diagnostic receipt reached
the executor. The trajectory audit also retains two rejected checkpoint calls
(wrong nesting and a map where an observation string was required). The model
corrected both within the same assessment. These were recoverable tool errors,
so this control is not evidence of zero malformed model invocations.
The reviewer observed correct behavior for spanning and touching intervals and
reported no mismatch in 65,536 bounded pair comparisons. Its positive local
observation is useful; other obligations were outside this focused assessment.
No whole-task Support was claimed by the control. The source, original result
and frozen control inputs remained unchanged.

## Remaining architectural work

The legacy Principal still selects final verification, one protocol correction,
repair/succession and resting through code. This revision repairs the meaning of
existing interfaces and grants; it does not claim that all workflow choices have
moved to context-level strategy. Drafting failure recovery, execution interruption,
and whole-response protocol failure still need deliberate continuation through
the original responsibility and allocation.

Useful early diagnosis is not guaranteed by the existence of `record_review`.
Scope, inference latency, tool work and the executor's chosen action allocation
remain relevant. Better behavioral coverage also remains a strategy question;
passing a retained matrix does not remove unexplored states or interactions.
The successful read-only control uses a different allocation and purpose from
the earlier all-model solve. It establishes that the repaired transport can carry
real diagnostic work, not that all 30-second diagnoses now succeed or that a new
full benchmark cohort will improve.

Artifacts: `/data/ProContract/procontract-local-review-evolution-20261021`.
Original cohort analysis:
`/data/ProContract/programbench-trajectory-retest-20261021/post-run-analysis`.
