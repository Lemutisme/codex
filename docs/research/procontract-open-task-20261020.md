# Open-ended responsibility and request context

The structural migration removes the requirement for a finite task lifetime.
Ordinary `procodex` tasks now default to no hard task deadline. Explicit limits
remain enforceable, including the original grant on restart. The pure
`codex-rs/pro-contract` kernel and RSI code are unchanged.

## Implementation and boundaries

- Harness settings and persisted task accounting represent absence explicitly:
  `total_secs` and `deadline_ms` are optional. Continuation waits on events or
  cancellation when there is no deadline, rather than a large sentinel timer.
- Progress can retain its accounting without enabling successor sessions or
  requiring finite time. Real parent/owner limits clamp actions when present.
  Worker, command and chosen diagnostic allocations remain distinct; their
  defaults have not all been removed.
- Persisted finite records keep their wire values. Missing/corrupted deadline
  data cannot silently widen a historical finite grant. New configuration
  defaults cannot renew or remove an existing allocation.
- User interruption now reaches the controller through `on_turn_abort` with an
  executor epoch. It records no handoff and retains the responsibility. An old
  abort is ignored after a newer epoch starts. Restart/resume uses the original
  task, evidence and grant.
- The evaluation gateway accepts optional time and request ceilings independently.
  Arming and owner shutdown remain meaningful without a timer, including closure
  during connection startup. Its benchmark defaults remain 21600 seconds and
  1000 requests.
- The terms adapter separates non-obligatory `context` (preference, permission,
  background) from requirements and process constraints. Context does not grant
  tool authority or enter the obligation catalog. Empty context preserves old
  serialization/hashes. Reviewer strategy checks classification against the
  original request, so actual requirements cannot be silently discarded there.
- The production drafter schema enumerates exact host-issued request-source IDs.
  The host resolves them to original text. It does not normalize guessed aliases,
  apply timing keywords, or retry negative judgments until they pass.

The source-ID vocabulary and context representation belong to the harness/store.
Interpreting what the user requires or prefers belongs to strategy. Neither needs
a new kernel command or task-solving workflow invariant.

## What the real runs found

Two fresh complete solver E2Es used GPT-5.6-Luna/max for all roles, no native task
deadline and no gateway time/request ceiling. Tools were offline. Each received
one solve and a frozen external grader; neither was rerun to select a score.
The qualification supervisor had a separate 900-second watchdog, which did not
fire. The prepared executor configuration was installed before app-server startup;
actual containers confirmed the declared 180-second command limit and private
runtime loader. These are synthetic capability tasks, not ProgramBench/Vals.

| Task/build | Requests | Seconds | External artifact result | Internal outcome |
| --- | ---: | ---: | --- | --- |
| JSON Merge Patch / dev2 | 42 | 256.83 | 32/32; initial artifact 15/32 | `terms_gap`: soft turnaround expectation became a constraint |
| Adjacent runs / dev3, prompt clarification only | 36 | 254.14 | 32/32 | `reviewer_unable`: the advisory constraint still demanded timing evidence |

Both artifacts are successful on their measured checks. Internal non-Support is
an implementation/representation lesson, not a reason to relabel those artifacts
as failures. Prompt clarification alone did not reliably distinguish guidance
from obligations; that motivated the explicit context field.

Two live production drafter calls on dev3 also exposed a mechanical source-ID
error: the soft control returned `"0"` where the host requires `"request:0"`.
Semantic classification was useful, but that response did not qualify the native
protocol. The hard control preserved the prohibition and deadline. The subsequent
schema enum removes this avoidable ambiguity without broadening authority.

## Latest native/live qualification

Dev4 includes typed context, the source-ID enum and the rebuilt store helper.
Two controls used actual native Issue/check/review with real Luna/max drafter and
reviewer calls. Only the artifact-writing executor was scripted. The production
worker request/schema/tool loop was forwarded to the real gateway; these are
integration controls, not full-model solver performance measurements.

| Control | Actual requests | Seconds | Native result |
| --- | ---: | ---: | --- |
| Artifact plus permission, background and soft time preference | 14 | 50.15 | All three context kinds retained; one artifact obligation; Support |
| Artifact plus no-deletion prohibition and explicit 120-second stop | 14 | 52.72 | Both process constraints retained; artifact supported, process evidence unresolved |

All 28 upstream responses completed with the recorded Luna/max identity. Both
review responses passed protocol validation on their first final response; no
protocol correction was needed. The soft task had no hard deadline. The hard
control was provisioned with an actual 120-second native grant. The gateway had
no time/request ceiling and the control supervisor had a separate 600-second
watchdog, not exercised.

The hard control demonstrates preservation of mandatory constraints, not complete
execution attestation. The reviewer lacked proof of no intervening deletion and
did not receive adequate timing evidence. Separate native deadline tests establish
enforcement; this does not supply missing evidence retroactively to the review.
Exposing an authoritative execution restriction as scoped reviewer evidence remains
a separate capability improvement. Do not weaken the requirement to make it pass.

The first postprocessing script incorrectly treated the domain-separated terms
hash as a blob filename. Original error results remain retained. A separate
read-only audit extracted the actual terms from the committed Issue journal and
checked classification. No model or solver was rerun for this correction.

## Verification

- 207 extension tests and 42 store tests passed. They cover optional deadlines,
  historical finite grants, action clamping, progress without successors,
  interruption epochs, context/obligation separation and source IDs.
- Targeted Clippy passed with warnings denied; native binaries and store/check
  helpers built successfully.
- 12 launcher configuration and 11 gateway tests passed, including unarmed versus
  untimed accounting, persistence, explicit limits and shutdown of untimed streams.
- Latest dev4 native controls passed for open-ended successor publication,
  interruption → app-server shutdown → restart → thread resume with the same
  grant, and a 60-second original deadline that stops background writes.
- Dev4 also passed untimed diagnostic checkpoint → real timeout → retained
  checkpoint retrieval → continuation → changed-subject check → final acceptance.
  Dev2 additionally passed the late-successor control under the original
  75-second grant.

The first cancellation test failed because interruption bypassed thread-idle
notification and left controller status at `working`. Its retained failure drove
the explicit abort hook. Tests then passed without inventing a task deadline.
Validation setup errors (including an initial capture helper assuming every task
has a succession row) remain in the artifact directory.

This verifies selected mechanisms and examples, not arbitrary long-horizon
success, universal classification reliability, or comparative benchmark gains.
Existing Principal workflow coupling remains migration work. See the separate
[RSI migration design](procontract-rsi-structure-20261020.md) for the next boundary.

## Evidence location

Artifacts: `/data/ProContract/procontract-open-task-20261020`.

- `source-dev4.json`, `package-dev4/build-source.json`: exact dirty source/build
  provenance. Earlier development packages contain inherited release metadata;
  their explicit `build-source.json`/source snapshots identify the actual builds.
- `typed-context-tests.log`, `clippy-typed-context.log`,
  `build-typed-context.log`, `python-qualification-final.log`.
- `native-controls-1.log` (original cancellation failure),
  `native-controls-2.json`, `native-controls-4.json`,
  `native-open-diagnosis-dev4.log` and its retained report directory.
- `live-e2e/plan.json`, `live-e2e-policy/plan.json` and their original run results.
  Frozen file hashes were rechecked after qualification with no changes.
- `draft-qualification-v2/live-plan.json`, `live-result.json`.
- `context-live-controls/plan.json`, original `RESULT.json`,
  `context-live-controls/AUDIT.json`, each control's ledger, requests, responses
  and `admitted-terms.json`.

The final release receipt binds the committed source to the tested development
snapshot and binaries. Compilation preceded commit and is recorded as such.
