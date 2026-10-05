# ProContract evidence: a sealed prober suite, faithful cases, and process constraints

Status: design, for review. Date: 2026-10-05. Branch `procontract-rsi`, after the merge of upstream `main` @7f892275e3.
Builds on the essential spec (`2026-09-29-procontract-essential-design.md`, cited E§n) and the RSI spec
(`2026-09-30-procontract-rsi-design.md`, cited R§n). It changes no kernel rule.

Inputs:
- M0 corpus-v1 (68 runs) and retest-v2 (8 ON runs), `~/run-artifacts/procontract-rsi-m0-20261001/`;
- two surveys of OpenCode work: native RSI e2e (`~/opencode-native-rsi`, `~/run-artifacts/native-rsi-*`) and earlier
  evidence/probe work (`~/opencode-*probe*`, `~/opencode-counterexample-*`, `~/run-artifacts/trajectory-credit-20261003`,
  `~/ICLR_paper/contents/4_exp.tex`).

## 1. Goal, measured problem, principles

**Goal.** `supported` must predict a high hidden-test pass rate, while the lane stays end to end inside the Codex
harness. Success: the missed-defect rate of supported candidates (hidden pass rate < 0.95) falls well below the 2/3
measured in retest-v2, and the verifier's own sealed pass rate correlates with the hidden pass rate.

**Measured problem (retest-v2 and corpus-v1).**
1. Differential cases run in an empty scratch directory, so relative file arguments never resolve: 39 of dutree's 40
   cases exercised only "path doesn't exist". (Verified in the check container: `dutree -s README.md` fails in an empty
   cwd and succeeds in `/workspace`.)
2. Cases carry no fixtures; dutree's 376 hidden failures are size computations over real directory trees.
3. stderr is not compared, although the task requires it; 30 of rust-sloth's 121 hidden failures assert on stderr.
4. The reference is not qualified: both-error and both-timeout count as agreement; unstable channels risk false defeats.
5. At most 40 cases, all public, frozen by the drafter from `--help` alone.
6. The drafter files cleanroom prohibitions under `out_of_scope`; the reviewer reports a terms gap, which forces
   `not_verified` (9/34 corpus-v1 ON runs, 2/8 retest-v2) and erases the reviewer's own verdict.

**Lessons adopted from OpenCode.** Internal evidence routinely passed while hidden scores were low; only a sealed oracle
discriminated (3 public + 5 sealed angle-grinder cases). Byte-exact obligations from one reference run produced
unsatisfiable debt and gaming; whole-observation rejection regressed (i3-style −8.53pp), so qualify per channel.
Mandatory gates and barriers cost score (Falsifier: 73/74, 81/81, 59/59 failed ready calls). Infrastructure failures
are invalid, never zero; a candidate's own build failure is a genuine zero. Large probe sets kept finding mismatches
after small ones were clean (code-minimap, cheat).

**Principles (elegance constraints).**
1. **No kernel change.** Everything lives in `Terms`, `EvidencePolicy`, the check pipeline and `decide`.
2. **One case runner.** Public cases, sealed cases, prober exploration and offline replay all run through
   `checks.rs`; nothing re-implements execution or comparison.
3. **The prober is the drafter's sibling.** Same worker runtime, same `Ports::run_worker` seam, same strict-JSON
   validation; one new file `workers/prober.rs`.
4. **Public and sealed are partitions of one case type**, judged by one pure function with per-partition rules.
5. **No new process, service or store.** Evidence goes to the existing ledger and experiment events; the offline
   command is a thin entry point over `checks::run`.
6. **Configuration lives in `settings.json`** and is copied into the policy at Issue, so it is hashed.

## 2. Data model (codex-pro-contract-store `terms.rs`)

All new fields use `#[serde(default)]`, so policies and terms already in ledgers still parse.

```rust
pub struct DifferentialCase {
    pub id: String,
    pub args: Vec<String>,
    pub stdin: Option<String>,          // limit raised from 4 KiB to 64 KiB
    pub files: Vec<FixtureFile>,        // written into the case directory before each run
    pub dirs: Vec<String>,              // empty directories
    pub env: BTreeMap<String, String>,  // at most 16 keys, [A-Z_][A-Z0-9_]*
    pub family: String,                 // coverage tag; the only sealed detail an executor may see
}
pub struct FixtureFile { pub path: String, pub text: String, pub repeat: u32 } // content = text × repeat
```
Fixture paths are relative, contain no `..`, and expand to at most 256 KiB per case.

```rust
pub struct EvidencePolicy {
    // existing: class, build_command, candidate_command, candidate_tests, differential (now "public"),
    //           reference_command
    pub sealed: Vec<DifferentialCase>,
    pub sealed_threshold_permille: u16,   // θ_s; default 950
    pub min_sealed_qualified: u32,        // default 100
    pub min_success_permille: u16,        // share of qualified sealed cases whose reference exits 0; default 500
}
pub struct ProcessConstraint { pub text: String, pub source_quote: String }
pub struct Terms { /* existing */ pub process_constraints: Vec<ProcessConstraint> }
```
`ExperimentKind` gains `Probe` (the prober's raw output and exploration observations).

## 3. The case runner (`checks.rs`)

One runner executes any list of cases in the check container (network none, container user, existing image):

- **Identical paths.** The working directory is always `/tmp/pc-case`; the program is always invoked as
  `/tmp/pc-bin/executable`, a symlink re-pointed to the reference or the candidate before each run. A symlink, not a
  copy, so an execute-only reference still works.
- **Base fixture.** The materialized base subject (the workspace the drafter saw; the reference executable is already
  excluded by the capture policy) is mounted read-only at `/pc-base`. Before every run the case directory is wiped,
  `/pc-base` is copied in, then the case's `dirs` and `files` are created.
- **Fixed environment.** `env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 TZ=UTC HOME=<fresh empty dir>` plus the case's `env`; stdin from
  the case (empty otherwise); no TTY in this version.
- **Order and timeout.** Reference, candidate, reference; 10 s each.
- **Channels.** Exit status, stdout, stderr, and the post-run file listing of the case directory (path and sha256 of
  every file).
- **Qualification, per channel, at every verification.** A channel is stable when the two reference runs agree on it.
  A case is `unqualified` when the reference exit status is unstable or the reference timed out. Otherwise the case
  passes when the candidate agrees with the reference on every stable channel; a candidate timeout fails. No output
  normalization.
- **Hang breaker.** After 5 candidate timeouts the remaining cases skip the candidate and fail.
- **Receipts.** `StepOutcome` gains `Unqualified`. Each case step is named `public:<id>` or `sealed:<id>` and records
  its outcome, stable channels, reference exit status and, for failures, a bounded per-channel diff.
- **Observe mode.** The same runner runs cases on the reference only (two runs, bounded outputs) for prober
  exploration (§4).

The build step and candidate tests are unchanged. Rough cost: 300 cases × 3 runs, milliseconds to tens of milliseconds
each, so one to three minutes per verification; the hang breaker bounds the worst case.

## 4. The prober worker (`workers/prober.rs`)

A hidden, isolated, tool-less worker that runs in parallel with the drafter, independent of it. Issue waits for both.

1. **Explore.** Input: the verbatim intake, a documentation-first base view (120 KB cap) and the reference `--help`
   observation the drafter also receives. Output: at most 30 exploration cases (with fixtures), for example each
   subcommand's help, one sample per documented input format, and typical combinations.
2. **Observe.** The lane runs them in observe mode; outputs are bounded to 2 KB per run and 40 KB in total.
3. **Write.** A fresh worker turn receives the same inputs plus the observations and returns
   `{coverage_plan: [{family, surface, description}], cases: [...]}` with 150 to 300 cases.

The instructions require covering every documented surface (subcommand, flag, option value, input format, exit and
error behavior) with at least three cases each, including success-path cases with realistic fixtures (nested
directories, files of known sizes, a file per documented format), boundaries (empty, zero, large, Unicode,
whitespace and line endings) and error classes. Only invocations are frozen, never expected outputs. The reference
program is never an input.

Validation follows the drafter: unique plain ids and fixture limits. Fewer than 150 cases are accepted. If the prober
fails or its output is malformed, the contract is still issued with an empty sealed partition; verification then
ends `not_verified` (insufficient evidence). Failure is visible and never silently weakens the evidence.
`prober::policy_digest()` joins the producer identities; the raw output goes to a `Probe` event.

## 5. Lane flow (`controller/runtime.rs`)

- Intake captures the base subject (unchanged). The active contract now keeps the base subject hash for verification.
- `draft` probes the reference once (`--help`), then runs the drafter and the prober concurrently. Issue combines the
  drafter's terms and public cases, the prober's sealed cases, and the evidence settings.
- `verify` materializes the candidate and the base, runs one pipeline (build, candidate tests, public cases, sealed
  cases), and calls the reviewer only when the mechanical rules in §6 pass.

## 6. Decision and exposure (`controller/decision.rs`)

`decide` evaluates in order:
1. The checks did not run (launch error, container timeout, incomplete receipts) → `NotVerified(Infrastructure)`.
2. The build failed → `Defeat`; the residual carries the build log.
3. A public case failed → `Defeat`; the residual names each failing public case (invocation, channel, bounded diff).
4. Sealed partition. Let Q be the qualified cases, P the passing ones, S the share of Q whose reference exits 0.
   - If Q < `min_sealed_qualified` or S < `min_success_permille` → `NotVerified(InsufficientEvidence)`.
   - If P/Q < θ_s → `Defeat`. The residual says only "N of Q independent sealed checks failed" and lists the failing
     families.
5. Otherwise the reviewer decides: `Support`, `Defeat`, or `NotVerified(ReviewerUnable | TermsGap)`.

**What the executor sees.** The brief adds one line: a larger set of independent sealed checks also runs after handoff,
and its contents are never shown. The brief also lists the process constraints verbatim (§7). Residuals carry public
details and sealed aggregates only, and the one repair is unchanged. The reviewer's receipt summary carries public
cases and sealed aggregates only, because reviewer residuals reach the executor.

**Outcome classes.** `NotVerified` carries one of `Infrastructure`, `InsufficientEvidence`, `ReviewerUnable`,
`TermsGap` or `NoHandoff`, in the verification event and the status record (new field, default empty). In the M0
report, a run whose executor turn failed with a provider or transport error is invalid (infrastructure) and excluded,
never scored zero. A candidate's own build failure stays a genuine zero.

## 7. Process constraints and terms gaps

- **Drafter.** Constraints on how the work is done or what must not be touched go to `process_constraints`, quoted
  verbatim through `resolve_span`. `out_of_scope` is only for elements the human excluded.
- **Brief.** A "Work constraints" block lists them verbatim.
- **Reviewer.** Process constraints count as covered, so they are never a terms gap and never by themselves a reason to
  answer cannot_judge. They are judged only through the artifact, for example an embedded copy of the reference
  program or a runtime dependency on it. We do not claim the environment enforces them; the current check environment
  does not.
- **Verdict and gaps are separate.** The parsed review becomes `{verdict: Support | Defeat | CannotJudge, terms_gap}`.
  A non-empty gap list still yields `NotVerified(TermsGap)`, but the verification event keeps the underlying verdict.

## 8. Settings

`settings.json` gains `evidence: {sealed_threshold_permille, min_sealed_qualified, min_success_permille}` with the
defaults above. They are copied into the policy at Issue, so they are hashed with it. θ_s is preregistered after
calibration (§9) and not changed afterwards.

## 9. Validation

**V1, offline replay (calibration; no executor reruns, same code).**
1. **Evidence.** For each of the 30 corpus-v1 tasks, the runner runs the real lane with `--stop-after-issue`: drafting,
   probing and Issue are real, then the executor turn is interrupted. This yields terms, public and sealed cases.
2. **Replay.** A thin command, `pro-contract-check` (ext crate bin over the exported `checks::run`), runs the pipeline
   for every labelled frozen subject of corpus-v1 and retest-v2 (judged and final; about 100 or more).
3. **Controls.**
   - Negative: `--candidate-is-reference`. The sealed failure rate must be about 0; otherwise the cases or the runner
     are wrong.
   - Positive: a constant-output candidate must fail nearly every qualified case.
4. **Calibration.** Split the 30 tasks by seed into 20 for calibration and 10 for holdout.
   - On calibration, pick the smallest θ_s whose supported candidates have at most 10% with a hidden pass rate below
     0.95, and report the support rate at that θ_s. Candidate values run from 800 to 1000 permille in steps of 10. If
     no value qualifies, the gate fails and V2 does not start.
   - On holdout, report the Spearman correlation between sealed and hidden pass rates, the missed-defect rate and the
     support rate.
   - Hidden pass rates come from `procontract_evaluation.pass_rate`, recomputed from archived `eval.json` for
     corpus-v1. The analysis script (`scripts/procontract_calibration.py`) only joins and counts.

**Gate to V2 (preregistered; numbers adjustable before V1 runs).**
- Negative-control false-alarm rate ≤ 1% of qualified sealed cases.
- Holdout Spearman ρ ≥ 0.6.
- Holdout missed-defect rate at the chosen θ_s ≤ 20%.

**V2, end to end.** A codex binary with the full lane runs an ON batch on 8–10 dev-pool instances outside corpus-v1. It
reports end-to-end health (infrastructure failures), the prospective missed-defect rate of supported, the
sealed-to-hidden correlation, and added wall time and tokens. Quality uplift is not measured here; detecting +5pp needs
about 37 pairs and belongs to the RSI stage.

## 10. Testing (TDD)

- Store: serde defaults, so old terms and policies parse; fixture and env limits.
- Workers: prober parse and validation; drafter process constraints; reviewer split of verdict and gaps; policy digests
  change.
- Case runner:
  - script tests (identical paths, base copy, fixtures, channel capture, hang breaker);
  - one docker integration test with a tiny fake reference and candidates covering every outcome (pass, fail per
    channel, unqualified via an unstable reference, timeout).
- `decide`: each rule and its order; residuals never contain sealed invocations.
- Automation: the fake `Ports` gains the prober; cover prober success, prober failure (empty sealed, then
  insufficient evidence), and the concurrent draft.
- Scripts: runner `--stop-after-issue`; calibration joins and counts; M0 report infrastructure exclusion.

## 11. Out of scope (later)

Seeded generator scripts and cross-run counterexample pools (OpenCode trajectory credit) come after V1/V2. Also later:
TTY and network peers; environment-enforced constraints (an execute-only reference with attestation); the RSI slice
over verifier policies, which uses this spec's offline corpus as its evaluator (R§9).

## 12. Risks

- **The sealed suite overfits to the documentation's surface** and misses hidden-test families. The holdout correlation
  measures this, and coverage tags make the gaps visible.
- **Qualification is too strict** (unstable stderr everywhere), so Q is too small and every verdict is insufficient
  evidence. The negative control and the Q distribution in V1 measure this.
- **Leakage.** Sealed contents never reach the executor (CODEX_HOME is not mounted; residuals carry aggregates).
  Family names are coarse by instruction.
- **Calibration n is small** (about 100 subjects over 30 tasks). θ_s is chosen on 20 tasks and reported on 10 held out,
  with task-clustered intervals.
