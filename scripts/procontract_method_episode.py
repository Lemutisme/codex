"""Isolated, one-attempt updater arms over the same captured target and fresh experience."""

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

import procontract_harness_program as harness
import procontract_outcomes as outcomes
import procontract_store as store
import procontract_succession as succession

ROLES = ("analyst", "challenger", "research")
METHODS = tuple(f"{role}.md" for role in ROLES)


def _read(path, max_bytes=1 << 20):
    raw = harness.read_regular(path, max_bytes)
    if raw is None:
        raise RuntimeError(f"missing method episode receipt: {path}")
    return json.loads(raw)


def _hash(path):
    raw = harness.read_regular(path, 1 << 20)
    if raw is None:
        raise RuntimeError(f"missing method episode evidence: {path}")
    return hashlib.sha256(raw).hexdigest()


def _capture(host, path):
    return store.capture(host.store, path, [])["subject_hash"]


def freeze_input(host, batch):
    """Capture only this target's assigned fresh stream observations and the common prior K."""
    import procontract_rsi as rsi

    target, number = batch["version"], batch["batch"]
    if batch not in host.batches() or target != batch["expected_incumbent"]:
        raise RuntimeError("method input must belong to its assigned incumbent batch")
    root = host.camp / "method-inputs" / f"batch-{number}"
    receipt = root / "input.json"
    if receipt.exists():
        value = _read(receipt)
        if (value["target"], value["batch_id"], value["tasks"]) != (
            target,
            number,
            batch["tasks"],
        ):
            raise RuntimeError("method input assignment changed")
        verify_input(host, value)
        return value
    host.validate_harness(target)
    runs = [f"stream-{target[:12]}-{task}" for task in batch["tasks"]]
    observed = host.observed()
    if (
        not runs
        or len(set(batch["tasks"])) != len(runs)
        or any(name not in observed for name in runs)
    ):
        raise RuntimeError(
            "method input requires valid fresh observations for every assigned task"
        )
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".input-") as temporary:
        workspace = Path(temporary)
        archive = workspace / "archive"
        (archive / "runs").mkdir(parents=True)
        shutil.copytree(host.version_dir(target) / "bundle", workspace / "policy")
        shutil.copytree(
            workspace / "policy", archive / "versions" / target[:12] / "bundle"
        )
        previous = host.current_knowledge()
        rsi.copy_knowledge(previous, workspace / "knowledge")
        rsi.copy_knowledge(previous, archive / "knowledge")
        failing = {}
        for name, task in zip(runs, batch["tasks"]):
            result = observed[name]
            if (result["version"], result["task"], result["purpose"]) != (
                target,
                task,
                "stream",
            ):
                raise RuntimeError("method observation does not bind its target/task")
            host.validate_evaluator(result)
            host.validate_harness(target, Path(result["run_dir"]))
            observation = host.observe(name, result)
            shutil.copytree(observation, archive / "runs" / name)
            items = _read(observation / "outcomes.json", 16 << 20)
            failing[task] = sorted(
                item for item, value in items.items() if not value["passed"]
            )
            row = {
                "name": name,
                "version": target,
                "twin": target,
                "parent": None,
                "purpose": "stream",
                "outcomes": items,
            }
            directory = archive / "tasks" / task
            directory.mkdir(parents=True)
            (directory / "outcomes.md").write_text(
                outcomes.render(task, outcomes.matrix([row])), encoding="utf-8"
            )
        value = {
            "schema": 1,
            "class": "paired_updater_v1",
            "target": target,
            "batch_id": number,
            "tasks": list(batch["tasks"]),
            "runs": runs,
            "failing": failing,
            "knowledge": rsi.knowledge_identity(previous),
        }
        (workspace / "method_trial.json").write_text(
            json.dumps(value), encoding="utf-8"
        )
        (archive / "README.md").write_text(
            f"Method confirmation trial. Common target: {target}.\n"
            "Only this batch's frozen raw observations and common initial knowledge are available.\n"
            "No other methods, sibling outcomes or downstream evaluation are included.\n",
            encoding="utf-8",
        )
        value = {**value, "subject": _capture(host, workspace)}
    exposure = {"view": f"method-input:{number}", "parent": target, "sources": runs}
    if exposure not in [event["body"] for event in host.events("exposure")]:
        host.record("exposure", exposure)
    succession.receipt(receipt, value)
    return value


def verify_input(host, value):
    """Read captured input rather than rebuilding it from the current campaign archive."""
    import procontract_rsi as rsi

    host.validate_harness(value["target"])
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "input"
        store.materialize(host.store, value["subject"], root)
        expected = {key: item for key, item in value.items() if key != "subject"}
        if (
            _read(root / "method_trial.json") != expected
            or rsi.knowledge_identity(root / "knowledge") != value["knowledge"]
        ):
            raise RuntimeError("captured method input does not match its receipt")
        if _capture(host, root) != value["subject"]:
            raise RuntimeError("captured method input changed")


def _arm_root(host, plan, producer, arm):
    expected = plan["incumbent"] if arm == "control" else plan["candidate"]
    if (
        arm not in ("control", "candidate")
        or producer != expected
        or plan["class"] != "paired_updater_v1"
        or plan["batch_id"] != plan["input"]["batch_id"]
        or plan["root_id"] != plan["candidate"]
        or not re.fullmatch(r"[0-9a-f]{64}", plan["root_id"])
        or plan["input"]["target"] != plan["incumbent"]
        or plan["role_attempts"] != 1
        or set(plan["deadlines"]) != set(ROLES)
        or any(type(v) is not int or v <= 0 for v in plan["deadlines"].values())
    ):
        raise RuntimeError("invalid paired updater arm assignment")
    host.validate_harness(producer)
    if host.twin(producer) != host.twin(plan["input"]["target"]):
        raise RuntimeError("updater producer changes the common task phenotype")
    return host.camp / "method-trials" / plan["root_id"] / arm


def _stage(host, plan, producer, role, root, previous):
    import procontract_rsi as rsi

    binding = {
        "plan": store.digest("method_plan", plan),
        "producer": producer,
        "role": role,
        "common_input": plan["input"]["subject"],
        "previous": previous["output_subject"] if previous else None,
    }
    if root.exists():
        staged = _read(root / "stage.json")
        if (
            staged["binding"] != binding
            or _capture(host, root / "workspace") != staged["subject"]
            or _hash(root / "prompt.md") != staged["prompt_sha256"]
        ):
            raise RuntimeError("method stage inputs changed; preserving its launch")
        return staged
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=f".{role}-") as temporary:
        staged = Path(temporary)
        workspace = staged / "workspace"
        store.materialize(host.store, plan["input"]["subject"], workspace)
        if previous is not None:
            output = staged / "previous"
            store.materialize(host.store, previous["output_subject"], output)
            shutil.rmtree(workspace / "knowledge")
            if role == "challenger":
                rsi.hand_over(output, workspace, None)
            else:
                rsi.copy_knowledge(output / "knowledge", workspace / "knowledge")
                shutil.rmtree(workspace / "archive" / "knowledge")
                rsi.copy_knowledge(
                    output / "knowledge", workspace / "archive" / "knowledge"
                )
                insight = workspace / "archive" / "insight" / "paired"
                insight.mkdir(parents=True)
                for name in ("ANALYSIS.md", "CHALLENGE.md", "hindsight.json"):
                    shutil.copyfile(output / name, insight / name)
            shutil.rmtree(output)
        if role == "research":
            allowed = [
                name
                for name in [*rsi.TASK_FILES, harness.PROGRAM_FILE]
                if name in host.terms["mutable"]
            ]
            prompt = (
                rsi.RESEARCH_PROTOCOL.format(
                    parent=plan["input"]["target"][:12],
                    files=", ".join(allowed),
                    sections=", ".join(rsi.EXPERIMENT_SECTIONS),
                    prediction=rsi.PREDICT_CLASSES,
                    intervention=rsi.proposal_scope.research_constraint(host.terms),
                )
                + "\nKeep research.md, analyst.md and challenger.md identical to the common target.\n"
            )
        else:
            protocol = (
                rsi.ANALYST_PROTOCOL if role == "analyst" else rsi.CHALLENGER_PROTOCOL
            )
            prompt = protocol.format(pending=rsi.NOT_PENDING)
        (staged / "prompt.md").write_text(
            "Method confirmation trial.\n" + prompt, encoding="utf-8"
        )
        record = {
            "binding": binding,
            "subject": _capture(host, workspace),
            "prompt_sha256": _hash(staged / "prompt.md"),
        }
        succession.receipt(staged / "stage.json", record)
        staged.rename(root)
    return record


def _role_receipt(host, root, role, staged, delivery):
    receipt = {
        "role": role,
        "input_subject": staged["subject"],
        "output_subject": _capture(host, delivery),
        "files": {},
    }
    for name in (
        "launch-claim.json",
        "launch-exit.json",
        "runner-failed.json",
        "run/manifest.json",
        "run/run.json",
        "run/study-launch.json",
    ):
        if (root / name).exists():
            receipt["files"][name] = _hash(root / name)
    succession.receipt(root / "output.json", receipt)
    return receipt


def _verify_role(host, root, role, producer, deadline, staged, receipt):
    if (
        receipt["role"] != role
        or receipt["input_subject"] != staged["subject"]
        or receipt != _read(root / "output.json")
        or not {"launch-claim.json", "run/manifest.json"} <= receipt["files"].keys()
        or any(
            _hash(root / name) != digest for name, digest in receipt["files"].items()
        )
    ):
        raise RuntimeError("method role receipt changed")
    claim = _read(root / "launch-claim.json")["identity"]
    if (
        claim["parent"],
        claim["instructions"],
        claim["deadline_secs"],
        claim["input"],
        claim["prompt"],
    ) != (producer, f"{role}.md", deadline, staged["subject"], staged["prompt_sha256"]):
        raise RuntimeError("method role did not run its assigned producer/input")
    if (
        _capture(host, root / "workspace") != staged["subject"]
        or _hash(root / "prompt.md") != staged["prompt_sha256"]
    ):
        raise RuntimeError("method role input or protocol changed")
    if _capture(host, root / "run" / "workspace") != receipt["output_subject"]:
        raise RuntimeError("method role output differs from its captured delivery")
    if _capture(host, root / "run" / "policy") != _capture(
        host, host.version_dir(producer) / "bundle"
    ):
        raise RuntimeError("method role loaded another producer's policy")


def run_arm(host, plan, producer, arm):
    """Run exactly one attempt per role; private knowledge never becomes campaign knowledge."""
    import procontract_rsi as rsi

    root = _arm_root(host, plan, producer, arm)
    result_path = root / "result.json"
    if result_path.exists():
        result = _read(result_path)
        verify_arm(host, plan, producer, arm, result)
        return result
    verify_input(host, plan["input"])
    root.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": 1,
        "plan_digest": store.digest("method_plan", plan),
        "producer": producer,
        "arm": arm,
        "input_subject": plan["input"]["subject"],
        "status": "failed",
        "descendant": None,
        "reason": "",
        "receipts": [],
    }
    previous = None
    for role in ROLES:
        stage = root / role
        staged = _stage(host, plan, producer, role, stage, previous)
        output = stage / "output.json"
        if output.exists():
            receipt = _read(output)
        else:
            delivery = host.run_agent(
                stage,
                f"method-{arm}-{role}",
                producer,
                f"{role}.md",
                plan["deadlines"][role],
            )
            receipt = _role_receipt(host, stage, role, staged, delivery)
        _verify_role(
            host, stage, role, producer, plan["deadlines"][role], staged, receipt
        )
        result["receipts"].append(receipt)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            delivery = Path(temporary) / "delivery"
            store.materialize(host.store, receipt["output_subject"], delivery)
            if (stage / "runner-failed.json").exists():
                result["reason"] = _read(stage / "runner-failed.json")["reason"]
            elif role != "research":
                document = "ANALYSIS.md" if role == "analyst" else "CHALLENGE.md"
                result["reason"] = rsi.delivery_problem(
                    delivery,
                    document,
                    None,
                    {t: set(v) for t, v in plan["input"]["failing"].items()},
                )
            else:
                target = plan["input"]["target"]
                try:
                    files, base = (
                        rsi.bundle_texts(delivery / "policy"),
                        rsi.bundle_texts(host.version_dir(target) / "bundle"),
                    )
                    ok, reason, changed = host.qualify(delivery, target)
                    if any(files.get(name, "") != base[name] for name in METHODS):
                        ok, reason = (
                            False,
                            "updater trial cannot change the target's method files",
                        )
                except (OSError, ValueError) as error:
                    ok, reason, changed = (
                        False,
                        f"invalid research delivery: {error}",
                        False,
                    )
                result["reason"] = reason
                if ok:
                    result.update(
                        status="qualified",
                        descendant=host.register(
                            delivery / "policy",
                            target,
                            producer,
                            rsi.experiment_text(delivery),
                        )
                        if changed
                        else target,
                    )
        if (
            result["reason"]
            and role != "research"
            or result["status"] == "failed"
            and role == "research"
        ):
            break
        previous = receipt
    succession.receipt(result_path, result)
    verify_arm(host, plan, producer, arm, result)
    return result


def verify_arm(host, plan, producer, arm, receipt):
    """Validate sealed phase outputs and their launch receipts without running another agent."""
    import procontract_rsi as rsi

    root = _arm_root(host, plan, producer, arm)
    if (
        _read(root / "result.json") != receipt
        or receipt["plan_digest"] != store.digest("method_plan", plan)
        or (receipt["producer"], receipt["arm"], receipt["input_subject"])
        != (producer, arm, plan["input"]["subject"])
    ):
        raise RuntimeError("method arm receipt changed")
    verify_input(host, plan["input"])
    for index, value in enumerate(receipt["receipts"]):
        role = ROLES[index]
        stage = root / role
        staged = _read(stage / "stage.json")
        binding = {
            "plan": store.digest("method_plan", plan),
            "producer": producer,
            "role": role,
            "common_input": plan["input"]["subject"],
            "previous": receipt["receipts"][index - 1]["output_subject"]
            if index
            else None,
        }
        if staged["binding"] != binding:
            raise RuntimeError("method role belongs to another episode")
        _verify_role(
            host, stage, role, producer, plan["deadlines"][role], staged, value
        )
        with tempfile.TemporaryDirectory() as temporary:
            store.materialize(
                host.store, value["output_subject"], Path(temporary) / "output"
            )
    if receipt["status"] == "qualified":
        if [r["role"] for r in receipt["receipts"]] != list(ROLES):
            raise RuntimeError("qualified method arm did not finish all roles")
        host.validate_harness(receipt["descendant"])
        with tempfile.TemporaryDirectory() as temporary:
            delivery = Path(temporary) / "delivery"
            store.materialize(
                host.store, receipt["receipts"][-1]["output_subject"], delivery
            )
            generated = rsi.bundle_texts(delivery / "policy")
            target = plan["input"]["target"]
            original = rsi.bundle_texts(host.version_dir(target) / "bundle")
            descendant = host.version_dir(receipt["descendant"]) / "bundle"
            proposed, recorded = (
                harness.load(delivery / "policy"),
                harness.load(descendant),
            )
            if (
                rsi.bundle_texts(descendant)
                != {name: generated.get(name, "") for name in rsi.BUNDLE_FILES}
                or (proposed.digest if proposed else None)
                != (recorded.digest if recorded else None)
                or any(generated.get(name, "") != original[name] for name in METHODS)
                or receipt["descendant"] != target
                and host.versions()[receipt["descendant"]]["lineage"]
                != {"parent": target, "proposed_by": producer}
            ):
                raise RuntimeError(
                    "method descendant differs from its sealed research output"
                )
