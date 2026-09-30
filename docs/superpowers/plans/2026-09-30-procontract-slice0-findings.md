# ProContract Slice 0 — Findings (2026-09-30)

Plan: `docs/superpowers/plans/2026-09-30-procontract-slice0-spikes.md`. Base: upstream `ab84d71f5`. Instance:
`wfxr__csview.8ac4de0`. Probe artifacts live outside the repository under `/tmp/pc-slice0/` and
`~/run-artifacts/procontract-essential-20260930/`.

## Task 1 — Instance image and task prompt: PASS

- Images: `task_cleanroom` `sha256:a746c72c74adb5295b2b5909841ad4b81e9f912955d1a86e91ceecd3121caa82`,
  `task` `sha256:3ac3f94e3f4a824567ff36cf3abb17e50242f5e840d5edcf4c587089d93b2858`.
- Cleanroom: Ubuntu 22.04.5, **glibc 2.35**, Rust **1.92.0** (`/usr/local/cargo`), no gcc, **no cargo registry**. The
  workspace `/workspace` holds `.git` (one "Initial commit"), a 407-byte `README.md` with no usage content, licenses, and
  the reference `executable` (`csview 1.3.4`), mode `0111` owned by root: runnable but unreadable by the `agent` user
  (uid 1000). The container's default user is root, which *can* read it, so the executor must run as `--user 1000:1000`.
- Offline builds: a std-only crate builds and tests with `cargo --offline`; any external crate fails. Rust tasks are
  therefore std-only, which suits the Cargo check adapter.
- Official prompt: none ships in the image or in the ProgramBench repository (it is an evaluation harness). R2's goal
  text adds R2-specific instructions (`validate.sh`, batched probes). **Ruling:** use one neutral prompt for both arms,
  stored at `~/run-artifacts/procontract-essential-20260930/task-prompt.txt`, SHA-256
  `502f07f8d94119f95ed426d54b423ee90452350c4f7972f9a407dbd34f5588ee`.
- Evaluation contract (`src/programbench/eval/eval.py`): the submission is extracted into the workspace,
  `./compile.sh` must produce `./executable`, which the evaluator moves aside and tests. **Packaging must exclude the
  reference `executable`**; otherwise a no-op `compile.sh` would submit the reference itself.

## Task 2 — A Codex binary inside the cleanroom: PASS (musl)

- A host `--release` build (737 s) fails in the container: `GLIBC_2.38' not found`.
- A static `x86_64-unknown-linux-musl` build of `codex` and `codex-code-mode-host` succeeds by reusing R2's prepared
  toolchain (`~/run-artifacts/codex-r2-migration-20260928/environment/musl-preparation`: zig cc, musl OpenSSL, libcap,
  rusty_v8 150.4.0 musl archive — the same `v8` crate version as this base). Script:
  `~/run-artifacts/procontract-essential-20260930/musl/build-codex-musl.sh`. First build 753 s, incremental 42 s.
  `codex` `1752310e…c360b`, `codex-code-mode-host` `c391d25c…44bf8`.
- The host gnu build of `codex-code-mode-host` fails: no gnu `ptrcomp_sandbox` rusty_v8 prebuilt exists for 150.4.0
  (HTTP 404). **Ruling:** use the musl binaries on the host too, so host and container run identical bytes.

## Task 3 — exec-server over the `program` transport: PASS

- `CODEX_HOME/environments.toml` with `default = "cleanroom"`, `include_local = false`, and an environment whose
  `program = "docker"`, `args = ["run", "-i", "--rm", "--network", "none", "--user", "1000:1000", "-v",
  "<ws>:/workspace", "-v", "<musl codex>:/opt/codex:ro", "-w", "/workspace", "<task_cleanroom image>", "/opt/codex",
  "exec-server", "--listen", "stdio"]`.
- `--exit-on-stdin-close` is only valid with `--remote`/`--environment-id`; with it the server exits at startup
  (`transport closed`).
- Inside the container Codex's own sandbox cannot run (no bwrap). With `sandbox_mode = "workspace-write"` every command
  fails; with `sandbox_mode = "danger-full-access"` commands run as `agent` with `--network none`. Verified in one real
  turn with `gpt-5.6-luna`: `uname` shows the container, `touch /workspace/probe` lands in the host bind mount, host
  paths (`/tmp/pc-slice0`, `/home/duozhou`) are invisible, DNS fails. `CODEX_HOME` and the credential never enter the
  container.
- **Consequence for the spec:** under the evaluation profile the thread's sandbox mode is `danger-full-access` *inside
  the container*; custody (§13.2) must be decided by the environment — the thread uses only the configured isolated
  container environment and `include_local = false` — not by sandbox mode.

## Task 4 — Model reachability: PASS

`gpt-5.6-luna` at `max` answered in 3 s through the `openai-custom` provider (credential from the host environment).

## Task 5 — Turn-end boundary: PASS, with one caveat

- At `ab84d71f5`, `core/src/tasks/mod.rs` runs `emit_turn_stop_lifecycle` (line 843) before emitting `TurnComplete`
  (845) and before `emit_thread_idle_lifecycle_if_idle` (878). Freezing the artifact in `on_turn_stop` is sound.
- `TurnStopInput` carries only the session, thread and turn stores: the extension must record the workspace root and
  turn id in the turn store at turn start.
- Caveat: unified-exec background terminals can outlive a turn (`list_background_terminals`). The capture's
  verification pass (§5.2) is what detects background writers; the runner's prompt does not rely on background jobs.

## Task 6 — Official evaluation pipeline: PASS

- Test blobs synced for the instance (contents not opened). A deliberately null submission (an `executable` that exits
  1 with no output) was evaluated in 288 s and scored **67**, with one branch reporting `results_read_failed`.
- The same null submission scores **66–67** on four other easy Rust instances (`code-minimap`, `datasurgeon`,
  `elfcat`, `clog-cli`): result records are ~3× the test count with a ~2:1 pass:fail ratio, a property of the scoring
  rather than of csview. Arms must be compared above this floor, and only ✅ means solved (runbook §11).

## Deferred spikes (evaluation profile does not need them)

- Owner identity: under the evaluation profile the owner is the operator who launched the runner.
- Admission boundary (human-input observation, input sequence, conditional continuation, linearization against goal
  and permission writers): the evaluation runner sends one message and no concurrent human input exists, so the
  existing `continue_turn_if_idle` fence suffices for this profile. **Ruling:** these spikes move to the explicit core
  loop slice (spec §12 slice 3) — cost if wrong: a race the benchmark cannot exhibit.
- Reachable-capability gating: the evaluation `CODEX_HOME` configures no hooks, notify, MCP servers or dynamic tools;
  the extension verifies this at intake and abstains otherwise.

## Verdict

The benchmark vertical slice is feasible on this host without weakening any security policy: host institution with the
musl `codex`, executor in a network-less cleanroom container as uid 1000 via the exec-server `program` transport,
std-only Cargo checks in fresh containers, `gpt-5.6-luna` at `max`, and official evaluation of a packaged submission
that excludes the reference binary. One spec clarification is needed (Task 3 consequence) and is folded into the
benchmark slice plan.
