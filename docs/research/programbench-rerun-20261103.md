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
