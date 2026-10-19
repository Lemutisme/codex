"""Pinned grader-only resources and observable pytest attempt boundaries."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import tempfile
from types import MappingProxyType

ROOT = "/opt/procontract-grader"
PLUGIN_ROOT = "/tmp/procontract-test-runtime"
PLUGIN_NAME = "_pc_test_runtime"
PLUGIN = '''import gc
import json
from pathlib import Path
import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    # Finished attempts may leave exception/fixture cycles retaining file descriptors.
    # Release unreachable objects before another attempt, without closing live resources
    # or changing the official retry count, assertions, timeout or scheduling policy.
    gc.collect()

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    worker = getattr(item.config, "workerinput", {}).get("workerid", "main")
    record = {"test_id":item.nodeid, "phase":report.when, "outcome":report.outcome,
        "attempt":getattr(item, "execution_count", 1),
        "exception_type":call.excinfo.typename if call.excinfo else None,
        "message":str(call.excinfo.value)[:2000] if call.excinfo else None}
    with (Path(__file__).parent / ("attempts-" + worker + ".jsonl")).open("a") as stream:
        stream.write(json.dumps(record) + "\\n")
    if call.excinfo:
        # The diagnostic report is materialized. Discard finished invocation locals,
        # including the locals view cached while rendering the traceback, so a retry
        # does not inherit otherwise-unreachable resources. Executing frames and
        # resources still owned by live fixtures/globals are unaffected.
        for entry in call.excinfo.traceback:
            frame = entry.frame.raw
            try:
                frame.clear()
            except RuntimeError:
                continue
            _ = frame.f_locals
'''


@dataclass(frozen=True)
class Assets:
    archive: Path
    sha256: str
    environment: object
    path_prepend: tuple[str, ...]

    def verify(self):
        with self.archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != self.sha256:
            raise ValueError("pinned grader resource archive changed")


def load_assets(value):
    if not isinstance(value, dict) or set(value) != {"archive", "sha256", "environment", "path_prepend"}:
        raise ValueError("grader assets need archive, sha256, environment and path_prepend")
    path = Path(value["archive"])
    environment, prepend = value["environment"], value["path_prepend"]
    if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise ValueError("grader asset archive must have an absolute path and SHA-256")
    if not isinstance(environment, dict) or any(
        not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        or not isinstance(text, str) or "\0" in text
        for name, text in environment.items()
    ):
        raise ValueError("invalid grader environment")
    if not isinstance(prepend, list) or any(
        not isinstance(part, str) or not part or Path(part).is_absolute()
        or ".." in Path(part).parts or ":" in part or "\0" in part for part in prepend
    ):
        raise ValueError("grader PATH additions must be relative archive paths")
    result = Assets(path, value["sha256"], MappingProxyType(environment), tuple(prepend))
    result.verify()
    return result


def runtime_evaluator(base, assets=None):
    class RuntimeEvaluator(base):
        def _compile_executable(self, env, log_buf):
            super()._compile_executable(env, log_buf)
            if assets is None:
                return
            assets.verify()
            env.copy_in(assets.archive, "/tmp/procontract-grader-assets.tar.gz")
            command = (
                "sha256sum /tmp/procontract-grader-assets.tar.gz && "
                f"mkdir -p {ROOT} && tar --no-same-owner --delay-directory-restore -xzf /tmp/procontract-grader-assets.tar.gz -C {ROOT} && "
                "rm /tmp/procontract-grader-assets.tar.gz"
            )
            result = self._run_step(command, env=env, log_buf=log_buf,
                step_name="install_pinned_grader_assets_after_candidate_hash", timeout=120)
            if result.get("output", "").split()[0] != assets.sha256:
                raise RuntimeError("copied grader assets differ from pinned archive")
            result = self._run_step(shlex.join(["sha256sum", self._stashed_executable]),
                env=env, log_buf=log_buf, step_name="verify_candidate_after_grader_assets", timeout=10)
            if result.get("output", "").split()[0] != self.result.executable_hash:
                raise RuntimeError("grader assets changed the compiled candidate")

        def _run_step(self, command, **kwargs):
            if kwargs.get("step_name") != "run_tests":
                return super()._run_step(command, **kwargs)
            env = kwargs["env"]
            super()._run_step(f"mkdir -p {PLUGIN_ROOT}", env=env, log_buf=kwargs["log_buf"],
                step_name="prepare_test_attempt_observer", timeout=10)
            with tempfile.TemporaryDirectory(prefix="pc-test-runtime-") as temporary:
                plugin = Path(temporary) / (PLUGIN_NAME + ".py")
                plugin.write_text(PLUGIN)
                env.copy_in(plugin, PLUGIN_ROOT + "/" + plugin.name)
            prefix = (
                f'export PYTHONPATH="{PLUGIN_ROOT}${{PYTHONPATH:+:$PYTHONPATH}}"; '
                f'export PYTEST_PLUGINS="{PLUGIN_NAME}${{PYTEST_PLUGINS:+,$PYTEST_PLUGINS}}"; '
            )
            if assets is not None:
                prefix += "".join(f"export {name}={shlex.quote(value)}; " for name, value in assets.environment.items())
                if assets.path_prepend:
                    paths = ":".join(ROOT + "/" + part for part in assets.path_prepend)
                    prefix += f'export PATH={shlex.quote(paths)}:"$PATH"; '
            result = super()._run_step(prefix + command, **kwargs)
            # Preserve each attempt, including the original failure preceding any rerun.
            merge = "from pathlib import Path; p=Path(" + repr(PLUGIN_ROOT) + "); (p/'attempts.jsonl').write_text(''.join(f.read_text() for f in sorted(p.glob('attempts-*.jsonl'))))"
            super()._run_step(shlex.join(["python3", "-c", merge]), env=env,
                log_buf=kwargs["log_buf"], step_name="collect_test_attempt_observations", timeout=10)
            super()._copy_file_from_container(env=env, log_buf=kwargs["log_buf"],
                container_path=PLUGIN_ROOT + "/attempts.jsonl", step_name="test_attempt_observations", timeout=10)
            return result

    return RuntimeEvaluator
