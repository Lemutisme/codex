"""Release a tested exploration head, never an untested research delivery.

Checkpoints are fixed in campaign terms. The host records its choice before reading fresh
confirmation evidence; an interrupted confirmation resumes that choice, not a newly selected
version. Qualification permits exploration. Only the separate adoption contract permits promotion.
"""


def advance(host) -> str | None:
    """Finish a pending release or consume the latest completed release checkpoint once.

    Call before starting another stream batch and after learning from a completed batch. The
    host owns confirmation reservations, resumption and settlement; this module only selects.
    """
    every = host.terms.get("stream", {}).get("release_every", 0)
    if not every:
        return None
    selections = [event["body"] for event in host.events("selection")]
    finished = {
        body["batch"] for body in selections if body["role"] == "stream_release_result"
    }
    intent = next(
        (
            body
            for body in selections
            if body["role"] == "stream_release_intent" and body["batch"] not in finished
        ),
        None,
    )
    if intent is None:
        batches = host.batches()
        if not batches:
            return None
        batch = batches[-1]
        number, candidate = batch["batch"], batch["version"]
        if number % every or number in finished or not host.learned(number):
            return None
        runs = {f"stream-{candidate[:12]}-{task}" for task in batch["tasks"]}
        if not runs or not runs <= host.observed().keys():
            return None
        insight = next(
            (
                body
                for body in reversed(host.insights())
                if body["experiment"] == candidate and runs <= set(body["coverage"])
            ),
            None,
        )
        incumbent = host.incumbent()
        qualified = any(
            body["role"] == "stream_policy"
            and body["version"] == candidate
            and body["batch"] <= number
            for body in selections
        )
        reason = ""
        if candidate == incumbent or not qualified:
            reason = "no qualified changed policy was tested"
        elif not insight or (insight["status"], insight["verdict"]) != (
            "qualified",
            "present",
        ):
            reason = (
                "the tested policy has no challenged, present signature for this batch"
            )
        elif host.contract(f"adoption.{candidate[:16]}") is not None:
            reason = (
                "this policy already has an adoption decision in progress or completed"
            )
        elif host.confirm_budget_left() < host.terms["gates"]["confirm_tasks"]:
            reason = "not enough fresh confirmation tasks"
        intent = {
            "batch": number,
            "version": candidate,
            "expected_incumbent": incumbent,
        }
        if reason:
            host.record(
                "selection",
                {**intent, "role": "stream_release_result", "outcome": reason},
            )
            return f"release after batch {number}: {reason}"
        intent.update(role="stream_release_intent", insight=insight["k"])
        host.record("selection", intent)
    outcome = host.confirm(intent["version"], intent["expected_incumbent"])
    host.record(
        "selection", {**intent, "role": "stream_release_result", "outcome": outcome}
    )
    return f"release after batch {intent['batch']}: {outcome}"
