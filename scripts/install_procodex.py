#!/usr/bin/env python3
"""Install a clean source-built package alongside Codex. No model calls or credential changes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def install(source, package, image, prefix):
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"]
    ).strip():
        raise RuntimeError("commit source and finish formatting before installation")
    receipt = json.loads((package / "build-source.json").read_text())
    if receipt["source_commit"] != revision:
        raise RuntimeError("package belongs to another source revision")
    for name in ("codex", "codex-code-mode-host", "pro-contract-store"):
        if sha(package / "bin" / name) != receipt["binaries"][name]:
            raise RuntimeError(f"package binary changed: {name}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("install requires an immutable Docker image ID")
    binary = prefix / "bin/procodex"
    if binary.is_symlink():
        raise RuntimeError("refusing to replace a procodex symlink")
    if binary.exists():
        with binary.open("rb") as existing:
            if b"PROC0DEX_LOCAL_LAUNCHER" not in existing.read(4096):
                raise RuntimeError(
                    "refusing to overwrite an unrelated procodex executable"
                )
    root = prefix / "share/procodex"
    release = root / "releases" / revision
    if release.exists():
        raise RuntimeError("release already exists; do not overwrite it")
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise RuntimeError("installation root is redirected")
    current = root / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError("current is not a managed symlink")
    release.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package, release)
    scripts = release / "scripts"
    scripts.mkdir()
    for path in (source / "scripts").glob("procontract*.py"):
        shutil.copy2(path, scripts / path.name)
    for name in ("procodex.py", "procodex_config.py"):
        shutil.copy2(source / "scripts" / name, scripts / name)
    shutil.copy2(source / "scripts/PROCODEX.md", release / "README.md")
    policies = Path("codex-rs/ext/pro-contract/policies")
    shutil.copytree(source / policies, release / policies)
    manifest = dict(
        schema=1,
        source_commit=revision,
        image=image,
        binaries=receipt["binaries"],
        native_procontract=True,
        interactive_auto_rsi=False,
        rsi_cli="explicit separately sealed research; no automatic benchmark launch",
    )
    (release / "procodex-release.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    previous = str(current.resolve()) if current.exists() else None
    binary.parent.mkdir(parents=True, exist_ok=True)
    launcher = binary.with_name("procodex.new")
    staged = root / "current.new"
    if (
        launcher.exists()
        or launcher.is_symlink()
        or staged.exists()
        or staged.is_symlink()
    ):
        raise RuntimeError("a partial installation exists; preserve it for inspection")
    import shlex

    with launcher.open("x") as output:
        output.write(
            "#!/bin/sh\n# PROC0DEX_LOCAL_LAUNCHER\nexec "
            + shlex.quote(sys.executable)
            + " "
            + shlex.quote(str(current / "scripts/procodex.py"))
            + ' "$@"\n'
        )
    launcher.chmod(0o755)
    (release / "install.json").write_text(
        json.dumps(
            dict(previous=previous, executable=str(binary), python=sys.executable),
            indent=2,
        )
        + "\n"
    )
    staged.symlink_to(release)
    staged.replace(current)
    launcher.replace(binary)
    return dict(
        executable=str(binary),
        release=str(release),
        source_commit=revision,
        previous=previous,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    print(
        json.dumps(
            install(source, args.package.resolve(), args.image, args.prefix.resolve()),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
