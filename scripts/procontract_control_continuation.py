"""New OFF-only scope spending original unlaunched slots, never reopening the old runner."""

import contextlib
import json
from pathlib import Path
import sqlite3

import procontract_study_budget as budget
from procontract_credential_gate import PROFILE


def remaining(path, expected):
    import procontract_online_plan as plans

    parent = plans.verify(path, expected)
    root = Path(parent["root"])
    terminal = root / "terminal.json"
    if (
        parent.get("continuation")
        or parent["arms"] != ["vanilla"]
        or json.loads(terminal.read_text())["status"] != "stopped"
    ):
        raise ValueError("continuation requires a stopped, original OFF control")
    database = root / "budget.sqlite"
    budget.status(database, expected, parent["limits"])
    with contextlib.closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    ) as db:
        used = {key for (key,) in db.execute("SELECT key FROM reservations")}
    if not used <= {f"{i}-vanilla" for i in range(len(parent["tasks"]))}:
        raise ValueError("parent allowance has an unrecognized claim")
    for key in used:
        run = root / "runs" / key
        summary = json.loads((run / "run.json").read_text())
        exited = summary.get("native_process_exit") or {}
        if (
            exited.get("status") != "exited"
            or type(exited.get("returncode")) is not int
            or exited["returncode"] != 0
            or not (run / "online-trace-cleanup.json").is_file()
        ):
            raise ValueError("parent process lifetime or cleanup is unresolved")
    indices = [i for i in range(len(parent["tasks"])) if f"{i}-vanilla" not in used]
    if not indices:
        raise ValueError("no unlaunched task allowance remains")
    return parent, {
        "parent_plan": str(path.resolve()),
        "parent_sha256": expected,
        "terminal_sha256": plans.sha(terminal),
        "indices": indices,
        "scope": "explicitly authorized unlaunched slots; no refund, replacement or old-run restart",
    }


def ledger(plan, digest):
    descriptor = plan.get("continuation")
    if descriptor is None:
        return Path(plan["root"]) / "budget.sqlite", digest, plan["limits"]
    import procontract_online_plan as plans

    parent = plans.verify(Path(descriptor["parent_plan"]), descriptor["parent_sha256"])
    indices = descriptor["indices"]
    terminal = Path(parent["root"]) / "terminal.json"
    if (
        parent.get("continuation")
        or parent["arms"] != ["vanilla"]
        or plan["arms"] != ["vanilla"]
        or plan.get("credential_preflight") != PROFILE
        or not indices
        or any(type(i) is not int or not 0 <= i < len(parent["tasks"]) for i in indices)
        or indices != sorted(set(indices))
        or plan["tasks"] != [parent["tasks"][i] for i in indices]
        or plan["limits"]
        != {
            "task_launches": len(indices),
            "learning_launches": 0,
            "allocated_seconds": len(indices) * parent["episode_secs"],
        }
        or any(
            plan[k] != parent[k]
            for k in (
                "model",
                "effort",
                "binary",
                "seed",
                "provider",
                "episode_secs",
                "inference_secs",
                "grading_secs",
                "research_secs",
            )
        )
        or plans.sha(Path(plan["prompt"])) != plans.sha(Path(parent["prompt"]))
        or plans.sha(terminal) != descriptor["terminal_sha256"]
    ):
        raise ValueError("continuation changes the original control or allowance")
    database = Path(parent["root"]) / "budget.sqlite"
    budget.status(database, descriptor["parent_sha256"], parent["limits"])
    return database, descriptor["parent_sha256"], parent["limits"]
