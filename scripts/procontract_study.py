"""Operator-sealed live-study inputs, not a hermetic operating-system boundary.

The evaluator virtualenv (including bytecode and .pth files) is sealed. Host stdlib,
shared libraries, OS tools/services and opaque provider routing remain trusted.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent
ENVIRONMENT = ("PATH", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH")
LIMITS = {"task_launches", "learning_launches", "allocated_seconds"}
SCOPE = "source, resources, binaries and evaluator virtualenv; not host stdlib, shared libraries, OS or provider routing"
FIELDS = {
    "schema",
    "camp",
    "terms_sha256",
    "limits",
    "runner",
    "host_python",
    "store_bin",
    "evaluator_python",
    "python_version",
    "environment",
    "files",
    "scope",
}


def _encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate study key")
        result[key] = value
    return result


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 << 20:
        raise ValueError("study manifest must be a bounded regular file")
    with path.open("rb") as source:
        raw = source.read((16 << 20) + 1)
    if len(raw) > 16 << 20:
        raise ValueError("study manifest exceeds its size limit")
    return raw, json.loads(raw, object_pairs_hook=_object)


def _limits(value):
    if (
        not isinstance(value, dict)
        or set(value) != LIMITS
        or any(
            type(v) is not int or not 1 <= v <= (1 << 63) - 1 for v in value.values()
        )
    ):
        raise ValueError("invalid study limits")


def _profile(terms):
    if (terms.get("model"), terms.get("effort")) != ("gpt-5.6-luna", "max"):
        raise ValueError("live study requires Luna/max")
    stream = terms.get("stream") or {}
    if (
        not terms.get("canonical")
        or stream.get("mode") != "guarded"
        or stream.get("release_every") != 1
        or type(terms.get("budgets", {}).get("task_attempts")) is not int
        or terms["budgets"]["task_attempts"] != 1
        or type(terms.get("task_deadline_secs")) is not int
        or terms["task_deadline_secs"] != 18000
    ):
        raise ValueError(
            "live study requires canonical guarded single-attempt five-hour terms"
        )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", terms.get("research_image", "")):
        raise ValueError("research image must be content addressed")
    for name in ("research_deadline_secs", "analysis_deadline_secs"):
        if type(terms.get(name)) is not int or not 1 <= terms[name] <= 18000:
            raise ValueError("learning deadlines must be bounded positive seconds")


def _registry(terms):
    import procontract_canonical_registry as registries

    identity = terms["canonical"]
    frozen = registries.load(
        Path(identity["registry_path"]), identity["registry_sha256"]
    )
    frozen.validate_campaign(terms)
    return frozen


def _tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"missing or redirected study resource directory: {root}")
    paths = set()
    for directory, names, files in os.walk(root, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                if not path.resolve(strict=True).is_relative_to(root.resolve()):
                    raise ValueError(f"escaping study directory link: {path}")
                paths.add(path)
        paths.update(Path(directory) / name for name in files)
    return paths


def _store_bin():
    return Path(
        os.environ.get(
            "PRO_CONTRACT_STORE_BIN",
            str(SCRIPTS.parent / "codex-rs/target/debug/pro-contract-store"),
        )
    ).absolute()


def mandatory_paths(terms, host_python, store_bin):
    """Recompute the required inventory from trusted code/terms, never manifest file keys."""
    import procontract_checkpoint as checkpoints

    frozen = _registry(terms)
    codex = Path(terms["codex_bin"])
    paths = set(SCRIPTS.glob("*.py"))
    cache = SCRIPTS / "__pycache__"
    if cache.exists():
        paths.update(_tree(cache))
    checkpoint = checkpoints.from_terms(terms, frozen)
    if frozen.dependency_policy is not None:
        paths.update(frozen.dependency_policy.required_paths())
    if "ph_supervisor" in terms:
        import procontract_ph_supervisor as supervisor

        paths.add(supervisor.plan_path(terms))
    if checkpoint is not None:
        for path in checkpoint.required_paths():
            paths.update(_tree(path) if path.is_dir() else (path,))
    paths.update(
        SCRIPTS.parent / "codex-rs/ext/pro-contract/policies" / name
        for name in (
            "executor.md",
            "research.md",
            "analyst.md",
            "challenger.md",
            "drafter.md",
            "prober.md",
            "reviewer.md",
        )
    )
    paths.update(
        (
            codex,
            codex.resolve().parent / "codex-code-mode-host",
            Path(store_bin),
            Path(host_python),
            frozen.python,
            Path(terms["task_prompt"]),
            frozen.path,
            frozen.pins_file,
            frozen.blob_manifest,
            frozen.programbench / "uv.lock",
        )
    )
    for directory in ("src", "scripts"):
        paths.update(_tree(frozen.programbench / directory))
    paths.update(_tree(frozen.wheelhouse))
    for task in frozen.tasks:
        paths.update(_tree(frozen.blob_root / task))
    # Preserve the lexical .venv interpreter path: resolving it first loses its dependencies.
    environment = frozen.python.parent.parent
    if not (environment / "pyvenv.cfg").is_file():
        raise ValueError("evaluator Python must name an explicit virtualenv")
    paths.update(_tree(environment))
    return {path.absolute() for path in paths}


def _files(paths):
    result, hashes = {}, {}
    for path in sorted(paths):
        target = path.resolve(strict=True)
        info = target.stat()
        if path.is_symlink() and target.is_dir():
            result[str(path)] = {"directory_link": str(target)}
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"nonregular study resource: {path}")
        if target not in hashes:
            h = hashlib.sha256()
            with target.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
            after = target.stat()
            if (info.st_ino, info.st_size, info.st_mtime_ns) != (
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError(f"study resource changed while hashing: {path}")
            hashes[target] = h.hexdigest()
        result[str(path)] = {
            "target": str(target),
            "sha256": hashes[target],
            "bytes": info.st_size,
            "mode": stat.S_IMODE(info.st_mode),
        }
    return result


def _terms(terms):
    return _digest({key: value for key, value in terms.items() if key != "study"})


def freeze(camp: Path, terms: dict, limits: dict) -> dict:
    """Seal a new campaign before initialization; never retrofit a running study."""
    camp = camp.resolve()
    path = camp / "study.json"
    if (
        "study" in terms
        or path.exists()
        or path.is_symlink()
        or (camp / "campaign.json").exists()
        or (camp / "campaign.json").is_symlink()
    ):
        raise ValueError("study freeze requires a new campaign")
    _profile(terms)
    _limits(limits)
    frozen = _registry(terms)
    host_python = str(Path(sys.executable).absolute())
    store_bin = str(_store_bin())
    manifest = {
        "schema": 1,
        "camp": str(camp),
        "terms_sha256": _terms(terms),
        "limits": limits,
        "host_python": host_python,
        "store_bin": store_bin,
        "evaluator_python": str(frozen.python),
        "runner": [host_python, str(SCRIPTS / "procontract_benchmark_runner.py")],
        "python_version": sys.version,
        "environment": {key: os.environ.get(key) for key in ENVIRONMENT},
        "files": _files(mandatory_paths(terms, host_python, store_bin)),
        "scope": SCOPE,
    }
    raw = _encoded(manifest)
    if len(raw) > 16 << 20:
        raise ValueError("study manifest exceeds its size limit")
    camp.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=camp, prefix=".study-", delete=False
    ) as temporary:
        pending = Path(temporary.name)
        temporary.write(raw)
        temporary.flush()
        os.fsync(temporary.fileno())
    try:
        os.link(
            pending, path
        )  # Atomic publication, exclusively: an existing seal cannot be replaced.
        if os.name == "posix":
            directory = os.open(camp, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        pending.unlink()
    return {
        "manifest_path": str(path),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }


def verify(
    camp: Path, terms: dict, runner: list | None = None, *, evaluator=False
) -> dict:
    """Revalidate actual resources at an execution boundary; no process or model launch."""
    camp = camp.resolve()
    descriptor = terms.get("study")
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"manifest_path", "manifest_sha256"}
        or descriptor["manifest_path"] != str(camp / "study.json")
    ):
        raise ValueError("missing or redirected study descriptor")
    raw, manifest = _read(camp / "study.json")
    if hashlib.sha256(raw).hexdigest() != descriptor["manifest_sha256"]:
        raise ValueError("study manifest identity changed")
    if (
        not isinstance(manifest, dict)
        or set(manifest) != FIELDS
        or type(manifest["schema"]) is not int
        or manifest["schema"] != 1
        or manifest["camp"] != str(camp)
        or manifest["scope"] != SCOPE
        or not isinstance(manifest["environment"], dict)
        or set(manifest["environment"]) != set(ENVIRONMENT)
    ):
        raise ValueError("unsupported study manifest")
    _profile(terms)
    _limits(manifest["limits"])
    # Only this module and stdlib have run so far. Authenticate inventoried helper bytes
    # before importing registry/harness code, then derive the mandatory set independently.
    files = manifest["files"]
    if (
        not isinstance(files, dict)
        or not files
        or any(
            not isinstance(name, str) or not Path(name).is_absolute() for name in files
        )
        or not {str(path.absolute()) for path in SCRIPTS.glob("*.py")} <= files.keys()
    ):
        raise ValueError(
            "study runtime or resource inventory changed: invalid source list"
        )
    actual = _files({Path(name) for name in files})
    if actual != files:
        raise ValueError("study runtime or resource inventory changed")
    frozen = _registry(terms)
    host_python = manifest["host_python"]
    store_bin = manifest["store_bin"]
    expected_runner = [host_python, str(SCRIPTS / "procontract_benchmark_runner.py")]
    if (
        not isinstance(host_python, str)
        or not Path(host_python).is_absolute()
        or not isinstance(store_bin, str)
        or not Path(store_bin).is_absolute()
        or manifest["runner"] != expected_runner
        or (runner is not None and runner != expected_runner)
        or manifest["evaluator_python"] != str(frozen.python)
        or manifest["terms_sha256"] != _terms(terms)
    ):
        raise ValueError("study command or campaign identity changed")
    environment = {key: os.environ.get(key) for key in ENVIRONMENT}
    if evaluator:
        if str(Path(sys.executable).absolute()) != str(frozen.python) or environment[
            "PATH"
        ] != manifest["environment"].get("PATH"):
            raise ValueError("study evaluator interpreter or PATH changed")
    elif (
        str(Path(sys.executable).absolute()) != host_python
        or str(_store_bin()) != store_bin
        or sys.version != manifest["python_version"]
        or environment != manifest["environment"]
    ):
        raise ValueError("study host interpreter or environment changed")
    if {str(path) for path in mandatory_paths(terms, host_python, store_bin)} != set(
        actual
    ):
        raise ValueError("study runtime or resource inventory changed")
    return manifest
