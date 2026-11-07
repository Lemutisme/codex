# Continuing Astra RSI analysis for native Codex ProContract

The user requested an Astra agent to continue analyzing how the harness and
strategy should evolve. The existing `/root/astra_sol61_rsi_retro` agent was
reactivated, retaining its previous evidence and candidates. New working outputs
are under `/data/ProContract/procontract-codex-rsi-evolution-20261107-astra/`.

The assignment covers successful and failed trajectories, precise causal
attribution, minimal layer-appropriate capabilities or context changes, scoped
counterexamples, and falsifiable validation. It also examines the end-to-end RSI
path from terminal evidence to a candidate, measured selection and the actual
later execution version. The live model cohorts remain frozen.

The first finding narrows the `run` publication failure: capture/resume completed
for publication10, an asynchronous cell was returned, and the executor attempted
additional publications without waiting for that cell. The investigation is now
following the independent publication owner, caller termination and teardown.
The existing owner mechanism should not be duplicated, and pending state should
not be cleared without resolving the actual operation outcome.

The qualification example also needs a precise interpretation. Its request did
include process requirements; a correct `42\n` artifact alone does not establish
the requested execution history. The improvement target is visibility and binding
of the existing execution receipts, together with separation of artifact support,
past-action evidence and final delivery. This is not evidence for removing the
user's process obligations.

These are initial research findings, not a completed causal report or a deployed
change. Candidate adoption requires review and verification. Kernel semantics
remain domain independent; task-solving choices remain strategy, and execution
capabilities and lifecycle handling remain harness.
