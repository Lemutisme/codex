"""Host-owned local configuration and isolation boundaries; never starts inference."""

import hashlib
import json
import os
from pathlib import Path
import tomllib


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
    package, workspace, root, source_home, image, check, *, isolation="nested"
):
    """Copy routing only; never carry hooks, MCP, global permissions or project trust over."""
    if isolation not in ("nested", "container-only"):
        raise ValueError("unknown execution isolation")
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
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    home = root / "workspaces" / key
    if any(path.is_symlink() for path in (home, *home.parents)):
        raise ValueError("redirected ProCodex workspace state")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    docker_args = [
        "run",
        "-i",
        "--rm",
        "--network",
        "none",
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
        "-w",
        "/workspace",
        image,
        "/bin/bash",
        "-c",
        'mkdir -p "$HOME" && exec /opt/procodex/bin/codex exec-server --listen stdio',
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
    atomic(home / "config.toml", toml(config))
    atomic(home / "environments.toml", env_text)
    atomic(home / "pro_contract/settings.json", json.dumps(settings, indent=2) + "\n")
    atomic(home / "procodex-session.json", json.dumps(identity, indent=2) + "\n")
    return home, config
