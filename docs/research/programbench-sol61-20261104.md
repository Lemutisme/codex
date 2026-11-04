# ProgramBench Sol-6.1 cohort after trajectory absorption

The user requested GPT-6.1 Sol after incorporating the prior trajectory insights
into ProContract's harness and strategy, with Vals ProgramBench as the reference.
This is an independent 200-task cohort at
`/data/ProContract/programbench-sol61-20261104/`. It preserves the original randomized
task order and excludes previous solutions, hidden evaluator feedback and Vals
trajectories from solver context. Prior Luna runs and three live independent retries
remain separate and unchanged.

## Version and scope

The deployed package is the qualified `1ae7c0517` strategy/native implementation
with the `14215d7cb` private-grader timeout repair. Its source records and file hashes
are frozen in `source.json` and `plan.json`; development HEAD at preparation was
`67900dc8f`. Ordinary task strategy SHA256 is
`cee04464090d979772d41e3ae07aabb5a0bf10a5356e8b088783d8a78d65d4d9`.

The absorbed strategy addresses preservation of inputs and usable intermediate
artifacts, discriminating observations, meaningful execution conditions, concrete
regressions and retained diagnostic work. The harness corrections preserve owner
context, caller-selected return paths and access to actual producer outputs. These
remain context choices and execution capabilities respectively; the campaign adds
no research workflow to the progress/responsibility kernel.

The prior RSI qualification covered the full 200-case census/index, accumulated
deeper trajectory studies, native context use and artifact/validator controls.
It did not semantically inspect every recorded tool action or establish a score
gain. This cohort reuses the benchmark studied during improvement, so it is not a
held-out demonstration of generalization or an isolated causal harness comparison.

## Resources and model qualification

- `gpt-6.1-sol`, reasoning `max`, all roles, ProContract ON only.
- Each independent solver receives one 21,600-second allocation; requests have no
  count ceiling and remain counted across roles, failures and continuations.
- Offline execution, UID 1000, 20 CPUs, 60 GiB, 180-second shell lifetime, and the
  original 10,000-character head/tail text-observation profile.
- Four-hour outer grading allocation, original pinned evaluator/test sources,
  scoring function and test/retry/xdist semantics. Infrastructure assets include
  the earlier qualified offline repairs, including the Go-critic asset override.
- Admission capacity is recorded separately in `capacity.json` and
  `capacity-history.jsonl`. Preparation, solver, grading and archival jobs share
  capacity with the three still-running Luna retries. Admission changes neither
  restart attempts nor renew their allocations.

Official model documentation was checked at
<https://developers.openai.com/api/docs/models/gpt-6.1-sol>. The existing Responses
route actually returned Sol/max responses during a native ProContract tool probe.
The probe wrote and read a file inside an offline environment, exited successfully
and left no owned containers. All three charged diagnostic requests, including the
interrupted background request, remain separate from benchmark accounting.

The bundled model catalog's default context was stale. This cohort explicitly
configures the documented Codex 500,000-token context; native usage reported its
475,000-token effective window. No catalog rebuild or Luna configuration change
was needed. Probe artifacts are under
`/data/ProContract/programbench-sol61-planning-20261104/native-qualification/`.

## Deployment controls

All 200 pinned official images are cached. Each case must additionally pass exact
eligible-test collection and a native image/UID/network probe before its first
solver allocation. Preparation failures remain visible and consume no solver grant.

The deployment reads model, effort and context from the frozen plan in executor,
worker and thread configuration. The gateway checks every request's model/effort
and records actual response identities. The strategy observation hook uses the
gateway's real `reserve_with_context` entry point and retains the original and
actually forwarded developer context without changing payloads or grants.

Score publication uses the pinned evaluator Python in a separate subprocess with
explicit private-Docker PATH/executable and offline environment. This avoids the
previous inherited-environment error. The original scorer value is bound to the
task, eligible identities, frozen submission, raw evaluation, registry, pins and
adapter. Completeness and infrastructure errors remain separate. Attempts are
considered in protocol order, never selected for the highest score.

Five deployment controls passed: actual strategy/accounting hook, model mismatch,
shared capacity/resource admission, PID identity and supervisor adoption without
renewing interrupted jobs. Completed runs use verified lossless archival before
uncompressed trajectory/workspace copies are removed. Scores and submissions stay
available outside that archive.

## Vals reference

Snapshot: <https://www.vals.ai/benchmarks/programbench>, updated 2026-10-29.
Sol/max run ID is `463db0cd-1865-4c57-be1b-d23d51f5fbe8`.

| Metric | Vals Sol-6.1/max |
| --- | ---: |
| Mean task test-pass rate | 85.25% |
| Tasks at least 95% | 92/200 (46%) |
| Fully resolved | 6/200 (3%) |

All 200 heatmap task IDs match the local cohort. The public trajectory manifest
covers only 194 of those tasks; no task trajectory artifact was downloaded for
this study. The 194 published percentages agree with the full heatmap at its
reported precision. Frozen source snapshots are in the planning directory, and
`vals-reference.json` retains the complete reporting-only mapping.

Vals uses mini-SWE-agent with Valkyrie/model-library, a six-hour time limit and
1,000 steps. The user's unlimited-request preference remains in force here. Reports
must retain that resource difference and distinguish mean pass rate, at-least-95%
rate, full resolution and evaluation completeness. Partial-cohort means include
their coverage; pending measurements are not invented zeroes.

Live execution and scores: `STATUS.json`, `RESULTS.json`, and per-case immutable
allocations, request ledgers, evaluation receipts and retention records.

## First admission verification

Lazygit's first allocation began **2026-11-04 01:20:34 UTC**, with its original
deadline **07:20:34 UTC**. Its actual response identities are Sol/max, the exact
task strategy occurs in both original and forwarded developer context, and native
token usage reports the expected 475,000 effective context window. The actual
executor container has the declared network, UID, CPU and memory settings.
The recorded grant still has no request ceiling and no renewal.

After this check, combined admission capacity increased from four (three retained
Luna retries plus one Sol case) to the already authorized sixteen. The change is
recorded in `capacity-history.jsonl`; it does not edit `plan.json` or any running
allocation. See `EXECUTION_CHECK.json` for the measured first-admission evidence.
This records a real start and configuration verification, not a completed score.
