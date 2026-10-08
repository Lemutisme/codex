"""Serve only adopted producers; probe candidates without delegating learning authority.

Assignments and phase receipts are durable. Probe readiness permits confirmation, not the
next serve: an explicit adoption must settle before production can advance.
"""

import procontract_release as release
import procontract_method_confirmation as method_confirmation
import procontract_store as store
import procontract_succession as succession


def _event(host, role, number):
    return next(
        (
            event["body"]
            for event in reversed(host.events("selection"))
            if event["body"]["role"] == role and event["body"].get("batch") == number
        ),
        None,
    )


def _record(host, role, batch, **fields):
    if _event(host, role, batch["batch"]) is None:
        host.record(
            "selection",
            {
                "role": role,
                **{
                    key: batch[key]
                    for key in (
                        "batch",
                        "phase",
                        "version",
                        "expected_incumbent",
                        "expected_incumbent_seq",
                    )
                },
                **fields,
            },
        )


def learned(host, number):
    return _event(host, "guarded_batch_result", number) is not None


def pending_experiment(host, asked):
    batches = host.batches()
    if batches and batches[-1]["phase"] == "probe":
        candidate = batches[-1]["version"]
        return candidate if candidate not in asked else None
    return None


def _measure(host, pairs, purpose):
    results = host.measure_all(pairs, purpose)
    if any(result["validity"] != "valid" for result in results.values()):
        raise RuntimeError(
            f"guarded {purpose} batch has invalid execution/evaluation; "
            "preserving its assignments without advancing"
        )
    return results


def _analysis(host, batch):
    runs = {f"stream-{batch['version'][:12]}-{task}" for task in batch["tasks"]}
    experiment = batch["version"] if batch["phase"] == "probe" else None
    evidence = store.digest("analysis_evidence", host.observed())
    return next(
        (
            body
            for body in reversed(host.insights())
            if body.get("analysis_identity", {}).get("parent")
            == batch["expected_incumbent"]
            and body.get("analysis_identity", {}).get("evidence") == evidence
            and body["experiment"] == experiment
            and runs <= set(body["coverage"])
        ),
        None,
    )


class _ReleaseHost:
    """Use the unchanged release gates with readiness distinct from guarded completion."""

    def __init__(self, host):
        self.host = host

    def __getattr__(self, name):
        return getattr(self.host, name)

    def learned(self, number):
        return _event(self.host, "guarded_probe_ready", number) is not None

    def measure_all(self, pairs, purpose):
        return _measure(self.host, pairs, purpose)

    def confirm(self, candidate, incumbent):
        return succession.confirm(self, candidate, incumbent)


def _finish(host, batch, outcome, *, candidate=None, detail=""):
    _record(
        host,
        "guarded_batch_result",
        batch,
        outcome=outcome,
        candidate=candidate,
        detail=detail,
    )
    return f"guarded {batch['phase']} batch {batch['batch']}: {outcome}; {detail}"


def step(host):
    batches = host.batches()
    if not batches or learned(host, batches[-1]["batch"]):
        number = len(batches) + 1
        if number > host.batch_count():
            return "the guarded stream is complete"
        incumbent = succession.incumbent_record(host)
        version = host.incumbent()
        previous = _event(host, "guarded_batch_result", number - 1)
        candidate = (
            previous.get("candidate")
            if previous and previous["phase"] == "serve"
            else None
        )
        if candidate and (
            incumbent["seq"] != previous["expected_incumbent_seq"]
            or version != previous["expected_incumbent"]
        ):
            raise RuntimeError(
                "guarded proposal producer changed before probe assignment"
            )
        size = host.terms["stream"]["batch"]
        method = candidate is not None and host.twin(candidate) == host.twin(version)
        batch = {
            "batch": number,
            "phase": "method_probe" if method else "probe" if candidate else "serve",
            "version": version if method else candidate or version,
            "expected_incumbent": version,
            "expected_incumbent_seq": incumbent["seq"],
            "tasks": host.order()[(number - 1) * size : number * size],
        }
        if method:
            if any(
                task in host.exposed_tasks()
                or any((host.camp / "runs").glob(f"*-{task}"))
                for task in batch["tasks"]
            ):
                raise RuntimeError(
                    "method probe requires observations not exposed or started before its assignment"
                )
            batch["method_candidate"] = candidate
        host.record("assignment", batch)
    else:
        batch = batches[-1]
    number, version = batch["batch"], batch["version"]
    tested = batch.get("method_candidate", version)
    adoption = (
        host.contract(f"adoption.{tested[:16]}")
        if batch["phase"] in ("probe", "method_probe")
        else None
    )
    if adoption and adoption["standing"] == "discharged":
        if host.incumbent() != tested:
            raise RuntimeError(
                "guarded adopted producer changed before phase reconciliation"
            )
        if batch["phase"] == "probe":
            release.advance(_ReleaseHost(host))
        return _finish(
            host, batch, "adopted", detail="next serve uses the settled incumbent"
        )
    # Challenge/Withdraw can revoke a settlement without appending a new selection record.
    if (
        succession.incumbent_record(host)["seq"] != batch["expected_incumbent_seq"]
        or host.incumbent() != batch["expected_incumbent"]
    ):
        raise RuntimeError(
            "guarded batch incumbent changed; preserving its frozen assignment"
        )

    if batch["phase"] == "serve":
        _measure(host, [(version, task) for task in batch["tasks"]], "stream")
        improvement = f"improvement.{number}"
        state = host.contract(improvement)
        selected = _event(host, "stream_policy", number + 1)
        detail = "resumed settled learning"
        analysis = _analysis(host, batch)
        if analysis and analysis["status"] == "failed":
            detail = "analysis failed; incumbent unchanged"
        elif state is None or (state["standing"] != "released" and selected is None):
            detail = host.learn(number)
        elif state["standing"] == "released":
            detail = "learning rejected or failed; incumbent unchanged"
        state = host.contract(improvement)
        if state is not None and state["standing"] == "outstanding":
            host.release(improvement, "guarded serve analysis did not qualify")
        selected = _event(host, "stream_policy", number + 1)
        candidate = (
            selected["version"] if selected and number < host.batch_count() else None
        )
        if (
            candidate is not None
            and host.twin(candidate) == host.twin(version)
            and host.terms["stream"].get("method_confirmation", "defer") == "defer"
        ):
            _record(host, "guarded_method_deferred", batch, candidate=candidate)
            detail = "method-only candidate deferred; task confirmation cannot certify its research method"
            candidate = None
        if (
            candidate is not None
            and host.contract(f"adoption.{candidate[:16]}") is not None
        ):
            candidate = (
                None  # A previously decided version cannot buy another confirmation.
            )
        return _finish(host, batch, "served", candidate=candidate, detail=detail)

    if batch["phase"] == "method_probe":
        _measure(host, [(version, task) for task in batch["tasks"]], "stream")
        detail = method_confirmation.step(host, batch)
        adoption = host.contract(f"adoption.{tested[:16]}")
        if adoption and adoption["standing"] == "discharged":
            if host.incumbent() != tested:
                raise RuntimeError(
                    "method adoption did not publish its expected producer"
                )
            return _finish(host, batch, "adopted", detail=detail)
        if adoption and adoption["standing"] == "outstanding":
            if adoption["support"]:
                _record(host, "guarded_awaiting_adoption", batch)
                return f"guarded method probe batch {number}: {detail}; next serve is pending"
            raise RuntimeError(
                "method confirmation is unfinished; preserving its assignment"
            )
        return _finish(host, batch, "rejected", detail=detail)

    if _event(host, "guarded_probe_ready", number) is None:
        _measure(host, [(version, task) for task in batch["tasks"]], "stream")
        analysis = _analysis(host, batch)
        if analysis is None:
            analysis = host.insight(host.analyze(batch["expected_incumbent"]))
        _record(
            host,
            "guarded_probe_ready",
            batch,
            analysis=analysis["k"],
            analysis_status=analysis["status"],
        )
    detail = (
        release.advance(_ReleaseHost(host)) or "resuming the frozen release decision"
    )
    adoption = host.contract(f"adoption.{version[:16]}")
    if adoption and adoption["standing"] == "discharged":
        if host.incumbent() != version:
            raise RuntimeError("guarded adoption did not publish its expected producer")
        return _finish(host, batch, "adopted", detail=detail)
    if adoption and adoption["standing"] == "outstanding":
        if adoption["support"]:
            _record(host, "guarded_awaiting_adoption", batch)
            return f"guarded probe batch {number}: awaiting the principal's adoption; next serve is pending"
        raise RuntimeError(
            "guarded confirmation is still pending; preserving its assignment"
        )
    return _finish(host, batch, "rejected", detail=detail)
