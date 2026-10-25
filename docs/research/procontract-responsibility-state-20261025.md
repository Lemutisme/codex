# Current responsibility and retained observations

This development change follows the executor-interruption migration and its
post-repair review. The pure kernel and store are unchanged. Full validation and
the build/source identities are recorded in
`/data/ProContract/procontract-responsibility-state-20261025/REPORT.md`.

## Reproduced failure and repair

After an accepted Defeat, the kernel advances the contract version and generation
and retires its candidate. The controller previously passed the old contract into
the next strategy decision. A selected second verification could therefore reach
Support with stale version 2 while the kernel correctly required version 3.
The original failing reproduction is retained in
`/data/ProContract/procontract-postrepair-review-20261025`.

The controller now propagates the state returned by the accepted transition.
Selected verification establishes a proposal when the current candidate does not
identify the selected subject/generation, independent of capture origin. One
proposal operation serves delivery, interrupted work and reassessment after Defeat.
The earlier interruption-specific proposal branch and its extra in-memory proposal
test are removed. Existing delivery-time proposal scheduling remains unchanged.

The strategy receives current responsibility version/generation/candidate fields
separately from the assessment's own revision and generation. Neither adopting the
new contract state nor reproposing the same bytes changes the earlier evidence.
Local checks and diagnosis can operate with no active candidate; they do not
create one. Rest after Defeat also creates no proposal. Repeated verification of
an existing candidate still does not allocate another proposal unnecessarily.

The selection of checks, diagnosis, further verification or rest remains in
context-level strategy. A new verification does not renew task authority or reset
resource consumption. Kernel version and coordinate checks are not weakened.

## Late results and owner changes

A second deterministic control delayed a local continuation submission result
until after a new owner turn. Previously its acknowledgement overwrote the new
status with the old repairing state; an error could similarly rest the new turn.
The failing trace is retained as `late-submission-before.log` in the artifact root.

Continuation, snapshot selection, verification and successor result paths now
publish their statuses against the originating owner epoch. A dedicated publication
mutex orders that check and status commit with owner epoch invalidation, closing
the gap between a memory check and an asynchronous database write. It is never
held across model/tool execution or executor shutdown. State mutex guards still
do not cross storage I/O. Restoration's RecoveryBlocked state remains separate
from a rendered resting status.

Stale results remain in the execution history, and spent admissions remain spent.
They cannot change the current disposition through these migrated publication
paths. This is an in-process ownership boundary, not a claim of autonomous recovery
after a controller crash, exactly-once external effects or complete migration of
legacy preparation scheduling.

## Validation scope

Rust controls cover direct verification after Defeat; checks/diagnosis followed
by verification for both delivery and interruption snapshots; repeated Defeat;
rest without a new proposal; historical generation preservation; and late success
and error acknowledgements after owner supersession. The former recovery and
resource controls remain part of the suite.

Native app-server/container/tool controls include a deliberately adverse first
scripted review of unchanged bytes followed by selected reassessment. They verify
the command sequence, exact subject identity, old evidence generation and absence
of executor replay. This is a protocol/control test, not a claim that a real model
has improved its judgments. No old scored solver is resumed or relabeled.

Durable pending decisions and wake-up, recovery of selector failure, work selection
independent of issued terms, and bounded historical retrieval remain subsequent
migration work. No fixed retry policy, extra evidence threshold or RSI coordinator
is introduced here.
