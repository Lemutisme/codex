# Preparation failures: catalogue semantics and plugin loading

2026-10-28. Root-cause analysis under the user's instruction to record first and
repair together later. No frozen code, test archive, denominator or solver changed.
Both failures occur before solver admission.

Evidence is retained under
`/data/ProContract/procontract-preparation-rootcause-20261028/`:
`evidence.json`, `source-identities.json` and `plugin-import-reproduction.json`.
The inspected readiness, scope and runtime adapter sources have exactly the same
SHA-256 as the frozen campaign copies.

## Jsonschema: discovery was incorrectly equated with the fixed catalogue

Task `stranger6667__jsonschema.d52e881`, branch `0fcad6a13514`:

- The pinned archive's pytest collection produces 1946 names.
- The pinned tests.json lists 1101 names for that branch.
- The catalogue set is exactly the first 1101 names in observed collection order.
- The last catalogue entry is explicitly ignored as `gold_fail`.
- The archive's eval/run.sh invokes pytest with `-x`, which stops a test run at
  its first failure; collection-only mode does not execute tests or stop there.
- There are two explicit ignored names. After excluding them, the readiness
  comparison sees 1944 observed names versus 1099 expected names: missing 0,
  extra 845. Every extra name belongs to the conformance parametrization.

This is consistent with a catalogue recorded through the first failing test under
the supplied fail-fast runner. The original historical run is not rerun here, so
that history is an inference from the exact prefix, known gold failure and script.
The immediate failure is fully determined: readiness compares all discoverable
nonignored names to the fixed catalogue and rejects the 845-name difference.

Relevant source: `scripts/procontract_evaluator_readiness.py::_evaluate_branch`,
especially the construction of actual/expected and the equality check. The scope
plugin limits discovery to files in the official archive and respects explicit
ignored modules; it does not make archive discovery identical to the published
test catalogue. The two sets are different in this real branch.

The design error is treating discoverable tests, historically executed tests and
the declared scoring scope as the same thing. A correct adapter must model their
relationship explicitly. Preserve the pinned eligible denominator, missing-required
test detection, identity/duplicate checks and actual execution semantics. Decide
scope handling against that protocol rather than silently enlarging the denominator,
discarding assertions or merely deleting the mismatch check. Candidate-dependent
fail-fast behavior also needs qualification during the consolidated repair.

## I3-style: injected capability depended on an overwritten environment variable

Task `altdesktop__i3-style.f93821b`, archive branch `790105b80ebd`:

The adapter writes its collection plugin under `/tmp/procontract-readiness` and
exports that directory in PYTHONPATH. It also adds the plugin name to PYTEST_PLUGINS.
Scope and runtime observers use the same temporary-directory/environment pattern.
The official eval/run.sh then invokes:

```sh
PYTHONPATH=. pytest --junitxml=eval/results.xml --timeout=5 --timeout-method=thread -n auto -v
```

This replaces the inherited import path for pytest while retaining the injected
PYTEST_PLUGINS list. Pytest consequently tries to load `_pc_collection_probe` but
cannot find its module. The script wraps the invocation in `set +e` and ends with
`exit 0`, so the outer shell return code is zero even though pytest failed to start.
No scope receipt is written; its later copy failure is a consequence, not the
initial cause.

A minimal host-only reproduction used one temporary test and a temporary plugin:
with the inherited plugin path, collection returned zero; with PYTHONPATH reset
to '.', it returned one and the same missing-plugin error. This confirms the import
path mechanism. It is not a benchmark rerun or qualification of a repaired adapter.

The design error is relying on ambient environment inheritance to provide a host
capability across a script boundary that legitimately controls its own environment.
Plugin bootstrap must remain valid for the actual interpreter/runner being used,
without task-name exceptions or changing candidate source. Qualification must
include script-side environment reassignment, child interpreters and the existing
scope/runtime observers. Keep the receipt check: it detected the failed capability
despite the shell's successful exit code.

## Relationship to the other recorded failures

These are evaluation-adapter issues. The publication problem is separately an
operation-lifecycle defect: cancellation/cleanup results are not always finalized
durably, and unresolved state prevents a subsequent decision. DuckDB is a large
artifact-processing boundary: raw evaluator results exist but are not processed
past fixed parser/hash limits. Their fixes are different.

The shared architectural concern is an incomplete interface between layers:
execution/discovery details are used as substitutes for explicit scope, capability
or lifecycle facts. A local method or transport failure can then end preparation,
continuation or scoring even while the underlying responsibility or artifact remains.

Harness should preserve the requested operation's semantics, expose concrete
outcomes and reconcile execution. Strategy should choose useful next work using
those facts. Kernel should retain domain-independent responsibility and authorized
transitions; it should not gain pytest exceptions, output-size verdicts or retry
workflow rules. No low task score is explained away by this diagnosis, and no
perfect score is downgraded by an unrelated internal verification state.
