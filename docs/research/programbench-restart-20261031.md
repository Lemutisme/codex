# ProgramBench restart recovery and new trajectory observations

The host reboot interrupted the fixed time-only campaign. Recovery artifacts are
retained at `/data/ProContract/programbench-recovery-20261031-2239/`; the separate
`AMENDMENT.json` identifies the recovery scheduler, scripts and exact scope.
The frozen solver, prompts, model, evaluator code, tests and resource plan remain
unchanged: 200 independent ProContract attempts, GPT-5.6-Luna/max, six hours per
solver, no request ceiling, offline solvers and four total case slots.

## Recovery facts

The stale 197/200 count was terminal job records, not 197 completed solves.
Before the reboot, a missing shared evaluator interpreter caused 66 cases to fail
before solver admission. Doxygen separately completed its solve but could not
launch its evaluator. The cause of the virtualenv deletion is unknown. It must
not be attributed to another agent or to the reboot without evidence.

All 766 files pinned by the plan were verified unchanged. The plan SHA-256 is
`7f694155be16732e4c21d291120a08a43733e1b7ef50702e54333cdadf20ba78`.
The evaluator virtualenv was restored from its existing lockfile and cached
packages with `uv sync --locked --no-dev --offline`; imports passed. Its restored
Python is 3.13.14; the earlier interpreter patch identity was not established.
The campaign Docker daemon was restarted with its original data root and options.

Every one of the 66 preparation failures was checked for absence of a solver
launch, allocator, workspace and terminal solve result. Their directories were
moved intact into the recovery archive, with every retained file hash verified.
They receive fresh preparation for their original first solve. Six earlier,
distinct preparation failures remain recorded and are excluded from this retry.

Three launched, ungraded solvers had lost their processes. Their original request
counts are 2285, 1582 and 1249, including one unfinished request each. Original
starts/deadlines and accounting were read without arming a new allocation.
Confirmed stopped workspaces were packaged and scored with the original canonical
evaluator. No inference, fresh solver or renewed six-hour allocation was used.

| Interrupted artifact | Canonical result | Requests already spent |
| --- | ---: | ---: |
| deadnix | 582/602 = 96.68% | 2285 |
| yj | 684/767 = 89.18% | 1582 |
| blake3 | 642/647 = 99.23% | 1249 |

These are strong retained artifact results. Their interruptions remain explicit;
the report presents both all valid artifact scores and the uninterrupted subset.
Doxygen's first actual evaluation uses its existing frozen submission and writes
a supplemental result. Its original evaluator-start failure is preserved.

The independent recovery scheduler counts recovery grading and new work against
the same four slots. Before each admission it checks the evaluator executable and
imports, Docker, the model route and the original disk reserve. Missing shared
prerequisites pause admissions. Frozen preparation, solving and grading code are
not edited. Terminal evidence survives recovery cleanup errors. Reporting now
distinguishes interrupted scoring, preparation failure and terminal finalization
failure; dutree is no longer presented as a live grading process.

At 22:51 UTC, all three interrupted artifacts had valid scores; stgit, ripgrep
and serpl were solving, and doxygen occupied the fourth slot for grading.
There were 124 valid scores, mean 76.8736%; the 121 uninterrupted valid scores
had mean 76.4235%. This is an incomplete local cohort under the recorded evaluator
conditions, not an official leaderboard submission. Vals has different request
resources. Consult the live recovery `status.json` for subsequent progress.

## New stopped trajectory: xq

The original xq attempt scored **714/792 = 90.1515%**, compared with the retained
Vals Luna/max reference of 86.74%. It used 2882 requests under its original
six-hour allocation. No causal attribution to extra compute or ProContract follows
from this single comparison.

The final implementation has a node representation, markup parsing, XML/HTML
formatting, XPath/CSS traversal and XML-to-JSON conversion. Its complete internal
comparison receipts improve 61/63 → 62/63 → 63/63. Six later/full observations
including the first all-pass receipt retain 63/63. Independent review nevertheless
finds further behavior differences: CDATA whitespace, declaration-only trailing
newlines, DOCTYPE formatting and processing-instruction behavior. This is evidence
that new discriminating observations can add value after a fixed sample saturates;
it does not imply that every repeated full review was useful.

External residuals expose a broader omitted input channel. Thirty failed assertion
names involve configuration. The retained evaluator trace shows `.xq` files in a
temporary HOME supplying indentation, tabs and related settings. The candidate
initializes options from defaults and command-line arguments, with no `.xq` loading
path. A small stopped-candidate replay confirms that `indent = 4` in HOME/.xq has
no effect, while the explicit `--indent 4` option changes the output correctly.
This locates a missing configuration-input mechanism for that observation; it does
not claim to independently explain all 30 assertions or all 78 residual failures.

Evidence is retained in `trajectory-xq/analysis.json`, the copied ledger/source,
original feedback and result hashes. Source SHA-256:
`2681f01ac16c50686467421f4973b9be8b6d49b2b08a24b461c07a93d4f22dc6`.
The replay used host Python on the stopped source with a temporary HOME; it was
neither new solver inference nor official regrading. No hidden test feedback was
given to live solvers. This analysis also does not establish whether that input
channel was discoverable from the particular initial documentation alone.

## General implications, retaining the existing layer boundaries

- **H1, durable execution:** a result belongs to an admitted operation, not the
  process that happened to observe it. Reconcile interrupted effects and preserve
  partial work, original authority and accounting. A missing terminal record does
  not establish absence of work or authorize a fresh attempt.
- **H2, applicable conditions:** a failed shared prerequisite is an environment
  observation. Check the dependency before admitting work that requires it, and
  preserve the distinction between inability to execute and poor task quality.
  No retry-count policy or new kernel state is required.
- **S1/S2, useful coverage:** when observations saturate, strategy can reconsider
  its model of the task's inputs and state. Command-line cases do not establish
  behavior under configuration, persistent state, environment or external events.
  Which additional channel matters depends on the task; do not install a universal
  test count, mandatory audit sequence or domain checklist in harness.
- **S3, cumulative learning:** retain successful representations and repairs,
  alongside versioned counterexamples and their conditions. Strong artifact
  quality, incomplete acceptance and interrupted execution remain separate facts.

The current failures and successes fit H1–H3/S1–S3. They do not justify another
responsibility kernel or a scalar reward that combines missing measurements,
internal Support, cost and user-facing quality.
