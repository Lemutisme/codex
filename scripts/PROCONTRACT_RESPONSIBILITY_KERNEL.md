# Responsibility kernel audit and the native OFF control

This stage holds the native binary and task protocol fixed. It does not repair the
kernel before measuring its existing behavior, reopen a terminal study, enable RSI,
or authorize additional inference. The local installed release is unchanged.

## What responsibility means

The pure `codex-pro-contract` reducer tracks obligations, not intelligence. An
executor handoff proposes an artifact; it cannot support or discharge itself.
Support names the current contract revision, candidate generation, artifact,
capture policy and evidence policy. Defeat or withdrawal invalidates the relevant
judgment and leaves/reopens the obligation. Stopping a runtime is not discharge.

The Host authenticates roles and supplies evidence identities; the reducer cannot
authenticate a process, judge arbitrary natural language, or establish that a
claimed verifier is epistemically independent. `Reach::Within` is diligence, not
unseen confirmation. The current evaluation lane never settles automatically.

There are three separate implementation layers:

1. `codex-rs/pro-contract`: deterministic authority/coordinate transitions.
2. `codex-rs/pro-contract-store`: transactional persistence, idempotency, immutable
   content-addressed artifacts and hash-chained events.
3. `codex-rs/ext/pro-contract/src/controller`: model-assisted drafting/probing,
   capture, checking/review, bounded repair, user-visible status and lifecycle.

A sound reducer does not make an unsound Host or incomplete scheduler sound.

## Independent acceptance questions

| Question | Required evidence | What does not establish it |
|---|---|---|
| Is authority preserved? | Wrong-role/stale-coordinate rejection, current-subject evidence, no self-discharge | A high task score |
| Is intent preserved? | Original request retained, grounded sources, omissions/exclusions explicitly accounted for | Well-formed JSON or source IDs alone |
| Is verification meaningful? | Known-good and known-bad native fixtures; unsupported/unknown stays distinct | Returning failure for every task |
| Does responsibility survive interruption? | Reopen ledger, restore active contract and repair allowance, reconcile pending work without duplicated authority | A SQLite file existing after exit |
| Does execution make bounded progress? | Choose continue/repair/stop from residual obligations, progress and remaining budget; terminal failure remains outstanding | Endless retry or a fixed single repair |
| Does the system help solve tasks? | Fixed-budget ON/OFF outcomes with all costs and failures retained | Tests of the state machine alone |

Kernel/storage tests and a local scripted-provider native fixture are free of real
model calls. They validate mechanics, including recognizing a supported candidate,
not model competence, universal correctness or general performance gains.

## Findings to keep distinct from benchmark results

- The benchmark profile sets `repair_attempts=1`. On another defeat, runtime rests
  `did_not_pass`; it does not spend the remaining task allowance adaptively. The
  ledger can preserve an outstanding obligation while no executor is scheduled.
- Source-reference validity does not prove that a model-generated contract covers
  every requirement. A numeric string such as `7` is not the issued `request:7` ID;
  the observed malformed draft correctly failed closed but harmed availability.
- Runtime recovery replays accepted contract history, validates issued bindings,
  and restores the original captured base and repair accounting. Resume itself
  never repeats an interrupted worker or repair; a new turn continues the same
  responsibility. Missing or inconsistent recovery evidence blocks automation
  without erasing its known contract identity. Durable storage alone is not a
  substitute for the native restart-and-next-handoff regression test.
- The pure reducer checks declared authenticated roles. Authentication, truthful
  provenance/reach classification and verifier isolation remain Host obligations.

## Controlled vanilla definition

`procontract_online_pilot.py prepare --comparison vanilla` seals three OFF tasks.
`--comparison contract` seals fresh ON/OFF pairs instead. Both prohibit coverage
mode, allocate zero RSI research calls, retain the identical seed P, model/effort,
task prompt, container constraints, binary, capture/submission rules and evaluator.
The actual native invocation differs only in enabling/disabling `pro_contract`.

This is a **feature-OFF ablation**, not an untouched upstream default installation.
Hooks and ordinary multi-agent execution are disabled in both arms. OFF naturally
ends after the executor hands off; ON waits for its check/repair lane. This measures
the combined ProContract workflow, not the isolated benefit of bookkeeping versus
extra verifier computation. Actual tokens and wall time must accompany scores.

Every task receives at most 4 hours native execution plus 1 hour grading. Inference
is reserved durably before launch; no research reservation is possible with a zero
learning cap. OFF must have no contract status or internal worker rollouts. It is
graded without requiring a contract, but malformed results, unknown process
lifetime and environment/integrity failures remain failures, never invented zeroes.

When existing frozen ON runs are reused, disclose the cross-batch comparison and
pin their original plan/results. Do not import their workspaces, transcripts or
scores into the OFF executor. No replacement trials or unused-budget reuse.

Completion of a functional control yields its own acceptance receipt; it never
marks RSI acceptance or the responsibility kernel as proven.
