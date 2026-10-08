"""Bounded transport evidence, independent of model-turn or app-server completion.

An executor environment may die while the app-server and model continue running.
These observations neither restart it nor reinterpret an evaluator's result.
"""


class ExecutionHealth:
    def __init__(self):
        self.disconnection_count = 0
        self.disconnections = []

    def observe(self, message: dict, thread_id: str | None) -> None:
        if (
            thread_id is None
            or message.get("method") != "thread/environment/disconnected"
        ):
            return
        params = message.get("params", {})
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            return
        self.disconnection_count += 1
        if len(self.disconnections) < 16:
            environment = params.get("environmentId")
            emitted = message.get("emittedAtMs")
            self.disconnections.append(
                {
                    "environment_id": environment[:256]
                    if isinstance(environment, str)
                    else None,
                    "emitted_at_ms": emitted if type(emitted) is int else None,
                }
            )

    def summary(self) -> dict:
        return {
            "disconnect_observed": self.disconnection_count > 0,
            "disconnect_count": self.disconnection_count,
            "disconnections": self.disconnections,
            "events_omitted": self.disconnection_count - len(self.disconnections),
        }
