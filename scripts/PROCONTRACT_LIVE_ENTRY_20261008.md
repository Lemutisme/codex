# Sealed entry to the test-time RSI engine

This increment does not add another research workflow. It puts a verified entry and a
durable launch-allowance gate around the existing guarded Host, including its adopted
execution, analysis, challenge and research roles.

## New-study creation

Initialize a **new** canonical guarded campaign through `procontract_rsi.py init` with
the previously documented registry/pins, stream and confirmation inputs. Add all three
operator-chosen limits:

```text
--study-task-launches <maximum task runners, including both confirmation arms>
--study-learning-launches <maximum analyst/challenger/research runners, including retries>
--study-allocated-secs <sum of full declared runner deadlines>
```

The profile requires `gpt-5.6-luna/max`, one 18000-second inference allocation per task
unit, canonical evaluation, guarded releases, and a content-addressed research image.
Learning deadlines must be explicit positive values at most 18000 seconds. Sealing an
existing campaign is rejected; do not retrofit new semantics onto historical receipts.

Initialization exclusively publishes `study.json`, provisions an empty, identity-bound
`study-budget.sqlite`, and then creates the campaign and its ProContract terms binding.
The descriptor is stored in `campaign.json`. A crash in initialization may leave a
partial, unstarted study requiring operator reconciliation; it does not authorize
deleting accounting from a study that has launched work.

Example allocation arithmetic, **not a funded or executed study**: three stream phases
and four paired confirmation tasks can require 11 task launches (3 + 2 x 4). With two
attempts each for analyst/challenger in each phase and one researcher in the two serve
phases, allow at most 14 learning launches. At 18000/3600 seconds respectively the sum
is 248400 allocated seconds. This is deliberately an upper bound, not an actual-cost
estimate or a recommendation to spend it. At least four stream tasks must be declared
to let phase three research a successor rather than finish the stream.

## Verified continuation

The operator retains the study-manifest SHA-256 stored in `campaign.json`. Continue via:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/procontract_live.py stream \
  --camp "$CAMP" --study-sha256 "$STUDY_SHA" --count 1

PYTHONDONTWRITEBYTECODE=1 python3 scripts/procontract_live.py budget \
  --camp "$CAMP" --study-sha256 "$STUDY_SHA"
```

The entry validates the pin and inventory before importing the Host. `status` and
`adopt --version ...` use the same entry. `--count` never expands the sealed allowance.
The native Host also enforces declared seals, including cache and first-adoption paths;
removing only the declaration while leaving `study.json` cannot silently downgrade it.

Sealed inventory includes the local Python source and existing bytecode, seven seed
policies, Codex/code-mode-host/store binaries, both Python executable identities,
ProgramBench source/fixtures, evaluator virtualenv (including bytecode and `.pth`),
offline blobs/wheels, registry/pins, task prompt, selected environment and complete
campaign terms excluding the circular study descriptor. The verifier derives the
required inventory independently; a manifest cannot omit a required file to exempt it
from checking. Runner children suppress bytecode writes to avoid changing their own
sealed source inventory.

This is **not a hermetic OS seal**. The initial entry/verifier, host stdlib/shared
libraries, OS tools/services, permissions and opaque provider routing remain trusted.
The operator must protect the Host, manifest and ledger from candidate writes. Hash
checks are not isolation against a privileged actor replacing the trusted verifier.

## The actual paid boundary

Every task and learning role converges at `procontract_benchmark_runner.run`. Immediately
before constructing AppServer, the study gate checks the seal, registered and prepared
policy bytes, harness identity, model/effort, binary, image, prompt, role deadline and
generated runtime configuration. Unsealed or drifted prepared metadata inside a sealed
campaign is rejected. Runtime overrides cannot relabel a frozen producer.

It then transactionally reserves one task/learning launch and its **entire declared
deadline**. Only the first successful reservation returns authorization. Known failures,
unknown launches and crashes after reservation stay charged; a receipt is evidence,
not a reusable capability. Missing/corrupted/deleted accounting is never treated as zero
balance. Reservations use the fixed campaign ledger path, not a caller-chosen new DB.
Normal cached Host results do not enter the runner and therefore do not charge again.
Producer/phase authority remains in the guarded Host. The low-level runner checks a
registered producer and the sealed allowance, not the whole guarded assignment: a
principal's direct experiment with a registered version is not a production adoption
or evidence that the guarded workflow selected that version.

The reservation receipt appears in `study-launch.json` and a completed runner's
`run.json`. It limits runner launches and deadline allocations, **not individual model
HTTP requests, tokens or dollar invoices**. A runner contains multiple executor/worker
requests and transport retries. Preparation, external evaluation and shutdown tails are
not inference-allocation seconds. Cost receipts remain separate; unknown cost is not
zero, and strict dollar caps would require transport/provider-side admission.

Canonical evaluator/score children receive the same study descriptor and recheck the
source/resource seal even after a long task. Their environment remains credential-free.
Per-thread binding prevents concurrent confirmation arms from dropping one another's
study flags. Existing evaluator launch claims and receipt recovery remain unchanged.

## Completion boundary

Offline tests cover the entry, identity checks, real SQLite accounting, actual runner
dispatch boundary with fake transport, and legacy compatibility. They do not establish
authenticated model access, native active-turn steering, ProgramBench scores or causal
RSI benefits. This environment still denies Docker API access; no new live model run is
claimed. Actual fresh-task resources/pins, authorized Docker/provider execution,
model-generated P/M/H updates, independent confirmation and adopted live continuation
remain required. The previous method-only deferral and research-benefit caveats still
apply: this launch gate is not evidence that the updater has become more capable.
