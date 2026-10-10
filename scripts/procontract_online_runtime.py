"""Opt-in online learner attached to native Codex's public app-server run loop.

No hidden labels enter this controller. One native no-tool proposal, one fenced
checkpoint; experimental inheritance only. The executor allocation excludes the
research reservation even though research can run concurrently.
"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

from procontract_delivery_budget import DeliveryBudget
import procontract_harness_program as harness
import procontract_online as online
import procontract_online_worker as researcher


class OnlineRuntime:
    def __init__(
        self,
        lineage,
        episode,
        root,
        binary,
        provider,
        credential,
        *,
        total_secs=18000,
        research_secs=900,
        allocation=None,
    ):
        self.lineage, self.episode, self.root = lineage, episode, Path(root)
        self.binary, self.provider, self.credential = binary, provider, credential
        self.allocation = allocation or lineage.begin(
            episode, total_secs, research_secs
        )
        if allocation is not None:
            with lineage.transaction() as db:
                reserved = db.execute(
                    "SELECT body FROM events WHERE key=?", (f"episode:{episode}",)
                ).fetchone()
            if reserved is None or json.loads(reserved[0]) != allocation:
                raise ValueError("runtime allocation differs from durable selection")
        self.initial = lineage.version(self.allocation["parent"])
        if online.digest(self.initial) != self.allocation["parent"]:
            raise ValueError("initial program differs from reserved parent")
        self.trigger = harness.parse(online.encoded(self.initial["harness"]))
        self.root.mkdir(mode=0o700)
        self.cancel = threading.Event()
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="online-research"
        )
        self.future = self.budget = None
        self.candidate = None
        self.commands = []
        self.status = "observing"
        self.command_count = self.after_ack = 0
        self.commands_with_exit = self.failed_commands = 0
        self.dispatch_recorded = False
        self.research_receipt = None
        self.error = None
        self._terminal = None
        self._write("allocation.json", self.allocation)

    def _write(self, name, value):
        with (self.root / name).open("x", encoding="utf-8") as out:
            out.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
            out.flush()
            import os

            os.fsync(out.fileno())

    def observe(self, message, thread_id):
        if not thread_id:
            return
        params = message.get("params", {})
        if (
            message.get("method") != "item/completed"
            or params.get("threadId") != thread_id
        ):
            return
        item = params.get("item", {})
        if item.get("type") != "commandExecution":
            return
        self.command_count += 1
        if type(item.get("exitCode")) is int:
            self.commands_with_exit += 1
            self.failed_commands += int(item["exitCode"] != 0)
        if self.dispatch_recorded and self.status == "experimental":
            self.after_ack += 1
        self.commands.append(
            {
                "command": str(item.get("command", ""))[:180],
                "status": item.get("status"),
                "exit_code": item.get("exitCode"),
                "output": str(item.get("aggregatedOutput", ""))[:280],
            }
        )
        self.commands = self.commands[-3:]

    def poll(self, server, turns, status, handle, *, elapsed_secs):
        if status and status.get("resting") is True and not status.get("contract_id"):
            raise RuntimeError(
                "online learning requires an issued ProContract task contract"
            )
        if not status or not status.get("contract_id"):
            return
        if self.allocation["research_secs"] == 0:
            return
        remaining = self.allocation["executor_secs"] - elapsed_secs
        if self.cancel.is_set() or remaining <= 0:
            return
        if self.future is None and self.status == "observing":
            # Fixed permission to explore, not a claim that the current method failed.
            # Trigger only after observed native execution, with enough time left.
            if (
                not turns.active
                or elapsed_secs < 30
                or self.command_count < 4
                or remaining <= self.allocation["research_secs"] + 60
            ):
                return
            if not status or status.get("phase") in ("checking", "drafting"):
                return
            repairs = status.get("repairs_used")
            if type(repairs) is not int or repairs < 0:
                return
            facts = {
                "deadline_secs": self.allocation["executor_secs"],
                "remaining_secs": max(0, int(remaining)),
                "turns_completed": turns.completed,
                "repairs_used": repairs,
                "executor_command_completions_observed": self.command_count,
            }
            if not self.trigger.evaluate(facts):
                return
            observations = {
                "status": {
                    k: status.get(k) for k in ("phase", "resting", "repairs_used")
                },
                "commands": self.commands,
                "command_completions": self.command_count,
                "commands_with_exit": self.commands_with_exit,
                "failed_commands": self.failed_commands,
                "research_trigger": {"program": self.trigger.digest, "facts": facts},
                "remaining_secs": int(remaining),
                "scope": "observed_execution_not_hidden_reward",
            }
            # Trim by bytes rather than characters for non-ASCII tool output.
            while (
                len(online.encoded(observations)) > online.OBSERVATION_BYTES
                and observations["commands"]
            ):
                observations["commands"] = observations["commands"][1:]
            packet = self.lineage.claim(self.episode, observations)
            self._write("research-input.json", packet)
            worker = self.root / "worker"
            worker.mkdir(mode=0o700)
            self.status = "researching"
            self.future = self.pool.submit(
                researcher.run,
                self.binary,
                worker,
                packet,
                self.provider,
                self.credential,
                deadline_secs=self.allocation["research_secs"],
                cancellation=self.cancel,
            )
        if (
            self.future is not None
            and self.future.done()
            and self.status == "researching"
        ):
            try:
                raw, receipt = self.future.result()
                self.research_receipt = receipt
                self._write("research-receipt.json", receipt)
                if receipt["status"] != "completed" or raw is None:
                    raise ValueError("research did not complete; no retry")
                self._write("proposal.json", json.loads(raw))
                self.candidate = self.lineage.register(self.episode, raw)
                program = harness.parse(online.encoded(self.candidate["harness"]))
                self.budget = DeliveryBudget(
                    deadline_secs=self.allocation["executor_secs"],
                    program=program,
                    policy_notice=self.candidate["execution"],
                )
                self.status = "candidate"
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
                self.status, self.error = "rejected", str(error)[:500]
        if self.budget is not None and not self.dispatch_recorded:
            self.budget.maybe_steer(
                server,
                turns,
                status,
                handle,
                elapsed_secs=elapsed_secs,
                executor_command_completions_observed=self.command_count,
            )
            attempt = self.budget.summary()["attempt"]
            if attempt is not None:
                # Persist failures too. No second request on lost ACK.
                self.lineage.dispatch(self.episode, attempt)
                self.dispatch_recorded = True
                self.status = (
                    "experimental"
                    if attempt["outcome"] == "accepted"
                    else "not_applied"
                )
                self._write(
                    "dispatch.json",
                    {
                        "candidate": online.digest(self.candidate),
                        "attempt": attempt,
                        "activation": self.budget.activation,
                        "commands_at_ack": self.command_count,
                    },
                )

    def close(self):
        if self._terminal is not None:
            return self._terminal
        self.cancel.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        if (
            self.future is not None
            and self.research_receipt is None
            and not self.future.cancelled()
        ):
            try:
                _, self.research_receipt = self.future.result()
                self._write("research-receipt.json", self.research_receipt)
            except (ValueError, RuntimeError, OSError) as error:
                self.error = str(error)[:500]
        result = {
            "status": self.status,
            "error": self.error,
            "allocation": self.allocation,
            "initial_version": online.digest(self.initial),
            "candidate": online.digest(self.candidate) if self.candidate else None,
            "research": self.research_receipt,
            "dispatch": self.budget.summary() if self.budget else None,
            "command_completions_after_ack": self.after_ack,
            "command_metrics": {
                "commands": self.command_count,
                "commands_with_exit": self.commands_with_exit,
                "failed_commands": self.failed_commands,
            },
            "claim": "experimental_dispatch_and_observed_activity_only; no stable adoption or causal gain",
        }
        reason = (self.error or "").encode()[:300].decode("utf-8", errors="ignore")
        self.lineage.finish_trial(
            self.episode,
            status=self.status,
            reason=reason,
            commands_after_ack=self.after_ack,
        )
        self._write("terminal.json", result)
        self._terminal = result
        return result
