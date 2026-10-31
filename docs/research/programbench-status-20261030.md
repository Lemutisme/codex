# Time-only cohort status, 2026-10-30

Snapshot at approximately 22:52 UTC. The frozen solver and campaign files remain
unchanged. This status pass records new outcomes and checks anomalous state reporting;
it is not a new strategy implementation or a rerun of stopped solvers.

- 112/200 job records are terminal; 104 valid canonical scores.
- Four actual solver jobs are active and 84 tasks are queued; admissions continue.
- Valid-subset mean 75.7505%; Vals on the same 104 tasks 68.3189%, under different
  request resources. Seventy-eight higher and twenty-six lower results.
- Two perfect results: hex 823/823 and zip-password-finder 680/680. Both feedback
  vectors contain only passes and their raw result hashes match the bound records.
- Zip-password-finder used 1572 requests and 225.64 minutes, then rested by strategy
  choice. Its strong result remains valid without internal Support. This establishes
  a successful partial-duration attempt, not a causal comparison with longer runs.

New strong results include code-minimap 311/313 = 99.36%, htop 685/692 = 98.99%,
xcp 1150/1184 = 97.13%, html-to-markdown 853/885 = 96.38% and bartib 689/721 = 95.56%.
The increased aggregate describes a changing subset, not a changed solver version.

## Eight terminal jobs have no valid score

Five failed before solver admission: jsonschema, i3-style, pueue, gdu and age.
The new gdu collection probe reports five missing expected identities and no extras.
Age's grader setup requests Go 1.25.5, which is unavailable in the effective offline
toolchain environment. The absent scope receipt follows that earlier setup failure.
Both belong in the existing observation/bootstrap qualification work; no solver
attempt or score is invented for them.

DuckDB remains unscored because its large raw output was not processed past the
result parser/hash limits. Jq now has an invalid canonical result with 1277 not_run
entries, one unexpected test identity and a denominator mismatch. Its observed
partial counts must not be presented as a valid full canonical score. The jq root
execution/collection cause needs separate analysis; no excluded cases or denominator
were changed in this pass.

Dutree is the eighth terminal unscored job, and has a reporting defect described below.
Thus the live row labels (106 finished, five preparation_failed, one grading) must
not be interpreted as one genuine ongoing grading job in addition to the four solvers.

## Dutree: cleanup failure prevented the terminal result from being saved

`JOB_RESULT.json` is terminal with a run_case.py failure. `driver.log` locates the
uncaught error in the final cleanup call. In run_case.py, cleanup is called before
writing RESULT.json inside finally; its exception prevents that result write.
There is no RESULT.json or evaluation directory for this case. The app-server PID
has exited, and a read-only Docker inspection finds the execution container dead,
Running=false and Pid=0. Docker reports an overlay2 root-filesystem removal failure
(`directory not empty`) while removing that dead container.

The supervisor's report function chooses `grading` merely because runtime-result.json
exists, before considering the terminal failed job record. It therefore presents
this already-failed job as still grading. That label was not repeated as live
grading progress in the user-facing status.

The general H1 issue includes distinguishing confirmed execution stop, residual
resource cleanup, submission/evaluation progress and durable result publication.
A cleanup exception must remain visible without erasing the operation outcome;
derived status should incorporate the terminal disposition rather than infer it
solely from an intermediate artifact's existence. The precise overlay2 removal
cause is not established here. No dead-container deletion, solver restart, submission
freeze or grading repair was attempted in this status pass.

The unresolved-publication ending appears in 36 solver attempts. Its known lifecycle
defects remain recorded for consolidated repair. No full detailed trajectory analysis
of all newly completed cases is claimed.

Evidence is saved under `/data/ProContract/procontract-status-20261030/`:
cohort-status.json, perfect-score-audit.json and triage.json. See
[the evolution register](procontract-evolution-register.md) for the consolidated
harness/strategy directions.
