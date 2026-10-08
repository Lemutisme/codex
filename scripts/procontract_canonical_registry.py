"""Immutable, operator-pinned ProgramBench inputs; never supplied by a candidate."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from procontract_harness_program import read_regular

MAX_BYTES = 1 << 20
TASK_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}__[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.[0-9a-f]{7,40}"
)
HEX256 = re.compile(r"[0-9a-f]{64}")
REQUIRED = {
    "schema",
    "tasks",
    "programbench",
    "programbench_head",
    "hf_revision",
    "wheelhouse",
    "blob_root",
    "blob_manifest",
    "pins_file",
}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate registry key")
        result[key] = value
    return result


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value:
        raise ValueError("registry resource paths must be bounded absolute paths")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(
            "registry resource paths must be absolute without parent traversal"
        )
    return path


def _source(path, expected):
    if not isinstance(expected, str) or HEX256.fullmatch(expected) is None:
        raise ValueError("an externally pinned registry SHA-256 is required")
    raw = read_regular(path, MAX_BYTES)
    if raw is None or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("canonical registry identity changed or is missing")
    return raw


@dataclass(frozen=True)
class Registry:
    path: Path
    digest: str
    tasks: Mapping[str, Mapping[str, object]]
    programbench: Path
    programbench_head: str
    hf_revision: str
    python: Path
    wheelhouse: Path
    blob_root: Path
    blob_manifest: Path
    pins_file: Path
    exposed_tasks: tuple[str, ...]
    exposure_scope: str
    operator_exposed_tasks: tuple[str, ...]

    def verify_source(self):
        _source(self.path, self.digest)

    def validate_campaign(self, terms):
        """Check source identity and known group overlap, not unknown training exposure."""
        if terms.get("confirmation_exposure_scope", "strict") != self.exposure_scope:
            raise ValueError("canonical campaign differs: confirmation_exposure_scope")
        for name, expected in (
            ("programbench", str(self.programbench)),
            ("programbench_head", self.programbench_head),
            ("hf_revision", self.hf_revision),
        ):
            if terms.get(name) != expected:
                raise ValueError(f"canonical campaign differs: {name}")
        stream, pools = terms.get("stream", {}), terms.get("pools", {})
        if stream is None:
            stream = {}
        if not isinstance(stream, dict) or not isinstance(pools, dict):
            raise ValueError("campaign task pools must be objects")
        groups = [
            stream.get("order", []),
            pools.get("dev", []),
            pools.get("confirm", []),
        ]
        for tasks in groups:
            if not isinstance(tasks, list) or any(
                not isinstance(t, str) or t not in self.tasks for t in tasks
            ):
                raise ValueError("campaign names a task outside its canonical registry")
            if len(tasks) != len(set(tasks)):
                raise ValueError("campaign task pools contain duplicates")
        development = set(groups[0]) | set(groups[1]) | set(self.exposed_tasks)
        # Prospective holdouts relax only disclosed operator history, never lineage exposure.
        if self.exposure_scope == "strict":
            development.update(self.operator_exposed_tasks)
        # Commits of the same owner/repository stay together, including known historical IDs.
        seen_groups = {task.rsplit(".", 1)[0].casefold() for task in development}
        confirm_groups = {task.rsplit(".", 1)[0].casefold() for task in groups[2]}
        if seen_groups & confirm_groups:
            raise ValueError(
                "confirmation overlaps a development or known-exposed repository"
            )


def load(path: Path, expected_sha256: str) -> Registry:
    path = _path(str(path))
    raw = _source(path, expected_sha256)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except RecursionError as error:
        raise ValueError("registry is too deeply nested") from error
    if (
        not isinstance(data, dict)
        or not REQUIRED <= data.keys()
        or data.keys()
        - REQUIRED
        - {"python", "exposed_tasks", "exposure_scope", "operator_exposed_tasks"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("unsupported canonical registry schema")
    tasks = data["tasks"]
    if not isinstance(tasks, dict) or not 1 <= len(tasks) <= 4096:
        raise ValueError("canonical registry needs a bounded nonempty task map")
    frozen = {}
    for task, spec in tasks.items():
        if (
            TASK_ID.fullmatch(task) is None
            or not isinstance(spec, dict)
            or set(spec) - {"total", "image", "image_tag"}
        ):
            raise ValueError("invalid task registry entry")
        if type(spec.get("total")) is not int or not 1 <= spec["total"] < 1 << 31:
            raise ValueError("eligible count must be a positive bounded integer")
        image = spec.get("image")
        if (
            not isinstance(image, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None
        ):
            raise ValueError("cleanroom image must be content addressed")
        tag = spec.get(
            "image_tag",
            f"programbench/{task.replace('__', '_1776_')}:task_cleanroom_v6",
        )
        if (
            not isinstance(tag, str)
            or len(tag) > 512
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9_.-]+)?", tag)
            is None
        ):
            raise ValueError("invalid cleanroom image tag")
        frozen[task] = MappingProxyType(
            {"total": spec["total"], "image": image, "image_tag": tag}
        )
    for name in ("programbench_head", "hf_revision"):
        if (
            not isinstance(data[name], str)
            or re.fullmatch(r"[0-9a-f]{40}", data[name]) is None
        ):
            raise ValueError(f"{name} must be a pinned revision")
    exposure_scope = data.get("exposure_scope", "strict")
    if exposure_scope not in ("strict", "prospective_lineage"):
        raise ValueError("invalid exposure scope")
    exposed = data.get("exposed_tasks", [])
    operator_exposed = data.get("operator_exposed_tasks", [])
    for name, tasks in (
        ("known-exposure", exposed),
        ("operator-exposure", operator_exposed),
    ):
        if (
            not isinstance(tasks, list)
            or len(tasks) > 10000
            or any(
                not isinstance(t, str) or TASK_ID.fullmatch(t) is None for t in tasks
            )
            or len(tasks) != len(set(tasks))
        ):
            raise ValueError(f"invalid {name} task list")
    if exposure_scope == "prospective_lineage" and not operator_exposed:
        raise ValueError("prospective lineage requires disclosed operator exposure")
    programbench = _path(data["programbench"])
    return Registry(
        path=path,
        digest=expected_sha256,
        tasks=MappingProxyType(frozen),
        programbench=programbench,
        programbench_head=data["programbench_head"],
        hf_revision=data["hf_revision"],
        python=_path(data.get("python", str(programbench / ".venv/bin/python"))),
        wheelhouse=_path(data["wheelhouse"]),
        blob_root=_path(data["blob_root"]),
        blob_manifest=_path(data["blob_manifest"]),
        pins_file=_path(data["pins_file"]),
        exposed_tasks=tuple(exposed),
        exposure_scope=exposure_scope,
        operator_exposed_tasks=tuple(operator_exposed),
    )
