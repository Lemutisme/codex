# Fine-grained native Codex harness evolution

Astra phase3 separates22 capabilities into working mechanisms, use/visibility
gaps, implementation defects and unadopted candidates. The detailed matrix is
[capability-matrix.md](capability-matrix.md). It uses new native Codex trajectories,
not historical OpenCode outcomes.

The inspected eight paired archives contain no `compacted` event. Several
successors successfully recovered earlier counterexamples and corrected stale
plans by rereading current code. This does not prove all information survived;
it does rule out presenting compaction loss as the demonstrated cause of these
regressions. Initial strategy text and actual original/forwarded payload hashes
matched in the four inspected ProContract cases.

Priority mechanisms:

1. Current-state/context views: distinguish current subject/build/operation facts
   from prior claims, interpretations and selected work. Strategy decides which
   history and uncertainty matter; the harness exposes reliable identities/views.
2. Retention and retrieval: contract evidence paging works. A truncated arbitrary
   tool result does not yet automatically expose a usable full-output handle;
   an audit hash alone is not a retrieval capability. Any new page reader must
   remain within the original task's observation permissions and limits.
3. Tool invocation/result fidelity: preserve actual executable, argv, stdin, cwd,
   relevant environment, exit/completion state and output coverage. Direnv's
   candidate trusting inheritedPWD is a concrete hypothesis about artifact logic,
   not evidence that the tool failed to set cwd.
4. Asynchronous ownership: publication activity, unresolved effects and controller
   resting are different. Waiting must use the existing owner and recheck the
   original selection on a precise completion event, without replaying effects
   or renewing an allocation. Native implementation qualification remains pending.
5. Verification and receipts: expose already retained execution evidence to the
   process obligation that needs it. Strategy chooses check/diagnose/verify and
   preserves useful local findings; no universal full-review or sample-count gate.
6. RSI: reuse source capture/import/inbox/selection/resolved-input capabilities.
   Knowledge or a candidate file is not evidence that a later task used that
   version. Current candidates remain outside the frozen comparative cohorts.

Two additional grader defects were diagnosed during this status review and a
repair prepared for independent artifact-only recovery:

- PHP's suite allowance is3 hours but the pinned container keeper is `sleep 2h`.
  Four observed large-branch executions ended after about7196 seconds with the
  container gone, losing the terminal test/observation receipts. A new keeper
  follows the original owner deadline, with a separately declared cleanup grace;
  absent deadlines remain absent. Test-body timeouts and retry rules are unchanged.
- Wrapcheck's compile succeeded and produced an independent Go binary with mode
  0111. In-container SHA256 then failed on read permission. Trusted Docker archive
  reading hashes the bytes without chmod or host extraction, preserving the
  executable mode. This is an artifact-read capability, not a candidate repair.

37 adapter controls pass; two optional environment-dependent controls were skipped.
The new recovery jobs require an actual private-container control before grading:
execute a mode0111 ELF, confirm in-container reading fails, hash it through the
trusted transport, and verify its mode and execution remain unchanged. The new
owner deadline is checked in the effective container command. Those controls run
inside the admitted measurement slot, not alongside unaccounted benchmark jobs.

The recovery plan and qualification bindings are retained here. Original solver
packages, source archives and failed measurements remain unchanged. Actual native
publication fixes and the proposed context changes are not installed in the live
model cohorts.
