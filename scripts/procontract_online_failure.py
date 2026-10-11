"""A narrow host-owned failure boundary, not catch-all exception suppression."""


def bounded_reason(value):
    return str(value).encode()[:300].decode("utf-8", errors="ignore")


class ContractUnavailable(RuntimeError):
    """An abstained intake; the pilot must still establish safe termination."""

    def __init__(self, status):
        self.contract_status = {
            "phase": status["phase"],
            "contract_id": status.get("contract_id"),
            "resting": status.get("resting"),
            "repairs_used": status.get("repairs_used"),
            "detail": bounded_reason(
                status.get("detail") or "task contract was not issued"
            ),
        }
        super().__init__(
            "online learning requires an issued ProContract task contract: "
            + self.contract_status["detail"]
        )


def contained_contract_failure(summary):
    """None means ordinary processing or fatal handling, NEVER permission to ignore it."""
    status = summary.get("status") or {}
    closed = summary.get("native_process_exit") or {}
    learning = summary.get("online_learning") or {}
    error = summary.get("runner_error")
    if (
        status.get("phase") != "abstained"
        or status.get("resting") is not True
        or status.get("contract_id")
        or closed.get("status") != "exited"
        or type(closed.get("returncode")) is not int
        or closed["returncode"] != 0
        or (summary.get("execution_environment") or {}).get("disconnect_observed")
        is not False
        or error not in (None, "ContractUnavailable")
        or any(
            learning.get(k) is not None for k in ("research", "candidate", "dispatch")
        )
    ):
        return None
    if error is None and (
        summary.get("server_exited_early")
        or (summary.get("turn_statuses") or [None])[-1] != "completed"
    ):
        return None
    return {
        "kind": "contract_unavailable",
        "quality": None,
        "reason": bounded_reason(
            status.get("detail") or "task contract was not issued"
        ),
    }
