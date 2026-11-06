"""Native goal lifecycle for an externally allocated benchmark attempt.

The caller arms its original allocation before starting any turn. Native Codex
owns continuation; this adapter never sends synthetic continuation prompts or
restarts a solver when an ordinary turn completes.
"""


def command(binary):
    return [str(binary), "--disable", "hooks", "--disable", "view_image",
            "--disable", "multi_agent", "-c", "agents.enabled=false",
            "--enable", "goals", "app-server"]


def activate(server, thread_id, handle):
    goal = server.request("thread/goal/set", {
        "threadId": thread_id,
        "origin": "user",
        "objective": (
            "Complete the ProgramBench implementation task supplied in the initial "
            "user message, obeying its rules and the original shared allocation. "
            "Deliver independently authored source and an executable compile.sh "
            "that rebuilds ./executable in a fresh workspace."
        ),
        "status": "active",
        "tokenBudget": None,
    }, handle)["goal"]
    if goal["status"] != "active" or goal["tokenBudget"] is not None:
        raise RuntimeError("native goal did not receive the requested unbounded-token activation")
    retained = read(server, thread_id, handle)
    if retained is None or retained["objective"] != goal["objective"]:
        raise RuntimeError("native goal activation was not retained")
    return goal


def read(server, thread_id, handle):
    return server.request("thread/goal/get", {"threadId": thread_id}, handle)["goal"]


def stop_reason(goal, *, turn_active):
    if goal is None:
        raise RuntimeError("the admitted native goal disappeared")
    if turn_active or goal["status"] == "active":
        return None
    return "native_goal_" + goal["status"]
