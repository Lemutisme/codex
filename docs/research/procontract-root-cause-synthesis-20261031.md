# Root-cause synthesis: useful work, failed work and misleading measurements

2026-10-31. This adds hex, zip-password-finder, astaxie/bat and dog to the previous
twenty inspected cases. The sample is purposeful, not a causal experiment. Frozen
code, submissions, scores, denominators and network configuration remain unchanged;
the user-directed consolidated repair is still deferred.

At approximately 03:14 UTC: 115 terminal jobs, 107 valid local scores, four active
solvers, 81 queued. Forty scores are at least 90%, twelve at least 98%, sixteen
below 50%, and two perfect. These are descriptive counts, not acceptance thresholds.

Artifacts in `/data/ProContract/procontract-synthesis-20261031/` include the cohort
snapshot, counts, four-case episodes-evidence.json, source-bound trace-evidence.json,
commentary index, measurement-conditions.json and grader-network-observation.json.
The canonical group counts are checked against the fixed eligible denominators.

## Correction: low scores do not identify the cause by themselves

Dog and astaxie/bat both have real protocol implementations and local-server
experiments. Dog encodes/parses DNS and implements UDP/TCP/TLS/HTTPS transport;
bat builds actual HTTP requests. Their recorded scores are 491/1300 = 37.77%
and 675/1091 = 61.87%, but part of the failure signal concerns the environment:

- Of dog's 809 eligible failures, 425 explicitly contain `Network is unreachable`
  at an assertion requiring returncode zero. The intended successful DNS-output
  checks have not been reached in those records.
- Fixed tests query public endpoints such as 8.8.8.8 and example.com. Bat tests
  also call public httpbin.org endpoints. Of bat's 416 failures, 351 contain a
  returncode-zero assertion; that count alone does not identify every cause.
- The shared campaign daemon starts with `--bridge=none --iptables=false
  --ip-masq=false`; its only networks are host and none.
- An isolated default-network probe in the dog grader image observes only loopback
  and an empty IPv4 route table. It runs no candidate/reference/test and makes no
  outbound request.
- The evaluator's `_new_env` applies network=none to non-testing environments.
  Test branches use testing=True and default daemon networking. The daemon-wide
  configuration therefore removes a capability expected by those public-service tests.

This establishes an environmental limitation and the first failing stage of the
425 explicit dog assertions. It does not establish a corrected score, explain
all failures, or establish Vals' exact evaluator conditions. Qualify evaluation
prerequisites before attributing score gaps only to strategy, model quality or
request budgets. Bat/dog cannot by themselves prove that rest was premature or
that no useful protocol model or experiment existed.

Preserve all raw scores under their actual conditions. Do not remove affected tests,
alter denominators or invent a network-adjusted score. Solver offline authorization
remains intact. Later repair must distinguish solver permissions from evaluation
needs and separately record any re-evaluation of the same frozen submissions.

## What the perfect cases add

**Hex:** the source models byte rows, formatting, prefixes, colors, array output
and function output. After the fixed internal comparisons already pass 88/88,
independent review finds an extreme-column counterexample. Nearby probes identify
a padding-width relation, rather than merely special-casing one huge number: when
missing-cell padding exceeds 65535 characters, the reference panics after writing
the row prefix. The source models that boundary and later streams large output.
The result is 823/823 after 2799 requests and approximately six hours. Its 15 full
verification choices and 23 successors are not proof that all those calls were needed.

**Zip-password-finder:** the source implements actual archive-entry handling,
generation/dictionary order, ZipCrypto/WinZip AES behavior and worker dispatch.
Review identifies that the workers option was initially parsed but unused; the
later source passes it into execution. Subsequent probes distinguish empty charset
behavior and absent versus present-but-empty RUST_BACKTRACE. Strategy rests after
225.64 minutes and 1572 requests; the result is 680/680. This is a successful early
rest in this case, not a general stopping rule.

These scores remain valid without internal Support. We have not externally graded
all intermediate snapshots or isolated each method's contribution to the final score.

## Mechanisms across good and bad trajectories

| Mechanism | Useful manifestation | Failure or limitation | Ownership |
|---|---|---|---|
| Representation expresses the needed behavior | Shellharden lexical structure; loop execution state; hex formatting rules; actual ZIP processing | Tinycc zero/NOP fallbacks, missing language/codec families, lookup fixes limited to enumerated inputs | Strategy chooses methods; solver writes task artifacts; domain algorithms do not enter kernel/harness |
| Observation reaches the intended path | Local HTTP/ICMP fixtures, actual PTY interaction, valid synthetic inputs | Missing tools/runtime, different self paths, invalid fixtures, public-service tests without routing | Harness supplies actual capabilities/conditions; strategy constructs and interprets observations |
| Evidence changes a useful decision or shared rule | Json-tui preserves queued input; focused parser and stream-state repairs | Broad reviews that cannot recover missing historical evidence, or treating failure-group labels as diagnoses | Strategy, supported by evidence access |
| Knowledge and work accumulate | Runnable regressions, generators, retained source and conditions | Eleven explicit rollback narratives contradicted by matching delivery/tool/context facts; product-only continuation loses observation assets | Harness retains/exposes facts; strategy selects and uses context |
| Responsibility survives an attempt ending | Oha captures interrupted work and selects a successor under its original grant | Running receipts never finalized; pending publication; draft/selector failure; cleanup preventing result persistence | Harness lifecycle; existing kernel responsibility semantics remain sufficient |
| Evaluation preserves intended meaning | Full eligible outcome vectors and qualified observation controls | Catalogue/discovery mismatch, lost plugins, unavailable dependencies, result-size rejection and missing grading connectivity | Evaluation adapter; no task-solving policy or kernel threshold |

These mechanisms can coexist in one run. A low score can accompany useful methods,
and a high score can accompany redundant review or a mechanical interruption.
Rest/verify/successor labels alone cannot tell us whether the choice was productive.

## Strength of the causal claims

Direct local mechanisms are established for cancellation/finalization, plugin-path
overwriting, catalogue inequality, result-size rejection, cleanup masking result
persistence, queued-input loss, contradictory commit narratives and missing grader
network capability. Source, retained observations and small controls support these.

Good representations, informative experiments and cumulative repairs are supported
method observations. Their individual contributions to whole-task scores are not
measured by a matched-compute experiment. Still unresolved are the score gain from
recovering an early stop, the best context rewrite, the benefit/cost of repeated
reviews and the scores under qualified evaluation conditions. Task complexity,
model capability, sampling variation and real resources remain relevant.

## General long-horizon synthesis

Useful work forms a chain: an applicable observation informs a meaningful choice;
the choice improves a deliverable or resolves an important uncertainty; the resulting
knowledge, assets and execution state remain available for subsequent work.
No fixed phase sequence follows. Work can involve implementation, information or
capability acquisition, experiments, coordination, delivery or waiting for an event.
User expectations guide priorities; actual hard limits constrain execution. No
hard deadline is required for responsibility, continuation or cancellation to exist.

Failures occur at different links: a representation cannot express the goal; an
observation is unavailable or misleading; an action cannot answer its intended
question; existing facts are misread or lost; or the substrate cannot continue or
persist an outcome. Adding a universal test count, retry count, review sequence
or countdown would not repair these distinct mechanisms.

For consolidated work, treat **execution continuity** and **measurement fidelity**
as independent prerequisites. Qualify lifecycle/original grants and actual
execution/collection/evaluation environments plus result processing. Then hold the
qualified harness fixed to compare focused strategy/context changes on fresh E2E
tasks, including connected and open-ended work. Mechanism controls diagnose local
behavior; they do not replace end-to-end quality evaluation. No new model run or
strategy/harness repair was performed in this synthesis pass.

See the [evolution register](procontract-evolution-register.md),
[positive episodes](procontract-positive-trajectories-20261028.md),
[state-claim audit](procontract-reflection-20261027.md),
[lifecycle defects](procontract-publication-lifecycle-20261026.md), and
[preparation causes](programbench-preparation-rootcause-20261028.md).
