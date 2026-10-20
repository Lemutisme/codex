# Focused diagnosis, retained judgments and continuation

This implements the current evolution before revisiting RSI. The responsibility
kernel and RSI implementation are unchanged. Existing snapshots, task grants,
evidence access and the experiment journal carry the new capability; no additional
workflow engine or mandatory review sequence is introduced.

`publish_progress` accepts an optional diagnostic `question`, `assessment_secs`,
and `continue_from` alongside `review: true`. The caller chooses the question and
allocation. The harness clamps work to the original task/current-owner grant.
Repeating an identical request ID recalls the result; changed work needs a new ID.
The question does not create a new contract obligation.

Diagnostic reviewers can call `record_review` before their final response. Each
explicit checkpoint uses the existing obligation/citation validation and is
committed before acknowledgment. Checkpoints remain readable even when the worker
times out. They are scoped reviewer judgments, not host proof, final Support or
settlement. The final review and its failure remain separate; checker failures
no longer hide an independently occurring reviewer timeout in the public record.

A continuation can use an earlier public assessment or checkpoint as historical
context, including retained inspections. Prior judgments cannot be cited as current
artifact or execution proof. Complete public checker receipts may be reused when
subject, revision, policy, environment/inputs and harness identity match. A changed
subject is checked anew. This is continuation from persisted work, not restoration
of hidden reasoning or renewal of the original task deadline.

The work-method and reviewer prompts choose the focus, when to save a useful
judgment, whether to continue, and how much depth to pursue. These choices remain
replaceable context. Formal acceptance and the legacy Principal orchestration
remain separate; this change does not claim that all historical workflow coupling
has already been removed.

## Validation

- 199 extension Rust tests passed, including durable checkpoint recall, citation
  checks, invalid-result isolation, historical-context scope, unchanged-check reuse,
  changed-subject rechecking and original-deadline clamping. Production build and
  targeted Clippy with warnings denied passed.
- 23 existing native app-server/code-mode/Docker scenarios passed. A new native
  scenario exercises a reviewer checkpoint followed by a real timeout, public
  retrieval, continuation, duplicate request recall, version change and final
  acceptance. It verifies that only final handoff produces Propose/Support.
- Nine launcher configuration tests passed.
- Native testing caught a real response-format bug in the first implementation:
  appending budget data as another text block produced concatenated JSON in code
  mode. Remaining time now lives inside the existing JSON object. The original
  failures, a fixture-role-detection failure and the prompt-length regression are
  preserved; the prompt was shortened without raising its limit.

## Two fresh real-model tasks

Both used the default strategy, GPT-5.6-Luna/max for every model role, a shared
900-second task maximum, no request ceiling and offline tools. Neither prompt
mandated a diagnostic workflow. Each had one solve and an immutable natural
delivery. They are synthetic capability E2Es, not ProgramBench or a matched
performance ablation.

| Task | Requests | Seconds | Retained artifact | Internal result |
|---|---:|---:|---|---|
| Lexicographically minimal precedence order | 31 | 195.4 | 64/64 frozen external cases; initial implementation 51/64 | Support |
| Correct a nonsymmetric quadratic-form argument | 46 | 307.9 | 6/6 preregistered criteria in assistant analytical review | Support |

The mathematical review is neither formal verification nor human review. The
proof establishes the symmetric/skew decomposition, the zero set `ker(S)`,
semidefinite Cauchy-Schwarz, and explicit counterexamples for the corresponding
claims about a nonsymmetric `A`.

The theory executor selected a 60-second progress allocation. Its reviewer
committed a real diagnostic checkpoint before timing out. The checkpoint survived,
the timeout remained visible, and a later independent final review supported the
delivered proof. The code task completed without a progress publication. These
runs validate live checkpoint use, not a causal improvement in task scores or
autonomous use of every continuation option. Explicit continuation and budget
selection also have the controlled native E2E evidence above.

Accounting: 76 complete Luna/max responses and one charged incomplete stream
associated with the theory diagnostic timeout. No final review protocol correction
was needed in these two solves.

### Test-driver condition correction

The live cohort's plan declared 180-second commands, but its driver edited the
environment file after `thread/start`. The already loaded environment retained
the native 1800-second command limit, observed on the theory container. The shared
900-second task maximum and offline execution did apply. The artifact scores and
checkpoint observations remain valid under those actual conditions; this cohort
does not qualify a 180-second command profile.

The original plan, scripts and results remain unchanged. A corrected staging
driver prepares configuration before app-server admission and is retained for a
future separately frozen cohort; it has not launched another paid solve. The
native diagnostic regression now asserts the actual admitted Docker command has
the 180-second limit and network=none. That complete native scenario passed after
the correction, with no new model calls.

All records are under `/data/ProContract/procontract-evolution-20261020/`:
`native-final/`, `native-regressions.json`, `live-e2e-analysis.json`, and the
original `live-e2e/runs/*/RESULT.json`. The proof assessment is separately stored
as `manual-review.json`; it does not overwrite the initial pending-review record.
The live plan's 264 frozen files remain unchanged. Development snapshots and
earlier failed qualifications are retained.
