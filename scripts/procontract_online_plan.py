"""Operator-owned, fresh three-instance pilot plan. Preparation never calls a model."""

import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tomllib

import procontract_benchmark_runner as runner
import procontract_canonical as canonical
import procontract_online as online
import procontract_native_trace_binding as trace

SCRIPTS = Path(__file__).resolve().parent
ORDER_RULE = "sha256(online-pilot-v1:<instance>), ascending, first 3"
TRACE_PROFILE = {
    **trace.PROFILE,
    "retention": "private_archive_then_release_owned_mount",
}


def sha(path):
    return canonical.sha256(path)


def publish(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        out.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        out.flush()
        import os

        os.fsync(out.fileno())


def select_tasks(tasks):
    if len(tasks) < 3:
        raise ValueError("pilot requires three distinct ready instances")
    return sorted(
        tasks,
        key=lambda t: hashlib.sha256(("online-pilot-v1:" + t).encode()).hexdigest(),
    )[:3]


def prepare(root, source_registry, binary, prompt, *, comparison="stream"):
    if comparison not in ("stream", "paired"):
        raise ValueError("comparison must be stream or paired")
    arms = ["adaptive"] if comparison == "stream" else ["frozen", "adaptive"]
    root, binary = root.resolve(), binary.resolve()
    inputs = root / "inputs"
    inputs.mkdir(parents=True)
    source = json.loads(source_registry.read_text())
    tasks = select_tasks(source["tasks"])
    registry = {
        **source,
        "tasks": {task: source["tasks"][task] for task in tasks},
        "pins_file": str(inputs / "canonical-pins.json"),
        "exposed_tasks": [],
        "exposure_scope": "prospective_lineage",
    }
    if descriptor := source.get("dependency_policy"):
        policy = json.loads(Path(descriptor["path"]).read_text())
        if sha(Path(descriptor["path"])) != descriptor["sha256"]:
            raise ValueError("source dependency manifest changed")
        selected_images = {source["tasks"][task]["image"] for task in tasks}
        policy["tasks"] = {task: policy["tasks"][task] for task in tasks}
        policy["images"] = {image: policy["images"][image] for image in selected_images}
        publish(inputs / "dependency-policy.json", policy)
        registry["dependency_policy"] = {
            "path": str(inputs / "dependency-policy.json"),
            "sha256": sha(inputs / "dependency-policy.json"),
        }
    # This is a fresh learning lineage, not an assertion of global non-exposure.
    publish(inputs / "canonical-registry.json", registry)
    (inputs / "task-prompt.txt").write_bytes(prompt.read_bytes())
    canonical.configure(
        inputs / "canonical-registry.json", sha(inputs / "canonical-registry.json")
    )
    with (root / "canonical-preflight.log").open("x") as log:
        subprocess.run(
            [
                source.get("python", sys.executable),
                str(SCRIPTS / "procontract_canonical.py"),
                "freeze",
                "--registry",
                str(inputs / "canonical-registry.json"),
                "--registry-sha256",
                sha(inputs / "canonical-registry.json"),
            ],
            env=canonical.evaluator_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )

    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(SCRIPTS.parent), *args], text=True
        ).strip()

    if git("status", "--porcelain"):
        raise ValueError("commit the controller before sealing a new pilot")
    package = binary.parent.parent
    release = json.loads((package / "procodex-release.json").read_text())
    if release["binaries"]["codex"] != sha(binary):
        raise ValueError("native package receipt mismatch")
    base = tomllib.loads(runner.config_toml())
    provider = base["model_providers"][base["model_provider"]]
    source_files = [*SCRIPTS.glob("procontract_*.py"), SCRIPTS / "procodex_config.py"]
    frozen_scripts = root / "controller/scripts"
    frozen_scripts.mkdir(parents=True)
    for path in source_files:
        shutil.copyfile(path, frozen_scripts / path.name)
    files = {str(path): sha(path) for path in frozen_scripts.iterdir()}
    for name in ("codex", "codex-code-mode-host", "pro-contract-store"):
        path = package / "bin" / name
        if sha(path) != release["binaries"][name]:
            raise ValueError("native companion package receipt mismatch")
        files[str(path)] = sha(path)
    files.update({str(path): sha(path) for path in inputs.iterdir() if path.is_file()})
    plan = {
        "schema": 1,
        "protocol": "online-program-learning-pilot-v1",
        "root": str(root),
        "model": "gpt-5.6-luna",
        "effort": "max",
        "tasks": tasks,
        "order_rule": ORDER_RULE,
        "arms": arms,
        "task_attempts": 1,
        "research_attempts_per_task": 1,
        "episode_secs": 18000,
        "inference_secs": 14400,
        "grading_secs": 3600,
        "research_secs": 900,
        "limits": {
            "task_launches": 3 * len(arms),
            "learning_launches": 3,
            "allocated_seconds": 54000 * len(arms),
        },
        "binary": str(binary),
        "entrypoint": str(frozen_scripts / "procontract_online_pilot.py"),
        "native_source_commit": release["source_commit"],
        "controller_source_commit": git("rev-parse", "HEAD"),
        "provider": {"base_url": provider["base_url"], "env_key": provider["env_key"]},
        "registry": str(inputs / "canonical-registry.json"),
        "registry_sha256": sha(inputs / "canonical-registry.json"),
        "pins_sha256": sha(inputs / "canonical-pins.json"),
        "prompt": str(inputs / "task-prompt.txt"),
        "files": files,
        "seed": online.seed(),
        "automatic_stable_adoption": False,
        "private_native_trace": TRACE_PROFILE,
        "exposure": "new empty lineage; historical operator exposure disclosed; not globally unseen",
        "comparison_mode": comparison,
        "comparison": (
            "paired descriptive combined-program effect; no method-only causal attribution"
            if comparison == "paired"
            else "adaptive-only stream: operational closure and descriptive scores; no matched-budget net-gain claim"
        ),
        "budget_note": "5h total per arm/instance: 4h inference including research, 1h frozen grading. Adaptive researcher reserves 15min of the 4h, even if concurrent. Actual tokens/cost may differ.",
        "compliance_note": "Native ProContract provides within-evidence review, not an exhaustive syscall/dependency audit. Functional scores alone do not certify all submission constraints.",
        "unknown_policy": "stop on infrastructure unknown; preserve malformed/inactive proposals without same-task retry",
    }
    publish(root / "online-plan.json", plan)
    return {
        "plan": str(root / "online-plan.json"),
        "sha256": sha(root / "online-plan.json"),
        "tasks": tasks,
        "paid_launched": False,
    }


def verify(path, expected):
    if sha(path) != expected:
        raise ValueError("pilot plan differs from operator pin")
    plan = json.loads(path.read_text())
    if (
        plan["protocol"] != "online-program-learning-pilot-v1"
        or Path(plan["root"]) != path.resolve().parent
    ):
        raise ValueError("invalid pilot identity")
    for source, wanted in plan["files"].items():
        if sha(Path(source)) != wanted:
            raise ValueError(f"pilot input drift: {source}")
    return plan


def authorize(plan, plan_sha256, authorization):
    value = json.loads(authorization.read_text())
    if (
        value.get("plan_sha256") != plan_sha256
        or value.get("limits") != plan["limits"]
        or value.get("authorized") is not True
        or not value.get("user_message")
    ):
        raise ValueError("fresh explicit pilot budget authorization required")
    return {"path": str(authorization.resolve()), "sha256": sha(authorization)}
