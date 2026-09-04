<p align="center"><strong>Codex CLI</strong> is a coding agent from OpenAI that runs locally on your computer.
<p align="center">
  <img src="https://github.com/openai/codex/blob/main/.github/codex-cli-splash.png" alt="Codex CLI splash" width="80%" />
</p>
</br>
If you want Codex in your code editor (VS Code, Cursor, Windsurf), <a href="https://developers.openai.com/codex/ide">install in your IDE.</a>
</br>If you want the desktop app experience, run <code>codex app</code> or visit <a href="https://chatgpt.com/codex?app-landing-page=true">the Codex App page</a>.
</br>If you are looking for the <em>cloud-based agent</em> from OpenAI, <strong>Codex Web</strong>, go to <a href="https://chatgpt.com/codex">chatgpt.com/codex</a>.</p>

---

## ProContract

This fork includes ProContract, an experimental settlement protocol for agent
work. It starts with a narrow question:

> What may the system recognize as finished when the executor is temporary,
> fallible, and unable to certify its own work?

A model process can stop, lose context, or be replaced while the obligation
that started the work still exists. ProContract therefore keeps execution and
settlement separate. The executor may edit files, run commands, report a
blocker, request revised terms, or hand off a candidate. None of those actions
settles the Contract. Recognized completion requires an authorized attestation
for an exact Contract revision, captured subject, and evidence coordinate.

The short form is:

```text
executors propose
evidence supports
authority settles
accepted defeat restores responsibility
```

### Philosophy

ProContract treats an agent invocation as a temporary executor, not as the
owner of a continuing duty. Messages and files can preserve useful memory, but
memory does not say which obligations remain, who may change them, or what
counts as completion. That standing lives in an institution outside the
executor.

It also separates history from current support. A hash fixes the identity of a
specification or captured subject; it does not make a claim true. Evidence
supports a claim only under its stated subject, policy, environment, evaluator,
and time. An authorized challenge can later withdraw that support without
deleting the earlier attestation or pretending the earlier work never
happened.

This gives failure a concrete consequence. If support for a discharged duty is
defeated, the duty becomes outstanding again. Duties that depended on it lose
their support as well, so the system cannot remain quiet while responsibility
has fallen through a dependency gap.

### How it works

Four parts enforce the boundary:

| Part | Responsibility |
| --- | --- |
| Principal | Issues terms, decides revisions, attests, challenges, resumes, or releases. In the app-server adapter, this is the host client and is not model-visible. |
| Executor | Works in a separate Codex thread with delegated tools, authority, deadlines, and shared turn/action budgets. It may hand off work but cannot settle itself. |
| Kernel and ledger | Apply deterministic state transitions, reject stale or unauthorized commands without changing state, and atomically persist the projection, event, sequence, and hash-chain head. |
| Subject and evidence envelope | Capture a bounded, content-addressed filesystem subject and run any frozen replay checks before the Principal evaluates the handoff. |

The main lifecycle is:

```text
issue -> dormant -> active -> verification -> discharged
                     |             |
                     |             +-> challenge -> dormant or escalated
                     +-> blocked, retry, revision petition, or escalation

issuer-authorized waiver -> released
```

Only `active` standing authorizes executor effects. `verification` means that
the executor handed off a candidate, not that the work is complete.
`discharged` means that the Principal attested the exact handoff. `released`
means that the issuer explicitly waived the duty. A scope is quiet only when
every duty is discharged or released at a named ledger frontier.

Three policies remain distinct:

- Execution policy tells the executor how to attempt the work. It is advisory
  and is not part of the Contract specification hash.
- Evidence policy freezes the finite checks required before settlement. Its
  identity is part of the Contract.
- Succession policy would decide what becomes a canonical incumbent. This is
  future work and is not another name for completion.

### Walkthrough

ProContract is currently available through the experimental app-server v2
API. Enable the under-development feature in `config.toml`:

```toml
[features]
pro_contract = true
```

Start `codex app-server`, initialize the connection with
`capabilities.experimentalApi: true`, send the `initialized` notification, and
create a Principal thread with `thread/start`. The examples below omit that
standard handshake and use placeholders from earlier responses.

1. Issue a Contract for the loaded Principal thread. The host fixes the goal,
   delegated authority, budget, settlement claim, replay policy, and retry
   policy. `executionPolicy` is stored separately from the normative terms.

```json
{
  "method": "proContract/issue",
  "id": 10,
  "params": {
    "threadId": "<principal-thread-id>",
    "spec": {
      "trigger": { "type": "immediate" },
      "goal": "Repair the parser and preserve its public behavior.",
      "brief": "Change the parser, add focused tests, and hand off the exact workspace.",
      "artifacts": ["src/parser.rs", "tests/parser.rs"],
      "requires": [],
      "authority": [
        "filesystem.read",
        "filesystem.write",
        "process.execute"
      ],
      "budget": {
        "turns": 12,
        "actions": 40,
        "deadlineAt": 4102444800
      },
      "evidence": {
        "claim": "The captured parser satisfies the focused test suite.",
        "replay": {
          "checks": [
            {
              "argv": ["cargo", "test", "--test", "parser"],
              "cwd": null,
              "timeoutMs": 120000,
              "exit": 0
            }
          ],
          "protected": [],
          "artifacts": ["src/parser.rs", "tests/parser.rs"]
        }
      },
      "resolution": {
        "maxAttempts": 2,
        "retryDelayMs": 1000
      }
    },
    "executionPolicy": "Reproduce the failure first, then make the smallest repair.",
    "originalRequest": "Fix the parser regression."
  }
}
```

The response contains the Contract ID, revision, `specHash`, executor thread,
execution counters, and a quiet certificate. An immediate Contract becomes
active and dispatches an executor. Time-triggered and dependency-bound
Contracts remain dormant until their activation conditions hold.

2. Wait for the executor to call `contract_report_ready`. ProContract captures
   the subject, runs the frozen replay checks when configured, and moves a
   successful handoff to `verification`. Read the authoritative state rather
   than inferring completion from the executor's final message:

```json
{
  "method": "proContract/read",
  "id": 11,
  "params": {
    "threadId": "<principal-thread-id>",
    "contractId": "<contract-id>"
  }
}
```

The handoff contains `subject.hash`, the artifact list, replay result, summary,
and declared uncertainties. A failed replay produces exact negative evidence
and does not settle the duty.

3. Materialize the immutable handoff into a new absolute path and evaluate it
   outside the executor's workspace:

```json
{
  "method": "proContract/handoff/materialize",
  "id": 12,
  "params": {
    "threadId": "<principal-thread-id>",
    "contractId": "<contract-id>",
    "destination": "/absolute/path/to/independent-review"
  }
}
```

4. If the independent evaluation supports the claim, attest the exact
   coordinates returned by `proContract/read`. The attestation evidence is
   independent from the executor's replay report.

```json
{
  "method": "proContract/attest",
  "id": 13,
  "params": {
    "threadId": "<principal-thread-id>",
    "contractId": "<contract-id>",
    "revision": 1,
    "specHash": "<spec-hash>",
    "subjectHash": "<subject-hash>",
    "evidenceHash": "<independent-evaluator-evidence-hash>"
  }
}
```

The accepted transition moves the Contract to `discharged`. If it was the last
outstanding duty in the scope, the returned quiet certificate has
`quiet: true` and names the ledger frontier at which that statement holds.

5. If later evidence defeats the attestation, challenge the exact revision and
   subject while naming the new defeater evidence:

```json
{
  "method": "proContract/challenge",
  "id": 14,
  "params": {
    "threadId": "<principal-thread-id>",
    "contractId": "<contract-id>",
    "revision": 1,
    "subjectHash": "<subject-hash>",
    "evidenceHash": "<defeater-evidence-hash>",
    "disclosure": "executor",
    "summary": "The target runtime exposes a parser case missing from the replay policy."
  }
}
```

An executor-visible challenge returns the duty to `dormant` so another bounded
attempt can address the residual. A sealed challenge moves it to `escalated`
without revealing the evidence summary. In both cases the ledger preserves the
old attestation as history while removing its current support. Live dependent
duties are escalated rather than left falsely discharged.

### Current boundary

ProContract is an under-development, local-only prototype. The reducer enforces
completion integrity under authenticated command, canonicalization, and
sole-transition assumptions. The current system does not claim adversarial
process confinement: a same-user process may still reach local credentials,
the SQLite ledger, or evidence storage outside the mediated tool paths.

Replay is a local preflight, not proof that a target environment will behave
the same way. Capture-policy identity and complete environment/evaluator
coordinates are not yet part of the v1 subject and evidence envelope. Canonical
succession, judge replacement, guaranteed capability improvement, and
recursive self-improvement are not claimed.

For the precise invariants, implementation map, evidence, and open limits, see:

- [ProContract theory](specs/pro-contract.md)
- [Codex implementation map](specs/pro-contract-implementation.md)
- [Evidence and experiments](specs/pro-contract-evidence.md)
- [Witnessed succession research](specs/pro-contract-succession.md)
- [Experimental app-server API](codex-rs/app-server/README.md)

## Quickstart

### Installing and running Codex CLI

Run the following on Mac or Linux to install Codex CLI:

```shell
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Run the following on Windows to install Codex CLI:

```shell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

The standalone installers download from `https://releases.openai.com/codex` by default and fall back to GitHub Releases if a metadata or asset download is unavailable. To force GitHub Releases, set `CODEX_INSTALLER_USE_RELEASES_OPENAI_COM` to `false` (`0` and `no` are also accepted):

```shell
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_INSTALLER_USE_RELEASES_OPENAI_COM=false sh
```

```powershell
$env:CODEX_INSTALLER_USE_RELEASES_OPENAI_COM='false'; irm https://chatgpt.com/codex/install.ps1 | iex
```

Codex CLI can also be installed via the following package managers:

```shell
# Install using npm
npm install -g @openai/codex
```

```shell
# Install using Homebrew
brew install --cask codex
```

Then simply run `codex` to get started.

<details>
<summary>You can also go to the <a href="https://github.com/openai/codex/releases/latest">latest GitHub Release</a> and download the appropriate binary for your platform.</summary>

Each GitHub Release contains many executables, but in practice, you likely want one of these:

- macOS
  - Apple Silicon/arm64: `codex-aarch64-apple-darwin.tar.gz`
  - x86_64 (older Mac hardware): `codex-x86_64-apple-darwin.tar.gz`
- Linux
  - x86_64: `codex-x86_64-unknown-linux-musl.tar.gz`
  - arm64: `codex-aarch64-unknown-linux-musl.tar.gz`

Each archive contains a single entry with the platform baked into the name (e.g., `codex-x86_64-unknown-linux-musl`), so you likely want to rename it to `codex` after extracting it.

</details>

### Using Codex with your ChatGPT plan

Run `codex` and select **Sign in with ChatGPT**. We recommend signing into your ChatGPT account to use Codex as part of your Plus, Pro, Business, Edu, or Enterprise plan. [Learn more about what's included in your ChatGPT plan](https://help.openai.com/en/articles/11369540-codex-in-chatgpt).

You can also use Codex with an API key, but this requires [additional setup](https://developers.openai.com/codex/auth#sign-in-with-an-api-key).

## Docs

- [**Codex Documentation**](https://developers.openai.com/codex)
- [**Contributing**](./docs/contributing.md)
- [**Installing & building**](./docs/install.md)
- [**Open source fund**](./docs/open-source-fund.md)

This repository is licensed under the [Apache-2.0 License](LICENSE).
