"""Shared immutable P/H episode terms and bounded receipts; no campaign execution."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from procontract_dependency_policy import BUILD_RUNTIME_POLICY

PROTOCOL = "single_candidate_ph_v1"
H_PROTOCOL = "single_candidate_h_v1"
H_ADMISSION = "accepted_h_probe_v1"
PH = {"executor.md", "drafter.md", "prober.md", "reviewer.md", "harness.json"}
METHOD_ROLES = frozenset(("analyst.md", "challenger.md", "research.md"))
MAX_BYTES = 512 << 10
SUPERVISOR = Path(__file__).with_name("procontract_ph_supervisor.py").resolve()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


@dataclass(frozen=True)
class EpisodeProfile:
    """Closed episode scope; selecting it does not authorize a paid launch."""

    protocol: str
    submission_policy: str
    proposal_kind: str
    mutable: frozenset[str]
    fixed_roles: frozenset[str]
    required_admission: str | None = None
    phase_learning_limits: tuple[int, int, int] = (5, 9, 14)
    paid_row_limit: int = 25


def profile(protocol):
    if protocol == PROTOCOL:
        return EpisodeProfile(
            PROTOCOL, "rust-preinstalled-v1", "all", frozenset(PH), METHOD_ROLES
        )
    require(protocol == H_PROTOCOL, "unknown sealed episode protocol")
    return EpisodeProfile(
        H_PROTOCOL,
        BUILD_RUNTIME_POLICY,
        "harness",
        frozenset(("harness.json",)),
        METHOD_ROLES | (PH - {"harness.json"}),
        H_ADMISSION,
        (6, 12, 18),
        29,
    )


class EpisodeNotReady(RuntimeError):
    """A valid future plan lacks its trusted admission/enforcement integration."""

    def __init__(self, selected):
        self.profile = selected
        super().__init__(
            "H-only supervision is not paid-ready: build/runtime execution evidence "
            "and the complete study preflight have not been enabled"
        )


def raw(path, limit=MAX_BYTES):
    require(
        not path.is_symlink() and path.is_file() and path.stat().st_size <= limit,
        f"unsafe or missing receipt: {path}",
    )
    with path.open("rb") as source:
        value = source.read(limit + 1)
    require(len(value) <= limit, "receipt exceeds bound")
    return value


def digest(path):
    return hashlib.sha256(raw(path)).hexdigest()


def document(path, limit=MAX_BYTES):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate receipt key")
            result[key] = value
        return result

    return json.loads(raw(path, limit), object_pairs_hook=object_pairs)


def publish(path, value):
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
    require(len(data) <= MAX_BYTES, "supervisor receipt exceeds bound")
    with path.open("xb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def plan_path(terms):
    value = terms.get("ph_supervisor")
    require(
        isinstance(value, dict) and set(value) == {"plan_path", "plan_sha256"},
        "missing P/H supervisor descriptor",
    )
    path = Path(value["plan_path"])
    require(
        path.is_absolute() and ".." not in path.parts and path.resolve() == path,
        "supervisor plan path is redirected",
    )
    require(digest(path) == value["plan_sha256"], "supervisor plan differs from pin")
    return path


def inspect_plan(camp, terms):
    """Validate an externally pinned profile/plan as DATA, not launch readiness."""
    plan = document(plan_path(terms))
    require(isinstance(plan, dict), "supervisor plan must be an object")
    selected = profile(plan.get("protocol"))
    require(
        plan
        == {
            "schema": 1,
            "protocol": selected.protocol,
            "campaign": str(camp.resolve()),
            "source_sha256": digest(SUPERVISOR),
            "max_phases": 3,
            **(
                {"required_admission": selected.required_admission}
                if selected.required_admission
                else {}
            ),
        },
        "supervisor plan does not bind this episode/source",
    )
    expected = {
        "model": "gpt-5.6-luna",
        "effort": "max",
        "submission_policy": selected.submission_policy,
        "proposal_kind": selected.proposal_kind,
        "adoption": "presumed",
        "task_deadline_secs": 18000,
        "analysis_deadline_secs": 3600,
        "research_deadline_secs": 3600,
        "confirmation_exposure_scope": "prospective_lineage",
    }
    stream, gates = terms["stream"], terms["gates"]
    require(
        all(terms.get(key) == value for key, value in expected.items())
        and set(terms["mutable"]) == selected.mutable
        and len(terms["mutable"]) == len(selected.mutable),
        "campaign differs from fixed P/H scope",
    )
    require(
        terms.get("checkpoint")
        and terms.get("canonical")
        and terms["budgets"]["task_attempts"] == 1
        and stream.get("mode") == "guarded"
        and stream.get("method_confirmation") == "defer"
        and stream["batch"] == stream["release_every"] == 1
        and len(stream["order"]) >= 4,
        "episode needs inherited state and guarded single-task phases with buffer",
    )
    require(
        len(terms["pools"]["confirm"]) == gates["confirm_tasks"] == 4
        and gates["confirm_min_wins"] == 3
        and gates["confirm_min_delta"] == 0.000001,
        "P/H confirmation gate differs",
    )
    if selected.protocol == H_PROTOCOL:
        import procontract_fixed_auditor_role as auditor_role
        import procontract_native_trace_binding as trace

        auditor_role.validate_descriptor(terms.get("fixed_auditor"))
        trace_profile = terms.get("native_notice_trace")
        require(
            isinstance(trace_profile, dict)
            and trace_profile.keys() == trace.PROFILE.keys()
            and all(
                type(trace_profile[key]) is type(value) and trace_profile[key] == value
                for key, value in trace.PROFILE.items()
            ),
            "native notice trace differs from the fixed H profile",
        )
    else:
        require(
            "fixed_auditor" not in terms, "fixed auditor requires the H-only profile"
        )
        require(
            "native_notice_trace" not in terms,
            "native notice trace requires the H-only profile",
        )
    return plan


def campaign_profile(camp, terms):
    """Inspect a declared episode; absence means an ordinary, non-profile campaign."""
    return (
        profile(inspect_plan(camp, terms)["protocol"])
        if "ph_supervisor" in terms
        else None
    )


def validate_plan(camp, terms):
    """Paid/init entry: execution-profile readiness must be enabled separately."""
    plan = inspect_plan(camp, terms)
    selected = profile(plan["protocol"])
    if selected.required_admission is not None:
        raise EpisodeNotReady(selected)
    return plan
