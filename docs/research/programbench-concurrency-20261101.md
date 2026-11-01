# ProgramBench admission capacity: 4 → 8 → 16

On 2026-11-01 the user authorized trying eight/sixteen concurrent cases because
CPU and memory had substantial headroom. The recovery scheduler now reads a
separate authorized capacity target. Its original frozen plan and 766 pinned
solver/evaluator inputs remain unchanged. This is an explicit scheduling amendment;
the concurrency history is retained rather than claiming unchanged host load.

Artifacts: `/data/ProContract/programbench-concurrency-20261101/`.
The effective target is in
`/data/ProContract/programbench-recovery-20261031-2239/capacity.json`;
`capacity-events.jsonl` records when each target took effect.
`AMENDMENT.v2.json` and `supervise_recovery.v2.py` preserve the preceding scheduler.

At the initial inspection the host exposed 60 CPUs, load 4.52, approximately
145 GiB available memory and 167 GiB free disk. Recent requests across the four
active solvers had 381 HTTP 200 responses, one still in progress and no recorded
request failures. Each solver container used tens of MiB at that instant; the
configured 20-CPU/60-GiB values are limits, not reserved or continuously consumed
resources.

The scheduler alone was restarted to add capacity reloading. Existing jobs kept
their PIDs, workspaces and allocations. Eight live solvers were observed before
the next increase; their load was 8.18 and available memory approximately 146 GiB.
The target then changed to sixteen without restarting the scheduler or workers.

At the qualified sixteen-solver observation:

| Observation | Value |
| --- | ---: |
| Live cases with actual model requests | 16 |
| CPU count / one-minute load | 60 / 12.68 |
| Available memory | 144.52 GiB |
| Free disk | 164.44 GiB |
| Recent completed HTTP 200 requests | 543 |
| Recent still-pending requests | 8 |
| Recent recorded model-request failures | 0 |

All sixteen allocator profiles and observed model identities were verified as
GPT-5.6-Luna/max, 21600 seconds and no request ceiling. Their actual environment
configuration retains `--network none`, 20 CPUs and 60 GiB. The four original
starts/deadlines/profiles are unchanged. Lowering a future capacity target only
pauses new admissions until active work drains; it does not cancel existing work.
Preparation, solver execution, grading and archival all occupy the same case slot.

`VERIFIED.json`, `stage8-observed.json`, `stage16-observed.json` and
`original-grant-audit.json` retain the checks. Capacity controls accept the recorded
authorized range and reject zero, booleans, values above sixteen and changed
authorization identities. A separate read-only monitor retains host/job/request
observations every minute. It makes no model requests and does not modify solvers.

One preparation failure occurred during the increase: gping's evaluator branch
attempted Ubuntu snapshot package access in its offline preparation environment,
then exited 100 without a scope receipt. The diagnostic records failed DNS access;
no solver was admitted. That failure remains recorded. These observations do not
support attributing it to CPU/memory exhaustion, nor claiming an error-free full
campaign. Its evaluator prerequisite needs separate investigation.

The initial capacity observation establishes that sixteen concurrent solvers
actually run with substantial host headroom. It does not establish sustained peak
resource demand or a measured fourfold throughput gain. The original per-instance
limits remain intact, and concurrency periods are available when analyzing any
later wall-time or throughput differences. No kernel or strategy was changed to
increase campaign admission capacity.
