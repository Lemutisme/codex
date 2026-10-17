# Scoped obligations and host observations

Implementation extends `87beae267`. The settlement reducer in `codex-rs/pro-contract`
is unchanged. Validation lives at `/data/ProContract/obligation-evolution-validation-20261017`.

## Problem and invariant

Three frozen native diagnostic runs produced correct code/data artifacts and a sound
small mathematical proof, while final review could not name process gaps with legal IDs.
Content requirements had IDs; execution constraints had text only. Complete feedback
reads existed in native transcripts but were not available to the reviewer as host facts.
One theory run also actually missed the successful initial-publication step.

The repair follows one boundary: an obligation has a stable reference and an assessment
scope; evidence supports only its recorded scope; uncertainty and method failure do not
become artifact counterexamples or new authority.

## Representation and compatibility

`Terms::obligations()` derives a catalog from the original frozen terms. Content IDs are
retained. Host-generated process IDs use a disjoint prefix, extended if a legacy content
ID collides. Original quotes and inference status remain visible. Catalog references are
bound by the terms hash; changed terms require the existing revision mechanism.

No field is inserted into historical serialized Terms, and no historical hash is rewritten.
Legacy execution constraints did not record whether their wording was inferred; the view
reports that status as unknown (`null`), rather than inventing a false/explicit value.
The review protocol has a new method identity and generates schemas with exact legal-ID
enums. Its `requirement_id` wire field remains readable for compatibility and now names
either kind of obligation. Historical records without the new host observations do not
retroactively gain process evidence.

The host derives execution-obligation membership when parsing a review. A model cannot
mark an artifact counterexample as a process claim by supplying that metadata. Local
coverage, findings and gaps remain distinct. Missing process coverage prevents full
Support. An execution finding alone produces an explicit blocker and leaves the artifact
available; it does not instruct a new executor to rewrite files to undo a past action.

## Observation boundary

The archive's read/query semantics stay separate from native observation. The Codex adapter
records a response preparation before returning its value and a distinct native tool
lifecycle completion afterward. Records bind the task, caller thread/turn/call, code-mode
cell/nested invocation, source digest, byte range and returned-byte digest. No raw tool
arguments or shell commands are added to the journal.

Only an actual matching completion can attest successful native access. A crash, cancelled
call, missing completion or failed receipt commit stays unconfirmed. Restart cannot infer
completion from a prepared response. A persisted per-task 4096-receipt allowance bounds
this observer; new sessions cannot renew it. Observation failure does not manufacture
evidence that a required action occurred.

The reviewer sees a frozen observation prefix ending at the matching delivery/publication
capture, together with bounded baseline comparison. The boundary binds subject, terms,
turn and execution epoch. Later calls or completions cannot silently enter an earlier
certificate. The Support evidence hash binds the committed verification event and thus
the observation document it references.

The current adapter observes feedback access and publication/capture facts. It does not
attest mental comprehension, complete execution history, all network activity or dependency
installation. Baseline equality proves bytes/mode at two boundaries, not absence of
intermediate edits. Missing capability remains a real evidence gap. Additional adapters
can provide other scoped observations without adding task-specific kernel commands.
The current artifact-computation capability cannot attest execution history, even when
its program exits successfully and names an execution-obligation ID. Positive execution
coverage must cite scoped host observations; artifact computations remain available for
artifact claims and exploration.

## Protocol correction and authority

A malformed response can receive one corrective turn in the same reviewer session. The
evidence catalog, issued citations, read/computation budgets and original monotonic deadline
are preserved. Admission time is included in that deadline. The correction instruction
does not prefer Support and explicitly preserves findings and unknowns.

A durable reservation precedes dispatch; both failed and final protocol results are linked
to the assessment. Large malformed output is retained with an explicit bound, original hash
and byte count. A valid partial, negative or unknown judgment is not a formatting failure
and does not trigger this retry. A second malformed response stops without a new session,
grant or kernel transition.

## Verification targets

Unit tests cover unchanged historical Terms bytes, ID collisions, exact schema enums,
process gaps retaining artifact coverage, execution findings not authorizing artifact
repair, subject-bound process citations, self-attestation refusal, prepared versus completed
access, restart uncertainty and the immutable handoff cutoff.

Native app-server/code-mode/Docker tests cover root access, deliberately omitted access,
successor access, one successful correction retaining old citations/session, and correction
exhaustion. The existing delivery, progress, resource, deadline, partial judgment,
computation, PTY, restart and scope scenarios remain part of qualification. A first native
run caught default `functions` namespace normalization in code-mode lifecycle callbacks;
the failure is retained and the adapter corrected.

Controlled validation passed 36 kernel, 180 extension and 40 store tests and 59 Python
regressions. All 19 native scenarios passed before the final inference-status metadata
correction and citation-scope tightening; the complete Rust suite passed again afterward.
The final package receives a repeat of the native scenarios plus a bounded three-case
real-model follow-up. The external validation report
retains the exact source/binary identities and version-specific results.

These tests qualify the implemented boundaries. They do not establish arbitrary task
completion, all process properties, formal proof correctness or a leaderboard gain.
