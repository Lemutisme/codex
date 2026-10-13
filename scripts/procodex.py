#!/usr/bin/env python3
"""Local ProContract Codex preview. Isolated state; no automatic benchmark or RSI spending."""

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sqlite3


from procodex_config import configure, toml


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "rsi":
        package = Path(__file__).resolve().parent.parent
        env = {
            **os.environ,
            "PRO_CONTRACT_STORE_BIN": str(package / "bin/pro-contract-store"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.call(
            [
                sys.executable,
                str(package / "scripts/procontract_rsi.py"),
                *(argv[1:] or ["--help"]),
            ],
            env=env,
        )
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Unrecognized options are passed to Codex. Use procodex rsi --help for the separately budgeted research CLI.",
    )
    parser.add_argument(
        "-C",
        "--cd",
        type=Path,
        default=Path.cwd(),
        help="workspace to expose inside the isolated executor",
    )
    parser.add_argument(
        "--container-image",
        help="an already installed, compatible Docker image (no pull)",
    )
    parser.add_argument(
        "--check",
        help="explicit verification command in the frozen candidate, offline; default is review-only",
    )
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--successor-sessions",
        type=int,
        default=3,
        help="fresh executor sessions after failed verification (0 disables; max 16)",
    )
    parser.add_argument(
        "--task-seconds",
        type=int,
        default=14400,
        help="original-intake wall-clock deadline for automatic succession; never reset by a new session",
    )
    parser.add_argument(
        "--container-only",
        action="store_true",
        help="explicitly use Docker as the execution sandbox, without nested bwrap; approvals remain on-request",
    )
    args, rest = parser.parse_known_args(argv)
    if not 0 <= args.successor_sessions <= 16 or not 60 <= args.task_seconds <= 86400:
        parser.error("succession requires 0..16 sessions and 60..86400 task seconds")
    if args.check is not None and (
        not args.check.strip() or len(args.check.encode()) > 4096
    ):
        parser.error("--check must be a nonempty command of at most 4096 UTF-8 bytes")
    package = Path(__file__).resolve().parent.parent
    release = json.loads((package / "procodex-release.json").read_text())
    if args.version:
        print(
            f"procodex preview {release['source_commit'][:12]} (native ProContract; interactive auto-RSI off)"
        )
        return 0
    if sys.platform != "linux" or shutil.which("docker") is None:
        parser.error("this local preview requires Linux and Docker")
    workspace = args.cd.expanduser().resolve(strict=True)
    if not workspace.is_dir() or workspace == Path("/") or workspace == Path.home():
        parser.error("choose a project directory, not / or the entire home directory")
    image_query = args.container_image or release["image"]
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_query], text=True
    ).strip()
    if not image.startswith("sha256:"):
        parser.error("Docker did not resolve an immutable image ID")
    root = (
        Path(os.environ.get("PROCODEX_HOME", Path.home() / ".procodex"))
        .expanduser()
        .resolve()
    )
    source_home = (
        Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        .expanduser()
        .resolve()
    )
    if root == source_home or root == workspace or root.is_relative_to(workspace):
        parser.error(
            "ProCodex state must be outside the workspace and separate from CODEX_HOME"
        )
    os.umask(0o077)
    isolation = "container-only" if args.container_only else "nested"
    diagnostic = bool(rest and rest[0] in ("doctor", "status"))
    if not diagnostic and isolation == "nested":
        probe = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={package},dst=/opt/procodex,readonly",
                image,
                "/opt/procodex/codex-resources/bwrap",
                "--unshare-user",
                "--ro-bind",
                "/",
                "/",
                "/bin/true",
            ],
            capture_output=True,
            timeout=20,
        )
        if probe.returncode:
            message = "Nested Codex sandbox is unavailable on this host. Docker-only mode keeps the project-only writable mount, network=none, cap-drop=ALL and on-request approvals; Codex itself will show full access INSIDE that container."
            print(message, file=sys.stderr)
            if not sys.stdin.isatty() or input(
                "Use Docker-only isolation for this invocation? [y/N] "
            ).strip().lower() not in ("y", "yes", "是"):
                parser.error(
                    "no sandbox change made; use --container-only only if you accept the documented boundary"
                )
            isolation = "container-only"
    home, config = configure(
        package,
        workspace,
        root,
        source_home,
        image,
        args.check,
        isolation=isolation,
        successor_sessions=args.successor_sessions,
        task_seconds=args.task_seconds,
    )
    if rest and rest[0] in ("doctor", "status"):
        if rest[0] == "status":
            database = home / "pro_contract/ledger_1.sqlite"
            records = []
            if database.is_file():
                with contextlib.closing(
                    sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                ) as connection:
                    records = [
                        json.loads(row[0])
                        for row in connection.execute(
                            "SELECT json FROM records WHERE kind='status' ORDER BY key DESC LIMIT 20"
                        )
                    ]
            print(json.dumps(dict(codex_home=str(home), contracts=records), indent=2))
            return 0
        print(
            json.dumps(
                dict(
                    source_commit=release["source_commit"],
                    native=str(package / "bin/codex"),
                    workspace=str(workspace),
                    codex_home=str(home),
                    image=image,
                    pro_contract=True,
                    automatic_general_rsi=False,
                    fresh_executor_sessions=args.successor_sessions,
                    succession_task_seconds=args.task_seconds,
                    approval_policy=config["approval_policy"],
                    sandbox_mode=config["sandbox_mode"],
                    check=args.check,
                    network="none",
                ),
                indent=2,
            )
        )
        return 0
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    env["CODEX_SQLITE_HOME"] = str(home)
    env.pop("CODEX_ROLLOUT_TRACE_ROOT", None)
    provider = config.get("model_providers", {}).get(config["model_provider"], {})
    if provider.get("env_key", "OPENAI_API_KEY") == "OPENAI_API_KEY":
        from procontract_benchmark_runner import current_key

        if key := current_key(env):
            env["OPENAI_API_KEY"] = key
    # Login state is private per workspace; never write back to the existing Codex home.
    auth = source_home / "auth.json"
    if auth.is_file() and not (home / "auth.json").exists():
        with (home / "auth.json").open("xb") as target:
            target.write(auth.read_bytes())
    command = [
        str(package / "bin/codex"),
        "--enable",
        "pro_contract",
        "--disable",
        "hooks",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
        "-C",
        "/workspace",
    ]
    if not rest or rest[0] not in (
        "exec",
        "app-server",
        "login",
        "logout",
        "features",
        "debug",
    ):
        command.append("--no-daemon")
    command.extend(rest)
    print(
        f"[procodex] {workspace} -> /workspace; offline {isolation} executor; check={args.check or 'review-only'}.",
        file=sys.stderr,
    )
    print(
        "[procodex] Native contracts enabled. No background benchmark or automatic general-task RSI.",
        file=sys.stderr,
    )
    print(
        f"[procodex] Failed verification can start up to {args.successor_sessions} fresh sessions within {args.task_seconds}s from original intake; no task/budget reset.",
        file=sys.stderr,
    )
    os.chdir(workspace)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    raise SystemExit(main())
