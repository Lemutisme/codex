"""Read-only guards and denominators for descriptive stream comparisons, not adoption evidence."""

import json

from procontract_succession import task_attempt_limit


def validate_comparison(stream, baseline) -> None:
    """Reject comparisons that change the committed experiment or its fixed control."""
    if task_attempt_limit(stream.terms) != task_attempt_limit(baseline.terms):
        raise ValueError("comparison identity differs: task_attempts")
    for name, default in (
        ("proposal_kind", "all"),
        ("confirmation_exposure_scope", "strict"),
    ):
        if stream.terms.get(name, default) != baseline.terms.get(name, default):
            raise ValueError(f"comparison identity differs: {name}")
    if stream.terms["stream"].get("mode", "explore") != baseline.terms["stream"].get(
        "mode", "explore"
    ):
        raise ValueError("comparison stream differs: mode")
    if stream.terms.get("canonical") != baseline.terms.get("canonical"):
        raise ValueError("comparison identity differs: canonical")
    if stream.terms["stream"].get("method_confirmation", "defer") != baseline.terms[
        "stream"
    ].get("method_confirmation", "defer"):
        raise ValueError("comparison stream differs: method_confirmation")
    for field in (
        "codex_sha256",
        "model",
        "effort",
        "task_prompt",
        "task_prompt_sha256",
        "programbench_head",
        "hf_revision",
        "research_image",
        "task_deadline_secs",
    ):
        if (
            field != "task_prompt_sha256"
            and field not in stream.terms
            or stream.terms.get(field) != baseline.terms.get(field)
        ):
            raise ValueError(f"comparison identity differs: {field}")
    for field in ("order", "batch"):
        if stream.terms["stream"][field] != baseline.terms["stream"][field]:
            raise ValueError(f"comparison stream differs: {field}")
    if stream.order() != baseline.order():
        raise ValueError("comparison exclusions differ")
    roots = []
    for host in (stream, baseline):
        versions = host.versions()
        initial = [
            vid
            for vid, m in versions.items()
            if m["lineage"]
            == {
                "parent": None,
                "proposed_by": "operator",
            }
        ]
        if len(initial) != 1:
            raise ValueError("comparison requires exactly one operator root")
        roots.append((initial[0], versions[initial[0]]))
    if roots[0] != roots[1]:
        raise ValueError("comparison operator roots differ")


def coverage(stream, baseline) -> dict:
    """Keep missing/invalid tasks in the full denominator, never just the valid intersection."""
    tasks = stream.order()
    assignments = [
        (t, b["version"]) for b in stream.batches() for t in b["tasks"] if t in tasks
    ]
    assigned = dict(assignments)
    if len(assigned) != len(assignments):
        raise ValueError("comparison stream assigns a task more than once")
    root = next(
        vid
        for vid, m in baseline.versions().items()
        if m["lineage"]
        == {
            "parent": None,
            "proposed_by": "operator",
        }
    )
    sides = {}
    for name, host, purpose, expected in (
        ("stream", stream, "stream", assigned),
        ("baseline", baseline, "baseline", dict.fromkeys(tasks, root)),
    ):
        results = {}
        for path in sorted((host.camp / "runs").glob(f"{purpose}-*/result.json")):
            result = json.loads(path.read_text())
            task = result["task"]
            if task not in tasks:
                continue  # Excluded instances remain recorded, but are not in this comparison.
            if task in results or result["version"] != expected.get(task):
                raise ValueError(f"ambiguous or unassigned {name} result: {task}")
            results[task] = result
        sides[name] = {
            "valid": [
                t for t in tasks if t in results and results[t]["validity"] == "valid"
            ],
            "invalid": [
                t for t in tasks if t in results and results[t]["validity"] != "valid"
            ],
            "missing": [t for t in tasks if t not in results],
        }
    pairs = set(sides["stream"]["valid"]) & set(sides["baseline"]["valid"])
    return {
        "status": "complete" if tasks and len(pairs) == len(tasks) else "incomplete",
        "total_tasks": len(tasks),
        "assigned_tasks": len(assigned),
        "valid_pairs": len(pairs),
        **sides,
        "interpretation": "Descriptive paired scores; adaptive tasks are not independent. "
        "The task bootstrap is not certification of learning or evidence for adoption.",
    }
