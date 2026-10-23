# Resource-aware, strategy-selected work

The preceding `fd17d4d71` runs showed that reliable continuation could still spend
the full request allowance without improving the artifact. Bat completed 10
successors, its last five deliveries had identical captured bytes, and its final
selection saw 3.6 hours remaining while only one shared model request remained.
The original scores and trajectories remain unchanged.

This revision changes the decision interface rather than adding a stagnation rule.

## Implemented boundaries

- The allocator supplies current time/count observations to every real model role
  and a host view to the controller. The current reservation is included; unknown
  completion is not represented as an active process or refunded request.
- Captured handoffs enter strategy selection. The strategy can choose public checks,
  focused diagnosis, full verification, further execution, or rest. Full review is
  no longer an obligatory step before each next work decision.
- The selector can inspect immutable public evidence with the existing archive
  tool. It cannot execute mutable tools or read arbitrary host blobs.
- A diagnosis can reuse complete checks in its current frozen selection loop.
  Local evidence is retained separately from full acceptance. Original acceptance
  criteria, responsibility identity and actual resource limits are preserved.
- Capture provenance is independent of whether an assessment is local or formal.
  A partial observation does not erase an unrelated known scope restriction.

The pure kernel and store are unchanged. Initial drafting/probing and a bounded
review-protocol correction are still existing code-selected orchestration. General
managed experiment fixtures and broader cross-handoff evidence reuse remain future
work; this revision does not claim universal long-horizon effectiveness.

## Validation and retained failures

Artifacts are under `/data/ProContract/procontract-work-selection-20261023`.
The final unit pass contains 235 extension Rust tests; Python validation covers
51 tests; Clippy and the native build pass. Fourteen native integration controls
cover the new observation choices, actual archive reads, scoped authority, original
resource persistence, interrupted execution and explicit acceptance.

A real Luna/max last-request control first selected a useful public check but then
hit a second model admission. This exposed that model-visible balance alone was
insufficient. The final control uses the host allocator view: it preserves the
check result and rests with `budget_exhausted`, using exactly one real request and
no gateway rejection. The initial failed control remains retained. A second real
selector control chooses full verification after a public check and reaches Support.
Other roles in these two controls are scripted, not real-model solves.

The full-model qualification task is difference constraints with independently
checked feasibility/negative-cycle certificates and a separately reviewed proof.
It has no fixed native task deadline; the qualification allocator supplies an
explicit 1800-second environment limit. The external code checker was qualified
against a correct implementation (305/305) and an incorrect stub (43/305) before
task inference. The completed all-role Luna/max run passed 305/305 and reached
Support in 111 requests and 15.15 minutes. One interrupted request remained charged;
an earlier bounded diagnostic timeout and its checkpoint were retained. The chosen
sequence was check, focused negative-cycle diagnosis, then full verification. The
diagnosis reused the check's actual execution receipt. Manual review found the
certificate arguments sound; completeness cites the standard Bellman--Ford theorem
rather than providing proof-assistant certification. Exact records are outside the
source tree in `proof-and-trajectory-review.json` and `full-model/runs/`.

The prospective ProgramBench comparison uses two score-independent fresh instances,
SQLite and genact, with ProContract on/off. Each attempt uses the same Luna/max,
six-hour/1000-shared-request/offline profile. The native arm receives the same
allocator facts and preserved reference capability. Each final stopped workspace
is scored independently. Small paired comparisons remain descriptive and do not
establish leaderboard-wide or causal improvement by themselves.

The SQLite collection preflight also exposed a general evaluator-adapter mismatch:
serial preflight omitted xdist loadgroup name suffixes. The preflight now invokes
the pinned plugin's own name transformation at the matching collection-hook stage,
preserving its ordering relative to conftest-added marks. A regression covers static,
duplicate, multiple and later-added groups without running test bodies. Both official
collections now match exactly (SQLite 13,510; genact 231); no test or denominator was
changed. Initial failed preflights are retained separately. This host-only change
does not alter the previously frozen model qualification runtime.
