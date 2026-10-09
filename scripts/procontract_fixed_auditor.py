"""Private single-use fixed auditor lane with one source-pinned paid-readiness switch.

The trusted controller supplies authenticated evidence packs and receipts. No evolved
policy, harness, score, arm or version is passed to the auditor. Journal/ledger state
is operator owned. Missing terminal evidence never grants a replacement attempt.
"""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

import procontract_compliance_evidence as evidence
import procontract_fixed_auditor_native as native
import procontract_fixed_auditor_role as role
import procontract_ph_protocol as protocol
import procontract_study as study
import procontract_study_budget as budget

PAID_ENABLED = True
PHASES = {"initial_serve": 1, "probe": 1, "confirmation": 8, "successor_serve": 1}
FILES = {
    "claim.json": 64 << 10,
    "study-launch.json": 64 << 10,
    "native.json": 64 << 10,
    "final.json": evidence.MAX_RESULT * 8,
    "evidence-served.jsonl": native.MAX_LOG,
    "rpc.jsonl": native.MAX_LOG,
    "stdout.log": native.MAX_LOG,
    "stderr.log": native.MAX_STDERR,
    "codex-home/config.toml": 64 << 10,
    "codex-home/environments.toml": 64 << 10,
}


def _write(path, value):
    raw = role.encoded(value) + b"\n"
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    if os.name == "posix":
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _read(path, cap=64 << 10):
    return evidence._parse(evidence._read(path, cap), cap)


def _files(root):
    result = {}
    for name, cap in FILES.items():
        path = root / name
        if path.exists() or path.is_symlink():
            result[name] = hashlib.sha256(evidence._read(path, cap)).hexdigest()
    return result


def _context(host, phase):
    if phase not in PHASES:
        raise ValueError("unknown fixed auditor phase")
    seal = study.verify(host.camp, host.terms)
    config = host.terms.get("fixed_auditor")
    role.validate_descriptor(config)
    selected = protocol.campaign_profile(host.camp, host.terms)
    if selected is None or selected.protocol != protocol.H_PROTOCOL:
        raise ValueError("fixed auditor requires the sealed H-only episode profile")
    if (host.terms.get("model"), host.terms.get("effort")) != (role.MODEL, role.EFFORT):
        raise ValueError("fixed auditor requires Luna/max study terms")
    descriptor = host.terms["study"]
    if set(descriptor) != {"manifest_path", "manifest_sha256"}:
        raise ValueError("invalid fixed auditor study identity")
    root = host.camp / "fixed-auditor" / phase
    if root.is_symlink() or root.parent.is_symlink():
        raise ValueError("redirected fixed auditor root")
    return seal, config, root


def _identity(host, phase, packs, evidence_receipts, config, *, receipt_schema=2):
    if type(receipt_schema) is not int or receipt_schema not in (1, 2):
        raise ValueError("unsupported fixed auditor receipt schema")
    service = role.EvidenceService(packs)
    if len(packs) != PHASES[phase] or len(evidence_receipts) != len(packs):
        raise ValueError("fixed auditor phase evidence count differs")
    role.output_schema(service.packs)
    service.prompt()
    for pack, receipt in zip(packs, evidence_receipts, strict=True):
        if (
            not isinstance(receipt, dict)
            or receipt.get("pack_sha256") != pack.digest
            or receipt.get("submission_sha256") != pack.submission_sha256
        ):
            raise ValueError("fixed auditor private evidence receipt differs from pack")
    identity = {
        "role": "fixed_auditor",
        "phase": phase,
        "model": role.MODEL,
        "effort": role.EFFORT,
        "deadline_secs": role.DEADLINE,
        "study_sha256": host.terms["study"]["manifest_sha256"],
        "episode_protocol": protocol.H_PROTOCOL,
        "plan_sha256": host.terms["ph_supervisor"]["plan_sha256"],
        "configuration_sha256": role.digest(config),
        "native_sha256": host.terms["codex_sha256"],
        "packs": [
            {
                "pack_sha256": pack.digest,
                "submission_sha256": pack.submission_sha256,
                "evidence_receipt_sha256": role.digest(receipt),
            }
            for pack, receipt in zip(service.packs, evidence_receipts, strict=True)
        ],
    }
    if receipt_schema == 2:
        identity["receipt_schema"] = 2
    if len(role.encoded(identity)) > 16 << 10:
        raise ValueError("fixed auditor identity exceeds bound")
    return identity


def _reservation(host, seal, key, identity, receipt):
    budget.status(
        host.camp / "study-budget.sqlite",
        host.terms["study"]["manifest_sha256"],
        seal["limits"],
    )
    encoded, binding = budget._binding(
        identity["study_sha256"],
        key,
        "learning",
        role.DEADLINE,
        seal["limits"],
        identity,
    )
    expected = {
        "id": receipt["id"],
        "key": key,
        "study_sha256": identity["study_sha256"],
        "kind": "learning",
        "deadline_secs": role.DEADLINE,
        "binding_sha256": binding,
    }
    if receipt != expected:
        raise ValueError("fixed auditor reservation receipt differs")
    with closing(
        sqlite3.connect(
            (host.camp / "study-budget.sqlite").resolve().as_uri() + "?mode=ro",
            uri=True,
        )
    ) as database:
        rows = database.execute(
            "SELECT kind,deadline_secs,identity_json,receipt_id,binding_sha256 "
            "FROM reservations WHERE key=?",
            (key,),
        ).fetchall()
    if rows != [("learning", role.DEADLINE, encoded, receipt["id"], binding)]:
        raise ValueError("fixed auditor reservation is not in the sealed budget")


def audit_reservation(host, seal, key, identity, receipt):
    """Cost audit without evidence bytes; full acceptance additionally requires verify()."""
    if not isinstance(key, str) or key not in {
        f"fixed-auditor/{phase}" for phase in PHASES
    }:
        raise ValueError("invalid fixed auditor budget key")
    phase = key.split("/")[1]
    checked_seal, config, root = _context(host, phase)
    if seal != checked_seal:
        raise ValueError("fixed auditor seal differs")
    expected_keys = {
        "role",
        "phase",
        "model",
        "effort",
        "deadline_secs",
        "study_sha256",
        "configuration_sha256",
        "native_sha256",
        "packs",
        "episode_protocol",
        "plan_sha256",
    }
    receipt_schema = (
        identity.get("receipt_schema", 1) if isinstance(identity, dict) else None
    )
    if type(receipt_schema) is not int or receipt_schema not in (1, 2):
        raise ValueError("unsupported fixed auditor receipt schema")
    if receipt_schema == 2:
        expected_keys.add("receipt_schema")
    if (
        not isinstance(identity, dict)
        or set(identity) != expected_keys
        or identity["role"] != "fixed_auditor"
        or identity["phase"] != phase
        or identity["model"] != role.MODEL
        or identity["effort"] != role.EFFORT
        or identity["deadline_secs"] != role.DEADLINE
        or identity["study_sha256"] != host.terms["study"]["manifest_sha256"]
        or identity["episode_protocol"] != protocol.H_PROTOCOL
        or identity["plan_sha256"] != host.terms["ph_supervisor"]["plan_sha256"]
        or identity["configuration_sha256"] != role.digest(config)
        or identity["native_sha256"] != host.terms["codex_sha256"]
        or not isinstance(identity["packs"], list)
        or len(identity["packs"]) != PHASES[phase]
        or any(
            not isinstance(row, dict)
            or set(row)
            != {"pack_sha256", "submission_sha256", "evidence_receipt_sha256"}
            or not all(evidence._sha(value) for value in row.values())
            for row in identity["packs"]
        )
    ):
        raise ValueError("fixed auditor reservation identity differs")
    _reservation(host, seal, key, identity, receipt)
    claim = _read(root / "claim.json")
    if claim != {"schema": 1, "identity": identity, "reservation": receipt}:
        raise ValueError("fixed auditor claim differs")
    terminal = _read(root / "receipt.json", 1 << 20)
    if (
        type(terminal.get("schema")) is not int
        or terminal["schema"] != receipt_schema
        or receipt_schema == 2
        and "validation_error" not in terminal
        or terminal.get("phase") != phase
        or terminal.get("identity") != identity
        or terminal.get("identity_sha256") != role.digest(identity)
        or terminal.get("reservation") != receipt
        or terminal.get("files") != _files(root)
        or terminal.get("native") != _read(root / "native.json")
        or terminal.get("outcome") not in ("accepted", "rejected", "unknown")
    ):
        raise ValueError("fixed auditor terminal evidence differs")
    if terminal["native"]["status"] == "completed":
        required = {
            "final.json",
            "evidence-served.jsonl",
            "rpc.jsonl",
            "stdout.log",
            "stderr.log",
            "codex-home/config.toml",
            "codex-home/environments.toml",
        }
        if not required <= terminal["files"].keys():
            raise ValueError("completed fixed auditor lacks native evidence files")
        actual = evidence._read(root / "codex-home/config.toml", 64 << 10).decode()
        environments = evidence._read(
            root / "codex-home/environments.toml", 64 << 10
        ).decode()
        if (
            actual != role.config(config["routing"])
            or environments != "include_local = false\n"
        ):
            raise ValueError("fixed auditor native configuration changed")
    return terminal


def execute(host, phase, packs, evidence_receipts):
    """Reserve and claim before exactly one native launch; terminal replay never relaunches."""
    seal, config, root = _context(host, phase)
    identity = _identity(host, phase, packs, evidence_receipts, config)
    if root.exists():
        return verify(host, phase, packs, evidence_receipts)
    provider = config["routing"]
    if not PAID_ENABLED and urlsplit(provider["base_url"]).hostname not in (
        "127.0.0.1",
        "::1",
        "localhost",
    ):
        raise RuntimeError(
            "paid fixed auditor remains disabled pending controller integration"
        )
    native.ambient_preflight()
    if provider["env_key"] == "OPENAI_API_KEY":
        from procontract_benchmark_runner import current_key

        credential = current_key(os.environ)
    else:
        credential = os.environ.get(provider["env_key"])
    if not isinstance(credential, str) or not credential or len(credential) > 16384:
        raise ValueError("fixed auditor credential missing or excessive")
    root.mkdir(parents=True, mode=0o700)
    key = f"fixed-auditor/{phase}"
    receipt = budget.reserve(
        host.camp / "study-budget.sqlite",
        identity["study_sha256"],
        key,
        "learning",
        role.DEADLINE,
        seal["limits"],
        identity,
    )
    _write(root / "study-launch.json", receipt)
    _write(
        root / "claim.json", {"schema": 1, "identity": identity, "reservation": receipt}
    )
    service = role.EvidenceService(packs)
    raw, terminal = native.run(
        Path(host.terms["codex_bin"]), root, service, provider, credential
    )
    if raw is not None:
        with (root / "final.json").open("xb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
    _write(root / "native.json", terminal)
    findings, outcome, validation_error = [], "unknown", None
    if (
        terminal["status"] == "completed"
        and terminal["native_exit"] == 0
        and raw is not None
    ):
        try:
            findings = service.validate(raw)
            outcome = _decision(findings, raw)
        except ValueError as error:
            validation_error = _validation_error(error)
    result = {
        "schema": identity.get("receipt_schema", 1),
        "phase": phase,
        "identity": identity,
        "identity_sha256": role.digest(identity),
        "reservation": receipt,
        "native": terminal,
        "findings": findings,
        "outcome": outcome,
        "files": _files(root),
    }
    if result["schema"] == 2:
        result["validation_error"] = validation_error
    _write(root / "receipt.json", result)
    return verify(host, phase, packs, evidence_receipts)


def _decision(findings, raw):
    if all(row["accepted"] for row in findings):
        return "accepted"
    results = evidence._parse(raw, evidence.MAX_RESULT * 8)["audits"]
    violation = any(
        any(
            finding["status"] == "violation"
            for finding in result["requirements"].values()
        )
        or any(
            finding["classification"] == "violation"
            for finding in result["opaque_files"]
        )
        for result in results
    )
    return "rejected" if violation else "unknown"


def _validation_error(error):
    """Private bounded diagnostic, not a judgment or permission to retry."""
    raw = str(error)[:513].encode("utf-8", errors="replace")
    return {
        "type": "ValueError",
        "message": raw[:512].decode("utf-8", errors="ignore"),
        "truncated": len(raw) > 512,
    }


def verify(host, phase, packs, evidence_receipts):
    """Authenticate terminal custody, replay exact tool service, and recheck final citations."""
    seal, config, root = _context(host, phase)
    recorded = _read(root / "claim.json")["identity"]
    identity = _identity(
        host,
        phase,
        packs,
        evidence_receipts,
        config,
        receipt_schema=recorded.get("receipt_schema", 1),
    )
    receipt = _read(root / "study-launch.json")
    terminal = audit_reservation(
        host, seal, f"fixed-auditor/{phase}", identity, receipt
    )
    service = role.EvidenceService(packs)
    findings, outcome, validation_error = [], "unknown", None
    native_receipt = terminal["native"]
    if native_receipt["status"] == "completed" and native_receipt["native_exit"] == 0:
        raw = evidence._read(root / "evidence-served.jsonl", native.MAX_LOG)
        for line in raw.splitlines():
            row = evidence._parse(line, native.MAX_LINE)
            if (
                not isinstance(row, dict)
                or set(row) != {"arguments", "authorized", "success", "response_sha256"}
                or type(row["authorized"]) is not bool
            ):
                raise ValueError("fixed auditor evidence service log differs")
            text, success = (
                service.call(row["arguments"])
                if row["authorized"]
                else ("Refused: unexpected tool or thread/turn identity.", False)
            )
            if (
                success != row["success"]
                or hashlib.sha256(text.encode()).hexdigest() != row["response_sha256"]
            ):
                raise ValueError("fixed auditor evidence service replay differs")
        result = evidence._read(root / "final.json", evidence.MAX_RESULT * len(packs))
        if native_receipt["final_sha256"] != hashlib.sha256(result).hexdigest():
            raise ValueError("native final result digest differs")
        try:
            findings = service.validate(result)
            outcome = _decision(findings, result)
        except ValueError as error:
            validation_error = _validation_error(error)
    if terminal["schema"] == 2 and role.encoded(
        terminal["validation_error"]
    ) != role.encoded(validation_error):
        raise ValueError("fixed auditor validation diagnostic changed")
    if terminal["outcome"] != outcome or terminal["findings"] != findings:
        raise ValueError("fixed auditor result or served coverage changed")
    return terminal
