# ProContract reach: what evidence can settle, for any task

Status: design, for review. Date: 2026-10-05. Branch `procontract-rsi` @5597532a59.

It revises three documents:
- the essential spec (`2026-09-29-procontract-essential-design.md`, cited E§n);
- the RSI spec (`2026-09-30-procontract-rsi-design.md`, cited R§n);
- the four-axiom notes (`~/procontract-next-design.md`, cited N§n).

It changes one kernel structure (two coordinate fields) and one kernel rule.

Inputs:
- the evidence calibration (`~/run-artifacts/procontract-rsi-m0-20261001/calibration-v1/REPORT.md`);
- retest-v2;
- the OpenCode evidence and RSI surveys (2026-10-04);
- the paper's P1–P4 and its adoption corollary (`~/ICLR_paper/contents/2_prelim.tex:81`, `3_theory.tex`).

## 1. From one measurement to one principle

**The measurement.** An independent prober froze 168–286 sealed differential cases per task. It was a separate worker in a
separate role. The reference program answered every case. The cases then judged 95 frozen candidates whose hidden-test
pass rates were known. Results:
- Across tasks, the sealed pass rate barely tracked the hidden one: ρ = 0.28.
- Within a task, it ordered candidates correctly 81–92% of the time.
- Every candidate it scored at 0.99 or above still fell short of 0.95 on the hidden tests.

**The cause.** The roles were independent; the information was not. The prober read the executor's documentation. It
asked the executor's oracle questions the executor could have asked itself. Its evidence therefore measured how well the
executor used what it had. It could say nothing about what the executor lacked: which behaviors the principal's tests
weigh.

> **Reach.** Evidence settles only what it carries from beyond the reach of the claim it judges. Evidence from within that
> reach measures diligence and can rank alternatives. It cannot certify.

**Definitions.**
- The **reach** of a claim is what its producer could read or ask, together with what every process that selected the
  claim read.
- The **criterion** is what the principal will finally accept. It splits in two:
  - the part fixed by information within reach;
  - the part fixed only beyond it.
- Evidence certifies that second part only as far as its basis reaches beyond.

| Task | Where the criterion lies | What evidence from within reach can do |
|---|---|---|
| A formal proof under a checker | Wholly within reach: the statement and the checker | Certify. Checking is settling |
| Re-implement a program against a reference | The reference is within reach, but which behaviors the principal's tests weigh is not | Rank and measure diligence. Not certify (§1) |
| Any request read from natural language | Intent beyond the words is beyond reach until the principal speaks | Nothing about intent. Only the principal closes it |

A formal proof and a hidden test suite are not different kinds of task. They are the same principle at two settings of
where the criterion lies.

## 2. The kernel, read through reach

The kernel's sentence changes in two phrases:

> Executors propose; evidence **from beyond their reach** supports; authority — **the holder of what lies beyond** —
> settles; accepted defeat restores responsibility.

"Authority settles" turns out to be an information necessity, not a governance preference: only the holder of what lies
beyond can close the gap that evidence from within reach leaves open. Delegation is how the principal lends it:
- a hidden test suite;
- a rubric;
- a pre-authorized convention.

This is why delegated material must stay sealed from the claimant. Once read, it is within reach.

The four axioms do not change. Each already had an information reading, which is now explicit:

| Axiom | Role reading (today) | Information reading (now explicit) |
|---|---|---|
| **A1 Monopoly** | The executor has no settling verb | Nothing may settle on evidence from within reach alone, except the explicit human, who *is* the beyond |
| **A2 Exactness** | A recognizing command binds the full coordinate | The coordinate also binds the evidence's **basis** and its **reach** |
| **A3 Conservation** | Outstanding duty ends only by authorized discharge or release | **Certifying power is conserved too.** A source read by a selection can no longer certify that selection; exposure only accumulates |
| **A4 Defeasance** | Accepted defeat restores responsibility; history only appends | The record stays open to information from beyond that arrives later: a settlement, a new test, a reversal |

## 3. Reach, defined at the institution

These definitions live at L1 (the institution). The kernel only records what the institution asserts (§4).

- **Source.** A content-addressed unit of information. Examples:
  - a request;
  - a workspace snapshot;
  - documentation;
  - a test suite;
  - a human statement;
  - a settlement record;
  - a prior run's records;
  - an **oracle**, as a capability;
  - an **oracle answer** to a chosen question.
- **View.** The sources a run may read and the oracles it may ask. The host fixes it when it launches the run: it is the
  `View` of `Run_v(τ, View, W, B)`. The run never sets its own view.
- **Lineage view of a claim.**
  - The view of the run that produced it;
  - plus the views of every run whose outputs selected it, including research-parent choices and candidate selection;
  - plus every source exposed to those runs.
- **Basis of a piece of evidence.** The sources it depends on. For an oracle answer, the basis is the pair *(oracle,
  chooser of the question)*.
- **Beyond.** Evidence is beyond a claim when its basis contains information **from the criterion's holder** that lies
  outside the claim's lineage view. Examples:
  - the principal's statements and settlements;
  - a delegated hidden test suite or rubric;
  - a pool the principal sealed.

  Independence from the producer is necessary but not sufficient (corrected after §9.1):
  - An oracle answer to a question chosen from within the view is within reach, because the producer could have asked
    it. §1 measured exactly this.
  - Questions chosen outside the view by anyone other than the criterion's holder can be independent and still carry
    nothing about what the principal weighs. Disagreement between peers and seeded random draws are examples.
- **Exposure ledger.** For each source, the runs that read it. Reading adds the source to their lineage views. Exposure is
  append-only and never resets (P1).

R§3.2's instruments become instances, not separate rules:
- a pool commitment is a sealed set of sources;
- a query budget is how much certifying power the campaign may spend;
- the information diet is the view.

## 4. The change, by layer

### L0 kernel: two fields and one rule

```text
Coordinate += basis: Digest     // the evidence's basis set, content-addressed
            , reach: Reach      // Within | Beyond: asserted by the authenticated verifier, recorded verbatim
```

**Rule (sharpens A1 under A3).**
- A Discharge with `DecisionProvenance::Presumed` or `Interpreted` requires current support whose reach is `Beyond`. Neither
  provenance involves an explicit human act.
- An `Explicit` discharge may rest on `Within` support: the human supplies what lies beyond. The settlement records that it
  did.

Nothing else in the kernel changes:
- Comparative claims need no new kernel field. Their baseline is bound in the terms, as the adoption contract already binds
  its expected incumbent (R§3.4).
- Reach joins the coordinate fields the kernel records but cannot verify, like the environment and evaluator digests. The
  institution computes it; the kernel keeps it exact.

**Admission test** (N§1: what is the shortest counterexample if the field is removed?):
- In retest-v2, two of three supported candidates fell short of the hidden bar.
- In OpenCode, admitted evidence passed 64/64 while hidden tests passed 75.8% (eva). The same happened with ngrrram,
  i3-style and cppcheck.
- N§0 already states that internal assurance passing is not out-of-distribution utility.

Without reach, every one of these reads as "supported".

### L1 institution

- **Views.** Fixed at launch.
- **Exposure ledger.** Kept per §3.
- **Reach.** Computed from basis against lineage view.
- **Confirmation.** Draws only on sources unexposed to the candidate's lineage and to the selection.
- **Status names the reach.** A status reads "supported (diligence)" or "supported (certified)", so no consumer mistakes
  one for the other.

### L4 policy plane

- **One execution primitive for tasks and for research.** `Run_v(τ, View(C, A), W, B)`:
  - `v` is an exact version;
  - `τ` is a task;
  - `C` is the contract state;
  - `A` is the research archive;
  - `W` is an isolated workspace;
  - `B` is a budget.

  An ordinary task delivers an artifact. An improvement task delivers an experiment and possibly a version. Both go through
  the same proposal, judgment and settlement.
- **The first evolvable decision is what to ask beyond reach, and when.** Internal compute raises diligence: more
  candidates, more reasoning, more checks within reach. Only questions answered from beyond reach raise the ceiling.
  Information acquisition is therefore where improvement compounds.

## 5. Succession: the same rules one level up

RSI adds no mechanism. Only the subject of the claim changes.

| Level | Claim | Exploration (no authority; any information) | Adoption (beyond-reach support; authority) |
|---|---|---|---|
| Artifact | "This delivery meets the terms" | Compare generations during repair | The principal settles, or a delegated beyond-reach check |
| Version | "v′ is at least as good as the incumbent" | Choose a research parent | A comparative claim with the incumbent as baseline, supported only by sources unexposed to the candidate's lineage and to the selection |
| Method | "Generator g₁ yields better successors than g₀" | Choose which method to keep researching | M(g): same parent, same experience, same budget; selection on development evidence only; confirmation on fresh sources |

Consequences already stated elsewhere, now as corollaries of reach:
- **A research parent needs no evidence beyond the rule that picks it**, because the parent role carries no authority
  (paper, adoption corollary).
- **No version adopts itself, and adoption follows its evidence.** A version's own outputs are within its reach.
- **Rollback moves execution, not authority.** Execution state is within reach; settlements are records of what lay beyond.
- **A research task may succeed by refuting its hypothesis.** It owes an experiment, not a better version. Research
  progress and version progress are different claims.
- **Meta^n truncation is unchanged.** Everything mutable may improve itself; nothing normative revises itself. The fixed
  point is the kernel, the root evaluator and the principal.

**Measuring improvement of the method.**

M(g) = E_{p,ξ}[ J_fresh(v̂_g(p, E, B)) − J_fresh(p) ]

where `v̂_g` is the successor that method g selects from parent p, experience E and budget B, on development evidence
alone. Picking the best descendant by its fresh score would turn the confirmation set into a selector, that is, bring it
within reach.

## 6. Why comparison is the efficient use of what lies beyond

A comparison between two alternatives on the same task cancels common-mode error:
- the task's difficulty;
- the evidence's bias;
- the score's scale.

Two consequences:
- **Comparative evidence from within reach ranks well** (81–92% in §1). It is the right instrument for exploration:
  choosing parents, branches and repairs.
- **Information from beyond is scarce** (≈ 11 pp standard deviation per paired run; about 37 pairs to detect +5 pp). It is
  best spent on paired comparisons against the incumbent, tested sequentially and stopped early.

So reach decides *what may be concluded*, and comparison decides *how cheaply*.

## 7. Any task, in deployment

Outside a benchmark there are no hidden tests. What lies beyond reach arrives through the principal's settlements:
explicit acceptance, rejection, or the implicit acceptance the essential spec defines (E§).

- **Adoption** is a sequential test over that stream.
- **A turn for the worse** is an accepted defeat, and A4 rolls the incumbent back.
- **What accumulates** is settled questions: *(context, question, answer from beyond, provenance)*, each with its exposure
  record. They become the next task's checks and the next version's confirmation material. Exposure keeps them honest.

## 8. Seeing the large in the small

| Observation | Reach reading |
|---|---|
| Sealed suite: ρ 0.28 across tasks, 81–92% within | Evidence from within reach ranks; it does not certify |
| A proof checker certifies | The criterion lies wholly within reach |
| OpenCode: internal evidence passed routinely while hidden scores were low | The same as the sealed suite |
| Hand-made held-out suites repeatedly picked the wrong official best; adaptive reuse of a holdout overfits | Exposure consumes certifying power (A3) |
| The drafter's terms can miss the request (termsGap) | Whether the terms are faithful to the request lies beyond the drafter; only the principal settles it |
| v7: the envelope alone cost −4.55 pp; envelope × policy gained +3.42 pp (N§0) | Accounting yields nothing from beyond by itself; it pays only when it feeds a learner |
| A worker renamed the root reference and voided a campaign (N§2.4) | A selection that touches its own confirmation brings it within reach |
| Goodhart's law | Optimizing a measure that lies within your own reach |

## 9. Falsifiable predictions and the next experiment

1. **Questions chosen outside the producer's view outperform questions chosen within it. Tested, and falsified.**
   - **Design.** At 40 oracle queries per candidate, compare three ways of choosing questions:
     - (a) from the documentation;
     - (b) where leave-one-out peers disagree over a 400-case mutated pool;
     - (c) by seeded random draws from that pool.
   - **Results** (75 candidates, `calibration-v1/reach-experiment/REPORT.md`):

     | Choice | Overall ρ | Within-task concordance | Missed at ≥ 0.95 |
     |---|---|---|---|
     | (a) Documentation | 0.31 | 0.81 | 10 / 21 |
     | (b) Peer disagreement | 0.29 | 0.65 | 9 / 9 |
     | (c) Random draws | 0.02 | 0.77 | 5 / 5 |

   - **Reading.** The partition "inside versus outside the producer's view" was too loose. Neither peers nor random draws
     hold the criterion, so their independence bought no certifying power.
   - **Correction.** Beyond now requires information from the criterion's holder (§3). The kernel sentence already said
     so: authority is the holder of what lies beyond.
   - **What the corrected definition predicts.** Only principal-side sources certify: hidden tests, settlements, sealed
     delegated suites. The development-time instruments ((a)–(c)) rank but do not certify.
1b. **Only the criterion's holder certifies.** For a fixed query cost, evidence drawn from a principal-side source predicts
   the principal's verdict better than any producer-independent source. For example, take a disjoint half of a delegated
   suite as the evidence and score it against the other half. The test is close to definitional for random halves. It is
   informative when the delegated half is small or skewed, and in deployment, where settlements are the only such source.
2. **Comparative evidence from within reach is enough to choose research parents.** Prospectively, the parent it prefers is
   more often better on fresh confirmation than chance.
3. **Reach predicts reliability.** Settlement on `Beyond` support misses fewer defects than settlement on `Within` support.

## 10. Limits

- **Model weights are an unseen source.** Pretraining may already contain a "beyond" (contamination). The only mitigation is
  fresh tasks.
- **Beyond is not the same as accurate.** Reach bounds what may be concluded, not how precisely. Precision comes from
  comparison and sequential testing (§6).
- **Granularity.** Bases are sets of sources, not tokens, and the chooser of a question is part of the basis.
- **The kernel cannot verify reach.** It records the institution's assertion exactly, as it records environment digests.
  Getting views and exposure right is the institution's job, which is why the institution sits outside every version's
  write authority (R§7).

## 11. The first end-to-end slice (implemented)

**Commits:** `7fbc33d107` (kernel), `54e96c3162` (bundle), `48ddb785d0` (host).

- **Kernel.** The coordinate carries `basis` and `reach`. A discharge without an explicit human act needs `Beyond`
  support. The lane's own support is `Within`, and its status says it measures diligence.
- **A version is a policy bundle run by one codex binary.** The bundle has five files:
  - `executor.md`: the executor's developer instructions;
  - `research.md`: the research method;
  - `drafter.md`, `prober.md`, `reviewer.md`: the judgment workers' instructions.

  Version 0 is the shipped `ext/pro-contract/policies`. Schemas and the case format are protocol and do not change. The
  lane's identities carry the bundle digest, so the host can witness which version ran.
- **The protection a version needs is set by what it can change.** A bundle is data loaded by a fixed binary. A
  candidate therefore cannot touch any of these, which hold by construction:
  - the host;
  - the kernel;
  - the builder;
  - its own evaluation.

  Process isolation (R§7, M1) becomes necessary when harness code becomes mutable. The same loop then gains a builder,
  and nothing else changes.
- **The host** (`scripts/procontract_rsi.py`) runs from its own checkout and holds the campaign:
  - terms;
  - ledger;
  - versions;
  - runs.

  One step:
  1. The host chooses a research parent: the newest qualified version, unless it regressed against its own parent on
     development tasks; otherwise the best by development mean. This is exploration and carries no authority.
  2. The parent runs an improvement task under its own `research.md`. The task's view is its bundle (editable) and the
     development archive with the research history. Confirmation sources never enter that view.
  3. The host qualifies the delivery mechanically. The criterion is complete, so support is `Beyond`, and the host
     settles it under the campaign's convention.
     - An unchanged bundle is a null experiment: the research is done and no version is made.
  4. The host witnesses the candidate's bundle in a development run, then measures it on development tasks.
  5. If the candidate earns it, the host spends fresh tasks from a sealed pool on paired confirmation against the
     incumbent. Each task certifies once. The confirmation evidence supports adoption from beyond the candidate's reach.
  6. Adoption is the principal's explicit act unless the campaign pre-authorizes it.
- **The successor really succeeds.** A new incumbent serves the next tasks. Every research step runs its parent's own
  `research.md`, so v1's method produces v2.
- **Tested end to end without models:**
  - the v0 → v1 → v2 chain under both adoption modes;
  - a candidate that stays in research while the incumbent serves;
  - a null experiment;
  - a released, incomplete delivery;
  - resumption after a crash;
  - one retry of an invalid run, never scored zero.
- **Acceptance on real runs** (the proposal's bar):
  - a real v0 → v1 → v2 chain with independent incumbent selection;
  - at least one candidate kept in research without being deployed;
  - one recovery after a failure.
