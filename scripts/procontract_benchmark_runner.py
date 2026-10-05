#!/usr/bin/env python3
"""Runs one ProgramBench instance under the ProContract evaluation profile (spec §13).

  prepare   copy the instance workspace out of the cleanroom image and write CODEX_HOME
  run       drive `codex app-server` over stdio with the task prompt until the thread rests

Both arms use the same binary, prompt, model and deadline; ON enables the `pro_contract`
feature, OFF disables it. The model credential stays in this process's environment: neither
it nor CODEX_HOME is ever mounted into a container.
"""

import argparse
import hashlib
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

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
# Never captured as the candidate: the unreadable reference, build output and history.
CAPTURE_EXCLUDED = ["executable", "target", ".git"]
# Never submitted: the reference (a no-op compile.sh would submit it) and build output.
SUBMISSION_EXCLUDED = ["./executable", "./target"]
STATUS_POLL_SECS = 5.0


def config_toml(developer_instructions: str = "") -> str:
    """The executor's configuration; a version's standing instructions become its developer
    instructions."""
    instructions = (
        f"developer_instructions = {json.dumps(developer_instructions)}\n"
        if developer_instructions.strip()
        else ""
    )
    return f"""model = "{MODEL}"
model_reasoning_effort = "{EFFORT}"
model_provider = "openai-custom"
approval_policy = "never"
sandbox_mode = "danger-full-access"
web_search = "disabled"
{instructions}
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


def settings(
    workspace: Path, image: str, reference: bool = True, policy: Path | None = None
) -> dict:
    """The evaluation grant. Without a reference the lane has nothing to build or compare and
    decides from review alone; a policy bundle replaces the built-in worker instructions."""
    result = {
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
    if not reference:
        result["evaluation"]["reference_command"] = None
        result["evaluation"]["check"]["build_command"] = None
        result["evaluation"]["check"]["candidate_command"] = None
    if policy is not None:
        result["policy"] = str(policy)
    return result


def write_codex_home(
    home: Path,
    workspace: Path,
    codex_bin: Path,
    image: str,
    reference: bool = True,
    policy: Path | None = None,
    developer_instructions: str = "",
) -> None:
    (home / "pro_contract").mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(config_toml(developer_instructions))
    (home / "environments.toml").write_text(
        environments_toml(workspace, codex_bin, image)
    )
    (home / "pro_contract" / "settings.json").write_text(
        json.dumps(settings(workspace, image, reference, policy), indent=2) + "\n"
    )


def harness_ready(codex_bin: Path) -> str | None:
    """Return why codex cannot start its tool host, or None when it can."""
    host = codex_bin.resolve().parent / "codex-code-mode-host"
    if not (host.is_file() and os.access(host, os.X_OK)):
        return f"no executable codex-code-mode-host beside {codex_bin}: expected {host}"
    return None


def app_server_command(codex_bin: Path, arm: str) -> list[str]:
    toggle = "--enable" if arm == "on" else "--disable"
    return [str(codex_bin), "--disable", "hooks", toggle, "pro_contract", "app-server"]


def server_env(run_dir: Path, base: dict) -> dict:
    """The host environment with CODEX_HOME and HOME confined to the run directory."""
    return {
        **base,
        "CODEX_HOME": str(run_dir / "codex-home"),
        "HOME": str(run_dir / "home"),
    }


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


def cleanroom_image(instance: str) -> str:
    return f"programbench/{instance.replace('__', '_1776_')}:task_cleanroom"


def task_image(instance: str) -> str:
    return f"programbench/{instance.replace('__', '_1776_')}:task"


def ensure_images(instance: str) -> None:
    for image in (cleanroom_image(instance), task_image(instance)):
        present = (
            subprocess.run(
                ["docker", "image", "inspect", image], capture_output=True
            ).returncode
            == 0
        )
        if not present:
            subprocess.run(["docker", "pull", image], check=True)


def issued(status: dict | None) -> bool:
    """The ON lane has issued its contract (or come to rest without one)."""
    return bool(status) and status.get("phase") not in ("idle", "drafting")


def lane_silent(
    arm: str,
    status: dict | None,
    first_completion_at: float | None,
    now: float,
    limit: float = 600.0,
) -> bool:
    """The ON lane never wrote a status record long after the executor handed off."""
    return (
        arm == "on"
        and status is None
        and first_completion_at is not None
        and now - first_completion_at >= limit
    )


def rollout_costs(codex_home: Path) -> dict:
    keys = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    totals = {
        "executor": dict.fromkeys(keys, 0),
        "workers": dict.fromkeys(keys, 0),
        "worker_rollouts": 0,
    }
    for path in sorted((codex_home / "sessions").rglob("rollout-*.jsonl")):
        source, usage = None, None
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a rollout still being written may end mid-line
            payload = record.get("payload", {})
            if record.get("type") == "session_meta":
                source = payload.get("source")
            elif (
                record.get("type") == "event_msg"
                and payload.get("type") == "token_count"
                and payload.get("info")
            ):
                usage = payload["info"]["total_token_usage"]
        worker = (
            isinstance(source, dict) and source.get("internal") == "extension_worker"
        )
        totals["worker_rollouts"] += 1 if worker else 0
        for key in keys:
            totals["workers" if worker else "executor"][key] += (usage or {}).get(
                key, 0
            )
    return totals


class TurnTracker:
    """Turn state of the executor thread; hidden worker threads' turns are ignored."""

    def __init__(self, thread_id: str | None = None):
        self.thread_id = thread_id
        self.active = False
        self.completed = 0
        self.statuses: list[str] = []
        self.errors: list[str] = []
        self.turn_id: str | None = None

    def observe(self, message: dict) -> None:
        method = message.get("method")
        if method not in ("turn/started", "turn/completed"):
            return
        params = message.get("params", {})
        if self.thread_id is None or params.get("threadId") != self.thread_id:
            return
        self.turn_id = params["turn"]["id"]
        if method == "turn/started":
            self.active = True
        else:
            self.active = False
            self.completed += 1
            self.statuses.append(params["turn"].get("status", "unknown"))
            error = params["turn"].get("error") or {}
            if error.get("message"):
                self.errors.append(error["message"])


class AppServer:
    """Newline-delimited JSON-RPC (without the `jsonrpc` field) over the app-server's stdio."""

    def __init__(
        self, command: list[str], env: dict, log: Path, stderr: Path, cwd: Path
    ):
        self._log = log.open("a")
        self._stderr = stderr.open("a")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=env,
            cwd=cwd,
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
    problem = harness_ready(args.codex_bin)
    if problem:
        sys.exit(problem)
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True)
    if args.workspace_from is None:
        ensure_images(args.instance)
        source = []
        copy = (
            "cp -a /workspace/. /out/ && chown -R 1000:1000 /out "
            "&& chown 0:0 /out/executable && chmod 0111 /out/executable"
        )
    else:
        source = ["-v", f"{args.workspace_from.resolve()}:/in:ro"]
        copy = "cp -a /in/. /out/ && chown -R 1000:1000 /out"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            *source,
            "-v",
            f"{workspace}:/out",
            "--entrypoint",
            "sh",
            args.image,
            "-c",
            copy,
        ],
        check=True,
    )
    # A frozen copy of the version's bundle: the run reads it, the version cannot change it.
    policy = None
    instructions = ""
    if args.policy is not None:
        policy = run_dir / "policy"
        shutil.copytree(args.policy, policy)
        chosen = policy / args.instructions
        instructions = chosen.read_text() if chosen.exists() else ""
    write_codex_home(
        run_dir / "codex-home",
        workspace,
        args.codex_bin.resolve(),
        args.image,
        reference=not args.no_reference,
        policy=policy,
        developer_instructions=instructions,
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
    (run_dir / "home").mkdir(exist_ok=True)
    env = server_env(run_dir, dict(os.environ))
    prompt = (run_dir / "prompt.txt").read_text()
    server = AppServer(
        app_server_command(args.codex_bin, args.arm),
        env,
        run_dir / "app-server.jsonl",
        run_dir / "app-server.stderr",
        cwd=run_dir,
    )
    started = time.monotonic()
    turns = TurnTracker()
    eof = threading.Event()

    def handle(message: dict) -> None:
        method = message.get("method")
        if "id" in message and method is not None:
            server.refuse(message)
        elif method == "runner/eof":
            eof.set()
        else:
            turns.observe(message)

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
        turns.thread_id = thread_id
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
        first_completion_at = None
        while not eof.is_set():
            try:
                handle(server.messages.get(timeout=1))
            except queue.Empty:
                pass
            now = time.monotonic()
            if first_completion_at is None and turns.completed == 1:
                first_completion_at = now
            if now - last_poll >= STATUS_POLL_SECS:
                last_poll = now
                status = read_status(ledger, thread_id)
                if args.stop_after_issue:
                    # Intake is done once the lane drafts; the executor's work is not needed,
                    # so stop it and wait for the drafter and prober to issue the contract.
                    if (
                        status
                        and status.get("phase") == "drafting"
                        and turns.active
                        and turns.turn_id
                        and not summary.get("interrupted_executor")
                    ):
                        server.request(
                            "turn/interrupt",
                            {"threadId": thread_id, "turnId": turns.turn_id},
                            handle,
                        )
                        summary["interrupted_executor"] = True
                    if issued(status):
                        summary["stopped"] = "after_issue"
                        break
                elif is_done(
                    args.arm,
                    status,
                    turn_active=turns.active,
                    turns_completed=turns.completed,
                ):
                    break
                elif lane_silent(args.arm, status, first_completion_at, now):
                    summary["stopped"] = "no_status_record"
                    break
            if now - started > args.deadline_secs:
                summary["deadline_hit"] = True
                if turns.active and turns.turn_id:
                    server.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turns.turn_id},
                        handle,
                    )
                break
        summary.update(
            status=read_status(ledger, thread_id),
            turns_completed=turns.completed,
            server_exited_early=eof.is_set(),
            turn_statuses=turns.statuses,
            turn_errors=turns.errors,
            cost=rollout_costs(home),
        )
    finally:
        summary["elapsed_secs"] = round(time.monotonic() - started)
        server.close()
        (run_dir / "run.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["prepare", "run"])
    parser.add_argument("--arm", choices=["on", "off"], required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--image")
    parser.add_argument("--codex-bin", type=Path, default=DEFAULT_CODEX)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--deadline-secs", type=int, default=5 * 3600)
    parser.add_argument(
        "--policy",
        type=Path,
        help="a version's policy bundle directory (prepare)",
    )
    parser.add_argument(
        "--instructions",
        default="executor.md",
        help="the bundle file used as the executor's developer instructions (prepare)",
    )
    parser.add_argument(
        "--workspace-from",
        type=Path,
        help="build the workspace from this directory instead of the instance image (prepare)",
    )
    parser.add_argument(
        "--no-reference",
        action="store_true",
        help="the task has no reference program to compare against (prepare)",
    )
    parser.add_argument(
        "--stop-after-issue",
        action="store_true",
        help="interrupt the executor once the contract is issued (offline replay evidence)",
    )
    args = parser.parse_args()
    if args.stop_after_issue and args.arm != "on":
        parser.error("--stop-after-issue needs the ON arm")
    args.image = args.image or cleanroom_image(args.instance)
    if args.run_dir is None:
        args.run_dir = ARTIFACTS / "runs" / f"{args.instance}-{args.arm}"
    if shutil.which("docker") is None:
        sys.exit("docker is required")
    {"prepare": prepare, "run": run}[args.command](args)


if __name__ == "__main__":
    main()
