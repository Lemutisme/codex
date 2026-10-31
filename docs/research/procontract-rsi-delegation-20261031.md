# Delegated implementation: test-time learning / RSI E2E

User instruction: "可以，委托一个astra xhigh agent来完成，你来继续负责programbench的trajectory吸收。这是test-time RL/RSI"

The delegated agent owns implementation and qualification of
[the approved E2E architecture](procontract-rsi-e2e-architecture-20261031.md).
The parent retains ProgramBench monitoring, trajectory analysis and synthesis.
This authorizes development/testing in an isolated checkout; it does not unfreeze
the ongoing fixed 200-case experiment.

## Workspace and ownership

- Reserved implementation checkout:
  `/data/ProContract/worktrees/procontract-rsi-e2e-20261031`.
- Parent analysis checkout:
  `/data/ProContract/worktrees/procontract-continuous-work-20261016`.
- Read the checkout AGENTS.md and docs/PROCONTRACT_LAYERS.md. User definitions take
  precedence over older policy/code coupling: strategy is prompt/skill/context
  including orchestration; harness is control/tool code; kernel retains general
  progress/responsibility and authorized transitions. No universal task deadline.
- Use explicit workdir/absolute edit paths. Do not edit the parent's checkout.
  Commit implementation and tests in the delegated branch; do not merge it into
  the parent branch or overwrite installed/running packages.
- Do not spawn additional assistant delegates. Native app-server workers required
  by the application/E2E tests are a different mechanism and may be exercised.

## Concrete objective

Build and verify an operational end-to-end improvement path through the existing
kernel, with distinct task/improvement responsibilities and replaceable research
strategy. Retained real task observations must become usable research inputs;
the agent can retain/correct knowledge, create a candidate, execute an explicit
experiment, interpret it and select an authorized version. A subsequent task must
actually use the selected effective strategy/build before claiming automatic rollout.
Do not stop at a design document, scripted report generator or manual patch relay.

Implement the smallest reusable substrate rather than copying the old RSI workflow:

1. Durable operation outcomes, pending decisions and selected waits/wakes. Preserve
   original resources and cancellation; reconcile uncertain effects before replay.
   The controller need not stay in a permanent model loop or require a countdown.
2. Version/observation/experiment/decision operations with exact identities. Version
   definitions and per-run resolved context are distinct. Include current work_method,
   continuation and relevant skill/instruction sources; preserve old manifest meaning.
3. Context-level research orchestration through those operations. Knowledge uptake
   is not automatically a global prompt change; candidate adoption is separate.
4. Reuse the store's expected-incumbent/idempotent atomic adoption where appropriate.
   Preserve existing authorization and evidence conditions; never forge a human
   decision or let a candidate redefine its own authority/evaluator to pass.
5. A model-driven E2E episode with retained evidence, proposed change, tests/experiment,
   decision, actual adoption and a subsequent task using that version. Include failure
   controls around dispatch, finalization and adoption. A no-change decision can be
   correct, but does not exercise the rollout path.

The precise factoring is the delegated implementer's judgment. Do not add Learn,
Analyze or Improve kernel commands, empirical score gates or a new workflow DSL
without a demonstrated missing general semantic relation. Do not copy the old
mandatory analyst/challenger sequence, NOISE_FLOOR=0.087, fixed batch/retry/task counts,
or harness.json orchestration predicates into generic operations.

## Test-time learning meaning

The intended loop learns from task-time outcomes and updates scoped knowledge,
strategy/skills and, where warranted, harness versions. Do not claim model-weight
RL or universal improvement unless such an optimizer/evidence is actually present.
Keep quality, execution validity, measurement conditions, cost and adoption distinct.
Unavailable/misconfigured measurement is not a zero-quality reward. Research and
task-solving versions must have separate identities for attribution.

No per-iteration human permission prompt is intrinsically required within existing
standing authorization. Required source/evidence identities, actual authority,
stale-incumbent rejection and real resource limits remain enforced. Report concrete
limitations rather than silently widening authority or claiming unimplemented paths.

## Protect the running experiment and raw evidence

The fixed cohort is `/data/ProContract/programbench-full-timeonly-20261025`, solver
`c68db7c00a26057621b5a0d54a27e55d6969b1e7`. Read it as evidence only.

- Do not edit frozen plan/package/controller files, grader assets/wheelhouse, caches
  protected by hashes, running workspace contents or original scores. Some package
  files are hardlinked across cohorts.
- Do not stop/reconfigure shared Docker daemons, clean shared build trees, or resume
  graded solvers. The shared daemon socket belongs to the retained campaigns.
- Do not teach current fixed-cohort solvers from hidden feedback or change their
  versions. Any adaptive learning stream must be separate, explicit and versioned.
- Preserve solver network isolation and original six-hour/no-request-cap grants in
  benchmark profiles. Ordinary tasks and meta responsibilities may have no deadline.
- Qualify evaluation conditions. The shared daemon has no default bridge/NAT; recent
  DNS/HTTP failures include unavailable external routes. Do not treat their score
  gaps as clean strategy reward or silently change the current cohort's network.
- Do not add native Codex baseline runs. Real-model task validation remains
  ProContract-only, GPT-5.6-Luna/max, with explicit recorded assignments. Use small
  proportionate E2E episodes and deterministic fault controls, not another full
  200-case campaign. Do not print credentials.

## Useful existing code and evidence

- scripts/procontract_rsi.py: version registration and retained experiment mechanisms;
  Host.step/stream_step/learn currently couple research policy to host code.
- scripts/procontract_succession.py and codex-rs/pro-contract-store/src/store/adoption.rs:
  atomic settlement/selection, expected-incumbent fence and idempotency.
- codex-rs/ext/pro-contract/src/controller/runtime/: partial native continuation,
  publication pending/finalization defects and pre-Issue/worker/selector gaps.
- docs/research/procontract-root-cause-synthesis-20261031.md and
  procontract-evolution-register.md: current empirical scope, positive/negative
  mechanisms, measurement correction and linked source-bound artifacts.
- Earlier qualification: `/data/ProContract/procontract-responsibility-state-20261025/REPORT.md`.
- Local controls may use scripts/test_procodex_native.py and existing native fixtures.
  Scripted-provider controls establish mechanics; distinguish them from real-model RSI.

Build tools: `/data/ProContract/toolchains/cargo/bin` on PATH;
`CARGO_HOME=/data/ProContract/toolchains/cargo`;
`RUSTUP_HOME=/data/ProContract/toolchains/rustup`. Use an isolated CARGO_TARGET_DIR
under `/data/ProContract/procontract-rsi-development-20261031/`, with modest build
parallelism; do not mutate shared/frozen binaries. Python pytest is available via
`/data/ProContract/programbench-evaluator-repair-20261025/.venv/bin/python`.
The existing model route is `http://127.0.0.1:8317/v1`; use normal credential handling.

## Deliver and report

Keep a live implementation/status note in the delegated checkout and send milestone
messages to the parent: design factoring, first working native path, real E2E result,
and final commits. Report exact tests/artifacts, actual adoption/next-task version,
remaining gaps and resource use. Complete authorized development and meaningful
verification before ending; do not call a design-only result E2E completion.
