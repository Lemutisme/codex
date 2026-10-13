"""Offline full-matrix inputs: existing images/tests only, no inference or installs."""

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import procontract_dependency_inspection as inspection
import procontract_dependency_policy as dependencies
import procontract_online_plan as plans


def stage(root, source_registry):
    root, source_registry = Path(root).resolve(), Path(source_registry).resolve()
    source = json.loads(source_registry.read_text())
    sys.path.insert(0, str(Path(source["programbench"]) / "src"))
    from programbench.utils.load_data import (
        load_all_instances,
        get_active_branches,
        get_ignored_tests,
    )

    instances = {
        i["instance_id"]: i
        for i in load_all_instances()
        if not i["instance_id"].startswith("testorg__")
    }
    if len(instances) != 200:
        raise ValueError("expected the complete pinned 200-instance official matrix")
    root.mkdir(parents=True, exist_ok=False)
    inputs = root / "inputs"
    inputs.mkdir()
    old_policy = json.loads(Path(source["dependency_policy"]["path"]).read_text())
    if (
        plans.sha(Path(source["dependency_policy"]["path"]))
        != source["dependency_policy"]["sha256"]
    ):
        raise ValueError("source dependency policy changed")
    allowed = old_policy["allowed"]
    prompt = dependencies.render_prompt(allowed, policy_name=old_policy["policy"])
    (inputs / "task-prompt.txt").write_bytes(prompt)
    if plans.sha(inputs / "task-prompt.txt") != old_policy["prompt_sha256"]:
        raise ValueError("submission constraints differ from the approved baseline")
    # Independent regular copies; the evaluator never follows HF cache symlinks.
    cached = (
        Path.home()
        / ".cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/snapshots"
        / source["hf_revision"]
    )
    blobs = inputs / "evaluation-blobs"
    digests = {}
    for task, instance in sorted(instances.items()):
        for branch in get_active_branches(instance):
            name = f"{task}/tests/{branch}.tar.gz"
            path = blobs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached / name, path)
            digests[name] = plans.sha(path)
    plans.publish(
        inputs / "blob-manifest.json",
        {
            "schema": 1,
            "commit": source["hf_revision"],
            "blob_root": str(blobs),
            "blob_sha256": digests,
        },
    )
    reference_items = next(iter(old_policy["images"].values()))
    ordered = sorted(reference_items)

    def one(task):
        directory = inputs / "cases" / task
        directory.mkdir(parents=True)
        tag = f"programbench/{task.replace('__', '_1776_')}:task_cleanroom_v6"
        image = inspection._run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag]
        ).strip()
        if not inspection.IMAGE.fullmatch(image):
            raise ValueError("missing pinned cleanroom image")
        command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "1000:1000",
            "--memory",
            "64m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "16",
            "--workdir",
            "/",
            "--entrypoint",
            "/usr/bin/timeout",
            image,
            "--signal=KILL",
            "20",
            "/bin/sh",
            "-c",
            inspection.INSPECT,
            "inventory",
            *[reference_items[k]["path"] for k in ordered],
        ]
        observed = inspection._run(command).splitlines()
        if len(observed) != len(ordered):
            raise ValueError("incomplete preinstalled dependency inventory")
        items = {}
        for key, line in zip(ordered, observed):
            resolved, digest = line.split("\t")
            items[key] = {"path": resolved, "sha256": digest}
        dependencies.validate_items(items, allowed)
        policy = {**old_policy, "tasks": {task: image}, "images": {image: items}}
        plans.publish(directory / "dependency-policy.json", policy)
        instance = instances[task]
        ignored = get_ignored_tests(instance)
        total = len(
            {
                f"{b}/{t}"
                for b in get_active_branches(instance)
                for t in instance["branches"][b]["tests"]
                if f"{b}/{t}" not in ignored
            }
        )
        registry = {
            **source,
            "tasks": {task: {"image": image, "image_tag": tag, "total": total}},
            "blob_root": str(blobs),
            "blob_manifest": str(inputs / "blob-manifest.json"),
            "pins_file": str(directory / "canonical-pins.json"),
            "dependency_policy": {
                "path": str(directory / "dependency-policy.json"),
                "sha256": plans.sha(directory / "dependency-policy.json"),
            },
            "exposed_tasks": [],
            "operator_exposed_tasks": sorted(instances),
            "exposure_scope": "prospective_lineage",
        }
        plans.publish(directory / "canonical-registry.json", registry)
        return task

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for task in pool.map(one, sorted(instances)):
            print(json.dumps({"staged": task}), flush=True)
    result = {
        "schema": 1,
        "tasks": sorted(instances),
        "source_registry": str(source_registry),
        "source_registry_sha256": plans.sha(source_registry),
        "paid_calls": 0,
    }
    plans.publish(inputs / "inventory.json", result)
    return result


def seal(root, binary, *, parallel=4):
    root, binary = Path(root).resolve(), Path(binary).resolve()
    inventory = json.loads((root / "inputs/inventory.json").read_text())
    repo = Path(__file__).resolve().parent.parent
    if subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"]
    ).strip():
        raise ValueError("commit the controller before sealing")
    if parallel not in range(1, 5):
        raise ValueError(
            "the resource envelope permits at most four concurrent episodes"
        )
    controller = root / "controller/scripts"
    controller.mkdir(parents=True)
    for path in (repo / "scripts").glob("procontract*.py"):
        shutil.copyfile(path, controller / path.name)
    shutil.copyfile(
        repo / "scripts/procodex_config.py", controller / "procodex_config.py"
    )
    transport = root / "controller/bin/docker"
    transport.parent.mkdir()
    shutil.copyfile(controller / "procontract_sweep_docker.py", transport)
    transport.chmod(0o755)
    package = binary.parent.parent
    release = json.loads((package / "procodex-release.json").read_text())
    for name, digest in release["binaries"].items():
        if plans.sha(package / "bin" / name) != digest:
            raise ValueError("native package differs from release receipt")
    tasks = sorted(
        inventory["tasks"],
        key=lambda task: hashlib.sha256(
            ("succession-full-v1:" + task).encode()
        ).digest(),
    )

    def freeze(task):
        directory = root / "inputs/cases" / task
        registry = directory / "canonical-registry.json"
        spec = json.loads(registry.read_text())
        with (directory / "preflight.log").open("x") as log:
            env = {
                key: os.environ[key]
                for key in (
                    "PATH",
                    "HOME",
                    "USER",
                    "LANG",
                    "LC_ALL",
                    "TMPDIR",
                    "DOCKER_HOST",
                    "DOCKER_CONTEXT",
                    "XDG_RUNTIME_DIR",
                )
                if key in os.environ
            }
            env.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1")
            subprocess.run(
                [
                    spec["python"],
                    str(controller / "procontract_canonical.py"),
                    "freeze",
                    "--registry",
                    str(registry),
                    "--registry-sha256",
                    plans.sha(registry),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=True,
                env=env,
            )
        return task, {
            "registry": str(registry),
            "registry_sha256": plans.sha(registry),
            "pins_sha256": plans.sha(directory / "canonical-pins.json"),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        cases = dict(pool.map(freeze, tasks))
    import procontract_benchmark_runner as runner
    import procontract_online as online
    import tomllib

    config = tomllib.loads(runner.config_toml())
    provider = config["model_providers"][config["model_provider"]]
    files = {str(p): plans.sha(p) for p in controller.iterdir() if p.is_file()}
    files[str(transport)] = plans.sha(transport)
    files.update({str(p): plans.sha(p) for p in (root / "inputs").rglob("*.json")})
    files.update(
        {
            str(package / "bin" / name): digest
            for name, digest in release["binaries"].items()
        }
    )
    files[str(root / "inputs/task-prompt.txt")] = plans.sha(
        root / "inputs/task-prompt.txt"
    )
    plan = {
        "schema": 1,
        "protocol": "successor-full-v1",
        "root": str(root),
        "entrypoint": str(controller / "procontract_sweep.py"),
        "tasks": tasks,
        "cases": cases,
        "arms": ["successor"],
        "parallel": parallel,
        "model": "gpt-5.6-luna",
        "effort": "max",
        "binary": str(binary),
        "native_source_commit": release["source_commit"],
        "controller_source_commit": subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip(),
        "episode_secs": 18000,
        "inference_secs": 14400,
        "grading_secs": 3600,
        "research_secs": 0,
        "succession": {"max_sessions": 3, "total_secs": 14400},
        "limits": {
            "task_launches": len(tasks),
            "learning_launches": 0,
            "allocated_seconds": 18000 * len(tasks),
        },
        "provider": {"base_url": provider["base_url"], "env_key": provider["env_key"]},
        "credential_preflight": "provider-key-info-v1",
        "prompt": str(root / "inputs/task-prompt.txt"),
        "seed": online.seed(),
        "files": files,
        "disk_admission_gib": 50,
        "task_attempts": 1,
        "retention": "private lossless native-home archive after scoring and native exit; do not delete workspace, submission, scores or trace archive",
        "container_envelope": {
            "memory_default": "32g",
            "cpus_default": 4,
            "pids_default": 512,
            "network_default": "none",
            "scope_labels": True,
        },
        "claim_scope": "successor-only, historical comparisons descriptive; no causal net-benefit or globally unseen claim",
        "artifact_policy": "quiescent final workspace at handoff or controlled budget stop; no grading of unverified execution errors",
        "stop_policy": "stop new admission on any infrastructure/integrity failure; allow existing owned episodes to close; never rerun or refund",
        "order_rule": "sha256(succession-full-v1:<instance>); all 200 official instances",
        "exposure": "historical author scalar exposure plus disclosed peco/silver posthoc inspection; no cross-task learning or official grader feedback to executor",
    }
    plans.publish(root / "plan.json", plan)
    return {
        "plan": str(root / "plan.json"),
        "sha256": plans.sha(root / "plan.json"),
        "limits": plan["limits"],
        "paid_calls": 0,
    }
