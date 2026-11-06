# Early retry trajectories: retain the result and its actual mechanism

This addendum inspects selected spans from grex, trdsql, hostctl and chamber, plus
their original root-session progress. It is a checkpoint during the37-case retry
campaign, not its final aggregate. The underlying record verification covers49
citations and6 raw score hashes. No benchmark run was restarted by this analysis.

| Case | Original artifact | Independent retry | Exact test-vector comparison |
|---|---:|---:|---|
| grex | No usable score |1312/1312,100%|No valid paired score difference is available|
| trdsql | No usable score |1266/1312,96.4939%|No valid paired score difference is available|
| hostctl |1007/1051,95.8135%|1039/1051,98.8582%|32 improve;0 regress|
| chamber |1613/1748,92.2769%|1604/1748,91.7620%|22 improve;31 regress|

Grex is a particularly useful separation of facts. The malformed draft left
`phase=abstained` and no root Contract ID, while its executor continued and produced
a perfect externally scored artifact. Its root record also shows assessment being
refused because session terms were absent. Preserve the100% result and the gap in
Contract initialization coverage; neither fact substitutes for the other. The new
schema repair is qualified in development and is not retroactively installed here.

The same trajectory independently reinforces actual-target binding. A command
returned both a failed `cp` and777/777 passing checks, because the old root executable
was still the reference. The actor noticed, replaced the executable correctly and
then observed real differences. Later representation changes distinguished an
epsilon accepted by a shorter sample from an optional expression created by
factoring. A larger green test count alone did not distinguish these mechanisms.

Trdsql exposes interaction semantics that final bytes alone miss. A reference can
stop after a row limit while a producer still holds the pipe open; another format
correctly waits for EOF. SQL errors can roll back writes while preserving rows
already emitted. Compression/trailer checks and unused input sources introduce
different blocking conditions. Retain the specific successful and failing controls
rather than adopting a universal early-exit or timeout rule.

Hostctl's32 gains include29 completion tests. Its new partial-write and filesystem
side-effect controls are valuable, but the measured score gain cannot simply be
assigned to the most interesting narrative. Earlier runs already contained local
Docker and signal/temporary-profile controls. A separate clean-copy check initially
used an old commit after a failed Git commit; correcting the version produced the
meaningful build check. This reinforces the existing actual-subject finding.

Chamber has22 improved tests and31 regressions. Every regressed test's retained
failure includes `subprocess.TimeoutExpired`. Both attempts already had successful
local AWS fixtures and credential/signature work. The retry introduces richer
stateful checks, but may also accumulate waits across request and metadata retry
layers. This is a scoped hypothesis requiring the same inputs and environment with
both retained artifacts; it does not justify disabling all retries, changing task
deadlines or declaring the new score invalid.

Only one new candidate is proposed: project initialization outcome/Contract
identity, executor state/authority, and artifact/measurement identity separately.
Much of that data already exists in the current interfaces, so derived research
views should be tried before adding production state. The remaining observations
strengthen existing S1/S3/S4/S5/S7 knowledge. No kernel extension is proposed.

The source reader itself required two corrections: JSONL records use byte-LF
framing, and the parent grex receipt hashes its line including the final LF.
Applying the matching convention verifies the archived original line exactly.
These diagnostic mistakes were corrected without rewriting benchmark evidence.

The compact candidate and source index are retained here. Full selected payloads,
coverage records and the detailed report remain in
`/data/ProContract/procontract-sol61-rsi-retro-20261106-astra/retry-addendum/`.
