"""Bounded native activity observations, not tool success or semantic progress.

Count run-cumulative command-completion notifications, including duplicates and failures.
Code-mode wrappers, terminal polling, command text and tool outputs are not parsed.
The caller supplies no turn identity when its executor turn is inactive.
"""

MAX_COUNTER = (1 << 31) - 1


class ExecutorActivity:
    def __init__(self):
        self._completed = 0

    def observe(
        self, message: dict, *, thread_id: str | None, turn_id: str | None
    ) -> None:
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(turn_id, str)
            or not turn_id
            or not isinstance(message, dict)
            or "id" in message
            or message.get("method") != "item/completed"
        ):
            return
        params = message.get("params")
        if (
            not isinstance(params, dict)
            or params.get("threadId") != thread_id
            or params.get("turnId") != turn_id
        ):
            return
        item = params.get("item")
        if (
            not isinstance(item, dict)
            or item.get("type") != "commandExecution"
            or not isinstance(item.get("id"), str)
            or not item["id"]
        ):
            return
        self._completed = min(MAX_COUNTER, self._completed + 1)

    def summary(self) -> dict:
        return {"executor_command_completions_observed": self._completed}
