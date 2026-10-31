# Parent review of the delegated RSI implementation

The explicitly delegated Astra/xhigh implementation survived the host restart at
`5b3b1f1a4` in `feat/procontract-rsi-e2e-20261031`. After source/evidence review it
was merged into the development checkout at `2dc1a044b5`. The operations remain
opt-in; no fixed benchmark package, installed production package or active solver
was replaced. The delegated agent's process/handle is no longer live after reboot.

The parent verified the retained E5 chain from actual operation objects, kernel
settlements, actor views, resolved inputs and native command receipts. The model
authored the sole changed file, `reducer.py`; protected testing passed 6/6 fresh
cases; the selected version advanced from sequence 1 to 2; the next native task
actually invoked that version and returned `13\n` on `12\n-5\n6`.
The independent audit output and review metadata are in the recovery artifact root:
`parent-rsi-evidence-audit.json` and `parent-rsi-review.json`.

Parent validation reran all 37 Python controls successfully and directly reran
the retained Rust test executable: 249 passed. Cargo was unavailable in the
restarted host environment, so this was not a fresh Cargo rebuild. The delegated
qualification separately records the earlier build, Clippy and nine native
controls. Those results were inspected, not silently relabeled as new parent runs.
Allocator databases independently confirm all five trials: 15 + 56 + 24 + 63 + 103
= 261 model requests, 256 with reported usage. Failed and invalid trials remain
charged and retained.

The implemented decomposition follows the user's agreement:

- Existing kernel/store semantics are unchanged. Ordinary work and improvement
  use separate responsibilities through the same kernel implementation.
- Harness operations retain assignments, versions, outcomes, pending inputs,
  original grants and authorized selection; native action finalization survives
  caller loss. They do not choose a fixed research sequence.
- Research choices and workflow live in replaceable strategy context. Knowledge
  retention does not itself install behavior. Testing and adoption are separate
  operations whose subject, evidence, authority and next actual use are bound.

The measured achievement is **operational E2E closure for a synthetic tool
adaptation**. It does not yet demonstrate broad long-horizon improvement,
model-weight RL, automatic native-controller replacement or migration of a running
controller. E5's model left cursor 0 acknowledged; retained pending input was not
invented away. Ordinary task-history acceptance remained `not_verified`; the
separate, scoped adoption contract was discharged. E2/E4's earlier reach-invalid
settlements were explicitly defeated and remain historical observations.

The next research distinction is useful adaptation versus mechanism completion.
Future authorized adaptive experiments can test whether the retained trajectory
lessons improve fresh connected/open-ended tasks, with selection scope and actual
costs recorded. The fixed 200-instance cohort continues to supply post-run evidence
without receiving these updates. No task-specific threshold, universal deadline
or second learning kernel follows from this implementation.

See [the qualification](procontract-rsi-qualification-20261031.md),
[the operation interface](../PROCONTRACT_OPERATIONS.md), and
[the restart/trajectory record](programbench-restart-20261031.md).
