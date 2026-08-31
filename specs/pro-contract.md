# ProContract

ProContract is an executor-independent settlement protocol for agent work and a
foundation for witnessed succession.

This document states the theory, trust boundary, current Codex implementation,
empirical evidence, and designed extensions of ProContract. It is intentionally
stricter than a product overview. A claim in this document must remain
meaningful if the LLM executor is replaced by an arbitrary human contractor.

The implementation status in this document refers to the reviewed prototype
branch "codex-procontract-native-envelope" at commit "6b1f3b9df" on
2026-08-31.

## Reading discipline

Normative and capability claims use one of four labels:

- **IMPLEMENTED** means the reviewed Codex code contains the mechanism and
  focused tests exercise its central path.
- **PARTIAL** means the mechanism exists, but a stated assumption, platform,
  failure path, or evidence coordinate is missing.
- **FUTURE** means the concept is part of the design but absent from the
  reviewed implementation.
- **NOT CLAIMED** marks a tempting conclusion that ProContract does not entail.

Empirical claims are indexed by model, task cohort, evaluator, and date. They
are not kernel invariants.

Five events must never be collapsed:

| Event | Meaning | Institutional force | Status |
| --- | --- | --- | --- |
| Passed replay | A frozen subject satisfied a finite check list in one replay environment | Mechanical prerequisite only | **PARTIAL** |
| Archive winner | A search procedure ranked a candidate under one statistic | None outside that selection procedure | **NOT CLAIMED** as settlement |
| Executor handoff | An executor petitions verification for an exact subject | Pauses execution; does not settle | **IMPLEMENTED** |
| Discharged duty | An authorized attestation currently supports the exact handoff claim | Recognized completion at a ledger frontier | **IMPLEMENTED** |
| Adopted successor | A new artifact, policy, or judge becomes the canonical default for future work | Changes the incumbent | **FUTURE** |

The bare words "done", "verified", "trusted", and "improved" are insufficient.
Every use should name the subject, claim, evidence policy, environment,
authority, and ledger frontier that give it meaning.

## Thesis

An agent is a sequence of temporary executors. Context compaction, Session
deletion, process exit, model replacement, and human handoff can erase an
executor's working state while the duty that motivated the work remains.

Execution state is descriptive. It records what a process saw and did.
Settlement state is normative. It records what the institution currently
recognizes as outstanding, authorized, handed off, supported, or released.

ProContract separates them:

> Termination is not handoff. Handoff is not settlement. Settlement is current
> support, not permanent truth.

The executor may explore, modify files, run tools, report a blocker, petition
new terms, or hand off a candidate. None of those actions can make the
institution recognize completion. Recognized completion requires an authorized
transition bound to an exact duty revision, specification, subject, and
evidence reference.

When evidence supporting a settlement is defeated, ProContract does more than
retract a belief:

~~~text
loss of epistemic support
        ->
renewed normative responsibility under an identified owner
~~~

This coupling is the distinctive core of ProContract.

The current, strongest defensible thesis is:

> **IMPLEMENTED:** ProContract provides completion integrity: recognized
> completion is institutional, exact, persisted in an atomic ledger, and
> defeasible independently of the executor.

The longer research program is:

> **FUTURE:** Policies may explore and recursively improve; a minimal
> institution governs whether an evidenced candidate may become canonical
> succession.

The future sentence is not a claim that ProContract produces improvement. It
is a claim about who may recognize succession and under what coordinates.

## Why execution state cannot determine settlement

Let \(X(h)\) be the execution projection of history \(h\): visible context,
workspace, tests, process state, and trajectory. Let \(N(h)\) be its normative
standing: current revision, authority, subject, attestation, support, and
outstanding duties.

There can be two histories such that:

\[
X(h_1)=X(h_2), \qquad N(h_1)\ne N(h_2).
\]

For example, the same candidate and test output may be visible in both
histories while one report names the current revision and the other names a
superseded revision. Or both may say "tests passed" while one was produced in
the target runtime and the other in an incompatible interpreter.

Any executor policy that reads only \(X\) must choose the same action in both
histories:

\[
X(h_1)=X(h_2)
\Longrightarrow
\pi(X(h_1))=\pi(X(h_2)).
\]

If the correct settlement differs, that policy must be wrong in at least one
history. The missing state is not more memory about execution. It is normative
standing preserved outside the executor.

This is not a new theorem about partially observed control in general. The
ProContract contribution is identifying the omitted latent state in agent
completion as duty, authority, and current evidential support, then placing it
under an executor-independent transition protocol.

## Ontology

### Descriptive execution state

Descriptive state includes model messages, tool calls, files, leases, process
status, counters, and raw observations. It may be durable or ephemeral.
Deletion, exhaustion, or failure of descriptive state is not settlement.

### Duty

A duty is an institutionally admitted obligation identified by scope,
Contract ID, revision, terms identity, issuer, and executor. It remains
outstanding until an authorized discharge or release.

### Normative standing

Normative standing is the current institutional status of a duty:

- dormant;
- active;
- verification;
- escalated;
- discharged;
- released.

Dormant, active, verification, and escalated duties are outstanding. Only
discharged and issuer-authorized released duties are quiet.

### Authority

Authority answers who may perform or recognize an effect. ProContract has two
different authority planes:

- delegated execution capabilities, such as mediated filesystem or process
  access while an exact revision is active;
- institutional authority to issue, revise, attest, challenge, resume, or
  release.

Visibility in a model prompt is not authority. A tool definition may be hidden
for clarity, but execution admission at the finalized effect boundary is the
authoritative check.

### Subject

A subject is the immutable, content-addressed projection handed to a verifier.
It is not "the workspace" without qualification. The current Codex subject is
exact under its current capture policy, which bounds entries and bytes, skips
ordinary oversized files and symbolic links, and force-captures declared
artifacts. The manifest format is versioned, but the effective capture limits
are not yet serialized into that version or subject identity.

Two physical workspaces may therefore share a subject identity when their
differences are outside that projection. The capture policy is part of the
trusted evidence envelope.

### Claim

The optimization goal tells an executor what to pursue. The settlement claim
tells a verifier and Principal which proposition evidence may support.

A discharge recognizes the frozen claim. It does not assert that the goal
reached a global optimum, that all hidden requirements were discovered, or
that the verifier fully represents user intent.

### Handoff

A handoff is a subject-bound completion petition containing a concise summary,
known uncertainties, and optional mechanical replay evidence. It is produced
by executor work but admitted by the institution.

The summary and uncertainty list are executor-authored claims, not evidence.
ProContract does not guarantee that a persuasive, incomplete, or deceptive
handoff cannot induce a human Principal to attest incorrectly. Independent
adjudication must inspect the subject and external evidence rather than treat
handoff narration as testimony.

### Evidence policy

An evidence policy specifies a finite projection of a claim that must be
checked. In the current Codex slice, ReplayPolicy contains argv-based checks,
protected file hashes, and required artifact paths.

Evidence policy is normative because changing it changes what may support
settlement. It belongs under the specification hash.

### Execution policy

Execution policy is advisory guidance about how the executor should search,
probe, implement, and allocate effort. It does not change the duty, claim,
authority, budget, evidence requirement, or settlement rule.

The Codex binding stores execution policy separately from ContractSpec. It is
not included in specHash or revision and is projected once into the executor
context.

### Attestation

An attestation is finite testimony from an authorized Principal. The containing
Discharge command and Contract lookup bind it contextually to the Contract; its
fields bind revision, specification, handoff subject, evidence reference, and
verifier identity. The current reducer requires issuer-controlled attestation.

An opaque evidence hash proves identity, not semantic truth.

### Challenge

A challenge is a subject-bound defeater. It removes current support without
deleting the historical attestation. Executor-visible challenges provide
remediation information; sealed challenges reject support without leaking
holdout contents into the executor context.

### Settlement

Settlement is the accepted institutional transition from verification to
discharged. It requires an exact handoff and authorized attestation.

Settlement is terminal for ordinary execution but defeasible under a later
challenge.

### Completion

"Completion claim" means handoff. "Recognized completion" means discharged with
current support. These terms are not interchangeable.

### Succession

Succession is a **FUTURE** relation that changes a distinguished incumbent:
the artifact, policy, or judge future work inherits by default.

Succession is not another word for discharge. Many Contracts may be discharged
concurrently, whereas an incumbent role requires exclusive, serialized,
atomic replacement.

## Philosophical foundations

### An agent is a succession of temporary selves

An LLM invocation has no intrinsic normative continuity with a future
invocation. A later model may inherit messages or files, but inheritance does
not explain why a prior intention should still bind, which authority remains
valid, or what counts as release.

ProContract externalizes continuity. The institution, not the current
psychology of an executor, carries the duty.

This follows the role of intention as a commitment device. An intention is not
merely a present preference. It stabilizes future action and coordinates
others. When the policy that formed the intention is ephemeral, an external
institution must carry the commitment.

### Memory, obligation, and support are different

~~~text
past observation -> memory       -> future attention
current intent   -> Contract     -> future duty and authority
current witness  -> attestation  -> current epistemic support
defeater         -> challenge    -> renewed responsibility
~~~

Memory can influence a future policy and still be ignored. A Contract changes
what the institution recognizes even when the executor forgets it. An
attestation supports one frozen claim but may later lose standing.

### Institutional force comes from mediation

A schema is not a Contract merely because it is expressive. Contract force
comes from the institution's monopoly over recognized state transitions.

The institution does not monopolize all physical behavior. It monopolizes what
the mediated system accepts as authorized, settled, or quiet. Strong physical
non-bypass additionally requires a separate authority domain.

### Contracts are incomplete

Natural-language intent and an executable verifier cannot be identical.
Freezing an evidence policy prevents opportunistic weakening but also freezes
an imperfect proxy.

Incomplete-contract theory supplies the appropriate response: explicit
residual control rights. The issuer owns revision, release, and settlement
decisions; the executor may petition but cannot approve them.

### Truth is supported, not stored in an artifact

Specs, manifests, handoffs, reports, hashes, and proofs are boundary objects.
Their institutional type and provenance determine what role they play.

A report's existence does not make it true. A hash makes substitution
detectable, not semantics correct. A passed replay establishes only the
finite claim computed by that replay in the world where it ran.

### Evidence is indexed by the world that produced it

Evidence has an implicit environment argument:

\[
E = E(subject, policy, environment, evaluator, time).
\]

Removing that argument can make a precise hash precisely wrong. In the Amber
ProgramBench trajectory, the exact frozen executable passed replay under
Python 3.12.3 and was a syntax error under the evaluator's Python 3.10.12.
The subject hash did not change. The relevant world did.

Therefore:

\[
Support_{e_1}(c) \not\Rightarrow Support_{e_2}(c)
\]

unless environment equivalence or an explicit bridge has been established.

Environment-coordinate binding is **FUTURE** in the native replay report and a
required correction, not optional telemetry.

### Defeat creates responsibility

Truth-maintenance systems retract beliefs when justifications lose support.
ProContract adds a normative consequence:

\[
Defeat(support(o))
\land Mandated(o)
\Longrightarrow OutstandingRemediation(o).
\]

If a challenged duty supported downstream recognized duties, the challenge
closure restores responsibility transitively. Historical decisions remain
auditable; current support is withdrawn.

### Non-vacuous RSI requires a fixed point

If the improver, judge, mission, authority, and rule of adoption can all change
without an external constraint, "improvement" has no stable semantics.

The design problem is not eliminating every fixed point. It is minimizing and
making explicit the root relative to which improvement is meaningful.

The actual ProContract trust root is not only the pure reducer. It includes:

\[
R =
(K,\ authentication,\ canonicalization,\ atomic\ storage,\ capture\ policy,
evidence\ envelope,\ clock,\ root\ authority).
\]

Policies and judges may evolve only relative to this root or to a bridge
authorized by it. An entity cannot self-authorize replacement of the final
authority that gives "authorized" its meaning.

## Claim ladder

The document separates four types of claim.

### Unconditional kernel invariants

These are properties of the finite command algebra, assuming commands have
already been mapped to authenticated actor identities and canonical values.
They do not depend on model competence.

### Conditional system properties

These combine kernel invariants with named adapter and deployment assumptions:
exclusive role wiring, durable storage, mediated effects, a running process,
or a verifier that terminates.

### Empirical hypotheses

These concern score, cost, convergence, model behavior, compiler quality, or
evidence coverage. They are indexed by an experiment and may be falsified
without changing the kernel.

### Future protocol claims

These specify desirable extensions, including environment-coordinated
evidence, portable signatures, canonical succession, judge bridges, and
adversarial process isolation.

No future claim should be written in the present tense.

## Normative kernel

### Algebra

The current kernel is a pure, total, deterministic reducer:

~~~text
transition(state, authenticated finite command)
  -> next state + accepted/rejected decision + event
~~~

The current command vocabulary is:

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

The exact names and count are not constitutional. Their irreducible categories
are admission, activation, candidate petition, residual-control decision,
settlement, defeat, and routing of outstanding work.

Illegal commands preserve authoritative state. The ledger still records their
rejection.

### Status

~~~text
dormant -> active -> verification -> discharged
             |            |
             |            +-> challenge -> dormant or escalated
             +-> blocked/retry/escalation

issuer-authorized release -> released
~~~

Only active authorizes executor effects. Verification is outstanding work
awaiting adjudication. Escalation routes responsibility; it does not settle.

### Invariants

#### I1. Rejection preservation

\[
decision(c)=Rejected \Longrightarrow state'=state.
\]

Rejected authority-changing attempts remain auditable events.

#### I2. Obligation conservation

An outstanding duty ends only through accepted discharge or issuer-authorized
release. Session deletion, process exit, retry, blocked work, revision
petition, and escalation do not settle.

#### I3. Residual control

Only the issuer may approve revision or release. The executor may propose
different terms but cannot ratify them.

#### I4. No self-certification

Issuer and executor are distinct. Executor testimony can create a handoff and
enter verification, never an attestation or discharge.

#### I5. Exact coordinates

Authority-changing transitions check the applicable Contract ID, revision,
specification hash, subject hash, evidence reference, and actor identity.
Stale or substituted coordinates reject instead of being inferred from arrival
order.

#### I6. Replay subordination

When configured, mechanical replay must match the frozen policy and exact
subject and must pass before discharge is possible. Replay evidence must be
distinct from Principal attestation evidence.

Replay alone never discharges.

#### I7. Responsibility closure

An accepted challenge atomically removes current support from the target and
every live transitive dependent. Released duties remain released. Historical
attestations remain in the ledger.

#### I8. Dependency integrity

Requirements name already-issued duties at exact revisions. Activation checks
that every requirement is discharged with current attestation support.

Because a new Contract can require only existing Contracts, issuance order
prevents dependency cycles.

#### I9. Revision fencing

A pending revision blocks handoff and settlement until the issuer accepts or
rejects the exact petition. Rejection resumes the old terms; acceptance creates
a new revision and execution context.

#### I10. Frontier-relative quiet

\[
quiet(scope,f)
\iff
\forall o \in scope:
status_f(o)\in\{Discharged,Released\}.
\]

Quiet names a scope and ledger frontier. A later admission or challenge creates
a later frontier; it does not falsify the historical snapshot.

### Completion Integrity

Define:

\[
\begin{aligned}
CI ={}&
RejectionPreservation \\
&\land ObligationConservation \\
&\land ResidualControl \\
&\land NoSelfCertification \\
&\land CoordinateIntegrity \\
&\land ResponsibilityClosure \\
&\land QuietSoundness.
\end{aligned}
\]

Under authenticated actor mapping, canonical hashing, and atomic durable
storage, the intended theorem is:

\[
\forall \pi,\quad
Traces(K\parallel\pi)\models CI.
\]

Here \(\pi\) may be stochastic, mistaken, adversarial, or a human contractor.
The theorem concerns recognized state, not physical non-bypass, semantic
truth, outcome liveness, or task solvability.

The current Rust tests exercise representative invariant paths. Exhaustive
model checking and implementation refinement are **FUTURE** and required
before describing the theorem as mechanically proved.

## The actual trust root

The pure reducer is necessary but insufficient for system-level claims.

### Actor authentication and role wiring

The Rust reducer compares actor strings. It does not authenticate identities.
The Codex adapter controls which model-visible and Principal-only surfaces can
construct each command.

No-self-settlement at system level therefore assumes the executor cannot call
raw Principal methods or manufacture institution actors.

### Canonicalization

Specification and subject identity depend on SHA-256 over one canonical
serialization and one manifest grammar. Schema evolution and a second adapter
must agree on that encoding.

Canonicalization is consensus code, not a convenience.

### Atomic storage

The SQLite ledger commits projection, accepted or rejected decision, sequence,
and hash-chain head in one immediate transaction.

The hash chain is auditable and crash-consistent. It is not tamper-proof
against an actor that can rewrite the database and its anchors.

### Subject-capture policy

Capture limits, ignore rules, symbolic-link handling, ordinary-file size
limits, and forced artifact closure define the subject projection. These rules
must be versioned and named in portable evidence.

The reviewed implementation checks its total byte ceiling only after copying a
file into the object store. Enforcing the remaining limit during the read loop
is a known correctness requirement before adversarial artifact claims.

### Evidence environment

The current native replay report records commands, exits, output hashes,
protected files, artifacts, policy hash, and subject hash. It does not record
an image digest, interpreter, OS, architecture, toolchain, evaluator version,
duration, resource use, or descendant cleanup.

It is therefore **PARTIAL** evidence and must be described as local preflight.

### Clock

Deadlines, leases, and triggers trust the host clock. Heartbeat proves recent
process ownership, not semantic progress.

The reducer also trusts caller-supplied command timestamps and does not enforce
global monotonicity between them. Authenticated adapter construction of time is
therefore part of the current trust root.

### Root authority and mission semantics

The current Principal is the issuer. Independent means the executor cannot
invoke that surface; it does not necessarily mean a distinct organization or
human.

Goal and claim remain natural language. The Kernel checks identity and
authority, not construct validity.

## Security boundary

ProContract monopolizes recognized finality and mediated capability issuance,
not every physical effect.

At a mediated effect point:

~~~text
effect allowed
iff active exact revision
and current binding/lease
and delegated capability
and remaining shared budget
~~~

The current local Codex deployment is cooperative. A shell-capable process
running under the same operating-system authority may reach files or processes
outside an in-process adapter.

Strong adversarial non-bypass is **FUTURE** and requires:

- Principal credentials absent from the executor environment and namespace;
- ledger and evidence storage outside executor write authority;
- worker identities unable to authenticate Principal commands;
- every protected effect mediated by a capability-validating boundary;
- only finite subjects and evidence crossing from worker to institution.

System-level no-self-settlement is conditional on those assumptions.

## Layer ownership

~~~text
pure settlement kernel
  duty identity, roles, status, coordinate checks,
  dependency closure, decision, quiet

institution store and authority boundary
  authenticated commands, atomic projection and ledger,
  Principal/worker identity, durable event frontier

trusted evidence envelope
  subject capture, environment identity, replay execution,
  evaluator identity, finite report, provenance validation

execution adapter
  Session, model, tools, leases, fences, counters,
  interruption, recovery, effect admission

mutable policy plane
  execution guidance, compiler heuristics, probe strategy,
  budget allocation, candidate generation, selection policy

task adapter
  cleanroom, candidate layout, reference interface,
  benchmark evaluator, score normalization, test split
~~~

Core may bind hashes and identities of edge-owned manifests. It should not
interpret their task mechanics.

### Admission test for the pure Kernel

A concept belongs in the pure Kernel only when removing it permits at least
one of:

- false quiet without authorized settlement;
- self-certification;
- stolen or expanded authority;
- stale subject or evidence substitution;
- challenged support leaving a live dependent recognized without an owner;
- an authority-changing decision becoming unauditable.

If removal changes only score, prompt style, search order, scheduling
efficiency, replay implementation, or benchmark coverage, the concept belongs
at an edge.

### Transitional debt: ReplayPolicy

The current Kernel crate interprets argv, cwd, timeouts, protected files, and
artifact paths through ReplayPolicy. Those are verifier-adapter concepts, not
constitutional settlement concepts.

This remains supported implementation debt. The target shape is:

~~~text
Kernel:
  evidence_policy_hash
  evidence_result_coordinate

Evidence envelope:
  concrete argv/files/proofs/rubrics/tests
~~~

Migrating this representation must preserve existing Spec and ledger
coordinates or introduce an explicit compatibility version.

## Three policies, not one

The word "policy" names three different objects.

### Execution policy

Execution policy guides how work is attempted. It is mutable, replaceable, and
outside ContractSpec.

**PARTIAL:** Codex stores it on the execution binding as a typed developer
fragment and does not permit executor revision to change it. One projection
path is one-shot, while the full thread-context path does not consistently
honor the same one-shot and separate-message semantics.

Known context-boundary issues in the reviewed branch must be fixed before
production: the final executor prompt requires a hard token bound, contextual
user fragments must not be mistaken for the original request, and all policy
injection paths must preserve separate-message metadata.

### Evidence policy

Evidence policy defines a frozen mechanical prerequisite to settlement. It is
normative and belongs under specHash.

**PARTIAL:** ReplayPolicy serves this role but is environment-blind and
filesystem/process-specific.

### Succession policy

Succession policy determines what evidence and authority permit a candidate to
replace a canonical incumbent.

**FUTURE:** No such object or transition exists in the reviewed Codex Kernel.

This naming discipline resolves an apparent contradiction:

~~~text
execution policy is outside the duty specification
evidence policy is inside the duty specification
succession policy is not yet implemented
~~~

## Codex execution adapter

### Formation

The host controller may issue an exact Contract for a loaded Principal thread.
The compiler preserves the source request, rejects unknown capability names,
checks user-named artifacts, and produces a compiler-manifest hash.

Model-authored formation exists only in the optional proposal mode. The
reviewed latest-user-request lookup can confuse later contextual user fragments
with actual client input; this is a known authorization bug, not part of the
theory.

### Binding

Each Contract execution has a separate binding containing:

- Contract and ledger scope;
- current revision;
- executor Session identity;
- execution policy;
- attempt identity and count;
- cumulative turn and action counters;
- deadline and next-action time;
- lease owner and expiry.

Binding state is operational, not normative settlement state.

### Admission

Before each ordinary executor-turn provider request, the extension checks the
current Contract status, revision, pending revision, binding, lease, deadline,
and cumulative turn budget. Before each registered finalized tool call, it
additionally checks delegated tool authority and the cumulative action budget.

While a Contract remains active, contract status, ready, blocked, and
revision-petition tools bypass ordinary action reservation and authority lookup
so the executor can return responsibility without spending another effect
action. The effect-free host control tools update_plan and tool_search share
that exemption. Every exemption still requires a current active Contract and
revision.

Detecting turn, action, attempt, or deadline exhaustion escalates the Contract.
Ordinary executor-turn sampling and registered executor tools are denied after
escalation. Inline auto-compaction currently issues host-driven provider
requests outside the sampling-admission hook; those requests are not Contract
metered or fenced and are a known adapter gap.

### Semantic attempts

Transient transport interruption may resume the same semantic attempt.
Visible verifier challenges, accepted revisions, blocked context, and ordinary
attempt exhaustion create new attempt context without resetting shared
ceilings.

An attempt is not a Contract and its disappearance is not settlement.

### Handoff

report-ready captures a bounded subject before recording handoff. Failure to
capture or start configured replay escalates instead of inventing evidence.

The current adapter supports subject capture and replay only in the local
environment. Remote executor support is **FUTURE**.

### Principal

Principal-only APIs attest, challenge, decide revisions, resume, release,
inspect quiet, and materialize the exact handoff.

The executor receives status, ready, blocked, and revision-petition tools. It
does not receive Principal settlement APIs.

### Recovery

The adapter persists binding and ledger state and can reclaim expired leases
while a Principal runtime is loaded. Hosted wall-clock liveness while every
process is stopped is **NOT CLAIMED**.

Crash recovery, accepted revision, remote execution, Windows replay, and
combined authority/budget enforcement require additional integration coverage
before the branch is production-ready.

## Evidence and justification

### History, justification, and current support

Use separate symbols:

\[
\mathcal H = immutable\ decision\ history,
\quad
\mathcal J = justification\ graph,
\quad
\mathcal S = current\ support.
\]

A challenge changes \(\mathcal S\), may alter which duties are outstanding,
and appends to \(\mathcal H\). It does not rewrite \(\mathcal H\).

### Proposed complete evidence coordinate

The current coordinate is approximately:

\[
(contract,\ revision,\ specHash,\ subjectHash,\ policyHash,\ evidenceHash,
verifier).
\]

The target evidence envelope is:

\[
\begin{aligned}
\mathcal E = (&contract,\ revision,\ specHash,\ subjectHash,\\
              &evidencePolicyHash,\ environmentDigest, evaluatorDigest,\\
              &observationManifestHash,\ evidenceHash,\ authority).
\end{aligned}
\]

EnvironmentDigest should cover the compatibility properties relevant to the
claim, including image, OS, architecture, runtime/ABI, toolchain, sandbox, and
dependency closure. Exact image identity is appropriate when exact deployment
parity is required; a versioned compatibility predicate is appropriate when
portability is the claim.

### Trusted observations

A process observation should record:

- exact argv, cwd, selected environment, and input hashes;
- exit status;
- bounded stdout and stderr hashes;
- wall and CPU time;
- timeout and output-cap status;
- peak resource use when relevant;
- process-group termination and surviving descendants;
- subject, evaluator, and environment identities.

Model-authored prose may summarize these observations. It cannot replace them.

### Replay

Replay is limited preflight:

~~~text
frozen subject
  -> fresh materialization
  -> frozen finite checks
  -> protected/artifact inspection
  -> content-addressed report
~~~

Replay establishes neither hidden behavioral adequacy nor global correctness.
When replay runs in a different environment from deployment, it additionally
requires an explicit environment bridge.

### Independent adjudication

Principal evidence must remain distinct from executor handoff and mechanical
replay. A task adapter may provide tests, proof checking, a rubric, human
review, deployment receipt, or comparison against a named baseline.

The Kernel binds the result identity. It does not interpret task-specific
semantics.

## Knowledge continuity

Obligation conservation does not imply knowledge conservation.

The current Kernel preserves duty and historical decisions. It does not by
itself preserve hypotheses, probes, counterexamples, causal explanations, or
the residual frontier needed for efficient convergence.

Knowledge artifacts should be content-addressed evidence owned by an adapter:

~~~text
probe case
candidate observation
residual mismatch
hypothesis and dependency
resolution or unresolved status
environment/evaluator coordinate
~~~

New attempts may inherit them only when their support remains valid.

### Evidence inheritance

\[
Reuse(e,o')
\iff
Dependencies(e)\ unchanged
\lor
NonInterference(e,o')\ separately\ established.
\]

Copying a score or trace is not inherited assurance. A global wrapper, helper
override, changed runtime, changed evaluator, or changed routing policy may
invalidate evidence for tasks that were not explicitly modified.

This rule is central to policy succession and to archive-based recursive
improvement.

## Improvement without self-amendment

ProContract does not improve coding ability. At the protocol level it can
record duties whose subjects are candidate compilers, policies, verifiers, or
harnesses. A complete governed improvement and promotion loop is **FUTURE** at
the reviewed native Codex HEAD; earlier Python harness experiments exercised
parts of this method but are not native implementation evidence.

The designed learning loop is:

~~~text
ledger + subjects + external outcomes
  -> offline failure attribution
  -> candidate policy or verifier
  -> frozen evaluation protocol
  -> disjoint confirmation
  -> Principal decision
  -> future Contracts only
~~~

The current Contract executor cannot rewrite its own active duty or settlement
rules. A new candidate must be a new subject under a new or revised,
Principal-approved obligation.

### Policy as input and Policy as subject

There are two valid roles:

1. A policy used to execute another duty is execution input and remains outside
   that duty's Spec.
2. A policy being evaluated for future use is itself the frozen subject of a
   Policy Contract.

This is the designed route by which policy improvement could become governed
without contaminating every delivery specification with its executor strategy.

### Current empirical result

These tables are development evidence, not promotion-grade confirmation. Both
used GPT-5.6 Luna at reasoning effort max, one stochastic candidate per arm and
instance, and the ProgramBench active tests for Amber, Loop, and fd during
2026-08-29--30 UTC. The v5 run was a fresh three-instance A/B. The v6 run reused
those training instances after the v5 hidden outcomes were already known and
therefore cannot confirm the v3 policy. The precise ProgramBench runner commit
was not recorded in a durable manifest, which is itself a validity limitation.

The v5 source currently survives only in the untracked local experiment ledger
at "../scripts/PROCONTRACT_EXPERIMENTS.md"; its referenced temporary RESULT
artifact no longer exists. The corrected v6 report remains locally at
"/tmp/procontract-native-rpc-v6/RESULT.md" with SHA-256
"e7a9bde717cbf3e74f12ead3e44d9c85700223210f0ba8c9a0a88346da237dd7".
These coordinates must be committed or the tables removed before this document
is publication evidence.

The three-instance v5 ProgramBench slice reported:

| Arm | Amber | Loop | fd | Macro |
| --- | ---: | ---: | ---: | ---: |
| execution policy on | 78.2301% | 95.6338% | 80.6478% | 84.8372% |
| execution policy off | 69.5575% | 83.2394% | 77.8138% | 76.8702% |

That experiment is evidence that execution policy can affect utility while
leaving Kernel semantics unchanged. It is not evidence that one universal
policy is optimal.

The v6 evidence-convergence policy falsified that generalization:

| Arm | Amber | Loop | fd | Macro |
| --- | ---: | ---: | ---: | ---: |
| v3 policy on | 2.4779% | 96.1972% | 81.0526% | 59.9092% |
| parity policy off | 70.7965% | 67.3239% | 78.7854% | 72.3019% |

Excluding the failed Amber arm, v3 gained only a small amount over the earlier
v2 results while consuming substantially more actions and model tokens.

The correct conclusion is:

> Execution policy is replaceable and empirically falsifiable. Kernel stability
> does not make policy quality stable.

## Amber: the environment-coordinate falsifier

The v6 Amber candidate reported:

- one semantic attempt;
- exact subject capture;
- native compile and replay success;
- a 48-case self-contained differential corpus with zero reported residuals.

The same exact executable then failed under the official evaluator:

- replay image: Python 3.12.3;
- evaluator image: Python 3.10.12;
- failure: an f-string expression at amber.py line 726 is invalid in Python
  3.10;
- official result: 2.4779%, with one branch producing no JUnit report;
- an extended three-hour diagnostic produced the same missing result.

A bounded follow-up isolated the downstream amplification. Without pytest
failure reruns, the branch completed in 40.75 seconds with 398 failures,
31 passes, and five skips. With official reruns, two large-file assertion
rendering lanes consumed the branch lifetime after the TTY wrapper masked the
child syntax-error exit.

Therefore the three-hour tail is not evidence of catastrophic candidate regex
behavior. It is:

~~~text
environment mismatch
  -> artifact cannot start
  -> evaluator failure amplification
  -> missing finite report
~~~

The institutional result remained sound: the Delivery Contract was never
quiet, and the sealed evaluator challenge moved it to escalated while removing
current handoff support.

The case separates two claims:

- **SUPPORTED:** settlement responsibility remained conserved.
- **REFUTED:** local replay evidence was sufficient evidence of target-runtime
  compatibility.

## Adaptive selection pressure

Let a noisy evaluator estimate:

\[
\widehat J(H_m)=J(H_m)+\epsilon_m.
\]

Even when candidates have equal true quality,

\[
\mathbb E\left[\max_{m\le M}\widehat J(H_m)\right]
\]

can increase with the number of adaptively inspected candidates. A monotone
best-so-far statistic may therefore reflect search exposure as well as real
improvement.

The design principle is:

> As improvement power and adaptive selection pressure scale, assurance
> strength and exposure accounting must scale with them.

Candidate multiplicity, evaluator exposure, holdout reuse, judge version,
selection history, and stopping rules belong in a trusted experiment manifest
or evidence envelope. They do not belong as benchmark-specific concepts in the
pure Kernel.

Appropriate controls include preregistration, paired evaluation, disjoint
confirmation, reusable-holdout methods, selection-adjusted confidence, sealed
negative evidence, and explicit cost accounting.

These methods reduce risk. They do not make evaluator construct validity a
kernel theorem.

## Witnessed succession

### Status

Canonical succession is **FUTURE**.

The current Kernel implements the retraction substrate:

- a settlement can be challenged;
- support can be removed without deleting history;
- transitive dependents regain outstanding responsibility;
- quiet becomes false at the new frontier.

It does not implement accession:

- no canonical incumbent register;
- no policy lineage;
- no Adopt or Promote command;
- no atomic deployment swap;
- no judge bridge;
- no automatic rollback of an external deployment.

### Completion and succession are not identical

Completion integrity is not a complete reduction of succession integrity.

Completion is a per-duty predicate. Succession changes an exclusive mutable
reference:

\[
incumbent(role)\mapsto
(contract,\ revision,\ subjectHash,\ evidenceCoordinate).
\]

Succession adds at least:

1. uniqueness of the incumbent per role and scope;
2. total ordering of concurrent adoption proposals;
3. atomic replacement or no replacement;
4. relational evidence comparing incumbent and candidate;
5. deployment activation and rollback semantics;
6. bridge evidence when the judge itself changes.

The accurate relation is:

> Completion integrity is the invariant substrate of succession integrity.
> Challenge closure already supplies the duty-support withdrawal needed by a
> future succession protocol. It does not retract an incumbent or roll back a
> deployment. Succession adoption and retraction require a separate thin
> protocol and are not derived from discharge.

### Candidate succession certificate

A future finite certificate may bind:

\[
\begin{aligned}
\kappa_t = (&scope,\ frontier,\ missionHash,\\
            &incumbentHash,\ candidateHash,\\
            &oldJudgeHash,\ newJudgeHash,\\
            &environmentHash,\ assuranceCaseHash,\\
            &bridgeHash,\ authorityAttestations).
\end{aligned}
\]

The Kernel should validate finite identities, live support, role authority,
and atomic transition legality. It should not decide whether one policy is
semantically smarter.

### Judge succession

Replacing \(J_t\) with \(J_{t+1}\) cannot be authorized solely by
\(J_{t+1}\). A bridge may require old-judge and new-judge cross-evaluation,
stable calibration anchors, disagreement analysis, and independent root
authority.

A minimal cross-score matrix is:

\[
\begin{array}{c|cc}
 & H_t & H_{t+1}\\
\hline
J_t     & * & *\\
J_{t+1} & * & *
\end{array}
\]

No finite matrix proves universal evaluator validity. It makes the basis and
scope of succession explicit.

### Succession Integrity

A future property may be defined as:

\[
\begin{aligned}
SI ={}&
CanonicalUniqueness \\
&\land NoSelfAdoption \\
&\land IncumbentCandidateIntegrity \\
&\land AuthorityContinuity \\
&\land JudgeBridgeIntegrity \\
&\land LiveSupportClosure \\
&\land DefeatDrivenRollback \\
&\land QuietSoundness.
\end{aligned}
\]

The intended structural theorem would be:

\[
\forall \pi,\quad
Traces(SuccessionKernel\parallel\pi)\models SI.
\]

It would not imply:

\[
Utility(P_{t+1})>Utility(P_t)
\]

or convergence to a globally correct policy.

### Strongest current wording

The current paper or PR may say:

> ProContract implements completion integrity and specifies witnessed
> succession as a designed extension. Its challenge semantics already
> implement support withdrawal with transitive responsibility restoration;
> exclusive incumbent adoption, judge bridges, and deployment rollback remain
> future work.

It may not say:

> ProContract guarantees trustworthy recursive self-improvement.

## Relation to Meta^n

Meta^n and ProContract address orthogonal layers.

[Meta^n: Recursive Self-Improvement through Emergent
Depth](https://arxiv.org/html/2608.24735v1), arXiv:2608.24735v1, accessed
2026-08-31, holds a meta-operation \(\Omega\) fixed and applies it recursively
to expanding code and execution traces. Its evolutionary orchestrator
maintains a growing archive of candidate chains, reports both archive-best and
best-single-chain behavior, and stops search after a bounded non-improvement
rule. Implementation observations in this section refer to repository commit
[b7081843](https://github.com/minnesotanlp/meta-n/tree/b7081843d3c7b0e0f418ca10aaf2ccbff856e7f8).

ProContract contributes no claim that it generates better meta-layers or
searches more efficiently. Meta^n contributes no claim, as characterized here,
that archive membership constitutes institutional settlement.

The fair comparison is:

\[
\boxed{
MetaDepth\ expands\ what\ can\ be\ proposed;
\quad
InstitutionalContinuity\ limits\ what\ may\ be\ inherited.
}
\]

### Archive retention is not succession

For an archive \(\mathcal A_r\), archive-best may be:

\[
U_r(J)=
\frac{1}{N}\sum_i
\max_{H\in\mathcal A_r}J(t_i,H).
\]

If \(\mathcal A_r\subseteq\mathcal A_{r+1}\), then
\(U_{r+1}\ge U_r\) by construction. This does not imply that one chain
\(H_{r+1}\) dominates \(H_r\), that a deployable router generalizes, or that
the judge still represents the mission.

Meta^n reports archive-best and best-single-chain separately, so ProContract
should treat the distinction as complementary scope, not as a correction of a
claim the Meta^n authors did not make.

### Frozen traces are not inherited assurance

An archive may retain old evidence without rerunning unaffected tasks.
That is a valid search optimization. It is not sufficient for institutional
inheritance when a wrapper, helper library, global context, router, environment,
or evaluator changed.

ProContract's requirement is:

The evidence-inheritance rule in "Knowledge continuity" applies: reuse is
permitted only when dependencies are unchanged or non-interference is
separately established.

### Search stopping is not finality

Patience, score plateau, or budget exhaustion means the search policy found no
further candidate under its current resources. It does not discharge a mission
or make a scope quiet.

This distinction should be stated without implying that Meta^n calls its
search stopping rule institutional finality.

### Complementary composition

A Meta^n-style system may serve as:

- an improvement generator;
- an executor policy;
- a source of candidate wrappers and helper libraries;
- an archive-based selector.

All remain untrusted variation from the settlement institution's perspective.
They may be evaluated as exact subjects without moving their search mechanics
into the Kernel.

Before publication, every numeric Meta^n statement must be checked against the
exact paper version, split, backbone, and estimator. Comparisons must match
archive-best with archive-best and deployed single systems with deployed
single systems.

## Evaluation methodology

### Structural evaluation

The following is the required structural program, not a report that every item
has been measured at the reviewed HEAD. Current Rust tests cover representative
coordinate, replay, dependency-challenge, ledger, and app-server paths; the
complete command-by-state fault matrix and the four rates below are
**FUTURE**. Structural tests should use scripted actors before LLMs:

- duplicate and delayed commands;
- stale revision, subject, and verifier evidence;
- executor self-discharge attempts;
- crash between ledger operations;
- lease expiry and recovery;
- challenge of discharged prerequisites;
- dependency depth;
- process and Session deletion;
- sealed evidence;
- quiet snapshots before and after challenge.

Primary metrics include:

\[
FalseQuietRate,\quad
InvalidSettlementRate,\quad
DutyLossRate,\quad
ChallengeClosureRecall.
\]

### Semantic mutation

Each retained Kernel concept should have a shortest counterexample when
removed:

| Removed mechanism | Expected counterexample |
| --- | --- |
| issuer/executor separation | executor discharges itself |
| revision/spec binding | stale report settles new terms |
| subject binding | candidate A is evaluated and B accepted |
| rejection preservation | stale command partially mutates state |
| challenge closure | unsupported dependent remains discharged |
| quiet predicate | escalated duty is reported quiet |
| dependency guard | prerequisite disappears while dependent remains live |

If removing a guard produces no counterexample, the guard may be redundant
under existing constraints and should not be defended by rhetoric.

### Refinement

A small TLA+ or equivalent reference model should define:

~~~text
Init
Issue
Activate
ReportReady
Discharge
Challenge
Release
Crash
LeaseExpire
~~~

Generated command traces should run through both the model and Rust reducer,
comparing decision, normalized state, event, outstanding set, and quiet result
at every step.

### Empirical utility

Structural integrity and coding utility are separate estimands:

~~~text
ordinary execution - no execution
  = value of another model invocation

ProContract execution - matched ordinary execution
  = value/cost of the institutional envelope

independently attested result - executor handoff
  = value of the truth boundary
~~~

Matched arms freeze model, prompt information, tools, environment, parent
artifact, budget ceiling, reference interface, packaging, and evaluator.

Report score, solved rate, latency, tokens, actions, attempts, challenges,
evaluator errors, incomplete results, and final ledger frontier.

### Succession stress tests

The two most discriminating future experiments are:

1. **Archive-to-successor gap:** compare archive-best, best single chain,
   explicit composite router, and ProContract-gated incumbent on independent
   held-out tasks. Measure false succession, not only best score.
2. **Evaluator succession:** select with \(J_t\), introduce a corrected
   \(J_{t+1}\), and compare naive promotion with old/new-judge bridge evidence.

A useful system must also measure false rejection and overhead. A protocol that
never adopts anything has zero false succession and no practical value.

## Current guarantees and limits

| Claim | Status | Condition |
| --- | --- | --- |
| Duty conservation | **IMPLEMENTED** | authenticated role mapping and atomic store |
| No executor self-certification | **IMPLEMENTED** in reducer | system-level claim requires Principal isolation |
| Exact revision/spec/subject settlement | **IMPLEMENTED** | canonical encoding trusted |
| Replay subordinate to attestation | **IMPLEMENTED** | replay policy correctly represented |
| Target-environment validity of replay | **NOT CLAIMED** | environment coordinate absent |
| Challenge-driven transitive responsibility restoration | **IMPLEMENTED** | dependency graph and storage survive |
| Frontier-relative quiet | **IMPLEMENTED** | ledger readable |
| Durable recovery across process/model replacement | **PARTIAL** | storage and a running recovery host required |
| Mediated turn/action/authority enforcement | **IMPLEMENTED** | only for registered Codex effect paths |
| Adversarial physical non-bypass | **FUTURE** | requires separate authority domain |
| Knowledge convergence | **NOT CLAIMED** | adapter policy concern |
| General coding capability improvement | **NOT CLAIMED** | empirical and model/task-dependent |
| Principal cannot be persuaded by a deceptive handoff | **NOT CLAIMED** | requires independent evidence review and human/organizational controls |
| Canonical incumbent adoption | **FUTURE** | succession protocol absent |
| Judge succession and bridge integrity | **FUTURE** | succession protocol absent |
| Guaranteed recursive self-improvement | **NOT CLAIMED** | neither Kernel nor finite evaluator entails it |

## Engineering principles

1. **Simplicity is a correctness property.** Every transition should be
   understandable in one pass.
2. **Use smart edges and a dumb Kernel.** Models may draft and reconcile;
   adapters may evaluate; the Kernel validates finite authority and identity.
3. **Conserve duty by construction.** Process lifecycle is never settlement.
4. **Separate attention, authority, evidence, and finality.**
5. **Bind claims to exact coordinates and environments.**
6. **Keep execution policy outside normative terms.**
7. **Keep evidence policy frozen and explicit.**
8. **Treat handoff as petition and replay as preflight.**
9. **Preserve history while allowing support to be defeated.**
10. **Route support loss back to an identified owner.**
11. **Put task mechanics and search heuristics in adapters.**
12. **State every trust assumption and non-goal.**
13. **Require counterexamples for Kernel concepts.**
14. **Scale assurance with adaptive selection pressure.**
15. **Do not let future succession language rewrite current implementation
    status.**

Three substitution tests guide every design:

~~~text
Could a human contractor replace the LLM without changing Kernel semantics?
Could a non-filesystem verifier replace replay without changing settlement?
Could another harness replace Codex without changing the transition algebra?
~~~

## Change gate

Every proposed pure-Kernel change must state:

- which invariant it enforces;
- the shortest counterexample possible without it;
- why an adapter or composition cannot enforce the same boundary;
- the focused reducer test;
- the real boundary integration test;
- concepts and branches added;
- concepts and branches removed.

Performance evidence may justify a compiler, executor policy, verifier, or task
adapter change. It cannot by itself justify authority-changing Kernel
semantics.

## Implementation disposition

### Implemented at the reviewed Codex commit

- pure Contract reducer with exact role and coordinate guards;
- SQLite projection and append-only hash-chained decisions;
- bounded immutable subjects with forced artifact closure;
- separate normative Contract and operational execution binding;
- dedicated executor Sessions;
- fail-closed ordinary executor-turn sampling and registered-tool admission;
- cumulative turn/action/deadline/attempt bounds;
- structured handoff;
- local mechanical replay;
- Principal-only attestation and executor-visible challenge paths;
- transitive responsibility closure;
- frontier-relative quiet;
- experimental app-server API and generated schemas.

### Partial or review-blocking

- model-visible prompt and reminder token bounds;
- admission and accounting for inline auto-compaction provider requests;
- reliable identification of the actual client-authored source request;
- one-time, consistently separate-message execution-policy projection;
- remote executor capture and replay;
- Windows-portable replay tests;
- lease heartbeat and crash/recovery integration coverage;
- accepted-revision, Resume, and Release integration coverage;
- sealed-challenge focused coverage;
- Principal mutation APIs whose code exists but whose authority-changing
  branches lack focused tests;
- in-stream enforcement of subject byte limits;
- backward-compatible persisted InternalSessionSource encoding;
- target environment and evaluator identity in evidence.

### Future

- TLA+ model and Rust refinement testing;
- portable signatures and externally anchored ledger checkpoints;
- strong Principal/worker process isolation;
- content-addressed durable knowledge ledger;
- typed evidence combinators independent of argv/files;
- environment compatibility bridges;
- canonical incumbent register;
- atomic adoption and deployment rollback;
- policy and judge lineage;
- evaluator-succession bridge protocol;
- Meta^n succession stress tests;
- a second harness adapter.

## Related intellectual anchors

ProContract draws boundaries from several traditions without collapsing them
into one metaphor:

- intention and commitment explain why future action should resist casual
  reconsideration;
- incomplete-contract theory explains residual control rights under imperfect
  specifications;
- capability security explains delegated effect authority;
- event sourcing and durable execution explain audit and recovery;
- truth-maintenance systems explain defeasible epistemic support;
- cybernetics explains sensing, control state, action, and error signals;
- proof-carrying and supply-chain systems explain content identity and
  provenance;
- evolutionary and recursive-improvement systems explain candidate generation
  and adaptive selection pressure.

The novel conjunction is narrower:

> Completion is treated as a normative, defeasible state transition whose
> evidential defeat restores responsibility, independently of the executor.

Witnessed succession is the proposed extension of that conjunction, not a
completed result.

## Canonical concise statement

For the current implementation:

> ProContract is an executor-independent completion-integrity protocol. It
> conserves duties across ephemeral execution, binds recognized completion to
> an exact subject and authorized evidence reference, and restores
> responsibility when that support is defeated.

For the research program:

> Policies explore improvement; a minimal institution governs witnessed
> succession. ProContract does not guarantee that a successor is better. It
> governs what the system is allowed to recognize, inherit, and retract as
> canonical.

The shortest version is:

\[
\boxed{
Executors\ propose;\quad
evidence\ supports;\quad
authority\ settles;\quad
challenge\ restores\ responsibility.
}
\]
