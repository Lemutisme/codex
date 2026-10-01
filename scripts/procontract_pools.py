#!/usr/bin/env python3
"""Seen-list and sealed, salted pool split (RSI spec §10 item 6).

Reads only `repository`, `language` and `difficulty` from `task.yaml`; never `tests.json`."""

import argparse
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

import yaml

ID = re.compile(r"[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+\.[0-9a-f]{7}")
TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".tex",
    ".csv",
    ".log",
    ".py",
}
MAX_SCAN_BYTES = 5 << 20


def load_tasks(tasks_dir: Path, language: str) -> list[dict]:
    tasks = []
    for path in sorted(tasks_dir.glob("*/task.yaml")):
        data = yaml.safe_load(path.read_text())
        if data.get("language") == language:
            tasks.append(
                {
                    "id": path.parent.name,
                    "repository": data["repository"],
                    "language": data["language"],
                    "difficulty": data.get("difficulty") or "unknown",
                }
            )
    return tasks


def _is_test_path(parts: tuple[str, ...]) -> bool:
    return "tests" in parts or parts[-1] == "tests.json"


def seen_ids(paths: list[Path], known: set[str]) -> set[str]:
    found: set[str] = set()
    for root in paths:
        for path in [root] if root.is_file() else root.rglob("*"):
            relative = (root.name,) if root.is_file() else path.relative_to(root).parts
            if (
                _is_test_path(relative)
                or not path.is_file()
                or path.suffix not in TEXT_SUFFIXES
            ):
                continue
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            found |= set(ID.findall(path.read_text(errors="ignore"))) & known
    return found


def _rank(salt: str, repository: str) -> str:
    return hashlib.sha256(f"{salt}\0{repository}".encode()).hexdigest()


def split(
    tasks: list[dict], seen: set[str], salt: str, ratios: tuple[int, int, int]
) -> dict:
    result: dict[str, list[str]] = {"dev": [], "select": [], "confirm": []}
    strata: dict[str, list[dict]] = {}
    for task in tasks:
        if task["id"] in seen:
            result["dev"].append(task["id"])
        else:
            strata.setdefault(task["difficulty"], []).append(task)
    total = sum(ratios)
    for difficulty in sorted(strata):
        ranked = sorted(
            strata[difficulty], key=lambda task: _rank(salt, task["repository"])
        )
        dev_n = round(len(ranked) * ratios[0] / total)
        select_n = round(len(ranked) * ratios[1] / total)
        result["dev"] += [t["id"] for t in ranked[:dev_n]]
        result["select"] += [t["id"] for t in ranked[dev_n : dev_n + select_n]]
        result["confirm"] += [t["id"] for t in ranked[dev_n + select_n :]]
    return {name: sorted(ids) for name, ids in result.items()}


def commitment(salt: str, ids: list[str]) -> str:
    return hashlib.sha256(f"{salt}\0{json.dumps(sorted(ids))}".encode()).hexdigest()


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _salt(path: Path) -> str:
    if not path.exists():
        _write_private(path, secrets.token_hex(32))
    return path.read_text().strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    seen = sub.add_parser("seen")
    seen.add_argument("--tasks-dir", type=Path, required=True)
    seen.add_argument("--scan", type=Path, nargs="+", required=True)
    seen.add_argument("--out", type=Path, required=True)
    sp = sub.add_parser("split")
    sp.add_argument("--tasks-dir", type=Path, required=True)
    sp.add_argument("--language", default="rs")
    sp.add_argument("--seen", type=Path, required=True)
    sp.add_argument("--salt-file", type=Path, required=True)
    sp.add_argument("--ratios", default="40,30,30")
    sp.add_argument("--public-out", type=Path, required=True)
    sp.add_argument("--sealed-out", type=Path, required=True)
    args = parser.parse_args()
    known = {path.parent.name for path in args.tasks_dir.glob("*/task.yaml")}
    if args.command == "seen":
        args.out.write_text(
            json.dumps(sorted(seen_ids(args.scan, known)), indent=2) + "\n"
        )
        return
    tasks = load_tasks(args.tasks_dir, args.language)
    salt = _salt(args.salt_file)
    ratios = tuple(int(part) for part in args.ratios.split(","))
    pools = split(tasks, set(json.loads(args.seen.read_text())), salt, ratios)
    _write_private(args.sealed_out, json.dumps(pools, indent=2) + "\n")
    public = {
        "language": args.language,
        "ratios": ratios,
        "dev": pools["dev"],
        "counts": {name: len(ids) for name, ids in pools.items()},
        "commitments": {
            name: commitment(salt, pools[name]) for name in ("select", "confirm")
        },
        "difficulty": {
            task["id"]: task["difficulty"]
            for task in tasks
            if task["id"] in pools["dev"]
        },
    }
    args.public_out.write_text(json.dumps(public, indent=2) + "\n")


if __name__ == "__main__":
    main()
