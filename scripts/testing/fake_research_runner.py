#!/usr/bin/env python3
"""Stands in for the benchmark runner in succession tests, dispatching on the run's --instructions.

research.md: edits the bundle as FAKE_RESEARCH_MODE says: `better` adds a line the fake adapter
rewards, `worse` one it punishes, `method` changes only research.md, `leak` writes a development
task's name into executor.md, `delete` deletes prober.md, `null` changes nothing, `incomplete`
delivers an experiment without its sections, `crash` fails to prepare.

analyst.md: writes ANALYSIS.md, appends a line to knowledge/mechanisms.md and, when the archive
README names a pending experiment, a verdict.json whose signature is FAKE_SIGNATURE (default
`present`). FAKE_ANALYSIS=fail delivers nothing; FAKE_ANALYSIS=silent ends the run without run.json.

challenger.md: writes CHALLENGE.md. FAKE_CHALLENGE=fail delivers nothing; FAKE_CHALLENGE=crash fails
to prepare.

Every run appends its instructions file name to the file FAKE_LOG, when that is set."""

import json
import os
import re
import shutil
import sys
from pathlib import Path

SECTIONS = [
    "Mechanism",
    "Hypothesis",
    "Change",
    "Signature",
    "Prediction",
    "Falsifier",
    "Risks",
]
# A token of the development task acme__widget.* in the tests.
LEAK = "widget"


def research(workspace: Path, mode: str) -> None:
    executor = workspace / "policy" / "executor.md"
    if mode in ("better", "worse"):
        executor.write_text(executor.read_text() + f"{mode}\n")
    if mode == "leak":
        executor.write_text(executor.read_text() + f"Behave as {LEAK} does.\n")
    if mode == "delete":
        (workspace / "policy" / "prober.md").unlink()
    if mode == "method":
        text = workspace / "policy" / "research.md"
        text.write_text(text.read_text() + "Count distinct tasks.\n")
    sections = SECTIONS if mode != "incomplete" else SECTIONS[:2]
    (workspace / "EXPERIMENT.md").write_text(
        "".join(f"## {name}\n{mode}\n" for name in sections)
    )


def analyst(workspace: Path) -> None:
    if os.environ.get("FAKE_ANALYSIS") == "fail":
        return
    (workspace / "ANALYSIS.md").write_text("The analysis.\n")
    knowledge = workspace / "knowledge"
    knowledge.mkdir(exist_ok=True)
    with (knowledge / "mechanisms.md").open("a") as handle:
        handle.write("- a mechanism the analyst noted\n")
    readme = (workspace / "archive" / "README.md").read_text()
    if found := re.search(r"^Pending experiment: (\w+)$", readme, re.MULTILINE):
        (workspace / "verdict.json").write_text(
            json.dumps(
                {
                    "experiment": found.group(1),
                    "signature": os.environ.get("FAKE_SIGNATURE", "present"),
                    "outcome": "moved",
                    "reading": "counted",
                }
            )
        )


def challenger(workspace: Path) -> None:
    if os.environ.get("FAKE_CHALLENGE") != "fail":
        (workspace / "CHALLENGE.md").write_text("The challenge.\n")


def main() -> int:
    command, rest = sys.argv[1], sys.argv[2:]
    args = {}
    index = 0
    while index < len(rest):
        if rest[index] == "--no-reference":
            index += 1
            continue
        args[rest[index]] = rest[index + 1]
        index += 2
    run_dir = Path(args["--run-dir"])
    mode = os.environ.get("FAKE_RESEARCH_MODE", "better")
    if command == "prepare":
        instructions = args["--instructions"]
        if (instructions, mode) == ("research.md", "crash") or (
            instructions,
            os.environ.get("FAKE_CHALLENGE"),
        ) == ("challenger.md", "crash"):
            return 1
        shutil.copytree(args["--workspace-from"], run_dir / "workspace")
        (run_dir / "instructions").write_text(instructions)
        return 0
    instructions = (run_dir / "instructions").read_text()
    if os.environ.get("FAKE_LOG"):
        with open(os.environ["FAKE_LOG"], "a") as log:
            log.write(instructions + "\n")
    workspace = run_dir / "workspace"
    if instructions == "research.md":
        research(workspace, mode)
    elif instructions == "analyst.md":
        if os.environ.get("FAKE_ANALYSIS") == "silent":
            return 1
        analyst(workspace)
    else:
        challenger(workspace)
    (run_dir / "run.json").write_text(json.dumps({"turn_statuses": ["completed"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
