# ProContract: kernel and evolvable harness

User architecture decision, 2026-11-07:

> 分为 ProContract kernel 和细分的 harness，harness 可以进化，
> kernel 负责责任，进程，和 RSI。

There are two top-level components. The harness includes the replaceable strategy
and instruction library alongside its execution mechanisms. The October18
distinction between context-level workflow choices and agent-control/tool code
remains an internal harness boundary. They can share a repository and runtime
while retaining explicit interfaces and independently identified versions.

Kernel process responsibility here means task progress and lifecycle semantics:
who remains responsible, what progress/evidence belongs to which subject, and
which transitions are authorized. Concrete OS processes, asynchronous jobs,
delivery, cancellation and recovery are implemented by the harness. RSI uses the
same kernel for improvement responsibilities; its analysis and experimentation
methods are evolvable harness capabilities and strategy.

This is the development contract. The capability decomposition below is an
ownership map, not a claim that existing modules are already fully separated or
that new behavior has been deployed into frozen experiments.

## Ownership

| Component | Owns | Examples |
|---|---|---|
| ProContract kernel | Domain-independent responsibility/progress semantics, identities, coordinates, provenance relations and authorized transitions for tasks and RSI | Replacing an executor preserves responsibility; evidence has a subject and scope; support and settlement are distinct; an improvement proposal uses the existing authorized transitions |
| Evolvable harness | Execution mechanisms, context/retrieval, tools, state/evidence transport and persistence, measurement, observability, version delivery and strategy library | Execute or continue work; expose observations; supply selected instructions; enforce actual grants; run improvement experiments and bind a selected version to later execution |

## Harness capabilities

| Capability | Mechanism responsibility | Replaceable strategy responsibility |
|---|---|---|
| Execution and lifecycle | Dispatch, wait, wake, handoff, cancellation and recovery of owned work under original authority | Choose continuation, delegation, rest or another method |
| Context and retrieval | Assemble actual inputs; expose current subject/requirements and historical evidence with their identities; retain permitted content and bounded readback | Choose relevant history, interpretations, counterexamples and context for the next action |
| Tools and observations | Preserve invocation identity and conditions, outputs, partial/completion states and retrievable handles | Choose tools, inputs and experiments; interpret observations |
| Strategy / instruction library | Store, resolve and deliver versioned instructions; keep capability descriptions aligned with interfaces | Supply task-solving and research methods, including diagnosis, verification, repair and handoff orchestration |
| Measurement and receipts | Execute admitted measurements, retain outcomes and process receipts with exact subject/conditions | Select checks and diagnostic questions; assess what findings imply and what remains uncertain |
| Observability and resources | Link requests, roles, operations and effects where known; account for and enforce actual grants | Allocate effort and assess useful progress from the available observations |
| Version delivery | Retain definitions and actual resolved inputs; apply authorized selections and bind later execution to them | Propose, compare and select improvements within the admitted scope |

These capabilities reuse existing state and operation interfaces. They do not
require separate services or a second memory/operation owner. Capability
instructions explain how an interface behaves; strategy instructions guide how
to compose it. A delivered instruction is observable input, not proof that it
changed a decision or improved an outcome.

Within the harness, strategy chooses a workflow and mechanisms supply and execute
the operations that make it possible. Executing a handoff or reviewer call requires code.
Deciding that a particular failure should cause that handoff or review is a
strategy decision. This distinction applies even when both currently live in one
controller module.

A verification algorithm is a tool implementation. Selecting the check, supplying
its task-specific assertions, interpreting its limits, and choosing the next
action belong to strategy. A structured invocation or capability configuration
may carry that choice into code; an opaque configurable state machine is not a
substitute for a replaceable context-level strategy.

## One kernel for tasks and RSI

An improvement objective is a responsibility whose subject is a harness version
or capability. It can accumulate observations, retain partial progress, continue
across executors and propose a change through the same kernel semantics as an
ordinary task. Existing authorized support, settlement and selection relations
govern adoption; no separate RSI kernel or universal research sequence is needed.

The harness captures trajectory evidence, makes it retrievable, executes selected
experiments and delivers selected versions. Its strategy library directs causal
analysis, candidate construction, validation and workflow choices. These activities
may be composed into an E2E loop using the existing
[durable operations interface](PROCONTRACT_OPERATIONS.md).

An observation, an interpretation, a proposed change, an authorized adoption and
actual later use remain distinct. Local reasoning and exploratory experiments
can proceed within existing authority without a kernel judgment for each thought.
The kernel does not infer general improvement from a score increase or prescribe
sample counts, model choices or review frequency. Actual use is established by
the later execution's resolved instructions, code and tools. Adoption alone is
not evidence of a quality gain.

This architecture supports event-driven RSI as well as explicitly initiated
research. It does not assert that the current campaign is already subscribed to
automatic analysis/adoption. Current qualification and deployment scope remain
recorded in the operations and experiment reports. Frozen benchmark cohorts
retain their admitted versions and grants.

## Keep the harness essential

Provide the smallest coherent capabilities needed to perform work and observe its
effects. Return concrete results, errors, partial observations and remaining
resources through explicit interfaces. Keep assets and state available across
continuations. Allow strategies to compose these capabilities without adding
another task-specific controller for each domain.

The harness enforces explicit user/benchmark authorization and actual execution
constraints: for example a shared six-hour/1000-request grant, network isolation,
process lifetime, or required protocol integrity. It must not silently invent
new authority. These mechanisms do not require it to decide that a hundred tests
are sufficient, three successors are enough, or every task needs the same review
sequence.

Do not turn an observed failure into an unconditional workflow gate in code.
Heuristics about diagnosis, progress, evidence sufficiency, or allocating effort
start as replaceable strategy context. A strategy choice does not become a
universal invariant merely because it helped one benchmark instance.

Keep the kernel smaller still. It records/enforces the admitted semantics and
transitions; it does not implement a solver, infer domain truth from a sample
count, choose a testing method, or prescribe a workflow. New evidence can revise
earlier conclusions, so progress does not mean a mandatory monotonic quality
score after every action.

## Applying the trajectory lessons

| Lesson | Harness mechanism | Strategy choice |
|---|---|---|
| Preserve verification capability | Keep immutable inputs and reference interfaces separate from mutable build outputs, available across sessions | Decide which new comparison would resolve uncertainty and where to build the candidate |
| Make feedback actionable | Expose retained observations, invocation conditions and bounded diffs | Select or construct useful diagnostic examples and use them to plan repairs |
| Retain behavioral progress | Store versioned work and replay runnable checks | Maintain the regression cases learned from repairs and select affected controls |
| Diagnose stagnation | Make prior outcomes and changes inspectable; provide review/continuation capabilities | Recognize an unproductive approach and choose diagnosis, a different method, or handoff |
| Scope uncertain observations | Return partial results and per-property observations; isolate execution failures | Interpret dynamic behavior and decide what further observation is useful |
| Use the original budget well | Account for and enforce the actual shared grant | Allocate remaining effort among implementation, experiments, review and handoffs |

The fixed 100-case threshold, three-successor cap, eight-publication cap, and
mechanical-verdict-before-review workflow in the studied implementation are
existing policy/code coupling to examine. They are not definitions of the
kernel or the essential harness. Changing them must preserve the actual task
grant and the historical experiment records.

## Task lifetime, expectations and execution limits

User clarification, 2026-10-20: real long-horizon tasks may have no time limit,
although users may have expectations about when useful results will arrive.

A continuing responsibility does not require a finite execution deadline. Treat
absence of a hard deadline explicitly, not as a large finite sentinel or an
implicitly renewed sequence of expiring tasks. Persisting progress, handing off,
resuming and cancelling must work independently of a global countdown.

Keep three facts distinct:

- A user time expectation guides priorities, scope of intermediate deliveries,
  communication and method choice through strategy context. It does not silently
  become authority to terminate the task or redefine completion.
- An explicit user/benchmark limit or actual environment restriction is enforced
  by harness. Missing time limits do not change other permissions or allocations.
- An action's chosen allocation or environment timeout bounds that execution when
  applicable. Ending an attempt does not by itself end the underlying responsibility
  or erase its completed results. Do not replace a mandatory global deadline with
  another universal mandatory action slice.

The native adapter now accepts an optional `SuccessionSettings.total_secs` and
persists a nullable deadline. Ordinary `procodex` tasks default to no hard task
deadline. Progress and continuation do not require a finite grant. Explicit
limits, including historical admitted grants and benchmark profiles, keep their
original meaning across restarts. Local action/tool limits remain separate.
Interruption retains responsibility and completed work without certifying handoff
or completion; a later turn may resume the same task.

A task allocation does not itself choose an executor workflow. In the current
adapter, a deadline-only allocation with zero fresh sessions must preserve a
separately authorized same-thread repair allowance. It must not create a fresh
executor, renew the deadline, or convert an exhausted nonzero successor allowance
into additional local work.

Review transport also preserves independent scope: a rejected support binding
becomes a gap for that obligation, while unrelated observations and findings
remain usable. Ambiguous identities or contradictory envelopes still require
correction. Retaining local results creates neither new authority nor whole-task
Support, and choosing the next investigation remains strategy work.

Resolved reviews retain a shared citation table. Coverage references a stable key;
the corresponding source hash, byte range, quotation, subject and terms bindings
are stored once in that review. Existing public paging, checkpoints and diagnostic
continuation carry the table with its judgments. The model-message allowance is
distinct from host-derived evidence representation; reusing evidence does not make
an otherwise valid response too large. Legacy inline reviews remain readable.

The terms adapter keeps non-obligatory request context (preferences, permissions,
background) separate from acceptance obligations. Strategy interprets that context;
its storage does not grant execution authority. Independent review still compares
the classification with the original request, so placing a genuine requirement in
context cannot silently remove it. This is a request/evidence representation in
the harness/store, not a new settlement-kernel transition.

## Assessment and continuation

An assessment does not itself choose the next execution. The review wire now
describes request/terms discrepancies as omitted, added or altered obligations,
anchored to the original request and affected catalog IDs. Evidence gaps and finite
coverage remain obligation judgments. Historical unanchored records retain their
original interpretation; they are not silently rewritten by a newer strategy.
Anchors establish source identity, not the truth of the model's interpretation.

After capture/proposal and after selected observations, `continuation.md` chooses
among the offered capabilities: public checks, focused diagnosis, full acceptance
verification, executor continuation, successor, or rest. A handoff does not itself
schedule full review. The selector can read the task's immutable public archive;
it has no mutable execution tool. The harness retains the choice and dispatches
the selected operation under the original authority and resources.

Local checks and diagnosis retain their observations without issuing Support or
Defeat. Only selected full verification uses the original acceptance policy and
its kernel transitions. A local observation may guide repair before formal review,
and a captured partial delivery may rest without a completion claim. Capture source
(delivery or in-turn publication) is independent of the assessment's purpose.
Local operations omit withheld acceptance cases and their eligibility gates;
the original issued policy remains unchanged for full verification. Complete public
check receipts can be reused by a diagnosis in the same immutable selection loop.

Local continuation is reserved before dispatch and remains spent across recovery.
Owner input fences stale selections, and native interruption remains distinct from
an artifact failure. Original deadlines and successor reservations still apply.
The existing interpretation of local versus fresh-executor allowances is preserved:
an exhausted nonzero successor grant cannot become additional local attempts.
This compatibility boundary is not a new kernel invariant.

Verification summaries and successor transport describe observations, authority
and context. Their former instructions about which experiment to do first and
when to repair/hand off live in replaceable strategy text. Initial preparation and
the single review-protocol correction remain legacy code-selected workflow;
this is a partial migration, not a claim that all
orchestration has moved out of code. No RSI coordinator is introduced.

Continuation wire choices are a tagged union: check/verify/rest carry a reason,
diagnose carries a question, and resume/successor carry work scopes and a next step.
The output schema and parser
express the same alternatives. Repeated IDs do not widen a scope and are normalized;
unoffered actions and scopes still cannot create authority. Old stored selections
remain readable as historical records and are never replayed as new requests.

The selection's durable event hash links successor reservation/return or local
submission acknowledgements. A returned successor may identify a captured delivery
by its exact turn. Strategy receives these records alongside the current assessment
and the offered executor capabilities. Submission, return, artifact change and a
successful repair remain distinct; an absent link, including a legacy record, is
unknown rather than proof of nonexecution. Local submission does not claim a
completed turn. This adds observation transport in the harness, not a kernel state
transition or an instruction to retry.

The text benchmark adapter disables the native image-viewing tool. If another tool
still returns nontext content, the gateway delivers an explicit incomplete-observation
notice and retains available text plus an audit hash. It never forwards the omitted
content or changes the model/request/time grant. A modality mismatch in a tool result
therefore remains actionable feedback rather than terminating the entire task. This
profile-specific limit does not remove image capability from ordinary ProContract use.

Automatic turn admission also queues its additional context and instruction together.
Both are available in the first sampling step, alongside pending mailbox input. Starting
with context while deferring its instruction caused an avoidable second model response
for large worker packets. This is a general native harness input-assembly correction;
it does not convert an automatic turn into user authorization or change task grants.

## Interrupted execution and selected work

The captured work representation is independent of a completed handoff. After a
native executor failure, or a successor failure with confirmed shutdown, the
adapter retains an interruption snapshot and exposes it to the same continuation
strategy. Checks and diagnosis do not propose that snapshot to the kernel. If
strategy selects full verification, that operation proposes the exact captured
subject; repeated verification does not create duplicate proposals. The archive
exposes the interruption observation without manufacturing a delivery receipt.

Root failure during preparation remains recorded until the existing preparation
finishes, then reaches this selection path. The benchmark driver must follow the
lane's disposition: a failed root turn does not independently terminate active
preparation or continuation. User interruption and unresolved executor lifetime
retain their distinct stopping behavior. Original reservations, resource limits
and owner epochs remain in force; no retry-count policy is added to the kernel.

This migration does not yet provide autonomous recovery after controller process
loss or selector failure, or execution selection independent of issued terms.
Those broader continuation/wake capabilities remain explicit implementation work.

Publication preparation has its own execution outcome. When capture fails and the
executor has been confirmed resumed, or local materialization fails before any
assessment dispatch, the harness records a finished operation error. The original
reservation stays spent. The error remains readable and a repeated request recalls
that outcome; a new request can do further authorized work under the original grant.
An unknown barrier/resume or assessment effect remains unresolved. A failed local
preparation does not imply either a failed artifact or an outstanding external action.

These operation records use a separate public evidence scope from artifact assessment.
They cannot become diagnostic findings, Support or Defeat. Journal recovery can
finish an interrupted bookkeeping step from the retained operation outcome without
replaying its effects. Choosing whether to repair a fixture, change methods or make
another publication remains strategy work.

## Allocator observations

The shared model gateway projects an allocator snapshot into every request after
reserving that call. It records the exact forwarded payload hash and snapshot.
The remaining count includes the current call and all task roles; failed calls
stay spent. Absent time or count limits remain absent. These are observed resources,
not workflow instructions, future reservations, acceptance claims or user time
preferences.

The same committed allocator state is published atomically to a provisioner-owned
host file. Optional `resource_snapshot` settings connect that view to the native
controller. Known exhaustion prevents a new selector or worker from starting; a
previously selected non-model check may finish and retain its results. Missing or
inconsistent views remain unavailable, while the allocator still authoritatively
admits every request. The view cannot renew a grant. No fixed review reserve or
universal task countdown is introduced. A missing publication grant also does not
hide a separately declared native task deadline.

Public archive records identify their observation scope. Scope restrictions survive
check-only or unrelated partial observations; a new explicit judgment on that
obligation can revise them. Older-generation judgments cannot supersede newer ones
merely by arriving later. These are harness evidence relations, not extra kernel
states or benchmark-specific success rules.

## Development rule

The opt-in [durable operations interface](PROCONTRACT_OPERATIONS.md) now supports
ordinary tasks and separate improvement responsibilities through the existing
kernel. It retains version definitions, actual resolved inputs, assignments,
outcomes, pending events and authorized selections. Research sequence and candidate
choices live in `strategies/research/operations.md`. Stored knowledge does not
install behavior; a selected version must be bound to its actual later execution.
The first qualification establishes a scoped tool-adaptation loop, not general
quality gains or automatic migration of existing native controllers. Fixed
benchmark cohorts retain their admitted versions and resources.

For a proposed change, identify the smallest required capability or invariant and
the replaceable context that uses it. Place agent/tool execution code in the
relevant harness capability and task-solving/workflow choices in its strategy
library. Extend kernel only for a missing general semantic relation or authorized
transition shared by ordinary work and improvement responsibilities. Keep their
interfaces explicit so strategy can change without rewriting the execution
mechanism, and an adapter can change without changing the strategy's meaning.
