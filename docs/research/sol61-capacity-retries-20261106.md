# Sol capacity failure and independent retries

The user selected exactly37 original Sol cases whose terminal records directly
mention rate limiting. Ten cases with only earlier rate-limit messages are
excluded. Membership and retained incident evidence are in
`/data/ProContract/programbench-sol61-retries-20261106/QUEUE.json` and
`/data/ProContract/procontract-rate-limit-20261106/`.

These are independent repaired-version attempts: fresh workspaces, Sol6.1/max for
all roles, ProContract enabled, one21600-second allocation per task, unlimited
model requests, offline solver execution, and the original command/environment
limits. Failed requests count. Old runs, scores and grants remain unchanged;
retry scores do not replace the first-attempt aggregate. Original pending first
admissions have priority within the same shared capacity16.

## Failure and mechanism

The upstream reported organization TPM exhaustion. A transient provider capacity
refusal is distinct from exhaustion of a task's local request grant. The original
deployment configured zero native stream retries, so it could turn a transient
refusal into a terminal solver/controller failure.

The native provider's opt-in `wait_on_rate_limits = true` waits on structured
rate-limit errors and HTTP429. It uses exponential backoff from5 to60 seconds
with jitter, honors a later server Retry-After deadline, and re-enters the existing
request loop. Ordinary stream-error limits are independent; recognized billing
quota and context errors remain terminal. The default is false. The legacy remote
managed-provider wire defaults it to false and does not expose this option.

Cancellation and existing action/task timeouts own the wait. Waiting grants no
additional time or requests, and does not require a task to have a hard deadline.
The benchmark gateway preserves upstream error bodies/status and Retry-After;
it does not retry internally. Each native retry returns through the gateway and
is charged. This is harness transport behavior; no kernel transition or strategy
workflow was added.

Official guidance on exponential backoff and failed-request accounting was
checked against <https://developers.openai.com/api/docs/guides/rate-limits>;
the fetched source is retained with the incident.

## Qualification and measurement scope

Retained controls under the retry root cover gateway propagation/accounting,
native capacity waiting, server advice, cancellation, billing/context errors,
provider/config compatibility and shared scheduler admission. Real ProContract
app-server controls inject either SSE rate-limit refusal or HTTP429, then use
Sol/max to write/read a file inside the offline tool environment. A separate
deadline control verifies cancellation without allocation renewal or late
dispatch. These small diagnostic grants are not ProgramBench scores.

Retry grading uses the separately qualified grader bridge, with compilation
still offline. The exact pinned image config and filesystem are imported into
the grader daemon; official tests, assertions, retries and scorer remain pinned.
The original and corrected grading profiles remain separate. Current publication
closure/strategy changes also accompany the native build, so this retry cohort
is not an isolated causal test of the transport change, nor held-out evidence of
generalization. The deployment records exact source, binary and input hashes.
