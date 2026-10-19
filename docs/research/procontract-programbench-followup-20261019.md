# October 19 strict ProgramBench follow-up

Runtime `bdf04e61d`, GPT-5.6-Luna/max, one solve per task, original shared six-hour/1000-request
grant, offline tools, 180-second commands and 5000-character head/tail observations.

| Task | Official result | Vals Luna/max | Requests |
|---|---|---|---:|
| sitkevij/hex | 822/823 = 99.88% | 98.54% | 196 |
| sstadick/hck | 838/855 = 98.01% | 95.20% | 1000 |

Both first evaluations are valid, without evaluator warnings or branch errors. These are
good artifact results even though neither received internal Support. hck ended at the
request ceiling, before six hours. The scores describe the stopped submissions; retained
natural handoffs and internal conclusions are separate facts. No candidate was edited or
rescored during analysis. Chamber was not admitted before inference because its official
catalog and collected suite disagree; its preparation failures remain visible, with no
replacement solve or performance score.

The two task-matched comparisons do not establish a causal ProContract gain or a
leaderboard-wide result. The harness/provider differs from Vals and no matched native
control was run. All 602 frozen input/package/adapter files remain unchanged.

## What the trajectories establish

- Retained references survived builds and four hck successor launches. The original grant
  stayed shared. hck public checks improved from 31/37 to 36/37 to 37/37, and formal
  assessments supplied actionable counterexamples. These are actual capability and local
  progress observations; intermediate official scores were not measured.
- hck's remaining 17 eligible failures center on selection order, multiplicity, escapes,
  empty selections, regex semantics and warning boundaries. Its implementation explicitly
  assumes deduplication/nonoverlap in places where the required behavior preserves
  distinctions. A representation needs discriminating observations before its simplifying
  assumptions become implementation invariants.
- Both submissions build and their archived compile scripts have mode 0755. Neither
  contains a runnable regression suite. Retained transcripts preserve experiments, but
  strategy adherence to reusable regression memory remains incomplete.
- hck spent 480 completed requests in executors, six in preparation, and 508 in reviewers,
  plus six interrupted diagnostic streams. Its six diagnostic reviews returned no complete
  judgment within the local time slice. Formal review did drive repairs. Assessment cost
  and useful information need to be considered together, rather than treating review as
  a cost-free ritual.
- Reviewers mixed partial positive evidence with whole-obligation `coverage`, putting the
  same ID in coverage and findings/gaps. hex's response and correction were rejected;
  hck needed four formal corrections. Raw observations remain retained, but the protocol
  can prevent an actionable finding from reaching the repair path.
- Reviewers repeatedly lacked facts already known to the host, including executable mode
  and enforced resource/isolation conditions. They also asked for exhaustive historical
  provenance or unrestricted equivalence. Evidence scope must be explicit; a missing
  observation should not erase an observed result or silently become a new requirement.

## Ownership

Keep the pure kernel unchanged for these lessons. Harness follow-ups concern scoped fact
transport, efficient bounded evidence reads, preservation of partial assessment work,
caller-selected resource allocation within the original grant, and a wire distinction
between observations and full-obligation conclusions. Strategy follow-ups concern
discriminating probes, regression memory, review timing and changing an ineffective method.
Do not convert the lessons into task-specific branches, universal quotas or a mandatory
planner. The legacy internal sealed-check workflow remains migration work; official hidden
tests must remain outside solving.

This document records analysis, not implementation of those follow-ups. Full provenance,
request attribution and failure categories are in
`/data/ProContract/programbench-strict-20261019/post-run-analysis.md`.
