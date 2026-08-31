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

The v5 and v6 ProgramBench runs below are **development evidence**. Their
ProgramBench runner commit was not recorded in a durable run manifest. That
defect cannot be repaired retroactively by copying result files now.

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
