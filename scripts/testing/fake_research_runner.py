#!/usr/bin/env python3
"""Stands in for the benchmark runner in succession tests. Research runs edit the bundle as
FAKE_RESEARCH_MODE says: `better` adds a line the fake adapter rewards, `worse` one it punishes,
`null` changes nothing, `incomplete` delivers an experiment without its sections, `crash` fails
to prepare."""

import json
import os
import shutil
import sys
from pathlib import Path

SECTIONS = ["Deficiency", "Hypothesis", "Change", "Prediction", "Falsifier", "Risks"]


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
        if mode == "crash":
            return 1
        shutil.copytree(args["--workspace-from"], run_dir / "workspace")
        return 0
    workspace = run_dir / "workspace"
    executor = workspace / "policy" / "executor.md"
    if mode in ("better", "worse"):
        executor.write_text(executor.read_text() + f"{mode}\n")
    sections = SECTIONS if mode != "incomplete" else SECTIONS[:2]
    (workspace / "EXPERIMENT.md").write_text(
        "".join(f"## {name}\n{mode}\n" for name in sections)
    )
    (run_dir / "run.json").write_text(json.dumps({"turn_statuses": ["completed"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
