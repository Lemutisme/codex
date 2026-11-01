# Offline preparation and completion of failed ProgramBench cases

The user requested preparing the offline environment and placing every failed
case from this round on a completion list. The active completion workspace is
`/data/ProContract/programbench-completion-20261101/`.

`RUN_LIST.md` and `completion-list.json` contain the admitted work; `STATUS.json`
and `COMBINED_RESULTS.json` provide the live projection. Original runs, failures,
scores and the frozen plan remain under `programbench-full-timeonly-20261025`.
The completion scheduler also discovers later terminal failures as that original
queue drains. It never treats a merely low valid score as an infrastructure retry.

## Admitted work and current validation

| Work | Cases | Accounting |
| --- | ---: | --- |
| First solves after failed preparation | 11 | No previous solver launch; each receives its first six-hour allocation |
| Recovery/scoring of stopped artifacts | 8 | No solver inference or renewed original allocation |
| Independent stgit retry | 1 | Separate second attempt; its score is excluded from the original first-attempt aggregate |

All **11 first-solve cases passed actual offline preparation and exact eligible
collection**. This includes Pandoc's 5214 tests, i3-style's 539, gdu's 1161,
age's 676, fselect's 3115 and Miller's 14637. `QUALIFIED.json` binds every complete
receipt and confirms that all 766 original frozen files remain unchanged.

Pandoc and i3-style have been admitted for real model work. Their profile is
GPT-5.6-Luna/max, 21600 seconds, no model-request ceiling, offline execution and
the original command/environment limits. The total of original case jobs,
completion jobs and qualification jobs stays within the authorized capacity
(sixteen), using one admission lock for the two completion queues. Existing
allocations survive coordinator replacement without restart or renewal.

**DuckDB's original score has already been recovered: 1354/5649 = 23.9688%.**
Its original 707,262,431-byte evaluation was complete; the older host validator's
32-MiB parsing gate prevented validation. Reprocessing that same raw artifact
verified its original evaluation-receipt and submission hashes, passed the complete
schema/identity/denominator checks, and produced all 5649 feedback entries. No
behavioral test or model inference was repeated. `REPROCESSING.json` separately
records the original evaluator/registry/pin identities and the new validation.

Stgit's retained candidate explicitly rejects `completion ... --style name-only`,
which its official test module invokes during collection. The selected remedy is
a new user-requested independent attempt with an empty task history and unchanged
solver package/prompt, rather than editing its old solution or substituting reference
behavior during grading. Its original attempt remains intact and separately reported.

## General adapter changes

The changes are in evaluation/provisioning and experiment execution. Kernel and
solver strategy are unchanged; active original solvers receive no hidden results
or runtime updates.

- Pinned grader assets can declare an explicit preparation command after candidate
  compilation and hashing. A local APT repository supplies the exact downloaded
  packages, alongside Python wheels, Go toolchains/module caches and Cargo's
  locked dependencies. Networked acquisition occurred only in host-owned preparation;
  actual qualification, grading and solving remain offline. The solver cannot
  access the grader caches or test inputs.
- Pytest observers remain importable when an official script replaces `PYTHONPATH`.
  Their admitted paths are installed through the active pytest interpreter's
  site directory. A branch with several pytest invocations now retains their
  combined collection, instead of silently replacing earlier observations.
- The pinned official catalogue selects the measured leaves and modules. Extra
  discovered tests cannot silently change the denominator. A precomputed set of
  ancestor paths preserves the same archive-file selection while avoiding repeated
  scans of the whole archive. Miller then collected all 14637 eligible tests within
  the unchanged 600-second preparation allocation; earlier attempts timed out.
- Large rendered diagnostic strings can use bounded transport with original length,
  UTF-8 digest and retained head/tail. This occurs after assertions execute and does
  not modify test outcomes, identities, retry counts, item timeouts or xdist policy.
  It addresses jq's observed execnet `string is too long` failure. Diagnostic text
  is explicitly abbreviated, not represented as fully retained text.
- Complete host-owned evaluation artifacts no longer become invalid merely for
  crossing fixed 32/256-MiB parse/hash gates. Original strict schema/duplicate-key,
  identity, full eligible-set and official-score checks still run; hashing streams.
  Parsing still uses the existing schema implementation and actual worker resources.
- Recovery confirms stopped writers before packaging. A Docker removal race that
  already ended in confirmed absence is distinct from a live writer. Terminal
  evidence is saved even when cleanup reports an error. Archived workspaces can
  be repackaged without extracting candidate-controlled paths on the host.

The original four-hour scoring allocation and existing batch/item timeouts remain
in force. No deadline extension or hidden count refund is used to make a result
look complete. If a future completion job still fails, its error remains visible
as `needs_repair`; the scheduler does not invent a score or silently loop solvers.

## Verification and retained failures

Twenty actual pytest/unit controls passed, including replaced `PYTHONPATH`, split
collection, exact catalogue scope, and large xdist diagnostic transport with an
unchanged failed outcome. Thirteen registry controls and eight canonical-host
controls passed. The host controls required the retained store binary to be supplied
explicitly after the reboot; the earlier missing-binary test errors were environmental.
Two completion-driver controls cover removal races and faithful archived-workspace
repackaging. A 33-MiB artifact control verifies that the former size rejection is
removed while inconsistent error semantics remain rejected.

The eleven real offline qualification receipts and the DuckDB reprocessing are
the end-to-end evidence for this completion work. Qualification failures encountered
while assembling the environment remain in `qualification-history/` and append-only
logs. The caches' extraction permissions and APT's dropped-capability bootstrap
were fixed before paid inference. Go-critic's gold program also needed the exact
Go 1.24.0 toolchain when run with its test archive; its offline `help` invocation
was checked before requalification.

This is running completion work, not a claim that all twenty final scores have
arrived. The first-attempt aggregate includes newly admitted first solves and
declared measurement recovery, while independent solver retries remain separate.
