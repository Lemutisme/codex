# Shared review evidence and obligation scope

The previous all-model difference-constraints solve passed 111 external checks, but
its valid 4,848-byte reviewer response failed inside the harness: 19 conclusions
reused five quotations, and repeated inline expansion exceeded 64 KiB. Its draft
also duplicated program runtime behavior as an agent-history obligation.

Resolved reviews now contain a shared citation table. Each coverage row references
the content-derived identity of a host-bound citation: subject, terms, source,
source hash, byte range and exact quotation. Repeated reads of the same range share
the same identity. Existing immutable review/checkpoint storage, public paging and
diagnostic continuation preserve the table, so this needs no new store or kernel
transition. Previously retained inline reviews remain readable.

The 64 KiB model-response allowance remains. Host-derived evidence uses its existing
read capability bounds and is no longer rejected as if it were model prose. Issued
citation checks, execution-source restrictions, and rejection of local invalid
support are unchanged. A model-supplied table cannot replace host-issued evidence.

The drafting and reviewing strategy now resolves subject, actor and time before
classifying obligations. Delivered program behavior belongs to artifact assessment;
required actions by the agent/tools during the assignment require historical
evidence. Providing tests does not imply an additional requirement to have executed
them. Actual required executions and prohibitions remain obligations. This is
context-level interpretation, not a keyword classifier or a new kernel rule.
The workflow context also considers observed diagnosis cost and retained work after
timeouts; no universal action duration or automatic retry was introduced.

Validation before benchmark admission:

- 218 extension Rust tests and targeted Clippy pass. Regressions cover 19 repeated
  quotations, distinct host evidence exceeding 64 KiB, stable subject/terms binding,
  persistence, legacy formats and independent local failures.
- A native baseline control reproduces the old citation-expansion failure. The
  new binary reaches Support on the same 19-claim fixture without raising a limit.
- Six native controls pass, plus a diagnostic timeout/continuation control that
  retrieves both a supported review and its checkpoint through native public paging
  and verifies their shared citation content and subject identity.
- Four separate real GPT-5.6-Luna/max drafts correctly classify runtime properties,
  explicit work history, proof properties and runtime prohibitions. Each case has
  one call, with no retries. These are strategy probes, not full solves or proof
  verification; they do not establish universal semantic classification accuracy.
- Production binaries build successfully. Initial prompt-length and test-literal
  failures and the first Clippy rejection are retained in qualification logs.

Qualification artifacts: `/data/ProContract/procontract-shared-evidence-20261021`.
Prospective ProgramBench cohort:
`/data/ProContract/programbench-shared-evidence-20261021`. Selection is frozen before
task inference: LuaJIT, ripgrep and treemd, one fresh solve each, GPT-5.6-Luna/max,
six hours, 1000 shared provider requests, offline task containers and 180-second
commands. Original scores, failed calls and trajectories are retained. This is
neither a paired causal ablation nor an official Vals submission.

The pure kernel and store are unchanged. Existing code still selects portions of
the Principal workflow; this patch does not claim complete strategy/harness
decoupling, zero model invocation errors, or proven arbitrary-horizon improvement.
