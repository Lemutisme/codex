# Continuing the two unlaunched OFF tasks

The original three-task OFF study stopped on a provider-expired credential during
sox. Its terminal record and missing score remain unchanged. Explicit user consent
to continue authorizes only the original, unlaunched peco and silver_searcher slots:
two tasks, 36,000 allocated seconds, no RSI and no sox rerun.

`prepare --continue-from <parent-plan> --parent-sha256 <pin> --credential-preflight`
creates a new scope from the parent's exact source registry, binary and prompt.
It maps child indices to original unspent task keys. Both scopes use the **same
parent budget database and limits**; no copied/reset balance and no extra budget.
The old terminal's budget is its immutable stopping-time snapshot; subsequent
explicitly authorized claims appear in the live shared ledger with their child
plan and episode identities. The original supervisor is never restarted.

Expiry admission calls only the configured HTTPS provider origin's `/key/info`,
with redirects forbidden and response size bounded. A credential must be declared
non-expiring or cover the entire five-hour episode plus 300 seconds. Missing,
blocked, malformed or too-short metadata refuses inference before spending a task
slot. Receipts retain no key, key hash, raw body or provider error body. The exact
validated credential is supplied to the native process rather than rereading a
possibly changed file. Each new episode checks its current credential again.

This is **expiry-window admission**, not an implementation of indefinite token
renewal, hot rotation, or protection against revocation. A current long-lived key
allows this finite batch without changing the native model transport or binary.
Any new invalid/unknown execution still stops; no hidden replay or replacement.

The same fixed P, Luna/max, preinstalled dependency constraints, 4h native + 1h
grading, native OFF feature flag and evaluator are retained. Historical ON results
remain a cross-batch descriptive control, not a new score for the resume-fixed ON
binary. A combined report must include the original failed sox slot, not silently
average only successful remaining tasks.

The supervisor refreshes STATUS.md at each launch and termination, so a stopped
study does not keep advertising itself as running. Exact receipts remain the
authority. Native local fixture tests verify pinned credentials and absence of
contract/research workers without real model calls.
