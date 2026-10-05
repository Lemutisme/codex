#!/usr/bin/env python3
"""Per-task outcome matrix across every stored run of one task (tasks/<task>/outcomes.md).

A pass rate says how much passed, not which tests. The matrix keeps the items: the floor (failed by
every stored run, so no version has reached it), the always-passing items, and the sensitive set
(items whose outcome differs between runs). Runs of one twin (same behavior, different draw) show
the task's own noise; flips along a lineage edge mean something only when read against it.

Pure and family-agnostic: runs arrive as per-item outcomes, the host decides which runs to pass."""

from procontract_attribution import TOP_FAMILIES, family, flips

MAX_ROWS = 25

GUIDE = """Read this for one task across all its stored runs. The floor is the set of items \
failed by every stored run: no version has reached it, so ask why it is unreached (an input the \
executor never tried, a behavior no policy has produced) before asking how to improve a score. \
The always-passing items carry no signal about versions. The sensitive items are those whose \
outcome differs between runs, which is where versions and chance differ. Replicates are runs of \
the same twin (same behavior): their pass-rate spread and the items they disagree on are this \
task's noise, and an edge's flips must be read against it; a flip count no larger than the \
replicate disagreement is not evidence. Items missing from some run are left out of the floor, \
always and sensitive sets but still count in that run's pass rate."""


def pass_rate(outcomes: dict) -> float:
    return sum(o["passed"] for o in outcomes.values()) / len(outcomes) if outcomes else 0.0


def passed_map(run: dict) -> dict[str, bool]:
    return {item: bool(o["passed"]) for item, o in run["outcomes"].items()}


def count_families(ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in ids:
        counts[family(item)] = counts.get(family(item), 0) + 1
    return counts


def classify(runs: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """(common, floor, always, sensitive): ids present in every run and how they split."""
    if not runs:
        return [], [], [], []
    common = sorted(set.intersection(*(set(r["outcomes"]) for r in runs)))
    floor, always, sensitive = [], [], []
    for item in common:
        votes = {bool(r["outcomes"][item]["passed"]) for r in runs}
        (sensitive if len(votes) > 1 else always if votes == {True} else floor).append(item)
    return common, floor, always, sensitive


def family_rows(runs: list[dict], common, floor, always, sensitive) -> list[dict]:
    rows = []
    for name in sorted({family(i) for i in common}):
        members = [i for i in common if family(i) == name]
        rows.append(
            {
                "family": name,
                "n": len(members),
                "floor": sum(i in floor for i in members),
                "always": sum(i in always for i in members),
                "sensitive": sum(i in sensitive for i in members),
                "passed": {
                    r["name"]: sum(bool(r["outcomes"][i]["passed"]) for i in members)
                    for r in runs
                },
            }
        )
    return rows


def replicate_rows(runs: list[dict]) -> list[dict]:
    rows = []
    for twin in dict.fromkeys(r["twin"] for r in runs):
        group = [r for r in runs if r["twin"] == twin]
        if len(group) < 2:
            continue
        rates = [pass_rate(r["outcomes"]) for r in group]
        shared = set.intersection(*(set(r["outcomes"]) for r in group))
        disagree = sorted(
            i for i in shared if len({bool(r["outcomes"][i]["passed"]) for r in group}) > 1
        )
        rows.append(
            {
                "twin": twin,
                "runs": [r["name"] for r in group],
                "pass_rates": rates,
                "spread": max(rates) - min(rates),
                "disagree": disagree,
            }
        )
    return rows


def edge_rows(runs: list[dict]) -> list[dict]:
    """Each run paired with every run of its parent twin (replicates give several edges)."""
    rows = []
    for child in runs:
        if child["parent"] is None:
            continue
        for parent in (r for r in runs if r["twin"] == child["parent"]):
            f = flips(passed_map(parent), passed_map(child))
            rows.append(
                {
                    "child": child["name"],
                    "parent": parent["name"],
                    "progress": f["progress"],
                    "regress": f["regress"],
                    "by_family": {
                        "progress": f["progress_families"],
                        "regress": f["regress_families"],
                    },
                }
            )
    return rows


def matrix(runs: list[dict]) -> dict:
    """The outcome matrix of one task over all its stored runs."""
    common, floor, always, sensitive = classify(runs)
    return {
        "runs": [
            {
                "name": r["name"],
                "version": r["version"],
                "pass_rate": pass_rate(r["outcomes"]),
                "items": len(r["outcomes"]),
            }
            for r in runs
        ],
        "items": len(common),
        "floor": floor,
        "always": always,
        "sensitive": sensitive,
        "families": family_rows(runs, common, floor, always, sensitive),
        "replicates": replicate_rows(runs),
        "edges": edge_rows(runs),
    }


def capped(rows: list[str], noun: str) -> list[str]:
    """Table rows bounded to MAX_ROWS, with the omission stated."""
    if len(rows) <= MAX_ROWS:
        return rows
    return rows[:MAX_ROWS] + ["", f"{len(rows) - MAX_ROWS} more {noun} omitted."]


def top(counts: dict[str, int]) -> str:
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_FAMILIES]
    return ", ".join(f"{name} ({n})" for name, n in ranked) or "none"


def render(task: str, m: dict) -> str:
    runs = ", ".join(f"{r['name']} {r['pass_rate']:.3f} ({r['items']} items)" for r in m["runs"])
    out = [
        f"# Outcomes: {task}",
        "",
        GUIDE,
        "",
        "## Summary",
        "",
        f"- runs: {len(m['runs'])}" + (f" ({runs})" if runs else ""),
        f"- items present in every run: {m['items']}",
        f"- floor (failed by every run): {len(m['floor'])}",
        f"- always passing: {len(m['always'])}",
        f"- sensitive: {len(m['sensitive'])}",
        "",
        "## Families",
        "",
    ]
    ordered = sorted(m["families"], key=lambda f: (-f["sensitive"], -f["floor"], f["family"]))
    names = [r["name"] for r in m["runs"]]
    rows = [
        f"| {f['family']} | {f['n']} | {f['floor']} | {f['always']} | {f['sensitive']} | "
        + " | ".join(str(f["passed"].get(n, "-")) for n in names)
        + " |"
        for f in ordered
    ]
    out += [
        "Sorted by sensitive, then floor; the last columns are passes per run.",
        "",
        "| family | n | floor | always | sensitive | " + " | ".join(names) + " |",
        "|---|---|---|---|---|" + "---|" * len(names),
    ]
    out += capped(rows, "families")
    out += ["", "## Replicates", ""]
    if m["replicates"]:
        out += [
            "| twin | runs | pass rates | spread | disagree |",
            "|---|---|---|---|---|",
        ]
        out += capped(
            [
                f"| {r['twin']} | {', '.join(r['runs'])} "
                f"| {', '.join(f'{p:.3f}' for p in r['pass_rates'])} "
                f"| {r['spread']:.3f} | {len(r['disagree'])} |"
                for r in m["replicates"]
            ],
            "replicate groups",
        )
    else:
        out.append("No twin has two runs on this task: the noise here is unmeasured.")
    out += ["", "## Edges", ""]
    if m["edges"]:
        out += [
            "| child | parent | progress | regress | top progress | top regress |",
            "|---|---|---|---|---|---|",
        ]
        out += capped(
            [
                f"| {e['child']} | {e['parent']} | {len(e['progress'])} | {len(e['regress'])} "
                f"| {top(e['by_family']['progress'])} | {top(e['by_family']['regress'])} |"
                for e in m["edges"]
            ],
            "edges",
        )
    else:
        out.append("No run has a parent among the stored runs.")
    return "\n".join(out) + "\n"
