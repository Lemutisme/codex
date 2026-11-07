# Grading resources and a separate retained-artifact calibration

The user asked how many evaluations run concurrently, how many CPU cores they
receive, and whether grading can receive more resources. At inspection, three
instances were being graded: SQLite, the peco transport recovery, and `run` from
the native GPT-6-Luna arm. Grading shares the24 whole-job admission slots with
preparation and solving; there is no separate fixed grading-worker pool.

Each grading container has a10-core CPU quota. The existing frozen profile runs
one test branch at a time. Individual test workers follow each official script:
the observed peco branch uses six pytest workers, while SQLite uses `-n auto`
with the official group distribution. Compile remains offline, and testing uses
the already qualified grader bridge.

The host has60 available logical CPUs. The measured grading containers were
using roughly0.6,1.6 and0.9 cores at that instant. Peco and `run` had zero CPU
quota throttling; the inspected SQLite container had accumulated only0.058
seconds of throttling. Doubling a container's CPU quota therefore does not
address the observed long evaluation.

SQLite's retained first evaluation identified the more consequential limit.
Its small branch took31 seconds. Its large branch contains16,525 raw catalogue
tests before official exclusions; twice it reached approximately97% and was
stopped by the3,600-second suite-command limit. The test-scope receipt is emitted
at session completion, so the resulting `official_test_scope_receipt_failed`
reports follow the earlier suite timeout. Parallel branches would scarcely help
this particular case because almost all work is in one branch. More suite time
is the relevant additional resource. Other cases, such as dep-tree with12
branches, can benefit from branch parallelism.

## Implemented capability and selected pilot

The trusted grading registry now exposes two independent, pinned resource fields:

- `branch_workers`, default1, forwards the native evaluator's existing isolated
  branch concurrency capability.
- `test_suite_seconds`, default3600, bounds the suite command. It does not change
  the official test command, per-test timeouts, assertions or retries. Compile,
  setup and observation steps retain their own limits.

The selected independent calibration uses2 branches,10 CPU cores per container,
a10,800-second suite grant and a43,200-second total grading allocation. At most
one calibration instance runs at a time, using up to20 cores for simultaneous
test containers. It shares the existing total24 admissions. Candidate source,
original solver allocations and the live frozen grader packages remain unchanged.

The two subjects are the stopped native GPT-6-Luna dep-tree implementation and
the stopped Sol SQLite retry. Dep-tree supplies a previously scored comparison
for test identity, outcome vector, compiled subject and elapsed time. SQLite
tests whether the full official result can be obtained under the larger suite
allocation. Results remain separate measurements; this is not an automatic
score replacement or deployment across the ongoing cohorts.

Adapter validation:31 checks passed, with two unrelated environment-dependent
controls skipped. Checks cover retained defaults, pin drift, forwarding branch
concurrency, and keeping the exact test command and other step limits intact.
The actual artifact measurements provide the end-to-end qualification; no
speedup or result equivalence is claimed before they finish.

Deployment: `/data/ProContract/programbench-grader-resources-20261107/`.
The scheduler waits for each source job's terminal receipt before admission.
Prepared images can retain campaign labels, so overlapping a remeasurement with
the source job's cleanup would otherwise allow an old label filter to affect the
new container. The original jobs are allowed to finish normally.

This work is grading harness resource control. It adds no ProContract kernel
state, model-facing workflow rule or RSI candidate activation.
