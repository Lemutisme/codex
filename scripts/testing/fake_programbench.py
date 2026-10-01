#!/usr/bin/env python3
"""A stand-in for `programbench eval` with scripted outcomes.

Set FAKE_PROGRAMBENCH_PLAN to a JSON file
`{"<instance>": [{"score": "99", "solved": false, "branch_errors": [], "crash": false}, ...]}`.
Attempt n uses entry n; the last entry repeats. Each run records the submitted members into
`<dir>/<instance>/fake-seen.json`.
"""

import json
import os
import sys
import tarfile
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] != "eval":
        print("fake_programbench supports only `eval`", file=sys.stderr)
        return 2
    eval_dir = Path(args[1])
    instance = args[args.index("--filter") + 1].strip("^$").replace("\\.", ".")
    plan = json.loads(Path(os.environ["FAKE_PROGRAMBENCH_PLAN"]).read_text())
    counter = Path(os.environ["FAKE_PROGRAMBENCH_PLAN"] + f".{instance}.count")
    attempt = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(attempt + 1))
    steps = plan[instance]
    step = steps[min(attempt, len(steps) - 1)]
    if step.get("crash"):
        print("evaluator crashed", file=sys.stderr)
        return 1
    instance_dir = eval_dir / instance
    with tarfile.open(instance_dir / "submission.tar.gz") as archive:
        seen = {
            member.name: archive.extractfile(member).read().decode(errors="replace")
            for member in archive.getmembers()
            if member.isfile()
        }
    (instance_dir / "fake-seen.json").write_text(json.dumps(seen))
    resolved = 10 if step["solved"] else 9
    (instance_dir / f"{instance}.eval.json").write_text(
        json.dumps(
            {
                "test_results": [
                    {"name": f"t{i}", "status": "passed" if i < resolved else "failure"}
                    for i in range(10)
                ],
                "test_branch_errors": {
                    branch: "results_read_failed" for branch in step["branch_errors"]
                },
            }
        )
    )
    score = "✅" if step["solved"] else step["score"]
    print(f" {instance}    {score}  fake")
    return 0


if __name__ == "__main__":
    sys.exit(main())
