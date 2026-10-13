"""Losslessly archive only a completed sweep's own native home; never user workspaces."""

import json
import os
from pathlib import Path
import shutil
import tarfile
import time

import procontract_online_plan as plans


def archive_home(run):
    run = Path(run)
    home = run / "codex-home"
    if home.is_symlink() or not home.is_dir():
        raise ValueError("archive source is not the owned native home")
    summary = json.loads((run / "run.json").read_text())
    if summary.get("native_process_exit", {}).get("status") != "exited":
        raise ValueError("native home is still in use or its lifetime is unknown")
    archive = run / "codex-home.tar.gz"
    temporary = run / "codex-home.tar.gz.partial"
    if archive.exists() or temporary.exists():
        raise ValueError("archive already exists; never overwrite evidence")
    started = time.monotonic()
    with temporary.open("xb") as output:
        with tarfile.open(
            fileobj=output, mode="w:gz", compresslevel=1, dereference=False
        ) as bundle:
            bundle.add(home, arcname="codex-home")
        output.flush()
        os.fsync(output.fileno())
    # Validate the compressed stream before removing the redundant directory.
    with tarfile.open(temporary, "r:gz") as bundle:
        count = sum(1 for _ in bundle)
    temporary.replace(archive)
    receipt = {
        "archive": archive.name,
        "sha256": plans.sha(archive),
        "members": count,
        "elapsed_secs": time.monotonic() - started,
        "scope": "lossless native-home archive after native exit and evaluation; workspace, submission and result retained",
    }
    plans.publish(run / "codex-home-archive.json", receipt)
    shutil.rmtree(home)
    return receipt
