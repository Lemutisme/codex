# ProCodex local preview

A separately installed Codex fork with native ProContract, host-owned evidence
references, bounded on-demand reviewer reads, and the separately budgeted RSI CLI.
It does not replace `codex`, change its config, or automatically start a benchmark.

## Start

```sh
cd /path/to/a/project
procodex
```

State is under `~/.procodex/workspaces/`, isolated by workspace, image, check and
execution-isolation choice. The current user's provider routing is inherited
from `CODEX_HOME/config.toml` (normally `~/.codex/config.toml`), not their hooks,
MCP servers, permissions or project trust. Default model is gpt-5.6-luna/max;
normal Codex model arguments remain available. Credentials stay on the host.

The executor runs in an offline Docker container. Only the selected project is
mounted writable; the installed package is read-only, capabilities are dropped,
no Docker socket or host credentials are mounted. Images are resolved locally
by content ID; startup does not pull images or install dependencies.

Default Codex policy remains workspace-write/on-request. Some hosts, including
the tested Ubuntu AppArmor configuration, cannot create the nested user namespace.
In that case startup stops before inference or asks for explicit confirmation.
To knowingly use Docker as the execution sandbox instead:

```sh
procodex --container-only
```

This mode sets Codex's internal filesystem mode to full access **inside the
container**, not on the host. Docker's project-only writable mount, no-network,
capability restrictions and on-request approvals remain. It does not change the
host's AppArmor/sysctl configuration. No silent fallback is performed.

Add an explicit check against each frozen candidate:

```sh
procodex --container-only --check 'python3 -m unittest discover'
```

Without `--check`, verification is review-only, not a test-pass guarantee. The
preview issues a contract for the first substantive request in a session; use
`/new` for a different task. Large workspaces or excluded dependencies may exceed
capture/check capabilities; an abstention/unknown is not success.

```sh
procodex --version
procodex doctor
procodex --container-only status       # use the same --check if one was selected
procodex rsi --help
```

The full RSI controller remains an explicit, separately sealed research workflow.
Interactive sessions do **not** automatically mutate/promote policies or launch
background research. A local contract's support is evidence within reach, not
independent benchmark gain or a claim that general-purpose RSI is complete.

## Repairs included

- Draft requirements select host-owned human-request IDs. Workspace documentation
  does not silently acquire the authority of a user requirement.
- Reviewers have a frozen, ID-only read capability, no execution environment, and
  no general filesystem access. Required artifacts are indexed first. They read
  the complete request/terms; support references are resolved by the host.
- Worker context uses existing Core contextual fragments, at most 7,000 payload
  bytes per item and 96,000 bytes per packet. History is not rewritten.
- The fixed research auditor supports host-issued citation handles. Unknown
  judgments, inventory coverage and adoption rules are not weakened.
- H schema 3 separates an active executor from a resting failed contract lane:
  checkpoint may run in that case, but convergence/check/review protection remains.
  Schemas 1 and 2 retain their existing behavior.

Scientific outcome policy, compile-failure scoring and stop-on-unknown study
rules are unchanged. No closed study is restarted or rescored. Failure-only
research and cost-aware promotion need a separately specified future protocol.
This is a rebuilt pinned fork, not a claim that it tracks latest upstream.

## Rebuild/install

Use `just assemble-codex-package` with an explicit target and source revision.
Build `pro-contract-store` from the same tree and put it in `bin/`. After a clean
commit, record `build-source.json` with source_commit and SHA-256 for the three
binaries. Then:

```sh
python scripts/install_procodex.py --package /path/to/package --image sha256:IMAGE_ID
```

Installations are versioned under `~/.local/share/procodex/releases/`; `current`
selects one release. The original Codex executable and state remain untouched.
