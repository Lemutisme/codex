# Queue the three remaining GPT-5.6-Luna cases

The user authorized queueing every remaining Luna5.6 remeasurement/retry. The
durable coordinator is
`/data/ProContract/programbench-luna56-completion-20261107/`.

| Task | Selected action | Preserved subject / new allocation |
|---|---|---|
| Tparse | Independent solver retry after terminal upstream503 | Fresh workspace; GPT-5.6-Luna/max; six hours; unlimited counted requests; offline;20 CPUs/60 GiB;180-second commands |
| Dog | Artifact-only grading repair | Exact original Luna source archive; qualified grader network conditions; zero solver calls |
| SQLite | Artifact-only grading completion | Exact November3 Luna retry archive; larger suite execution allocation; zero solver calls |

Tparse uses the qualified native binary at `c2130fc07` with the November3 Luna
policy bundle. Its retained `work_method.md` hash is
`cee04464090d979772d41e3ae07aabb5a0bf10a5356e8b088783d8a78d65d4d9`.
The source version, binary, supplied policy and transport adapters are explicitly
pinned. A task-independent request confirmed the exact `gpt-5.6-luna`/`max`
response identity before queue activation. No earlier implementation or score is
supplied to the new solver.

Grading uses the selected resource profile: at most two isolated10-core test
branches, a three-hour suite command and a twelve-hour measurement allocation.
Official per-test timeouts, assertions, retries and scorer remain unchanged.
The already completed dep-tree calibration reproduced every raw test outcome,
the compiled executable hash and the73.9884% score under this profile.

The coordinator shares total capacity24 and the64 GiB available-memory admission
reserve with the live Sol and GPT-6-Luna jobs. It reserves the next three slots
without interrupting active jobs. Ordinary admission capacity is restored when
all three are admitted. Original solver grants and raw results are retained.

`QUEUE.json` names exactly these three jobs, `QUEUE_ARMED.json` binds the queue
and frozen plans, and the systemd unit survives the interactive session. It does
not resume a stopped solver. Actual preparation and scoring execute through the
same qualified paths as the ongoing campaigns.

`BASELINE.json` binds the existing197 valid Luna results. `COMPLETION.json` adds
each declared completion result only after the independent scorer audit matches
its artifact, tests and projection hash. An API-failed retry can retain an
artifact score without becoming a valid model instance. No selection takes the
maximum of old and new results. The original Jsonschema and stgit corrections
are already included in the197-case baseline.

Sol's existing pending jobs and SQLite remeasurement continue in their own
queues. No duplicate Sol attempt or new RSI strategy activation was created.
