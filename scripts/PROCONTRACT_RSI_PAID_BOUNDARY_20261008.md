# Paid-launch recovery and the single-model execution profile

This increment follows the bounded recursive-engine patch series. It does not claim a
new model result, research-method benefit or completed live RSI campaign.

## Paid learning invocations

`Host.run_agent` now records a persistent, exclusive launch claim after successful
preparation and before invoking the paid runner. It binds the parent, role, model,
effort, H identity, binary, runner command, image, deadline, prompt, captured input
workspace and prepared manifest. The claim is flushed; POSIX also syncs its directory.
The trusted study launcher must still pin the actual Host/runner source, not just paths.

Recovery distinguishes:

- No launch claim, with a matching Host prepare-only record: preparation may retry.
- Claim plus a trustworthy terminal receipt: validate and reuse that exact attempt.
- Claim with no trustworthy terminal receipt or recorded exit: **unreconciled**.
  Preserve the claim and workspace; do not relaunch, certify leftover documents, assume
  the process is stopped or count unknown costs as zero.
- A late terminal receipt from the original child can reconcile the same claim.
- A recorded nonzero runner exit remains a failed attempt, even if documents exist.
- A nonempty legacy run directory without a claim or trusted prepare-only record is
  also unreconciled, not permission to delete and pay again.

This is fail-closed, at-most-once launch, not an exactly-once distributed protocol.
A crash after reserving a claim but before spawning can leave a spent/unknown attempt.
No state file alone proves a process is still running; external process or provider
evidence is required where terminal receipts cannot resolve the ambiguity.

## Task-attempt allowance

New campaigns default to `--task-attempts 1`. The allowance is persisted under
`budgets.task_attempts`; Host rejects malformed values and never exceeds that allowance
across restarts. Older campaigns without this field retain their previous two-attempt
semantics, rather than silently rewriting historical terms. Explicit two-attempt
experiments remain possible, but they are not the planned five-hour Luna profile.

The unit is `purpose × version × task`. Candidate and incumbent each receive their own
declared task allowance during paired confirmation. Retries of an evaluator against
the same frozen submission are separate; they do not authorize another model execution.
Descriptive comparisons reject mismatched normalized attempt policies.

With one attempt and `task_deadline_secs=18000`, there is only one five-hour inference
allocation per unit. This does not include research, preparation, grading or shutdown
tail time, and is not a whole-study compute cap or hard real-time termination guarantee.

## Fixed-model profile

The benchmark runner disables ordinary multi-agent V1/V2 and sets
`agents.enabled=false`. The latter is essential: model-catalog selection can otherwise
take precedence over feature flags. Internal ProContract workers retain their separately
pinned model/effort settings. This profile removes the ordinary child-agent model/effort
override surface; it is not a claim about opaque provider-side model routing.

All planned roles remain `gpt-5.6-luna / max`. This is a new pinned execution profile;
do not silently resume an old live study with changed Host scripts or options.

The old Luna experiment was also audited separately: its preserved 44 rollouts contain
75 `turn_context` records, all declaring Luna/max, with no ordinary collaboration
subagent source recorded. The existence of an override risk is not evidence that the
old experiment actually used a stronger model. Context counts are not request or invoice
counts.

## Adoption freshness

Before the first atomic incumbent publication, `adopt` rechecks the supported candidate's
role and H bytes. Source drift after confirmation cannot publish an invalid candidate.
Replaying an already settled adoption still returns idempotently, even if its source
artifacts were later cleaned up; historical decisions are not rewritten. Registered role
and experiment text is frozen as exact UTF-8 bytes, without platform newline conversion.

## Verification and remaining live gates

The pinned native Codex binary successfully initialized, started a Luna/max-configured
thread, and recognized `turn/steer`, rejecting it because no turn was active. The probe
did not issue `turn/start`; its provider had no real key and pointed to a non-serving
loopback endpoint. This verifies native protocol/config acceptance, **not model access,
active-turn steering or a captured outgoing model-tool surface**. A local HTTP mock was
not started because loopback listener creation is denied in this environment.

Docker API access remains denied and the intended worktree/Git metadata remain read-only.
No new benchmark inference or commit is claimed. The following still require work:

1. A fresh-task canonical registry: the previous adapter is limited to the three already
   exposed tasks. Do not switch to the default evaluator merely to avoid that restriction,
   because its skipped-case denominator differs.
2. A pinned Luna-only live launcher, with a complete source/environment manifest and
   explicit learning/confirmation budgets.
3. Explicit post-adoption production assignment. The existing dual-head stream can have
   exploration V2 queued when V1 is adopted; incumbent publication alone does not prove
   that the next task and researcher used the adopted V1.
4. Authenticated live execution, fresh confirmation, and actual adopted-version continuation.
   Offline fixtures or transport probes cannot establish their completion or RSI benefit.
