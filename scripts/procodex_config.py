"""Host-owned local configuration and isolation boundaries; never starts inference."""

import hashlib
import json
import os
from pathlib import Path
import tomllib

import procodex_inputs


def toml(document, prefix=()):
    lines = []
    for key, value in document.items():
        if value is not None and not isinstance(value, dict):
            lines.append(f"{json.dumps(key)} = {json.dumps(value, ensure_ascii=False)}")
    for key, value in document.items():
        if isinstance(value, dict):
            names = (*prefix, key)
            lines.extend(
                [
                    "",
                    "[" + ".".join(json.dumps(name) for name in names) + "]",
                    toml(value, names),
                ]
            )
    return "\n".join(lines) + "\n"


def atomic(path, content):
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("redirected ProCodex state path")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as output:
        output.write(content)
    temporary.chmod(0o600)
    temporary.replace(path)


def configure(
    package,
    workspace,
    root,
    source_home,
    image,
    check,
    *,
    isolation="nested",
    successor_sessions=None,
    task_seconds=None,
    review_compute=False,
    continuous_work=False,
    inputs=None,
    strategy=None,
):
    """Copy routing only; never carry hooks, MCP, global permissions or project trust over."""
    if isolation not in ("nested", "container-only"):
        raise ValueError("unknown execution isolation")
    if (successor_sessions is not None and
            (type(successor_sessions) is not int or not 0 <= successor_sessions <= 2**32-1)) or (task_seconds is not None and
            (type(task_seconds) is not int or not 1 <= task_seconds <= (2**64-1)//1000)):
        raise ValueError(
            "session count must be nonnegative and an explicit task duration must be positive and representable"
        )
    if any(c in str(workspace) for c in ("\n", "\0", ",")):
        raise ValueError("workspace path is not representable as a Docker bind mount")
    source = source_home / "config.toml"
    base = tomllib.loads(source.read_text()) if source.is_file() else {}
    custom = root / "config.toml"
    own = tomllib.loads(custom.read_text()) if custom.is_file() else {}
    provider_name = own.get("model_provider", base.get("model_provider", "openai"))
    provider = own.get("model_providers", base.get("model_providers", {})).get(
        provider_name
    )
    config = dict(
        model=own.get("model", "gpt-5.6-luna"),
        model_reasoning_effort=own.get("model_reasoning_effort", "max"),
        model_provider=provider_name,
        approval_policy="on-request",
        sandbox_mode="workspace-write"
        if isolation == "nested"
        else "danger-full-access",
        web_search="disabled",
        cli_auth_credentials_store="file",
        features=dict(
            pro_contract=True,
            hooks=False,
            apps=False,
            plugins=False,
            multi_agent=False,
            multi_agent_v2=False,
        ),
        agents=dict(enabled=False),
        developer_instructions="Execution tools run only in an offline Docker container. Only the selected project is mounted writable; host state and credentials are not mounted. Do not attempt external network access or dependency installation. Native ProContract reviews frozen artifacts; this does not establish RSI gain.",
    )
    if provider is not None:
        allowed = {
            "name",
            "base_url",
            "env_key",
            "env_key_instructions",
            "wire_api",
            "supports_websockets",
            "requires_openai_auth",
            "http_headers",
            "env_http_headers",
            "request_max_retries",
            "stream_max_retries",
            "stream_idle_timeout_ms",
        }
        config["model_providers"] = {
            provider_name: {
                key: value for key, value in provider.items() if key in allowed
            }
        }
    identity = dict(
        workspace=str(workspace), image=image, check=check, isolation=isolation
    )
    declared_inputs = procodex_inputs.declarations(inputs)
    if declared_inputs:
        identity["inputs"] = declared_inputs
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    home = root / "workspaces" / key
    if any(path.is_symlink() for path in (home, *home.parents)):
        raise ValueError("redirected ProCodex workspace state")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    attachments = procodex_inputs.provision(home, declared_inputs)
    config["sqlite_home"] = str(home)
    config["log_dir"] = str(home / "log")
    input_args = []
    for attachment in attachments:
        input_args += ["--mount", f'type=bind,src={attachment["source"]},dst={attachment["target"]},readonly']
    if attachments:
        config["developer_instructions"] += "\nDeclared read-only task inputs:\n" + "\n".join(
            f'- {item["name"]}: {item["target"]} (SHA-256 {item["sha256"]})'
            for item in attachments)
    docker_args = [
        "run",
        "-i",
        "--rm",
        "--network",
        "none",
        "--label", f"procontract.task={key}",
        "--log-driver", "local", "--log-opt", "max-size=16m", "--log-opt", "max-file=2",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "8g",
        "--memory-swap",
        "8g",
        "--pids-limit",
        "512",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        f"type=bind,src={workspace},dst=/workspace",
        "--mount",
        f"type=bind,src={package},dst=/opt/procodex,readonly",
        *input_args,
        "-w",
        "/workspace",
        image,
        "/bin/bash",
        "-c",
        'mkdir -p "$HOME" && exec /opt/procodex/bin/codex exec-server --listen stdio --max-process-output-bytes 33554432 --max-total-output-bytes 268435456 --max-process-seconds 1800',
    ]
    # The environment format uses a TOML array of tables, not an inline JSON object.
    env_text = 'default="procodex"\ninclude_local=false\n[[environments]]\nid="procodex"\nprogram="docker"\n'
    env_text += "args=" + json.dumps(docker_args) + "\n"
    settings = dict(
        evaluation=dict(
            environment_id="procodex",
            workspace_container_root="/workspace",
            workspace_host_root=str(workspace),
            excluded_paths=[
                ".git",
                ".venv",
                "node_modules",
                "target",
                "__pycache__",
                ".procodex",
            ],
            check=dict(
                docker="docker",
                image=image,
                user=f"{os.getuid()}:{os.getgid()}",
                candidate_mount="/candidate",
                timeout_secs=300,
                build_command=check,
                candidate_command=None,
            ),
            reference_command=None,
        ),
        repair_attempts=1,
        worker=dict(model=None, reasoning_effort=None, deadline_secs=900),
    )
    if successor_sessions is None or successor_sessions or continuous_work or task_seconds is not None:
        settings["succession"] = dict(total_secs=task_seconds)
        if successor_sessions is not None:
            settings["succession"]["max_sessions"] = successor_sessions
    if attachments:
        settings["evaluation"]["check"]["inputs"] = [
            dict(name=item['name'], source=item['source'], digest=item['sha256'])
            for item in attachments]
    prior = home / "pro_contract/settings.json"
    existing = json.loads(prior.read_text()) if prior.exists() else None
    if existing is not None:
        if existing.get("succession"):
            settings["succession"] = existing["succession"]
        else:
            settings.pop("succession", None)
    if strategy is not None:
        strategy = Path(strategy).expanduser().resolve(strict=True)
        if not strategy.is_dir():
            raise ValueError("strategy must be a context bundle directory")
        settings["policy"] = str(strategy)
    elif existing and existing.get("policy"):
        settings["policy"] = existing["policy"]
    # A resumed task keeps its original capability grant, including when CLI defaults change.
    if existing and existing.get("progress"):
        settings["progress"] = existing["progress"]
        if "succession" in existing:
            settings["succession"] = existing["succession"]
    elif continuous_work and existing is None:
        settings["progress"] = dict(executor_label=f"procontract.task={key}",
            assessment_secs=120)
    if review_compute:
        # Changing a verification capability does not create another task/home or reset
        # its existing succession grant. Computation grants are persisted by the runtime.
        settings["review_execution"] = dict(max_calls=8, timeout_secs=30, max_output_bytes=65536)
    atomic(home / "config.toml", toml(config))
    atomic(home / "environments.toml", env_text)
    atomic(home / "pro_contract/settings.json", json.dumps(settings, indent=2) + "\n")
    atomic(home / "procodex-session.json", json.dumps(identity, indent=2) + "\n")
    return home, config
