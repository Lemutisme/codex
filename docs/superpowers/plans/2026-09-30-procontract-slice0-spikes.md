# ProContract Slice 0 (Feasibility Spikes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the risks that could force a design change before the benchmark vertical slice is planned in detail, and
record each finding.

**Architecture:** Spikes are throwaway probes (spec §12 slice 0, §13.5). Each spike answers one question with a command
or a scratch program and a pass/fail criterion; code written here is not kept in the product tree. Findings are appended
to `docs/superpowers/plans/2026-09-30-procontract-slice0-findings.md` and may send parts of the spec back for revision.

**Tech Stack:** Codex (Rust 1.95, `just`), Docker 29, ProgramBench (`uv run programbench`), `gpt-5.6-luna` via the
configured `openai-custom` provider.

**Spec:** `docs/superpowers/specs/2026-09-29-procontract-essential-design.md` (§3.3, §5, §6.2, §11, §12 slice 0, §13).

## Global Constraints

- Work only in `/home/duozhou/codex-worktrees/procontract-essential-impl` (branch `procontract-essential-impl`, base
  upstream `ab84d71f5`). Throwaway probe code lives under `/tmp/pc-slice0/` and is never committed.
- Never weaken host or Docker security policy: no `--privileged`, no `SYS_ADMIN`, no `seccomp=unconfined`, no
  `apparmor=unconfined` (spec §13.2; the R2 constraint).
- Inference containers run with `--network none`; the model credential never enters a container.
- Do not read `tests/test*` blobs of the instance before packaging (runbook §11 cleanroom rule).
- Use `just` for Rust builds and tests, never `cargo test` directly (`AGENTS.md`).

## Review Focus

- A cleanroom image whose glibc is older than the host's: a host-built `codex` binary fails inside the container → the
  spike must prove a static (musl) binary runs there.
- A Rust task whose dependencies are not vendored in the image: `cargo build --offline` fails → the check adapter's
  "missing is `cannot_judge`" rule would make every check `cannot_judge`.
- The exec-server `program` transport expecting a stdio mode flag the CLI does not expose → the environment config
  would need a wrapper.
- `on_turn_stop` running after file writes from background processes started by the turn → the frozen artifact could
  still race; the spike records whether background terminals outlive `on_turn_stop`.
- A task prompt that differs between ON and OFF arms → the comparison is invalid; the prompt must be byte-identical.

---

### Task 1: Instance image and task prompt

**Files:**
- Create: `docs/superpowers/plans/2026-09-30-procontract-slice0-findings.md` (findings log, committed)

- [ ] **Step 1: Pull the cleanroom and eval images**

Run:
```bash
docker pull programbench/wfxr_1776_csview.8ac4de0:task_cleanroom
docker pull programbench/wfxr_1776_csview.8ac4de0:task
```
Expected: both pulls complete; record their image digests (`docker image inspect --format '{{.Id}}'`).

- [ ] **Step 2: Inspect the cleanroom layout without running tests**

Run:
```bash
docker run --rm --network none programbench/wfxr_1776_csview.8ac4de0:task_cleanroom \
  sh -c 'pwd; ls -la /workspace; ls /workspace | head -50; cat /etc/os-release | head -3; ldd --version 2>&1 | head -1; command -v cargo rustc; cargo --version; rustc --version; ls ~/.cargo/registry 2>/dev/null | head'
```
Expected: record the workspace entries (reference binary, docs), OS, glibc version, Rust toolchain, and whether a cargo
registry cache exists. Do not open any `tests/` directory.

- [ ] **Step 3: Find the canonical task prompt**

Look for the task statement shipped with the instance (for example a `TASK.md`, `README`, or docs under `/workspace`)
and for the official agent prompt used by ProgramBench's reference harnesses. Record the exact prompt text that both arms
will send, and its SHA-256. If no official prompt exists, derive a minimal neutral prompt from the first paragraph of the
R2 goal (without R2's `validate.sh` and probing instructions) and record that choice explicitly.

- [ ] **Step 4: Probe offline Rust builds in the image**

Run:
```bash
docker run --rm --network none programbench/wfxr_1776_csview.8ac4de0:task_cleanroom sh -c '
  cd /tmp && cargo new --quiet probe && cd probe &&
  printf "[dependencies]\ncsv = \"1\"\n" >> Cargo.toml &&
  (cargo build --offline 2>&1 | tail -3); echo exit=$?'
```
Expected: record whether a common dependency resolves offline. A failure means the image provides no registry
cache; record which crates, if any, are available.

- [ ] **Step 5: Commit findings**

```bash
git add docs/superpowers/plans/2026-09-30-procontract-slice0-findings.md
git commit -m "docs: record slice-0 image and prompt findings"
```

### Task 2: A Codex binary that runs inside the cleanroom container

**Files:**
- Findings log only.

- [ ] **Step 1: Build the host `codex` binary**

Run (in `codex-rs/`): `just codex --version` is not a build command; build with
```bash
cargo build -p codex-cli --bin codex --release
```
Expected: `target/release/codex` exists; record build time.

- [ ] **Step 2: Try the host binary inside the container**

Run:
```bash
docker run --rm --network none -v "$PWD/target/release/codex:/opt/codex:ro" \
  programbench/wfxr_1776_csview.8ac4de0:task_cleanroom /opt/codex --version
```
Expected: prints a version, or fails with a glibc error. On failure, continue to Step 3.

- [ ] **Step 3: Build a static musl binary if needed**

Run:
```bash
cargo +stable build -p codex-cli --bin codex --release --target x86_64-unknown-linux-musl
```
Expected: record whether it builds (the `stable` toolchain has the musl std), and whether it runs in the container. If
neither binary runs, record the blocker; the environment would then need a binary built inside the image.

### Task 3: exec-server over the `program` transport into the container

**Files:**
- Scratch: `/tmp/pc-slice0/codex-home/config.toml`

- [ ] **Step 1: Find the stdio mode of `codex exec-server`**

Read `codex-rs/exec-server/src/` (the stdio server entry used by `StdioCommand`) and `codex-rs/cli/src/main.rs` to learn
the exact arguments that make `codex exec-server` speak its protocol over stdin/stdout. Record them.

- [ ] **Step 2: Configure a container environment**

Create `/tmp/pc-slice0/codex-home/config.toml` from `~/.codex/config.toml` (provider and credentials unchanged) and add:
```toml
[[environments]]
id = "cleanroom"
program = "docker"
args = ["run", "-i", "--rm", "--network", "none",
        "-v", "/tmp/pc-slice0/ws:/workspace",
        "-v", "/path/to/codex:/opt/codex:ro",
        "programbench/wfxr_1776_csview.8ac4de0:task_cleanroom",
        "/opt/codex", "exec-server", "<stdio args from Step 1>"]
```
(Use the environment-selection keys that `exec-server/src/environment_toml.rs` actually defines; adjust names to the
source.)

- [ ] **Step 3: Run one turn in that environment**

Run `codex exec` with `CODEX_HOME=/tmp/pc-slice0/codex-home` against the `cleanroom` environment and the prompt "Run
`uname -a; ls /workspace; touch /workspace/probe` and report." Expected: the command runs inside the container
(`uname` shows the container), `/tmp/pc-slice0/ws/probe` appears on the host, and nothing under `CODEX_HOME` is visible
from inside the container (`ls /tmp/pc-slice0/codex-home` from the container fails).

### Task 4: Model reachability

- [ ] **Step 1: One cheap call with the evaluation model**

Run:
```bash
codex exec -m gpt-5.6-luna -c model_reasoning_effort='"max"' -s read-only --skip-git-repo-check "Reply with the word ready."
```
Expected: prints `ready`; record latency. Failure blocks the benchmark slice.

### Task 5: Turn-end boundary for artifact freezing

**Files:**
- Findings log only.

- [ ] **Step 1: Confirm ordering in the current base**

Read `codex-rs/core/src/tasks/mod.rs` around `emit_turn_stop_lifecycle`, `TurnComplete` and
`emit_thread_idle_lifecycle_if_idle`, and `codex-rs/ext/extension-api/src/contributors/turn_lifecycle.rs`. Record: does
`on_turn_stop` run before `TurnComplete` is emitted and before the active turn is cleared, and what the contributor can
access there (turn store, cwd/environment).

- [ ] **Step 2: Background processes**

Record whether a unified-exec background process started by the turn can still be running at `on_turn_stop`
(`core/src/tasks/mod.rs` comments on background terminals). This decides whether capture must also wait for, or
exclude, background writers.

### Task 6: Official evaluation pipeline

- [ ] **Step 1: Smoke-test ProgramBench eval with the local fixture**

Run the runbook §4 fixture self-check (`uv run programbench eval` on the `testorg__calculator.abc1234` fixture) and
record that the pipeline works end to end on this host.

- [ ] **Step 2: Sync the instance's test blobs without reading them**

Run: `uv run programbench blob sync wfxr__csview.8ac4de0`. Expected: completes; do not open the blob contents.

### Task 7: Findings review and plan gate

- [ ] **Step 1: Summarize**

Append a verdict to the findings log: for each spike, pass/fail and the consequence for the benchmark vertical slice
plan; list any spec sections that must change.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-09-30-procontract-slice0-findings.md
git commit -m "docs: record slice-0 feasibility findings"
```
