#!/usr/bin/env python3
"""Stands in for procontract_benchmark_runner.py in batch tests."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    command = sys.argv[1]
    args = dict(zip(sys.argv[2::2], sys.argv[3::2]))
    run_dir = Path(args["--run-dir"])
    if command == "prepare":
        if os.environ.get("FAKE_RUNNER_FAIL_PREPARE") == args["--instance"]:
            print("image pull failed", file=sys.stderr)
            return 1
        (run_dir / "workspace").mkdir(parents=True, exist_ok=True)
        return 0
    marker = os.environ.get("FAKE_RUNNER_CRASH_ONCE")
    if marker and not Path(marker).exists():
        Path(marker).write_text("crashed")
        return 1
    (run_dir / "run.json").write_text(
        json.dumps({"turns_completed": 1, "turn_statuses": ["completed"]})
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
