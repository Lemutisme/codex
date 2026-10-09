"""Read-only authenticated canonical pack assembly, never an adoption/paid-run gate.

Only root-thread native command notifications are projected, not full child-process,
syscall, or file-tool behavior. Pending starts retain exit_code=None. Private receipts
may identify runs; only the EvidencePack goes to the independent auditor.
"""

import gzip
import io
from pathlib import Path
import re

import procontract_compliance_evidence as evidence

MAX_PROTOCOL = 256 << 20
MAX_COMPRESSED = 32 << 20
MAX_RECORD = 1 << 20
MAX_TURNS = 2
PASSIVE_ITEMS = frozenset(
    (
        "userMessage",
        "agentMessage",
        "reasoning",
        "fileChange",
        "plan",
        "contextCompaction",
    )
)


class EvidenceUnavailable(RuntimeError):
    """Incomplete/ambiguous evidence; no retry or paid launch is authorized."""


def _require(value, message):
    if not value:
        raise EvidenceUnavailable(message)


def native_commands(raw, *, compressed, thread_id):
    """Project initial turn plus at most one native repair; pending process exits stay null."""
    _require(
        isinstance(thread_id, str) and 0 < len(thread_id) <= 160,
        "native root thread is missing",
    )
    _require(
        type(raw) is bytes
        and len(raw) <= (MAX_COMPRESSED if compressed else MAX_PROTOCOL),
        "native capture exceeds bound",
    )
    source = io.BytesIO(raw)
    stream = gzip.GzipFile(fileobj=source) if compressed else source
    request = response = active = None
    turns = []
    commands, completed, count, command_bytes = {}, set(), 0, 0
    try:
        with stream:
            while line := stream.readline(MAX_RECORD + 1):
                count += len(line)
                _require(
                    len(line) <= MAX_RECORD and count <= MAX_PROTOCOL,
                    "native capture decoded bound exceeded",
                )
                outgoing = line.startswith(b"> ")
                value = evidence._parse(line[2:] if outgoing else line, MAX_RECORD)
                _require(
                    isinstance(value, dict), "native capture record is not an object"
                )
                method, params = value.get("method"), value.get("params", {})
                if (
                    outgoing
                    and method == "turn/start"
                    and params.get("threadId") == thread_id
                ):
                    _require(
                        request is None
                        and type(value.get("id")) is int
                        and value["id"] > 0,
                        "native turn/start is ambiguous",
                    )
                    request = value["id"]
                elif (
                    not outgoing and request is not None and value.get("id") == request
                ):
                    _require(
                        response is None
                        and type(value.get("id")) is int
                        and "method" not in value
                        and "error" not in value,
                        "native turn/start acknowledgement differs",
                    )
                    response = value.get("result", {}).get("turn", {}).get("id")
                    _require(
                        isinstance(response, str) and response,
                        "missing native turn acknowledgement",
                    )
                if (
                    outgoing
                    or "id" in value
                    or not isinstance(params, dict)
                    or params.get("threadId") != thread_id
                ):
                    continue
                if method in ("turn/started", "turn/completed"):
                    item = params.get("turn", {})
                    if method == "turn/started":
                        _require(
                            active is None
                            and len(turns) < MAX_TURNS
                            and request is not None
                            and isinstance(item.get("id"), str)
                            and item["id"]
                            and item.get("status") == "inProgress"
                            and item["id"] not in {turn["id"] for turn in turns},
                            "native root lifecycle start differs",
                        )
                        active = item["id"]
                        turns.append({"id": active, "status": "inProgress"})
                    else:
                        _require(
                            active is not None
                            and item.get("id") == active
                            and item.get("status") in ("completed", "interrupted"),
                            "native root lifecycle completion differs",
                        )
                        turns[-1]["status"] = item["status"]
                        active = None
                elif method in ("item/started", "item/completed"):
                    item = params.get("item", {})
                    item_turn = params.get("turnId")
                    _require(
                        active is not None and item_turn == active,
                        "native item is outside the active captured root turn",
                    )
                    kind = item.get("type")
                    _require(
                        kind == "commandExecution" or kind in PASSIVE_ITEMS,
                        "unsupported native execution mechanism",
                    )
                    if kind != "commandExecution":
                        continue
                    item_id, command = item.get("id"), item.get("command")
                    _require(
                        isinstance(item_id, str)
                        and 0 < len(item_id) <= 256
                        and isinstance(command, str)
                        and len(command) <= 65536
                        and len(command.encode()) <= 65536,
                        "malformed native command",
                    )
                    key = (item_turn, item_id)
                    if method == "item/started":
                        _require(
                            key not in commands
                            and len(commands) < 4096
                            and item.get("status") == "inProgress",
                            "duplicate/invalid native command start",
                        )
                        projected = {"command": command, "exit_code": None}
                        command_bytes += len(evidence._json(projected).encode()) + 1
                        _require(
                            command_bytes <= evidence.MAX_COMMANDS,
                            "native command projection exceeds bound",
                        )
                        commands[key] = projected
                    else:
                        code = item.get("exitCode")
                        _require(
                            key in commands
                            and key not in completed
                            and commands[key]["command"] == command
                            and item.get("status")
                            in ("completed", "failed", "declined")
                            and (code is None or type(code) is int),
                            "orphan/conflicting native command completion",
                        )
                        commands[key]["exit_code"] = code
                        completed.add(key)
        _require(
            request is not None
            and turns
            and response == turns[0]["id"]
            and active is None,
            "native root lifecycle is incomplete",
        )
    except (OSError, EOFError, ValueError, AttributeError, TypeError) as error:
        raise EvidenceUnavailable(
            "native capture is unreadable or malformed"
        ) from error
    return list(commands.values()), dict(
        scope="observed root command notifications; not complete process/syscall or file-tool capture",
        thread_id=thread_id,
        turn_id=turns[0]["id"],
        commands=len(commands),
        turns=turns,
        pending=len(commands) - len(completed),
        terminal_status=turns[-1]["status"],
        protocol_sha256=evidence._digest(raw),
    )


def build_run_pack(host, run_dir):
    """Authenticate one existing measurement and assemble evidence, with no model/tool calls.

    The gate freezes the private receipt on first assembly and compares it byte-for-byte
    on replay. This function does not reserve budget, call measure(), or alter state.
    """
    import procontract_canonical as canonical
    import procontract_dependency_inspection as inspection
    import procontract_dependency_policy as dependency
    import procontract_ph_audit as audits
    import procontract_rsi as rsi

    try:
        _require(
            host.terms.get("submission_policy") == dependency.BUILD_RUNTIME_POLICY,
            "compliance assembly is future build/runtime policy only",
        )
        run = Path(run_dir)
        _require(
            run.is_absolute()
            and run.resolve() == run
            and run.is_relative_to(host.camp / "runs")
            and not any(path.is_symlink() for path in (run, *run.parents)),
            "unsafe measured-run path",
        )
        artifacts = {}

        def read(path, cap=MAX_RECORD):
            data = evidence._read(path, cap)
            artifacts[str(path)] = evidence._digest(data)
            return data

        result_path = run.parent / "result.json"
        result = evidence._parse(read(result_path), MAX_RECORD)
        _require(isinstance(result, dict), "missing canonical result identity")
        task, version, purpose = (
            result.get(key) for key in ("task", "version", "purpose")
        )
        _require(
            all(isinstance(x, str) and x for x in (task, version, purpose))
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", purpose)
            and evidence._sha(version)
            and run
            == host.camp / "runs" / f"{purpose}-{version[:12]}-{task}" / "attempt-1"
            and result.get("run_dir") == str(run)
            and result.get("validity") == "valid",
            "measurement does not identify exactly this single attempt",
        )
        host.validate_evaluator(result)
        # Source-only validation has no failure-marker writes; activation checks below are read-only.
        host.validate_harness(version)
        marker = run / "harness-identity-failure.txt"
        _require(
            not (marker.exists() or marker.is_symlink()),
            "run already has an identity failure",
        )
        manifest = evidence._parse(read(run / "manifest.json"), MAX_RECORD)
        summary = evidence._parse(read(run / "run.json"), MAX_RECORD)
        expected_harness = host.versions()[version].get("harness")
        for value in (manifest, summary):
            activation = value.get("harness_program")
            actual = (
                {key: activation.get(key) for key in ("sha256", "interpreter")}
                if isinstance(activation, dict)
                else None
            )
            _require(actual == expected_harness, "native harness activation differs")
        _require(not rsi.runner_problem(summary), "native runner reports a failure")
        _require(
            manifest.get("instance") == task
            and manifest.get("study_version") == version
            and manifest.get("instructions") == "executor.md"
            and manifest.get("image") == canonical.TASKS[task]["image"]
            and audits.native_exited(summary),
            "native task identity or terminal process differs",
        )
        logs = [
            path
            for path in (run / "app-server.jsonl", run / "app-server.jsonl.gz")
            if path.exists() or path.is_symlink()
        ]
        _require(len(logs) == 1, "native capture is absent or ambiguous")
        log = logs[0]
        commands, capture = native_commands(
            read(log, MAX_COMPRESSED if log.suffix == ".gz" else MAX_PROTOCOL),
            compressed=log.suffix == ".gz",
            thread_id=summary.get("thread_id"),
        )
        archive = run / "submission.tar.gz"
        submission = evidence._parse(read(run / "submission-receipt.json"), MAX_RECORD)
        _require(
            isinstance(submission, dict) and set(submission) == {"sha256"},
            "canonical submission receipt differs",
        )
        digest = evidence._digest(read(archive, evidence.MAX_ARCHIVE))
        _require(
            submission["sha256"] == digest,
            "canonical submission receipt digest differs",
        )
        result_eval = evidence._parse(
            read(run / "eval/canonical-result.json"), MAX_RECORD
        )
        attempt = result_eval.get("attempts")
        _require(
            type(attempt) is int and attempt in (1, 2),
            "canonical evaluation attempt missing",
        )
        directory = run / "eval" / f"attempt-{attempt}" / task
        bound = canonical.validate_receipt(task, archive, directory)
        _require(
            bound.get("exit_code") == 0 and bound.get("submission_sha256") == digest,
            "canonical evaluation is not a successful bound process",
        )
        raw_eval = directory / f"{task}.eval.json"
        build = evidence.project_clean_build(raw_eval, bound["raw_eval_sha256"])
        artifacts[str(raw_eval)] = bound["raw_eval_sha256"]
        for name in ("evaluation-receipt.json", "evaluation-claim.json"):
            read(directory / name)
        policy = canonical.registry().dependency_policy
        _require(
            policy is not None and policy.name == dependency.BUILD_RUNTIME_POLICY,
            "missing future image policy",
        )
        policy_data = evidence._parse(read(policy.path), MAX_RECORD)
        _require(
            artifacts[str(policy.path)] == policy.digest,
            "policy identity changed during assembly",
        )
        image = canonical.TASKS[task]["image"]
        pins = canonical.checked_pins()
        image_receipt = pins["dependency_policy"]["images"][image]
        inspection.validate_receipt(policy, image, image_receipt)
        read(canonical.PINS_FILE)
        proof = dict(
            image=image,
            policy_sha256=policy.digest,
            inspection_sha256=evidence._digest(evidence._json(image_receipt).encode()),
            allowed=[
                {**row, **policy.items(image)[f"{row['kind']}:{row['name']}"]}
                for row in policy_data["allowed"]
            ],
        )
        pack = evidence.build_pack(
            archive, digest, commands=commands, proof=proof, clean_build=build
        )
        receipt = dict(
            schema=1,
            submission_sha256=digest,
            pack_sha256=pack.digest,
            artifacts=artifacts,
            capture=capture,
        )
        return pack, receipt
    except EvidenceUnavailable:
        raise
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        AttributeError,
    ) as error:
        raise EvidenceUnavailable(
            "canonical compliance evidence is incomplete or changed"
        ) from error
