"""Validate native task delivery independently of contract judgment; no inference."""
import json
import re
from pathlib import Path

import procontract_store as store


def helper(run):
    manifest = run / "manifest.json"
    if manifest.exists():
        native = json.loads(manifest.read_text()).get("codex_bin")
        if native:
            binary = Path(native).resolve().parent / "pro-contract-store"
            if binary.is_file():
                return binary
    return None


def select(events, thread, prompt):
    captures = [r for r in events if r["event"]["kind"] == "capture"
                and r["event"]["body"].get("phase") == "task_delivery"
                and r["event"]["body"].get("thread_id") == thread]
    if not captures:
        return None  # Old releases do not acquire a new receipt retrospectively.
    intakes = [r for r in events if r["event"]["kind"] == "intake"
               and r["event"]["body"].get("thread_id") == thread]
    if len(intakes) != 1 or intakes[0]["event"]["body"].get("text") != prompt:
        raise ValueError("delivery has no unique matching original admission")
    intake = intakes[0]
    turns = set()
    for capture in captures:
        body = capture["event"]["body"]
        turn = body.get("turn_id")
        epoch = body.get("execution_epoch")
        if (capture["seq"] <= intake["seq"] or body.get("intake") != intake["hash"]
                or body.get("capture_policy") != intake["event"]["body"].get("capture_policy")
                or not isinstance(turn, str) or not turn or turn in turns
                or type(epoch) is not int or not 0 <= epoch < 2**64
                or not re.fullmatch(r"[0-9a-f]{64}", body.get("subject_hash", ""))):
            raise ValueError("delivery differs from its admitted task or frozen artifact")
        turns.add(turn)
    last = max(captures, key=lambda r: (r["event"]["body"]["execution_epoch"], r["seq"]))
    return {"verified": True, "event_hash": last["hash"], **last["event"]["body"]}


def snapshot(run, thread):
    directory = run / "codex-home/pro_contract"
    if thread is None or not (directory / "ledger_1.sqlite").exists():
        return None
    binary = helper(run)
    store._run(["verify", "--store", str(directory)], binary=binary)
    events = json.loads(store._run(["events", "--store", str(directory)], binary=binary))
    return select(events, thread, (run / "prompt.txt").read_text())


def materialize(run, delivery):
    """Package the delivered bytes, not a later mutable workspace or a claimed summary."""
    actual = snapshot(run, delivery["thread_id"])
    if actual != delivery:
        raise ValueError("native delivery changed after process shutdown")
    target = run / "delivered-workspace"
    if target.exists():
        raise ValueError("delivery workspace already exists; preserve for reconciliation")
    store._run(["materialize", "--store", str(run / "codex-home/pro_contract"),
                "--subject", delivery["subject_hash"], "--dest", str(target)], binary=helper(run))
    (run / "delivery-receipt.json").write_text(json.dumps(delivery, indent=2) + "\n")
    return target
