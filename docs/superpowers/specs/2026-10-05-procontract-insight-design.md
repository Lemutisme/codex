# ProContract RSI: the experiment's observation

Status: approved direction (2026-10-05), implemented on branch `procontract-insight`.
Evidence: `~/run-artifacts/procontract-rsi-m0-20261001/trajectory-study/REPORT.md` (82 agents, two rounds,
every headline claim adversarially checked) and its notes.

## 1. What the trajectories showed

Campaign 1 ran three research steps. Each edited `executor.md`; the development means were .804, .799,
.802. The trajectory study found why nothing moved, and none of it was visible to the research agent:

- The research agent saw scores and 40 failure lines per run, never a trajectory. It spent 0.2% of the
  executor's tokens, lifted two of its three hypotheses from its own method text, and read sealed
  agreement as fidelity.
- Its edits restated default behaviour. Instructions that required an artifact (ledger, coverage table,
  regression files) were followed in 0 of ~112 runs. No experiment stated a behaviour that could be
  counted, so no run could show whether the change engaged.
- The largest failure mass lies in inputs the executor never sent to the reference (~44% of failing
  tests by key token; ~65% allowing near misses), identical to the test across v0–v2. The sealed suite
  shares the blind spot, so self-checks measure diligence, not coverage.
- Cost and much of what gets fixed are set by the repair turn, which is driven by one note. The note
  is clipped from the head at 2000 bytes after the sealed-family line was appended last, and it is lost
  at compaction.
- Identical policy spans 0.80–0.87 on one task. With 4 tasks × 1 run and a 0.02 gate, a null candidate
  is put forward 16–30% of the time and a true +0.02 about half the time.

## 2. Principle

A measurement yields a verdict and an observation. The verdict — the hidden outcome — lies beyond the
executor's reach and says *whether*. The observation — the trajectory — says *why*. Research must
explain verdicts by observations before it proposes, and every explanation is a claim:

- A mechanism read from trajectories is within-reach evidence: it ranks hypotheses and can veto a
  promotion. It certifies nothing.
- A mechanism is settled only by a prediction stated before the runs that test it (the next
  candidate's runs, then fresh confirmation tasks).
- Claims, their evidence and their standing persist. What the campaign has learned is a ledger of
  defeasible claims, read by every later step: within a task (its dossier) and across tasks (the
  mechanisms).

This is the reach principle applied to the institution's own understanding: Issue (an analysis states
a mechanism), Challenge (an independent checker tries to defeat it), Discharge or Defeat (a prediction
made from it meets the hidden outcome).

## 3. The loop

```
measure ─▶ observe ─▶ analyze ─▶ challenge ─▶ research ─▶ measure candidate ─▶ observe ─▶ analyze ─▶ challenge ─▶ decide ─▶ confirm
            (host)    (analyst.md) (challenger.md) (research.md)                                    settles the experiment
```

- **Observe** (host, mechanical, any task): every valid run is normalized into the archive.
- **Analyze** (a codex run following the research parent's `analyst.md`): explains outcomes from
  trajectories, settles the pending experiment, and updates the knowledge.
- **Challenge** (a separate codex run following `challenger.md`): tries to defeat each new or changed
  claim against the data and amends standing. It never adds mechanisms.
- **Research** (`research.md`): proposes one change from a mechanism in the knowledge, with a countable
  signature.
- **Decide**: a candidate is put forward only if its development delta clears the gate *and* the
  challenged verdict says its signature is present. A change that did not engage cannot be credited
  with a score that is noise.

An analysis runs whenever the set of valid runs has grown since the last one. Each step therefore
analyses once before research (the bootstrap, or nothing new) and once after its candidate is measured.

## 4. Observation (host; general)

For every valid development run, and every spent confirmation run (a spent task never certifies
again, so reading it costs nothing), the archive holds:

- `runs/<run>/summary.json`: the result without labels, plus a `trajectory` block: per turn, calls,
  oracle calls, tokens; compactions; notes (bytes, clipped or not).
- `runs/<run>/outcomes.json`: per item, passed and message (from the adapter).
- `runs/<run>/trajectory.md`: the executor thread in order, with bounded excerpts: calls, outputs,
  agent messages, ProContract notes, compaction summaries (the agent's own beliefs, since reasoning is
  encrypted), turn boundaries, elapsed time and tokens.
- `runs/<run>/events.jsonl`: the same thread as records, with full commands and the head and tail of
  each output.
- `runs/<run>/final/`: the final workspace's text files (code and documentation), bounded.
- `tasks/<task>/outcomes.md`: per task across all stored runs, the floor (fails everywhere), the
  always-passing items, the sensitive set, families, replicate spread among runs of one twin, and flips
  along each lineage edge.

Everything is computed from codex rollouts and the adapter's per-item outcomes; a task family supplies
only `outcomes(run_dir)`, `oracle_patterns()` and `task_tokens(task)`.

## 5. Analysis and challenge

Both are codex runs on the research image, with no network and no reference, in a workspace of
`archive/` (read-only) and `knowledge/` (editable). The analyst delivers `ANALYSIS.md` and, when an
experiment is pending, `verdict.json`:

```json
{"experiment": "<version12>", "signature": "present|partial|absent", "outcome": "...", "reading": "..."}
```

The challenger receives the analyst's delivery, checks it against the data, may amend `knowledge/`
and `verdict.json`, and delivers `CHALLENGE.md`. The challenged delivery becomes the campaign's
knowledge and verdict. If no delivery qualifies after one retry, the verdict is unknown, the candidate
stays in research, and the knowledge is unchanged.

Both methods live in the policy bundle beside `research.md`. A version that changes only `research.md`,
`analyst.md` or `challenger.md` does tasks exactly as its parent does (a twin) and is not measured.

## 6. Knowledge

```
knowledge/
  mechanisms.md   claims: statement, standing (open|supported|weakened|refuted), evidence pointers,
                  alternative explanation, signature, falsifier, experiments that tested it
  refuted.md      beliefs the evidence overturned, with pointers
  tasks/<task>.md per-task dossier: outcome structure, clusters and why they fail, what was tried
  proposals.md    levers outside the bundle (harness, measurement), for the principal
  tools/          analysis scripts worth reusing
```

UTF-8 text only, at most 512 KiB in total, so that it is distilled rather than dumped. A campaign may be
seeded with knowledge at `init`.

Boundary: dossiers carry hidden-test detail for the research view only. The files that shape how a
version does tasks (`executor.md`, `drafter.md`, `prober.md`, `reviewer.md`) must stay task-agnostic.
Qualification rejects a candidate whose changed task-shaping files name any task the campaign has
exposed (`task_tokens`). Confirmation on fresh tasks remains the certifier.

## 7. The experiment contract

`EXPERIMENT.md` sections: Mechanism (the knowledge entry and archive pointers it rests on),
Hypothesis, Change, Signature (the behaviour the change must produce, countable in a trajectory),
Prediction (which items or families move, direction, rough size), Falsifier, Risks. An addition to a
task-shaping file should replace or delete text it supersedes; this is method, not a mechanical rule.

## 8. Harness defects the study found (fixed in the binary)

- The repair note puts the sealed-family line first, so clipping removes public detail, not the one
  signal that measured breadth.
- The prober sees the reference's help in full up to a larger bound, with head and tail kept.
- The outstanding note survives compaction (if the compaction path allows it cleanly; otherwise a
  proposal).

Levers outside the bundle found later go to `knowledge/proposals.md`, and `status` lists them for the
principal.

## 9. Measurement (the principal's decision)

The 4 × 1 development stage is a screen. Section 3's signature requirement removes promotions of
changes that never engaged. It does not make small effects detectable. For campaign 2 the options are
more confirmation tasks per candidate (≥ 8, so a null passes rarely), or parent replicates on
development tasks. This is a budget decision for the principal.

## 10. Next, not now

- Score each turn-end snapshot (the ledger holds them) to measure what the repair turn buys.
- Fork-and-replay the repair turn from one snapshot with controlled notes.
- Replicates of the parent, so that the outcome matrix carries a measured noise floor for each task.

## 11. Validation (2026-10-05)

- Unit tests: 80 (trajectory, outcomes, attribution, host with fake runners), including verdict gating,
  knowledge carried between steps, challenger failure, the task-token boundary, resume after interruption, and
  spent versus unspent confirmation runs.
- Real smoke (`~/run-artifacts/procontract-rsi-m0-20261001/insight-smoke/`, set up by
  `insight-smoke-setup.py`): campaign 1's versions re-registered, 15 of their runs imported read-only, the
  seed knowledge, binary v5. One `analyze` ran a real analyst (10.7M tokens, 12 min) and a real challenger
  (13.0M tokens, 16 min); the analysis qualified with verdict `partial` for 0402adfe0e7c. The analyst
  traced each task's floor and flips to calls in the trajectories, found a mechanism the study had missed
  (pls `--collapse` needs a `Cargo.lock` fixture, which only the parent created), and judged the family
  inventory as engaged in language but never as an artifact. The challenger recomputed every number,
  weakened the parent-versus-child contrast with a counterexample, and kept `partial`. Knowledge grew from
  152K to 192K with a new mechanism (M16) and a reusable analysis script.

## 12. One run is a learning signal (implemented 2026-10-06)

RSI is test-time learning without parameter updates: the policy is the frozen model plus the context
(bundle, knowledge), and an update is an edit. Ordinary RL needs many rollouts because each yields one
scalar, a baseline needs a group, and nothing says why. One run carries more than that:

- **The outcome is a vector, and its noise is uneven.** Items every stored run failed (the floor)
  seldom pass by chance. Run-to-run noise lives in the sensitive set and moves in lumps.
- **The trajectory holds the agent's information over time.** For each failing cluster, the
  analyst asks whether the agent ever had the information that would have avoided it:
  `never_sent` (from an artifact, a convention, prior knowledge only, or unobservable),
  `never_compared`, `left_unfixed` or `too_shallow`. This assigns credit within one run, with no
  second run. It is the run's own counterfactual: hindsight relabelled by what the agent knew.
- **A prediction stated before the run turns its outcome into a signal.** The residual between a
  claim and evidence from beyond the claimant's reach is the signal. The claim is the baseline.

Mechanics:

- The analyst delivers `hindsight.json` (clusters: task, items, class, source, evidence, lesson).
  Every item must have failed in some run of its task and sit in one cluster only; a source, when
  given, is text. The challenger checks and may amend it. The archive README sums the latest table by class: where
  the failure mass sits and how much of it any behavior can reach.
- A candidate that changes a task-shaping file (executor.md, drafter.md, prober.md, reviewer.md) must
  deliver `prediction.json` (`{"rescue": {task: [item ids]}}`) over development tasks. Only items
  on the floor count; the rest are dropped. Items of one test family move together, so a family is
  one chance event: the unit chance is measured in and the prediction is settled in. Even rescuing
  every named family must be unlikely by chance alone (the product of the families' rates at most
  `prediction_alpha`), or no single run could decide it; with a few quiet families that takes two or
  three, with a noisy task more. Qualification rejects a prediction below that minimum.
- The host registers the prediction as a contract (`prediction.<id>`) before any of the candidate's
  runs, mechanism witness included, and releases it if the witness fails. The terms freeze the floor
  families and the chance rates. Both the prediction and its measurement resume after a host stops:
  a candidate whose prediction is outstanding is measured before a new step starts.
- After the development runs, the host settles the prediction mechanically, from the normalized
  observations. A frozen family is rescued when its task's run passes any of its items. With n
  frozen families, k rescued, and chance rate p_i for each (its task's), the prediction holds when
  P(at least k of n independent events with chances p_i) <= `prediction_alpha` (default 0.01). It is
  then discharged, with support from beyond the candidate's reach. Otherwise the candidate is
  defeated and the contract released. A frozen task without a valid run voids the settlement
  (recorded, never held), so a claim is never judged on a subset that infrastructure chose.
  `versions/<id>/settlement.json` records the result, and an analysis treats an experiment as
  pending only after it is settled.
- Chance holds each run of a task out in turn against the floor of the others and counts, per
  family with floor items, whether the held-out run passes any. Policy-driven flips count as chance
  there, so the rate errs high. Tasks differ in noise by an order of magnitude, so each task's rate
  is its own counts weighed against the pooled rate (the pool smoothed by a prior of one rescue in
  ten); the same ten pseudo-exposures weigh them. As runs accumulate, the floor purifies and the
  rates fall. The README shows the pooled and per-task rates.
- Put forward = signature present (challenged, within reach, so it can veto) ∧ prediction held
  (beyond reach) ∧ development delta ≥ `dev_min_delta` (no broad harm) ∧ confirmation budget.

The same law holds at every timescale. Within a call, the signal is the environment's answer to an
expectation. Within a task, it is the oracle and the verifier's note. Across runs of a task, it is
the hidden outcome. Across tasks, it is fresh confirmation. For the learner, it is its successors.
At each level only evidence from beyond that level's reach certifies. Within-reach agreement is
self-reward: it ranks and vetoes, and taken as reward it invites hacking (one executor hard-coded the
verifier's path). This is where RSI differs from TTRL, whose pseudo-reward is majority agreement.

## 13. Proposed, not implemented: claims at handoff

In deployment there are no hidden tests, and the principal's settlement (accept, correct, follow
up) is sparse. A sparse signal can teach only if the handoff states claims with their reach: what
was checked, against what evidence, and what was not reached. Then a correction lands on a claim.
No handoff in about 87 runs disclosed a gap. The study shows prose does not elicit this, so the
harness must own the structure: the executor's handoff carries claims, and settlement attaches to
them. This changes ProContract's handoff protocol and needs its own design.

A further hypothesis, untested: a belief slot that survives compaction may let the executor keep
what it learned within a task (the repair-note fix of §8 is one instance). Its signature would be
fewer re-explorations after compaction.
