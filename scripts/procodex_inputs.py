"""Provision named, task-owned read-only files independently of mutable work outputs."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


def declarations(items):
    result = {}
    for name, source in (items or {}).items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name):
            raise ValueError("input names must be plain names, not paths")
        result[name] = os.path.abspath(os.path.expanduser(str(source)))
    return dict(sorted(result.items()))


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provision(home, inputs):
    """Snapshot once; reopening a task retains its original files and their modes.

    A source may change or disappear after admission. That does not silently
    replace this task's input or create a new task grant. A new task home admits
    new inputs. Docker mounts individual files read-only at /inputs/<name>.
    """
    inputs = declarations(inputs)
    if not inputs:
        return []
    root = home / "inputs"
    if root.is_symlink():
        raise ValueError("task input store is redirected")
    if not root.exists():
        staged = Path(tempfile.mkdtemp(prefix=".inputs-", dir=home))
        try:
            (staged / "files").mkdir()
            entries = {}
            for name, source in inputs.items():
                original = Path(source)
                if not original.is_file():
                    raise ValueError(f"declared input is not a regular file: {name}")
                target = staged / "files" / name
                shutil.copy2(original, target)
                entries[name] = dict(source=source, sha256=sha(target),
                                     mode=stat.S_IMODE(target.stat().st_mode))
            (staged / "manifest.json").write_text(json.dumps(entries, sort_keys=True) + "\n")
            staged.rename(root)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    manifest = root / "manifest.json"
    if manifest.is_symlink():
        raise ValueError("task input manifest is redirected")
    entries = json.loads(manifest.read_text())
    if {name: entry['source'] for name, entry in entries.items()} != inputs:
        raise ValueError("input declarations differ from this task's retained inputs")
    mounts = []
    for name, entry in entries.items():
        source = root / "files" / name
        if (source.is_symlink() or not source.is_file() or sha(source) != entry['sha256']
                or stat.S_IMODE(source.stat().st_mode) != entry['mode']):
            raise ValueError(f"retained input changed: {name}")
        mounts.append(dict(name=name, source=str(source), target="/inputs/"+name,
                           sha256=entry['sha256']))
    return mounts
