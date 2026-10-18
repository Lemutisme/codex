# ProgramBench execution profile

The 2026-10-18 validation uses GPT-5.6-Luna / max, the existing native ProContract
release `93324dbe0`, and three prospectively selected official instances. The
request/time authority is an external benchmark adapter; the responsibility
kernel and its settlement rules are unchanged.

The official mini-SWE-agent configuration and Vals description specify 21,600
seconds, 1,000 model steps, 180-second actions, offline task containers, and
5,000-character head/tail observations. Codex app-server turns are not model
steps. `procontract_benchmark_gateway.py` reserves each Responses request in a
durable SQLite transaction before forwarding it. Executor, drafting, exploration,
review, compaction, repair, and successor requests share the same allowance.
Failed or interrupted attempts are not refunded, and SDK retries are disabled.
Restarting the gateway cannot change the original deadline or request allowance.

The gateway pins model/effort, rejects provider-hosted network tools, applies the
character observation boundary to actual model requests, and records source and
forwarded hashes. The execution transport enforces the command lifetime even
between reads. The external supervisor freezes the workspace after stopping its
writers and then runs the canonical evaluator without giving hidden-test results
back to the solver. Exhaustion submits that stopped workspace; it does not imply
natural delivery, internal Support, or authorized settlement.

Local evidence is retained under
`/data/ProContract/programbench-strict-20261018`. The source configuration, current
official image digests, test revision, selection, grader readiness, adapter tests,
full-duration transport qualification, and launch manifest are separate records.
The three instances are `sharkdp__bat.f822bd0`, `sheepla__pingu.926d475`, and
`ast-grep__ast-grep.dde0fe0`. Selection excluded the recent six official tasks and
did not use their scores; prior operator exposure is still disclosed.

This aligns the stated execution limits, not the entire Vals harness or provider
snapshot. The private loader needed by the current native binary is a read-only
transport mount; child task processes retain the image's own loader/libraries.
ast-grep's declared pexpect dependency is installed from pinned offline wheels in
the grader after candidate compilation and hash verification. Earlier bootstrap
and qualification failures remain retained. Only completed, valid evaluations
may supply external scores; no leaderboard-wide or causal claim follows from
these three cases.
