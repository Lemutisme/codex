# Memory audit after increasing concurrency

The user asked whether sixteen concurrent cases exhausted memory and whether
eight would help. At 18:56 UTC the scheduler and all sixteen case processes were
live (fifteen solving, one grading); the host had about 160 GiB available RAM,
load 4.4 on 60 CPUs and zero current memory-pressure averages.

**OOM kills did occur, but the retained kernel events identify container cgroup
limits. They do not establish host-wide exhaustion caused by sixteen concurrency.**
The kernel log begins at this boot, 2026-10-31 22:32 UTC. Its 54 OOM events all
report `CONSTRAINT_MEMCG`; no global OOM kill was found in that log.

| Actual cgroup limit at the event | Kill events |
| --- | ---: |
| 2 GiB | 52 |
| 60 GiB | 1 |
| 512 MiB | 1 |

The first 2-GiB event occurred at 03:47 UTC, before the 05:10/05:12 increase from
four to eight/sixteen. A smaller concurrency target does not change those
individual limits. Increasing a task's allocation is a different decision and
would change its execution conditions; no limit or original budget was changed.

The 60-GiB event at 12:57:13 is bound to **QuickJS** by container ID
`68f0db2aa345…` in its retained executor cleanup receipt and its native `uname`
output. The killed Python process had approximately 59.85 GiB anonymous resident
memory; the cgroup's usage equaled its 60-GiB limit. A host observation less than
three seconds away still had 110.59 GiB available. This is evidence of a particular
execution consuming its own allocation, not sixteen ordinary containers jointly
exhausting the host. The exact allocation-producing command was not identified.

The 512-MiB kill at 16:18:15 has a host observation within two seconds showing
160.23 GiB available. Native inspection code has a 512-MiB cap, but the removed
historical container is not yet reliably bound to that operation. The 2-GiB
containers also need task/phase attribution. Do not infer ownership just from a
matching limit or user ID. Nine additional `__vm_enough_memory` allocation refusals
are retained separately; their requested sizes/callers have not been reconstructed.

## Eight versus sixteen: what was actually observed

| Target | Observation window / samples | Lowest sampled available RAM |
| --- | --- | ---: |
| 8 | approximately one minute / 4 samples | 143.53 GiB |
| 16 | 05:12–18:56 UTC / 834 samples | 91.00 GiB |

The sixteen-case period's highest sampled one-minute load was 26.33 on 60 CPUs.
These minute samples do not capture every transient peak, and eight was not a
matched long-duration experiment. The kernel's event classification is the direct
evidence for the observed kills. There is no current memory-pressure basis for
reducing admission capacity; it remains sixteen. Eight is an available scheduling
choice, but would not directly repair the recorded per-container overflows.

Disk headroom was tighter than RAM: its sampled minimum was 26.27 GiB, later
recovering above 140 GiB after existing job lifecycle/retention work. That is a
separate capacity observation, not an OOM explanation.

## Observation and architecture lessons

The original concurrency monitor recorded host headroom and request outcomes,
which cannot establish the absence of container OOMs. Resource observations need
their enforcement scope: host, container, action, subprocess and invocation.
Retain container identity, actual limit, peak/kill event and owning operation so
automatic removal does not erase the attribution. This fits H2/H3's existing
execution-condition and evidence-transport responsibilities; it adds no strategy
workflow or kernel quality gate.

Strategy should distinguish an intentionally stressful probe, a candidate's
unbounded allocation, and an undersized measurement operation before choosing a
repair or requesting a different grant. An OOM is not automatically a zero score,
an instruction to halve concurrency, or permission to enlarge a frozen grant.

Artifacts: `/data/ProContract/procontract-memory-audit-20261101/` contains the full
kernel log, parsed events with actual cgroup limits, nearest host observations,
monitor summaries, QuickJS bindings and `SUMMARY.json`. No inference, rerun,
container memory adjustment, solver restart or budget renewal occurred in this
audit. All existing benchmark results retain their original conditions.
