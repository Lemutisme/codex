# ProgramBench admission increased from16 to24

The user requested higher concurrency and an analysis of memory limits. The
shared scheduler target is now24, with64 GiB of host `MemAvailable` required
before admitting another job. The amendment changes admission capacity only.
Existing six-hour allocations, model request accounting, solver/command limits,
native goal configuration and frozen strategies remain unchanged.

## Measurements before the change

| Observation | Measured value |
|---|---:|
| Host physical RAM | 176.8 GiB |
| Host available RAM | 120.6 GiB |
| Swap | 0 |
| Active benchmark jobs | 16 |
| Current benchmark working set, including host controllers and grader | 12.8 GiB |
| Active dep-tree solver container lifetime memory peak | 18.4 GiB |
| Sol retry host service lifetime memory peak | 32.4 GiB |
| Available CPU affinity | 60 logical CPUs |
| One-minute load at the detailed observation | 22.6 |

`MemAvailable` includes reclaimable cache and is the useful admission signal.
`MemFree` alone understates usable RAM. Cgroup `memory.current` and `memory.peak`
include cache; the working-set estimate subtracts `inactive_file`. Separate
lifetime peaks are not a measured simultaneous peak and must not be summed as
though they occurred together.

The solver's60 GiB memory setting is a hard cap, not a reservation. Most live
solver containers were using tens or hundreds of MiB, with occasional much
larger compilation or execution bursts. Native Codex processes, ProContract
workers, model gateway buffers and artifact handling also consume host memory;
looking only at `docker stats` misses them. Model inference for this campaign
uses the external provider, so another task does not load another local model.

Other training/serving workloads share this machine. The host had a global OOM
episode on November6 at11:06 UTC, and later container-local OOM events. The
global episode cannot be attributed to the ProgramBench concurrency count from
these records alone. A container-local limit failure and host memory exhaustion
are different events. Retained kernel records include a candidate executable
with approximately59.8 GiB of anonymous RSS at its container-local OOM.

The current SQLite grader has no explicit Docker memory cap; it was using about
1.9 GiB of working set with a2.2 GiB lifetime charge peak. Solver limits do not
bound every grader or host process. These are measured together by the observer.
This admission amendment does not silently change the frozen grading profile.

## Why24 first

The current measurements support adding eight slots. The original16 GiB reserve
was small compared with the observed bursts and the declared60 GiB solver cap.
A64 GiB admission reserve leaves room for one such burst and controller overhead.
It is an operational headroom target, not a proof that all admitted jobs can
simultaneously approach their individual limits. When available RAM falls below
the reserve, the existing scheduler stops new admissions; it does not interrupt
running jobs or renew their allocations.

An immediate jump to32 would double concurrency while the new cohort has only a
small sample of compilation and grading peaks. CPU contention also matters:
concurrent long compilations still share60 host CPUs and retain their180-second
command deadlines. The next capacity decision should use the24-job observations,
including memory pressure, CPU pressure, API outcomes and completed-task
throughput. No automatic promotion to32 is armed.

## Retained evidence

The scheduler reached24 active jobs. Initial observations showed roughly95 GiB
available and14–16 GiB of directly attributable benchmark working set, with no
increase in the host OOM-kill counter. During the ramp, three CPU SFT processes
under `/data/rsi`, in a separate user-session cgroup, were each using about16 GiB
of RSS. Their shared pages must not be counted three times; a separate PSS
observation is retained. This concurrent workload is why admission observes
whole-host availability rather than extrapolating benchmark memory alone.

All16 pre-existing allocation records and all eight retained plan hashes matched
after reaching24 admissions. Scheduler and solver services were not restarted.
The initial sample demonstrates successful admission; compilation and grading
peaks continue to be observed before considering32.

The operational record is
`/data/ProContract/programbench-concurrency-20261107/`. A read-only systemd observer
records host memory, CPU/I/O/memory pressure, active jobs, cgroup current/peak
charges and OOM counters every30 seconds. It does not change task execution.

The amendment records the original16 live allocation hashes and eight frozen
plan hashes. Verification checks these again after the scheduler admits24 jobs.
The record and observer source are copied into
[`capacity-20261107/`](capacity-20261107/).
