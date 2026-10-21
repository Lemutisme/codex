# ProContract: kernel, harness, strategy

User architecture decision, 2026-10-18:

> strategy 为 prompt/skill 等 context level，包括如何编排工作流；
> harness 是 agent 控制/tool 层面的代码，保持本质性与解耦。

This is the ownership boundary for subsequent development. It does not claim
that the current controller already satisfies it everywhere.

## Ownership

| Layer | Owns | Examples |
|---|---|---|
| Kernel | Domain-independent progress/responsibility semantics, identities, coordinates, provenance relations, and authorized transitions | An observation belongs to a particular subject; replacing an executor does not erase the original responsibility; support and settlement are distinct |
| Harness | Agent-control and tool implementation, state/evidence transport and persistence, execution and cancellation, environment provisioning, and enforcement of actual grants | Launch or continue an agent; expose a verifier; capture a version; mount an input read-only; count requests against the original allocation |
| Strategy | Prompts, skills and supplied context that direct task reasoning and workflow orchestration | Decide what to investigate, which verifier to invoke, when to request diagnostic review, which regression controls to replay, whether to change methods or hand off |

The strategy chooses a workflow; the harness supplies and executes the operations
that make it possible. Executing a handoff or reviewer call requires code.
Deciding that a particular failure should cause that handoff or review is a
strategy decision. This distinction applies even when both currently live in one
controller module.

A verification algorithm is a tool implementation. Selecting the check, supplying
its task-specific assertions, interpreting its limits, and choosing the next
action belong to strategy. A structured invocation or capability configuration
may carry that choice into code; an opaque configurable state machine is not a
substitute for a replaceable context-level strategy.

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

## Development rule

For a proposed change, identify the smallest required capability or invariant and
the replaceable context that uses it. Put agent/tool execution code in harness;
put task-solving and workflow choices in strategy. Extend kernel only for a
missing general semantic relation or authorized transition. Keep their interfaces
explicit so a strategy can change without rewriting the execution mechanism,
and a harness adapter can change without changing the strategy's meaning.
