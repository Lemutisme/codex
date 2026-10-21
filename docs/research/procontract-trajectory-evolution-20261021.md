# Evolution from the October 21 trajectories

This change addresses observed interface and lifecycle failures without adding a
kernel command or a mandatory research/retry workflow. The pure responsibility
kernel, original benchmark artifacts and their scores remain unchanged.

## Observed causes

The frozen cohort used source `5a453049c`, GPT-5.6-Luna/max, one solve per instance,
six-hour/1000-request shared limits and offline execution. Valid first evaluations:
scc 266/464, trdsql 1059/1312, lnav 224/989. These positive artifact results remain
valid despite internal non-Support. All three stopped after about 84.4 minutes
when their last upstream requests disconnected within four milliseconds.

The additional audit reads actual model tool calls rather than inferring causes
from final scores:

- Twenty diagnostic workers made 645 tool cells. Their initial sequential
  single-entry directory reads consumed 257 cells; the median was 14 per worker,
  with up to 51.9 seconds before a non-index action. This was transport/discovery
  overhead within the chosen 60–180 second diagnostic allocations.
- Several workers sent empty obligation scopes or non-file IDs to computation.
  The adapter reserved a computation slot before validating those arguments, so
  rejected requests exhausted execution capacity without executing anything.
- The one attempted diagnostic checkpoint had useful observations and scoped
  judgments. It was rejected solely because its redundant top-level `missing`
  field was absent. No checkpoint was retained in the original cohort.
- Native worker/child execution errors were flattened into reviewer inability or
  no handoff. The runner treated any idle controller as a natural terminal point.
  Actual task completion, an execution failure and a substantive judgment were
  insufficiently distinguished at this boundary.

The upstream service/tunnel cause itself is not established by local evidence.
The observed issue here is how a failed attempt is represented and resumed.

## Changes and ownership

| Layer | Change | Retained boundary |
| --- | --- | --- |
| Harness evidence transport | Bounded multi-entry catalog pages; exact inspection paths; lossless interning of repeated request quotes | No additional evidence authority, omitted obligations, larger reply cap or universal sample gate |
| Harness computation | Scope/schema validation before reservation; obligation-ID vocabulary and canonical file-ID syntax | Every admitted attempt stays spent; unknown effects still require reconciliation |
| Harness review protocol | Derive missing evidence from affected judgments; accept historical global gaps | No relaxation of citation binding, unknown judgments or full-obligation support requirements |
| Harness lifecycle | Distinct native execution-interruption outcome for root, reviewer and successor | User abort remains distinct; no renewed grant, fabricated handoff or automatic retry policy |
| Gateway | SQLite closure synchronized with writers and late callbacks fenced | Failed/incomplete model requests remain charged |
| Strategy | Page/batch evidence reads, preserve early local judgments, discriminate variable observations, choose continuation from retained state | Workflow remains replaceable context; no task-ID or timing-field filter in code |

The compact catalog is a view of existing frozen terms. It references the
separate original request and stores each exact quote once. Historical terms and
their identities are not rewritten. The single-entry `index` operation remains
available for old clients; `list` improves transport without prescribing which
files a reviewer should inspect.

The current native API already permits an authorized `turn/start` after
`thread/resume`. The new interruption classification preserves what happened;
the recovery tests exercise that operation under the same responsibility and
original request/time allocation. This is not an unattended recovery coordinator.
Waiting, changing methods or requesting a continuation remains strategy work.

## Validation

- 212 extension Rust tests passed. New controls cover bounded catalog paging and
  cursor completeness, exact quote/scope preservation, local checkpoints without
  a redundant aggregate field, validation before execution reservation, and the
  distinction between execution interruption and a review judgment.
- Production binaries built; targeted Clippy passed with warnings denied. An
  initial prompt-size regression was fixed by shortening the protocol text rather
  than increasing the existing prompt bound.
- 36 gateway/runner Python tests passed. A concurrent SQLite trigger/owner-close
  test verifies serialization, retention of the admitted request and rejection
  of new dispatch after close. Late callbacks cannot use the closed connection.
- Seven native scenarios passed, plus the native diagnostic timeout/continuation
  scenario. They include 503 injection into the initial executor, reviewer and
  successor, shutdown/restart/resume, one Issue, unchanged native grant, and
  unchanged gateway start/deadline with the failed request still counted. Existing
  cancellation, open-ended succession, finite deadline shutdown and actual frozen
  computation remain covered. Four affected native scenarios were repeated after
  the gateway/fixture closure fixes and passed.

## Real-model qualification and retained setup failures

Two native diagnostic controls use real Luna/max reviewers with scripted drafting
and execution. The diagnostic allocation is 60 seconds. One control is a focused
artifact mismatch; the other has a 6223-byte request, twelve redundant obligations
on the same artifact and 48 background files, to exercise catalog transport. The
latter is a representation stress control, not a naturally drafted contract.

The focused control retained a checkpoint, returned a valid partial review with
a concrete finding, and later obtained formal Support. It used nine real model
requests and about 49 seconds for the complete control. An inherited fixture
asserted the old serialized `defeat` variant rather than allowing a valid scoped
`partial` finding. Its original assertion failure remains; a read-only audit
qualifies the actual native records without another model run.
The diagnostic itself used four model requests over 12.6 seconds; catalog
discovery occupied one model tool cell.

The first dense control retained a checkpoint but its scripted executor ignored a
yielded code-mode cell after 31 seconds, advanced prematurely and canceled the
pending publication. The harness correctly kept those unresolved effects visible.
The control also crashed during gateway teardown (exit 139). Source inspection
found SQLite close was unsynchronized with callback writes; a native crash
backtrace has not established that race as the unique crash cause.

The scripted fixture now waits for yielded cells before advancing. The corrected
dense control, with the same 60-second diagnostic allocation, retained a checkpoint,
returned a valid partial review and reached formal Support. Its eighteen real
responses completed, with about 97.3 seconds for the entire control including
execution, diagnosis, repair and formal review. The original canceled control is
preserved separately; these are interface qualifications, not selected solver
scores or a causal benchmark comparison.
Its diagnostic used eleven model requests over 47.1 seconds and one catalog
discovery cell. These intervals measure first request through final diagnostic
response, not the complete task runtime.

One additional fresh full-model code E2E runs through the actual ProCodex entrypoint
with all roles on Luna/max. Its frozen JSON Pointer task has 44 external cases and
four public checks. Native and gateway task deadlines are absent; a separate
900-second qualification supervisor watchdog is declared. The delivered artifact
passed all 44 frozen external cases. Independent formal review found a real
escaped-lone-surrogate output failure not covered by the public checks; a successor
fixed it under the same responsibility. Three separate post-solve regression cases
confirm that repair and following-line continuation without modifying the original
44-case score.

This run used 77 requests (75 complete Luna/max responses and two incomplete
streams). Its executor selected one 30-second diagnosis, which timed out without
a checkpoint. At the predefined 900-second supervisor cutoff, the repaired
artifact had been naturally handed off but final review was still running;
internal Support is false. The artifact result is successful, and the diagnostic
timeout/final-review latency remain visible limitations. This is not a naturally
completed acceptance cycle or evidence that every diagnostic now succeeds.
The full-model run used the same native binaries/policies before the Python gateway
close fix; the corrected live control and closure tests exercise that later fix.
No official benchmark task was rerun, and no benchmark improvement claim follows.

## Remaining work

These changes remove observed overhead and failure modes. They do not make every
diagnosis useful or every supported artifact correct. The original cohort's
timing-sensitive comparisons and local-green/low-external-score gap still require
better property selection and coverage exploration. Strategy now addresses those
observations; no program-specific normalizer was added to the comparator.

The legacy Principal's final-review/succession scheduling and an unattended RSI
coordinator remain separate migration work. This change supplies clearer outcomes
and usable operations rather than moving that workflow into another code engine.

Artifacts: `/data/ProContract/procontract-trajectory-evolution-20261021`.
The diagnostic trace/cost audit, source snapshots, original failed controls,
`native-controls*.json`, `native-diagnostic`, `live-diagnostic-controls*`,
`full-model-e2e`, and final qualification/provenance receipts retain the evidence.
