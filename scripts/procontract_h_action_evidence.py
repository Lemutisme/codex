"""Strict bounded evidence of a registered notice RPC, not model obedience or utility."""

from decimal import Decimal
import gzip
import hashlib
import json
import math
import os
import stat

import procontract_delivery_budget as delivery_budget
import procontract_harness_program as harness
import procontract_ph_protocol as protocol

MAX_SOURCE = 256 << 20
MAX_COMPRESSED = 32 << 20
MAX_DECODED = 256 << 20
MAX_RECORD = 1 << 20


def _rpc(run, summary, attempt, action, floors):
    # Oversize/unknown logs fail closed, never authorize another attempt.
    paths = [
        p
        for p in (run / "app-server.jsonl", run / "app-server.jsonl.gz")
        if p.exists() or p.is_symlink()
    ]
    protocol.require(len(paths) == 1, "probe needs exactly one raw protocol log")
    path = paths[0]
    before = path.lstat()
    protocol.require(stat.S_ISREG(before.st_mode), "unsafe probe protocol log")
    source_hash, total = hashlib.sha256(), 0
    active = request = response = None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        opened = os.fstat(source.fileno())
        protocol.require(
            (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino)
            and stat.S_ISREG(opened.st_mode),
            "probe log changed while opening",
        )
        limit = MAX_COMPRESSED if path.suffix == ".gz" else MAX_SOURCE
        while chunk := source.read(MAX_RECORD):
            total += len(chunk)
            protocol.require(total <= limit, "probe protocol source exceeds bound")
            source_hash.update(chunk)
        source.seek(0)
        stream = gzip.GzipFile(fileobj=source) if path.suffix == ".gz" else source
        total = 0
        with stream:
            while line := stream.readline(MAX_RECORD + 1):
                total += len(line)
                protocol.require(
                    len(line) <= MAX_RECORD and total <= MAX_DECODED,
                    "probe protocol log exceeds bound",
                )
                outgoing = line.startswith(b"> ")
                value = json.loads(line[2:] if outgoing else line)
                protocol.require(
                    isinstance(value, dict), "malformed probe protocol record"
                )
                params = value.get("params", {})
                if (
                    not outgoing
                    and "id" not in value
                    and value.get("method") in {"turn/started", "turn/completed"}
                    and params.get("threadId") == summary["thread_id"]
                ):
                    active = (
                        params["turn"]["id"]
                        if value["method"] == "turn/started"
                        else None
                    )
                if outgoing and value.get("method") == "turn/steer":
                    protocol.require(
                        request is None
                        and attempt is not None
                        and isinstance(params, dict)
                        and set(params) == {"threadId", "expectedTurnId", "input"}
                        and type(value.get("id")) is int
                        and value["id"] > 0
                        and params.get("threadId") == summary["thread_id"]
                        and params.get("expectedTurnId")
                        == active
                        == attempt["turn_id"],
                        "probe steering request differs or repeats",
                    )
                    # Floors come from the same feasible interval as the ceil fact;
                    # an independently plausible display value is not sufficient.
                    protocol.require(
                        any(
                            params.get("input")
                            == [
                                {
                                    "type": "text",
                                    "text": delivery_budget.notice(action, n),
                                    "text_elements": [],
                                }
                            ]
                            for n in floors
                        ),
                        "probe RPC payload is not the registered Host action",
                    )
                    request = value
                elif (
                    not outgoing
                    and request is not None
                    and value.get("id") == request.get("id")
                    and "method" not in value
                ):
                    protocol.require(
                        response is None, "duplicate probe steering acknowledgement"
                    )
                    response = value
    protocol.require(
        (request is None) == (attempt is None),
        "probe attempt differs from protocol log",
    )
    if attempt is not None and attempt["outcome"] == "accepted":
        protocol.require(
            response is not None
            and "error" not in response
            and response.get("result", {}).get("turnId") == attempt["turn_id"],
            "probe acknowledgement does not match its turn",
        )
    return {
        "path": path.name,
        "sha256": source_hash.hexdigest(),
        "notice": request["params"]["input"][0]["text"] if request else None,
        "coordinate": {
            "request_id": request["id"],
            "thread_id": request["params"]["threadId"],
            "turn_id": request["params"]["expectedTurnId"],
        }
        if request
        else None,
    }


def probe(run, program, deadline):
    """Read raw native receipts; tolerant feedback projections never authorize action."""
    summary = protocol.document(run / "run.json")
    activation, delivery = summary["harness_program"], summary["delivery_budget"]
    protocol.require(
        isinstance(activation, dict) and isinstance(delivery, dict),
        "malformed H runtime receipts",
    )
    expected_keys = {
        "sha256",
        "interpreter",
        "evaluations",
        "last_input",
        "last_decision",
    }
    if program.schema >= 2:
        expected_keys |= {"action", "last_eligibility"}
    protocol.require(
        set(activation) == expected_keys
        and (activation["sha256"], activation["interpreter"])
        == (program.digest, program.interpreter)
        and activation.get("action", "converge") == program.action
        and type(activation["evaluations"]) is int
        and 0 <= activation["evaluations"] <= harness.MAX_INTEGER,
        "malformed H activation",
    )
    facts = activation["last_input"]
    if facts is not None:
        protocol.require(
            activation["last_decision"] is program.evaluate(facts)
            and facts["deadline_secs"] == deadline
            and activation["evaluations"] > 0,
            "H predicate receipt differs",
        )
    else:
        protocol.require(
            activation["last_decision"] is None, "H predicate lacks its input"
        )
    if program.schema >= 2:
        eligibility = activation["last_eligibility"]
        protocol.require(
            eligibility is None
            and activation["evaluations"] == 0
            or isinstance(eligibility, dict)
            and set(eligibility) == {"eligible", "reason"}
            and type(eligibility["eligible"]) is bool
            and eligibility["reason"] in delivery_budget.ELIGIBILITY_REASONS
            and eligibility["eligible"] == (eligibility["reason"] == "eligible"),
            "malformed H eligibility receipt",
        )
    reserve = min(3600, deadline // 4)
    protocol.require(
        set(delivery) == {"reserve_secs", "attempt"}
        and type(delivery["reserve_secs"]) is int
        and delivery["reserve_secs"] == reserve,
        "H delivery receipt differs",
    )
    attempt, outcome, floors = delivery["attempt"], "no_action", set()
    if attempt is not None:
        required = {"turn_id", "remaining_secs", "outcome"}
        if program.schema >= 2:
            required.add("action")
        protocol.require(
            isinstance(attempt, dict)
            and required <= attempt.keys()
            and isinstance(summary.get("thread_id"), str)
            and 0 < len(summary["thread_id"]) <= 128
            and attempt.get("action", "converge") == program.action
            and isinstance(attempt["turn_id"], str)
            and 0 < len(attempt["turn_id"]) <= 128
            and attempt["outcome"]
            in {"accepted", "timeout", "error", "unacknowledged"},
            "malformed H delivery attempt",
        )
        remaining = attempt["remaining_secs"]
        protocol.require(
            type(remaining) in (int, float)
            and math.isfinite(remaining)
            and 0 <= remaining <= deadline
            and activation["last_decision"] is True
            and facts is not None
            # A positive sub-millisecond convergence attempt can round to 0.0.
            # ceil(actual_remaining) must still prove the positive interval.
            and (
                remaining > 0
                or (
                    program.action == "converge"
                    and reserve > 0
                    and facts["remaining_secs"] == 1
                )
            ),
            "H attempt lacks valid true predicate facts",
        )
        if program.schema >= 2:
            protocol.require(
                activation["last_eligibility"]
                == {"eligible": True, "reason": "eligible"},
                "H attempt lacks raw eligible predicate",
            )
        if program.action == "converge":
            protocol.require(
                remaining <= reserve, "H convergence was outside its late window"
            )
        else:
            protocol.require(
                deadline - remaining >= min(300, deadline // 10)
                and remaining >= min(60, deadline // 10),
                "H checkpoint was outside its eligible window",
            )
        rounded, ceiling = Decimal(str(remaining)), facts["remaining_secs"]
        earliest, latest = (
            (0, reserve)
            if program.action == "converge"
            else (min(60, deadline // 10), deadline - min(300, deadline // 10))
        )
        lower = max(
            rounded - Decimal("0.0005"), Decimal(ceiling - 1), Decimal(earliest)
        )
        upper = min(rounded + Decimal("0.0005"), Decimal(ceiling), Decimal(latest))
        if lower < upper:
            floors.add(ceiling - 1)
        if ceiling > 0 and earliest <= ceiling <= latest and rounded == ceiling:
            floors.add(ceiling)  # ceil's closed integer endpoint has this floor.
        protocol.require(
            rounded == rounded.quantize(Decimal("0.001")) and floors,
            "H receipt has no consistent rounding/ceil interval",
        )
        outcome = attempt["outcome"]
    return {
        "outcome": outcome,
        "eligibility_basis": "raw_last_eligibility"
        if program.schema >= 2
        else "legacy_controller_late_window",
        "protocol_log": _rpc(run, summary, attempt, program.action, floors),
    }
