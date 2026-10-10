"""Bounded experimental program learning; no inference, promotion or benchmark authority.

The operator owns this database outside all executor mounts. Experimental inheritance
is NOT certification. Canonical feedback is supplied only after freezing a submission.
"""

import hashlib
import json

import procontract_harness_program as harness

TEXT_BYTES = 1600
PROGRAM_BYTES = 4000
OBSERVATION_BYTES = 1200
PACKET_BYTES = 7000


def encoded(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def parse(raw):
    if type(raw) is not bytes or len(raw) > PROGRAM_BYTES:
        raise ValueError("program packet exceeds bound")
    value = json.loads(
        raw, object_pairs_hook=harness._object, parse_constant=harness._invalid_number
    )
    if (
        type(value) is not dict
        or value.keys() != {"schema", "execution", "research", "harness"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
    ):
        raise ValueError("unsupported online program")
    for field in ("execution", "research"):
        if (
            type(value[field]) is not str
            or not value[field].strip()
            or len(value[field].encode()) > TEXT_BYTES
        ):
            raise ValueError(f"{field} must be nonempty bounded text")
    program = harness.parse(encoded(value["harness"]))
    if program.schema != 3 or program.action != "checkpoint":
        raise ValueError("online pilot permits lifecycle-v3 checkpoints only")
    return value


def seed():
    return {
        "schema": 1,
        "execution": "Prefer discriminating checks over repeated undirected inspection. Preserve task constraints. Verify a buildable deliverable before declaring completion.",
        "research": "Use observed failures, unknowns and measured prior returns to propose ONE small, falsifiable change to execution and checkpoint timing. Improve this research method only when the evidence motivates a concrete change in how subsequent experiments are selected. Preserve useful existing behavior. Never treat a hypothesis or a reviewer opinion as measured gain.",
        "harness": {
            "schema": 3,
            "action": "checkpoint",
            "when": {"command_completions_observed_gte": 4},
        },
    }


def instructions(program):
    """Strategy context shared by both arms; never part of human contract intake."""
    return (
        "Experimental execution strategy; never modifies user requirements, permissions or checks:\n"
        + program["execution"]
    )


def output_schema():
    # H is JSON encoded inside a string to retain the existing recursive grammar;
    # the host parses/compiles it before registering or executing anything.
    return {
        "type": "object",
        "properties": {
            key: {"type": "string"}
            for key in (
                "execution",
                "research",
                "harness_json",
                "mechanism",
                "prediction",
            )
        },
        "required": [
            "execution",
            "research",
            "harness_json",
            "mechanism",
            "prediction",
        ],
        "additionalProperties": False,
    }


def proposal(raw):
    if type(raw) is not bytes or len(raw) > PACKET_BYTES:
        raise ValueError("proposal exceeds bound")
    value = json.loads(
        raw, object_pairs_hook=harness._object, parse_constant=harness._invalid_number
    )
    if type(value) is not dict or set(value) != set(output_schema()["required"]):
        raise ValueError("unexpected proposal fields")
    for key, text in value.items():
        if (
            type(text) is not str
            or not text.strip()
            or len(text.encode())
            > (harness.MAX_BYTES if key == "harness_json" else TEXT_BYTES)
        ):
            raise ValueError("invalid proposal text")
    program = parse(
        encoded(
            {
                "schema": 1,
                "execution": value["execution"],
                "research": value["research"],
                "harness": json.loads(
                    value["harness_json"], object_pairs_hook=harness._object
                ),
            }
        )
    )
    return program, {key: value[key] for key in ("mechanism", "prediction")}
