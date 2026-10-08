#!/usr/bin/env python3
"""Verified entry to the existing guarded workflow; never initializes or expands a study."""

import argparse
import json
import sys
from pathlib import Path

import procontract_study as study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stream", "status", "adopt", "budget"))
    parser.add_argument("--camp", type=Path, required=True)
    parser.add_argument("--study-sha256", required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--version")
    args = parser.parse_args()
    if not 1 <= args.count <= 1000:
        parser.error(
            "count must be between 1 and 1000; it does not expand the sealed budget"
        )
    camp = args.camp.resolve()
    terms = json.loads((camp / "campaign.json").read_text())
    if terms.get("study", {}).get("manifest_sha256") != args.study_sha256:
        raise RuntimeError("live entry differs from the operator's study pin")
    sealed = study.verify(camp, terms)
    if args.command == "budget":
        import procontract_study_budget as budget

        print(
            json.dumps(
                budget.status(
                    camp / "study-budget.sqlite", args.study_sha256, sealed["limits"]
                ),
                indent=2,
            )
        )
        return
    # The workflow and all runtime sources are checked before the Host is imported.
    import procontract_rsi as rsi

    argv = [str(Path(rsi.__file__)), args.command, "--camp", str(camp)]
    if args.command == "stream":
        argv += ["--count", str(args.count)]
    elif args.command == "adopt":
        if args.version is None:
            parser.error("adopt requires --version")
        argv += ["--version", args.version]
    sys.argv = argv
    rsi.main()


if __name__ == "__main__":
    main()
