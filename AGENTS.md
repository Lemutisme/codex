# ProContract architecture

For ProContract work, follow the user's layer definitions in
[docs/PROCONTRACT_LAYERS.md](docs/PROCONTRACT_LAYERS.md):

- **Strategy** is context-level instruction: prompts, skills, and other supplied
  context, including how to compose and orchestrate the workflow.
- **Harness** is agent-control and tool-layer code. Keep it essential: expose and
  execute capabilities, retain state, and enforce actual authorization/resource
  boundaries without embedding task-solving strategy.
- **Kernel** contains the domain-independent progress/responsibility semantics
  and authorized transitions. Do not promote empirical workflow heuristics into
  kernel invariants.
- **Time**: a task may have no hard deadline. User time expectations guide strategy;
  explicit user/benchmark/environment resource limits constrain execution. Durable
  progress, continuation and cancellation must not depend on a finite global
  countdown. Existing mandatory task-lifetime assumptions are migration work.

Keep these layers decoupled. Choosing when to diagnose, review, hand off, change
methods, or replay checks belongs to strategy; implementing those operations
belongs to harness. Moving a hard-coded workflow into a configuration file does
not, by itself, make it a context-level strategy. Existing coupling is migration
work, not a precedent for new coupling.

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
