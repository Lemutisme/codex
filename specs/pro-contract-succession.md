# ProContract witnessed succession

This document specifies a **FUTURE** extension of completion integrity. The
reviewed Codex implementation does not contain a canonical incumbent register,
Adopt/Promote/Rollback commands, policy lineage, judge bridges, or atomic
deployment switching.

## Program thesis

> Policies explore improvement; a minimal institution governs what may be
> recognized, inherited, and withdrawn as canonical succession.

This does not mean the institution discovers better policies. Candidate
generation and semantic evaluation remain fallible edge processes.

## Completion is not succession

Completion is a per-duty predicate. Multiple duties may be discharged
concurrently.

Succession changes one distinguished mutable reference:

\[
incumbent(scope,role)\mapsto
(contract,\ revision,\ subject,\ evidenceCoordinate).
\]

It therefore adds properties not implied by completion integrity:

1. one current incumbent per scope and role;
2. a total order over concurrent adoption decisions;
3. atomic replacement or no replacement;
4. relational evidence comparing incumbent and candidate;
5. activation and rollback of the deployed reference;
6. bridge evidence when the judge or mission changes.

Current challenge semantics supply one useful prerequisite: an authorized
defeater can withdraw support from duties and restore responsibility without
deleting history. They do not retract an incumbent or roll back a deployment.

## Root-relative continuity

Every defensible succession comparison holds some mission semantics, evidence
rule, and authority stable across that comparison. A root need not remain
physically fixed for an entire trajectory.

A root may change through a rolling bridge accepted under its predecessor. A
purely self-authorized replacement can occur, but it does not inherit the
predecessor's meaning of "authorized"; it begins a new normative regime.

For one transition, the root is approximately:

\[
R_t =
(K,\ authentication,\ canonicalization,\ storage,\ capturePolicy,
evidenceEnvelope,\ clock,\ rootAuthority)_t.
\]

## Policy as input and policy as subject

A policy has two different roles:

- when used to execute another duty, it is advisory execution input and should
  remain outside that duty's normative specification;
- when proposed for future use, it is itself a frozen subject of a Policy
  Contract.

This allows policy generators and selectors to evolve without letting the
current execution policy rewrite the duty it is executing.

The current Codex binding supplies a content hash for the first role. That is
policy identity, not lineage or succession: it does not compare candidates,
select an incumbent, or authorize adoption.

## Incumbent register

A future register should contain only exact references:

~~~text
scope
role
generation
mission hash
incumbent subject coordinate
supporting succession certificate
adopted ledger frontier
previous incumbent reference
~~~

It must not contain benchmark-specific score logic or a mutable winner chosen
outside the institution.

## Succession certificate

A finite candidate certificate may bind:

\[
\begin{aligned}
\kappa_t = (&scope,\ frontier,\ missionHash,\\
            &incumbentHash,\ candidateHash,\\
            &oldJudgeHash,\ newJudgeHash,\\
            &environmentHash,\ assuranceCaseHash,\\
            &bridgeHash,\ authorityAttestations).
\end{aligned}
\]

The succession reducer validates identity, current support, role authority,
and atomic transition legality. It does not decide whether one policy is
semantically smarter.

## Judge succession

Replacing \(J_t\) with \(J_{t+1}\) cannot be justified solely by
\(J_{t+1}\). A bridge may include:

- cross-evaluation of incumbent and candidate under both judges;
- stable calibration anchors;
- disagreement cases and error taxonomy;
- environment/evaluator identities;
- exposure and selection history;
- an attestation authorized under the predecessor root.

A minimal cross-score matrix is:

\[
\begin{array}{c|cc}
 & H_t & H_{t+1}\\
\hline
J_t     & * & *\\
J_{t+1} & * & *
\end{array}
\]

No finite bridge proves universal judge validity. It exposes the scope and
authority of the change.

## Succession Integrity

A future structural property may be:

\[
\begin{aligned}
SI ={}&
CanonicalUniqueness \\
&\land NoSelfAdoption \\
&\land IncumbentCandidateIntegrity \\
&\land AuthorityContinuity \\
&\land JudgeBridgeIntegrity \\
&\land LiveSupportClosure \\
&\land AtomicActivation \\
&\land DefeatDrivenRollback \\
&\land QuietSoundness.
\end{aligned}
\]

Under an explicit succession command interface and authenticated root, the
intended theorem would be:

\[
\forall \pi,\quad
Traces(S\parallel\pi)\models SI.
\]

It would not imply:

\[
Utility(P_{t+1})>Utility(P_t)
\]

or convergence to a globally correct policy.

## Evidence inheritance

Frozen history is not inherited assurance.

\[
Reuse(e,o')
\iff
Dependencies(e)\ unchanged
\lor
NonInterference(e,o')\ separately\ established.
\]

A global wrapper, helper override, changed prompt context, router, runtime,
capture policy, or evaluator can invalidate evidence for work that was not the
focus of the change.

Succession certificates should identify which support was rerun, which was
reused, and why reuse remains valid.

## Adaptive selection pressure

Let:

\[
\widehat J(H_m)=J(H_m)+\epsilon_m.
\]

Even with equal true candidate quality:

\[
\mathbb E\left[\max_{m\le M}\widehat J(H_m)\right]
\]

can grow with adaptively inspected candidates. Stronger candidate generators
increase the value of optimizing a proxy as well as the chance of finding real
improvement.

The evidence envelope should therefore record:

- candidate multiplicity;
- evaluator exposure;
- holdout reuse;
- judge version;
- selection history;
- stopping rule;
- paired seeds and budgets;
- selection-adjusted uncertainty.

These are experiment-manifest concepts, not pure settlement-Kernel concepts.

## Relation to Meta^n

[Meta^n: Recursive Self-Improvement through Emergent
Depth](https://arxiv.org/html/2608.24735v1) fixes a meta-operation
\(\Omega\), applies it recursively to expanding code and traces, and searches
an evolutionary archive of candidate chains. Repository observations here
refer to commit
[b7081843](https://github.com/minnesotanlp/meta-n/tree/b7081843d3c7b0e0f418ca10aaf2ccbff856e7f8).

Meta^n and ProContract address orthogonal axes:

\[
\boxed{
MetaDepth\ expands\ what\ can\ be\ proposed;
\quad
InstitutionalContinuity\ limits\ what\ may\ be\ inherited.
}
\]

For an archive \(\mathcal A_r\):

\[
U_r(J)=
\frac{1}{N}\sum_i
\max_{H\in\mathcal A_r}J(t_i,H).
\]

If \(\mathcal A_r\subseteq\mathcal A_{r+1}\), archive-best is monotone by
construction. That does not imply one chain dominates its predecessor, a
composite router generalizes, or the judge still represents the mission.

Meta^n reports archive-best and best-single-chain separately. ProContract
should not criticize it for claiming institutional adoption when it does not.
The legitimate scope statement is:

> Meta^n addresses candidate-generation depth and archive search. ProContract
> specifies a separate settlement and future succession boundary; it adds no
> search-efficiency claim.

Search patience or score plateau means no further candidate was found under a
budget. It is not mission satisfaction or institutional quiet.

## Stress tests

### Archive-to-successor gap

Compare:

- raw archive-best;
- best single chain;
- an explicit composite router;
- a succession-gated incumbent.

Evaluate each as a single deployable system on independent held-out tasks.
Measure false succession, regression, cost, and false rejection rather than
only maximum score.

### Evaluator succession

Select candidates with \(J_t\), then introduce a corrected \(J_{t+1}\).
Compare:

- naive promotion;
- new-judge-only promotion;
- predecessor-authorized old/new bridge evidence.

Track proxy drift, disagreement, responsibility restoration, and rollback.

### Negative control

A protocol that never adopts has zero false succession and no utility.
Evaluation must therefore report both false adoption and false rejection, plus
latency and verification cost.

## Status boundary

At the reviewed Codex prototype:

- duty-level support withdrawal and challenge closure exist;
- canonical incumbent adoption does not;
- external deployment rollback does not;
- judge succession does not;
- no RSI process has been demonstrated.

The strongest present-tense statement remains:

> ProContract implements completion integrity and specifies witnessed
> succession as a future protocol. It does not guarantee recursive
> self-improvement.
