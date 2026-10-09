"""Seal and reserve the actual paid runner entry, not a cached Host method call."""

import hashlib
import json
from pathlib import Path

import procontract_canonical_recovery as recovery
import procontract_harness_program as harness
import procontract_study as study
import procontract_study_budget as budget


def _enclosing_study(path):
    for parent in (path, *path.parents):
        if (parent / "study.json").exists() or (parent / "study.json").is_symlink():
            return parent
    return None


def _campaign(descriptor):
    path = Path(descriptor["manifest_path"])
    camp = path.parent
    raw = harness.read_regular(camp / "campaign.json", 1 << 20)
    if raw is None:
        raise RuntimeError("study campaign is missing or unsafe")
    terms = json.loads(raw)
    if terms.get("study") != descriptor:
        raise RuntimeError("prepared runner belongs to a different study")
    return camp, terms


def prepare(args):
    path, digest = (
        getattr(args, "study_manifest", None),
        getattr(args, "study_sha256", None),
    )
    if path is None and digest is None:
        policy = getattr(args, "policy", None)
        if (
            _enclosing_study(args.run_dir.resolve()) is not None
            or policy is not None
            and _enclosing_study(policy.resolve()) is not None
        ):
            raise RuntimeError(
                "sealed campaign preparation cannot omit its study identity"
            )
        return None
    if path is None or digest is None:
        raise ValueError("study preparation requires manifest path and SHA-256")
    descriptor = {"manifest_path": str(path), "manifest_sha256": digest}
    camp, terms = _campaign(descriptor)
    study.verify(camp, terms)
    if (
        not args.run_dir.resolve().is_relative_to(camp)
        or args.run_dir.resolve() == camp
        or args.policy is None
        or args.policy != camp / "versions" / args.policy.parent.name / "bundle"
    ):
        raise RuntimeError("study preparation must name a registered producer bundle")
    return descriptor


def prepare_trace(run_dir, manifest):
    """Derive an optional private observer only from already sealed study terms."""
    if manifest.get("study") is not None:
        import procontract_native_trace_binding as native_trace

        _, terms = _campaign(manifest["study"])
        native_trace.prepare(run_dir, manifest, terms)


def authorize(args, manifest, profile):
    """A committed reservation authorizes only this invocation; replay is never free."""
    descriptor = manifest.get("study")
    if descriptor is None:
        if _enclosing_study(args.run_dir.resolve()) is not None:
            raise RuntimeError("sealed campaign runner cannot omit its study identity")
        if "native_notice_trace" in manifest:
            raise RuntimeError("native trace requires a sealed study")
        return None
    camp, terms = _campaign(descriptor)
    seal = study.verify(camp, terms)
    run_dir = args.run_dir.resolve()
    if not run_dir.is_relative_to(camp) or run_dir == camp:
        raise RuntimeError("study runner lies outside its campaign")
    role = manifest.get("instructions")
    if role not in {"executor.md", "analyst.md", "challenger.md", "research.md"}:
        raise RuntimeError("unsupported study runner role")
    task = role == "executor.md"
    deadline = (
        terms["task_deadline_secs"]
        if task
        else terms[
            "research_deadline_secs"
            if role == "research.md"
            else "analysis_deadline_secs"
        ]
    )
    if (
        args.deadline_secs != deadline
        or args.arm != "on"
        or getattr(args, "stop_after_issue", False)
        or getattr(args, "delivery_reserve_secs", 0) != 0
        or args.codex_bin.resolve() != Path(terms["codex_bin"]).resolve()
        or manifest.get("arm") != "on"
        or any(
            manifest.get(key) != terms[key]
            for key in ("model", "effort", "codex_bin", "codex_sha256")
        )
    ):
        raise RuntimeError(
            "study runner differs from its authorized model/binary/deadline profile"
        )
    # Import the Host only after the file seal has been checked.
    import procontract_rsi as rsi
    import procontract_canonical_registry as registry

    host = rsi.Host(camp)
    version = manifest.get("study_version")
    if version not in host.versions():
        raise RuntimeError("study runner producer is not registered")
    host.validate_harness(version, run_dir, require_success=False)
    source, prepared = host.version_dir(version) / "bundle", run_dir / "policy"
    names = {path.name for path in source.iterdir()}
    if names != {path.name for path in prepared.iterdir()} or any(
        (raw := harness.read_regular(source / name, rsi.MAX_BUNDLE_FILE)) is None
        or harness.read_regular(prepared / name, rsi.MAX_BUNDLE_FILE) != raw
        for name in names
    ):
        raise RuntimeError("prepared study policy differs from its registered producer")
    image = terms["research_image"]
    if task:
        frozen = registry.load(
            Path(terms["canonical"]["registry_path"]),
            terms["canonical"]["registry_sha256"],
        )
        image = frozen.tasks[manifest["instance"]]["image"]
    if manifest.get("image") != image:
        raise RuntimeError("study runner image differs from its frozen image")
    prompt = harness.read_regular(run_dir / "prompt.txt", rsi.MAX_BUNDLE_FILE)
    if prompt is None or hashlib.sha256(prompt).hexdigest() != manifest.get(
        "prompt_sha256"
    ):
        raise RuntimeError("prepared study prompt changed")
    if task and manifest["prompt_sha256"] != terms["task_prompt_sha256"]:
        raise RuntimeError("study task prompt differs from its campaign")
    # Match prepare's text-mode newline conversion while retaining exact role-byte custody above.
    instructions = harness.read_regular(prepared / role, rsi.MAX_BUNDLE_FILE).decode(
        "utf-8"
    )
    instructions = instructions.replace("\r\n", "\n").replace("\r", "\n")
    workspace, home = run_dir / "workspace", run_dir / "codex-home"
    expected = {
        home / "config.toml": profile.config_toml(
            instructions, model=terms["model"], effort=terms["effort"]
        ),
        home / "environments.toml": profile.environments_toml(
            workspace, args.codex_bin.resolve(), image
        ),
        home / "pro_contract/settings.json": json.dumps(
            profile.settings(
                workspace,
                image,
                reference=task,
                policy=prepared,
                model=terms["model"],
                effort=terms["effort"],
            ),
            indent=2,
        )
        + "\n",
    }
    actual = {
        path: harness.read_regular(path, rsi.MAX_BUNDLE_FILE) for path in expected
    }
    if any(
        actual[path] is None
        or actual[path].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        != text
        for path, text in expected.items()
    ):
        raise RuntimeError("prepared study runtime configuration changed")
    dependency_verification = None
    if task and frozen.dependency_policy is not None:
        import procontract_canonical as canonical
        import procontract_dependency_inspection as inspection

        dependency_verification = inspection.verify_image(
            frozen.dependency_policy, image
        )
        if (
            canonical.checked_pins()["dependency_policy"]["images"][image]
            != dependency_verification
        ):
            raise RuntimeError(
                "study dependency artifacts differ from the verified pins"
            )
    identity = {
        "version": version,
        "role": role,
        "instance": manifest["instance"],
        "manifest_sha256": hashlib.sha256(
            (run_dir / "manifest.json").read_bytes()
        ).hexdigest(),
        "configuration": {
            str(path.relative_to(run_dir)): hashlib.sha256(raw).hexdigest()
            for path, raw in actual.items()
        },
    }
    if dependency_verification is not None:
        identity["dependency_policy"] = {
            "sha256": frozen.dependency_policy.digest,
            "image_verification": dependency_verification,
        }
    if task:
        import procontract_h_admission as h_admission

        admission = h_admission.authorize_task(host, run_dir, manifest)
        if admission is not None:
            identity["h_admission"] = admission["digest"]
    import procontract_native_trace_binding as native_trace

    trace = native_trace.provision(run_dir, manifest, terms)
    if trace is not None:
        identity["native_notice_trace"] = trace
    receipt = budget.reserve(
        camp / "study-budget.sqlite",
        descriptor["manifest_sha256"],
        str(run_dir.relative_to(camp)),
        "task" if task else "learning",
        args.deadline_secs,
        seal["limits"],
        identity,
    )
    recovery.atomic_artifact(
        run_dir / "study-launch.json",
        lambda path: path.write_text(json.dumps(receipt) + "\n"),
    )
    return receipt
