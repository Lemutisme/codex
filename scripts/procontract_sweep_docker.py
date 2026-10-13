#!/usr/bin/env python3
"""Scoped host Docker transport: bounded resources and auditable cleanup ownership."""

import os
import re
import sys


def arguments(args, environ):
    if not args or args[0] not in ("run", "create"):
        return args
    study, episode = (
        environ.get("PROCONTRACT_SWEEP_ID", ""),
        environ.get("PROCONTRACT_SWEEP_EPISODE", ""),
    )
    if not re.fullmatch(r"[0-9a-f]{64}", study) or not re.fullmatch(
        r"\d+-successor", episode
    ):
        raise ValueError("missing immutable sweep/container owner")
    additions = [
        "--label",
        f"procodex.study={study}",
        "--label",
        f"procodex.episode={episode}",
    ]
    memory = (
        args[args.index("--memory") + 1]
        if "--memory" in args
        else next(
            (a.split("=", 1)[1] for a in args if a.startswith("--memory=")), "32g"
        )
    )
    for option, value in (
        ("--memory", "32g"),
        ("--memory-swap", memory),
        ("--cpus", "4"),
        ("--pids-limit", "512"),
        ("--network", "none"),
        ("--pull", "never"),
    ):
        if option not in args and not any(a.startswith(option + "=") for a in args):
            additions += [option, value]
    return [args[0], *additions, *args[1:]]


if __name__ == "__main__":
    os.execv(
        "/usr/bin/docker", ["/usr/bin/docker", *arguments(sys.argv[1:], os.environ)]
    )
