"""Real native ProContract + Docker + RSI cycle; local scripted provider and fixture grader.

No benchmark reference or real API credential is used. A virtual elapsed clock
exercises the 300s steering guard without spending minutes sleeping in this test.
"""

import copy
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import procodex
import procontract_benchmark_runner as runner
import procontract_online as online
from procontract_online_acceptance import assess
from procontract_online_lineage import Lineage
from procontract_online_runtime import OnlineRuntime
from procontract_online_trace import OnlineTrace
from test_procodex_native import custom_call, text_values


class FixtureProvider:
    def __init__(self, initial):
        self.initial = initial
        self.requests, self.methods, self.errors = [], [], []
        self.counts = {}
        self.more_commands, self.finish = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                try:
                    if self.headers.get("Authorization") != "Bearer LOCAL_FIXTURE_ONLY":
                        raise ValueError("non-fixture credential refused")
                    size = int(self.headers["Content-Length"])
                    if not 0 < size < 2 << 20:
                        raise ValueError("fixture request bound")
                    body = json.loads(self.rfile.read(size))
                    props = (
                        body.get("text", {})
                        .get("format", {})
                        .get("schema", {})
                        .get("properties", {})
                    )
                    role = (
                        "research"
                        if "harness_json" in props
                        else "draft"
                        if "differential_cases" in props
                        else "review"
                        if "coverage" in props
                        else "executor"
                    )
                    with owner.lock:
                        owner.requests.append((role, body))
                        serial = len(owner.requests)
                        owner.counts[role] = owner.counts.get(role, 0) + 1
                        ordinal = owner.counts[role]
                    if serial > 20:
                        raise ValueError("local fixture request budget exhausted")
                    if (body["model"], body["reasoning"]["effort"]) != (
                        "gpt-5.6-luna",
                        "max",
                    ):
                        raise ValueError("unexpected model routing")
                    if role == "executor" and owner.initial[
                        "execution"
                    ] not in "\n".join(text_values(body)):
                        raise ValueError(
                            "initial native execution strategy was not consumed"
                        )
                    if role == "research":
                        prompt = next(
                            t
                            for t in text_values(body["input"])
                            if "The snapshot below contains" in t
                        )
                        packet = json.loads(prompt.rsplit("\n", 1)[-1])
                        owner.methods.append(packet["program"]["research"])
                        if (
                            owner.initial != online.seed()
                            and not packet["past_rewards"]
                        ):
                            raise ValueError(
                                "inherited method did not receive prior measured feedback"
                            )
                        if packet["program"] != owner.initial:
                            raise ValueError(
                                "native research did not consume selected controller"
                            )
                        names = set(text_values(body.get("tools", [])))
                        if names & {
                            "exec_command",
                            "shell",
                            "read_file",
                            "apply_patch",
                            "read_evidence",
                        }:
                            raise ValueError("researcher acquired execution tools")
                        h = copy.deepcopy(packet["program"]["harness"])
                        h["when"]["command_completions_observed_gte"] += 2
                        identity = packet["parent"][:8]
                        message = {
                            "execution": f"Run a discriminating fixture check after {identity}.",
                            "research": f"Test one bounded fixture hypothesis after {identity}.",
                            "harness_json": json.dumps(h),
                            "mechanism": "Delay checkpoint until two additional observations; preserve the contract.",
                            "prediction": json.dumps(
                                {
                                    "metric": "canonical_fraction",
                                    "direction": "at_least",
                                    "threshold": 0.5,
                                }
                            ),
                        }
                    elif role == "draft":
                        message = {
                            "decision": "contract",
                            "reason": "",
                            "requirements": [
                                {
                                    "id": "R1",
                                    "text": "answer.txt contains ready",
                                    "source_id": "request:0",
                                    "inferred": False,
                                }
                            ],
                            "out_of_scope": [],
                            "process_constraints": [],
                            "candidate_tests": False,
                            "differential_cases": [],
                        }
                    elif role == "review":
                        message = {
                            "verdict": "cannot_judge",
                            "coverage": [],
                            "findings": [],
                            "terms_gap": [],
                            "missing": "fixture has no independent review claim",
                            "residual": "",
                        }
                    elif ordinal <= 3:
                        if ordinal == 2 and not owner.more_commands.wait(45):
                            raise TimeoutError("research did not reach candidate state")
                        if ordinal == 3 and not owner.finish.wait(45):
                            raise TimeoutError("checkpoint did not dispatch")
                        count = (
                            owner.initial["harness"]["when"][
                                "command_completions_observed_gte"
                            ]
                            if ordinal == 1
                            else 2
                        )
                        code = (
                            'text("fixture continuation");'
                            if ordinal == 3
                            else f"for (let i=0;i<{count};i++) text(await tools.exec_command({{cmd:\"printf 'ready\\n' > answer.txt\",yield_time_ms:1000,max_output_tokens:1000}}));"
                        )
                        item = custom_call(body, code, f"fixture-{serial}")
                        message = None
                    else:
                        message = "Fixture task complete."
                    if message is not None:
                        item = {
                            "type": "message",
                            "id": f"message-{serial}",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(message)
                                    if isinstance(message, dict)
                                    else message,
                                }
                            ],
                        }
                    response = f"fixture-{serial}-" + "x" * 500
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    for event in [
                        {"type": "response.created", "response": {"id": response}},
                        {"type": "response.output_item.done", "item": item},
                        {
                            "type": "response.completed",
                            "response": {
                                "id": response,
                                "usage": {
                                    "input_tokens": 10,
                                    "output_tokens": 10,
                                    "total_tokens": 20,
                                },
                            },
                        },
                    ]:
                        self.wfile.write(
                            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                        )
                        self.wfile.flush()
                except Exception as error:
                    owner.errors.append(str(error))
                    self.send_error(500, "local fixture error")

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.provider = {
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "env_key": "FIXTURE_KEY",
        }

    def close(self):
        self.more_commands.set()
        self.finish.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE") and os.environ.get("PROCODEX_TEST_IMAGE"),
    "requires local native package and preinstalled Docker image; no real inference",
)
class NativeCycleTests(unittest.TestCase):
    def test_issued_contract_two_generations_feedback_and_unforced_selection(self):
        package = Path(os.environ["PROCODEX_NATIVE_PACKAGE"])
        image = os.environ["PROCODEX_TEST_IMAGE"]
        with tempfile.TemporaryDirectory(prefix="procodex-rsi-cycle-") as temporary:
            root = Path(temporary)
            lineage = Lineage(
                root / "lineage", selection_scope="a" * 64, selection_mode="coverage"
            )
            results, versions, observed_methods, counts = [], {}, [], []
            for index in range(3):
                run = root / str(index)
                run.mkdir()
                key = f"{index}-adaptive"
                allocation = lineage.begin(key, 14400, 900)
                initial = lineage.version(allocation["parent"])
                versions[online.digest(initial)] = initial
                fixture = FixtureProvider(initial)
                workspace = run / "workspace"
                workspace.mkdir()
                (workspace / "answer.txt").write_text("not ready\n")
                local_config = procodex.toml(
                    {
                        "model": "gpt-5.6-luna",
                        "model_reasoning_effort": "max",
                        "model_provider": "fixture",
                        "approval_policy": "never",
                        "sandbox_mode": "danger-full-access",
                        "web_search": "disabled",
                        "model_providers": {
                            "fixture": {
                                **fixture.provider,
                                "name": "Local fixture",
                                "wire_api": "responses",
                                "supports_websockets": False,
                                "request_max_retries": 0,
                                "stream_max_retries": 0,
                            }
                        },
                    }
                )
                with mock.patch.object(
                    runner, "config_toml", return_value=local_config
                ):
                    runner.write_codex_home(
                        run / "codex-home",
                        workspace,
                        package / "bin/codex",
                        image,
                        reference=False,
                        model="gpt-5.6-luna",
                        effort="max",
                    )
                (run / "manifest.json").write_text(
                    json.dumps(
                        {"image": image, "model": "gpt-5.6-luna", "effort": "max"}
                    )
                )
                (run / "prompt.txt").write_text("Make answer.txt contain ready.")
                trace = OnlineTrace(run, "a" * 64)
                runtime = OnlineRuntime(
                    lineage,
                    key,
                    run / "online",
                    package / "bin/codex",
                    fixture.provider,
                    "LOCAL_FIXTURE_ONLY",
                    allocation=allocation,
                )
                servers = []
                started = time.monotonic()
                actual_server = runner.AppServer
                actual_poll = runtime.poll

                def open_server(*args, **kwargs):
                    server = actual_server(*args, **kwargs)
                    servers.append(server)
                    return server

                def poll(server, turns, status, handle, *, elapsed_secs):
                    if time.monotonic() - started > 100:
                        raise TimeoutError("local integration fixture deadline")
                    actual_poll(server, turns, status, handle, elapsed_secs=500)
                    if (
                        runtime.status in ("candidate", "experimental", "rejected")
                        or allocation["research_secs"] == 0
                    ):
                        fixture.more_commands.set()
                    if runtime.dispatch_recorded or allocation["research_secs"] == 0:
                        fixture.finish.set()

                try:
                    # Route only to the local provider; do not read or mutate real credentials.
                    env = {
                        "PATH": os.environ["PATH"],
                        "FIXTURE_KEY": "LOCAL_FIXTURE_ONLY",
                        "OPENAI_API_KEY": "LOCAL_FIXTURE_ONLY",
                    }
                    with (
                        mock.patch.object(runner, "os", SimpleNamespace(environ=env)),
                        mock.patch.object(
                            runner, "current_key", return_value="LOCAL_FIXTURE_ONLY"
                        ),
                        mock.patch.object(runner, "AppServer", side_effect=open_server),
                        mock.patch.object(runtime, "poll", side_effect=poll),
                        mock.patch("builtins.print"),
                    ):
                        runner.run(
                            SimpleNamespace(
                                run_dir=run,
                                codex_bin=package / "bin/codex",
                                arm="on",
                                deadline_secs=allocation["executor_secs"],
                                delivery_reserve_secs=0,
                                stop_after_issue=False,
                                study_manifest=None,
                                study_sha256=None,
                            ),
                            learning=runtime,
                            online_trace=trace,
                        )
                    summary = json.loads((run / "run.json").read_text())
                    status = summary["status"]
                    self.assertEqual(
                        fixture.errors,
                        [],
                        (status, (run / "app-server.stderr").read_text()[-2000:]),
                    )
                    self.assertTrue(status and status.get("contract_id"), status)
                    self.assertTrue(status["resting"], status)
                    self.assertEqual(summary["turn_statuses"], ["completed"])
                    terminal = summary["online_learning"]
                    witness = summary["native_notice_trace"]
                    if index < 2:
                        self.assertEqual(
                            (terminal["status"], witness["evidence"]["status"]),
                            ("experimental", "observed"),
                        )
                        self.assertIsNotNone(terminal["harness_decision_difference"])
                        self.assertEqual(fixture.methods, [initial["research"]])
                    if runtime.candidate:
                        versions[online.digest(runtime.candidate)] = runtime.candidate
                    # Independent, immutable fixture grading, not a model self-grade.
                    archive = run / "submission.tar.gz"
                    runner.package(workspace, archive)
                    with tarfile.open(archive) as packaged:
                        content = packaged.extractfile("./answer.txt").read()
                    resolved = int(content == b"ready\n") + int(
                        content.strip() == b"ready"
                    )
                    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                    research = terminal.get("research") or {}
                    reward = lineage.reward(
                        key,
                        resolved=resolved,
                        total=2,
                        submission_sha256=sha,
                        evaluator_sha256="f" * 64,
                        selection_evidence={
                            "native_secs": summary["elapsed_secs"],
                            "research_secs": research.get("elapsed_secs", 0),
                            "grading_secs": 0.01,
                            "episode_secs": 18000,
                            **terminal["command_metrics"],
                            "input_witness": online.digest(witness)
                            if witness["evidence"]["status"] == "observed"
                            else None,
                        },
                    )
                    results.append(
                        {
                            "episode": key,
                            "status": "scored",
                            "online": terminal,
                            "native_context_evidence": witness,
                            "learning_reward": reward,
                            "outcome": {
                                "valid": True,
                                "resolved": resolved,
                                "total": 2,
                                "submission_sha256": sha,
                            },
                        }
                    )
                    observed_methods.extend(fixture.methods)
                    counts.append(fixture.counts)
                finally:
                    fixture.more_commands.set()
                    fixture.finish.set()
                    try:
                        runtime.close()
                    finally:
                        for server in servers:
                            if server.process.poll() is None:
                                server.close()
                            server.process.stdout.close()
                            server._log.close()
                        try:
                            trace.close()
                        finally:
                            fixture.close()
                        if output := os.environ.get("PROCODEX_CYCLE_REPORT"):
                            report_path = Path(output)
                            retained = (
                                report_path.parent
                                / (report_path.stem + "-evidence")
                                / key
                            )
                            retained.mkdir(parents=True)
                            for name in (
                                "private-native-trace.tar.gz",
                                "online-trace-descriptor.json",
                                "online-trace-cleanup.json",
                                "run.json",
                                "app-server.jsonl",
                                "app-server.stderr",
                                "online/allocation.json",
                                "online/research-input.json",
                                "online/research-receipt.json",
                                "online/proposal.json",
                                "online/dispatch.json",
                                "online/terminal.json",
                            ):
                                path = run / name
                                if path.is_file():
                                    destination = retained / name
                                    destination.parent.mkdir(
                                        parents=True, exist_ok=True
                                    )
                                    shutil.copyfile(path, destination)
                            (retained / "fixture-provider-requests.json").write_text(
                                json.dumps(fixture.requests) + "\n"
                            )
            report = assess(
                {
                    "tasks": ["fixture-a", "fixture-b", "fixture-c"],
                    "arms": ["adaptive"],
                },
                results,
                lineage.events(),
                versions,
                evidence_kind="synthetic",
            )
            self.assertEqual(report["status"], "PASS", report)
            self.assertNotEqual(observed_methods[0], observed_methods[1])
            self.assertEqual(lineage.current(), online.seed())
            if output := os.environ.get("PROCODEX_CYCLE_REPORT"):
                with Path(output).open("x") as report_file:
                    report_file.write(
                        json.dumps(
                            {
                                "acceptance": report,
                                "counts": counts,
                                "real_model_calls": 0,
                                "provider": "localhost scripted fixture",
                                "grader": "fixed immutable fixture checks, not ProgramBench",
                                "guard_clock": "virtual elapsed=500 seconds; actual native process lifetime measured",
                                "results": results,
                                "events": lineage.events(),
                            },
                            indent=2,
                        )
                        + "\n"
                    )


if __name__ == "__main__":
    unittest.main()
