#!/usr/bin/env python3
"""Deterministic peer for inheritance tests, not a model or a quality evaluator."""

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import procontract_harness_program as harness  # noqa: E402
from procontract_delivery_budget import DeliveryBudget  # noqa: E402
from testing import fake_research_runner as fake  # noqa: E402

METHODS = ("research.md", "analyst.md", "challenger.md")


def write_json(path, value):
    path.write_text(json.dumps(value))


def stage(text):
    return int(re.search(r"^PEER_STAGE=(\d+)$", text, re.MULTILINE).group(1))


def activation(bundle, instructions):
    text = (bundle / instructions).read_text()
    budget = DeliveryBudget(
        deadline_secs=100, reserve_secs=25, program=harness.load(bundle)
    )
    turns = SimpleNamespace(
        active=True, thread_id="peer-thread", turn_id="peer-turn", completed=0
    )
    calls = []

    def request(method, params, handle, timeout):
        if method != "turn/steer" or params["expectedTurnId"] != turns.turn_id:
            raise ValueError("unexpected controller request")
        calls.append(remaining)
        return {"turnId": turns.turn_id}

    for remaining in (15, 10, 5):
        budget.maybe_steer(
            SimpleNamespace(request=request),
            turns,
            {"phase": "working", "repairs_used": 0},
            lambda _: None,
            elapsed_secs=100 - remaining,
        )
    return {
        "instructions": instructions,
        "instruction_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "method_stage": stage(text),
        "steer_at_remaining": calls[0] if calls else None,
        "steer_calls": len(calls),
        "delivery_budget": budget.summary(),
        "harness_program": budget.activation,
    }


def prepare(run_dir, bundle, instructions, source=None):
    run_dir.mkdir(parents=True, exist_ok=True)
    if source is None:
        (run_dir / "workspace").mkdir()
    else:
        shutil.copytree(source, run_dir / "workspace")
    shutil.copytree(bundle, run_dir / "policy")
    program = harness.load(run_dir / "policy")
    write_json(
        run_dir / "manifest.json",
        {
            "instructions": instructions,
            "harness_program": {
                "sha256": program.digest,
                "interpreter": program.interpreter,
            },
        },
    )


def run(run_dir, intervention="mixed"):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    role = manifest["instructions"]
    receipt = activation(run_dir / "policy", role)
    workspace = run_dir / "workspace"
    if role == "research.md":
        feedback = [
            json.loads(path.read_text())
            for path in sorted((workspace / "archive" / "runs").glob("*/summary.json"))
        ]
        if not feedback or any(
            row.get("validity") != "valid"
            or type(row.get("pass_rate")) not in (int, float)
            for row in feedback
        ):
            raise ValueError("research requires scored feedback")
        receipt["feedback"] = [
            {"task": row["task"], "pass_rate": row["pass_rate"]} for row in feedback
        ]
        fake.research(workspace, "better" if intervention == "execution" else "method")
        if intervention == "execution":
            # Guarded task confirmation may certify P/H, not simultaneous method edits.
            successor = json.loads(harness.load(run_dir / "policy").source)["when"][
                "remaining_fraction_lte"
            ][0]
        else:
            successor = receipt["method_stage"] + 1
            for name in METHODS:
                path = workspace / "policy" / name
                path.write_text(
                    re.sub(
                        r"^PEER_STAGE=\d+$",
                        f"PEER_STAGE={successor}",
                        path.read_text(),
                        flags=re.MULTILINE,
                    )
                )
        write_json(
            workspace / "policy" / harness.PROGRAM_FILE,
            {"schema": 1, "when": {"remaining_fraction_lte": [successor + 1, 20]}},
        )
        receipt["produced_stage"] = successor
    elif role == "analyst.md":
        fake.analyst(workspace)
    elif role == "challenger.md":
        fake.challenger(workspace)
    else:
        raise ValueError(f"unsupported peer role: {role}")
    write_json(run_dir / "run.json", {"turn_statuses": ["completed"], **receipt})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--instructions")
    parser.add_argument("--workspace-from", type=Path)
    parser.add_argument(
        "--intervention", choices=("mixed", "execution"), default="mixed"
    )
    args, _ = parser.parse_known_args()
    if args.command == "prepare":
        prepare(args.run_dir, args.policy, args.instructions, args.workspace_from)
    else:
        run(args.run_dir, args.intervention)


if __name__ == "__main__":
    main()
