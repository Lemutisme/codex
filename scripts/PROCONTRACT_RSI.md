# ProContract RSI: exploration without self-certification

This host joins the online stream to ProContract's independent adoption path.
One pinned Codex runtime executes tasks and research. A version can change its
seven role policies, including how it researches, analyses and challenges its
own successors. The kernel, evaluator, budget rules and host stay outside those
versions' write authority.

## Workflow

```text
assign task + version -> execute -> frozen delivery -> external feedback
    -> analyst -> challenger -> research -> qualified exploration policy
    -> next unseen batch

fixed release checkpoint -> freeze the policy that actually ran
    -> fresh paired confirmation against incumbent -> authorized adoption
```

`exploration_head` may be experimental. `incumbent` changes only through an
adoption contract. A checkpoint does not certify the newly generated, untested
policy: it considers the version that completed that batch, and requires that
version's own challenged mechanism signature to be present. Structural
qualification and a successful research delivery are not claims of improvement.

## Run

Build the host's store CLI, separately from the pinned execution runtime:

```sh
cd codex-rs
cargo build -p codex-pro-contract-store --bin pro-contract-store
cd ..
export PRO_CONTRACT_STORE_BIN="$PWD/codex-rs/target/debug/pro-contract-store"
```

Use a compatible Codex binary with `codex-code-mode-host` beside it. The existing
v6 runtime is compatible. ProgramBench images, its checkout, the task prompt and
the runner's model credentials must be prepared as for the existing benchmark
runner. Credentials belong to the trusted host, not the research workspace.

`stream.txt` contains one instance ID per line. `sealed.json` has a `confirm`
array of separate instance IDs, never previously exposed to this research
lineage. Keep both the runtime and evaluator inputs pinned throughout a run.

```sh
python3 scripts/procontract_rsi.py init \
  --camp /path/to/campaign --codex-bin /path/to/pinned/codex \
  --model gpt-5.6-luna --effort max \
  --task-prompt /path/to/task-prompt.txt --research-image YOUR_RESEARCH_IMAGE \
  --programbench /path/to/ProgramBench --hf-revision PINNED_REVISION \
  --instances /path/to/stream.txt --batch 16 --release-every 2 \
  --sealed /path/to/sealed.json --sealed-pool confirm \
  --confirm-pool 16 --confirm-tasks 8 --confirm-min-wins 6 \
  --confirm-min-delta 0.0 --adoption presumed
python3 scripts/procontract_rsi.py stream --camp /path/to/campaign --count 1
python3 scripts/procontract_rsi.py status --camp /path/to/campaign
```

Model and effort apply to execution, analysis, challenge and research. Use a fresh
campaign to compare another model; do not relabel a running campaign.

Repeat `stream` to advance. `--adoption explicit` instead requires the operator
to run `adopt --camp ... --version ...` after confirmation. `--release-every 0`
retains research-only streaming. Streams reject imported seed knowledge and
overlap with their confirmation reserve. A task-name filter is not proof that
an externally supplied reserve was never exposed; its provenance remains an
operator responsibility.

Only one modifying CLI invocation owns a campaign at once. A restarted host
resumes its assigned batch and frozen release choice. Confirmation reservations
remain spent, including after failure. Each measurement has at most two attempts
across restarts; an interrupted attempt is invalid, not free. Invalid outcomes
are never converted to a zero score. Failed analyses keep old knowledge and do
not advance the exploration policy.

Adoption's discharge and incumbent event commit in one SQLite transaction,
fenced against the incumbent selection recorded before confirmation. Legacy
unsettled confirmations without that assignment fail closed; do not reuse their
support with a new fence. Settled legacy versions remain readable.

## Verify without model calls

```sh
cd codex-rs && just test -p codex-pro-contract-store && cd ..
PYTHONPATH=scripts python3 -m unittest \
  test_procontract_release test_procontract_succession test_procontract_comparison
```

These integration tests use real store transactions and deterministic task/model
doubles, not evidence that the learned policy improves a real model. They cover
both adoption modes, stale incumbents, interrupted confirmation, rollback of a
failed transaction, bounded attempts and separate exploration/serving versions.

`baseline` runs the operator root, not a later incumbent. `report` checks pinned
comparison identities and reports missing/invalid tasks against the full task
set. Its task bootstrap is descriptive, not a statistical certificate for an
adaptive learning method; release decisions do not consume that report.

## Deliberate boundary

This is policy-level RSI, not unrestricted binary self-modification. Generated
harness binaries must not run in the current trusted host's credential-bearing
process. A protected builder, isolated candidate runtime and scoped model and
environment access are prerequisites to opening that boundary. A hash chain
does not provide OS isolation, and the store CLI is an operator interface, not
a model-visible authority endpoint.
