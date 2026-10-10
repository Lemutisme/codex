"""Bounded, reward-driven selection of whole online controllers, not ACK promotion.

Exp3-IX-style losses with explicit exploration and optimistic new-arm admission.
The growing arm set is a heuristic: no stationary-task or regret guarantee is made.
"""

import json
import math
import random
import re

from procontract_online import digest, encoded

PROFILE = {
    "algorithm": "bounded-controller-exp3ix-v1",
    "eta": 0.3,
    "gamma": 0.05,
    "epsilon": 0.2,
    "cost_weight": 0.1,
    "max_versions": 8,
    "credit": "initial_controller_entire_adaptive_episode",
}


def initialize(db, scope, seed):
    row = db.execute("SELECT value FROM state WHERE key='selection'").fetchone()
    if scope is None:
        if row:
            raise ValueError("reward-driven lineage requires its original scope")
        return
    if type(scope) is not str or re.fullmatch(r"[0-9a-f]{64}", scope) is None:
        raise ValueError("selection scope must bind the frozen study")
    if row:
        state = json.loads(row[0])
        if state["scope"] != scope or state["profile"] != PROFILE:
            raise ValueError("selection scope or algorithm changed")
    else:
        if db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            raise ValueError("cannot reinterpret a legacy lineage as reward learning")
        state = {"scope": scope, "profile": PROFILE, "arms": []}
        admit(state, seed)
        db.execute(
            "INSERT INTO state VALUES ('selection',?)", (encoded(state).decode(),)
        )


def admit(state, version):
    if version in {a["version"] for a in state["arms"]}:
        return
    if len(state["arms"]) >= 2 * PROFILE["max_versions"]:
        return
    # Optimism is an explicit exploration prior, not an invented observation.
    prior = min((a["loss"] for a in state["arms"]), default=0.0)
    for mode in ("research", "hold"):
        state["arms"].append(
            {"version": version, "mode": mode, "loss": prior, "samples": 0}
        )


def distribution(state):
    floor = min(a["loss"] for a in state["arms"])
    weights = [math.exp(-PROFILE["eta"] * (a["loss"] - floor)) for a in state["arms"]]
    total = sum(weights)
    return [
        {
            "version": a["version"],
            "mode": a["mode"],
            "probability": (1 - PROFILE["epsilon"]) * w / total
            + PROFILE["epsilon"] / len(weights),
        }
        for a, w in zip(state["arms"], weights, strict=True)
    ]


def choose(db):
    if db.execute("""
        SELECT 1 FROM events e WHERE e.kind='episode' AND NOT EXISTS
        (SELECT 1 FROM events r WHERE r.key='reward:' || json_extract(e.body,'$.episode'))
    """).fetchone():
        raise ValueError("previous episode has no terminal reward; no resampling")
    state = json.loads(
        db.execute("SELECT value FROM state WHERE key='selection'").fetchone()[0]
    )
    alternatives = distribution(state)
    draw = random.SystemRandom().random()
    cumulative = 0.0
    selected = alternatives[-1]
    for action in alternatives:
        cumulative += action["probability"]
        if draw < cumulative:
            selected = action
            break
    return {
        **selected,
        "draw": draw,
        "alternatives": alternatives,
        "state_sha256": digest(state),
        "scope": state["scope"],
    }


def prediction(text):
    value = json.loads(text)
    if (
        type(value) is not dict
        or value.keys() != {"metric", "direction", "threshold"}
        or value["metric"] not in {"canonical_fraction", "command_failure_fraction"}
        or value["direction"] not in {"at_least", "at_most"}
        or type(value["threshold"]) not in (int, float)
        or not math.isfinite(value["threshold"])
        or not 0 <= value["threshold"] <= 1
    ):
        raise ValueError("prediction must bind an observable bounded metric")
    return value


def learn(db, allocation, reward, evidence, proposed):
    if type(evidence) is not dict or evidence.keys() != {
        "native_secs",
        "research_secs",
        "grading_secs",
        "episode_secs",
        "commands",
        "failed_commands",
        "commands_with_exit",
        "input_witness",
    }:
        raise ValueError("selection requires complete host-measured outcome evidence")
    times = [evidence[k] for k in ("native_secs", "research_secs", "grading_secs")]
    if (
        any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in times)
        or type(evidence["episode_secs"]) is not int
        or not allocation["total_secs"] < evidence["episode_secs"] <= 18000
    ):
        raise ValueError("invalid measured cost or all-in allocation")
    commands, failed, known = (
        evidence[k] for k in ("commands", "failed_commands", "commands_with_exit")
    )
    if (
        any(type(v) is not int for v in (commands, failed, known))
        or not 0 <= failed <= known <= commands
    ):
        raise ValueError("invalid observed command counters")
    witness = evidence["input_witness"]
    if witness is not None and (
        type(witness) is not str or re.fullmatch(r"[0-9a-f]{64}", witness) is None
    ):
        raise ValueError("input witness must bind a completed native request receipt")
    chosen = allocation["selection"]
    state = json.loads(
        db.execute("SELECT value FROM state WHERE key='selection'").fetchone()[0]
    )
    if digest(state) != chosen["state_sha256"]:
        raise ValueError("selection changed while episode was running")
    quality = reward["resolved"] / reward["total"]
    cost = min(1.0, sum(times) / evidence["episode_secs"])
    weight = PROFILE["cost_weight"]
    utility = (quality - weight * cost + weight) / (1 + weight)
    arm = next(
        a
        for a in state["arms"]
        if (a["version"], a["mode"]) == (chosen["version"], chosen["mode"])
    )
    arm["loss"] += (1 - utility) / (chosen["probability"] + PROFILE["gamma"])
    arm["samples"] += 1
    # A child has no independent sample yet. Its creator's entire adaptive policy
    # earned this return; the child enters only as a new, explicitly unmeasured arm.
    if reward["experimental_version"] and witness:
        admit(state, reward["experimental_version"])
    assessment = None
    if proposed:
        predicted = prediction(proposed["prediction"])
        actual = (
            quality
            if predicted["metric"] == "canonical_fraction"
            else (failed / known if known and known == commands else None)
        )
        assessment = {
            **predicted,
            "actual": actual,
            "met": None
            if actual is None
            else (
                actual >= predicted["threshold"]
                if predicted["direction"] == "at_least"
                else actual <= predicted["threshold"]
            ),
            "scope": "mixed_episode_observation_not_candidate_effect",
        }
    db.execute(
        "UPDATE state SET value=? WHERE key='selection'", (encoded(state).decode(),)
    )
    return {
        "utility": utility,
        "cost_fraction": cost,
        "evidence": evidence,
        "credited_version": chosen["version"],
        "mode": chosen["mode"],
        "propensity": chosen["probability"],
        "prediction": assessment,
        "next_distribution": distribution(state),
        "credit": PROFILE["credit"],
    }
