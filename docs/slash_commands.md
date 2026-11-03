# Slash commands

For an overview of Codex CLI slash commands, see [this documentation](https://developers.openai.com/codex/cli/slash-commands).

## Local ProContract research control

This ProContract build exposes `/rsi` when its local owner-control endpoint is
configured. Prepare a protected research profile with `procodex rsi prepare
--config PROFILE.json`, then launch `procodex --rsi-config PROFILE.json`. Provisioning
retains evidence and capabilities without starting model inference.

| Command | Effect |
| --- | --- |
| `/rsi <goal>` or `/rsi start <goal>` | Admit the initial research request under the configured scope |
| `/rsi` or `/rsi status` | Inspect retained execution state without starting work |
| `/rsi input <feedback>` | Deliver new owner input to the continuing responsibility |
| `/rsi resume` | Resume from retained work and choices, keeping original grants |
| `/rsi cancel` or `/rsi stop` | Cancel execution and retain completed work |

The command is a thin local socket client. Research goals, evidence, selected work
and outcomes belong to the durable runtime, independently of the TUI's lifetime.
The supplied research strategy chooses work, checks, experiments and waiting; the
command does not prescribe a phase sequence. A timeout waiting for an acknowledgement
does not replay the request: `/rsi status` exposes the retained state.

`procodex rsi --help` controls the same endpoint from a shell. The old fixed-workflow
research CLI remains available explicitly as `procodex rsi-legacy`. The new entry
does not modify or resume frozen benchmark attempts. Standing research can have no
hard deadline, while explicit action/user/environment limits retain their meaning.
