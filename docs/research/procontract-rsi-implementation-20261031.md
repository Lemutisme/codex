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

Further qualification before the final episode:

- 17 Python controls now pass, including scoped unknown-effect fencing, late local
  reconciliation/wake, actor cancellation, initialization loss, expiry-safe receipt
  reads and task/research deployment identity. The three initial failing edge
  controls are retained in `logs/additional-faults-before.log`.
- Native caller loss is reproduced by abandoning a code-mode publication waiter.
  The older ProContract package fails to finalize it; the development package
  completes the assessment and repair. This is ProContract before/after, not a
  native Codex comparison. Detailed receipts are in `native-controls/`.
- Preliminary episode `e1` is execution-invalid (libc mismatch). Its early raw
  projection treated a missing output as false; this is not a quality result.
  Fresh native projections retain unavailable quality as null.
- Episode `e2` reached a genuine model-authored candidate, a 6/6 sealed result,
  and delegated kernel adoption. Its chosen wait did not stop an unrelated
  legacy drafter. It was interrupted through its own isolated runner, with
  adoption and failed-operation evidence retained; no next-task rollout claim
  is made for that partial episode. This led to the adapter wait/shutdown fix.

The next replay, `e3`, stopped before dispatching research because its declared
native effect scope was unresolved. A container had auto-removed between Docker
inspection and removal; the CLI failure was conservatively retained. The adapter
now checks the subsequent live set, with controls for both already-removed and
still-running containers and for unrelated mounts. Raw `e3` is retained.

Current validation: 248 Rust tests and Clippy pass; 20 Python operation/adapter
controls pass. The native reviewer-503 control now also reaches strategy-selected
verification without another user turn or another executor call. Known local
inspection finalization and thread teardown now await owned action receipts;
unknown historical executions remain unresolved rather than inferred complete.
