#!/usr/bin/env python3
"""Deterministic updater peer: exercises method inheritance, never a model or real gain."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

METHODS = ("research.md", "analyst.md", "challenger.md")
SECTIONS = (
    "Mechanism",
    "Hypothesis",
    "Change",
    "Signature",
    "Prediction",
    "Falsifier",
    "Risks",
)


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def stage(text):
    return int(re.search(r"^UPDATER_STAGE=(\d+)$", text, re.MULTILINE).group(1))


def fingerprint(root):
    values = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def prepare(args):
    args.run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.workspace_from, args.run_dir / "workspace")
    shutil.copytree(args.policy, args.run_dir / "policy")
    write(
        args.run_dir / "manifest.json",
        {
            "instructions": args.instructions,
            "workspace_from": str(args.workspace_from),
            "producer": args.policy.parent.name,
            "model": args.model,
            "effort": args.effort,
        },
    )


def run(root):
    manifest = json.loads((root / "manifest.json").read_text())
    role = manifest["instructions"]
    standing = (root / "policy" / role).read_text()
    method_stage = stage(standing)
    workspace = root / "workspace"
    trial = workspace / "method_trial.json"
    receipt = {
        "instructions": role,
        "method_stage": method_stage,
        "instruction_sha256": hashlib.sha256(standing.encode()).hexdigest(),
        "method_trial": trial.exists(),
        "input_knowledge_sha256": fingerprint(workspace / "knowledge"),
        "target_policy_sha256": fingerprint(workspace / "policy"),
        "source_workspace": manifest["workspace_from"],
        "model_metadata_only": True,
    }
    if trial.exists():
        receipt["trial_context"] = json.loads(trial.read_text())
    if role == "analyst.md":
        (workspace / "ANALYSIS.md").write_text(
            f"Synthetic analysis by updater stage {method_stage}.\n"
        )
        write(workspace / "hindsight.json", {"clusters": []})
        (workspace / "knowledge").mkdir(exist_ok=True)
        (workspace / "knowledge" / "updater-reading.md").write_text(
            f"Analyzed by inherited stage {method_stage}.\n"
        )
        readme = workspace / "archive" / "README.md"
        pending = (
            re.search(r"^Pending experiment: (\w+)$", readme.read_text(), re.MULTILINE)
            if readme.exists()
            else None
        )
        if pending:
            write(
                workspace / "verdict.json",
                {
                    "experiment": pending.group(1),
                    "signature": "present",
                    "outcome": "synthetic",
                    "reading": "fixture only",
                },
            )
    elif role == "challenger.md":
        (workspace / "CHALLENGE.md").write_text(
            f"Synthetic challenge by inherited stage {method_stage}.\n"
        )
    elif role == "research.md":
        feedback = [
            json.loads(path.read_text())
            for path in sorted((workspace / "archive" / "runs").glob("*/summary.json"))
        ]
        if not feedback or any(row.get("validity") != "valid" for row in feedback):
            raise ValueError("updater requires delivered scored feedback")
        receipt["feedback"] = [
            {"task": row["task"], "pass_rate": row["pass_rate"]} for row in feedback
        ]
        if trial.exists():
            # Same target P/M in both arms. Only the inherited updater differs, and it uses O.
            if method_stage > 0 and any(row["pass_rate"] < 1 for row in feedback):
                path = workspace / "policy" / "executor.md"
                path.write_text(path.read_text() + "\nbetter\n")
            receipt["target_method_stage"] = stage(
                (workspace / "policy" / "research.md").read_text()
            )
        else:
            if method_stage > 0:
                reports = [
                    json.loads(path.read_text())
                    for path in (workspace / "archive" / "method-trials").glob("*.json")
                ]
                accepted = [
                    report
                    for report in reports
                    if report["method"] == manifest["producer"] and report.get("passed")
                ]
                if not accepted:
                    raise ValueError(
                        "adopted updater needs its downstream method feedback before iterating"
                    )
                receipt["method_feedback"] = accepted
            successor = method_stage + 1
            for name in METHODS:
                path = workspace / "policy" / name
                path.write_text(
                    re.sub(
                        r"^UPDATER_STAGE=\d+$",
                        f"UPDATER_STAGE={successor}",
                        path.read_text(),
                        flags=re.MULTILINE,
                    )
                )
            receipt["produced_stage"] = successor
        (workspace / "EXPERIMENT.md").write_text(
            "".join(
                f"## {name}\nSynthetic evidence-conditioned updater fixture.\n"
                for name in SECTIONS
            )
        )
    else:
        raise ValueError("unknown updater role")
    write(root / "run.json", {"turn_statuses": ["completed"], **receipt})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--instructions")
    parser.add_argument("--workspace-from", type=Path)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="max")
    args, _ = parser.parse_known_args()
    prepare(args) if args.command == "prepare" else run(args.run_dir)


if __name__ == "__main__":
    main()
