#!/usr/bin/env python3
"""One non-restarting P/H episode: serve, unpaired probe/paired gate, adopted serve.

Terminal closure is NOT evidence of H action, submission compliance, isolated H benefit,
method improvement or general RSI advantage. Those require separate evidence audits.
Phase process-group containment is Linux-only; escaped sessions and daemon containers
are not covered. An interrupted or failed phase never authorizes a restart.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from procontract_ph_protocol import MAX_BYTES as MAX_BYTES
from procontract_ph_protocol import PH as PH
from procontract_ph_protocol import PROTOCOL
from procontract_ph_protocol import digest
from procontract_ph_protocol import document
from procontract_ph_protocol import plan_path as plan_path
from procontract_ph_protocol import publish
from procontract_ph_protocol import raw
from procontract_ph_protocol import require
from procontract_ph_protocol import validate_plan as validate_plan

SHUTDOWN_GRACE = 2.0
SHUTDOWN_WAIT = 5.0


def process_identity(pid):
    value = {"pid": pid, "observed_at": time.time()}
    try:
        value.update(
            start_ticks=int(
                Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
            ),
            boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        )
    except (OSError, ValueError, IndexError):
        value["start_ticks"] = None
    return value


class Supervisor:
    def __init__(self, args):
        self.args, self.camp = args, args.camp.resolve()
        self.root, self.active = self.camp / "ph-supervision", None
        self.group = self.pending_signal = None
        self.launching = self.stopping = False
        self.terminal = {
            "schema": 1,
            "protocol": PROTOCOL,
            "outcome": "unknown",
            "phases": [],
            "claim": "workflow closure only; H activation, compliance and causal benefit need independent audits",
            "automatic_restart": False,
        }

    def interrupted(self, signum, _frame):
        if self.launching or self.stopping:
            self.pending_signal = signum
            return
        raise InterruptedError(f"signal {signum}; no restart is authorized")

    def shutdown(self):
        # The leader remains unreaped until both signals: its PID cannot be reused.
        result = {
            "scope": "owned_group_only_not_escaped_sessions_or_daemon_containers",
            "pgid": self.group,
            "signals": [],
            "returncode": None,
        }
        self.stopping = True
        try:
            if self.group is None:
                result["status"] = "unverified_group_not_signalled"
                return result
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.group, sig)
                    outcome = "sent"
                except ProcessLookupError:
                    outcome = "absent"
                except OSError as error:
                    outcome = f"error:{error.errno}"
                result["signals"].append({"signal": sig.name, "result": outcome})
                if sig == signal.SIGTERM:
                    time.sleep(SHUTDOWN_GRACE)
            try:
                result["returncode"] = self.active.wait(timeout=SHUTDOWN_WAIT)
                self.active = None
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass
            result["status"] = (
                "signals_requested_leader_reaped"
                if type(result["returncode"]) is int
                and all(s["result"] in {"sent", "absent"} for s in result["signals"])
                else "unknown"
            )
            return result
        finally:
            self.stopping = False
            self.group = None

    def command(self, phase):
        require(
            sys.platform == "linux" and hasattr(os, "WNOWAIT"),
            "live process-group containment requires Linux; no paid launch",
        )
        directory = self.root / f"phase-{phase}"
        directory.mkdir()
        command = [
            sys.executable,
            str(Path(__file__).with_name("procontract_live.py")),
            "stream",
            "--camp",
            str(self.camp),
            "--study-sha256",
            self.args.study_sha256,
            "--count",
            "1",
        ]
        publish(directory / "intent.json", {"command": command, "at": time.time()})
        with (directory / "stdout.log").open("xb") as log:
            try:
                self.launching = True
                try:
                    self.active = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    pid = self.active.pid
                    require(
                        pid != os.getpid()
                        and pid != os.getpgrp()
                        and os.getpgid(pid) == os.getsid(pid) == pid,
                        "phase group ownership unverified; no retry",
                    )
                    self.group = pid
                finally:
                    self.launching = False
                publish(directory / "process.json", process_identity(pid))
                if self.pending_signal:
                    self.interrupted(self.pending_signal, None)
                ended = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
                code = (
                    ended.si_status
                    if ended.si_code == os.CLD_EXITED
                    else -ended.si_status
                )
            finally:
                if self.active is not None:
                    cleanup = self.shutdown()
                    self.terminal["group_cleanup"] = cleanup
                    publish(directory / "group-cleanup.json", cleanup)
            log.flush()
            os.fsync(log.fileno())
        publish(directory / "exit.json", {"returncode": code, "at": time.time()})
        if self.pending_signal:
            self.interrupted(self.pending_signal, None)
        require(
            cleanup["status"] == "signals_requested_leader_reaped",
            "phase group shutdown is unknown; no retry",
        )
        require(code == 0, "phase exited nonzero; no retry or additional study")

    def run(self):
        self.root.mkdir(exist_ok=False)
        publish(
            self.root / "claim.json",
            {
                "process": process_identity(os.getpid()),
                "study_sha256": self.args.study_sha256,
                "plan_sha256": self.args.plan_sha256,
                "source_sha256": digest(Path(__file__).resolve()),
            },
        )
        try:
            self.execute()
        except BaseException as error:
            outcome = self.terminal["outcome"]
            if outcome == "unknown":
                outcome = (
                    "adopted_continuation_invalid_or_unknown"
                    if self.terminal.get("current_phase") == 3
                    else "stopped_invalid_or_unknown"
                )
            self.terminal.update(
                outcome=outcome,
                error={"type": type(error).__name__, "message": str(error)[:500]},
            )
            if self.active is not None:
                self.terminal["unreconciled_child"] = {
                    **process_identity(self.active.pid),
                    "returncode_at_observation": self.active.poll(),
                }
        publish(self.root / "terminal.json", self.terminal)
        return self.terminal

    def execute(self):
        terms = document(self.camp / "campaign.json")
        require(
            terms["study"]["manifest_sha256"] == self.args.study_sha256
            and terms["ph_supervisor"]
            == {"plan_path": str(self.args.plan), "plan_sha256": self.args.plan_sha256},
            "operator pins differ from study",
        )
        validate_plan(self.camp, terms)
        raw_seal = raw(self.camp / "study.json", 16 << 20)
        require(
            hashlib.sha256(raw_seal).hexdigest() == self.args.study_sha256,
            "study differs from external pin",
        )
        manifest = document(self.camp / "study.json", 16 << 20)
        verifier = Path(__file__).resolve().with_name("procontract_study.py")
        require(
            manifest["files"][str(verifier)]["sha256"] == digest(verifier),
            "verifier source differs from seal",
        )
        import procontract_study as study

        sealed = study.verify(self.camp, terms)
        require(
            str(Path(__file__).resolve()) in sealed["files"]
            and str(plan_path(terms)) in sealed["files"],
            "supervisor source/plan missing from seal",
        )
        import procontract_rsi as rsi
        import procontract_succession as succession
        from procontract_ph_audit import Audit

        host = rsi.Host(self.camp)
        audit = Audit(host, sealed)
        require(
            not host.batches()
            and not host.events("execution")
            and not host.insights()
            and len(host.versions()) == 1
            and not any(audit.paid()["reserved"].values()),
            "campaign is not new and unspent",
        )
        require(
            not any(
                any(path.iterdir())
                for path in (
                    self.camp / "runs",
                    self.camp / "insight",
                    self.camp / "research",
                )
                if path.exists()
            ),
            "preexisting partial work; no automatic resume",
        )
        root, candidate = host.incumbent(), None
        sequence = succession.incumbent_record(host)["seq"]
        for phase in (1, 2, 3):
            self.terminal["current_phase"] = phase
            self.command(phase)
            study.verify(self.camp, terms)
            balance = audit.paid()
            require(
                balance["reserved"]["task_launches"] <= (1, 10, 11)[phase - 1]
                and balance["reserved"]["learning_launches"] <= (5, 9, 14)[phase - 1],
                "phase exceeded the predeclared launch envelope",
            )
            batches = host.batches()
            plans = [
                e for e in host.events("assignment") if "confirmation" in e["body"]
            ]
            require(
                len(plans) <= (0 if phase == 1 else 1)
                and len(host.events("assignment")) == phase + len(plans),
                "additional confirmation or assignment is not authorized",
            )
            require(
                len(batches) == phase
                and [b["batch"] for b in batches] == list(range(1, phase + 1)),
                "unexpected stream assignment",
            )
            batch = batches[-1]
            parent = candidate if phase == 3 else root
            version = candidate if phase == 2 else parent
            expected = {
                "batch": phase,
                "phase": "probe" if phase == 2 else "serve",
                "version": version,
                "expected_incumbent": parent,
                "expected_incumbent_seq": sequence,
                "tasks": [terms["stream"]["order"][phase - 1]],
            }
            require(
                batch == expected and host.order() == terms["stream"]["order"],
                "phase producer, authority or committed task differs",
            )
            results = [
                e["body"]
                for e in host.events("selection")
                if e["body"].get("role") == "guarded_batch_result"
                and e["body"].get("batch") == phase
            ]
            require(
                len(results) == 1
                and all(
                    results[0].get(k) == v for k, v in expected.items() if k != "tasks"
                ),
                "missing/ambiguous guarded terminal result",
            )
            result = results[0]
            require(
                len(
                    [
                        e
                        for e in host.events("selection")
                        if e["body"].get("role") == "guarded_batch_result"
                    ]
                )
                == phase,
                "unexpected guarded result outside this episode",
            )
            audit.task(version, batch["tasks"][0], "stream")
            summary = {"batch": batch, "result": result, "budget": balance}
            self.terminal["phases"].append(summary)
            if phase == 2:
                if result["outcome"] != "adopted":
                    self.terminal["outcome"] = "probe_rejected_or_inconclusive"
                    return
                summary["analysis"] = audit.analysis(batch)
                summary["confirmation"] = audit.adoption(candidate, root, sequence)
                sequence = succession.incumbent_record(host)["seq"]
                self.terminal["adopted_candidate"] = candidate
                continue
            require(
                result["outcome"] == "served" and host.incumbent() == parent,
                "serve did not retain its adopted authority",
            )
            if phase == 1 and result.get("candidate") is None:
                self.terminal["outcome"] = "initial_no_candidate_or_unqualified"
                return
            try:
                summary["analysis"] = audit.analysis(batch)
            except (RuntimeError, ValueError, OSError, KeyError):
                self.terminal["outcome"] = (
                    "adopted_continuation_analysis_failed"
                    if phase == 3
                    else "initial_analysis_failed"
                )
                raise
            try:
                summary["research"] = audit.research(
                    phase, parent, result.get("candidate")
                )
            except (RuntimeError, ValueError, OSError, KeyError):
                self.terminal["outcome"] = (
                    "adopted_continuation_research_failed_or_unqualified"
                    if phase == 3
                    else "initial_research_failed_or_unqualified"
                )
                raise
            if phase == 1:
                candidate = result["candidate"]
            else:
                self.terminal["outcome"] = (
                    "adopted_continuation_qualified_successor"
                    if result.get("candidate")
                    else "adopted_research_qualified_no_change"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camp", type=Path, required=True)
    parser.add_argument("--study-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()

    controller = Supervisor(args)
    signal.signal(signal.SIGINT, controller.interrupted)
    signal.signal(signal.SIGTERM, controller.interrupted)
    result = controller.run()
    print(json.dumps({"outcome": result["outcome"], "automatic_restart": False}))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
