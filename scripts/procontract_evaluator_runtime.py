"""Pinned grader-only resources and observable pytest attempt boundaries."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import threading
import time
from types import MappingProxyType

ROOT = "/opt/procontract-grader"
PLUGIN_ROOT = "/tmp/procontract-test-runtime"
PLUGIN_NAME = "_pc_test_runtime"

# These are private, serial command environments owned by the evaluator. Preserve
# their initial service processes, including a sleep child below Docker's PID-1
# init, when an individual command times out. The benchmark's commands, command
# deadlines, test retries and container lifetime are unchanged.
SERVICE_PROCESSES = r'''import json,os
from pathlib import Path
rows={}
for path in Path('/proc').iterdir():
    if not path.name.isdigit() or int(path.name)==os.getpid():continue
    try:
        fields=(path/'stat').read_text().rsplit(')',1)[1].split()
        rows[path.name]=fields[19]
    except (OSError,IndexError):pass
print(json.dumps(rows))
'''
STOP_COMMAND_PROCESSES = r'''import json,os,signal,sys,time
from pathlib import Path
services=json.loads(sys.argv[1]);own=os.getpid();stopped=set();end=time.monotonic()+25
def active():
    rows=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) in (1,own):continue
        try:
            fields=(path/'stat').read_text().rsplit(')',1)[1].split()
            if fields[0]!='Z' and services.get(path.name)!=fields[19]:rows.append(int(path.name))
        except (OSError,IndexError):pass
    return rows
while True:
    remaining=active()
    if not remaining or time.monotonic()>=end:break
    for pid in remaining:
        try:os.kill(pid,signal.SIGKILL);stopped.add(pid)
        except ProcessLookupError:pass
    time.sleep(.02)
print(json.dumps({'confirmed':not remaining,'stopped':sorted(stopped),'remaining':remaining,
    'scope':'command processes in this private evaluator container; initial service identities preserved'}))
sys.exit(0 if not remaining else 1)
'''


def preserve_container_service(env):
    """Bind timeout cleanup to a private grader environment, not its keepalive."""
    if getattr(env, "_pc_service_preserved", False):
        return env
    observed = subprocess.run([env.executable, "exec", env.container_id, "python3", "-c", SERVICE_PROCESSES],
                              capture_output=True, text=True, check=True, timeout=10)
    services = json.loads(observed.stdout)
    lock = threading.Lock()

    def execute(command, *, timeout=None):
        with lock:
            limit = timeout or env.default_timeout
            if env.deadline is not None:
                remaining = env.deadline - time.monotonic()
                if remaining <= 0:
                    return {"output": "", "returncode": -1, "exception_info": "Workflow wall-time exhausted"}
                limit = min(limit, remaining)
            argv = [env.executable, "exec", "-w", env.cwd, env.container_id, "bash", "-lc", command]
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=limit)
                return {"output": result.stdout + result.stderr, "returncode": result.returncode, "exception_info": ""}
            except subprocess.TimeoutExpired as error:
                try:
                    stopped = subprocess.run([env.executable, "exec", env.container_id, "python3", "-c",
                        STOP_COMMAND_PROCESSES, json.dumps(services)], capture_output=True, text=True, timeout=30)
                    cleanup = json.loads(stopped.stdout) if stopped.returncode == 0 else {
                        "confirmed": False, "exit_code": stopped.returncode, "stdout": stopped.stdout, "stderr": stopped.stderr}
                except (OSError, ValueError, subprocess.SubprocessError) as failure:
                    cleanup = {"confirmed": False, "error": str(failure)}
                output = "".join(value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                                 for value in (error.stdout, error.stderr))
                return {"output": output, "returncode": -1,
                        "exception_info": f"Command timed out after {limit}s", "timeout_cleanup": cleanup}

    env.execute = execute
    env._pc_service_preserved = True
    return env


def install_plugin_path(run_step, env, log_buf, directory):
    """Keep admitted observers importable when an official script resets PYTHONPATH.

    Use the interpreter that already imports the installed pytest. Only its search
    path is extended; test scripts, cases and assertions are untouched.
    """
    name = "procontract-observer-" + hashlib.sha256(directory.encode()).hexdigest()[:16] + ".pth"
    code = ("from pathlib import Path; import pytest; "
            f"(Path(pytest.__file__).resolve().parent.parent / {name!r}).write_text({directory!r} + '\\n')")
    return run_step(shlex.join(["python3", "-c", code]), env=env, log_buf=log_buf,
                    step_name="retain_observer_import_path", timeout=10)
PLUGIN = '''import gc
import hashlib
import json
import os
from pathlib import Path
import pytest

def _transport_text(value):
    limit = int(os.environ.get("PC_GRADER_REPORT_TEXT_CHARS", "0"))
    if isinstance(value, str) and limit > 0 and len(value) > limit:
        digest = hashlib.sha256()
        for start in range(0, len(value), 65536):
            digest.update(value[start:start+65536].encode("utf-8", errors="backslashreplace"))
        edge = limit // 2
        return (value[:edge] + "\\n[diagnostic text abbreviated for transport; chars="
                + str(len(value)) + "; utf8_sha256=" + digest.hexdigest() + "]\\n" + value[-edge:])
    if isinstance(value, dict):
        return {key: _transport_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_transport_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_transport_text(item) for item in value)
    return value

@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_report_to_serializable(config, report):
    outcome = yield
    data = outcome.get_result()
    if isinstance(data, dict):
        # Assertions have already executed. Only rendered diagnostics and
        # captured-output sections are transported in bounded form; outcome,
        # test identity, retry count and execution timeout remain untouched.
        for name in ("longrepr", "sections"):
            if name in data:
                data[name] = _transport_text(data[name])

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
    prepare: tuple[str, ...] = ()

    def verify(self):
        with self.archive.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != self.sha256:
            raise ValueError("pinned grader resource archive changed")


def load_assets(value):
    required = {"archive", "sha256", "environment", "path_prepend"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"prepare"}:
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
    prepare = value.get("prepare", [])
    if not isinstance(prepare, list) or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in prepare):
        raise ValueError("grader preparation must be an explicit command argument list")
    result = Assets(path, value["sha256"], MappingProxyType(environment), tuple(prepend), tuple(prepare))
    result.verify()
    return result


def runtime_evaluator(base, assets=None, *, test_workspace="inherit", test_suite_seconds=None):
    if test_workspace not in ("inherit", "isolated"):
        raise ValueError("unknown test workspace profile")
    if test_suite_seconds is not None and (type(test_suite_seconds) is not int or test_suite_seconds <= 0):
        raise ValueError("test suite allocation must be a positive integer")
    class RuntimeEvaluator(base):
        def _new_env(self, *args, **kwargs):
            env = super()._new_env(*args, **kwargs)
            try:
                from procontract_submission_transport import install_submission_transport, restore_workspace_transport
                install_submission_transport(preserve_container_service(env))
                if kwargs.get('testing'):
                    restore_workspace_transport(env)
                if kwargs.get('testing') and test_workspace == 'isolated':
                    # Retain the complete build tree outside the official test
                    # source tree. The compiled subject is already stashed by the
                    # pinned evaluator and is restored/hashed by its normal path.
                    code = ("import json,os,subprocess,tempfile; "
                            "retained=tempfile.mkdtemp(prefix='procontract-candidate-build-',dir='/opt'); "
                            "subprocess.run(['cp','-a','--reflink=auto','/workspace/.',retained+'/workspace'],check=True); "
                            "[subprocess.run(['rm','-rf','--',entry.path],check=True) for entry in os.scandir('/workspace')]; "
                            "print(json.dumps({'retained_build_workspace':retained+'/workspace',"
                            "'test_workspace':'/workspace','compiled_subject':'unchanged stashed executable'}))")
                    result = env.execute(shlex.join(['python3', '-I', '-S', '-c', code]), timeout=30)
                    if result['returncode']:
                        raise RuntimeError('cannot isolate test source workspace: ' + result['output'])
                    env._pc_test_workspace = result
                return env
            except BaseException:
                env.cleanup()
                raise

        def _compile_executable(self, env, log_buf):
            try:
                super()._compile_executable(env, log_buf)
            finally:
                env._pc_transport_log = log_buf
                if hasattr(env, '_pc_submission_transport'):
                    log_buf.append({'step': 'submission_transport', **env._pc_submission_transport})
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
            if assets.prepare:
                self._run_step(shlex.join(assets.prepare), env=env, log_buf=log_buf,
                               step_name="prepare_pinned_grader_assets", timeout=120)
            result = self._run_step(shlex.join(["sha256sum", self._stashed_executable]),
                env=env, log_buf=log_buf, step_name="verify_candidate_after_grader_assets", timeout=10)
            if result.get("output", "").split()[0] != self.result.executable_hash:
                raise RuntimeError("grader assets changed the compiled candidate")

        def _run_step(self, command, **kwargs):
            env = kwargs.get('env')
            if env is not None and hasattr(env, '_pc_restored_workspace'):
                kwargs['log_buf'].append({'step': 'restore_compiled_workspace', **env._pc_restored_workspace})
                del env._pc_restored_workspace
            if env is not None and hasattr(env, '_pc_test_workspace'):
                kwargs['log_buf'].append({'step': 'isolate_test_source_workspace', **env._pc_test_workspace})
                del env._pc_test_workspace
            if kwargs.get("step_name") != "run_tests":
                return super()._run_step(command, **kwargs)
            if test_suite_seconds is not None:
                # Only the operator's suite execution grant changes. Official
                # test commands retain their own per-test limits and retries.
                kwargs["timeout"] = test_suite_seconds
            env = kwargs["env"]
            super()._run_step(f"mkdir -p {PLUGIN_ROOT}", env=env, log_buf=kwargs["log_buf"],
                step_name="prepare_test_attempt_observer", timeout=10)
            with tempfile.TemporaryDirectory(prefix="pc-test-runtime-") as temporary:
                plugin = Path(temporary) / (PLUGIN_NAME + ".py")
                plugin.write_text(PLUGIN)
                env.copy_in(plugin, PLUGIN_ROOT + "/" + plugin.name)
            install_plugin_path(super()._run_step, env, kwargs["log_buf"], PLUGIN_ROOT)
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
