# ProContract RSI: built-in recursive self-improvement on the essential ProContract

Status: design, for review. Date: 2026-09-30. Branch `procontract-rsi`, based on `procontract-essential-impl` @95332dce91
(itself on upstream `67727e7cf1`). This spec builds on
`docs/superpowers/specs/2026-09-29-procontract-essential-design.md` (the **essential spec**, cited as E§n) and replaces
its §10.1 ordering.

Inputs:
- the essential slice's validation (`~/run-artifacts/procontract-essential-20260930/REPORT.md`);
- a survey of earlier RSI experiments (`~/scratch/procontract-essential/survey-prior-rsi-20260930.md`);
- Astra rounds 8 and 9 (`astra-round8-rsi-20260930.md`, `astra-round9-rsi-lifecycle-20260930.md`);
- the paper (`~/ICLR_paper/contents/`: P1–P4 at `2_prelim.tex:81`, the four decisions at `3_alg.tex:52-54`, the
  adoption corollary at `3_theory.tex:33-54`);
- `~/procontract-next-design.md` §2 (Meta^n truncation).

## 1. Goal and principles

**Goal.** Recursive self-improvement built into ProContract with no second mechanism. RSI is ordinary contracts whose
subject is a version of the harness. Generation is performed by the current version's own harness. Judgment, custody
and adoption stay outside every version's write authority.

**Principles.**

1. **Contract as loop.** Improvement, promotion and adoption are contracts. Research-parent selection and scheduling are
   protected controller computations over immutable events (paper `3_theory.tex:46-51`). The kernel's four axioms are
   unchanged.
2. **Mutable versus normative, not internal versus external.** Everything mutable may improve itself. Nothing normative
   may revise itself. The fixed point is the kernel, the root evaluator and the human (Meta^n truncation).
3. **Explore freely on the development pool; judge rigidly on fresh data.** Exploration only decides what to test.
   Held-out data is spent only through accounted, preregistered queries, and each confirmation allocation serves one
   candidate.
4. **Causality from randomization at this scale.** Effect claims come from randomized paired experiments. Diagnostic
   replay only targets proposals.
5. **Measurement before optimization, protection before running generated versions** (the Astra round-8 order: fixed
   rules → protection → continuity → qualified generation → recursive generation → adoption).
6. **Zero adoptions is a legitimate result.** Gates are never relaxed after results are seen.

**Non-goals.**
- Model-weight self-improvement.
- Autonomous incumbent adoption in the first slices.
- Non-Rust instances in M0.
- Interactive-product RSI (implicit acceptance is not ground truth, E§9).
- Evolving the institution itself.

**What counts as what.**
- *Recursion*: v_{k+1} = G_{v_k}(E_k), where G is implemented by v_k's own package.
- *Replaceability*: a new process continues an Outstanding contract with its bindings intact.
- *Improvement*: an independent, powered, preregistered comparison on fresh data. Parentage is never evidence.

## 2. Layers and authority

| Layer | Content | Evaluated by | Self-improvable |
|---|---|---|---|
| L0 | executor harness code and strategy text; Principal judgment policies (drafting, differential-case generation, review, brief, repair) | the root evaluator on tasks | yes, proposed by L1 |
| L1 | generator (successor-generation routine), explorer (acquisition policy), belief statistics | prospective equal-budget randomized lineages (§8) | yes (it lives in the version package) |
| L2 | campaign terms: pools, gates, thresholds, budgets, information diet, mutable-component whitelist, adoption authority | normative | no; the system may file a petition, and a human Revises |
| fixed point | kernel, ledger and custody, root evaluator (not self-modifiable; operator corrections are new evaluator epochs), human | — | never |

Authority that no version may hold:
- writing the institution (kernel, ledger, blobs, events, labels);
- choosing roles;
- starting containers with arbitrary flags;
- holding the model credential;
- reading select or confirm pool contents or hidden tests;
- selecting its own selector;
- adopting itself.

## 3. Primitives and data model

Four primitives and two derived views. The only kernel change is deferred: a `pre_authorized{rule_hash}` decision
provenance, for the day adoption becomes rule-based. Everything else is institution-level.

### 3.1 Version

A version is a content-addressed manifest (canonical JSON in the blob store):

```text
Version {
  schema: 1,
  harness: { source_tree: Digest, build_recipe: Digest },    // executor harness (codex source)
  policies: { drafter, case_generation, reviewer, brief, repair: Digest },  // judgment policy bundles
  generator: Digest,                                          // successor-generation routine (L1)
  explorer: Digest,                                           // acquisition policy (L1)
  model: { id, effort },                                      // part of identity; a model change is a new version
  config: Digest,
  state_schema: u32,
  lineage: { parents: [VersionId], proposed_by: VersionId | Operator, operator_seed: bool },
}
VersionId = digest_of("version", manifest)
```

A **build receipt**, produced by the protected builder, binds a VersionId to executable and image digests, the
toolchain, dependency digests and the qualification gates it passed. A version without a receipt is not runnable.

### 3.2 Campaign contract

- A human Issues it, and it stays Outstanding for the campaign's life. Its subject is the campaign report.
- Its terms bind:
  - opaque pool commitments (salted hashes of the dev / select / confirm instance lists);
  - the query budget per pool;
  - the T2/T3 gates and thresholds;
  - total and per-tier budgets and stop rules;
  - the mutable-component whitelist;
  - the information diet;
  - the adoption authority.
- A human may Revise while it is Outstanding (E§4, `transition.rs:259`).
- Expenditure and consumed queries are cumulative events, so a revision never resets them or makes consulted data fresh
  again (P1).
- Closing: the human Discharges it on the final report, or Releases it.

### 3.3 Improvement contract

- **Subject:** a version manifest.
- **Executor:** the expanded node's own harness (the institution launches that version's binary).
- **Terms:** one hypothesis, its target deficiency, the predicted effect and metric, the single component it may
  change, and the campaign hash.
- **Evidence class `qualification`:**
  - hermetic protected build (receipt);
  - conformance suite;
  - the manifest diff is confined to the declared component and no normative path;
  - a **host-collected mechanism witness**: the changed code path or the new policy identity actually executes on a
    smoke task.
- **Outcomes:** Support means "qualified". Qualification says nothing about utility.

### 3.4 Adoption contract

- One per candidate put forward. **Subject:** the candidate VersionId. Its terms bind the campaign hash and the
  **expected incumbent**.
- Its evidence policy is the entire promotion protocol (qualification receipt, custody gates, T2, T3), so the result is
  **one support certificate**. Withdrawing any piece of promotion evidence is a Withdraw of that support: atomic, with no
  support-dependency DAG (E§4.5 stays deferred).
- It owes "adopt iff the preregistered gates pass". A failed gate leads to Release under the campaign's
  pre-authorization; nothing is left owed forever.
- Discharge is the adoption act. It belongs to the human Settler in every slice of this spec.

### 3.5 Experiment events

An append-only, hash-chained table in the institution store. It replaces the mutable `records` table for research data.

```text
ExperimentEvent =
  | Acquisition { campaign, explorer: VersionId, options: [..], chosen, propensity }
  | Assignment  { campaign, version: VersionId, task, pool, repeat, seed, order }
  | Execution   { assignment, run_id, subject_hash, receipts, cost, witnesses, identities }
  | Label       { subject_hash, evaluator_epoch, environment, outcome: {solved, score, raw_counts}, validity }
  | Query       { campaign, pool, candidate: VersionId, tier, result_bits }
  | Correction  { of: event_seq, reason, evaluator_epoch }
```

- Every event carries the identities of what produced it: harness binary, policy digests, model/effort, evaluator epoch.
- Labels attach to the **exact judged subject**, never to a live workspace.

### 3.6 Derived views

- **Incumbent**: the most recently Discharged adoption contract that is still Discharged.
  - When a Discharge is applied, the institution checks in the same transaction that the adoption's bound expected
    incumbent equals the current incumbent. There is no pointer write, no crash window and no stale promotion.
  - A Challenge or Defeat on the latest adoption makes the view fall back to the previous still-valid adoption, which is
    authorized and qualified by construction.
- **Routing**: the incumbent, unless the operator has set an emergency suspension, which is operational and not
  normative. Contracts in flight continue under the version they started with, through fenced continuation (P3).
- **Frontier, calibration tables and cost ledgers**: pure functions of events and contracts.

Rollback is three distinct operations:
- artifact regression → Challenge or Defeat of the adoption claim;
- compromised judgment → Withdraw of its support;
- operational failure → routing suspension.

## 4. Lifecycle

```
observe → explore → improve → evaluate (T0→T1→T2→T3) → promote → monitor
   ↑                                                              │
   └───────────────── new labels, new deficiencies ───────────────┘
```

1. **Observe.** Ordinary contracts leave judgments. The protected evaluator attaches Labels where an external outcome
   exists. Calibration tables per version and component are derived: P(solved | supported), missed-defect rate, false
   defeats, abstention, cost. Labels are not free; the campaign budget pays for them.
2. **Explore.** The explorer (§5) chooses a node to expand, a component and tasks.
3. **Improve.** An improvement contract is Issued. The chosen node's own harness produces the candidate, which is
   qualified (§3.3).
4. **Evaluate.** Tiers (§6).
5. **Promote.** Research-parent status is a controller computation over events: cheap and revocable. Adoption goes
   through an adoption contract (§3.4).
6. **Monitor.** The adopted version first serves a share of new work (canary). A regression leads to a Challenge of the
   adoption, and the incumbent view falls back.

## 5. Exploration

**Substrate.** Everything that follows is a derived view over it, so tree, MCTS and causal explorers all plug in later:
- a content-addressed provenance archive, outside any cleanup's reach;
- immutable experiment events with propensities;
- diagnostic replay packets at component boundaries.

**Structure.**
- Nodes are versions. An edge is one intervention on one component, with a stated hypothesis.
- One-component edges label interventions. They do not by themselves establish attribution; randomized paired
  comparison does.
- Merges (two parents) are deferred. An interaction claim needs matched base, A, B and A+B evaluations.
- Rejected nodes remain explorable stepping stones. Nodes that failed custody or qualification are never executed.

**First explorer (fixed in the first slice): bounded branching.**
- Each expansion proposes 3 children.
- The 2 best *qualified* children by development evidence are expanded next.
- 20 % of expansions draw uniformly from the eligible archive.
- Depth and width caps come from the campaign.
- Allocation is round-robin at first, then modest ranking on dev evidence.
- In effect this is a depth-1 MCTS with ε-uniform exploration.

**Graduation path:** deeper subtree-yield backups → Thompson sampling → merges. Each is an L1 change, allowed only when
per-node child counts can support it, and evaluated prospectively (§8).

**Node statistics.** Direct child yield per *all* charged cost, qualification rate, dev improvement. Subtree
productivity is the objective, not an estimate. T0 calibration gains are never backed up as utility.

**Diagnostic replay (targeting only).**
- Unit: the immutable checkpoint or input packet at the intervention boundary, plus a defined downstream policy.
- Reviewer swap: exactly recomputes the judgment on identical terms, artifact and receipts; model reviewers are
  sampled.
- Case-generation swap: measures detection quality on saved artifacts. It is not the effect of deploying the drafter.
- Repair or executor components: restore the checkpoint and rerun the suffix.
- Labels stay tied to the human request, never to an alternative drafter's narrowed terms.
- A representative audit sample runs alongside targeted diagnostics, so selection is never on outcomes alone.

**Information diet (normative, bound by the campaign).**
- The explorer sees dev outcomes, T0 replays and diagnostic reports.
- From select and confirm it sees only authorized gate results, under campaign-wide query accounting that spans branches,
  clones, merges and campaign successors.
- It never sees hidden tests.
- Evaluated replicas' memories, rollouts, caches and workspaces never flow back to the explorer.
- Errors and timing carry no pool details.
- The explorer proposes acquisitions; the institution applies fixed admission rules.

## 6. Evaluation

| Tier | Content | Measures | Data |
|---|---|---|---|
| T0 | diagnostic replay on saved artifacts | diagnostic quality only; it cannot raise the solved rate of frozen artifacts | dev corpus |
| T1 | randomized paired runs against the parent on a dev audit panel: randomized order, repeated independent model draws, recorded inclusion probabilities | effect estimate | dev |
| T2 | preregistered paired comparison against the incumbent; fresh batches, or a justified adaptive-testing protocol; sequential test with alpha spending | selection gate | select, query-accounted |
| T3 | one preregistered candidate per fresh confirmation allocation; after a failure, fresh data | adoption gate | confirm |

- **Primary utility:** instances fully solved (✅) at a fixed total budget.
- **Secondary:** score above each instance's measured null floor; cost and latency distributions.
- **Hard gates:** custody and safety invariants.
- **Invalid rows:** a preregistered policy (bounded reruns, then `invalid`), recorded and never dropped.
- **Labels:** each carries evaluator epoch, image digests and ignore-policy version; corrections are append-only.
- **Sample sizes (guidance, frozen per campaign).**
  - Paired ✅ outcomes at 20 % discordance need about 160 independent pairs for +10 pt and about 630 for +5 pt (5 %
    two-sided, 80 % power). Cluster by task, not by test or seed.
  - False-support bounds: 0 of 60 supported artifacts bounds the rate at about 5 %; 0 of 300 at about 1 % (95 %).
  - With 107 Rust instances split three ways, end-to-end +5 pt claims are out of reach. Claims are narrowed; statistics
    are never relaxed.

## 7. Protection boundary (sub-project M1; design level here)

The institution becomes a **separately protected service** (E§3.6), run as its own OS user (`pcinst`) and reached over
a Unix socket. Every harness version is an unprivileged client.

- **Service-owned:**
  - kernel, ledger, blobs, experiment events, campaign and adoption state, derived views;
  - capture and freezing: the service reads the workspace itself;
  - check orchestration, with candidate and reference in separate execution namespaces and outputs compared service-side,
    which closes the same-uid `/proc/<pid>/fd` and detached-process forgery vectors of the v1 pipeline;
  - the judgment-worker launcher, running authoritative policy bundles;
  - the root evaluator and pool contents;
  - the builder;
  - the scheduler and explorer runner;
  - the budget meter.
- **Environment broker.** The harness's `environments.toml` names a broker client. The service starts the cleanroom
  container with fixed flags (`--network none`, `--user 1000:1000`, prescribed mounts). The harness holds no Docker
  socket.
- **Model broker.** A local proxy owned by the service holds the credential and meters per-contract spend. The
  harness's provider `base_url` points at the broker.
- **Capabilities, not roles.** A client receives scoped capability tokens: for example "Executor of contract C,
  generation g". The service derives the role from the token, never from a client-supplied field.
- **Thin client.** The extension forwards intake, turn boundaries and idle events, and receives the brief and residuals.
  Drafting, verification and decision run service-side.
- **Continuation with leases.** The service grants a process a fenced lease on a contract. A new process (possibly a
  new version) receives a fresh lease plus bounded continuation context, and late writes from the old lease are
  rejected.

The M1 sub-project gets its own spec and plan. Its acceptance tests are adversarial:
- forged Support;
- writing authority files;
- a budget reset;
- a stale-lease write;
- a hidden-data read;
- container-flag injection.

## 8. Meta-optimization

- **L1** policies (generator, explorer) are version components.
- A new L1 policy is evaluated **prospectively** by equal-budget randomized lineages: fixed generator/explorer,
  recursive, and sham (no-op edits, which measure resampling). Lineages are matched on proposal count, sampling,
  selection opportunities and evaluation spend.
- Off-policy evaluation over logged propensities is only for choosing among a finite, overlapping menu of observed
  actions. It never evaluates a new generator, whose descendants are absent from the log.
- **L2**: the system may file a petition (a proposed campaign revision with evidence). Only a human Revise adopts it,
  and consumed queries and expenditure carry over.

## 9. Sub-projects and order

| # | Sub-project | Deliverable and success | Falsifier | Cost |
|---|---|---|---|---|
| M0 | Measurement (§10) | pinned evaluation manifest; certified-snapshot labels; immutable experiment events with identities; pools and seen-list; batch runner; dev artifact corpus v0 | drift, unexplained missing rows, label ≠ judged subject | about 60 full runs plus replays (user approval at plan time) |
| M1 | Protected institution service (§7) | service, brokers, capabilities, thin client, hardened referee, fenced continuation | any adversarial acceptance test passes an attack | largest engineering item; ≤10 synthetic episodes |
| M2 | First RSI slice: bounded branching evidence-package succession | one campaign; the mutable component is the *evidence package* (`policies.case_generation` plus `generator`, named together as one whitelist component); ≤6 candidates, depth 2, fixed explorer; ≥2 branches produce grandchildren through their own qualified packages; T0 on the mixed dev corpus plus small paired T1; synthetic promotion and withdrawal races; no production adoption | a budget reset, a hidden-data return path, a stale promotion, a rejected package affecting the default path | ≈3–6 generation episodes plus replays plus ≤30 T1 runs |
| M3 | Paired end-to-end pilot | ON(v_k) vs ON(v0) vs OFF on the select pool under the query budget | calibration or cost regression | ≈120–180 runs |
| M4 | Preregistered confirmation, then a human-adopted canary; then harness-code components | one T3 per allocation; canary monitoring and fallback exercised | contamination, failed gates | scoped to the corpus |

Each of M1–M4 gets its own spec, plan and review before implementation.

## 10. M0: measurement (plan-ready)

M0 makes every later number trustworthy. It changes the extension, the runner and the evaluation pipeline, not the
kernel.

1. **Evaluation manifest.** Pin the ProgramBench commit, image digests (never tags), the ignore-policy version and the
   evaluator CLI version. Every Label records them as its evaluator epoch. The runner refuses to evaluate when a pin
   drifts.
2. **Certified-snapshot labels.**
   - The ON arm labels the frozen subject that was judged. For each verification the runner materializes it from the
     blob store by `subject_hash` and packages *that*, not the live workspace.
   - The OFF arm, and the ON arm's final handoff, are captured by the same capture policy at run end, and are labelled
     by subject hash.
   - The label reports `subject_hash`; packaging exclusions are unchanged (`./executable`, `./target`).
3. **Immutable experiment events** (§3.5), as a new append-only, hash-chained table next to the ledger. Research
   writes go there; the `records` upsert stays only for operational status. Every event carries harness binary sha256,
   policy digests, model/effort and evaluator epoch.
4. **Reviewer identity in certificates.** `evaluator_digest` binds the reviewer prompt, model and configuration, not
   just the check script and image.
5. **Measurement-relevant deferred minors from the essential slice.**
   - Failure logs keep head and tail.
   - The reviewer is told to answer `cannot_judge` when the candidate view omits files that matter.
   - The reviewer prompt respects its 60 K evidence cap.
   - `turn.status` is recorded in run records.
   - The runner stops when no status record appears 10 minutes after the first turn completed.
   - `digest_of` fails loudly on serialization errors.
6. **Pools.**
   - Restrict to the 107 Rust instances. Instances used in earlier experiments are **dev-only**; the seen-list is
     compiled from `~/run-artifacts` manifests and the paper's task lists.
   - The remainder is split dev / select / confirm by a salted hash of the repository name, stratified by difficulty
     where it is known.
   - Commitments are recorded; the select and confirm lists are sealed in the operator's store and never passed to any
     harness.
7. **Null sentinels.** A null submission is scored for every corpus instance, giving the per-instance null floor and
   validating the evaluator. Branch errors (`results_read_failed`) are classified and follow the invalid-row policy.
8. **Batch runner.**
   - Parallel, detached from tool timeouts, resumable.
   - Per-run manifests: instance, pool, arm, version identities, seed, order.
   - Randomized run order; preregistered invalid-row handling.
   - Cost accounting from rollouts: executor and workers, cached and uncached.
   - Content-addressed archive outside any cleanup's reach.
   - Instances are generalized from csview to any Rust instance; the cleanroom and task images are resolved and
     verified per instance.
9. **Corpus v0.** About 30 dev Rust instances × {ON, OFF} × 1, with one binary built from the M0 branch head (it
   includes the essential slice's final-review fixes), recorded as version v0. For each run it keeps:
   - the base, every frozen subject, terms, cases, receipts and verdicts;
   - labels on every frozen subject;
   - costs.

   Before launch the user approves the run count and budget.
10. **M0 report.** Per-arm solved counts with null floors; P(solved | supported), the missed-defect rate and the
    false-defeat rate with confidence bounds; cost distributions; measured noise (a few duplicated runs), which sizes
    M2–M4.

**M0 tests.** Unit tests for:
- event chaining and immutability;
- identities present on every event;
- the label attaches to the materialized subject, not the workspace;
- pool assignment is deterministic under the salt, and the seen-list forces dev;
- an evaluator pin drift refuses the run;
- the invalid-row policy;
- the reviewer identity changes `evaluator_digest`.

Plus a smoke run on one dev instance end to end before the corpus launch.

## 11. Lessons from earlier experiments → mechanisms

| Lesson (survey) | Mechanism here |
|---|---|
| Development gains did not survive confirmation | T3 on fresh data; adoption is a separate contract; zero adoptions is legitimate |
| Noise ≈ effect size (±4pp) | paired randomized T1 with repeats; power guidance frozen per campaign; M0 measures the noise |
| Changes that never ran were scored | host-collected mechanism witness in qualification |
| Invalid rows aborted generations | preregistered invalid-row policy; conservation, never dropped |
| Research parent ≠ incumbent worked | a controller-computed parent view plus adoption contracts |
| Thresholds moved after results | campaign terms are hash-bound; only a human Revise changes them; queries carry over |
| Unreachable objectives meant zero promotions | utility is ✅ at budget plus a secondary null-floor score; pools stratified by difficulty |
| A cleanup deleted the artifacts | content-addressed archive under the service's custody |
| Confirmation pools ran out | campaign-wide query accounting; one candidate per allocation |
| Fixed-generator and sham controls were never run | a mandatory part of §8 before any recursion claim |

## 12. Risks and open questions

- **Scale:** 107 Rust instances cap every claim. Other languages need their own prompts and toolchains (post-M4).
- **Cost:** a full run is 25–60 min and 30–70 M mostly-cached tokens. M0 alone is about 60 runs.
- **Verifier reward hacking** by a candidate executor: closed by M1's hardened referee. Until M1, generated executor
  code is never run.
- **Evaluator drift or infrastructure faults:** pinned epochs and sentinels; corrections are new epochs.
- **Open questions:**
  - Where the root evaluator runs relative to the service (same uid, or a further isolated runner).
  - Whether the model broker can meter cached versus uncached tokens exactly.
  - How continuation context is bounded for P3.
