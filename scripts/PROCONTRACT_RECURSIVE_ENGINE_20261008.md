# Recursive engine: inherited methods and executable harness decisions

This stage extends the existing ProContract Host, not a second orchestration system.
It adds a deliberately narrow executable harness surface to the seven inherited role
policies. The Codex binary, model weights, evaluator, authority and budgets stay fixed.

```text
task with version V -> frozen delivery -> external feedback
    -> analyst(V) -> challenger(V) -> researcher(V)
    -> mechanically qualified role policies + harness program -> V+1
    -> next task AND next analysis/challenge/research execute V+1

independent release checkpoint -> fresh confirmation -> authorized incumbent adoption
```

Exploration qualification is not evidence of improvement. The existing independent
release/adoption path remains separate. A method-only change cannot acquire a claim of
better research merely by inheriting its parent's task scores.

## Executable surface

An authorized researcher may add or edit `policy/harness.json`:

```json
{
  "schema": 1,
  "when": {
    "all": [
      {"remaining_fraction_lte": [1, 10]},
      {"completed_turns_lte": 0}
    ]
  }
}
```

The trusted interpreter compiles this into immutable tuples, then evaluates it during
the actual runner loop. Inputs are only the deadline, remaining seconds, completed
executor turns and repairs used. A true result requests convergence guidance. It does
not supply a message, RPC name, file path, new deadline or evaluation result.

Predicates are `always`, `remaining_fraction_lte`, `completed_turns_lte`,
`repairs_used_gte`, `all`, `any` and `not`. Source is capped at 4 KiB, with at most
64 predicate nodes and depth 8. Duplicate keys, floating point, non-finite values,
unknown operations, unsafe files and out-of-range integers are rejected. All branches
are validated, including branches that short-circuit at execution time.

The Host permits at most one fenced steering request, only for an active executor in
an allowed phase and within `min(3600, deadline // 4)` remaining seconds. The original
hard deadline still applies. The program cannot expand that window or retry a request.
For a five-hour task the maximum window is its final hour; research runs use their own
smaller deadline. The existing interrupt/cleanup tail is not a strict real-time guarantee.

This is interpreted harness-control program evolution, not arbitrary Python/Rust
binary self-modification. No candidate program receives filesystem, network, process,
credential, evaluator or ledger capabilities. It does not alter native worker internals.

## Actual inheritance and identity

- `register` freezes the exact validated program bytes and records its digest and
  interpreter identity separately from the seven role hashes. Missing programs retain
  legacy behavior and version identities; old campaign mutation permissions do not expand.
- Task and learning roles already share `runner.prepare/run`. Both now pin the program
  and execute it; `run.json.harness_program` records evaluation count, final input and
  decision. Zero evaluations means loaded but not exercised, not an execution witness.
- CLI reserve overrides cannot silently replace a version's program.
- Host validates registered role/program bytes before dispatch and checks prepared/run
  activation identities afterward, including cached valid task results. Drift stops the
  campaign without purchasing another attempt under the same identity.
- A harness change invalidates the execution `twin`; a method-only change invalidates
  analysis reuse even when observations are unchanged. Analysis inputs bind the producer,
  evidence, protocol, pending experiment and prior knowledge. Its own accepted knowledge
  output is recognized without recursively reanalysing that output forever.
- Interrupted analysis inputs cannot be changed by deleting already spent attempts.
  Ordinary failed research is rejected and leaves the exploration policy unchanged;
  failed runner output is not certified merely because documents remain on disk.

The interpreter and Host are trusted, pinned implementation components. Their source
identity must remain frozen for a study; the mutable program cannot upgrade its own
interpreter or authority rules.

## Offline closure evidence

The recursive integration test uses the real Host and real Rust store with deterministic
model/task peers. The peer reads the inherited research policy and observed task feedback;
it does not take its successor generation from an external environment switch.

Across three batches it checks `V0 -> V1 -> V2`, unchanged executor text, changed research
methods and programs, role-specific activation identities, restart reuse, and actual
steering through the production `DeliveryBudget`. Program thresholds stay within the
Host's action window. Scripted task scores stay at 0.5: this test claims control-flow and
inheritance closure, not learning efficacy or autonomous model improvement.

Separate tests exercise the real prepare/run plumbing with fake transport, malicious
program rejection, source/activation drift, failed-run handling and method-cache identity.
No Docker, model or hidden evaluator is required by these tests.

## Running scope

Use the existing `procontract_rsi.py init/stream/status` workflow. New campaigns allow
`harness.json` by default alongside the seven role files; an explicit `--mutable` list
must include it to permit changes. Task and research activation requires no separate
adapter flag. Keep model/effort at `gpt-5.6-luna/max` for the planned study.

This stage is prepared in a writable source archive because the integrated worktree and
Git metadata are read-only in the current session. Docker access is also denied. No new
Luna run, benchmark result, formal promotion or commit is claimed here. Full live closure
still requires authorized execution, a pinned runtime/protocol smoke and independent
confirmation inputs. Receipt-bound source-checkpoint selection, whole-runtime isolation,
total-study budget enforcement and causal RSI benefit experiments remain separate work.
