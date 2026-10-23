"""Exercise evaluator bootstrap and collection without judging a candidate.

This module is host-only. Test identities stay in the grading domain; the
published receipt contains counts and a digest, never solver feedback.
"""
import hashlib
import json
import shlex
import os
import subprocess
import tempfile
import uuid
from pathlib import Path


COLLECTOR = '''import json
from pathlib import Path
import pytest
from _pytest.junitxml import mangle_test_address

class _WorkerCollectionNames:
    def pytest_collection_modifyitems(self, config, items):
        from xdist.remote import WorkerInteractor
        WorkerInteractor.pytest_collection_modifyitems(None, config, items)

@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    config.option.collectonly = True
    if hasattr(config.option, "numprocesses"):
        config.option.numprocesses = 0
    # Register at worker-setup time, preserving ordering relative to conftest
    # hooks. Applying this at collection_finish would also rename marks added
    # later by a conftest, unlike the official worker.
    if config.getoption("dist", default=None) == "loadgroup":
        config.option.loadgroup = True
        config.pluginmanager.register(_WorkerCollectionNames(), "pc_worker_collection_names")

def pytest_collection_finish(session):
    prefix = session.config.getoption("junitprefix", default=None)
    names = []
    for item in session.items:
        parts = mangle_test_address(item.nodeid)
        if prefix:
            parts.insert(0, prefix)
        names.append(".".join(parts))
    Path("/tmp/procontract-collection.json").write_text(json.dumps({
        "names": names, "errors": session.testsfailed,
        "collection_only": bool(session.config.option.collectonly)}))

@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session):
    return True
'''


def retain_image_reference(env, image, log_buf):
    # The official compile environment deliberately erases the image workspace.
    # Extract from a never-started container, outside all candidate workspaces.
    name = "pc-readiness-reference-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="pc-reference-") as directory:
        path = Path(directory) / "reference"
        try:
            subprocess.run([env.executable, "create", "--name", name, "--network", "none", image],
                check=True, capture_output=True, timeout=30)
            subprocess.run([env.executable, "cp", name+":/workspace/executable", str(path)],
                check=True, capture_output=True, timeout=30)
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("frozen image reference must be a regular file")
            os.chmod(path, 0o600)
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            env.copy_in(path, "/tmp/procontract-readiness-reference")
            log_buf.append({"step":"retain_image_reference_for_collection", "image":image,
                "reference_sha256":digest, "returncode":0})
            return digest
        finally:
            removed = subprocess.run([env.executable, "rm", "-f", name],
                capture_output=True, timeout=30)
            if removed.returncode and b"No such container" not in removed.stderr:
                raise RuntimeError("reference extraction container cleanup unconfirmed")


def collection_evaluator(base):
    class CollectionEvaluator(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.collected = {}
            self.reference_hash = None

        def _compile_executable(self, env, log_buf):
            # Collection can call the program at module import (e.g. --help).
            # Keep the image's trusted reference solely in this host-only probe.
            # The null submission still exercises the ordinary build/hash path.
            self.reference_hash = retain_image_reference(env, f"{self.image_name}:{self.image_tag}", log_buf)
            super()._compile_executable(env, log_buf)

        def _restore_executable(self, env, log_buf):
            super()._restore_executable(env, log_buf)
            result = self._run_step(
                "cp /tmp/procontract-readiness-reference /workspace/executable && "
                "chmod +x /workspace/executable && sha256sum /workspace/executable",
                env=env, log_buf=log_buf, step_name="use_image_reference_only_for_collection", timeout=30,
            )
            if result["output"].split()[0] != self.reference_hash:
                raise RuntimeError("collection reference changed from its frozen image")

        def _run_step(self, command, **kwargs):
            if kwargs.get("step_name") == "run_tests":
                install = (
                    "from pathlib import Path; "
                    "p=Path('/tmp/procontract-readiness');p.mkdir(exist_ok=True);"
                    f"(p/'_pc_collection_probe.py').write_text({COLLECTOR!r})"
                )
                super()._run_step(
                    shlex.join(["python3", "-c", install]),
                    env=kwargs["env"], log_buf=kwargs["log_buf"],
                    step_name="install_collection_probe", timeout=10,
                )
                command = (
                    'export PYTHONPATH="/tmp/procontract-readiness${PYTHONPATH:+:$PYTHONPATH}"; '
                    'export PYTEST_PLUGINS="_pc_collection_probe${PYTEST_PLUGINS:+,$PYTEST_PLUGINS}"; '
                    'export PYTEST_ADDOPTS="$PYTEST_ADDOPTS --collect-only"; ' + command
                )
                kwargs["timeout"] = 60
            return super()._run_step(command, **kwargs)

        def _copy_file_from_container(self, **kwargs):
            if kwargs.get("step_name") == "results_read":
                kwargs["container_path"] = "/tmp/procontract-collection.json"
            return super()._copy_file_from_container(**kwargs)

        def _evaluate_branch(self, branch, image):
            observed = json.loads(self._run_test_branch(branch, image, self.result.log))
            names = observed.get("names")
            if (observed.get("collection_only") is not True or observed.get("errors") != 0
                    or not isinstance(names, list) or not all(isinstance(n, str) for n in names)
                    or len(names) != len(set(names))):
                raise RuntimeError(
                    "evaluator collection is incomplete or malformed: "
                    f"collection_only={observed.get('collection_only')!r}, "
                    f"errors={observed.get('errors')!r}, "
                    f"count={len(names) if isinstance(names, list) else None}, "
                    f"unique={len(set(names)) if isinstance(names, list) and all(isinstance(n, str) for n in names) else None}"
                )
            expected = {name for name in self.tests_by_branch[branch]
                        if f"{branch}/{name}" not in self.ignored_tests}
            actual = {name for name in names if f"{branch}/{name}" not in self.ignored_tests}
            if actual != expected:
                raise RuntimeError(
                    f"evaluator eligible collection differs: missing={len(expected-actual)}, extra={len(actual-expected)}"
                )
            self.collected[branch] = sorted(actual)

        def readiness(self):
            result = self.run()
            if result.error_code or set(self.collected) != set(self.tests_branches):
                raise RuntimeError("evaluator bootstrap or collection did not complete")
            encoded = json.dumps(self.collected, sort_keys=True, separators=(",", ":")).encode()
            return {
                "valid": True, "total": sum(map(len, self.collected.values())),
                "branches": len(self.collected), "attempts": 1,
                "compiled_executable_hash": result.executable_hash,
                "collection_reference_hash": self.reference_hash,
                "collection_sha256": hashlib.sha256(encoded).hexdigest(),
                "mode": "reference_collection_only", "collector_sha256": hashlib.sha256(COLLECTOR.encode()).hexdigest(),
            }

    return CollectionEvaluator
