"""Apply official pytest module exclusions before import, in both collection and grading.

A catalogue entry can name a collector module rather than an individual test. Filtering
only final leaf names loses that exclusion when a repaired dependency makes the module
collectible. Resolve the supplied names against actual pytest module identities instead
of guessing path prefixes or adding task-specific exclusions.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import threading
import tarfile


DIRECTORY = "/tmp/procontract-test-scope"
PLUGIN_NAME = "_pc_official_scope"
PLUGIN = '''import hashlib
import json
from pathlib import Path
import pytest
from _pytest.junitxml import mangle_test_address

_root = Path(__file__).parent
_bytes = (_root / "scope.json").read_bytes()
_scope = json.loads(_bytes)
_ignored = frozenset(_scope["ignored"])
_eligible = _scope.get("eligible", [])
_files = _scope.get("files")
_work_root = Path(_scope.get("root", "/workspace"))
_allowed = None if _files is None else frozenset(_work_root / name for name in _files)
_excluded = set()
_foreign = set()

@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path, config):
    if _allowed is None:
        return None
    path = Path(collection_path).absolute()
    if path in _allowed or any(path in source.parents for source in _allowed):
        return None
    _foreign.add(str(path.relative_to(_work_root)) if path.is_relative_to(_work_root) else str(path))
    return True

def _identity(node):
    parts = mangle_test_address(node.nodeid)
    prefix = node.config.getoption("junitprefix", default=None)
    if prefix:
        parts.insert(0, prefix)
    return ".".join(parts)

class _ExcludedModule(pytest.Module):
    def collect(self):
        _excluded.add(_identity(self))
        return ()

@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makemodule(module_path, parent):
    node = pytest.Module.from_parent(parent, path=module_path)
    identity = _identity(node)
    if identity in _ignored and not any(name.startswith(identity + ".") for name in _eligible):
        return _ExcludedModule.from_parent(parent, path=module_path)
    return None

@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if hasattr(session.config, "workeroutput"):
        session.config.workeroutput["pc_official_excluded_modules"] = sorted(_excluded)
        session.config.workeroutput["pc_nonofficial_paths"] = sorted(_foreign)
        return
    (_root / "receipt.json").write_text(json.dumps({
        "schema": 1, "selectors_sha256": hashlib.sha256(_bytes).hexdigest(),
        "excluded_modules": sorted(_excluded), "nonofficial_paths": sorted(_foreign),
        "scope": "Exact official module identities excluded before import; leaf exclusions remain in the official scorer."}))

@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    _excluded.update(node.workeroutput.get("pc_official_excluded_modules", []))
    _foreign.update(node.workeroutput.get("pc_nonofficial_paths", []))
'''


def archive_files(archive):
    """The pinned official archive, not submission content, supplies discovery paths."""
    paths = set()
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("official archive path escapes its workspace")
            if member.isfile() or member.issym() or member.islnk():
                paths.add(str(path))
    return sorted(paths)


def scoped_evaluator(base):
    class ScopedEvaluator(base):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._official_scope = threading.local()

        def _run_test_branch(self, branch, image, log_buf, **kwargs):
            prefix = branch + "/"
            eligible = set(self.tests_by_branch[branch]) - {
                name[len(prefix):] for name in self.ignored_tests if name.startswith(prefix)
            }
            if not eligible:
                log_buf.append({"step":"empty_official_scope", "branch":branch,
                    "eligible_count":0,"returncode":0,
                    "meaning":"No eligible tests in the pinned official scope; no branch setup or tests executed."})
                return '<testsuites><testsuite tests="0" errors="0" failures="0" skipped="0" /></testsuites>'
            self._official_scope.eligible = sorted(eligible)
            self._official_scope.files = archive_files(Path(self.blob_dir) / "tests" / (branch + ".tar.gz"))
            self._official_scope.ignored = sorted(
                name[len(prefix):] for name in self.ignored_tests if name.startswith(prefix)
            )
            try:
                return super()._run_test_branch(branch, image, log_buf, **kwargs)
            finally:
                del self._official_scope.ignored
                del self._official_scope.files
                del self._official_scope.eligible

        def _run_step(self, command, **kwargs):
            ignored = getattr(self._official_scope, "ignored", [])
            files = getattr(self._official_scope, "files", None)
            if kwargs.get("step_name") != "run_tests" or files is None:
                return super()._run_step(command, **kwargs)
            payload = json.dumps({"ignored": ignored, "eligible":self._official_scope.eligible,
                "root":"/workspace", "files":files}, sort_keys=True).encode()
            env = kwargs["env"]
            super()._run_step(
                f"mkdir -p {DIRECTORY}", env=env, log_buf=kwargs["log_buf"],
                step_name="prepare_official_test_scope", timeout=10,
            )
            with tempfile.TemporaryDirectory(prefix="pc-test-scope-") as temporary:
                root = Path(temporary)
                (root / (PLUGIN_NAME + ".py")).write_text(PLUGIN)
                (root / "scope.json").write_bytes(payload)
                for name in (PLUGIN_NAME + ".py", "scope.json"):
                    env.copy_in(root / name, DIRECTORY + "/" + name)
            command = (
                f'export PYTHONPATH="{DIRECTORY}${{PYTHONPATH:+:$PYTHONPATH}}"; '
                f'export PYTEST_PLUGINS="{PLUGIN_NAME}${{PYTEST_PLUGINS:+,$PYTEST_PLUGINS}}"; '
                + command
            )
            result = super()._run_step(command, **kwargs)
            receipt = json.loads(super()._copy_file_from_container(
                env=env, log_buf=kwargs["log_buf"], container_path=DIRECTORY + "/receipt.json",
                step_name="official_test_scope_receipt", timeout=10,
            ))
            if (receipt.get("selectors_sha256") != hashlib.sha256(payload).hexdigest()
                    or not isinstance(receipt.get("excluded_modules"), list)
                    or not all(isinstance(name, str) and name in ignored
                               for name in receipt["excluded_modules"])):
                raise RuntimeError("test collection scope differs from the official exclusions")
            return result

    return ScopedEvaluator
