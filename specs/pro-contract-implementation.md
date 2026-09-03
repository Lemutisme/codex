# ProContract Codex implementation

This document maps the Codex implementation to the ProContract theory. It is
implementation evidence, not the constitutional definition of ProContract.

The mapping was refreshed after rebasing the prototype branch onto
`origin/main` at `a9519cbcd` and adapting it to the borrowed `ToolCall` API.
Update this coordinate whenever implementation changes invalidate line
references.

## Layer map

| Layer | Codex owner | Current role |
| --- | --- | --- |
| Pure reducer | `codex-rs/pro-contract/src/kernel.rs` | finite status and command transitions |
| Specification types | `codex-rs/pro-contract/src/spec.rs` | duty terms and current concrete ReplayPolicy |
| Subject projection | `codex-rs/pro-contract/src/subject.rs` | bounded content-addressed filesystem subject |
| Institution store | `codex-rs/pro-contract/src/ledger.rs` | atomic projection, rejection, event, and hash head |
| Execution binding | `codex-rs/ext/pro-contract/src/binding.rs` | Session, attempt, lease, budget, policy identity |
| Evidence runner | `codex-rs/ext/pro-contract/src/replay.rs` | local materialization and replay |
| Lifecycle adapter | `codex-rs/ext/pro-contract/src/runner.rs` | activation, Session dispatch, recovery |
| Effect admission | `codex-rs/ext/pro-contract/src/lib.rs` | provider/tool gates and capability projection |
| Principal boundary | `codex-rs/ext/pro-contract/src/principal.rs` | model-invisible settlement authority |
| App-server adapter | `codex-rs/app-server/src/request_processors/pro_contract_processor.rs` | experimental Principal RPC |

## Guard taxonomy

Every reducer rejection belongs to exactly one primary class:

- **C — constitutional:** removing the guard permits false settlement, stolen
  authority, substituted identity, unsupported recognition, or lost duty.
- **W — well-formedness:** the command cannot be interpreted as one finite
  protocol operation. It may support a constitutional invariant without being
  a separate invariant.
- **D — defensive consistency:** a projection that was already read became
  internally impossible while constructing the cloned next state. These guards
  fail closed; they do not define valid external behavior.

Every rejection also preserves state under I1. The table maps its primary
purpose so that the invariant set can be audited without promoting all
implementation checks into constitutional concepts.

## Kernel rejection audit

| Line | Rejection | Class | Invariant or role |
| ---: | --- | :---: | --- |
| 243 | only issuer may issue | C | I3 residual authority |
| 246 | issuer and executor must differ | C | I4 no self-certification |
| 249 | specification hash mismatch | C | I5 exact coordinates |
| 252 | empty identity or scope | W | canonical command identity |
| 255 | invalid Contract specification | W | finite specification |
| 265 | conflicting existing Contract | C | I5 identity/idempotency |
| 269 | self dependency | C | I8 acyclic dependency |
| 272 | required Contract absent | C | I8 dependency identity |
| 275 | required coordinate mismatch | C | I5/I8 |
| 278 | required Contract released | C | I8 live support |
| 306 | target Contract absent | W | command target |
| 309 | forged institution command | C | I3/I4 actor authority |
| 317 | non-issuer challenge | C | I3 defeater authority |
| 320 | challenge during pending revision | C | I9 revision fence |
| 323 | challenge outside adjudication | C | lifecycle enabledness |
| 331 | challenge coordinate mismatch | C | I5 exact coordinates |
| 334 | invalid challenge evidence | W | finite evidence reference |
| 340 | visible challenge without summary | W | disclosure contract |
| 343 | sealed challenge with summary | C | sealed disclosure boundary |
| 351 | missing dependent projection | D | cloned-state consistency |
| 385 | command after terminal settlement | C | I2 terminal immutability |
| 401 | handoff outside active revision | C | I2/I5 effect standing |
| 404 | handoff during pending revision | C | I9 revision fence |
| 410 | handoff/spec/subject mismatch | C | I5 exact coordinates |
| 414 | required replay absent | C | I6 evidence prerequisite |
| 415 | unsolicited replay supplied | C | I6 frozen evidence policy |
| 422 | replay coordinate mismatch | C | I5/I6 |
| 429 | missing handoff target projection | D | cloned-state consistency |
| 467 | blocked report outside active revision | C | lifecycle enabledness |
| 470 | invalid blocked report | W | finite reason and revision fence |
| 474 | missing blocked target projection | D | cloned-state consistency |
| 490 | revision petition by non-executor | C | I3 residual authority |
| 493 | duplicate or reasonless petition | W | I9 single pending petition |
| 499 | invalid revision hash or rewired requires | C | I5/I8 requirement immutability |
| 502 | invalid proposed specification | W | finite specification |
| 506 | missing petition target projection | D | cloned-state consistency |
| 523 | revision decision by non-issuer | C | I3 residual authority |
| 526 | decision without pending petition | C | I9 revision fence |
| 529 | revision decision coordinate mismatch | C | I5/I9 |
| 534 | revision blocked by live dependent | C | I8 upstream fencing |
| 541 | missing revision target projection | D | cloned-state consistency |
| 559 | activation outside dormant revision | C | lifecycle/I5 |
| 562 | pending revision or expired deadline | C | I9/effect authority |
| 565 | trigger not ready | W | activation condition |
| 577 | dependency not currently evidenced | C | I8 live support |
| 581 | missing activation target projection | D | cloned-state consistency |
| 594 | resume by non-issuer or non-escalated duty | C | I3/lifecycle |
| 597 | resume coordinate mismatch | C | I5 |
| 600 | resume during pending revision | C | I9 revision fence |
| 604 | missing resume target projection | D | cloned-state consistency |
| 624 | invalid escalation coordinate or reason | W | finite routing command |
| 628 | missing escalation target projection | D | cloned-state consistency |
| 645 | release by non-issuer or without reason | C | I3 residual authority |
| 648 | release coordinate mismatch | C | I5 |
| 651 | release blocked by live dependent | C | I8 upstream fencing |
| 658 | missing release target projection | D | cloned-state consistency |
| 673 | discharge without handoff | C | I2/I4 petition boundary |
| 676 | discharge outside verification or during revision | C | lifecycle/I9 |
| 679 | discharge by non-issuer/verifier | C | I4 no self-certification |
| 687 | attestation coordinate mismatch | C | I5 exact coordinates |
| 690 | duplicate attestation identity | C | historical identity |
| 694 | configured replay missing at discharge | C | I6 evidence prerequisite |
| 704 | replay unsupported, stale, or reused as attestation | C | I5/I6 |
| 711 | missing discharge target projection | D | cloned-state consistency |

The audit is complete for the 64 rejection sites in the reviewed reducer.
Future implementation should replace free-form rejection strings with a typed
reason enum and require every enum variant to map to one class and, for class
C, one constitutional invariant. That would make this audit mechanically
drift-detecting.

## Constitutional dependency rules

Three guards were previously implicit in the implementation and are now
explicit theory:

1. requirements cannot change across revision;
2. a live dependent fences acceptance of an upstream revision;
3. a live dependent fences release of its upstream duty.

These rules make issuance-order acyclicity durable across revision. They also
create deliberate rigidity: graph adaptation issues a new Contract instead of
rewiring a live node.

## Test mapping

### Reducer

Current focused tests cover:

- executor self-settlement and subject substitution;
- replay/attestation evidence separation;
- failed replay and exact negative evidence;
- revision-decision coordinate binding;
- requirement immutability across revision;
- upstream revision/release fencing by a live dependent;
- challenge closure across foundation -> integration -> delivery;
- subject capture including forced ignored/large artifacts;
- atomic persistence of accepted and rejected events.

The dependency-depth test establishes reducer-level traversal beyond the
single-edge case. It does not establish correctness under concurrent challenges
or storage/process failure.

### Adapter

Current focused tests cover:

- shared turn, action, and attempt ceilings;
- spent-budget preservation across revision;
- failed native replay reopening the exact duty;
- replay timeout becoming exact negative evidence rather than verifier
  unavailability;
- subject-capture failure escalating without fabricated evidence;
- native handoff without self-settlement;
- sampling denial and bounded provider windows;
- tool denial before handler start;
- Principal RPC issue/handoff/attest;
- executor-visible challenge continuation;
- rejected-revision same-attempt continuation;
- execution-policy projection in representative Session requests;
- domain-separated policy identity across challenge attempts and fail-closed
  rejection of a conflicting stored hash.

### Missing integration evidence

- accepted revision and fresh executor dispatch;
- Resume and Release RPC behavior;
- sealed-challenge focused path;
- crash/lease recovery and duplicate-dispatch races;
- inline auto-compaction admission and accounting;
- remote executor subject capture and replay;
- Windows-portable replay commands;
- subject byte limit enforced during streaming read;
- backward-compatible persisted InternalSessionSource decoding;
- target environment/evaluator identity in evidence coordinates.

## Current implementation limits

The current local adapter is cooperative. It does not isolate the Principal
credential, SQLite ledger, or evidence store from a same-user shell process.
System-level adversarial non-bypass is therefore not established.

Replay is local preflight. Its report records duration and persists timeout
only after the process API acknowledges termination, but omits environment
identity, interpreter, OS/architecture, resource usage, and confirmed
descendant cleanup.

Until replay can materialize and execute the frozen subject in a named target
environment, a target-aware adapter must keep local replay and deployment
evidence separate:

~~~text
worker handoff
  -> exact subject materialization
  -> trusted target build/startup preflight
       fail -> content-addressed report -> executor-visible challenge
       pass -> target-bound evidence -> independent semantic evaluation
  -> Principal attestation or challenge
~~~

The preflight report must bind the handoff subject, target image/environment,
commands, exit, bounded output, and verifier identity. It must run on a copy of
the subject and cannot silently mutate the handoff. A local replay pass alone
must not authorize Principal attestation when the Contract's deployment claim
is target-specific.

This is not hypothetical hygiene. A Jot development candidate passed Python
3.12 local replay while importing `tomllib`, then scored 29/752 because the
Python 3.10 target could not import it. The Kernel correctly preserved the duty
after challenge; only a target adapter could have prevented the unsupported
handoff from reaching semantic evaluation.

A test-blind target startup preflight reproduced the distinction with only
`compile.sh` and `executable --help`: the unsupported subject failed immediately
and a self-contained comparison subject passed. The frozen report is
`/tmp/procontract-target-preflight-20260903/RESULT.md` (SHA-256
`0fb21d66187ea578bad6c7bd1e5765c26e25c0b8ca41c319a112bd67ca6f2c97`).

Execution policy is outside ContractSpec. Its binding now stores a
domain-separated content hash, but context projection is not yet uniformly
one-shot across all context-building paths. Policy lineage, comparison, and
adoption remain absent.

The native implementation does not contain a canonical incumbent register,
atomic adoption, deployment rollback, policy lineage, or judge succession.
