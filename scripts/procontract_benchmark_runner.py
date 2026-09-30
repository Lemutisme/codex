#!/usr/bin/env python3
"""Runs one ProgramBench instance under the ProContract evaluation profile (spec §13).

  prepare   copy the instance workspace out of the cleanroom image and write CODEX_HOME
  run       drive `codex app-server` over stdio with the task prompt until the thread rests
  evaluate  package submission.tar.gz and run the official `programbench eval`

Both arms use the same binary, prompt, model and deadline; ON enables the `pro_contract`
feature, OFF disables it. The model credential stays in this process's environment: neither
it nor CODEX_HOME is ever mounted into a container.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

INSTANCE = "wfxr__csview.8ac4de0"
CLEANROOM_IMAGE = "programbench/wfxr_1776_csview.8ac4de0:task_cleanroom"
MODEL = "gpt-5.6-luna"
EFFORT = "max"
ENVIRONMENT_ID = "cleanroom"
CONTAINER_WORKSPACE = "/workspace"
AGENT_USER = "1000:1000"
ARTIFACTS = Path.home() / "run-artifacts" / "procontract-essential-20260930"
DEFAULT_CODEX = (
    ARTIFACTS / "musl" / "target" / "x86_64-unknown-linux-musl" / "release" / "codex"
)
DEFAULT_PROMPT = ARTIFACTS / "task-prompt.txt"
PROGRAMBENCH = Path.home() / "ProgramBench"
# Never captured as the candidate: the unreadable reference, build output and history.
CAPTURE_EXCLUDED = ["executable", "target", ".git"]
# Never submitted: the reference (a no-op compile.sh would submit it) and build output.
SUBMISSION_EXCLUDED = ["./executable", "./target"]
STATUS_POLL_SECS = 5.0


def config_toml() -> str:
    return f"""model = "{MODEL}"
model_reasoning_effort = "{EFFORT}"
model_provider = "openai-custom"
approval_policy = "never"
sandbox_mode = "danger-full-access"
web_search = "disabled"

[model_providers.openai-custom]
name = "OpenAI Custom"
base_url = "https://model-proxy.development.research-platform.isara.io/v1"
env_key = "OPENAI_API_KEY"
supports_websockets = false
wire_api = "responses"
"""


def environments_toml(workspace: Path, codex_bin: Path, image: str) -> str:
    args = [
        "run",
        "-i",
        "--rm",
        "--network",
        "none",
        "--user",
        AGENT_USER,
        "-v",
        f"{workspace}:{CONTAINER_WORKSPACE}",
        "-v",
        f"{codex_bin}:/opt/codex:ro",
        "-w",
        CONTAINER_WORKSPACE,
        image,
        "/opt/codex",
        "exec-server",
        "--listen",
        "stdio",
    ]
    return (
        f'default = "{ENVIRONMENT_ID}"\n'
        "include_local = false\n\n"
        "[[environments]]\n"
        f'id = "{ENVIRONMENT_ID}"\n'
        'program = "docker"\n'
        f"args = {json.dumps(args)}\n"
    )


def settings(workspace: Path, image: str) -> dict:
    return {
        "evaluation": {
            "environment_id": ENVIRONMENT_ID,
            "workspace_container_root": CONTAINER_WORKSPACE,
            "workspace_host_root": str(workspace),
            "excluded_paths": CAPTURE_EXCLUDED,
            "check": {
                "docker": "docker",
                "image": image,
                "user": AGENT_USER,
                "candidate_mount": "/candidate",
                "timeout_secs": 1800,
                "build_command": "chmod +x ./compile.sh && ./compile.sh",
                "candidate_command": "./executable",
            },
            "reference_command": f"{CONTAINER_WORKSPACE}/executable",
        },
        "repair_attempts": 1,
        "worker": {"model": MODEL, "reasoning_effort": EFFORT, "deadline_secs": 2400},
    }


def write_codex_home(home: Path, workspace: Path, codex_bin: Path, image: str) -> None:
    (home / "pro_contract").mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(config_toml())
    (home / "environments.toml").write_text(
        environments_toml(workspace, codex_bin, image)
    )
    (home / "pro_contract" / "settings.json").write_text(
        json.dumps(settings(workspace, image), indent=2) + "\n"
    )


def app_server_command(codex_bin: Path, arm: str) -> list[str]:
    toggle = "--enable" if arm == "on" else "--disable"
    return [str(codex_bin), "--disable", "hooks", toggle, "pro_contract", "app-server"]


def read_status(ledger: Path, thread_id: str) -> dict | None:
    if not ledger.exists():
        return None
    try:
        with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=5) as db:
            row = db.execute(
                "SELECT json FROM records WHERE kind = 'status' AND key = ?",
                (thread_id,),
            ).fetchone()
    except sqlite3.Error:
        return None
    return json.loads(row[0]) if row else None


def is_done(
    arm: str, status: dict | None, *, turn_active: bool, turns_completed: int
) -> bool:
    """The executor has handed off and, under ON, the automation lane has come to rest."""
    if turn_active or turns_completed == 0:
        return False
    return arm == "off" or bool(status and status.get("resting"))


def package(workspace: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    excludes = [f"--exclude={path}" for path in SUBMISSION_EXCLUDED]
    subprocess.run(
        [
            "tar",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "--anchored",
            *excludes,
            "-czf",
            str(dest),
            "-C",
            str(workspace),
            ".",
        ],
        check=True,
    )


class AppServer:
    """Newline-delimited JSON-RPC (without the `jsonrpc` field) over the app-server's stdio."""

    def __init__(self, command: list[str], env: dict, log: Path, stderr: Path):
        self._log = log.open("a")
        self._stderr = stderr.open("a")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=env,
            text=True,
            bufsize=1,
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self._next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._log.write(line)
            self._log.flush()
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.messages.put({"method": "runner/eof"})

    def _send(self, message: dict) -> None:
        assert self.process.stdin is not None
        line = json.dumps(message)
        self._log.write(f"> {line}\n")
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send(
            {"method": method, **({"params": params} if params is not None else {})}
        )

    def request(self, method: str, params: dict, handle, timeout: float = 120) -> dict:
        """Sends a request; other messages that arrive meanwhile go to `handle`."""
        self._next_id += 1
        request_id = self._next_id
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=1)
            except queue.Empty:
                continue
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result", {})
            handle(message)
        raise TimeoutError(f"{method} got no response in {timeout}s")

    def refuse(self, message: dict) -> None:
        """Server-to-client requests are not expected (approval policy `never`); refuse them."""
        self._send(
            {"id": message["id"], "error": {"code": -32601, "message": "unsupported"}}
        )

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._log.close()
        self._stderr.close()


def prepare(args: argparse.Namespace) -> None:
    run_dir: Path = args.run_dir
    if run_dir.exists() and any(run_dir.iterdir()):
        sys.exit(f"{run_dir} is not empty; choose a fresh run directory")
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "-v",
            f"{workspace}:/out",
            "--entrypoint",
            "sh",
            args.image,
            "-c",
            "cp -a /workspace/. /out/ && chown -R 1000:1000 /out "
            "&& chown 0:0 /out/executable && chmod 0111 /out/executable",
        ],
        check=True,
    )
    write_codex_home(
        run_dir / "codex-home", workspace, args.codex_bin.resolve(), args.image
    )
    prompt = args.prompt.read_bytes()
    (run_dir / "prompt.txt").write_bytes(prompt)
    manifest = {
        "arm": args.arm,
        "instance": args.instance,
        "image": args.image,
        "codex_bin": str(args.codex_bin.resolve()),
        "codex_sha256": hashlib.sha256(args.codex_bin.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def run(args: argparse.Namespace) -> None:
    run_dir: Path = args.run_dir
    home = run_dir / "codex-home"
    if "OPENAI_API_KEY" not in os.environ:
        sys.exit("OPENAI_API_KEY must be set in the runner's environment")
    env = {**os.environ, "CODEX_HOME": str(home)}
    prompt = (run_dir / "prompt.txt").read_text()
    server = AppServer(
        app_server_command(args.codex_bin, args.arm),
        env,
        run_dir / "app-server.jsonl",
        run_dir / "app-server.stderr",
    )
    started = time.monotonic()
    state = {"turn_active": False, "turns_completed": 0, "turn_id": None, "eof": False}

    def handle(message: dict) -> None:
        method = message.get("method")
        if "id" in message and method is not None:
            server.refuse(message)
        elif method == "turn/started":
            state["turn_active"] = True
            state["turn_id"] = message["params"]["turn"]["id"]
        elif method == "turn/completed":
            state["turn_active"] = False
            state["turns_completed"] += 1
        elif method == "runner/eof":
            state["eof"] = True

    summary: dict = {"arm": args.arm, "deadline_secs": args.deadline_secs}
    try:
        server.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "procontract-benchmark-runner",
                    "title": None,
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            },
            handle,
        )
        server.notify("initialized")
        thread = server.request(
            "thread/start",
            {
                "model": MODEL,
                "config": {"model_reasoning_effort": EFFORT},
                "sandbox": "danger-full-access",
                "approvalPolicy": "never",
                "cwd": CONTAINER_WORKSPACE,
            },
            handle,
        )
        thread_id = thread["thread"]["id"]
        summary["thread_id"] = thread_id
        server.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
            },
            handle,
        )
        ledger = home / "pro_contract" / "ledger_1.sqlite"
        status = None
        last_poll = 0.0
        while not state["eof"]:
            try:
                handle(server.messages.get(timeout=1))
            except queue.Empty:
                pass
            now = time.monotonic()
            if now - last_poll >= STATUS_POLL_SECS:
                last_poll = now
                status = read_status(ledger, thread_id)
                if is_done(
                    args.arm,
                    status,
                    turn_active=state["turn_active"],
                    turns_completed=state["turns_completed"],
                ):
                    break
            if now - started > args.deadline_secs:
                summary["deadline_hit"] = True
                if state["turn_active"] and state["turn_id"]:
                    server.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": state["turn_id"]},
                        handle,
                    )
                break
        summary.update(
            status=read_status(ledger, thread_id),
            turns_completed=state["turns_completed"],
            server_exited_early=state["eof"],
        )
    finally:
        summary["elapsed_secs"] = round(time.monotonic() - started)
        server.close()
        (run_dir / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


def evaluate(args: argparse.Namespace) -> None:
    run_dir: Path = args.run_dir
    eval_dir = run_dir / "eval"
    package(run_dir / "workspace", eval_dir / args.instance / "submission.tar.gz")
    log = run_dir / "eval.log"
    with log.open("w") as out:
        subprocess.run(
            [
                "uv",
                "run",
                "programbench",
                "eval",
                str(eval_dir),
                "--filter",
                f"^{re.escape(args.instance)}$",
                "-w",
                "1",
                "-b",
                "1",
                "--docker-cpus",
                "4",
            ],
            cwd=args.programbench,
            stdout=out,
            stderr=subprocess.STDOUT,
            check=True,
        )
    text = log.read_text()
    match = re.search(rf"^\s*{re.escape(args.instance)}\s+(✅|\d+)", text, re.MULTILINE)
    result = {
        "instance": args.instance,
        "score": None if match is None else match.group(1),
        "solved": bool(match and match.group(1) == "✅"),
    }
    (run_dir / "evaluation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["prepare", "run", "evaluate"])
    parser.add_argument("--arm", choices=["on", "off"], required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--instance", default=INSTANCE)
    parser.add_argument("--image", default=CLEANROOM_IMAGE)
    parser.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--deadline-secs", type=int, default=5 * 3600)
    parser.add_argument("--programbench", type=Path, default=PROGRAMBENCH)
    args = parser.parse_args()
    if args.run_dir is None:
        args.run_dir = ARTIFACTS / "runs" / f"{args.instance}-{args.arm}"
    if shutil.which("docker") is None:
        sys.exit("docker is required")
    {"prepare": prepare, "run": run, "evaluate": evaluate}[args.command](args)


if __name__ == "__main__":
    main()
