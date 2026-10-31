# Durable operations and scoped version selection

`scripts/procontract_operations.py` supplies execution and evidence operations to
ordinary tasks and improvement responsibilities. It calls the existing
`pro-contract-store` kernel; it adds no learning or goal transitions. The older
`scripts/procontract_rsi.py` remains a historical fixed-workflow campaign driver.
The new interface neither imports its scheduler nor adopts its empirical gates.

A protected provisioner creates `Operations` with an `Authority` and explicitly
admitted `Measurement` capabilities. The authority names its original source,
deployment scope, editable files, permitted measurements and optional actual
limits. Missing deadlines/count limits remain absent. A changed host implementation
requires explicit migration before new work, rather than silently reinterpreting
an old assignment. Measurement executable/configuration sources are pinned and
checked before execution. The caller may choose an action allocation; the host
caps it by the admitted capability and original authority.

`procontract_operations_rpc.Broker` exposes a local capability socket for one
responsibility. Mount the socket into its offline environment; keep the host
journal, authority, sealed evaluator and inputs outside it. Actor identity and
settlement provenance come from that binding. The actor cannot bootstrap a version,
create authorization evidence, choose an unoffered measurement, widen its editable
files or supply a human settlement. The example research context is
[`strategies/research/operations.md`](../strategies/research/operations.md).

The capability surface is intentionally small:

| Operation | Meaning |
| --- | --- |
| register / get / read | Immutable v2 version definitions and incremental event retrieval |
| resolved | Instructions actually supplied, retrieved sources and run conditions |
| observation / knowledge | Outcomes or explicitly labeled claims; scoped interpretation/correction, without adopting behavior |
| submit / dispatch / inspect / reconcile / cancel | One explicit assignment, durable reservation, process identity, outcome and original resources |
| subscribe / inbox / wakes / wait | Selected event inputs, coalesced pending cursor, durable waiting; selector failure does not acknowledge input |
| adopt | Existing kernel Issue/Propose/Support and atomic Discharge + selection, with actual delegated provenance and an expected-incumbent fence |

Version definitions identify all supplied instruction files, code/build, model,
resolver and tool identities; task and research lineages are distinct. The actor's
file bytes are content-addressed. A provisioner can explicitly permit changes to
build/model/resolver/tool definition fields; these are declarations whose actual
use must be bound by the execution adapter. They are not self-authenticating build
attestations. Per-run resolved inputs are separate from version definitions.
The qualification adapter retains exact native model request payloads as well as
version/context identities and allocator request/usage records for every role.

Dispatch can be delivered repeatedly. A worker claims the durable reservation
before starting external work. Cancellation/finalization belongs to the operation,
not the requesting transport. A retained receipt is reconciled into one outcome
and wake transaction after caller/process loss. A lost worker without a receipt
is `unknown`; re-dispatch does not repeat it and its observation still wakes subscribers.
Authenticated effect scopes fence conflicting actions. Confirmed local process/group
shutdown can reconcile an interrupted result without inventing quality. Original assignments and allocations
are not renewed. This is not an exactly-once claim about external effects. Local
process shutdown cannot certify container/remote shutdown after the client failed;
those lifetimes require a retained adapter attestation. The native qualification
adapter confirms/removes only containers with that invocation's exclusive host
mounts. Its selected-wait handling quiesces the invocation after the actor turn
ends, even if an unrelated legacy preparation worker is still running.

Adoption is scoped to the original authority and a host-admitted measurement. The
protected evaluator determines its own admissibility result; no numeric research
threshold is built into the operation host. Presumed adoption requires actual
beyond-reach evidence. The actor's interpretations or within-reach self-tests
cannot supply that condition. Initial selection cites the provisioner's standing
authorization and makes no performance claim. Kernel/store settlement conditions
are unchanged. A lost adoption acknowledgement returns the original committed
receipt; a different request or stale incumbent is rejected. Committed receipts remain
readable after allocation expiry; that read creates no new authority. A research
version cannot inherit the existing task deployment's kind. Cancellation and an
admitted adoption have a single host ordering.

The native runtime additionally retains a cancelled action's terminal receipt,
lets a publication outlive its caller's transport, waits for a known local
inspection owner to finalize before assessing its receipt, and permits a fresh strategy
decision after confirmed check/reviewer interruption. Thread teardown still
cancels work. Unknown effects remain blocked. Completed shutdown without a
caller-level computation result spends the original slot but does not invent an
observation or prevent a separately authorized next action.

Run the small real-model qualification explicitly:

```sh
PRO_CONTRACT_STORE_BIN=/path/to/package/bin/pro-contract-store \
  python3 scripts/qualify_procontract_operations.py \
  --root /new/isolated/episode --package /path/to/package --image IMAGE
```

The fixture uses GPT-5.6-Luna/max, native ProContract, offline containers, an
independent sealed reducer measurement, and separately recorded task/research
allocations with no model-request ceiling. A native task outcome atomically wakes
the research responsibility; the model uses the socket to diagnose, author a
candidate, select experiments and decide adoption. A fresh native task loads the
selected version. The fixture contains no replacement patch or promotion decision.
This is a deliberately synthetic defect and tests operational closure, not broad
improvement, causal ProgramBench gains or model-weight reinforcement learning.

Fault controls are in `scripts/test_procontract_operations.py`; native lifecycle
controls are in the extension's execution/progress/inspection tests. Unknown native
process effects, pre-Issue recovery and automatic in-process retry of a failed
legacy native selector are not silently repaired by this interface: the generic
host preserves their operation outcome/pending input for a separately authorized
arrangement. Existing fixed campaigns remain pinned and receive no automatic
migration or hidden feedback.
