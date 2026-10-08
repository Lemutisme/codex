"""Carry the same study seal across credential-free canonical evaluator processes."""

import copy
import json
from contextvars import ContextVar
from pathlib import Path

import procontract_harness_program as harness
import procontract_study as study

_binding = ContextVar("canonical_study", default=None)


def bind(descriptor, *, evaluator=False):
    _binding.set(
        (copy.deepcopy(descriptor), evaluator) if descriptor is not None else None
    )


def verify():
    binding = _binding.get()
    if binding is None:
        return
    descriptor, evaluator = binding
    camp = Path(descriptor["manifest_path"]).parent
    raw = harness.read_regular(camp / "campaign.json", 1 << 20)
    if raw is None:
        raise RuntimeError("sealed evaluator campaign is missing or unsafe")
    terms = json.loads(raw)
    if terms.get("study") != descriptor:
        raise RuntimeError("evaluator belongs to a different study")
    study.verify(camp, terms, evaluator=evaluator)


def flags():
    binding = _binding.get()
    if binding is None:
        return []
    descriptor, _ = binding
    return [
        "--study-manifest",
        descriptor["manifest_path"],
        "--study-sha256",
        descriptor["manifest_sha256"],
    ]
