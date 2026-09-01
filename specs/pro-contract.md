# ProContract

ProContract is an executor-independent settlement protocol for agent work.

It addresses one question:

> What is the system allowed to recognize as finished when the executor is
> temporary, fallible, and unable to certify itself?

This is the canonical theory document. Codex implementation details, empirical
evidence, and future succession research live in:

- [ProContract Codex implementation](pro-contract-implementation.md);
- [ProContract evidence](pro-contract-evidence.md);
- [ProContract witnessed succession](pro-contract-succession.md).

## Reading discipline

Claims use four labels:

- **IMPLEMENTED** — present in the reviewed reducer or adapter and exercised on
  its central path;
- **PARTIAL** — present, but a named assumption, platform, failure path, or
  refinement remains open;
- **FUTURE** — designed but absent;
- **NOT CLAIMED** — tempting but not entailed.

Structural claims, deployment claims, and empirical claims are different
types. A model score cannot prove an invariant. A reducer test cannot prove
verifier validity or physical process isolation.

Five events must never be collapsed:

| Event | Meaning | Force |
| --- | --- | --- |
| Passed replay | A subject satisfied finite checks in one environment | mechanical prerequisite |
| Archive winner | A search statistic preferred a candidate | none outside selection |
| Executor handoff | The executor petitions verification | outstanding |
| Discharged duty | Authorized evidence currently supports settlement | recognized completion |
| Adopted successor | A candidate becomes the canonical incumbent | **FUTURE**, not discharge |

The words "done", "verified", "trusted", and "improved" are incomplete unless
they name a subject, claim, evidence policy, environment, authority, and
ledger frontier.

## Thesis

An agent is a sequence of temporary executors. Context compaction, Session
deletion, process exit, model replacement, and human handoff can erase working
state while the duty that motivated the work remains.

Execution state is descriptive. Settlement state is normative:

~~~text
execution state
  what a process saw and did

settlement state
  what the institution currently recognizes as
  outstanding, authorized, handed off, supported, or released
~~~

ProContract separates them:

> Termination is not handoff. Handoff is not settlement. Settlement is current
> support, not permanent truth.

An executor may explore, edit, run tools, report a blocker, petition new terms,
or hand off a candidate. None of those acts can create recognized completion.
Discharge requires an authorized transition bound to exact duty and evidence
coordinates.

An accepted defeater does not erase history. It withdraws current support and
restores responsibility:

~~~text
loss of current epistemic support
        ->
outstanding normative responsibility under an identified owner
~~~

The conceptual ingredients have precedents in commitment protocols,
defeasible norms, truth maintenance, revocation, and compensating workflows.
The candidate systems contribution is their mechanized conjunction for
ephemeral executors:

\[
\boxed{
\begin{aligned}
&institution\text{-}held\ standing\\
{}+{}&no\ executor\ self\text{-}certification\\
{}+{}&exact\ subject/evidence\ coordinates\\
{}+{}&atomic\ support\ withdrawal\\
{}+{}&dependent\ responsibility\ restoration\\
{}+{}&continuity\ across\ executor\ replacement.
\end{aligned}
}
\]

The strongest present reducer claim is:

> **IMPLEMENTED at reducer level:** ProContract provides completion integrity:
> recognized completion is institution-held, exact under stated coordinate
> assumptions, and defeasible independently of executor survival.

The current SQLite store separately commits reducer projection, decision event,
sequence, and ledger head in one transaction. That is an implemented store
property, not part of the pure-reducer theorem.

It does not claim conceptual priority for any ingredient, verifier truth,
physical non-bypass, or recursive self-improvement.

## Why executor projection is insufficient

Let \(X(h)\) be the executor projection of history \(h\): visible context,
workspace, tests, process state, and trajectory. Let \(N(h)\) be the current
standing of duties, authority, subjects, and support.

Two histories may satisfy:

\[
X(h_1)=X(h_2),\qquad N(h_1)\ne N(h_2).
\]

The same candidate and test narration may be visible while one report names a
stale revision, wrong subject, revoked support, or incompatible runtime.
Any policy reading only \(X\) must behave identically:

\[
X(h_1)=X(h_2)
\Longrightarrow
\pi(X(h_1))=\pi(X(h_2)).
\]

This proves only that the current executor projection is insufficient. It does
not by itself entail an institution; richer descriptive memory could
distinguish the histories.

External normative standing follows from two additional requirements:

1. no self-certification means standing cannot be executor-writable, because
   the executor could otherwise write "discharged";
2. survival across executor replacement means standing cannot depend on one
   executor's continued existence.

Given those requirements, the distinguishing state must live in a durable
authority domain. It is normative because mediated effects and settlement are
licensed by it. This is a design-necessity argument, not a metaphysical claim
that every hidden state is institutional.

## Ontology

### Duty

A duty is an admitted obligation identified by scope, Contract ID, revision,
terms identity, issuer, and executor. It remains outstanding until authorized
discharge or release.

### Standing

Current standing is one of:

~~~text
dormant
active
verification
escalated
discharged
released
~~~

Dormant, active, verification, and escalated are outstanding. Only discharged
and issuer-authorized released duties are quiet.

### Authority

Authority has two planes:

- execution capabilities delegated while an exact revision is active;
- institutional rights to issue, amend, settle, defeat, resume, or waive.

Model-visible affordance is not authority. The authoritative execution check
occurs at a mediated effect boundary.

### Subject

A subject is a content-addressed projection handed to a verifier. It is exact
only relative to its capture function.

The current Codex subject projection skips ordinary oversized files and
symbolic links and force-captures declared artifacts. Its manifest format is
versioned, but effective capture limits are not yet bound into subject
identity. Exact-subject claims therefore trust an uncoordinated capture policy
in v1.

### Goal and claim

The goal tells an executor what to optimize. The settlement claim tells the
Principal which proposition evidence may support.

Discharge recognizes that claim. It does not assert global optimality,
complete requirement discovery, or construct validity of the verifier.

### Handoff

A handoff is an executor-authored, subject-bound petition containing summary,
uncertainties, and optional mechanical evidence.

Its narration is not evidence. ProContract does not prevent a persuasive,
incomplete, or deceptive summary from misleading a human Principal.

### Evidence policy

Evidence policy defines a frozen finite prerequisite for settlement. Changing
it changes what may support the claim, so its identity is normative.

### Execution policy

Execution policy advises how to search, probe, implement, and allocate effort.
It cannot alter duty, claim, authority, evidence requirements, or settlement.

### Attestation

An attestation is finite testimony from settlement authority. The containing
Discharge command binds it to one Contract; its fields bind revision,
specification, subject, evidence, and verifier identity.

An evidence hash establishes identity, not semantic truth.

### Challenge

A challenge is an authorized, subject-bound defeater. It withdraws current
support without deleting historical attestation. Visible challenges may guide
remediation; sealed challenges reject support without revealing holdout
contents to the executor.

### Settlement and completion

Settlement is the accepted transition from verification to discharged.
"Completion claim" means handoff. "Recognized completion" means discharged with
current support.

### Succession

Succession changes a distinguished incumbent inherited by future work.
It is **FUTURE** and not another word for discharge. The minimal boundary is
retained later in this document; the full design is in
[witnessed succession](pro-contract-succession.md).

## Philosophical foundations

### Temporary selves cannot own continuity

An invocation has no intrinsic normative continuity with its successor.
Messages and files may persist without explaining why an intention still
binds, which authority remains current, or what counts as release.

The institution, not executor psychology, carries the duty.

### Memory, duty, and support are different

~~~text
past observation -> memory      -> future attention
current intent   -> Contract    -> future duty and authority
current witness  -> support     -> recognized settlement
accepted defeater-> challenge   -> renewed responsibility
~~~

Memory may influence a future policy and still be ignored. Contract standing
continues even when the executor forgets. Support may later be defeated while
history remains true as history.

### Institutional force is scoped mediation

A schema is not a Contract merely because it is expressive. Institutional
force comes from exclusive control over recognized transitions and the effects
conditioned on them.

Today that force is coextensive with registered Codex effect paths. The local
prototype is not a universal physical institution.

### Incomplete terms require residual control

Natural-language intent and executable evidence policy cannot be identical.
Freezing evidence prevents opportunistic weakening and also freezes an
imperfect proxy.

Residual control belongs to an authority distinct from execution. The issuer
may amend or waive; the executor may petition but cannot ratify.

### Truth is supported, not stored

Specs, hashes, reports, and proofs are boundary objects. Their existence does
not prove their claims. Canonical identity prevents substitution; it does not
make the represented proposition true.

### Evidence is world-indexed

\[
E=E(subject,\ policy,\ environment,\ evaluator,\ time).
\]

Evidence produced in environment \(e_1\) does not automatically support the
same claim in \(e_2\):

\[
Support_{e_1}(c)\not\Rightarrow Support_{e_2}(c).
\]

The Amber development run supplied the same executable to Python 3.12 replay
and Python 3.10 evaluation. Replay passed; the target artifact could not parse.
The lesson is constitutive: environment identity belongs in the evidence
coordinate. Details and limitations are in
[ProContract evidence](pro-contract-evidence.md).

### Defeat has a normative consequence

Truth-maintenance systems retract support. ProContract also routes the
consequence:

\[
AcceptedDefeat(support(o))
\land Mandated(o)
\Longrightarrow OutstandingResponsibility(o).
\]

The reducer does not discover epistemic defeat. An authorized challenge tells
it that support has been defeated at an exact coordinate.

### Improvement semantics are root-relative

Each defensible comparison holds some mission semantics, evidence rule, and
authority stable across that comparison. This does not require one physical
component to remain fixed forever.

A root may change through a rolling bridge. A purely self-authorized
replacement does not inherit its predecessor's meaning of "authorized"; it
begins a new normative regime.

For one claimed continuity step:

\[
R_t=(K,\ authentication,\ canonicalization,\ storage,\ capturePolicy,
evidenceEnvelope,\ clock,\ rootAuthority)_t.
\]

## Claim ladder

### Reducer invariants

Properties of the finite transition function under already-authenticated
commands. They do not depend on model competence.

### Store and adapter properties

Properties requiring atomic persistence, role wiring, command confinement,
effect mediation, or a running recovery process.

### Empirical hypotheses

Claims about score, cost, evidence coverage, or model behavior. They are
indexed by a frozen experiment and may be falsified without changing Kernel
semantics.

### Future protocols

Environment bridges, strong process isolation, portable signatures,
incumbent adoption, and judge succession. Future claims remain future tense.

## Normative Kernel

### Algebra

The reducer is pure, total, and deterministic:

~~~text
transition(state, authenticated finite command)
  -> next state + decision + event
~~~

Its current command vocabulary is:

~~~text
issue
activate
report-ready
report-blocked
petition-revision
decide-revision
discharge
challenge
resume
escalate
release
~~~

Exact names and count are not constitutional. The irreducible categories are
admission, activation, candidate petition, residual-control decision,
settlement, defeat, and routing of outstanding work.

Rejected commands preserve authoritative state and remain ledgered.

### Lifecycle

~~~text
dormant -> active -> verification -> discharged
             |            |
             |            +-> challenge -> dormant or escalated
             +-> blocked/retry/escalation

issuer-authorized waiver -> released
~~~

Only active standing authorizes executor effects. Verification remains
outstanding. Escalation routes responsibility; it does not settle.

### Constitutional invariants

#### I1. Rejection preservation

\[
Rejected(c)\Longrightarrow state'=state.
\]

#### I2. Obligation conservation

An outstanding duty ends only by authorized discharge or release. Process,
Session, retry, blocked, revision-petition, and escalation events do not
settle.

#### I3. Residual authority

Only the issuer may approve amendment or release. Institution-only transitions
require institution actor standing.

#### I4. No self-certification

Issuer and executor are distinct. Executor testimony may reach verification,
never attestation or discharge.

#### I5. Coordinate integrity

Applicable Contract, revision, specification, subject, evidence, and actor
coordinates must match. Conflicting reuse, stale identity, and duplicate
attestation reject.

Subject exactness in v1 is relative to the trusted capture projection because
capturePolicyHash is not yet part of the coordinate.

#### I6. Evidence subordination

Let \(E\) be a finite evidence-prerequisite predicate. If configured, \(E\)
must hold for the exact handoff before discharge. Mechanical evidence cannot
double as Principal attestation.

The current v1 predicate is concrete ReplayPolicy. Interpreting argv, cwd,
timeouts, protected files, and artifact paths in the Kernel crate is
transitional debt.

#### I7. Responsibility closure

An accepted challenge withdraws current support from the target and every live
duty in the reducer-computed dependent closure. Released duties stay released;
historical attestations remain.

The reducer now tests a dependency chain of depth two. System behavior under
concurrent challenges and injected storage/process failure remains
**PARTIAL**.

#### I8. Dependency immutability and fencing

Requirements name existing duties at exact revisions. Revision cannot change
the requirement set. An outstanding dependent fences acceptance of an upstream
revision and release of that upstream duty.

Issuance order plus immutable edges prevents cycles. Graph adaptation issues a
new Contract rather than rewiring a live node.

#### I9. Revision fencing

A pending revision blocks activation, handoff, challenge, and discharge until
the issuer accepts or rejects the exact petition.

#### I10. Frontier-relative quiet

\[
quiet(scope,f)
\iff
\forall o\in scope:
status_f(o)\in\{Discharged,Released\}.
\]

Quiet names a frontier, not an eternal fact.

### Guard taxonomy

The current reducer has 64 rejection sites. They are classified as:

- constitutional enforcement;
- command well-formedness;
- fail-closed internal consistency.

The complete line-by-line mapping lives in
[Codex implementation](pro-contract-implementation.md). Future code should use
a typed rejection enum and a test that requires every variant to map to one
class and, when constitutional, one invariant.

## Completion Integrity

Define:

\[
\begin{aligned}
CI_K={}&
RejectionPreservation\\
&\land ObligationConservation\\
&\land ResidualAuthority\\
&\land NoSelfCertification\\
&\land CoordinateIntegrity\\
&\land EvidenceSubordination\\
&\land ResponsibilityClosure\\
&\land DependencyIntegrity\\
&\land QuietSoundness.
\end{aligned}
\]

Let \(\pi\) select finite commands only through \(K\)'s interface. Assume:

1. actor identities are authenticated before transition;
2. \(\pi\) cannot mutate authoritative state except through \(K\);
3. canonical encodings and hashes preserve the identities compared;
4. \(K[E]\) is the sole producer of recognized state transitions.

Then the intended reducer theorem is:

\[
\forall\pi,\quad
Traces(K[E]\parallel\pi)\models CI_K.
\]

This is guard correctness under an interface, not adversarial process
confinement.

System completion integrity additionally requires:

- atomic durable storage;
- exclusive role wiring;
- command-channel confinement;
- mediation of every protected effect;
- a live recovery/adjudication process when liveness is claimed.

The current local deployment does not establish adversarial confinement.
\(CI_{system}\) is therefore **PARTIAL**.

Representative Rust tests exist. Exhaustive model checking, guard-to-invariant
drift enforcement, concurrency/crash injection, and Rust/reference-model
refinement are **FUTURE**.

## Trust root and security boundary

The pure reducer is necessary and insufficient for system guarantees.

### Actor mapping

The reducer compares actor identities; it does not authenticate them. The
adapter determines which surfaces may construct Principal, executor, or
institution commands.

### Canonicalization

Specification and subject identities depend on one serialization, hash
algorithm, and projection grammar. These are consensus code.

### Store

SQLite commits projection, decision event, sequence, and hash head in one
immediate transaction. The chain is crash-consistent and auditable. It is not
tamper-proof against an actor able to rewrite the store and its anchors.

### Capture policy

Ignore rules, entry and byte limits, symlink behavior, and forced artifact
closure define subject identity. They must be bound by a future
capturePolicyHash.

The current implementation checks its total byte ceiling after copying a file.
Streaming enforcement is a known correctness gap.

### Environment and evaluator

The current replay report lacks image, interpreter, OS, architecture,
toolchain, evaluator, resource, and confirmed descendant-cleanup coordinates.
It records check duration and persists a timed-out negative result only after
the process API acknowledges termination. Replay remains **PARTIAL** local
preflight.

### Clock

Deadlines and leases trust host time. The reducer accepts caller-supplied
timestamps without global monotonicity checks, so authenticated time
construction belongs to the adapter trust root.

### Physical boundary

Institutional force is scoped to mediated effects:

~~~text
effect allowed
iff exact active revision
and current binding/lease
and delegated capability
and remaining shared budget
~~~

Strong non-bypass is **FUTURE**. It requires Principal credentials, ledger, and
evidence storage outside executor authority and every protected effect behind
a capability-validating boundary.

## Layer ownership

~~~text
pure settlement Kernel
  standing, authority roles, exact coordinates,
  support closure, decision, quiet

institution store and authority boundary
  actor authentication, atomic ledger, durable frontier

trusted evidence envelope
  subject capture, environment/evaluator identity,
  finite observations and provenance

execution adapter
  Session, model, tools, leases, budgets,
  recovery and effect admission

mutable policy plane
  execution guidance, compiler and probe strategy,
  candidate generation and selection

task adapter
  cleanroom, layouts, references, tests and scores
~~~

Kernel may bind edge-manifest identities. It should not interpret task
mechanics.

### Kernel admission test

A concept belongs in Kernel only when removing it permits:

- false quiet without settlement;
- executor self-certification;
- stolen authority;
- stale subject/evidence substitution;
- unsupported dependent recognition without an owner;
- an unauditable authority-changing decision.

Score, prompt style, scheduling, replay implementation, and search order remain
at edges.

## Three policies

### Execution policy

Advisory method for attempting work. It stays outside ContractSpec and
specHash. The Codex execution binding now persists the bounded instructions
with a domain-separated content hash and rejects conflicting stored identity.
That makes one exact policy observable across semantic attempts without making
it normative Contract state. Projection remains **PARTIAL** because context
paths do not yet share uniform one-shot/separate-message behavior.

### Evidence policy

Frozen prerequisite for settlement. Its identity belongs under specHash.
Current ReplayPolicy is **PARTIAL** because it is environment-blind and
filesystem/process-specific.

### Succession policy

Rules for replacing a canonical incumbent. **FUTURE**.

~~~text
execution policy -> how work is attempted
evidence policy  -> what finite support is required
succession policy-> what may become incumbent
~~~

## Evidence and knowledge continuity

Use separate symbols:

\[
\mathcal H=immutable\ history,\qquad
\mathcal J=justification\ graph,\qquad
\mathcal S=current\ support.
\]

A challenge appends to \(\mathcal H\), changes \(\mathcal S\), and may restore
outstanding duties. It does not rewrite history.

### Target evidence coordinate

\[
\begin{aligned}
\mathcal E=(&contract,\ revision,\ specHash,\ subjectHash,\\
            &evidencePolicyHash,\ capturePolicyHash,\\
            &environmentDigest,\ evaluatorDigest,\\
            &observationManifestHash,\ evidenceHash,\ authority).
\end{aligned}
\]

The Kernel binds finite identities. The evidence envelope validates concrete
commands, proofs, files, rubrics, tests, and environments.

### Trusted observation

An execution observation should record exact input coordinates, exit, bounded
output hashes, duration, timeout, resource status, descendant cleanup, and
subject/environment/evaluator identities.

Model prose may summarize an observation. It cannot replace it.

### Knowledge is not duty

Obligation conservation preserves responsibility, not hypotheses,
counterexamples, or convergence state. Those belong in content-addressed
adapter evidence.

Evidence may be inherited only when:

\[
Reuse(e,o')
\iff
Dependencies(e)\ unchanged
\lor
NonInterference(e,o')\ established.
\]

Copying an old score is not inherited assurance.

## Succession boundary

Canonical succession is **FUTURE**. Completion integrity is its settlement
substrate, not a complete reduction.

Completion is a per-duty predicate. Succession changes an exclusive mutable
incumbent and therefore additionally requires:

- uniqueness and total ordering;
- atomic replacement;
- relational incumbent/candidate evidence;
- deployment activation and rollback;
- judge/mission bridge evidence.

Current challenge closure supplies duty-support withdrawal, one prerequisite
for future retraction. It does not retract an incumbent or roll back external
deployment.

See [witnessed succession](pro-contract-succession.md) for the future register,
certificate, judge bridge, Meta^n relation, and stress tests.

## Nearest-neighbor boundary

Conceptual priority is not claimed. The novelty question is whether one prior
system combines all \(CI_K\) properties in an executor-replacement harness.
The following deltas are provisional pending a dedicated literature review:

| Family | Shared mechanism | Candidate missing property |
| --- | --- | --- |
| [TMS](https://www.sciencedirect.com/science/article/pii/0004370279900080) / [ATMS](https://www.sciencedirect.com/science/article/pii/0004370286900809) | defeasible support and dependency propagation | duty, authority, remediation owner |
| [Commitment machines](https://doi.org/10.1007/3-540-45448-9_17) | institutional debtor/creditor commitments | exact subject/evidence coordinates and defeat closure |
| [Electronic institutions](https://doi.org/10.1007/3-540-44682-6_8) / normative MAS | mediated counts-as rules and governors | subject-bound defeasible settlement under executor replacement |
| [Sagas](https://doi.org/10.1145/38713.38742) / BPMN compensation | recovery after invalidated work | recognition/support semantics and no self-settlement |
| Reopenable ticket workflows | durable assigned work and reopening | formal exact evidence and transitive support closure |
| [PKI revocation](https://www.rfc-editor.org/rfc/rfc5280) | support withdrawal without history deletion | outstanding remediation duty |
| [in-toto](https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias) / SLSA | content identity and separated functionaries | live duty and defeat-driven responsibility |
| Defeasible deontic logic | contrary-to-duty and reparative obligations | durable implemented settlement harness |

The linked primary sources were checked for this preliminary boundary on
2026-08-31. This is not an exhaustive related-work review, and no absence claim
is publication-ready until each family and its descendants are reviewed
systematically.

## Structural evaluation

Scripted actors should precede LLM evaluation:

- duplicate, delayed, and stale commands;
- self-discharge attempts;
- revision, subject, evidence, and verifier substitution;
- dependency depth and concurrent challenges;
- crash between authoritative operations;
- lease expiry and process recovery;
- sealed disclosure;
- quiet before and after defeat.

Primary structural metrics include FalseQuietRate, InvalidSettlementRate,
DutyLossRate, and ChallengeClosureRecall. They have not yet been measured over
an exhaustive trace set.

### Semantic mutation

| Removed mechanism | Expected shortest counterexample |
| --- | --- |
| issuer/executor separation | executor discharges itself |
| revision/spec binding | stale report settles new terms |
| subject binding | candidate A evaluated, B accepted |
| rejection preservation | stale command partially mutates state |
| challenge closure | unsupported dependent stays settled |
| quiet predicate | escalated duty reported quiet |
| immutable requirements | revision creates dependency cycle |
| upstream dependent fence | live dependent is stranded |

If removing a guard produces no counterexample, it may be redundant and should
not be defended rhetorically.

### Reference-model refinement

A future TLA+ or equivalent model should define Issue, Activate, ReportReady,
Discharge, Challenge, Release, Crash, and LeaseExpire. Generated traces should
compare model and Rust decision, normalized state, event, support set, and
quiet result after every command.

## Guarantees and limits

| Claim | Reducer | System |
| --- | --- | --- |
| Duty conservation | **IMPLEMENTED** | **PARTIAL:** confinement assumed |
| No executor self-certification | **IMPLEMENTED** | **PARTIAL:** Principal isolation absent |
| Exact coordinates | **IMPLEMENTED** | **PARTIAL:** capture policy unbound |
| Evidence subordinate to attestation | **IMPLEMENTED for v1** | **PARTIAL:** concrete replay debt |
| Target-environment replay validity | not reducer property | **NOT CLAIMED** |
| Dependent challenge closure | **IMPLEMENTED**, depth two tested | **PARTIAL:** no concurrency/crash refinement |
| Frontier-relative quiet | **IMPLEMENTED** | **PARTIAL:** durable store assumed |
| Mediated authority/budgets | not reducer property | **PARTIAL:** registered paths only |
| Adversarial physical non-bypass | not reducer property | **FUTURE** |
| Knowledge convergence | **NOT CLAIMED** | **NOT CLAIMED** |
| Capability improvement | **NOT CLAIMED** | empirical only |
| Canonical adoption / judge succession | not reducer property | **FUTURE** |
| Guaranteed RSI | **NOT CLAIMED** | **NOT CLAIMED** |

## Engineering principles

1. Simplicity is a correctness property.
2. Use smart edges and a dumb Kernel.
3. Conserve duty by construction.
4. Separate attention, authority, evidence, and finality.
5. Bind every recognized claim to exact coordinates.
6. Index evidence by the world that produced it.
7. Keep execution policy outside normative terms.
8. Freeze evidence policy explicitly.
9. Treat handoff as petition and replay as preflight.
10. Preserve history while allowing support to be defeated.
11. Route support loss to an identified owner.
12. Keep task mechanics and search heuristics in adapters.
13. Require counterexamples for Kernel concepts.
14. State every trust assumption and non-goal.
15. Do not let future succession language rewrite current status.

Three substitution tests guide design:

~~~text
Can a human contractor replace the LLM without changing Kernel semantics?
Can a non-filesystem verifier replace replay without changing settlement?
Can another harness replace Codex without changing the reducer?
~~~

The current answer to the second question is not yet yes because ReplayPolicy
remains concrete Kernel debt.

## Change gate

Every Kernel change must state:

- invariant enforced;
- shortest counterexample without it;
- why an edge cannot enforce the same boundary;
- focused reducer test;
- boundary integration test;
- concepts and branches added or removed.

Performance evidence may justify compiler, executor, verifier, and adapter
changes. It cannot alone justify new authority-changing Kernel semantics.

## Canonical statement

> ProContract contributes a mechanized settlement protocol for ephemeral
> executors. Recognized completion is institution-held, bound to exact
> content-addressed coordinates, closed to executor self-certification, and
> defeasible: an accepted evidential challenge withdraws current support and
> restores outstanding responsibility across dependent duties. Reducer
> guarantees hold under authenticated command-interface, canonicalization, and
> sole-transition assumptions; system guarantees additionally require atomic
> storage, command confinement, role isolation, and complete effect mediation.

Shortest form:

\[
\boxed{
Executors\ propose;\quad
evidence\ supports;\quad
authority\ settles;\quad
accepted\ defeat\ restores\ responsibility.
}
\]
