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
    if argv and argv[0] in ("rsi", "rsi-legacy"):
        package = Path(__file__).resolve().parent.parent
        env = {
            **os.environ,
            "PRO_CONTRACT_STORE_BIN": str(package / "bin/pro-contract-store"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.call(
            [
                sys.executable,
                str(package / "scripts" / ("procontract_research_control.py" if argv[0] == "rsi" else "procontract_rsi.py")),
                *(argv[1:] or ["--help"]),
            ],
            env=env,
        )
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Unrecognized options are passed to Codex. Use procodex rsi --help for persistent research control; rsi-legacy retains the historical campaign CLI.",
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
    parser.add_argument("--no-progress", action="store_true", help="disable same-turn progress publication for a new task")
    parser.add_argument("--strategy", type=Path,
        help="context bundle directory; work_method.md and optional worker prompts")
    parser.add_argument("--rsi-config", type=Path,
        help="protected research control profile; enables /rsi without starting inference")
    parser.add_argument("--input", action="append", default=[], metavar="NAME=FILE",
        help="retain a file as a read-only task input at /inputs/NAME")
    parser.add_argument(
        "--review-compute", action="store_true",
        help="allow bounded, isolated Python review of frozen binary or numerical evidence in the configured image",
    )
    parser.add_argument(
        "--successor-sessions",
        type=int,
        default=None,
        help="optional explicit ceiling on fresh sessions (0 disables); otherwise shared task time bounds them",
    )
    parser.add_argument(
        "--task-seconds",
        type=int,
        default=None,
        help="optional hard wall-clock limit from original intake; omit for no task deadline. Existing admitted limits are preserved on resume",
    )
    parser.add_argument(
        "--container-only",
        action="store_true",
        help="explicitly use Docker as the execution sandbox, without nested bwrap; approvals remain on-request",
    )
    args, rest = parser.parse_known_args(argv)
    inputs = {}
    for declaration in args.input:
        name, separator, value = declaration.partition("=")
        if not separator or not value or name in inputs:
            parser.error("--input requires unique NAME=FILE declarations")
        inputs[name] = value
    if (args.successor_sessions is not None and not 0 <= args.successor_sessions <= 2**32-1) or (args.task_seconds is not None and not 1 <= args.task_seconds <= (2**64-1)//1000):
        parser.error("session count must be nonnegative and an explicit task duration must be positive")
    if args.check is not None and (
        not args.check.strip() or len(args.check.encode()) > 4096
    ):
        parser.error("--check must be a nonempty command of at most 4096 UTF-8 bytes")
    package = Path(__file__).resolve().parent.parent
    release = json.loads((package / "procodex-release.json").read_text())
    if args.version:
        print(
            f"procodex preview {release['source_commit'][:12]} (native ProContract; explicit /rsi control)"
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
        review_compute=args.review_compute,
        continuous_work=not args.no_progress,
        inputs=inputs,
        strategy=args.strategy,
    )
    admitted_settings = json.loads((home / "pro_contract/settings.json").read_text())
    admitted_seconds = (admitted_settings.get("succession") or {}).get("total_secs")
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
                    research_control_profile=str(args.rsi_config.resolve()) if args.rsi_config else None,
                    fresh_executor_sessions=args.successor_sessions,
                    succession_task_seconds=admitted_seconds,
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
    if args.rsi_config is not None:
        from procontract_research_control import ensure

        env["PROCONTRACT_RESEARCH_SOCKET"] = str(ensure(args.rsi_config))
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
        "[procodex] Native contracts enabled. Research starts through explicit /rsi requests when a control profile is configured.",
        file=sys.stderr,
    )
    allocation = "no hard task deadline" if admitted_seconds is None else f"original {admitted_seconds}s hard task limit"
    print(
        f"[procodex] Continuations share {allocation}; existing authority and accounting persist.",
        file=sys.stderr,
    )
    os.chdir(workspace)
    os.execve(command[0], command, env)


if __name__ == "__main__":
    raise SystemExit(main())
