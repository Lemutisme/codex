# ProContract evidence

This document records empirical evidence and its limitations. It is not the
ProContract constitution and does not define Kernel semantics.

## Evidence custody rule

An empirical claim is citable only when the repository or an immutable
external store retains:

- source commit and dirty-state or binary hash;
- exact model, variant, reasoning effort, and service configuration;
- Contract specification and hash;
- execution policy and hash;
- candidate subject and capture-policy identity;
- execution and evaluation environment identities;
- evaluator code/image identity;
- task/split identities and prior exposure;
- budgets, seeds, replicate count, and selection rule;
- raw run records, failures, warnings, and incomplete outcomes;
- ledger frontier, handoff, attestation/challenge, and quiet result.

Missing coordinates do not make an observation useless. They permanently limit
which causal or publication claim it can support.

## Evidence grades

- **Structural:** scripted traces or model checking over the transition
  protocol.
- **Boundary:** integration tests across storage, Session, tools, replay, and
  Principal APIs.
- **Development:** model/task experiments with incomplete coordinates or prior
  exposure.
- **Confirmation:** preregistered, disjoint, fully coordinated evaluation
  observed once.

The ProgramBench runs below are **development evidence**. The historical v5
and v6 runner commit was not recorded in a durable run manifest. That defect
cannot be repaired retroactively by copying result files now. Later runs have
stronger coordinates but still use one candidate per cell.

## Native execution-policy evidence

### v5 three-instance A/B

The run used GPT-5.6 Luna at reasoning effort max, one candidate per arm and
instance, on Amber, Loop, and fd during 2026-08-29--30 UTC. Policy-on and
policy-off shared the native binary, task images, Contract terms, budgets,
reference interface, replay, and official active tests.

| Arm | Amber | Loop | fd | Macro |
| --- | ---: | ---: | ---: | ---: |
| execution policy on | 78.2301% | 95.6338% | 80.6478% | 84.8372% |
| execution policy off | 69.5575% | 83.2394% | 77.8138% | 76.8702% |

Policy-on reduced turns by 12.89% and actions by 13.15%, while increasing total
model tokens by 15.42% and wall time by 5.93%. The three tasks responded
differently. This supports task-conditioned policy selection and a policy-free
fallback, not a universal policy.

The original temporary v5 RESULT artifact no longer exists. The surviving
source is the local experiment ledger
`scripts/PROCONTRACT_EXPERIMENTS.md`, which was untracked when this evidence
document was written. These numbers must not be upgraded to confirmation
evidence.

### v7 matched ordinary-Codex baseline

A preregistered post-hoc baseline then completed the missing half of the v5
factorial on the same three instances. It reused the exact v5 binary, Luna Max
model, agent image, task images, user brief, and official tests. ProContract was
disabled. `ordinary off` ran normal Codex; `ordinary same policy` additionally
received the exact v5 execution policy as developer instructions. Existing v5
ProContract candidates were not rerun or modified.

| Instance | Ordinary off | Ordinary same policy | ProContract off | ProContract on | Public task best |
| --- | ---: | ---: | ---: | ---: | ---: |
| Amber | 72.3894% | 85.1327%* | 69.5575% | 78.2301% | 94.8673% |
| Loop | 92.6761% | 84.3662% | 83.2394% | 95.6338% | 99.2958% |
| fd | 79.1903% | 78.7854% | 77.8138% | 80.6478% | 99.3522% |
| Macro | **81.4186%** | **82.7615%*** | **76.8702%** | **84.8372%** | **97.8384%** |

`*` Amber ordinary-policy exhausted the same interactive branch twice without
producing JUnit. Its 481/565 active score includes that
`results_read_failed`; the other five ordinary evaluations have no branch,
system, or warning condition.

The fixed full product beat ordinary Codex without policy on all three tasks:
+5.8407, +2.9577, and +1.4575 points, or +3.4186 macro. That contrast does not
identify a Kernel effect. Holding policy absent, the ProContract envelope lost
4.5483 points macro and lost every task. Holding the execution policy present,
ProContract gained 2.0758 points macro but lost Amber and won Loop/fd. The four
cells therefore indicate an envelope-policy interaction, not monotone value
from either component alone.

Ordinary policy-on consumed 126.710M cumulative model tokens versus 78.577M
off (+61.3%) for only +1.3429 points macro. Its effect reversed by task. The
ordinary trajectories also spent 42--168 actions after first creating their
validation artifact; some added real coverage, while Amber still missed the
interactive child-cleanup invariant that caused evaluator failure.

The public-task-best column is the per-task maximum over published
[ProgramBench](https://programbench.com) runs retrieved on 2026-08-31 from the
site snapshot labeled updated 2026-08-16. It is an external scale reference,
not a matched baseline. Native ProContract-on remains 13.0012 points below that
three-task upper envelope. The other five previously reported native instances
are omitted because their exact historical binaries lack a matched ordinary
arm; mixing current-binary baselines into those rows would not repair that gap.

This remains development evidence: there is one candidate per cell, the
ordinary baselines were generated after v5 outcomes were known, generation was
concurrent, and the historical v5 raw result bundle is absent. The frozen v7
report is:

~~~text
/tmp/procontract-native-ordinary-v7/RESULT.md
sha256 77f308a16e748faf3d1dd3d36161493f2a9c56d8a8bc4b36de84094e2eb8070c
~~~

### v6 evidence-convergence falsification

The v6 run reused the three training instances after v5 hidden outcomes were
known. It added Rust 1.92 and a 332-crate offline registry to the agent image.
Policy v3 requested capability inventory, deterministic differential corpora,
seeded fuzz, residual repair, and fresh-copy replay.

| Arm | Amber | Loop | fd | Macro |
| --- | ---: | ---: | ---: | ---: |
| v3 policy on | 2.4779% | 96.1972% | 81.0526% | 59.9092% |
| parity policy off | 70.7965% | 67.3239% | 78.7854% | 72.3019% |
| prior v2 policy on | 78.2301% | 95.6338% | 80.6478% | 84.8372% |

Excluding Amber, v3 gained 0.4841 percentage points over prior v2 while using
51.6% more actions and 61.1% more model tokens. Across all three tasks, v3
policy-on lost 12.3927 points to its parity off arm.

All six executor trajectories used one semantic attempt, froze a subject, and
passed configured native replay. Every incomplete or non-perfect official
result was later submitted as a sealed challenge. The persisted ledgers moved
to escalated, removed current handoff support, advanced to frontier four, and
remained non-quiet.

The corrected local report was:

~~~text
/tmp/procontract-native-rpc-v6/RESULT.md
sha256 e7a9bde717cbf3e74f12ead3e44d9c85700223210f0ba8c9a0a88346da237dd7
~~~

That temporary path is not durable custody. The hash permits local
cross-checking only while the artifact survives.

### v8 adaptive leaderboard-policy seed

After inspecting only the generic structure of public leaderboard trajectories,
a preregistered Luna Max A/B tested a 1290-byte Fast/Deep policy seed on three
instances absent from the local experiment ledger. Both arms used the same
dirty-source binary, parity image, Contract, six-hour ceiling, replay, and
official evaluator. The native binding returned the same preregistered
domain-separated policy hash on all treatment arms and null on controls.

| Instance | Policy off | Adaptive v4 | Delta | Public task best |
| --- | ---: | ---: | ---: | ---: |
| zip-password-finder | 85.8824% | 99.1176% | +13.2353pp | 100.0000% |
| cheat | 62.2896% | 66.6667% | +4.3771pp | 86.1953% |
| thokr | 89.4382% | 92.5843% | +3.1461pp | 99.5455% |
| Macro | **79.2034%** | **86.1229%** | **+6.9195pp** | **95.2469%** |

All six trajectories reached verification in one semantic attempt, passed
native replay, and evaluated without errors or warnings. Every treatment
handoff selected `lane=deep`, named a measured trigger, and retained material
uncertainties. V4 used 644 versus 596 actions (1.081x) but 86.349M versus
53.326M cumulative model tokens (1.619x).

The preregistered promotion gate required both actions and tokens to remain at
most 1.5x control. V4 therefore **fails promotion** despite improving every task
and passing every other gate. It remains a strong Deep seed, not a canonical
default. This refusal is the first policy-RSI decision supported by a stable
native policy identity and a frozen multi-objective rule; canonical policy
adoption itself remains future work.

The executable gate returned `admit=false` with only `tokens` failed and bound
that decision as
`b8add9563b4d41fa56f1c8e1cad59a8f168b50db0bdf403af5eab79732fb7b14`.

Residuals discriminate the next mechanism. Zip failures fell from 96 to 6.
Thokr improved TUI basics but retained timing, graph, tiny-terminal, language,
and scoring differences. Cheat improved only 13 tests; search, update,
configuration, installer, and completion semantics dominate. A next generation
should default Fast, admit Deep only from trusted residual/risk evidence, and
bound context growth rather than merely action count. Those mechanisms belong
in task/policy adapters, not the settlement Kernel.

~~~text
/tmp/procontract-native-policy-v4-20260901/RESULT.md
sha256 ae92cf99beb9e60ffac850edee4bcc9881aa383316aabea38cebdca1cfffd954
~~~

## Amber environment-coordinate falsifier

The v6 Amber candidate reported:

- one semantic attempt;
- exact subject capture under the current capture policy;
- native compile and replay success;
- a 48-case self-contained differential corpus with zero reported residuals.

The same executable then failed in evaluation:

| Coordinate | Replay | Evaluation |
| --- | --- | --- |
| Python | 3.12.3 | 3.10.12 |
| Executable | same hash | same hash |
| Result | configured replay passed | syntax error at amber.py line 726 |

The official score was 2.4779%. One branch exhausted the 3600-second evaluator
limit twice without producing JUnit output. An isolated diagnostic extended
the branch limit to 10800 seconds and again produced no result.

The long tail was initially attributed to candidate regex behavior. A bounded
follow-up falsified that explanation:

- without pytest failure reruns, the branch finished in 40.75 seconds;
- it reported 398 failures, 31 passes, and five skips;
- the TTY wrapper masked the syntax-error child as exit zero;
- large unchanged-file assertions entered expensive pytest diff/report paths;
- official failure reruns amplified two lanes until timeout.

The correct causal chain is:

~~~text
environment mismatch
  -> artifact cannot start
  -> evaluator failure amplification
  -> missing finite report
~~~

This case supports:

- responsibility remained conserved: the Contract never became quiet and a
  sealed challenge moved it to escalated;
- exact subject hashing prevented candidate substitution;
- local replay did not establish target-runtime compatibility.

It refutes:

- capability availability implies capability adoption;
- self-authored residual zero establishes evaluator adequacy;
- additional evaluator time repairs an incompatible artifact;
- a passed replay is meaningful without its environment coordinate.

## Native executor-envelope and policy falsification

A same-model, same-task, same-image, same-evaluator Luna Max campaign separated
the native Codex executor envelope from the execution-policy text.

The retained Rust change gives Contract executors a dedicated bounded base
context while preserving project instructions, authority, and the externally
bound policy. First provider input fell from 5,017 tokens to 1,666-1,840 tokens.
The stable envelope also tells executors to use fresh scratch paths, batch
bounded independent observations, and choose implementation primitives faithful
to runtime semantics. None of those terms enter `ContractSpec` or `specHash`.

The exact 882-byte policy used by the strongest maintained OpenCode profile was
then run natively in Codex:

| Instance | Lean Codex + exact v2 | OpenCode + exact v2 |
| --- | ---: | ---: |
| zip-password-finder | 99.4118% | 99.5588% |
| cheat | 81.4815% | 85.5219% |
| thokr | 92.3596% | 95.7303% |
| Macro | 91.0843% | 93.6037% |

Policy bytes therefore do not explain the remaining 2.5194-point gap. Codex
used 31% more provider turns, 19% more actions, and about 50% more token traffic.
Its safe command envelope rejected destructive probe cleanup, it stayed near one
tool per provider turn, and it selected Python rather than C for the TTY/timing
task. The stable executor instructions now expose the safe scratch-path and
batching semantics instead of weakening command safety.

Two richer policies were rejected. V5's model-authored coverage ledger scored
91.2304% and conflated observing the reference with matching the candidate. V6
separated those states and demonstrated challenge-driven correction with exact
rejected-subject custody, but scored 89.3052%; one final frontier remained
schema-invalid. A syntactically valid evidence path established identity, not
semantic coverage: v6 cheat claimed a conformant frontier while failing 68
official tests.

The empirical boundary is therefore:

~~~text
lean executor envelope + replaceable broad-to-targeted policy = retained
model-authored coverage ontology as completion proof             = rejected
independent counterexample -> challenge -> fresh attempt          = retained
~~~

Raw reports:

~~~text
/tmp/procontract-native-policy-v5-match-20260902/RESULT.md
sha256 f72d477e4adb255558af7d21745ca92149b14f648bfcaef705560a0947b85012

/tmp/procontract-native-policy-v6-20260902/RESULT.md
sha256 59bbe177e24d1c7d18e3840fd8354c3728e97cbde612f45cc1da617c165c8066

/tmp/procontract-native-policy-v2-lean-20260902/RESULT.md
sha256 8e6e7b7b4303fe37e5a5c3f90dd4724f41b1bffc9970c51c750f3fad3c0710fd
~~~

### Native bounded-observation falsification

A follow-up added an opt-in `contract_probe_batch` edge capability without
changing Kernel state, `ContractSpec`, `specHash`, or the ledger. It runs up to
twelve local non-interactive candidate/reference cases as one Contract action,
binds the report to the candidate, semantic attempt, environment, and policy,
and keeps full bounded bytes outside model context.

On zip-password-finder, the final retained-output implementation used Luna Max
for one preregistered attempt. Seven reports compressed 110 executions into
seven actions with no timeout or output-limit event. It reached replay-backed
verification in 124 turns, 122 actions, 24.17 minutes, and 7.199M cumulative
model tokens. This was materially cheaper than the earlier probe trajectory,
but the exact frozen candidate scored only 649/680 = **95.4412%**, below lean
Codex v2's 676/680 and OpenCode v2's 677/680.

The trajectory exposed a semantic error in the first tool vocabulary. It
called exact bytes `matched` even though reference and candidate necessarily
had different executable paths and `argv[0]`. The worker erased that legitimate
coordinate difference by hard-coding the help program name to `reference`;
official deployment then failed executable-name and help tests. Its final
selected 10/10 exact cases also coexisted with 31 active failures, principally
help/parser variants and `maxPasswordLen=0` semantics.

Therefore:

~~~text
byte equality at one observation coordinate != semantic conformance
semantic conformance on selected cases         != coverage or settlement
~~~

The official evaluation was submitted as a sealed challenge. The exact
Contract moved from verification to escalated, lost current handoff support,
advanced to frontier four, and remained non-quiet. Commit `422cfd380` responds
by renaming the report relation to `byteEqual`/`difference`, exposing candidate
hash and trusted execution cost, and warning the executor not to erase
coordinate-bound differences. That semantic correction is structurally tested
but has no disjoint performance result yet. The tool remains opt-in.

~~~text
/tmp/procontract-native-probe-zip-v3-20260902/RESULT.md
sha256 3e77fbde0f191ecc6ea9509e13999e520d3cf2b23675252b48dd55be8592139a
~~~

### Fresh Jot frontier and rejected action checkpoint

A fresh Jot Luna Max A/B tested the corrected observation vocabulary, durable
request/candidate frontier, authority sandbox, and general action telemetry.
Both arms used the same source binary, image, six-hour Contract, official
evaluator, and exact v2 policy base. The treatment alone received the bounded
probe capability and a 642-byte frontier policy suffix.

| Arm | Official score | Turns | Actions | Token traffic | Wall |
| --- | ---: | ---: | ---: | ---: | ---: |
| exact v2 | 715/752 = 95.0798% | 222 | 219 | 28.754M | 43.83m |
| corrected native frontier | **730/752 = 97.0745%** | **164** | **161** | **19.347M** | **28.50m** |

The frontier gained 1.9947 percentage points while using 26.5% fewer actions,
32.7% less token traffic, and 35.0% less wall time. Both candidates reached
native replay-backed verification in one semantic attempt with zero evaluator
errors or warnings. Their non-perfect evaluator files were then submitted as
sealed challenges; both handoffs were withdrawn, both duties became escalated,
and both remained non-quiet.

Four native reports compressed 48 cases into four Contract actions and retained
46 syntactic request coordinates. The largest functional gain was all thirteen
exact subcommand-help fixtures. The remaining 20 failures concentrate in
stateful multi-vault behavior, TOML quoting/malformed input, special names, and
clap flag clusters. This supports the stateless observation primitive while
locating the next boundary in reusable stateful differential evidence and
fidelity-bearing implementation primitives.

The same run falsified exact-payload repetition as a sufficient convergence
signal. Frontier's 161 action payloads were all distinct. Baseline had 217
distinct payloads among 219 actions; only its second and third exact
`compile.sh; validate.sh` requests triggered reminders, after most exploration
cost had already occurred. Inferring semantic command equivalence in the host
would be unsound.

A candidate response projected cumulative action, tool, outcome, and exact
request counts at two geometric boundaries per octave (`32, 48, 64, 96, ...`).
It explicitly denied that count, novelty, or candidate age established semantic
progress and asked the model to bind further observation to a hypothesis or
documented surface. This mechanism was structurally bounded and remained
outside Contract state, but performance experiments rejected it.

| Causal A/B | Old binary | Checkpoint binary | Decision |
| --- | ---: | ---: | --- |
| Jot development retest | 29/752 = 3.8564% | 720/752 = 95.7447% | reject: actions 1.514x, tokens 2.068x; prior frontier was 730/752 at lower cost |
| disjoint tuc | **1177/1196 = 98.4114%** | 1142/1196 = 95.4849% | reject: -2.9264pp despite actions 0.779x and tokens 0.903x |

The Jot control imported `tomllib`, available in the Python 3.12 inference and
replay environment but absent from the Python 3.10 evaluator. Almost every
target invocation failed at import. The checkpoint treatment happened to write
a self-contained parser, but no checkpoint proved target compatibility. On
tuc, every checkpoint follow-up was locally justified and one compaction
preserved a 111-case differential summary, yet treatment fixed three control
failures and introduced 38. The control's later work closed option conflicts,
malformed-regex handling, formatted bounds, and empty-record cases.

The checkpoint was therefore removed. Exact repeated/long action telemetry
remains because it reports direct cost without claiming which semantic work is
valuable. The stronger result is:

~~~text
mechanical action novelty != semantic progress
named local hypothesis     != expected hidden residual mass
current replay passed      != target-runtime compatibility
~~~

Target-environment preflight belongs in the evidence adapter. Reusable stateful
differential observations and their surviving passing set belong in mutable
policy/evidence state. Neither concern justifies adding convergence or stopping
authority to the settlement Kernel.

The public Jot leader retrieved on 2026-09-03 scored 750/752 with about 398
shell actions. Its trajectory delayed implementation until after Rust, TOML,
path, and CLI investigation, then used a native Rust candidate, reusable
state-resetting differential suites, and seeded fuzzing. The contrast rules out
turning the checkpoint into an unconditional early-candidate or early-stop
policy: discriminating depth may be valuable even when raw action age is not.

~~~text
/tmp/procontract-action-jot-20260903/RESULT.md
sha256 285780104074ff9bfda52694eeb998a86c6e1493f5594567ea8be64e21dd0156

/tmp/procontract-action-checkpoint-ab-20260903/RESULT.md
sha256 725bae89d01cc562fe58d570297532c2ac0622aaff39cc3c4333ddb92a088942

/tmp/procontract-action-checkpoint-tuc-20260903/RESULT.md
sha256 5c114cc98b47649a33e972f05ad75920fd592d2fa2a33291eb6eb794bd891c25

/tmp/procontract-target-preflight-20260903/RESULT.md
sha256 0fb21d66187ea578bad6c7bd1e5765c26e25c0b8ca41c319a112bd67ca6f2c97
~~~

## Structural evidence

Current Rust tests cover representative reducer and adapter paths. The complete
fault matrix has not been measured, and FalseQuietRate,
InvalidSettlementRate, DutyLossRate, and ChallengeClosureRecall have not been
reported over exhaustive traces.

Native replay treats an acknowledged check timeout as content-addressed failed
evidence and restores the exact duty to dormant instead of classifying the
verifier as unavailable. The report records duration and is persisted only
after the process API acknowledges timeout termination. This does not establish
descendant cleanup, resource accounting, or target-environment equivalence, and
it does not make model-authored probe journals trusted observations.

Required structural evaluation includes:

- duplicate, delayed, and stale commands;
- self-discharge attempts;
- subject, revision, evidence, and verifier substitution;
- requirement depth and concurrent challenges;
- crash between projection/event operations;
- lease expiry and process recovery;
- sealed disclosure;
- quiet before and after challenge.

## Empirical estimands

Three effects must remain separate:

~~~text
ordinary execution - no execution
  = value of another model invocation

ProContract execution - matched ordinary execution
  = utility and cost of the institutional envelope

independently attested result - executor handoff
  = value of the adjudication boundary
~~~

Matched arms freeze model, prompt information, tools, environment, parent
artifact, maximum budget, reference interface, packaging, evaluator, and prior
exposure. Actual token and action use may remain outcomes under equal ceilings.

Report score, solved rate, latency, tokens, actions, attempts, challenges,
evaluator errors, incomplete results, and final ledger frontier.

## Promotion gate for future evidence

No future policy result becomes confirmation evidence unless:

1. its manifest and code coordinates are frozen before inference;
2. candidate generation cannot access confirmation or OOD results;
3. every baseline/candidate task and replicate pair is present;
4. environment and evaluator digests are bound;
5. missing, timed-out, or manually repaired records fail closed;
6. selection-adjusted utility and cost thresholds are preregistered;
7. raw evidence has durable custody independent of the candidate workspace.
