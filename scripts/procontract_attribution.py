#!/usr/bin/env python3
"""Attribution of progress and regression between a child version and its parent.

Raw outcomes say that a child scored differently; they do not say why. Attribution follows one
causal chain per task: what the policy changed -> whether behavior changed as intended -> whether
the criterion holder's outcome (the hidden tests) changed. This module supplies the last two links
as evidence: the executor's behavior statistics and the hidden-test flips. Whether the behavior
change is the one the hypothesis predicted is the research agent's judgment, not computed here.

Everything is family-agnostic and pure: a task family supplies its items (id -> passed) and its
oracle patterns (how the executor reaches the reference program)."""

import json
import re
from pathlib import Path

CALL_TYPES = ("function_call", "custom_tool_call")
VERIFY = re.compile(r"cargo test|pytest|\bdiff |\bcmp ")
PRODUCE = re.compile(r"apply_patch|\*\*\* Add File|\*\*\* Update File|cat >|\btee ")
BEHAVIOR_KEYS = ("tool_calls", "acquire", "verify", "produce", "tokens")
RATIO_BAND = (0.75, 1.33)
TOP_FAMILIES = 5


def family(item: str) -> str:
    """The dotted prefix of an id without its last component; an id without a dot is its own."""
    return item.rsplit(".", 1)[0] if "." in item else item


def flips(parent_items: dict[str, bool], child_items: dict[str, bool]) -> dict:
    """Items present in both whose outcome changed: progress is fail->pass, regress pass->fail."""
    shared = sorted(parent_items.keys() & child_items.keys())
    progress = [i for i in shared if not parent_items[i] and child_items[i]]
    regress = [i for i in shared if parent_items[i] and not child_items[i]]

    def by_family(ids: list[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in ids:
            counts[family(item)] = counts.get(family(item), 0) + 1
        return counts

    return {
        "progress": progress,
        "regress": regress,
        "progress_families": by_family(progress),
        "regress_families": by_family(regress),
    }


def rollouts(run_dir: Path, thread_id: str | None) -> list[Path]:
    """The executor's rollout files: those named for its thread. Workers' rollouts live beside
    them and are not the executor's trajectory, so an unknown thread yields no files."""
    paths = sorted((run_dir / "codex-home" / "sessions").rglob("*.jsonl"))
    return [path for path in paths if thread_id and thread_id in path.name]


def call_text(payload: dict) -> str:
    """The text of one tool call record: its arguments (function call) or input (custom tool)."""
    return str(payload.get("arguments") or payload.get("input") or "")


def reaches_oracle(text: str, oracle: list[re.Pattern]) -> bool:
    """Whether a tool call's text invokes the reference, by the task family's compiled patterns."""
    return any(pattern.search(text) for pattern in oracle)


def call_texts(path: Path) -> list[str]:
    texts = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            payload = json.loads(line).get("payload") or {}
        except json.JSONDecodeError:
            continue
        if payload.get("type") in CALL_TYPES:
            texts.append(call_text(payload))
    return texts


def uncached_tokens(usage: dict) -> int:
    """Input not served from cache plus output: the cost proxy. Total tokens are almost all cached
    input re-read on every turn and say little about work done."""
    return (
        (usage.get("input_tokens") or 0)
        - (usage.get("cached_input_tokens") or 0)
        + (usage.get("output_tokens") or 0)
    )


def behavior(run_dir: Path | str, oracle_patterns: list[str]) -> dict:
    """Statistics of the executor's trajectory. Missing files mean zeros. `acquire` counts tool
    calls containing at least one invocation of the reference; `tokens` is the executor's
    uncached tokens."""
    run_dir = Path(run_dir)
    try:
        summary = json.loads((run_dir / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        summary = {}
    status = summary.get("status") or {}
    executor = (summary.get("cost") or {}).get("executor") or {}
    oracle = [re.compile(pattern) for pattern in oracle_patterns]
    calls = [
        text
        for path in rollouts(
            run_dir, summary.get("thread_id") or status.get("thread_id")
        )
        for text in call_texts(path)
    ]
    return {
        "tool_calls": len(calls),
        "acquire": sum(reaches_oracle(t, oracle) for t in calls),
        "verify": sum(bool(VERIFY.search(t)) for t in calls),
        "produce": sum(bool(PRODUCE.search(t)) for t in calls),
        "tokens": uncached_tokens(executor),
        "turns": summary.get("turns_completed") or 0,
        "phase": status.get("phase"),
        "class": status.get("class"),
        "repairs_used": status.get("repairs_used") or 0,
    }


def ratio(child: float, parent: float) -> float | None:
    return child / parent if parent else None


def moved(child: float, parent: float) -> bool:
    """A count changed when its ratio leaves the band; from zero, any appearance is a change."""
    if not parent:
        return child > 0
    return not RATIO_BAND[0] <= child / parent <= RATIO_BAND[1]


def shown(child: float, parent: float) -> str:
    if not parent:
        return f"0→{child}" if child else "-"
    return f"{child / parent:.2f}"


def behavior_reading(parent: dict, child: dict) -> str:
    if not parent["tool_calls"] or not child["tool_calls"]:
        return "no behavior data"
    changed = any(moved(child[key], parent[key]) for key in BEHAVIOR_KEYS)
    return "behavior changed" if changed else "behavior unchanged"


def attribute(
    parent_result: dict,
    child_result: dict,
    parent_items: dict[str, bool],
    child_items: dict[str, bool],
    parent_behavior: dict,
    child_behavior: dict,
    noise: float,
) -> dict:
    """One row of the causal chain for one task."""
    delta = child_result["pass_rate"] - parent_result["pass_rate"]
    flipped = flips(parent_items, child_items)
    ratios = {
        key: shown(child_behavior[key], parent_behavior[key]) for key in BEHAVIOR_KEYS
    }
    outcome = (
        "progress"
        if delta >= noise
        else "regress"
        if delta <= -noise
        else "within noise"
    )
    reading = f"{behavior_reading(parent_behavior, child_behavior)} · outcome {outcome}"

    def top(counts: dict[str, int]) -> list[tuple[str, int]]:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_FAMILIES]

    return {
        "task": child_result["task"],
        "parent_rate": parent_result["pass_rate"],
        "child_rate": child_result["pass_rate"],
        "delta": delta,
        "progress": len(flipped["progress"]),
        "regress": len(flipped["regress"]),
        "net": len(flipped["progress"]) - len(flipped["regress"]),
        "top_progress": top(flipped["progress_families"]),
        "top_regress": top(flipped["regress_families"]),
        "ratios": ratios,
        "parent_behavior": parent_behavior,
        "child_behavior": child_behavior,
        "reading": reading,
    }


GUIDE = """Progress and regression are attributed along one causal chain, per task: what the policy \
changed (the child's Hypothesis), whether the executor's behavior changed (the ratios below, \
child over parent: tool calls, `acquire` = tool calls containing at least one invocation of the \
reference program, `verify` = test/diff runs, `produce` = file writes, uncached tokens = input \
not served from cache plus output; `0→n` means the parent had none), and whether the hidden-test \
outcome changed (progress is a test failing in the parent and passing in the child, regress the \
reverse, net their difference). A mean over tasks can hide opposite stories, so read each row. \
Judge from the behavior ratios and the Prediction whether the child did what it set out to do on \
that task; this view does not decide that for you.

Noise floor: {noise:.3f} ({source}). Single-test flips churn between runs even of the same \
policy; what is informative is flips concentrated in a family, and a family-wide regression can \
sit inside the pass-rate noise floor. `reading` has two parts. Behavior is `changed` when any \
count's ratio lies outside [0.75, 1.33] (or appears from zero), `unchanged` otherwise, and `no \
behavior data` when either run has no recorded tool calls. Outcome is `progress` when delta >= \
the floor, `regress` when delta <= -the floor, else `within noise`. The combinations mean:
- changed + progress: behavior changed (check its direction against the Prediction) and the \
outcome moved up.
- changed + regress: behavior changed (check its direction against the Prediction) and the \
outcome moved down.
- changed + within noise: behavior changed; any effect is below one run's noise floor, so cost \
is the visible effect.
- unchanged + anything: the policy change did not reach behavior on this task, so the outcome \
difference is trajectory noise, not the mechanism.
- no behavior data: the trajectory could not be read; nothing is claimed about behavior."""


def section(text: str, name: str) -> str:
    """The body of a `## name` section of an experiment record, or an empty string."""
    match = re.search(
        rf"^#+\s*{name}\s*$(.*?)(?=^#+\s|\Z)", text, re.MULTILINE | re.DOTALL | re.I
    )
    return match.group(1).strip() if match else ""


def fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def families(pairs: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in pairs) or "none"


def render(
    child: str,
    parent: str,
    rows: list[dict],
    experiment_text: str,
    noise: float,
    noise_source: str,
) -> str:
    out = [
        f"# Attribution: {child[:12]} against its parent {parent[:12]}",
        "",
        GUIDE.format(noise=noise, source=noise_source),
        "",
    ]
    for name in ("Hypothesis", "Prediction"):
        if body := section(experiment_text, name):
            out += [f"## Child's {name}", "", body, ""]
    out += [
        "## Per task",
        "",
        "| task | parent | child | delta | progress | regress | net | tool calls | acquire "
        "| verify | produce | uncached tokens | reading |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        r = row["ratios"]
        out.append(
            f"| {row['task']} | {row['parent_rate']:.3f} | {row['child_rate']:.3f} "
            f"| {row['delta']:+.3f} | {row['progress']} | {row['regress']} "
            f"| {row['net']:+d} | {r['tool_calls']} | {r['acquire']} | {r['verify']} "
            f"| {r['produce']} | {r['tokens']} | {row['reading']} |"
        )
    out += ["", "## Behavior and test families per task", ""]
    for row in rows:
        p, c = row["parent_behavior"], row["child_behavior"]
        out += [
            f"### {row['task']}",
            "",
            f"- counts parent -> child: tool calls {p['tool_calls']} -> {c['tool_calls']}, "
            f"acquire {p['acquire']} -> {c['acquire']}, verify {p['verify']} -> {c['verify']}, "
            f"produce {p['produce']} -> {c['produce']}, uncached tokens {p['tokens']} -> {c['tokens']}",
            f"- lane: {p['phase']}/{p['repairs_used']} repairs -> "
            f"{c['phase']}/{c['repairs_used']} repairs",
            f"- top progress families: {families(row['top_progress'])}",
            f"- top regression families: {families(row['top_regress'])}",
            "",
        ]
    if rows:
        mean_delta = sum(row["delta"] for row in rows) / len(rows)
        tokens = ratio(
            sum(row["child_behavior"]["tokens"] for row in rows),
            sum(row["parent_behavior"]["tokens"] for row in rows),
        )
        out.append(
            f"Totals: mean delta {mean_delta:+.3f} over {len(rows)} tasks; "
            f"executor uncached-token ratio {fmt(tokens)}."
        )
    return "\n".join(out) + "\n"
