# RSI implementation and qualification

Status: core implemented; qualification in progress on `feat/procontract-rsi-e2e-20261031`,
based on `454b2ba00fffad94e4262da9989eb682d5fdb853`.

Scope: reusable durable operations and model-selected research over the existing
ProContract kernel. Ordinary and improvement responsibilities remain distinct.
No model-weight optimizer or general improvement claim is intended. The fixed
200-instance ProgramBench campaign is read-only and receives no rollout.

Factoring:

- Native action finalization must outlive a cancelled caller; publication ownership
  must outlive tool transport. Unknown external effects still prohibit replay.
- A separate, generic host journal retains explicit assignments, outcomes,
  pending decisions, subscriptions and version definitions. It does not choose
  analyst/challenger stages, experiments, thresholds or a learning schedule.
- Research instructions choose operations. Knowledge records do not select a
  strategy. Selection uses the existing kernel/store adoption transaction with
  actual delegated provenance and an expected-incumbent fence.
- Version definitions include all instruction sources and build/model identities;
  runs separately retain the exact resolved inputs. Task and research versions
  have separate identities.

Qualification pending: targeted Rust lifecycle tests; durable host fault tests;
native scripted controls; one fresh GPT-5.6-Luna/max ProContract episode with
model-created candidate, explicit test, adoption and a next task using it.
All outputs and isolated build artifacts are under
`/data/ProContract/procontract-rsi-development-20261031/`.

Core checks: 248 Rust extension tests, Clippy with warnings denied, and 11
Python operation/authority fault controls pass. Three native scripted controls
pass (publication/repair, interrupted-root continuation, open-ended cancellation
and resume). A preliminary real-model attempt found incompatible image libc; it
was stopped and retained as execution-invalid, not quality evidence. A separate
offline Ubuntu 24.04 fixture image passes the executable preflight.
