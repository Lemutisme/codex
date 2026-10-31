#!/usr/bin/env python3
"""Durable execution/evidence capabilities, without a research workflow.

The protected host creates Authority and Measurement objects. Untrusted callers
select operations; they cannot supply provenance, replace evaluators or mint grants.
This journal is not another settlement kernel. Kernel commands use the existing
pro-contract-store, and adoption uses its atomic, fenced transaction.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

import procontract_store as kernel

IMPLEMENTATION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else encoded(value).encode()).hexdigest()


def atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x") as stream:
        stream.write(encoded(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        if stat[0] == "Z":
            return None
        return {"pid": pid, "start_ticks": stat[19],
                "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(identity):
    return bool(identity and process_identity(identity["pid"]) == identity)


def group_alive(pgid):
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = path.read_text().rsplit(') ', 1)[1].split()
            if int(fields[2]) == pgid and fields[0] != 'Z':
                return True
        except (FileNotFoundError, ProcessLookupError):
            pass
    return False


@dataclasses.dataclass(frozen=True)
class Authority:
    """Host-authenticated standing authorization; never accepted from a tool request."""
    principal: str
    source: str
    scope: str
    editable: tuple[str, ...]
    measurements: tuple[str, ...]
    allow_adoption: bool = False
    deadline: float | None = None
    operation_limit: int | None = None
    version_fields: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Measurement:
    """An admitted runner identity, not a workflow stage or numeric quality gate.

    The command receives assignment.json and writes result.json. It owns its
    measurement semantics; the host independently retains exit/lifecycle validity.
    beyond_reach is set by the provisioner only for actually sealed inputs.
    """
    argv: tuple[str, ...]
    identity: str
    environment: str
    beyond_reach: bool = False
    max_seconds: float | None = None
    external_effects: bool = False
    effect_scope: str | None = None


class Operations:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.db = self.root / "operations.sqlite"
        self.store = self.root / "kernel"
        self.config = json.loads((self.root / "host.json").read_text())
        self.authority = Authority(**self.config["authority"])

    @classmethod
    def create(cls, root, authority: Authority, measurements: dict[str, Measurement]):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        config = {"schema": 1, "implementation": IMPLEMENTATION, "authority": dataclasses.asdict(authority),
                  "measurements": {k: dataclasses.asdict(v) for k, v in measurements.items()}}
        for cap in config["measurements"].values():
            cap["sources"] = {arg: sha(Path(arg).read_bytes()) for arg in cap["argv"] if Path(arg).is_file()}
        if set(authority.measurements) - measurements.keys():
            raise ValueError("authority references an unavailable measurement")
        path = root / "host.json"
        if path.exists():
            if json.loads(path.read_text()) != json.loads(encoded(config)):
                raise ValueError("original authority/configuration cannot be renewed")
        else:
            atomic(path, config)
        host = cls(root)
        with host.tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS objects (id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source TEXT NOT NULL, object_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, request TEXT NOT NULL, state TEXT NOT NULL, owner TEXT, outcome TEXT);
                CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, source TEXT NOT NULL, kinds TEXT NOT NULL, cursor INTEGER NOT NULL, pending INTEGER, epoch INTEGER NOT NULL, cancelled INTEGER NOT NULL, wake TEXT);
                CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, request TEXT NOT NULL, command TEXT, result TEXT);
            """)
        return host

    @contextlib.contextmanager
    def tx(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def allowed(self):
        if self.config.get("implementation") != IMPLEMENTATION:
            raise ValueError("host implementation changed; explicit migration required before new work")
        if self.authority.deadline is not None and time.time() >= self.authority.deadline:
            raise ValueError("original host allocation exhausted")

    @contextlib.contextmanager
    def authority_lock(self):
        # Owner cancellation and an admitted settlement have a single ordering.
        # This does not hold the operation database while invoking the kernel.
        with (self.root / "authority.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def put(self, kind, body, *, source="host", notify=True):
        identity = sha({"schema": 1, "kind": kind, "body": body})
        with self.tx() as db:
            fresh = db.execute("INSERT OR IGNORE INTO objects VALUES (?,?,?)", (identity, kind, encoded(body))).rowcount
            if fresh and notify:
                self._event(db, kind, source, identity)
        return identity

    @staticmethod
    def _event(db, kind, source, identity):
        seq = db.execute("INSERT INTO events(kind,source,object_id) VALUES(?,?,?)", (kind, source, identity)).lastrowid
        for row in db.execute("SELECT * FROM inbox WHERE cancelled=0"):
            wake = json.loads(row["wake"]) if row["wake"] else {}
            if (row["source"] in ("*", source) and kind in json.loads(row["kinds"])
                    and wake.get("event", kind) == kind and seq > row["cursor"]):
                db.execute("UPDATE inbox SET pending=? WHERE id=?", (seq, row["id"]))
        return seq

    def get(self, identity, kind=None):
        with self.tx() as db:
            row = db.execute("SELECT * FROM objects WHERE id=?", (identity,)).fetchone()
        if row is None or (kind is not None and row["kind"] != kind):
            raise ValueError("missing object or incorrect kind")
        body = json.loads(row["body"])
        if sha({"schema": 1, "kind": row["kind"], "body": body}) != identity:
            raise ValueError("object identity differs")
        return body

    def read(self, after=0, kinds=None, limit=100):
        if not 1 <= limit <= 1000:
            raise ValueError("page limit must be in 1..1000")
        with self.tx() as db:
            rows = db.execute("SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
        return {"cursor": rows[-1]["seq"] if rows else after,
                "events": [dict(r) for r in rows if kinds is None or r["kind"] in kinds]}

    def register(self, definition, parent=None):
        """New definitions do not reinterpret legacy RSI bundle IDs."""
        self.allowed()
        definition = json.loads(encoded(definition))
        if set(definition) != {"kind", "files", "build", "model", "resolver", "tools"}:
            raise ValueError("version needs kind/files/build/model/resolver/tools")
        if definition["kind"] not in ("task", "research", "harness"):
            raise ValueError("unknown version purpose")
        for name, content in definition["files"].items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not path.parts or not isinstance(content, str):
                raise ValueError("invalid version file")
        if parent:
            prior = self.get(parent, "version")["definition"]
            if definition["kind"] != prior["kind"]:
                raise ValueError("task and research lineage must remain separate")
            changed = {k for k in set(prior["files"]) | set(definition["files"])
                       if prior["files"].get(k) != definition["files"].get(k)}
            if changed - set(self.authority.editable):
                raise ValueError("change exceeds authorized file scope")
            if any(definition[k] != prior[k] and k not in self.authority.version_fields for k in ("build", "model", "resolver", "tools")):
                raise ValueError("this grant does not authorize build/model/resolver/tool replacement")
        body = {"schema": "procontract_version_v2", "definition": definition,
                "files": {k: sha(v.encode()) for k, v in definition["files"].items()}, "parent": parent}
        return self.put("version", body)

    def resolved(self, version, instructions, sources, conditions):
        self.get(version, "version")
        # Actual instruction bytes, retrieved identities and run conditions are
        # independent of the reproducible version definition.
        return self.put("resolved_input", {"version": version, "instructions": instructions,
                        "sources": sources, "conditions": conditions})

    def observation(self, subject, sources, conditions, outcome, costs, *, source, claim=False):
        return self.put("claim" if claim else "observation", {
            "subject": subject, "sources": sources, "conditions": conditions,
            "outcome": outcome, "costs": costs}, source=source)

    def knowledge(self, subject, sources, interpretation, uncertainty, supersedes=None):
        for item in sources:
            self.get(item)
        if supersedes:
            self.get(supersedes, "knowledge")
        return self.put("knowledge", {"subject": subject, "sources": sources,
                        "interpretation": interpretation, "uncertainty": uncertainty,
                        "supersedes": supersedes})

    def subscribe(self, responsibility, source, kinds, cursor=0):
        """Select event inputs; this does not choose when or how to analyze them."""
        with self.tx() as db:
            old = db.execute("SELECT * FROM inbox WHERE id=?", (responsibility,)).fetchone()
            if old:
                if old["source"] != source or json.loads(old["kinds"]) != kinds:
                    raise ValueError("subscription already admitted")
                return dict(old)
            matches = [r["seq"] for r in db.execute("SELECT * FROM events WHERE seq>?", (cursor,))
                       if r["kind"] in kinds and source in ("*", r["source"])]
            db.execute("INSERT INTO inbox VALUES (?,?,?,?,?,0,0,NULL)",
                       (responsibility, source, encoded(kinds), cursor, max(matches) if matches else None))
        return self.inbox(responsibility)

    def inbox(self, responsibility):
        with self.tx() as db:
            row = db.execute("SELECT * FROM inbox WHERE id=?", (responsibility,)).fetchone()
        return dict(row) if row else None

    def decision_failed(self, responsibility, error):
        # Neither the cursor nor the pending input is acknowledged by a failed selector.
        return self.put("decision_failure", {"responsibility": responsibility, "error": error,
                        "at": time.time()}, source=responsibility)

    def wait(self, responsibility, epoch, through, condition):
        """Durably acknowledge selected input and wait for a selected event/time.

        A timestamp is an optional wake condition, never a task deadline.
        """
        if set(condition) - {"after", "event"}:
            raise ValueError("unknown wake condition")
        with self.tx() as db:
            row = db.execute("SELECT * FROM inbox WHERE id=?", (responsibility,)).fetchone()
            if not row or row["cancelled"] or row["epoch"] != epoch or through < row["cursor"] or through > (row["pending"] or row["cursor"]):
                raise ValueError("stale or unauthorized wait")
            pending = row["pending"] if (row["pending"] or 0) > through else None
            db.execute("UPDATE inbox SET cursor=?,pending=?,wake=? WHERE id=?", (through, pending, encoded(condition), responsibility))
        return self.inbox(responsibility)

    def wakes(self):
        with self.tx() as db:
            rows = db.execute("SELECT * FROM inbox WHERE cancelled=0").fetchall()
        ready = []
        for row in rows:
            condition = json.loads(row["wake"]) if row["wake"] else {}
            if row["pending"] is not None or (condition.get("after") is not None and time.time() >= condition["after"]):
                ready.append(dict(row))
        return ready

    def cancel_responsibility(self, responsibility):
        with self.authority_lock(), self.tx() as db:
            db.execute("UPDATE inbox SET epoch=epoch+1,cancelled=1 WHERE id=?", (responsibility,))
            ids = [r["id"] for r in db.execute("SELECT * FROM operations WHERE state IN ('reserved','running')")
                   if json.loads(r["request"])["request"]["responsibility"] == responsibility]
        for identity in ids:
            self.cancel(identity)

    def submit(self, identity, responsibility, version, measurement, inputs, purpose,
               seconds=None, resolved_input=None):
        self.get(version, "version")
        if resolved_input and self.get(resolved_input, "resolved_input")["version"] != version:
            raise ValueError("resolved input belongs to a different version")
        if measurement not in self.authority.measurements:
            raise ValueError("measurement is not authorized")
        cap = self.config["measurements"][measurement]
        if seconds is not None and (isinstance(seconds, bool) or not math.isfinite(seconds) or seconds <= 0):
            raise ValueError("action allocation must be positive")
        request = {"id": identity, "responsibility": responsibility, "version": version,
                   "measurement": measurement, "inputs": inputs, "purpose": purpose,
                   "seconds": seconds, "resolved_input": resolved_input}
        with self.tx() as db:
            old = db.execute("SELECT * FROM operations WHERE id=?", (identity,)).fetchone()
            if old:
                saved = json.loads(old["request"])
                if saved["request"] != request:
                    raise ValueError("operation ID conflicts with its original assignment")
                return {k: json.loads(old[k]) if k in ("request", "owner", "outcome") and old[k] else old[k] for k in old.keys()}
            self.allowed()
            inbox = db.execute("SELECT * FROM inbox WHERE id=?", (responsibility,)).fetchone()
            if not inbox or inbox["cancelled"]:
                raise ValueError("responsibility is unavailable or cancelled")
            count = db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            if self.authority.operation_limit is not None and count >= self.authority.operation_limit:
                raise ValueError("original operation allowance exhausted")
            scope = cap.get("effect_scope")
            if scope is not None:
                for prior in db.execute("SELECT * FROM operations"):
                    if json.loads(prior["request"])["measurement"].get("effect_scope") != scope:
                        continue
                    outcome = json.loads(prior["outcome"]) if prior["outcome"] else None
                    if prior["state"] in ("reserved", "running", "unknown") or (outcome and not outcome["shutdown_confirmed"]):
                        raise ValueError("conflicting effect scope is active or unresolved; reconcile before dispatch")
            limits = [v for v in (seconds, cap["max_seconds"]) if v is not None]
            ends = [v for v in (time.time() + min(limits) if limits else None, self.authority.deadline) if v is not None]
            assignment = {"request": request, "admitted_at": time.time(),
                          "deadline": min(ends) if ends else None, "owner_epoch": inbox["epoch"],
                          "implementation": self.config.get("implementation"),
                          "authority": sha(self.config["authority"]), "measurement": cap}
            db.execute("INSERT INTO operations VALUES (?,?, 'reserved',NULL,NULL)", (identity, encoded(assignment)))
        return self.inspect(identity)

    def inspect(self, identity):
        with self.tx() as db:
            row = db.execute("SELECT * FROM operations WHERE id=?", (identity,)).fetchone()
        if not row:
            raise ValueError("operation missing")
        return {k: json.loads(row[k]) if k in ("request", "owner", "outcome") and row[k] else row[k] for k in row.keys()}

    def operation_dir(self, identity):
        return self.root / "runs" / sha(identity)

    def dispatch(self, identity):
        item = self.inspect(identity)
        if item["state"] != "reserved":
            return self.reconcile(identity)
        # Duplicate launcher delivery is harmless: workers CAS the reservation
        # before any external action. Unknown running work is never re-dispatched.
        directory = self.operation_dir(identity)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "worker.log").open("ab") as log:
            worker = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "worker", str(self.root), identity],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            threading.Thread(target=worker.wait, daemon=True).start()
        return self.inspect(identity)

    def cancel(self, identity):
        self.inspect(identity)
        atomic(self.operation_dir(identity) / "cancel.json", {"requested_at": time.time()})
        return self.inspect(identity)

    def reconcile(self, identity):
        with self.authority_lock():
            return self._reconcile(identity)

    def _reconcile(self, identity):
        item = self.inspect(identity)
        directory = self.operation_dir(identity)
        receipt = directory / "receipt.json"
        child_path = directory / "child.json"
        if (not receipt.exists() and item["state"] in ("running", "unknown")
                and not alive(item["owner"]) and child_path.exists()
                and not item["request"]["measurement"].get("external_effects")):
            child = json.loads(child_path.read_text())
            if child and not alive(child) and not group_alive(child["pid"]):
                # Known local lifetime, unknown result. This never re-dispatches
                # the action or invents measurement/quality from its partial files.
                atomic(receipt, {"id": identity, "assignment": sha(item["request"]),
                    "execution": "interrupted", "shutdown_confirmed": True, "measurement": None,
                    "reason": "lost owner; recorded local child and its group have ended",
                    "observer": IMPLEMENTATION,
                    "reconciled_at": time.time()})
        if receipt.exists():
            value = json.loads(receipt.read_text())
            if value["assignment"] != sha(item["request"]):
                raise ValueError("receipt belongs to another assignment")
            with self.tx() as db:
                row = db.execute("SELECT state FROM operations WHERE id=?", (identity,)).fetchone()
                if row["state"] != "finished":
                    object_id = sha({"schema": 1, "kind": "operation_outcome", "body": value})
                    db.execute("INSERT OR IGNORE INTO objects VALUES (?, 'operation_outcome', ?)", (object_id, encoded(value)))
                    db.execute("UPDATE operations SET state='finished', outcome=? WHERE id=?", (encoded({"object": object_id, **value}), identity))
                    self._event(db, "operation_outcome", item["request"]["request"]["responsibility"], object_id)
        elif item["state"] == "running" and not alive(item["owner"]):
            with self.tx() as db:
                value = {"id": identity, "assignment": sha(item["request"]), "execution": "unknown",
                         "shutdown_confirmed": False, "measurement": None,
                         "observer": IMPLEMENTATION,
                         "reason": "operation owner disappeared without a retained receipt"}
                object_id = sha({"schema": 1, "kind": "operation_outcome", "body": value})
                changed = db.execute("UPDATE operations SET state='unknown',outcome=? WHERE id=? AND state='running'",
                                     (encoded({"object": object_id, **value}), identity)).rowcount
                if changed:
                    db.execute("INSERT OR IGNORE INTO objects VALUES (?, 'operation_outcome', ?)", (object_id, encoded(value)))
                    self._event(db, "operation_outcome", item["request"]["request"]["responsibility"], object_id)
        return self.inspect(identity)

    def run_worker(self, identity):
        with self.tx() as db:
            row = db.execute("SELECT * FROM operations WHERE id=?", (identity,)).fetchone()
            if row is None or row["state"] != "reserved":
                return
            assignment = json.loads(row["request"])
            request = assignment["request"]
            inbox = db.execute("SELECT * FROM inbox WHERE id=?", (request["responsibility"],)).fetchone()
            owner_invalid = inbox["cancelled"] or inbox["epoch"] != assignment["owner_epoch"]
            db.execute("UPDATE operations SET state='running',owner=? WHERE id=?", (encoded(process_identity(os.getpid())), identity))
        directory = self.operation_dir(identity)
        directory.mkdir(parents=True, exist_ok=True)
        version = self.get(request["version"], "version")
        atomic(directory / "assignment.json", {**assignment, "version": version})
        started = time.time()
        receipt = {"id": identity, "assignment": sha(assignment), "started": started,
                   "execution": "unknown", "shutdown_confirmed": False, "measurement": None}
        child = None
        try:
            deadline = assignment["deadline"]
            sources = assignment["measurement"].get("sources", {})
            if assignment.get("implementation") != IMPLEMENTATION or any(
                    not Path(p).is_file() or sha(Path(p).read_bytes()) != digest for p, digest in sources.items()):
                receipt.update(execution="configuration_changed", shutdown_confirmed=True)
            elif deadline is not None and time.time() >= deadline:
                receipt.update(execution="expired", shutdown_confirmed=True)
            elif owner_invalid or (directory / "cancel.json").exists():
                receipt.update(execution="cancelled", shutdown_confirmed=True)
            else:
                with (directory / "stdout").open("wb") as out, (directory / "stderr").open("wb") as err:
                    child = subprocess.Popen([*assignment["measurement"]["argv"], str(directory / "assignment.json")],
                                             cwd=directory, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                             start_new_session=True)
                    atomic(directory / "child.json", process_identity(child.pid))
                    while child.poll() is None:
                        reason = ("cancelled" if (directory / "cancel.json").exists() else
                                  "timed_out" if deadline is not None and time.time() >= deadline else None)
                        if reason:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                            receipt["execution"] = reason
                            break
                        time.sleep(0.025)
                    else:
                        receipt["execution"] = "completed" if child.returncode == 0 else "failed"
                    receipt.update(exit_code=child.returncode, shutdown_confirmed=True)
                result = directory / "result.json"
                if result.exists():
                    receipt["measurement"] = json.loads(result.read_text())
        except Exception as error:
            receipt["error"] = str(error)
            if child is None:
                receipt.update(execution="failed_to_start", shutdown_confirmed=True)
        finally:
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                receipt["shutdown_confirmed"] = True
            if child is not None and group_alive(child.pid):
                os.killpg(child.pid, signal.SIGKILL)
                until = time.monotonic() + 5
                while group_alive(child.pid) and time.monotonic() < until:
                    time.sleep(.025)
                receipt["shutdown_confirmed"] = not group_alive(child.pid)
            if child is not None and assignment["measurement"].get("external_effects"):
                # A local client's exit cannot attest remote/container lifetime.
                # Only the admitted adapter's retained observation can do so.
                receipt["shutdown_confirmed"] &= (receipt["measurement"] or {}).get("effects_resolved") is True
            receipt.update(finished=time.time(), elapsed_seconds=time.time() - started)
            receipt["streams"] = {name: sha((directory / name).read_bytes()) for name in ("stdout", "stderr") if (directory / name).exists()}
            atomic(directory / "receipt.json", receipt)
        self.reconcile(identity)

    def incumbent(self):
        rows = [r for r in kernel.events(self.store)
                if r["event"]["kind"] == "selection" and r["event"]["body"].get("role") == "incumbent"]
        return {"seq": rows[-1]["seq"], "version": rows[-1]["event"]["body"]["version"]} if rows else {"seq": None, "version": None}

    def issue(self, identity, terms):
        if kernel.contract(self.store, identity):
            return kernel.contract(self.store, identity)
        return kernel.apply(self.store, f"issue:{identity}", {
            "contract_id": identity, "expected_version": 0, "role": "issuer", "provenance": "delegate",
            "command": {"type": "issue", "owner": self.authority.principal,
                        "bindings": {"terms_hash": kernel.digest("terms", terms),
                                     "capture_policy_hash": kernel.digest("capture_policy", "version_v2"),
                                     "evidence_policy_hash": kernel.digest("evidence_policy", self.config)}}})

    def adopt(self, identity, version, expected_incumbent_seq, evidence, rationale, *, owner=None):
        """Select on host-qualified evidence; never accept a caller's reach/provenance."""
        with self.authority_lock():
            if owner is not None:
                inbox = self.inbox(owner[0])
                if not inbox or inbox["cancelled"] or inbox["epoch"] != owner[1]:
                    raise ValueError("decision owner has changed or cancelled")
            return self._adopt(identity, version, expected_incumbent_seq, evidence, rationale)

    def _adopt(self, identity, version, expected_incumbent_seq, evidence, rationale):
        request = {"version": version, "expected_incumbent_seq": expected_incumbent_seq,
                   "evidence": evidence, "rationale": rationale, "scope": self.authority.scope}
        with self.tx() as db:
            old = db.execute("SELECT * FROM decisions WHERE id=?", (identity,)).fetchone()
            if old and old["request"] != encoded(request):
                raise ValueError("decision ID conflicts")
            if old and old["result"]:
                return json.loads(old["result"])
        if old and old["command"]:
            command = json.loads(old["command"])
            if any(row["event"]["kind"] == "selection" and row["event"]["body"].get("adoption") == command["contract_id"]
                   for row in kernel.events(self.store)):
                # Reconcile a committed settlement, even if its caller lost the
                # acknowledgement and its allocation has since expired.
                result = kernel.adopt(self.store, f"adoption:{identity}", command, expected_incumbent_seq,
                                      kernel.identities(harness=self.config["implementation"]))
                with self.tx() as db:
                    db.execute("UPDATE decisions SET result=? WHERE id=?", (encoded(result), identity))
                return result
        self.allowed()
        if not self.authority.allow_adoption:
            raise ValueError("standing authorization does not permit adoption")
        definition = self.get(version, "version")["definition"]
        current = self.incumbent()["version"]
        if current and self.get(current, "version")["definition"]["kind"] != definition["kind"]:
            raise ValueError("version kind differs from this deployment scope")
        if not old:
            with self.tx() as db:
                db.execute("INSERT INTO decisions VALUES (?,?,NULL,NULL)", (identity, encoded(request)))
        # The public operation cannot create bootstrap authorization evidence.
        proof = self.get(evidence)
        if proof.get("version") == version and proof.get("authorization") == sha(self.config["authority"]):
            reach = "beyond"  # host-retained principal authorization, no quality claim
            measurement = {"identity": "initial_selection_authorization", "environment": self.authority.scope}
        else:
            receipt = proof
            assignment = self.inspect(receipt["id"])["request"]
            measurement = assignment["measurement"]
            if (assignment["request"]["version"] != version or receipt["execution"] != "completed"
                    or not receipt["shutdown_confirmed"] or not (receipt.get("measurement") or {}).get("admissible")
                    or not measurement["beyond_reach"]):
                raise ValueError("adoption lacks admitted beyond-reach evidence for this version")
            reach = "beyond"
        contract_id = f"selection.{sha(identity)[:32]}"
        terms = {"claim": "Select the exact version for the authorized scope on the recorded evidence",
                 "version": version, "scope": self.authority.scope, "source": self.authority.source,
                 "performance_claim": "Only the cited measurement conditions; no generalized superiority"}
        state = self.issue(contract_id, terms)
        if state["candidate"] is None:
            state = kernel.apply(self.store, f"propose:{contract_id}", {
                "contract_id": contract_id, "expected_version": state["version"], "role": "executor", "provenance": "automation",
                "command": {"type": "propose", "subject_hash": version}})
        if state["support"] is None:
            coordinate = {"contract_id": contract_id, "revision": state["revision"],
                **state["bindings"], "generation": state["candidate"]["generation"], "subject_hash": version,
                "environment_digest": kernel.digest("environment", measurement["environment"]),
                "evaluator_digest": kernel.digest("evaluator", measurement["identity"]),
                "evidence_hash": kernel.digest("evidence", proof), "basis": kernel.digest("basis", evidence), "reach": reach}
            state = kernel.apply(self.store, f"support:{contract_id}", {
                "contract_id": contract_id, "expected_version": state["version"], "role": "verifier", "provenance": "automation",
                "command": {"type": "support", "coordinate": coordinate, "certificate": kernel.digest("certificate", coordinate)}})
        with self.tx() as db:
            row = db.execute("SELECT command FROM decisions WHERE id=?", (identity,)).fetchone()
            command = json.loads(row["command"]) if row["command"] else {
                "contract_id": contract_id, "expected_version": state["version"], "role": "settler", "provenance": "delegate",
                "command": {"type": "discharge", "coordinate": state["support"]["coordinate"],
                            "attestation": kernel.digest("attestation", request), "decision": {"type": "presumed",
                            "convention": kernel.digest("convention", self.config["authority"]),
                            "classifier": kernel.digest("classifier", IMPLEMENTATION)}}}
            db.execute("UPDATE decisions SET command=? WHERE id=?", (encoded(command), identity))
        result = kernel.adopt(self.store, f"adoption:{identity}", command, expected_incumbent_seq,
                              kernel.identities(harness=IMPLEMENTATION))
        with self.tx() as db:
            db.execute("UPDATE decisions SET result=? WHERE id=?", (encoded(result), identity))
        return result

    def bootstrap(self, version):
        if self.incumbent()["version"] is not None:
            raise ValueError("bootstrap cannot replace an incumbent")
        evidence = self.put("authorization", {"version": version, "authorization": sha(self.config["authority"]),
                            "source": self.authority.source, "meaning": "authorized initial trial; no performance certification"})
        return self.adopt("bootstrap", version, None, evidence, "initial authorized trial")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["worker", "inspect", "reconcile"])
    parser.add_argument("root", type=Path)
    parser.add_argument("identity")
    args = parser.parse_args()
    host = Operations(args.root)
    if args.command == "worker":
        host.run_worker(args.identity)
    else:
        print(encoded(getattr(host, args.command)(args.identity)))


if __name__ == "__main__":
    main()
