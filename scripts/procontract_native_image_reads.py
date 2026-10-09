"""Finite private view_image dispatch evidence, not a general file/OS audit.

Read only the existing authenticated native trace. Project paths and outcomes, never
image bytes. A failed view may already have read bytes before decode failed. Absence
of other file accesses from this projection is not evidence that none occurred.
"""

import procontract_compliance_evidence as evidence
import procontract_native_notice_receipt as native
import procontract_native_trace_binding as binding


def _require(condition, message):
    if not condition:
        raise ValueError(f"native image evidence: {message}")


def _text(value, cap):
    _require(
        isinstance(value, str) and 0 < len(value.encode()) <= cap and "\0" not in value,
        "missing or oversized text",
    )
    return value


def _collect(run, manifest, summary, capture):
    """Assemble after native exit; the caller freezes/rechecks the returned private receipt.

    No arbitrary trace root is accepted. Baseline tasks without any H notice are valid;
    the mandatory descriptor and after-close storage receipt, not notice delivery, bind
    this collection. Unknown/missing/mutated evidence raises; never starts or retries work.
    """
    bound = binding.descriptor(run, manifest)
    receipt = summary.get("native_notice_trace")
    _require(
        bound is not None
        and isinstance(receipt, dict)
        and type(receipt.get("schema")) is int
        and receipt["schema"] == 1
        and receipt.get("descriptor_sha256")
        == manifest["native_notice_trace"]["sha256"]
        and receipt.get("retained_private_root") == str(run / binding.ROOT),
        "trace descriptor or receipt differs",
    )
    current = binding.storage(run)
    _require(
        not current["exhausted"]
        and isinstance(receipt.get("storage"), dict)
        and all(
            current[key] == receipt["storage"].get(key)
            for key in ("mount_id", "device", "max_bytes", "max_inodes")
        ),
        "trace storage changed or exhausted",
    )
    thread = capture["thread_id"]
    _require(thread == summary.get("thread_id"), "trace root differs")
    turns = {turn["id"] for turn in capture["turns"]}
    reader = native.Reader(
        run / binding.ROOT, thread_id=thread, turn_id=capture["turn_id"]
    )
    scan = native._Scan(reader)
    bundle, _, manifest_raw, log, events = scan.snapshot()
    files = {
        "manifest.json": evidence._digest(manifest_raw),
        "trace.jsonl": evidence._digest(log),
    }
    starts, images, ended, successes = {}, {}, set(), {}
    all_ended, result_types = set(), {}
    notifications = {
        (row["turn_id"], row["id"]): row["path"] for row in capture["image_views"]
    }
    _require(
        len(notifications) == len(capture["image_views"]),
        "duplicate image notifications",
    )

    def payload(ref, kind):
        value, digest = scan.payload(bundle, ref, kind)
        path = ref["path"]
        _require(
            path not in files or files[path] == digest, "payload changed during scan"
        )
        files[path] = digest
        return value

    threads = {
        _text(event["payload"].get("thread_id"), 128)
        for event in events
        if event["payload"]["type"] == "thread_started"
    }
    active, seen_turns, last_turn_seq = None, [], 0
    for event in events:
        scan.check_time()
        body = event["payload"]
        kind = body["type"]
        if event["thread_id"] == thread and kind in (
            "codex_turn_started",
            "codex_turn_ended",
        ):
            turn = event["codex_turn_id"]
            _require(
                body.get("codex_turn_id") == turn and turn in turns,
                "trace turn identity differs",
            )
            if kind == "codex_turn_started":
                _require(
                    active is None
                    and turn not in seen_turns
                    and body.get("thread_id") == thread,
                    "duplicate or overlapping trace turn",
                )
                active = turn
                seen_turns.append(turn)
            else:
                _require(
                    active == turn
                    and body.get("status") in ("completed", "cancelled", "aborted"),
                    "trace turn completion differs",
                )
                expected = next(
                    row["status"] for row in capture["turns"] if row["id"] == turn
                )
                _require(
                    (body["status"] == "completed") == (expected == "completed"),
                    "trace and app-server turn outcomes differ",
                )
                active, last_turn_seq = None, event["seq"]
        if kind not in ("tool_call_started", "tool_call_ended"):
            continue
        dispatch_thread = _text(event["thread_id"], 128)
        turn, call = (
            _text(event["codex_turn_id"], 128),
            _text(body.get("tool_call_id"), 256),
        )
        _require(dispatch_thread in threads, "unknown dispatch thread")
        if dispatch_thread != thread:
            continue
        _require(turn in turns and active == turn, "dispatch outside captured turns")
        key = (turn, call)
        if kind == "tool_call_started":
            _require(key not in starts, "duplicate dispatch start")
            tool_kind = body.get("kind")
            _require(isinstance(tool_kind, dict), "missing dispatch kind")
            tool_type = tool_kind.get("type")
            if tool_type == "other":
                _require(
                    set(tool_kind) == {"type", "name"}, "invalid generic dispatch kind"
                )
                _text(tool_kind["name"], 256)
            elif tool_type == "mcp":
                _require(
                    set(tool_kind) == {"type", "server", "tool"},
                    "invalid MCP dispatch kind",
                )
                _text(tool_kind["server"], 256)
                _text(tool_kind["tool"], 256)
            else:
                _require(
                    set(tool_kind) == {"type"}
                    and tool_type
                    in (
                        "exec_command",
                        "write_stdin",
                        "apply_patch",
                        "web",
                        "image_generation",
                        "spawn_agent",
                        "assign_agent_task",
                        "send_message",
                        "wait_agent",
                        "close_agent",
                    ),
                    "unknown dispatch kind",
                )
            starts[key] = tool_kind
            if starts[key] != {"type": "other", "name": "view_image"}:
                continue
            invocation = payload(body.get("invocation_payload"), "tool_invocation")
            _require(
                set(invocation) == {"tool_name", "tool_namespace", "payload"}
                and isinstance(invocation["tool_name"], str),
                "invalid dispatch invocation",
            )
            _require(
                invocation["tool_name"] == "view_image"
                and invocation["tool_namespace"] is None,
                "unknown image mechanism",
            )
            arguments = invocation["payload"]
            _require(
                isinstance(arguments, dict)
                and set(arguments) == {"type", "arguments"}
                and arguments["type"] == "function"
                and isinstance(arguments["arguments"], str),
                "invalid image invocation",
            )
            args = evidence._parse(arguments["arguments"].encode(), 16384)
            _require(
                isinstance(args, dict)
                and "path" in args
                and set(args) <= {"path", "detail", "environment_id"},
                "unknown image arguments",
            )
            path = _text(args["path"], 4096)
            environment, detail = args.get("environment_id"), args.get("detail")
            if environment is not None:
                _text(environment, 256)
            _require(detail in (None, "high", "original"), "unknown image detail")
            requester = body.get("requester")
            _require(isinstance(requester, dict), "missing image requester")
            if requester.get("type") == "model":
                _require(
                    set(requester) == {"type"}
                    and body.get("model_visible_call_id") == call
                    and body.get("code_mode_runtime_tool_id") is None,
                    "invalid image model requester",
                )
            else:
                _require(
                    set(requester) == {"type", "runtime_cell_id"}
                    and requester["type"] == "code_cell"
                    and body.get("model_visible_call_id") is None,
                    "invalid image code requester",
                )
                _text(requester["runtime_cell_id"], 128)
                _text(body.get("code_mode_runtime_tool_id"), 256)
            result_types[key] = (
                "direct_response"
                if requester["type"] == "model"
                else "code_mode_response"
            )
            _require(len(images) < 4096, "too many image reads")
            images[key] = dict(
                tool="view_image",
                path=path,
                environment_id=environment,
                detail=detail,
                observed_path=None,
                outcome=None,
                error=None,
            )
        else:
            _require(
                key in starts and key not in all_ended,
                "orphan or duplicate dispatch completion",
            )
            all_ended.add(key)
            if key not in images:
                continue
            _require(key not in ended, "duplicate image completion")
            ended.add(key)
            result = payload(body.get("result_payload"), "tool_result")
            row = images[key]
            outcome = result.get("type")
            if outcome == "error":
                _require(
                    set(result) == {"type", "error"}
                    and body.get("status") == "failed"
                    and key not in notifications,
                    "conflicting image failure",
                )
                row.update(outcome="error", error=_text(result["error"], 4096))
            else:
                _require(
                    body.get("status") == "completed" and outcome == result_types[key],
                    "unknown image completion status or requester",
                )
                if outcome == "direct_response":
                    response = result.get("response_item")
                    _require(
                        set(result) == {"type", "response_item"}
                        and isinstance(response, dict)
                        and set(response) == {"type", "call_id", "output"}
                        and response["type"] == "function_call_output"
                        and response["call_id"] == call,
                        "invalid image direct result",
                    )
                    content = response["output"]
                    _require(
                        isinstance(content, list)
                        and len(content) == 1
                        and isinstance(content[0], dict)
                        and content[0].get("type") == "input_image"
                        and set(content[0]) <= {"type", "image_url", "detail"},
                        "invalid image content",
                    )
                    image = content[0]
                else:
                    _require(
                        outcome == "code_mode_response"
                        and set(result) == {"type", "value"},
                        "unknown image result type",
                    )
                    image = result["value"]
                    _require(
                        isinstance(image, dict)
                        and set(image) <= {"image_url", "detail"},
                        "invalid image code result",
                    )
                _require(
                    isinstance(image.get("image_url"), str)
                    and image["image_url"].startswith(
                        "data:application/octet-stream;base64,"
                    )
                    and image.get("detail") in (None, "high", "original"),
                    "invalid image data result",
                )
                _require(key in notifications, "successful image lacks app-server pair")
                row.update(outcome="completed", observed_path=notifications[key])
                successes[key] = row["observed_path"]
    _require(
        active is None and seen_turns == [row["id"] for row in capture["turns"]],
        "native trace turns are incomplete",
    )
    footers = [
        (event["seq"], event["payload"])
        for event in events
        if event["payload"]["type"] == "rollout_ended"
        or (
            event["payload"]["type"] == "thread_ended"
            and event["payload"].get("thread_id") == thread
        )
    ]
    _require(
        len(footers) == 2
        and footers[0][1]["type"] == "thread_ended"
        and footers[1][1]["type"] == "rollout_ended"
        and footers[1][0] == len(events)
        and footers[0][0] > last_turn_seq
        and footers[0][1].get("status") == footers[1][1].get("status")
        and footers[1][1].get("status") in ("completed", "failed", "aborted"),
        "native trace terminal footer missing or ambiguous",
    )
    _require(
        set(images) == ended and successes == notifications,
        "missing or foreign image dispatch pair",
    )
    rows = list(images.values())
    evidence._typed_reads(rows)
    # A stable second bounded read detects concurrent source changes before the private
    # receipt is frozen. Later mutations change this receipt on the gate's existing replay.
    for name, digest in files.items():
        cap = (
            reader.limits.max_log_bytes
            if name == "trace.jsonl"
            else (
                reader.limits.max_manifest_bytes
                if name == "manifest.json"
                else reader.limits.max_payload_bytes
            )
        )
        _require(
            evidence._digest(scan.read(bundle / name, cap)) == digest,
            "trace source changed",
        )
    _require(
        binding.descriptor(run, manifest) == bound and binding.storage(run) == current,
        "trace binding changed during collection",
    )
    return rows, dict(
        schema=1,
        descriptor_sha256=receipt["descriptor_sha256"],
        reader_sha256=evidence._digest(evidence._read(__file__, 1 << 20)),
        limits=bound["limits"],
        thread_id=thread,
        turns=capture["turns"],
        files=files,
        reads_sha256=evidence._digest(evidence._typed_reads(rows)),
    )


def collect(run, manifest, summary, capture):
    """Normalize incomplete raw-trace evidence as an error for the existing no-retry gate."""
    try:
        return _collect(run, manifest, summary, capture)
    except (native._Unknown, OSError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("native image evidence is incomplete or malformed") from error
