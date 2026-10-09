"""Operator-pinned checkpoint DATA import; consistency checks are not independent truth.

Only the selected bundle, qualified knowledge and attributed feedback are learner inputs.
All other bytes remain host evidence. Provenance source_path values are never followed.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from dataclasses import dataclass

import procontract_canonical_registry as registries
import procontract_harness_program as harness
import procontract_store as store

MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 4096, 4 << 20, 32 << 20
ROLES = (
    "executor",
    "research",
    "analyst",
    "challenger",
    "drafter",
    "prober",
    "reviewer",
)


def _require(condition, message):
    if not condition:
        raise ValueError(f"checkpoint {message}")


def _json(raw):
    value = json.loads(raw, object_pairs_hook=registries._object)
    # Re-encoding forbids NaN/Infinity, including in operator-provided scores.
    json.dumps(value, allow_nan=False)
    return value


def _tree(root):
    _require(
        root.is_absolute() and ".." not in root.parts,
        "path must be absolute without traversal",
    )
    for ancestor in (root, *root.parents):
        _require(stat.S_ISDIR(ancestor.lstat().st_mode), "directory must not be linked")
    files, pending, total, nodes = {}, [root], 0, 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                nodes += 1
                _require(nodes <= MAX_FILES * 2, "tree has too many entries")
                path, info = Path(entry.path), entry.stat(follow_symlinks=False)
                relative = path.relative_to(root).as_posix()
                _require(len(path.relative_to(root).parts) <= 20, "tree is too deep")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    continue
                _require(
                    stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    "tree requires independent regular files",
                )
                total += info.st_size
                _require(
                    len(files) < MAX_FILES and total <= MAX_TOTAL_BYTES,
                    "tree exceeds its budget",
                )
                raw = harness.read_regular(path, MAX_FILE_BYTES)
                _require(
                    raw is not None
                    and len(raw) == info.st_size
                    and path.stat().st_nlink == 1,
                    "file changed during read",
                )
                files[relative] = raw
    return files


@dataclass(frozen=True)
class Checkpoint:
    root: Path
    bundle: Path
    knowledge: Path
    feedback_files: tuple[Path, ...]
    origin: dict
    excluded_tasks: tuple[str, ...]
    operator_exposed_tasks: tuple[str, ...]

    def descriptor(self):
        return json.loads(json.dumps(self.origin))

    def required_paths(self):
        return (self.root,)

    def validate_campaign(self, terms, registry=None):
        profile = {"id": terms.get("model"), "effort": terms.get("effort")}
        _require(
            profile == self.origin["model"]
            and terms.get("codex_sha256") == self.origin["native_sha256"],
            "model/native profile differs",
        )
        confirmation = terms.get("pools", {}).get("confirm", [])
        _require(
            isinstance(confirmation, list)
            and all(isinstance(t, str) for t in confirmation),
            "confirmation pool is malformed",
        )
        excluded = {t.rsplit(".", 1)[0].casefold() for t in self.excluded_tasks}
        _require(
            not excluded & {t.rsplit(".", 1)[0].casefold() for t in confirmation},
            "confirmation overlaps inherited exposure",
        )
        if registry is not None:
            _require(
                set(self.excluded_tasks) <= set(registry.exposed_tasks),
                "registry omits inherited exclusions",
            )
            _require(
                set(self.operator_exposed_tasks)
                <= set(registry.operator_exposed_tasks),
                "registry omits operator exposure disclosure",
            )
            registry.validate_campaign(terms)
        elif confirmation:
            _require(
                not self.operator_exposed_tasks,
                "confirmation with operator exposure requires a canonical registry",
            )


def from_terms(terms, registry=None, *, store_bin=None):
    if "checkpoint" not in terms:
        return None
    value = terms["checkpoint"]
    _require(
        isinstance(value, dict) and isinstance(value.get("path"), str),
        "campaign descriptor is malformed",
    )
    checkpoint = load(
        Path(value["path"]), value.get("manifest_sha256"), store_bin=store_bin
    )
    _require(
        value == {"path": str(checkpoint.root), **checkpoint.descriptor()},
        "campaign descriptor changed",
    )
    checkpoint.validate_campaign(terms, registry)
    return checkpoint


def load(path, expected_manifest_sha256, *, store_bin=None):
    """Verify DATA with an external pin and, when supplied, the trusted caller's binary."""
    _require(
        isinstance(expected_manifest_sha256, str)
        and registries.HEX256.fullmatch(expected_manifest_sha256),
        "requires an external manifest SHA-256",
    )
    try:
        return _load(Path(path), expected_manifest_sha256, store_bin)
    except (KeyError, TypeError, IndexError, OSError, RecursionError) as error:
        raise ValueError(f"malformed checkpoint: {error}") from error


def _load(root, pin, store_bin):
    files = _tree(root)
    _require(
        hashlib.sha256(files["MANIFEST.json"]).hexdigest() == pin,
        "manifest differs from external pin",
    )
    manifest, seal = _json(files["MANIFEST.json"]), _json(files["SEAL.json"])
    entries = manifest["entries"]
    _require(
        manifest["schema"] == 1
        and manifest["artifact_kind"] == "verified_checkpoint_data_only",
        "unsupported manifest",
    )
    _require(
        isinstance(entries, dict)
        and set(files) == set(entries) | {"MANIFEST.json", "SEAL.json"},
        "payload inventory differs",
    )
    for name, entry in entries.items():
        relative = PurePosixPath(name)
        _require(
            not relative.is_absolute()
            and str(relative) == name
            and ".." not in relative.parts
            and "\\" not in name
            and ":" not in name,
            "invalid payload path",
        )
        _require(
            entry["bytes"] == len(files[name])
            and entry["sha256"] == hashlib.sha256(files[name]).hexdigest(),
            "payload content differs",
        )
        if "export_mode" in entry:
            mode = entry["export_mode"]
            _require(
                isinstance(mode, str) and re.fullmatch(r"0o[0-7]{3,4}", mode),
                "invalid export mode",
            )
            # Relocation may change writability, but not whether learned tools execute.
            if os.name == "posix":
                _require(
                    (root / name).stat().st_mode & 0o111 == int(mode, 8) & 0o111,
                    "payload executable mode differs",
                )
    total = sum(len(files[name]) for name in entries)
    _require(
        (manifest["payload_file_count"], manifest["payload_bytes"])
        == (len(entries), total),
        "payload counts differ",
    )
    cp = _json(files["CHECKPOINT.json"])
    _require(
        cp["schema"] == 1
        and cp["artifact_kind"] == manifest["artifact_kind"]
        and cp["new_promotion"] is False,
        "unsupported checkpoint",
    )
    incumbent, knowledge = cp["incumbent"], cp["knowledge"]
    vid, contract_id = incumbent["id"], incumbent["adoption_contract"]
    _require(
        (
            incumbent["bundle"],
            incumbent["manifest"],
            knowledge["path"],
            cp["method_feedback"],
        )
        == (
            "incumbent/bundle",
            "incumbent/manifest.json",
            "knowledge",
            "learned-feedback/method-trial.json",
        ),
        "import paths differ from data schema",
    )
    version = _json(files["incumbent/manifest.json"])
    bundle = {
        name: files[f"incumbent/bundle/{name}"].decode("utf-8")
        for name in (f"{role}.md" for role in ROLES)
    }
    _require(
        all(len(text.encode()) <= 32768 for text in bundle.values()),
        "bundle exceeds policy budget",
    )
    _require(
        version["bundle"]
        == {
            name: store.digest("bundle_file", text, binary=store_bin)
            for name, text in bundle.items()
        },
        "bundle identity differs",
    )
    program = harness.load(root / "incumbent/bundle")
    _require(
        version.get("harness")
        == (
            {"interpreter": program.interpreter, "sha256": program.digest}
            if program
            else None
        ),
        "harness identity differs",
    )
    allowed = {f"incumbent/bundle/{name}" for name in bundle} | (
        {"incumbent/bundle/harness.json"} if program else set()
    )
    _require(
        {name for name in entries if name.startswith("incumbent/bundle/")} == allowed,
        "bundle contains unregistered data",
    )
    _require(
        vid
        == store.digest("version", version, binary=store_bin)
        == manifest["source_incumbent"],
        "selected version identity differs",
    )
    _require((root / "knowledge").is_dir(), "knowledge directory is missing")
    knowledge_files = {
        name[10:]: raw for name, raw in files.items() if name.startswith("knowledge/")
    }
    learned = {
        name: raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        for name, raw in knowledge_files.items()
    }
    _require(
        all("__pycache__" not in PurePosixPath(name).parts for name in learned),
        "knowledge contains cache data",
    )
    size = sum(map(len, knowledge_files.values()))
    _require(
        size <= 512 << 10
        and (knowledge["files"], knowledge["bytes"]) == (len(learned), size),
        "knowledge budget/counts differ",
    )
    _require(
        store.digest("knowledge", learned, binary=store_bin)
        == knowledge["digest"]
        == manifest["source_knowledge_digest"],
        "knowledge identity differs",
    )
    events = _json(files["evidence/store/experiment-events.json"])
    _require(
        isinstance(events, list)
        and 1 <= len(events) <= 8192
        and type(cp["last_event_seq"]) is int
        and cp["last_event_seq"] == len(events),
        "event count differs",
    )
    _require(
        all(
            isinstance(event, dict)
            and type(event.get("seq")) is int
            and event["seq"] == index
            for index, event in enumerate(events, 1)
        ),
        "event sequence differs",
    )
    decoded = [(e["seq"], _json(e["event_json"])) for e in events]
    selections = [
        (seq, e["body"])
        for seq, e in decoded
        if e["kind"] == "selection" and e["body"].get("role") == "incumbent"
    ]
    _require(
        selections[-1]
        == (
            incumbent["selection_seq"],
            {"adoption": contract_id, "role": "incumbent", "version": vid},
        ),
        "selected incumbent differs",
    )
    _require(
        any(
            e["kind"] == "version"
            and e["body"].get("id") == vid
            and e["body"].get("manifest") == version
            for _, e in decoded
        ),
        "version registration missing",
    )
    _require(
        isinstance(version["binary"], str)
        and registries.HEX256.fullmatch(version["binary"]),
        "native identity is malformed",
    )
    profile = version["model"]
    _require(
        profile == {"id": "gpt-5.6-luna", "effort": "max"}, "requires Luna/max source"
    )
    for _, event in decoded:
        identity = event["identities"]
        _require(
            (identity["harness"], identity["model"], identity["effort"])
            == (version["binary"], profile["id"], profile["effort"]),
            "source event profile differs",
        )
    record = _json(files["evidence/store/contracts.json"])[contract_id]
    state = record["state"]
    coordinate = state["settlement"]["coordinate"]
    _require(
        (record["version"], state["version"]) == (incumbent["contract_version"],) * 2
        and state["standing"] == incumbent["standing"] == "discharged",
        "adoption is not discharged",
    )
    _require(
        state["id"] == contract_id
        and state["candidate"]["subject_hash"] == coordinate["subject_hash"] == vid
        and coordinate["contract_id"] == contract_id
        and state["support"]["coordinate"] == coordinate,
        "adoption subject/support differs",
    )
    commands = [
        _json(e["command_json"])
        for e in _json(files["evidence/store/contract-events.json"])
        if e["contract_id"] == contract_id
    ]
    _require(
        commands[-1]
        == {
            "contract_id": contract_id,
            "expected_version": state["version"] - 1,
            "role": "settler",
            "provenance": commands[-1]["provenance"],
            "command": {"type": "discharge", **state["settlement"]},
        },
        "settlement command differs",
    )
    insights = [
        (seq, e["body"])
        for seq, e in decoded
        if e["kind"] == "insight" and e["body"].get("status") == "qualified"
    ]
    seq, insight = insights[-1]
    coverage = _json(files["evidence/qualified-insight/coverage.json"])
    _require(
        seq == knowledge["qualified_event_seq"]
        and insight["knowledge_digest"] == knowledge["digest"]
        and knowledge["parent"] == insight["analysis_identity"]["parent"] == vid,
        "qualified knowledge attribution differs",
    )
    _require(
        coverage
        == {
            **insight["analysis_identity"],
            "prior_knowledge": insight["prior_knowledge"],
        },
        "qualified insight coverage differs",
    )
    feedback = _json(files["learned-feedback/method-trial.json"])
    _require(
        len(files["learned-feedback/method-trial.json"]) <= 3501
        and feedback["method"] == vid
        and feedback["class"] == "paired_updater_v1"
        and feedback["passed"] is True,
        "method feedback is not attributed",
    )
    reports = [
        e["body"]["evidence"]
        for _, e in decoded
        if e["kind"] == "selection"
        and e["body"].get("role") == "method_confirmation_evidence"
        and e["body"]["confirmation"] == vid
    ]
    evidence = reports[-1]
    plans = [
        e["body"]
        for _, e in decoded
        if e["kind"] == "assignment"
        and e["body"].get("class") == "paired_updater_v1"
        and e["body"].get("confirmation") == vid
    ]
    plan = plans[-1]
    _require(
        feedback["comparator"] == plan["incumbent"]
        and feedback["common_input"] == plan["input"]["subject"]
        and feedback["adoption_subject"] == "method only, not a descendant task policy"
        and feedback["selection_unit"]
        == "one paired updater episode; not independent method replications"
        and feedback["outcome"] == "evaluated",
        "feedback attribution/scope differs",
    )
    _require(
        all(
            feedback[key] == evidence[key]
            for key in ("descendants", "mean_delta", "wins", "passed")
        )
        and feedback["tasks"] == len(evidence["pairs"]),
        "feedback differs from source evidence",
    )
    _require(
        coordinate["evidence_hash"]
        == store.digest("evidence", evidence, binary=store_bin),
        "settlement evidence differs",
    )
    exposure = _json(files["operator-metadata/complete-conservative-exposure.json"])
    lists = {}
    for name in (
        "confirmation_prohibited_tasks_conservative",
        "operator_exposed_tasks",
    ):
        values = exposure[name]
        _require(
            isinstance(values, list)
            and len(values) <= 4096
            and all(
                isinstance(t, str) and registries.TASK_ID.fullmatch(t) for t in values
            )
            and len(set(values)) == len(values)
            and exposure["counts"][name] == len(values),
            "invalid exposure inventory",
        )
        lists[name] = tuple(sorted(values))
    excluded, operator = lists.values()
    _require(
        set(excluded) <= set(operator), "operator disclosure omits carried exposure"
    )
    for name in (
        "historical_blocked_prior_tasks",
        "all_v1_declared_tasks",
        "all_v2_declared_tasks",
        "cumulative_actual_rollout_tasks",
        "current_v2_learner_consumed_tasks",
    ):
        _require(
            set(exposure[name]) <= set(excluded),
            "conservative inventory drops known exposure",
        )
    _require(
        set(exposure["confirmation_prohibited_repositories_conservative"])
        == {t.rsplit(".", 1)[0].casefold() for t in excluded},
        "repository exposure inventory differs",
    )
    _require(
        seal
        == {
            "schema": 1,
            "manifest_sha256": pin,
            "incumbent": vid,
            "knowledge_digest": knowledge["digest"],
            "payload_file_count": len(entries),
            "payload_bytes": total,
            "confirmation_exclusions": len(excluded),
            "operator_exposed_task_count": len(operator),
        },
        "seal differs from manifest",
    )
    campaign = _json(files["provenance/v2/campaign.json"])
    _require(
        (campaign["model"], campaign["effort"], campaign["codex_sha256"])
        == (profile["id"], profile["effort"], version["binary"]),
        "source campaign profile differs",
    )
    _require(
        hashlib.sha256(files["provenance/v2/study.json"]).hexdigest()
        == cp["source_study_sha256"],
        "source study digest differs",
    )
    origin = {
        "schema": 1,
        "manifest_sha256": pin,
        "source_version": vid,
        "knowledge_digest": knowledge["digest"],
        "source_study_sha256": cp["source_study_sha256"],
        "model": profile,
        "native_sha256": version["binary"],
        "adoption_contract": contract_id,
        "source_selection_seq": incumbent["selection_seq"],
        "source_knowledge_event_seq": seq,
        "import_kind": "operator_pinned_checkpoint_data",
        "new_promotion": False,
    }
    return Checkpoint(
        root,
        root / "incumbent/bundle",
        root / "knowledge",
        (root / "learned-feedback/method-trial.json",),
        origin,
        excluded,
        operator,
    )
