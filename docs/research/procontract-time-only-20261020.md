# Chamber: six hours without a model-request ceiling

The user requested a time-only experiment to study long-horizon progress. The
fresh solve retained GPT-5.6-Luna/max, the qualified 907392eff runtime and strategy,
offline execution, 180-second commands, 5000-character head/tail observations,
and the same official 1748-test evaluator. Only the shared request ceiling was
removed. Gateway commit 7850ae449 adds explicit `requests=None`, preserves request
accounting and deadline enforcement, and leaves the default ceiling at 1000.
Seven tests covered concurrency beyond 1000, restart/profile integrity, the
unchanged default ceiling, and actual HTTP stream deadline cancellation.

| Artifact | Requests | Solve minutes | Official passes | Rate |
|---|---:|---:|---:|---:|
| Previous independent capped run | 1000 | 130.61 | 1625/1748 | 92.96% |
| This run's preregistered native checkpoint | 859 | 112.98 | 1476/1748 | 84.44% |
| This run's final stopped workspace | 2462 | 359.84 | 1639/1748 | 93.76% |

The checkpoint was the latest immutable native version witnessed with at most
1000 requests, not the exact live workspace at request 1000. Both prescribed
artifacts were graded only after solving ended; their first evaluations were
valid. No official feedback reached the solver. This research profile differs
from the strict 1000-request ProgramBench/Vals profile.

From checkpoint to final, 166 tests improved and three regressed: net +163,
or +9.3249 percentage points. Gains included Secrets Manager, environment
semantics, error handling, validation and tags. Against the previous independent
run, 23 improved and nine regressed: net +14, or +0.8009 points. The experiment
demonstrates realized improvement during an extended trajectory, but a single
fresh stochastic run does not establish a general causal return per extra call.

All 2456 complete responses were Luna/max; six incomplete streams remained
charged to the request count. Complete-call attribution: initial executor 258,
seven successors 1497, preparation six, formal review 415, diagnostic reviews
without final judgments 280. Eight diagnostic sessions returned no final
judgment. One formal citation correction succeeded; the newer 55e395e5b citation
fix was intentionally excluded from this comparison.

The fixed internal comparison suite progressed from 105/123 to 121/123, while
public checks rose from 36/41 to 41/41. Final verification exceeded its remaining
action time after the runtime's ten-second cleanup margin. The recorded
`native_terminal` is therefore not natural verified completion. Internal Support
was false; the valid 93.76% artifact score remains a separate positive result.

Of 109 remaining official failures, 62 belong to the two SSM modules. Candidate
code still lacks `CHAMBER_AWS_SSM_ENDPOINT`; the test fixture uses that ordinary
environment interface for its local mock, whereas the candidate attempts default
external DNS. This is an implementation gap, not a reason to relax offline
evaluation. It does not imply that adding the variable would pass every SSM test.
These findings are post-run only and must not enter a future clean solver.

The general lessons retain the established ownership boundaries:

- Strategy should decide when additional probes of known behavior have become
  less useful than exploring new environments, states or backend paths.
- Harness should expose authorized diagnostic observations, reproducible
  conditions, partial work and remaining resources. Eight diagnostic sessions
  without final judgments warrant examining the mismatch between the bounded
  diagnostic operation and its full-review instructions, rather than prescribing
  a universal retry count.
- Current internally generated sealed checks expose aggregate mismatches but
  withhold individual cases. Several formal reviews repeated that seven, three,
  then two cases differed without identifying inputs. Choosing diagnostic versus
  independent-validation use belongs to strategy; transporting authorized
  evidence belongs to harness. Official hidden tests remain post-solve only.
- Kernel needs no task-specific gate, sample threshold or successor quota from
  this result. Subject identity, responsibility and authorized transitions remain
  its scope.

Detailed reports and original results live in
`/data/ProContract/programbench-chamber-time-only-20261020/`:
`post-run-analysis.md`, `post-run-analysis.json`, `long-horizon-analysis.json`,
and `completion-audit.json`. Five plans' 2825 frozen-file entries and both scored
artifacts were verified unchanged. All owned run processes stopped. Analysis
used no new model calls, grading, candidate changes or score-based retries.
