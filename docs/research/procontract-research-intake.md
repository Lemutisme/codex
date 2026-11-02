# Research over retained experience

`scripts/run_procontract_research.py` supplies a reusable native entry point for an
arbitrary evidence bundle and study context. The supplied strategy is
`strategies/research/trajectory_analysis.md`. The Python driver imports custody,
pins the selected context/runtime and dispatches one caller-selected operation.
It does not schedule analysis, criticism, experiments or adoption. No kernel,
Operations or native-adapter change is needed for this path.

The study context owns the substantive request: population and units of analysis,
source map, inherited hypotheses, current questions, actual user conditions and
the requested deliverables. The method separates census coverage, measurement
availability and claim verification; it examines success mechanisms, first observed
failure stages, counterexamples and proposal→verification→correction relations.
Reading a complete index is not equivalent to deeply reading every trajectory.
Prior analyses remain claims whose corrections and source evidence can be followed.

Prepare a new isolated study without making model requests:

```sh
PRO_CONTRACT_STORE_BIN=/path/to/package/bin/pro-contract-store \
  python3 scripts/run_procontract_research.py prepare \
  --root /new/research-intake \
  --package /path/to/package --image IMAGE \
  --bundle /study/bundle.json --study-context /study/study-context.md \
  --input census.json=/study/census.json \
  --input synthesis.md=/study/synthesis.md \
  --input evidence-map.json=/study/evidence-map.json \
  --prior-knowledge /previous/current-knowledge.json \
  --authorization-source 'User request and date' \
  --scope 'Isolated research over retained evidence; frozen task runs unchanged'
```

The bundle uses `procontract-evidence-bundle-v1`, with declared paths/hashes and
source-linked observations or claims. Repeat `--prior-knowledge` for exported cited
closures and `--input NAME=PATH` for additional files. Input names are plain names.
The driver snapshots the exact context and input bytes. Raw evidence goes through
the existing content-addressed source custody and bounded read interface. The
actor receives an intake receipt mapping bundle keys to retained object identities.
`--method PATH` explicitly selects another context-level research method.

Launch one action after sources are ready:

```sh
PRO_CONTRACT_STORE_BIN=/path/to/package/bin/pro-contract-store \
  python3 scripts/run_procontract_research.py run --root /new/research-intake
```

This uses GPT-5.6-Luna/max, offline native execution and unlimited request accounting.
The standing responsibility has no deadline. `--seconds N` can explicitly allocate
whole seconds to this action; omitting it leaves that action's deadline absent too. A repeated
delivery of the same pending interval retains the original operation and allocation.
It cannot silently renew a limit or change the selected request. A partial input
acknowledgement permits a separately selected action on the remaining page. The
driver does not automatically start that next action or retry an uncertain outcome.
Keep the pinned package, host adapter sources and admitted input snapshots unchanged
during native execution. An intentionally different study uses a separate root;
the prior cited knowledge can be imported without transferring authority.

The actor can retrieve sources, retain/revise knowledge, register a candidate
`work_method.md`, and select a wait. It has no measurement or adoption capability in
this intake. Thus a report or candidate is reviewable research output, not certified
performance or a deployment decision. Existing Operations measurements/adoption
remain available to separately authorized work; no small synthetic qualification
is implicitly substituted for the requested experience analysis.

`inspect --root PATH` reports existing state without dispatching. `export --root
PATH` writes `current-knowledge.json`, including current knowledge roots and their
cited closure/corrections. Native request payloads, allocator counts, resolved
context, output files and shutdown observations are retained by the shared adapter.
`actions/IDENTITY.json` records each returned action; `latest-action.json` is a
projection. Source hashes establish custody. Self-reported coverage and causal
claims still need substantive review against the cited evidence.

Run the focused custody/allocation controls with:

```sh
python3 -m unittest discover -s scripts -p test_run_procontract_research.py
```

These controls make no model calls and claim no task-quality improvement.
