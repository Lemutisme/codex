# Grader resources and official test scope

The full-corpus rollout exposed preparation failures before any solver request:
some official branches needed Python packages or a Go toolchain/module cache that
the isolated grader had not prepared. Pytest's unrestricted discovery also mixed
a submission's own tests into one scored corpus. These are assessment-adapter
failures, not kernel judgments about the quality of the submitted work.

The adapter now derives collection paths from the pinned official archive and
combines the catalogue with its exact exclusions. An ignored module diagnostic
does not exclude separately eligible descendants. A branch with no eligible tests
does not require its unrelated setup. The collector preserves the action allowance
supplied by its caller, within the existing overall preparation deadline.

Grader resources remain explicit inputs: exact Python distributions, immutable
wheels, Go 1.24.5 and its required module cache. The experiment profile resolves
static grader imports against that frozen catalogue before inference. It installs
these resources after compiling/hashing the candidate, retains the compiled hash,
and keeps the resources outside solver mounts. No test assertion, official fixture,
eligible denominator, solver policy or kernel transition is changed.

Validation is recorded at
`/data/ProContract/programbench-evaluator-repair-20261025/REPAIR_REPORT.md`:
29 unit/real-pytest controls, all 12 previously failed preparations plus muffet
passing native collection, and a valid 286/292 score for muffet's unchanged frozen
submission. Original failures and results remain intact.

The user subsequently chose a new uniform full cohort with one six-hour allocation
and no model-request ceiling. It uses fresh independent workspaces and the same
solver/strategy version. Old request-limited attempts are historical observations;
they are not resumed or merged into the new resource regime.
