# ProContract architecture

For ProContract work, follow the user's architecture definitions in
[docs/PROCONTRACT_LAYERS.md](docs/PROCONTRACT_LAYERS.md):

- **Two components**, per the user's 2026-11-07 decision: ProContract kernel and
  an evolvable harness. Strategy is an internal harness component.
- **Kernel** contains domain-independent responsibility, task progress/lifecycle
  semantics and authorized transitions, including RSI improvement responsibilities.
  Ordinary work and self-improvement use the same kernel; empirical workflow
  heuristics do not become kernel invariants.
- **Harness** contains execution, context management/retrieval, tools, measurement,
  observability, version delivery and a replaceable strategy/instruction library.
  It implements concrete process execution/cancellation and actual resource limits.
- **Strategy library** contains prompts, skills and other supplied context,
  including how to compose and orchestrate task and research workflows. Keep its
  choices decoupled from the harness mechanisms that execute them.
- **RSI** uses kernel responsibility, progress, evidence bindings and authorized
  adoption. Harness capabilities and strategy perform analysis, propose changes,
  run experiments and deploy selected versions. No separate RSI kernel is needed.
- **Time**: a task may have no hard deadline. User time expectations guide strategy;
  explicit user/benchmark/environment resource limits constrain execution. Durable
  progress, continuation and cancellation must not depend on a finite global
  countdown. Existing mandatory task-lifetime assumptions are migration work.

Keep the kernel/harness boundary explicit and the harness's strategy and mechanisms
decoupled. Choosing when to diagnose, review, hand off, change methods, or replay
checks belongs to strategy; harness mechanisms implement those operations. Moving
a hard-coded workflow into a configuration file does not, by itself, make it a
context-level strategy. Existing coupling is migration work, not a precedent for
new coupling. This architecture decision does not change frozen experiment inputs.

Benchmark preference, 2026-10-24: validate ProContract only by default. Do not add
native Codex comparison runs. If a native or remote Codex comparison is explicitly
requested later, actually enable and verify `/goal` under comparable resources.
Previous OFF attempts used ordinary turns without `/goal`; retain their raw
results as historical observations and state this limitation rather than using
them to claim long-horizon superiority.

Resource update, 2026-10-25: the new ProgramBench study uses independent attempts
for all 200 instances, GPT-5.6-Luna/max, one shared six-hour solver deadline and
no total model-request ceiling. Preserve accounting across roles and keep the old
1000-request cohort separate. Do not resume graded solvers or present the new
time-only study as resource-matched to Vals. Execution remains offline, with the
declared command/environment limits.

Concurrency update, 2026-11-01: the user authorized raising the active campaign
from four to eight/sixteen concurrent cases. Record the effective admission target
and changes separately from the frozen solver plan. This scheduling change does
not renew/restart attempts or change their six-hour grants, request accounting,
model/effort, network isolation or command/environment limits.

Completion update, 2026-11-01: the user authorized offline environment repair and
completion runs for this round's failures. Track the live completion list and
combined projection in `/data/ProContract/programbench-completion-20261101/`.
Never-started cases get first solver admissions; stopped artifacts get scoring
recovery without renewed solver budgets. A separately selected independent retry
(currently stgit) retains its original attempt and stays outside the original
first-attempt aggregate. Keep all original raw failures/results and the frozen
solver package. Shared admission capacity includes both original and completion jobs.

Sol cohort update, 2026-11-04: the user requested GPT-6.1 Sol after the general
trajectory-derived harness/strategy improvements. The independent full 200-task
cohort is `/data/ProContract/programbench-sol61-20261104/`: `gpt-6.1-sol`/max for all
roles, ProContract only, six hours per solver, unlimited requests, offline execution.
The prior Luna runs remain separate and unchanged; live retries share admission
capacity without renewed grants. Record capacity separately from the frozen plan.
Retain the resource difference from Vals' 1000 steps and distinguish mean test pass
rate, >=95% tasks and fully resolved tasks. The reused benchmark does not establish
held-out generalization.

Grading calibration update, 2026-11-05: independent artifact-only measurements live
under `/data/ProContract/programbench-sol61-grading-calibration-20261105/`. Solver
and compile isolation remain intact; testing uses the pinned evaluator's separately
qualified network conditions. Keep original Sol artifacts/budgets/raw scores and
the frozen solver plan unchanged. Dog's same archive and binary measured36.77%
versus96.46% across the two grading profiles; this is a measurement correction,
not a solver or strategy gain, and must not be mixed selectively into the original
aggregate. Measurement jobs share the total capacity16 through recorded scheduler
amendments. A single-result evidence-to-RSI pilot is configured; it does not yet
subscribe automatically to all campaign outcomes.

Reporting update, 2026-11-06: the user explicitly asked to stop repeating the
request-resource comparison caveat in routine updates. Report scores, coverage,
progress and concrete grading findings directly. Preserve actual protocols and
cohort lineage in experiment records without using that metadata to qualify every
positive result or withhold a defined score.

Valid-run reporting update, 2026-11-06: repair/repeat attempts invalidated by API or
settings failures and report the actual valid instance count. Ended jobs are not
valid evaluation coverage; do not headline such external failures as model zeroes.
Keep raw runs and declared retries/corrected measurements traceable. Genuine
artifact failures under a functioning environment remain outcomes; low score alone
does not justify invalidation or rerunning. Do not take the higher of old/new scores.

GPT-6-Luna comparison update, 2026-11-06: the user explicitly requested both
ProContract and vanilla Codex on `gpt-6-luna`, followed by deep RSI. The paired
study is `/data/ProContract/programbench-gpt6-luna-20261106/`, with 200 independent
tasks per arm, max effort, one six-hour allocation, unlimited counted requests,
offline execution and the declared command/environment limits. Vanilla means a
pinned unmodified Codex 0.167.0 package with actual native `/goal`; an idle ordinary
turn does not end that attempt. Both arms use the same external process-lifetime
adapter and corrected grader profile. Share the existing capacity16 without
renewing Sol allocations. Retain new insights, but do not activate RSI candidates
inside these frozen cohorts. Perform the deep comparison-driven RSI afterward.

Capacity update, 2026-11-07: after the user's request to increase concurrency and
analyze memory limits, the operator raised shared admission to24 and its available
memory reserve to64 GiB. The amendment and host/cgroup observations are retained in
`/data/ProContract/programbench-concurrency-20261107/`. This changes admission only;
preserve the existing per-instance limits, original allocations, frozen packages
and strategies. Keep the historical capacity16 records as history. A later
increase to32 requires an actual decision from subsequent capacity observations.

Luna completion update, 2026-11-07: the user authorized queueing the remaining
GPT-5.6-Luna cases. `/data/ProContract/programbench-luna56-completion-20261107/`
contains an independent six-hour/max/unlimited/offline Tparse retry after its
terminal503, and artifact-only Dog/SQLite measurements. Tparse retains the
November3 Luna policy bundle with the qualified c2130fc07 repaired native binary.
The measurements use the qualified grader bridge, two10-core branches and the
declared larger suite/measurement grants. They share capacity24; the next three
admissions are reserved outside frozen plans. `COMPLETION.json` adds only the
independently verified declared results to the frozen197-case Luna baseline.
No maximum-score selection, original-attempt resume or RSI candidate activation.

Rebuttal priority, 2026-11-07: the user made ProContract rebuttal preparation the
highest priority. Prioritize the existing experiment queues, missing valid
measurements, and reproducible rebuttal evidence. The owner-created PHP RAM
incident admission hold was lifted after exact owned release verification; this
does not renew any solve or authorize action on unrelated workloads. The PHP
measurement remains incomplete and needs bounded grader qualification before
remeasurement. Working English response modules and source-bound statistics are
under `/data/ProContract/rebuttal-20261107/`; actual review text, deadline and length
constraints were requested asynchronously. Keep new RSI candidates outside the
frozen comparative cohorts.
