# Three independent ProgramBench retries

The user explicitly requested rerunning jsonschema, SQLite and stgit after their
scoring anomalies. The new run directory is
`/data/ProContract/programbench-rerun-20261103/`. Each is a new independent attempt
using the latest qualified ProContract task strategy, GPT-5.6-Luna/max, one shared
six-hour solver allocation, unlimited requests and offline execution. Prior artifacts,
failures and scores remain unchanged; the new results are separate from the original
200-case first-attempt aggregate. Solvers receive only the original task interface,
reference executable and bundled documentation.

## Prior observations

- Jsonschema's original scorer value is 1766/2932 (60.23%). The supplied fail-fast
  test command stopped after a candidate assertion failure; 1089 tests were recorded
  `not_run`. The added strict-completeness view rejected that measurement, but the
  benchmark-defined scalar remains a real reported value.
- Original stgit caused a module-collection failure by rejecting a command used for
  dynamic test discovery. A separately retained retry has a scorer value 938/1488
  (63.04%) with 50 `not_run` records. It does not replace the original attempt.
- SQLite reached its supplied 3600-second test-command limit. A separate executor
  cleanup defect then stopped its private grader container, preventing collection of
  retained test observations. Repeated grading exhausted the four-hour outer allocation.
  These are distinct stages, not one inferred artifact-quality verdict.

## Confirmed execution repair

The pinned evaluator starts each container with `--init` and `sleep 2h`. Its timeout
cleanup used `kill -KILL -1`, assuming the keepalive was PID 1. In the actual process
layout PID 1 is Docker init and `sleep 2h` is its child. The sweep therefore killed
the keepalive as well as test processes.

A zero-model control on the actual SQLite image reproduced this in under one second:
a 0.25-second `sleep` timeout stopped the container (exit 137, no OOM), and the next
command failed with `container ... is not running`. Evidence is
`diagnosis/timeout-baseline.json` in the new run directory.

The ProContract grader adapter now captures the private environment's initial service
process identities, serializes host command calls and excludes those identities from
command-timeout cleanup. Timed-out command processes still stop; the original timeout
result and partial output remain, and subsequent observation collection can run.
The official evaluator source, assertions, test/retry/xdist policy, 3600-second batch
limit, four-hour grading allocation and existing container lifetime are unchanged.
This is a tool/execution repair; it selects no research or solver workflow.

The real container control verifies that timed-out child processes stop, the keepalive
survives, and a retained file plus the next command remain usable. Across the evaluator
and pytest-capable test environments, all 18 distinct targeted controls passed. Initial
setup errors from using an environment without installed ProgramBench metadata or the
explicit store-binary binding are retained in the diagnostic log; they are not code
failures. Final logs are `diagnosis/adapter-tests-v2.log` and
`diagnosis/pytest-controls.log`.

The new driver retains benchmark scorer values and execution-completeness/error facts
separately. It must not invent another solver attempt because a useful scorer value
also has a `not_run` flag, or merge new independent attempts into the first cohort.

## Admission and live verification

All three new cases passed actual offline native-runtime probes and exact eligible
collection: jsonschema2932, SQLite13510, stgit1488. A campaign-local Docker wrapper
initially duplicated `--network none`; this zero-inference preflight failure was
retained under `preparation-history/network-argument-v1/` and corrected before any
solver allocation began. Both explicit and default grader execution now retain
network isolation.

All three original new solver allocations began at **2026-11-03 23:37:24 UTC**;
their hard solver deadlines are **2026-11-04 05:37:24 UTC**. The native response ledger
confirms GPT-5.6-Luna/max, no request ceiling and no gateway rejection at the initial
live check. Actual solver containers use UID1000, network=none,20 CPUs and60GiB.
Their minimal mounts contain no prior solutions or grading sources.

The final task strategy (SHA256 `cee04464090d979772d41e3ae07aabb5a0bf10a5356e8b088783d8a78d65d4d9`)
is present byte-for-byte in each native session's recorded developer context.
The optional deployment payload-capture hook was attached to an unused budget entry
point and remains inactive; it is not claimed as gateway-payload evidence. Native
context observations, gateway payload hashes, request accounting and actual response
identities are retained separately. See `STRATEGY_CHECK.json` and `EXECUTION_CHECK.json`.

Scorer controls confirm that jsonschema's defined60.23% is retained despite1089
`not_run` records, and that a mismatched submission receipt is rejected. Scalar
publication runs as a separate read-only process under the explicit private-Docker
environment, preserving the original driver result. It performs no new behavioral
evaluation or model calls; live allocations and frozen solver inputs are unchanged.
The publication amendment and initial environment-setup failure are retained.

Live execution: `STATUS.json`. Separate scorer/completeness view: `SCORE_STATUS.json`.
The supervisor owns preparation-qualified jobs through solve, freeze, grading and
lossless retention. No failed solver is automatically restarted. These are independent
retries; the original200-case aggregate and earlier stgit retry remain intact.
