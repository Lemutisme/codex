# Trajectory analysis, second pass: mechanisms and transfer

Status: recorded for later consolidated work, 2026-10-26. This pass changes no
runtime, prompts, experiment allocation, submissions or scores. It extends
[the general strategy proposal](procontract-general-strategy-20261026.md) with
four more completed cases and more concrete explanations, including positive cases.

Scope: the frozen time-only ProgramBench cohort, solver `c68db7c00`, Luna/max,
one six-hour allocation and no request ceiling. The previous pass inspected six
cases; these four bring detailed strategy analysis to ten cases. They are a
purposeful diagnostic sample, not a random sample or a causal experiment.

| New case | Canonical result | Full verification choices | Diagnosis choices | Successor choices |
|---|---:|---:|---:|---:|
| muffet | 285/292 = 97.60% | 10 | 3 | 21 |
| elfcat | 529/564 = 93.79% | 7 | 7 | 26 |
| 7zip | 534/1043 = 51.20% | 7 | 7 | 14 |
| typst | 723/1724 = 41.94% | 5 | 9 | 19 |

These counts describe selected operations; a selection need not complete. All
four ran for approximately six hours. Differences in task complexity and difficulty
remain confounders; counts and scores do not establish a preferred number of reviews.

## Evidence and accounting

Artifact root: `/data/ProContract/procontract-strategy-analysis-20261026`.

- `episodes-evidence.json`: canonical scores, archive/evaluator hashes, eligible
  failure groups, exact selector decisions, assessments and captured source identities.
- `episode-trace-citations.json`: selected commentary and tool records with source
  session hash, timestamp and line number. Commentary is an agent statement;
  reported effects are checked against retained code, receipts or tool outputs.
- `trajectory-commentary-selected.json`: searchable commentary index for these
  four cases, explicitly labeled as statements rather than execution proof.
- `analyze_episodes.py`: reproducible ledger and canonical-feedback extraction.
- `lessons.json`: observations, possible mechanisms, transfer conditions and
  discriminating future checks. This is a research record, not a runtime schema.

Official failure analysis uses only identities present in canonical-feedback.json.
The raw evaluator also contains excluded tests; counting all its failures would
misrepresent the eligible denominator. No post-run evaluator data is provided to
active solvers, and no graded attempt is resumed. Internal public/sealed checks
below are the solver's own assessment machinery, not the official external tests.

## 1. A useful next step can improve the ability to observe

Muffet's retained `probe_server.py` exposes response delay, status, content type,
body, page graph and request logging. At 12:26–12:28 UTC the executor uses a local
differential matrix and reports missing srcset extraction, malformed-URL behavior
and submission-order versus completion-order collection. The final source contains
the server helper and the corresponding crawler/parser implementation. At 17:36,
retained tool results exercise a fresh build and local HTTP fixture; the executor
distinguishes exact JSON/JUnit observations from varying text order.

The mechanism worth retaining is an experiment environment with controlled inputs
that exposes meaningful behavior. Merely repeating unavailable public-network
requests would have exercised a different path. The observed 97.60% score is good;
this analysis does not attribute a specific score increment to the server helper.

Transfer: a connected task may benefit from a staging environment, a queryable
dataset, request tracing, a reproducible notebook or a small simulator. A theory
task may benefit from a counterexample generator or a finite special-case model.
Building such capability is useful when it reduces uncertainty relevant to later
choices. It can be unnecessary overhead for a simple task already well observed.

Potential check: on a fresh service task with meaningful success paths, compare
whether the strategy establishes a working observation path and uses it to change
implementation, rather than measuring only how many probes it issues.

## 2. Observations need valid preconditions and a clear interpretation

Elfcat's 22:29:33 commentary identifies an omitted e_ident byte in its synthetic
fixture generator. The earlier tool result has `32be-empty ref=101 our=0 DIFFER`;
the corrected generator's next result has `32be-empty ref=0 our=0 OK`. Other cases
still differ. The record supports correcting that particular experimental setup,
not a claim that all remaining differences were measurement errors.

Later, the 03:33:39 sweep reports 65 cases with 8 mismatches, preserving exact
boundary conditions. At 03:34:54, a fresh-build control reports that the system
matrix and a large-size fixture pass. These are examples of preserving working
behavior while investigating a specific family, without pretending that a finite
matrix proves all possible ELF behavior.

Transfer: a failed login does not test a protected workflow; a numerical result
under the wrong assumptions does not test a lemma; a missing dependency does not
test the intended pipeline. Calibrate the observation using the relevant working
precondition or a control when its validity is uncertain. The control's cost should
fit the uncertainty; a mandatory calibration count is unnecessary.

## 3. An observed-example repair and a transferable rule are different achievements

7zip's 18:15:34 executor message identifies `b"hello world\n" * 1000` from a retained
bzip2 mismatch and says it will add the observed output as a data case. The final
`sevenzip.py:1293` branch contains a dictionary of specific input bytes and output
streams, with libbz2 used outside that set. The record and code establish a local
compatibility improvement; they do not establish a general implementation of the
reference encoder's decisions.

Typst similarly retains `_smoke_pdf`, observed rendering modules and timestamp-ID
tables, alongside a real parser and a general rendering fallback. The 11:09–11:10
episode verifies the named fixture families exactly. Its canonical failures still
include datetime 0/97, introspection 0/52 and grid layout 0/49. Rendering lookup
does not explain all these failures: missing language/library functionality and
task difficulty are separate causes to investigate.

Transfer: distinguish reproducing a known observation from learning a rule expected
to hold when the task varies. A useful check changes a relevant input, composition,
assumption or environment that the repair did not explicitly enumerate. For theory,
examples can guide proof construction but do not replace a missing general argument.

Lookup tables and fixed assets are appropriate for finite catalogs, constant
resources or a legitimately finite domain. The proposed strategy is to describe
the solution's actual scope and test transfer where the requested scope needs it,
not to prohibit caching or impose a fixed number of unseen examples. The record
does not adjudicate benchmark disqualification or claim grader-data leakage.

## 4. Local feedback can draw effort away from missing capability families

7zip's last successor selection, event 3288, targets an archive-size difference
of 187 versus 188 bytes. This is a real requested difference. The final eligible
external result also contains whole weak families: CAB 0/33, volumes 0/30, BCJ
filters 0/23 and codec variants 2/36. Its independently written reader/writer has
genuine format support but a limited set of coder implementations.

Typst's late selections include a completion hint, exact render fixtures and a
pages-parser repair; larger language/library families remain absent or weak.
This supports a feedback-allocation concern: a visible small residual can become
the recurring target while the overall task model receives less attention. It
does not prove that implementing a missing family would have been feasible or
better under the same six hours. Nor does it show the executor never explored it.

Transfer: periodically compare the current residual with the user's broader
outcome, important unexamined areas, dependency bottlenecks and the feasibility
of the current representation. Use request/documentation/context to form that
view during work; post-run official test identities are not a permitted shortcut.
A different next step may acquire a library, literature result, specialist input
or stronger tool when available and authorized. The benchmark's clean-room/offline
rules remain applicable to the benchmark itself.

Potential check: fresh tasks where one obvious minor failure competes with an
unimplemented essential path. Observe the selected work and eventual user-facing
result. Include a countercondition where the minor difference is itself the
critical interoperability requirement.

## 5. Fresh snapshot identity does not identify what needs rechecking

Muffet's final two task deliveries, events 2629 and 2664, have identical source and
build-script digests. Comparing their complete stored manifests shows exactly one
changed entry: `__pycache__/muffet.cpython-310.pyc`. The later full subject is then
verified at events 2672 and 2679, following two verify choices, 2670 and 2677, on
that same full subject. Both assessments report 57/57 qualified internal sealed
comparisons passing and no concrete finding; the remaining blockers concern broad
coverage and historical/build evidence.

Elfcat's final two delivered manifests differ in `.gitignore` and a newly generated
`true.html`; its main source and compile script are unchanged. The ignore change
can matter to submission requirements even when it does not alter the parser.

The exact snapshot identities are valid. The strategy needs the change's meaning
and the relevant dependencies to choose a useful check. An unchanged artifact
can still deserve new observation; a changed file need not invalidate every
earlier result. Neither source equality nor a hash change is a complete workflow.

Transfer: retain historical evidence with its actual version/conditions, expose
changes and dependencies, and choose affected checks. A documentation edit, a
new cache file, a changed API version and a new model assumption have different
implications. Strategy may use old observations to plan work without rebinding
them as new kernel Support. Harness should expose actual differences and evidence
references; it should not hard-code that particular filenames are irrelevant.

## 6. Producing evidence and making it usable by the next decision are separate

Muffet's late tool results show a fresh archived-checkout build and local tests.
Subsequent reviews still report missing fresh-build/provenance/history evidence.
Some broad history claims cannot be established by those tests at all. A statement
that an executor ran a check also need not be a receipt accessible and appropriately
bound for that review. The observation is a mismatch between produced work and
the next assessment's usable evidence, not proof that all review gaps are false.

Repeating the build cannot resolve a missing evidence-transport path or establish
arbitrary historical facts. Strategy should identify the exact unresolved claim
and choose the evidence source/capability that could answer it. If the necessary
capability or past record is absent, retain that limitation and select other useful
authorized work or an appropriate delivery, instead of repeatedly asking the same
unanswerable question.

Transfer: a deployment needs the actual job receipt, research needs the applicable
source/derivation, and a long external workflow needs its operation identifiers.
Keep production, persistence, retrieval, interpretation and claimed scope distinct.
Harness supplies truthful storage/transport; strategy chooses and interprets it.
Kernel continues to bind admitted evidence/claims without prescribing the workflow.

## 7. Keep the means of continuing as well as the delivered product

Muffet's final `.gitignore` includes `probe_server.py`, `connect_proxy.py` and
`raw_server.py`. The retained workspace and archive preserve the observation
helper, and the final capture includes `probe_server.py`; it is not lost in this
attempt. A tracked-only checkout, however, will not carry the ignored helper.

This is a distinction between submission contents and reusable working assets.
An investigation environment, generator, failed hypothesis or proof dependency can
remain useful even when it is not part of the user's shipped product. Preserve it
with the responsibility or project context as appropriate, with enough conditions
to reproduce its role. Do not require every helper or generated result to be
committed into the deliverable, and do not treat every untracked file as disposable.

Transfer: this matters for multi-day engineering, experiments, scientific notebooks
and operations resumed after a clean deployment or another executor. A continuation
test should restore both the intended product and the selected observation assets,
then perform a genuinely new task-relevant observation.

## What to carry into general long-horizon tasks

The general strategy can maintain a compact working account of the intended useful
outcome, current artifact/world state, what has been learned and under which
conditions, open alternatives and dependencies, and available ways to act or learn.
This is a useful way to assemble context, not a required universal document,
ontology or numeric progress measure.

Before a consequential new step, compare the expected change in delivery or
decision quality with its cost and opportunity cost. Sometimes that favors direct
implementation; sometimes information gathering, capability acquisition, a broader
experiment, focused review, a useful partial delivery or waiting. Routine tool calls
do not require a new model planner, and no fixed phase sequence follows from these
examples. Additional compute is useful only insofar as its results are integrated
into the continuing task.

| Transfer setting | Strategy question to validate | Conditions that must remain explicit |
|---|---|---|
| Connected software maintenance | Can an existing library, current primary documentation or a staging probe remove the bottleneck? | Versions, actual access, dependency behavior and deployment objective |
| Mathematical/research work | Does the step establish a missing dependency, distinguish conjectures or test a reduction's assumptions? | Proof versus numerical exploration, source provenance and theorem scope |
| External service/job orchestration | What operation is already admitted, what result is awaited, and what can proceed independently? | Operation identity, known effects, user authority and wake condition |
| Changing data or environment | Which previous observations still apply after the observed change? | Input/data versions, observation time and relevant dependencies |
| Open-ended user task | What useful result should be delivered next, and what justifies continued work or waiting? | User expectations separated from actual hard grants; no invented deadline |

These connected/open-ended scenarios are extrapolations to test, not outcomes of
the offline corpus. More resources expand strategy options; they do not remove
the need to select, integrate and retain useful results. A narrowly scoped task
may need little exploration. A hard correctness requirement still needs its stated
evidence. A finite-scope delivery can be complete without exhausting all imaginable
improvements.

## Consolidated work and validation

Keep [the recorded lifecycle repair](procontract-publication-lifecycle-20261026.md)
separate from these method hypotheses. A prompt cannot supply durable finalization,
event waiting or evidence access that the harness does not expose.

For strategy revisions, prefer a short, coherent common context and selectively
loaded domain methods over appending a warning for each incident. Observe whether
the chosen method changes when its result fails to answer the question. Use fresh
inputs and domains to test transfer; retain controls where existing evidence is
adequate, repeating a check is justified, or stopping/waiting is appropriate.

Each lesson record links local observations to a proposed mechanism, its scope and
a future discriminating check. Later RSI can propose and compare such changes,
but the existence of a lesson is not evidence that its proposed prompt change wins.
No new benchmark runs, external actions or automatic strategy adoption were launched
by this analysis pass.
