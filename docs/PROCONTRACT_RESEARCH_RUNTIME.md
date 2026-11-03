# Durable research execution

`scripts/procontract_research_runtime.py` executes explicit user and agent choices
through the existing Operations/store interfaces. It adds no kernel transitions,
research stages, gain threshold, model-request ceiling or required task deadline.
The owner control transport is `procontract_research_control.py`; native `/rsi`
is a thin client of that separately provisioned endpoint.

## Provisioning and owner control

The public Python API is:

```python
runtime = ResearchRuntime.create(root, protected_config)  # zero model calls
reply = runtime.control(operation, request_id, request=None, thread_id=None)
```

`operation` is `start`, `resume`, `status`, `cancel` or `input`. A control request
identity is bound to its complete envelope. Repeating it returns its retained
receipt and re-ensures the supervisor when appropriate. Changing its body is an
error. Mutation intent is retained atomically with its input/generation/choice;
transport loss cannot issue the same goal twice, advance input twice, or apply an
old cancellation to a later resumed owner.

Provision before opening the UI when importing a large evidence corpus. A complete
repeat with the identical configuration reuses its pinned inputs; changed config
requires an explicit new admission. An incomplete provisioning root is retained
but cannot execute: the readiness marker must exist. No model is started by
creating the runtime, starting its owner endpoint, or reading status.

The protected configuration has this shape (paths are supplied by the provisioner,
not by a research actor):

```json
{
  "schema": "procontract-research-runtime-v1",
  "package": "/qualified/package",
  "image": "declared-image",
  "model": {"name": "declared-model", "effort": "declared-effort"},
  "strategy": "/context/research-method.md",
  "authority": {
    "principal": "delegating-user",
    "source": "the actual authorization",
    "scope": "the authorized project and research responsibility",
    "deadline": null,
    "operation_limit": null
  },
  "inputs": {"study-context.md": "/study/context.md"},
  "bundles": ["/study/evidence-bundle.json"],
  "prior_knowledge": ["/study/current-knowledge.json"],
  "projects": {
    "target": {
      "path": "/isolated/candidate",
      "writable": ["scripts", "strategies"],
      "excluded": [".git", "target"]
    }
  },
  "capabilities": {
    "research": {
      "kind": "native", "project": null,
      "inputs": ["study-context.md"],
      "select": ["research", "implement", "check", "exercise"]
    },
    "implement": {
      "kind": "native", "project": "target", "inputs": [], "select": []
    },
    "check": {
      "kind": "measurement", "project": "target",
      "measurement": {
        "argv": ["python3", "/protected/check.py"],
        "identity": "pinned check identity", "environment": "declared environment",
        "external_effects": true, "beyond_reach": false, "max_seconds": 300
      },
      "reconcile_argv": ["python3", "/protected/check.py", "reconcile"],
      "inputs": {"declared_runner_parameter": "value"}
    },
    "exercise": {
      "kind": "native", "project": "target", "inputs": [], "select": [],
      "strategy_files": {"work_method.md": "strategies/task-method.md"}
    }
  },
  "initial": {"capability": "research", "prompt": "Supplied strategy context", "seconds": null}
}
```

Native capabilities may declare `max_seconds`; absent means no capability-level
action deadline. Native time values are positive, representable whole seconds.
Actual original authority limits still cap admission. The runtime passes only the
remaining admitted native allocation to execution; restarts do not renew it.
The existing native adapter has a separate bounded shutdown grace. Measurement
limits retain their admitted runner meaning. Requests remain counted across roles
without a model-request ceiling.

`start` binds the explicit user goal and selects the configured initial capability.
`resume` recovers retained in-flight/queued work; when idle or cancelled, the explicit
owner command selects a new research turn over retained progress under the original
authority. It never replays the old assignment or restores spent allocations.
`input` is an explicit new owner turn: it advances the input generation, fences
older choices/waits, quiesces native invocations of the superseded generation, and
selects the configured research agent to receive the input. Passive observations
and operation outcomes instead follow the actor's selected wake handler.

`cancel` fences the owner, cancels queued choices, and requests scoped shutdown.
Completed work remains available. A status reply distinguishes prepared, queued,
running, waiting, cancelled and returned-without-selection execution views; none
is a new kernel completion judgment.

Acknowledging an input page does not withdraw the owner's requirements. Every native
action receives a read-only `/inputs/owner-context.jsonl` snapshot containing the
original request and ordered accepted owner inputs/control events through its admitted
generation. The control journal authenticates those records; an actor claim or imported
observation with an owner-like label cannot become an owner instruction. The snapshot
retains exact text and request/event/generation identities. It does not summarize the
owner's intent, choose a workflow, widen permissions or renew an allocation.

The normal runtime context links this immutable snapshot by hash and size and exposes
the concrete `action_assignment` separately. Long owner histories stay readable as
JSONL rather than being dumped into the ordinary context object. The invocation asks
the actor to read the standing owner context within its assigned scope; the whole
research goal is not an extra deliverable for every leaf. A stale action cannot be
rebound to a newer owner's context. Existing snapshots are not silently replaced.

## Actor capabilities

Every actor receives `/inputs/client.py`, `/inputs/intake.json` and
`/inputs/runtime-context.json`. The latter names its exact choice, origin,
predecessor/outcome, pending input and offered capability handles. It exposes no
arbitrary host-path reader or arbitrary host-command executor.

Call `python3 /inputs/client.py /workspace/s OPERATION JSON`. Existing immutable
evidence, search and scoped knowledge operations remain available.

`describe` and the supplied runtime context include an `operations` catalog with
the actual required argument names, optional defaults/omission semantics and handle
meanings for that invocation. Common `get`, `read`, `source_read`, `search` and
`knowledge` contracts are discoverable even in a leaf with no project mount. The
catalog is filtered by the transport's offered operations and grants no additional
permission. The standalone client still needs only Python's standard library; host
introspection dependencies are loaded only by the host. For example, `source_read`
uses a source object's `identity`, and metadata search uses `text`, not a filesystem
path or an inferred `query` argument.

The following runtime operations describe work and its outputs. Selection and
cancellation controls are offered only within the actor's declared descendant scope.

| Operation | Meaning |
| --- | --- |
| `receive {limit}` | Delivered input page plus an invocation-bound `delivery_token`; no acknowledgement |
| `work {identity,delivery,work}` | Delegate exactly the named capability, possibly queued behind its effect scope |
| `select {identity,delivery,work}` | Retain the chosen next work after this invocation returns and acknowledge only the delivered page |
| `select {identity,delivery,call}` | Atomically retain a leaf work item and an explicitly selected responsible continuation |
| `select {identity,delivery,wait}` | Retain an event/time wait, optionally with the explicitly selected work to run when it wakes |
| `work_status {identity}` | Read a selected work item and its actual Operations result |
| `work_status {after,limit}` | Page the durable work index without guessing operation IDs |
| `work_output {identity}` | List captured files and public messages from the actual producing invocation |
| `work_output {identity,output,offset,length}` | Read an exact bounded byte range from one listed output |
| `cancel_work {identity}` | Request shutdown of work within the actor's admitted descendant capability scope |

A work object contains `capability`, a native `prompt` when applicable, optional
`purpose`, `seconds`, `version` and `sources`. `sources` maps new plain input names
to retained **source object IDs**. Host run/workspace paths, raw command arrays and
unoffered capabilities are rejected. A wait contains `condition` using the existing
event/optional-time semantics and optionally a work object or a call. A wait without
work or call keeps no model alive and selects no automatic wake invocation.

A call contains `work` and `return_to`, both ordinary work objects selected by the
actor. The called capability is a leaf: a fixed measurement or a native actor with
no descendant selection permission. The return capability must be an offered native
actor able to select further work or waiting. The call and return recipe commit
together with the input acknowledgement. Once the leaf's actual effects are known
to have stopped, its outcome activates the retained return exactly once, regardless
of whether that outcome reports success or failure. An admission rejection similarly
returns its actual observation/reason. Unknown effects remain fenced until reconciled.

For example, the actor may select either an immediate call or a call on a chosen event:

```json
{"identity":"chosen-call","delivery":"DELIVERY_TOKEN",
 "call":{"work":{"capability":"offered-leaf","purpose":"the chosen question"},
         "return_to":{"capability":"offered-controller","prompt":"Use the actual returned outcome to choose useful remaining work.","seconds":null}}}
```

```json
{"identity":"chosen-event","delivery":"DELIVERY_TOKEN",
 "wait":{"condition":{"event":true},
         "call":{"work":{"capability":"offered-leaf","prompt":"the chosen question"},
                 "return_to":{"capability":"offered-controller","prompt":"Use the result under the continuing goal."}}}}
```

This is call/return transport, not a research-stage sequence. There is no automatic
initial-agent fallback, result-quality branch or replay of the leaf. Each action's
selected allocation is admitted once under the original authority; the call does
not renew the caller's or leaf's old allocation. Owner input/cancellation fences
even a return activated after the leaf ends. Direct `select(work)` remains an
intentional transfer without automatic return, and asynchronous `work` remains
available. Those choices do not become call/return implicitly.

`describe` exposes each offered capability's descendant `select` list, `can_select`,
project write paths, project mount/assessment view and per-invocation output scope.
A leaf cannot select further work just because its prompt requests it. The strategy
therefore owns a return path when the continuing goal needs one.

Runtime context separates a compact scheduling predecessor from actual returned
work linked by the call or wake event. Returned files live in their producer's
per-invocation `/workspace`; they are not assumed to exist in the consumer's project.
The output index identifies captured file names and final messages and supplies
exact `work_output` arguments. Raw outcomes remain available through `work_status`
or `get`; they are not dumped into the normal predecessor view.

Output pages bind the operation, complete assignment and outcome, content SHA-256,
byte range and slice SHA-256. `elision` reports bytes omitted before/after that range;
`view_complete` is explicit. Captured inline bytes remain readable even if the
producer workspace is later absent; larger/binary files are verified against their
captured manifest and read without following links. If those bytes are unavailable,
the manifest and the precise availability gap remain visible rather than inventing
an absent artifact. As with source pages, a downstream transport may elide a large
printed response; use bounded views or local structured processing and do not equate
retrieval with semantic reading of unseen bytes.

The actor chooses whether to implement, inspect, delegate, invoke a check, continue
or wait. There is no analyst/critic/repair sequence in the supervisor. A failed
operation is retained; it is not automatically repeated. A selected handler may
receive a delegated failure or uncertain effect observation and choose what to do.
Without a selected continuation/handler, returning ends that invocation and leaves
the responsibility inspectable for an explicit owner action.

Input tokens bind the delivering invocation, owner epoch, generation and exact
page. Selection/acknowledgement and wake activation are atomic. Duplicate choices
retain their operation identity and original allocation. A new owner input cannot
relabel an old mutating handler as a fresh decision. Supervisor loss leaves its
choices and independent Operations workers intact; a resumed supervisor reconciles
the same assignments before dispatching anything new.

## Candidate projects and measurements

Project lifetime is independent of per-action output directories. `/workspace/project`
is a read-only root with only provisioned writable subpaths overlaid writable.
Aliases of one resolved project path share an effect scope. A reader and writer
therefore serialize even if they use different capability/project names. The host
does not run Git commands from the untrusted project. Capture records symlinks
without following them, and source copy/hash is streamed.
An implementation capability may set `assessment_project:true` to bind native
publication/review to that declared project root and its exclusions. The default
artifact view remains the per-action workspace. This is an explicit capture scope;
it chooses no assessment workflow and does not move the report/output directory.

Project observations retain file bytes through source custody and record types,
modes, link targets and directories. Their `content_digest` is independent of
capture labels, project aliases and source record IDs; declared exclusions are part
of its scope. A changed observation identity therefore does not itself imply a
changed artifact. Ownership, timestamps, xattrs and hardlink relationships are
explicitly outside this representation.

Selecting a native capability with `strategy_files` resolves those project-relative
regular files into a separate **task** version. Unmapped policies retain the ordinary
task template, not the research method. Resolution waits until the project effect
scope is free. The assignment binds the exact resolved version, and native execution
retains its actual developer context/request bytes. By default the task receives
its own workspace and no project mount; `mount_project:true` is an explicit profile
option. This supports real downstream use of candidate task context without
changing the research incumbent or claiming deployment.

A measurement invokes only its provisioner-declared runner/arguments/inputs.
The protected assignment adds `runtime_project`, `runtime_project_snapshot`,
`runtime_inputs` and `selected_work`; its original assignment binding is retained.
Runner sources are pinned. A public check is not made beyond-reach by calling it
validation; the provisioner owns that declaration and its actual isolation.
Research/task lineages remain distinct, and target-code promotion is not automated
by this runtime. Candidate code, chosen checks and outcomes are reviewable artifacts.

After local executor loss, native cleanup inspects only its owned mounts. A trusted
measurement may supply a pinned `reconcile_argv` returning a scoped shutdown
attestation. A successful reconciliation appends evidence and a new current outcome
projection; original receipts/results remain unchanged. It cannot create a new
grant or turn unknown quality into a passing result. Unconfirmed effects continue
to fence overlapping work. Native startup failures now also retain cleanup facts
before any model call, avoiding an unfinalized setup-only operation.

Focused controls: `test_procontract_research_runtime.py`,
`test_procontract_operations.py` and `test_procontract_operations_adapter.py`.
They exercise execution integrity and authorization boundaries, not general task
quality or autonomous scientific discovery.
