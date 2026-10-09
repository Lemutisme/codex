"""One optional bounded notice inside a run's existing wall-clock budget.

Steering asks the active executor to checkpoint evidence or converge naturally. It
neither interrupts a turn nor certifies a handoff, artifact, progress or result.
"""

import math

from procontract_harness_program import MAX_INTEGER, Program

ELIGIBILITY_REASONS = frozenset(
    (
        "invalid_facts",
        "deadline_expired",
        "inactive_executor",
        "protected_phase",
        "checkpoint_warmup",
        "checkpoint_reserve",
        "convergence_window",
        "eligible",
    )
)


class DeliveryBudget:
    """Send at most one bounded notice, including when its acknowledgement is lost."""

    def __init__(
        self,
        *,
        deadline_secs: int,
        reserve_secs: int = 0,
        program: Program | None = None,
    ):
        if deadline_secs <= 0 or not 0 <= reserve_secs < deadline_secs:
            raise ValueError(
                "delivery reserve must be nonnegative and below the deadline"
            )
        self.deadline_secs = deadline_secs
        self.reserve_secs = reserve_secs
        self._attempt: dict | None = None
        self.program = program
        self.activation = (
            {
                "sha256": program.digest,
                "interpreter": program.interpreter,
                "evaluations": 0,
                "last_input": None,
                "last_decision": None,
            }
            if program is not None
            else None
        )
        if program is not None and program.schema == 2:
            self.activation.update(action=program.action, last_eligibility=None)

    def maybe_steer(
        self,
        server,
        turns,
        status,
        handle,
        *,
        elapsed_secs: float,
        executor_command_completions_observed: int | None = None,
    ) -> None:
        """Observe a fresh elapsed time and, if due, fence the notice to this executor turn.

        `turns` is the runner's executor-only TurnTracker. V1 permits no ledger yet;
        v2 requires a status with a known phase and an explicit integer repairs_used.
        An unknown phase or a lane doing checks/review is not eligible. Never retry
        an attempt: a timeout can mean the notice was already delivered. The v2
        command counter reports notifications, not successful commands or progress.
        """
        version_two = self.program is not None and self.program.schema == 2
        if version_two:
            if self._attempt is not None:
                return
            try:
                remaining = self.deadline_secs - elapsed_secs
                facts = {
                    "deadline_secs": self.deadline_secs,
                    "remaining_secs": max(0, math.ceil(remaining)),
                    "turns_completed": getattr(turns, "completed", None),
                    "repairs_used": status.get("repairs_used")
                    if isinstance(status, dict)
                    else None,
                    "executor_command_completions_observed": executor_command_completions_observed,
                }
                decision = self.program.evaluate(facts)
            except (TypeError, ValueError, OverflowError):
                facts, decision = None, None
            if facts is None:
                reason = "invalid_facts"
            elif remaining <= 0:
                reason = "deadline_expired"
            elif not turns.active or not turns.thread_id or not turns.turn_id:
                reason = "inactive_executor"
            elif status is not None and (
                not isinstance(status, dict)
                or status.get("phase")
                not in ("idle", "drafting", "working", "repairing")
            ):
                reason = "protected_phase"
            elif self.program.action == "checkpoint":
                if elapsed_secs < min(300, self.deadline_secs // 10):
                    reason = "checkpoint_warmup"
                elif remaining < min(60, self.deadline_secs // 10):
                    reason = "checkpoint_reserve"
                else:
                    reason = "eligible"
            elif not self.reserve_secs or remaining > min(
                self.reserve_secs, 3600, self.deadline_secs // 4
            ):
                reason = "convergence_window"
            else:
                reason = "eligible"
            self.activation.update(
                evaluations=min(
                    MAX_INTEGER, self.activation["evaluations"] + (facts is not None)
                ),
                last_input=facts,
                last_decision=decision,
                last_eligibility={"eligible": reason == "eligible", "reason": reason},
            )
            if reason != "eligible" or not decision:
                return
        else:
            remaining = self.deadline_secs - elapsed_secs
            if (
                not self.reserve_secs
                or self._attempt is not None
                or remaining <= 0
                or not turns.active
                or not turns.thread_id
                or not turns.turn_id
            ):
                return
            if status is not None and (
                not isinstance(status, dict)
                or status.get("phase")
                not in ("idle", "drafting", "working", "repairing")
            ):
                return
            if self.program is not None:
                facts = {
                    "deadline_secs": self.deadline_secs,
                    "remaining_secs": max(0, math.ceil(remaining)),
                    "turns_completed": turns.completed,
                    "repairs_used": (status or {}).get("repairs_used", 0),
                }
                decision = self.program.evaluate(facts)
                self.activation.update(
                    evaluations=self.activation["evaluations"] + 1,
                    last_input=facts,
                    last_decision=decision,
                )
                if not decision:
                    return
            if remaining > self.reserve_secs:
                return
        turn_id = turns.turn_id
        notice = (
            f"Run budget notice: approximately {int(remaining)} seconds remain within the "
            "existing total deadline; this notice grants no extra time. Stop broad exploration "
            "and new scope. Prioritize the required deliverables, leave a runnable/buildable "
            "artifact when the task calls for one, and use remaining time for targeted checks. "
            "End your turn naturally to hand off, leaving time for independent verification "
            "and any permitted repair. Report unfinished work and checks honestly; this notice "
            "does not certify completion or successful validation."
        )
        if version_two and self.program.action == "checkpoint":
            notice = (
                "Evidence checkpoint within the existing task and deadline: briefly record "
                "your current implementation state, evidence from checks already performed, "
                "and the next discriminating check. Then continue the task. This is not a "
                "request to finish or hand off, grants no extra time or permissions, and "
                "does not certify progress or successful validation."
            )
        attempt = {
            "turn_id": turn_id[:128],
            "remaining_secs": round(remaining, 3),
            "outcome": "unacknowledged",
        }
        if version_two:
            attempt["action"] = self.program.action
        # Consume the allowance before I/O, even if the active turn changes during the request.
        self._attempt = attempt
        try:
            response = server.request(
                "turn/steer",
                {
                    "threadId": turns.thread_id,
                    "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": notice, "text_elements": []}],
                },
                handle,
                timeout=min(10.0, remaining),
            )
        except TimeoutError as error:
            attempt.update(outcome="timeout", error=str(error)[:512])
        except (RuntimeError, OSError) as error:
            attempt.update(outcome="error", error=str(error)[:512])
        else:
            if isinstance(response, dict) and response.get("turnId") == turn_id:
                attempt["outcome"] = "accepted"
            else:
                attempt.update(
                    outcome="error",
                    error="steering acknowledgement did not match the turn",
                )

    def summary(self) -> dict:
        """A bounded, serializable receipt, not a claim that the executor handed off."""
        return {
            "reserve_secs": self.reserve_secs,
            "attempt": dict(self._attempt) if self._attempt is not None else None,
        }
