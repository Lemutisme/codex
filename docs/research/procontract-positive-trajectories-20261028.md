# What is useful in trajectories that score above the Vals reference

2026-10-28. Read-only analysis of five stopped ProContract attempts. No solver was
resumed and no scoring or runtime policy changed. These five add to the previous
fifteen inspected cases; the selection is purposeful, not a prevalence estimate.

## Comparison scope

The comparator is the frozen Vals `openai/gpt-5.6-luna` / max snapshot retrieved on
2026-10-25. Its local assets match their recorded SHA-256 values. They contain
model/task metrics, not full execution traces or per-task source histories. The
old public asset URLs now return 404; the original local copies remain available
and verified. This analysis does not infer that Vals lacks particular capabilities
or that a zero result was caused by a particular implementation failure.

Our new cohort permits unlimited model requests within one shared six-hour task
allocation. Vals' request-limited reference is therefore not matched compute.
The paired score differences are observations; the useful mechanisms below are
established from our own source, tools and retained assessments. No step-by-step
comparison against an unavailable Vals trajectory is claimed.

Later qualification: the [2026-10-31 synthesis](procontract-root-cause-synthesis-20261031.md)
finds a default grader-network limitation affecting public-service test paths.
Evaluation conditions therefore also need verification before causal comparison
with Vals. The positive local mechanisms and raw scores below are retained; their
aggregate score gaps are not isolated measurements of a strategy effect.

| Instance | ProContract | Vals Luna/max | Difference, pp | Our requests / minutes |
|---|---:|---:|---:|---:|
| pingu | 360/378 = 95.24% | 52.91% | +42.33 | 152 / 19.40 |
| shellharden | 1020/1095 = 93.15% | 54.43% | +38.72 | 2715 / 359.84 |
| loop | 709/710 = 99.86% | 84.23% | +15.63 | 2638 / 359.85 |
| miniserve | 293/304 = 96.38% | 86.18% | +10.20 | 326 / 44.48 |
| json-tui | 717/755 = 94.97% | 0.00% | +94.97 | 2471 / 359.82 |

The zero Vals result for json-tui is shown as published but is not used to infer
its failure mechanism. Pingu and miniserve are useful short-run controls: neither
uses more than 1000 calls, so their local success did not require crossing the
removed request ceiling. That does not make them matched-cost causal controls.

Artifacts: `/data/ProContract/procontract-positive-trajectories-20261028/` contains
`comparison.json`, `episodes-evidence.json`, `trace-evidence.json`,
`commentary-index.json`, `pty-input-control.json`, and `analyze.py`. The comparison
binds scores to original canonical results and Vals source identities. Trace items
retain session path, line and hash. Agent commentary is identified as a statement;
claims below are corroborated where indicated.

## 1. Pingu: build a usable mechanism early

The first executor maps parser behavior, finite/continuous counts, DNS-initialization
versus runtime errors, output framing and interrupt behavior. The final independently
authored Python source uses real OS socket interfaces, including IPv4/IPv6 ICMP
datagram paths, send/receive handling and SIGINT handling. This gives its normal
ping path a working implementation, with CLI and presentation behavior around it.

The canonical ping test group passes 34/36; the final total is 360/378. The entire
attempt uses 152 requests and 19.4 minutes, with no continuation selector decisions.
Its publication later hits the known inspection-finalization defect; that does not
erase the strong artifact already produced. The score cannot be credited to a
large succession/review loop that did not occur in this case.

Useful method: discover the key state distinctions and use the available primitives
to make the central behavior real. In a connected real-world task, the appropriate
primitive may instead be an existing library or service. The clean-room requirement
belongs to this benchmark; general strategy need not demand reimplementation.

## 2. Shellharden: a representation that supports families of repairs

The implementation preserves source spans, lexes shell words, tracks quotation and
nested substitutions, and separates transformation from rendering. The retained
`probe_cases.py` and `diff_probe.py` exercise input text across output modes,
comparing exit status, stdout and stderr.

A concrete sequence:

- At 05:06:36, the 94-case transform run reports a mismatch for
  `echo "a"$x"b"`: the reference and candidate place quoting boundaries differently.
- At 05:09:31, the transform mode reaches DONE with no differences, while syntax
  mode still reports coloring/span differences. The work distinguishes these layers
  instead of treating all mismatches as one undifferentiated failure.
- At 09:46:08, the retained tool output shows the 94-case corpus completing across
  seven invocations with no reported differences.
- At 09:48–09:49, additional nested-substitution/backtick probes expose new edges
  outside that corpus; changes to shared scanning paths retain passing transform
  and syntax controls.

This is an example of cumulative local knowledge: a reusable probe corpus and a
coherent parser permit a repair to cover related inputs while preserving established
behavior. The matrix's scope is the supplied stdin/mode observations, not all file
or shell-language behavior. Official variable tests pass 93/93 and string tests
63/67; the overall result remains 93.15%.

The internal sealed tally barely changes, 59/64 to 60/64, while many newly discovered
local defects are repaired. A single internal aggregate is an incomplete account
of progress. We have not externally graded each intermediate snapshot, so no exact
share of the +38.72 pp difference is assigned to these episodes.

## 3. Loop: model state and interactions, then repair precedence

The executor investigates iteration order, shell execution, output stream merging,
COUNT/ITEM values, combined stdin/--for inputs, stop-condition ordering and timing.
These become explicit implementation behavior rather than a set of printed examples.
For example, `_read_items` constructs the input stream, while the runtime chooses
the current item and retains its last value when the requested count exceeds the
stream length.

Early tool output at 14:50:39 shows many controls passing but a concrete combined
stdin/--for mismatch: reference output advances into the stdin items while the
candidate repeats the last --for item. Subsequent work addresses input semantics
and option precedence. Later probes isolate the difference between a repeated
option and a missing value, including cases where an earlier malformed duration,
regex or time value must keep its own diagnostic precedence.

Retained full assessments move from 64/67 to 65/67, 66/67 and finally 67/67 qualified
internal sealed comparisons. The canonical outcome is 709/710. The termination
group passes 55/55 and the counters group 41/41. These observations support the
value of a coherent execution model plus targeted interaction tests.

This trajectory also spends additional reviews after reaching 67/67 while broad
coverage/history gaps remain. The useful repair loop and the later repetition are
both real. A high final score does not establish that every continuation was useful
or that more reviews necessarily improve the result.

## 4. Miniserve: preserve working code and extend the actual HTTP interface

The first executor builds an independent standard-library HTTP server with file
serving and broad route/option structure. Handoff is followed by selected successor
work in the retained workspace. The recorded follow-up identifies and repairs
archive framing/member layout, upload/delete redirects, conditional file responses
and method-specific error behavior, including Python's default 501 versus the
reference's 404 path for unsupported methods.

The retained final source contains actual GET/HEAD/POST/OPTIONS/WebDAV handlers,
conditional request and Range handling, not only command-line responses. Tool
records and commentary around 08:35–08:41 cover local HTTP regression work and
clean exported-source builds. The final progress receipt records 29/29 public
checks passing; the canonical result is 293/304 in 44.48 minutes and 326 requests.

Useful method: an initial usable artifact remains the basis for further work, and
new investigation reaches protocol/file effects beyond the easy CLI surface.
The harness's observable contribution is retaining the workspace, reference and
selected continuation path. The method and implementation choices remain strategy
and task-solving work, not kernel workflow rules. No root-failure recovery is
claimed for this particular trajectory; it follows a completed handoff.

## 5. Json-tui: one shared interaction defect explains many symptoms

The initial source calls `tty.setraw(input_fd)`, whose default transition flushes
pending input. The terminal checks queue a quit key immediately. The first retained
assessment records timeout/exit 137 for file-object while the reference exits zero;
it has seventeen recorded public failures and an incomplete overall check run.

After reading the evidence, the implementation changes to an explicit
`termios.tcsetattr(..., TCSANOW, raw)` transition that preserves queued input.
The next complete assessment passes the same file-object check. Other issues,
including stdin/terminal routing and rendering, are then investigated. Publication
three passes stdin-object as well. Later observations reach 29 passing public
cases with one unqualified case, and the final canonical result is 717/755.

A minimal host PTY control corroborates the mechanism: queue q before setup,
then default setraw leaves no input available, whereas TCSANOW preserves byte 0x71.
This is a mechanism control, not a new benchmark run or a counterfactual score.
Because the first check run is incomplete, its aggregate is not treated as a
matched complete-suite before/after percentage.

Useful method: use actual invocation conditions to replace an initial explanation
with a better one, then fix the shared state transition and replay the affected
case. Late startup-window heuristics in the same trajectory remain a narrower,
condition-sensitive part of the implementation; this analysis does not promote
those constants into a general method.

## What these successes support

The strongest common pattern is not a particular number of reviews or successors.
It is a working mechanism, an observation that exposes a real difference, a change
to the underlying rule/state transition, and reusable checks that preserve prior
gains. Some tasks reach strong results quickly; others use sustained iterations.
Long-horizon capability benefits when later work starts with the knowledge and
tools already acquired instead of restarting from a handoff narrative.

For ProContract's evolution, these observations strengthen existing directions:

- **S1:** choose an informative method and a useful next action, including capability
  acquisition; a working socket/server/PTY experiment can matter more than another
  broad judgment.
- **S2:** choose a representation that expresses the relevant behavior and use
  neighboring cases/conditions to test a rule rather than memorizing one output.
- **S3:** retain and reuse runnable probes, current source and observed conditions;
  measure what actually changed before deciding on further work.
- **H1–H3:** preserve operation continuity, working observation capabilities and
  accessible state/evidence. They enable these methods without prescribing them.

These are method-level and supporting-capability observations. The small kernel
retains responsibility, authority and evidence relations; it should not absorb
shell parsing, terminal timing, a required review sequence or an empirical test count.

To isolate causal performance gains later, compare ProContract variants with the
same qualified harness/resources while changing a specific method/context choice,
then evaluate new E2E tasks. Vals' published score gap alone cannot perform that
attribution. Existing strong results remain strong while that research is pending.
