# GPT-6-Luna: ProContract and native Codex with goals

The requested comparison adds 200 independent ProgramBench tasks per arm using
`gpt-6-luna` at `max`. ProContract uses the native build at
`c2130fc07a670cf43129bc62d2c2017010a19dde`, including the argv boundary repair.
The baseline uses the unmodified Codex 0.167.0 Linux musl release, pinned locally
with its resources, code-mode host and standalone exec-server.

Each task has one six-hour solver allocation, unlimited model requests across
all roles, offline execution, 20 CPUs, 60 GiB, UID1000, a 180-second process
lifetime and the benchmark's 5,000-character output head and tail. Both arms use
the same original image digests, task order, task prompt and corrected grading
profile. Each has a fresh workspace. Official tests and scorer remain pinned.
The two arms are interleaved under the existing shared capacity16. Existing Sol
attempts keep their original allocations.

## Native goal activation

The driver arms the external allocation, starts the complete benchmark prompt,
then immediately calls `thread/goal/set` with an active user-authorized objective
and `tokenBudget: null`. It verifies persistence with `thread/goal/get`. Codex
owns all subsequent continuation. The driver observes the persisted goal and
drains its final native turn before stopping; it never treats an idle ordinary
turn as completion and never supplies synthetic “continue” prompts.

The real GPT-6-Luna/max qualification completed two ordinary turns. The first
wrote `step1.txt`; native goal continuation started the second, which wrote
`step2.txt` and completed the goal. Seven model requests retained the exact
`gpt-6-luna`/`max` response identity. The isolated baseline trajectory contained
no ProContract policy, tools or workspace working agreement.

## Common execution boundary

[`benchmark_exec_limit.py`](../../scripts/benchmark_exec_limit.py) forwards the
native JSON-RPC stream and sends `process/terminate` at the original admitted
process deadline. Reads and writes cannot renew that deadline. Executor argv,
file calls, process output and normal notifications remain native. Timeout
receipts are retained separately. Both arms use this adapter; neither executable
is patched to implement the benchmark restriction.

A real unmodified exec-server passed both short and 180-second checks: a long
command and its child stopped, an intervening read did not extend its lifetime,
failed launches retained their error, and a subsequent command succeeded on the
same server. Internal termination responses did not leak into the client RPC
stream. Four goal-lifecycle tests cover continuation, final-turn draining,
missing-goal failure and baseline feature selection.

The retained ProgramBench preparation controls collected the exact eligible
sets for hex (823) and lazygit (855), verified UID1000 and network isolation,
and executed each arm's own binary inside its image. These preparations made no
solver model calls.

## ProContract qualification and deferred RSI evidence

The ProContract qualification exercised GPT-6-Luna/max root and worker calls,
an issued contract, offline execution, artifact publication and independent
review. It produced the exact requested `42\n` file. The initial test fixture
had an invalid capture label; that fixture was corrected and its failed record
retained before any benchmark allocation.

The corrected capability test also exposed an existing strategy cost: review
kept asking for stronger evidence of the *action sequence* after the file and
required runtime observations were already correct. The operator ended this
capability observation after retaining the publication/review record. This
qualifies the exercised transport and capabilities, not settlement or Support.
Artifact success and review overhead are separate observations. This goes into
the post-comparison RSI backlog; it does not trigger a mid-cohort strategy change.

## Records and next analysis

The durable study root is
`/data/ProContract/programbench-gpt6-luna-20261106/`; its `procontract` and
`vanilla-goal` children retain independent frozen plans, packages, allocations,
raw trajectories, submissions and scores. A shared scheduler records admission
changes outside the frozen solver plans. Public deployment snapshots are under
[`gpt6-luna-20261106/`](gpt6-luna-20261106/).

Report valid scored counts, mean test pass rate, tasks at or above95%, and fully
resolved tasks separately. Retain artifact scores from interrupted API/settings
runs while excluding those invalid attempts from valid instance coverage. A
genuine low artifact score remains an outcome. No best-of score replacement.

After collection, deep RSI will compare paired behavioral outcomes and
trajectories: what produced durable progress, what lost it, what caused wasted
effort, and which capabilities or replaceable strategy instructions address the
cause. Retained knowledge does not automatically install a candidate. Kernel
changes require a missing general progress/responsibility relation; workflow
changes belong to strategy, execution capabilities to harness.

Official model sources fetched for this study:

- <https://developers.openai.com/api/docs/models/gpt-6-luna>
- <https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart>
