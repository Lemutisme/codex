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
