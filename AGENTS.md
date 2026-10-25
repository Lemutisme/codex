# ProContract architecture

For ProContract work, follow the user's layer definitions in
[docs/PROCONTRACT_LAYERS.md](docs/PROCONTRACT_LAYERS.md):

- **Strategy** is context-level instruction: prompts, skills, and other supplied
  context, including how to compose and orchestrate the workflow.
- **Harness** is agent-control and tool-layer code. Keep it essential: expose and
  execute capabilities, retain state, and enforce actual authorization/resource
  boundaries without embedding task-solving strategy.
- **Kernel** contains the domain-independent progress/responsibility semantics
  and authorized transitions. Do not promote empirical workflow heuristics into
  kernel invariants.
- **Time**: a task may have no hard deadline. User time expectations guide strategy;
  explicit user/benchmark/environment resource limits constrain execution. Durable
  progress, continuation and cancellation must not depend on a finite global
  countdown. Existing mandatory task-lifetime assumptions are migration work.

Keep these layers decoupled. Choosing when to diagnose, review, hand off, change
methods, or replay checks belongs to strategy; implementing those operations
belongs to harness. Moving a hard-coded workflow into a configuration file does
not, by itself, make it a context-level strategy. Existing coupling is migration
work, not a precedent for new coupling.

Benchmark preference, 2026-10-24: validate ProContract only by default. Do not add
native Codex comparison runs. If a native or remote Codex comparison is explicitly
requested later, actually enable and verify `/goal` under comparable resources.
Previous OFF attempts used ordinary turns without `/goal`; retain their raw
results as historical observations and state this limitation rather than using
them to claim long-horizon superiority.
