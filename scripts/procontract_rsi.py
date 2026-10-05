#!/usr/bin/env python3
"""ProContract succession: the institution's side of recursive self-improvement.

A version is a policy bundle (executor.md, research.md, drafter.md, prober.md, reviewer.md) run by
one codex binary. Improving the method is an ordinary task whose product may succeed the version
that does the work (reach spec §5). This host stays outside every version's write authority: it
runs from its own checkout, holds the campaign ledger, chooses research parents, runs and measures
versions, and keeps every claim in the kernel through the store CLI.

  init     start a campaign: pools, budgets, gates; register v0 and adopt it as the first incumbent
  step     one research step: parent → research run → delivery → qualification → development
           evaluation → (when it earns it) paired confirmation against the incumbent
  adopt    the human adopts a confirmed candidate (an explicit settlement)
  status   derived views: incumbent, versions, budgets

Reach in practice:
- exploration (choosing a parent, putting a candidate forward) may use any information and needs no
  authority;
- adoption needs comparative support from beyond the candidate's reach: confirmation tasks that no
  research view and no earlier selection has read, run fresh for candidate and incumbent;
- a source read by a selection never certifies it again (exposure only accumulates).

Every phase is resumable: runs are cached by directory, kernel commands are idempotent by key."""

import argparse
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_store as store

SCRIPTS = Path(__file__).resolve().parent
RUNNER = [sys.executable, str(SCRIPTS / "procontract_benchmark_runner.py")]
V0_BUNDLE = SCRIPTS.parent / "codex-rs" / "ext" / "pro-contract" / "policies"
BUNDLE_FILES = ["executor.md", "research.md", "drafter.md", "prober.md", "reviewer.md"]
MAX_BUNDLE_FILE = 32 << 10
EXPERIMENT_SECTIONS = [
    "Deficiency",
    "Hypothesis",
    "Change",
    "Prediction",
    "Falsifier",
    "Risks",
]
OWNER = "principal"

RESEARCH_PROTOCOL = """This is a research task: improve how an agent works.

Your workspace holds:
- policy/: the policy bundle of version {parent}. You may edit only these files: {files}. Each must
  stay under 32 KiB. The bundle as you leave it is your candidate.
- archive/: evidence from earlier runs and research steps. Read it; do not change it.

Deliver ./EXPERIMENT.md with the sections {sections}. No network is available.
"""


def now_key(*parts) -> str:
    return ":".join(str(part) for part in parts)


class Host:
    """One campaign directory: its terms, ledger, versions and runs."""

    def __init__(self, camp: Path, adapter=None, runner: list[str] | None = None):
        self.camp = camp
        self.store = camp / "store"
        self.terms = json.loads((camp / "campaign.json").read_text())
        self.adapter = adapter or ProgramBench(self.terms)
        self.runner = runner or RUNNER

    # ---- ledger -------------------------------------------------------------------------------

    def identities(self, epoch: str | None = None) -> dict:
        return store.identities(
            harness=self.terms["codex_sha256"],
            model=self.terms["model"],
            effort=self.terms["effort"],
            evaluator_epoch=epoch,
        )

    def record(self, kind: str, body: dict, epoch: str | None = None) -> None:
        store.append(self.store, kind, self.identities(epoch), body)

    def events(self, kind: str | None = None) -> list[dict]:
        records = [record["event"] for record in store.events(self.store)]
        return [event for event in records if kind is None or event["kind"] == kind]

    def contract(self, contract_id: str) -> dict | None:
        return store.contract(self.store, contract_id)

    def apply(
        self, contract_id: str, role: str, provenance: str, command: dict, key: str
    ) -> dict:
        state = self.contract(contract_id)
        return store.apply(
            self.store,
            key,
            {
                "contract_id": contract_id,
                "expected_version": state["version"] if state else 0,
                "role": role,
                "provenance": provenance,
                "command": command,
            },
        )

    def issue(
        self, contract_id: str, terms: dict, evidence_policy: dict, provenance: str
    ) -> dict:
        if (state := self.contract(contract_id)) is not None:
            return state
        bindings = {
            "terms_hash": store.digest("terms", terms),
            "capture_policy_hash": store.digest(
                "capture_policy", {"subject": "content-addressed"}
            ),
            "evidence_policy_hash": store.digest("evidence_policy", evidence_policy),
        }
        state = self.apply(
            contract_id,
            "issuer",
            provenance,
            {"type": "issue", "owner": OWNER, "bindings": bindings},
            now_key("issue", contract_id),
        )
        self.record(
            "issue",
            {
                "contract_id": contract_id,
                "terms": terms,
                "evidence_policy": evidence_policy,
            },
        )
        return state

    def propose(self, contract_id: str, subject: str) -> dict:
        state = self.contract(contract_id)
        if state["candidate"] and state["candidate"]["subject_hash"] == subject:
            return state
        return self.apply(
            contract_id,
            "executor",
            "automation",
            {"type": "propose", "subject_hash": subject},
            now_key("propose", contract_id, subject),
        )

    def support(self, contract_id: str, evidence: dict, basis, reach: str) -> dict:
        """Supports the current candidate on `evidence`, whose sources are `basis`."""
        state = self.contract(contract_id)
        if state["support"]:
            return state
        candidate = state["candidate"]
        coordinate = {
            "contract_id": contract_id,
            "revision": state["revision"],
            "terms_hash": state["bindings"]["terms_hash"],
            "generation": candidate["generation"],
            "subject_hash": candidate["subject_hash"],
            "capture_policy_hash": state["bindings"]["capture_policy_hash"],
            "evidence_policy_hash": state["bindings"]["evidence_policy_hash"],
            "environment_digest": store.digest(
                "environment", self.adapter.environment()
            ),
            "evaluator_digest": store.digest("evaluator", self.adapter.evaluator()),
            "evidence_hash": store.digest("evidence", evidence),
            "basis": store.digest("basis", basis),
            "reach": reach,
        }
        return self.apply(
            contract_id,
            "verifier",
            "automation",
            {
                "type": "support",
                "certificate": store.digest("certificate", [coordinate, evidence]),
                "coordinate": coordinate,
            },
            now_key("support", contract_id, candidate["generation"]),
        )

    def discharge(self, contract_id: str, decision: dict, attestation: str) -> dict:
        state = self.contract(contract_id)
        if state["standing"] == "discharged":
            return state
        return self.apply(
            contract_id,
            "settler",
            "human" if decision["type"] == "explicit" else "delegate",
            {
                "type": "discharge",
                "attestation": store.digest("attestation", attestation),
                "coordinate": state["support"]["coordinate"],
                "decision": decision,
            },
            now_key("discharge", contract_id),
        )

    def release(self, contract_id: str, reason: str) -> dict:
        state = self.contract(contract_id)
        if state["standing"] != "outstanding":
            return state
        if state["candidate"] and not state["support"]:
            # A candidate that failed its evidence is defeated first, so the record says why.
            state = self.apply(
                contract_id,
                "verifier",
                "automation",
                {
                    "type": "defeat",
                    "target": {"type": "candidate", **state["candidate"]},
                    "defeater": store.digest("defeater", reason),
                },
                now_key("defeat", contract_id),
            )
        return self.apply(
            contract_id,
            "settler",
            "delegate",
            {"type": "release", "attestation": store.digest("attestation", reason)},
            now_key("release", contract_id),
        )

    def presumed(self) -> dict:
        """The campaign's pre-authorized convention, under which the host settles mechanical
        qualifications and, when the campaign says so, adoptions."""
        return {
            "type": "presumed",
            "convention": store.digest("convention", self.terms),
            "classifier": store.digest("classifier", "procontract_rsi.py"),
        }

    # ---- versions -----------------------------------------------------------------------------

    def version_dir(self, vid: str) -> Path:
        return self.camp / "versions" / vid

    def register(
        self, bundle: Path, parent: str | None, proposed_by: str, experiment: str
    ) -> str:
        files = {
            name: (bundle / name).read_text() if (bundle / name).exists() else ""
            for name in BUNDLE_FILES
        }
        manifest = {
            "schema": 1,
            "binary": self.terms["codex_sha256"],
            "model": {"id": self.terms["model"], "effort": self.terms["effort"]},
            "bundle": {
                name: store.digest("bundle_file", text) for name, text in files.items()
            },
            "lineage": {"parent": parent, "proposed_by": proposed_by},
        }
        vid = store.digest("version", manifest)
        target = self.version_dir(vid)
        if not target.exists():
            (target / "bundle").mkdir(parents=True)
            for name, text in files.items():
                (target / "bundle" / name).write_text(text)
            (target / "EXPERIMENT.md").write_text(experiment)
            (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            self.record("version", {"id": vid, "manifest": manifest})
        return vid

    def versions(self) -> dict[str, dict]:
        return {
            event["body"]["id"]: event["body"]["manifest"]
            for event in self.events("version")
        }

    def incumbent(self) -> str:
        """The most recently recorded incumbent whose adoption is still settled."""
        for event in reversed(self.events("selection")):
            body = event["body"]
            if body["role"] == "incumbent":
                state = self.contract(body["adoption"])
                if state and state["standing"] == "discharged":
                    return body["version"]
        raise RuntimeError("the campaign has no incumbent")

    # ---- runs ---------------------------------------------------------------------------------

    def measure(self, vid: str, task: str, purpose: str) -> dict:
        """Runs a version on one task and labels the result; cached by run directory."""
        run_dir = self.camp / "runs" / f"{purpose}-{vid[:12]}-{task}"
        result_file = run_dir / "result.json"
        if result_file.exists():
            return json.loads(result_file.read_text())
        result = None
        for attempt in (1, 2):
            attempt_dir = run_dir / f"attempt-{attempt}"
            shutil.rmtree(attempt_dir, ignore_errors=True)
            result = self.adapter.run_and_label(
                self, self.version_dir(vid) / "bundle", task, attempt_dir
            )
            if result["validity"] == "valid":
                break
        result = {
            "version": vid,
            "task": task,
            "purpose": purpose,
            "run_dir": str(attempt_dir),
            **result,
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        result_file.write_text(json.dumps(result, indent=2) + "\n")
        self.record("execution", {k: v for k, v in result.items() if k != "label"})
        if result.get("label"):
            self.record(
                "label", result["label"], epoch=result["label"]["evaluator_epoch"]
            )
        return result

    def measure_all(
        self, pairs: list[tuple[str, str]], purpose: str
    ) -> dict[tuple[str, str], dict]:
        with ThreadPoolExecutor(self.terms["parallel"]) as pool:
            results = list(pool.map(lambda pair: self.measure(*pair, purpose), pairs))
        return dict(zip(pairs, results))

    def dev(self, vid: str) -> dict[str, float]:
        """Pass rate per development task (valid runs only), measuring what is missing."""
        self.measure_all([(vid, task) for task in self.terms["pools"]["dev"]], "dev")
        return self.dev_results(vid)

    def dev_results(self, vid: str) -> dict[str, float]:
        """Development pass rates already measured; never starts a run."""
        results = {}
        for path in sorted((self.camp / "runs").glob(f"dev-{vid[:12]}-*/result.json")):
            result = json.loads(path.read_text())
            if result["validity"] == "valid":
                results[result["task"]] = result["pass_rate"]
        return results

    # ---- research -----------------------------------------------------------------------------

    def choose_parent(self) -> tuple[str, str]:
        """Exploration, without authority: follow the newest qualified version unless it clearly
        regressed on development tasks against its own parent; otherwise the best by development
        mean. The incumbent always qualifies."""
        incumbent = self.incumbent()
        qualified = [incumbent] + [
            body["version"]
            for body in (event["body"] for event in self.events("selection"))
            if body["role"] == "qualified" and body["version"] != incumbent
        ]
        tolerance = self.terms["gates"]["parent_regression_tolerance"]
        newest = qualified[-1]
        parent = self.versions()[newest]["lineage"]["parent"]
        if (
            parent is None
            or paired_delta(self.dev(newest), self.dev(parent)) >= -tolerance
        ):
            return newest, "newest_qualified"
        means = {vid: mean(self.dev(vid).values()) for vid in qualified}
        return max(means, key=means.get), "best_dev_mean"

    def stage_research(self, parent: str, step: int) -> Path:
        """The research view: the parent's bundle (editable) and the archive (development evidence
        and research history). Confirmation tasks never enter it."""
        root = self.camp / "research" / f"step-{step}"
        workspace = root / "workspace"
        if workspace.exists():
            return root
        shutil.copytree(self.version_dir(parent) / "bundle", workspace / "policy")
        archive = workspace / "archive"
        archive.mkdir(parents=True)
        sources = []
        incumbent = self.incumbent()
        lines = [
            "# Archive",
            "",
            f"Incumbent version: {incumbent}. Research parent: {parent}.",
            "Pass rates come from hidden tests the agent never sees (beyond its reach); 1.0 is perfect.",
            "",
            "| version | parent | development mean | tasks |",
            "|---|---|---|---|",
        ]
        for vid, manifest in self.versions().items():
            results = self.dev_results(vid)
            lines.append(
                f"| {vid[:12]} | {(manifest['lineage']['parent'] or '-')[:12]} | "
                f"{mean(results.values()):.3f} | {len(results)} |"
            )
            vdir = archive / "versions" / vid[:12]
            vdir.mkdir(parents=True)
            shutil.copy(self.version_dir(vid) / "EXPERIMENT.md", vdir / "EXPERIMENT.md")
            shutil.copytree(self.version_dir(vid) / "bundle", vdir / "bundle")
        (archive / "README.md").write_text("\n".join(lines) + "\n")
        for result_file in sorted((self.camp / "runs").glob("dev-*/result.json")):
            result = json.loads(result_file.read_text())
            run = archive / "runs" / result_file.parent.name
            run.mkdir(parents=True)
            (run / "summary.json").write_text(
                json.dumps(
                    {k: v for k, v in result.items() if k not in ("label", "failures")},
                    indent=2,
                )
                + "\n"
            )
            (run / "failures.txt").write_text(result.get("failures", ""))
            sources.append(result_file.parent.name)
        self.record(
            "exposure",
            {"view": f"research:{step}", "parent": parent, "sources": sources},
        )
        prompt = RESEARCH_PROTOCOL.format(
            parent=parent[:12],
            files=", ".join(self.terms["mutable"]),
            sections=", ".join(EXPERIMENT_SECTIONS),
        )
        (root / "prompt.md").write_text(prompt)
        return root

    def research(self, parent: str, step: int) -> Path:
        root = self.stage_research(parent, step)
        run_dir = root / "run"
        if not (run_dir / "run.json").exists():
            shutil.rmtree(run_dir, ignore_errors=True)
            common = [
                "--arm",
                "on",
                "--instance",
                f"research-{step}",
                "--run-dir",
                str(run_dir),
            ]
            common += [
                "--codex-bin",
                self.terms["codex_bin"],
                "--image",
                self.terms["research_image"],
            ]
            prepare = common + [
                "--prompt",
                str(root / "prompt.md"),
                "--policy",
                str(self.version_dir(parent) / "bundle"),
            ]
            prepare += [
                "--instructions",
                "research.md",
                "--workspace-from",
                str(root / "workspace"),
                "--no-reference",
            ]
            subprocess.run([*self.runner, "prepare", *prepare], check=True)
            run = common + [
                "--deadline-secs",
                str(self.terms["research_deadline_secs"]),
            ]
            subprocess.run([*self.runner, "run", *run], check=False)
        return run_dir / "workspace"

    def qualify(self, delivery: Path, parent: str) -> tuple[bool, str, bool]:
        """Mechanical, complete criterion: an experiment record with every section, and a bundle
        changed only within the campaign's mutable files. Returns (qualified, reason, changed)."""
        experiment = delivery / "EXPERIMENT.md"
        if not experiment.exists() or not experiment.read_text().strip():
            return False, "no EXPERIMENT.md was delivered", False
        text = experiment.read_text()
        missing = [
            section
            for section in EXPERIMENT_SECTIONS
            if section.lower() not in text.lower()
        ]
        if missing:
            return False, f"EXPERIMENT.md lacks {', '.join(missing)}", False
        policy = delivery / "policy"
        extra = (
            sorted(p.name for p in policy.iterdir() if p.name not in BUNDLE_FILES)
            if policy.is_dir()
            else ["(missing policy/)"]
        )
        if extra:
            return (
                False,
                f"the bundle gained files outside the protocol: {', '.join(extra)}",
                False,
            )
        parent_bundle = self.version_dir(parent) / "bundle"
        changed = []
        for name in BUNDLE_FILES:
            path = policy / name
            new = path.read_bytes() if path.exists() else b""
            if len(new) > MAX_BUNDLE_FILE:
                return False, f"{name} exceeds 32 KiB", False
            try:
                new.decode("utf-8")
            except UnicodeDecodeError:
                return False, f"{name} is not UTF-8", False
            if new != (parent_bundle / name).read_bytes():
                changed.append(name)
        outside = [name for name in changed if name not in self.terms["mutable"]]
        if outside:
            return (
                False,
                f"changed files the campaign does not allow: {', '.join(outside)}",
                False,
            )
        return (
            True,
            "qualified" if changed else "a null experiment: the bundle is unchanged",
            bool(changed),
        )

    # ---- the step -----------------------------------------------------------------------------

    def step(self) -> str:
        parents = [
            e["body"]
            for e in self.events("selection")
            if e["body"]["role"] == "research_parent"
        ]
        last = parents[-1] if parents else None
        resuming = (
            last is not None
            and (state := self.contract(f"improvement.{last['step']}")) is not None
            and state["standing"] == "outstanding"
        )
        if resuming:
            step, parent = last["step"], last["version"]
        else:
            step = len(parents) + 1
            if step > self.terms["budgets"]["research_steps"]:
                return "the research budget is spent"
            parent, rule = self.choose_parent()
            self.record(
                "selection",
                {
                    "role": "research_parent",
                    "version": parent,
                    "rule": rule,
                    "step": step,
                },
            )
        improvement = f"improvement.{step}"
        self.issue(
            improvement,
            {
                "campaign": self.campaign_hash(),
                "parent": parent,
                "protocol": RESEARCH_PROTOCOL,
            },
            {
                "class": "qualification",
                "sections": EXPERIMENT_SECTIONS,
                "mutable": self.terms["mutable"],
            },
            "delegate",
        )
        delivery = self.research(parent, step)
        experiment = (
            (delivery / "EXPERIMENT.md").read_text()
            if (delivery / "EXPERIMENT.md").exists()
            else ""
        )
        ok, reason, changed = self.qualify(delivery, parent)
        subject = store.digest(
            "delivery",
            {
                "experiment": experiment,
                "bundle": {
                    name: (delivery / "policy" / name).read_text(errors="replace")
                    for name in BUNDLE_FILES
                    if (delivery / "policy" / name).exists()
                },
            },
        )
        self.propose(improvement, subject)
        if not ok:
            self.release(improvement, reason)
            return f"step {step}: research by {parent[:12]} did not qualify: {reason}"
        # The criterion is mechanical and complete, so the checks reach everything it asks.
        self.support(
            improvement, {"qualification": reason}, {"delivery": subject}, "beyond"
        )
        self.discharge(improvement, self.presumed(), reason)
        if not changed:
            return f"step {step}: {reason}"
        candidate = self.register(delivery / "policy", parent, parent, experiment)
        witness = self.adapter.witness(self, candidate)
        if witness:
            self.record(
                "selection",
                {"role": "unqualified", "version": candidate, "reason": witness},
            )
            return f"step {step}: candidate {candidate[:12]} failed its mechanism witness: {witness}"
        self.record("selection", {"role": "qualified", "version": candidate})
        incumbent = self.incumbent()
        delta = paired_delta(self.dev(candidate), self.dev(incumbent))
        gates = self.terms["gates"]
        if (
            delta < gates["dev_min_delta"]
            or self.confirm_budget_left() < gates["confirm_tasks"]
        ):
            return f"step {step}: candidate {candidate[:12]} stays in research (development delta {delta:+.3f})"
        self.record(
            "selection",
            {"role": "put_forward", "version": candidate, "dev_delta": delta},
        )
        return f"step {step}: candidate {candidate[:12]} put forward; " + self.confirm(
            candidate, incumbent
        )

    def campaign_hash(self) -> str:
        return store.digest("campaign", self.terms)

    def used_confirmation_tasks(self) -> list[str]:
        return [
            task
            for event in self.events("exposure")
            if event["body"]["view"].startswith("confirmation:")
            for task in event["body"]["sources"]
        ]

    def confirm_budget_left(self) -> int:
        return len(self.terms["pools"]["confirm"]) - len(self.used_confirmation_tasks())

    def confirm(self, candidate: str, incumbent: str) -> str:
        """Paired confirmation on fresh tasks: support from beyond the candidate's reach."""
        adoption = f"adoption.{candidate[:16]}"
        used = set(self.used_confirmation_tasks())
        fresh = [task for task in self.terms["pools"]["confirm"] if task not in used]
        tasks = fresh[: self.terms["gates"]["confirm_tasks"]]
        gate = {
            k: self.terms["gates"][k]
            for k in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
        }
        self.issue(
            adoption,
            {
                "campaign": self.campaign_hash(),
                "candidate": candidate,
                "expected_incumbent": incumbent,
                "gate": gate,
            },
            {
                "class": "paired_confirmation",
                "tasks": store.digest("pool", tasks),
                "gate": gate,
            },
            "delegate",
        )
        self.propose(adoption, candidate)
        # Spent before it is read: these tasks never certify anything again.
        self.record("exposure", {"view": f"confirmation:{candidate}", "sources": tasks})
        results = self.measure_all(
            [(v, t) for t in tasks for v in (candidate, incumbent)], "confirm"
        )
        pairs = {
            t: (
                results[(candidate, t)]["pass_rate"],
                results[(incumbent, t)]["pass_rate"],
            )
            for t in tasks
            if results[(candidate, t)]["validity"] == "valid"
            and results[(incumbent, t)]["validity"] == "valid"
        }
        deltas = [c - i for c, i in pairs.values()]
        evidence = {
            "pairs": pairs,
            "mean_delta": mean(deltas),
            "wins": sum(d > 0 for d in deltas),
            "gate": gate,
        }
        passed = (
            len(pairs) == len(tasks)
            and evidence["mean_delta"] >= gate["confirm_min_delta"]
            and evidence["wins"] >= gate["confirm_min_wins"]
        )
        if not passed:
            self.release(
                adoption,
                f"confirmation gate failed: {json.dumps(evidence, sort_keys=True)}",
            )
            return f"confirmation failed (mean delta {evidence['mean_delta']:+.3f}, {evidence['wins']}/{len(tasks)} wins)"
        self.support(
            adoption,
            evidence,
            {"tasks": tasks, "evaluator": self.adapter.evaluator()},
            "beyond",
        )
        if self.terms["adoption"] == "presumed":
            self.adopt(candidate, presumed=True)
            return f"confirmed and adopted under the campaign's convention (mean delta {evidence['mean_delta']:+.3f})"
        return f"confirmed (mean delta {evidence['mean_delta']:+.3f}); awaiting the principal's adoption"

    def adopt(self, candidate: str, presumed: bool = False) -> str:
        adoption = f"adoption.{candidate[:16]}"
        state = self.contract(adoption)
        if not state or not state["support"]:
            raise RuntimeError(f"{candidate[:12]} has no supported adoption")
        decision = self.presumed() if presumed else {"type": "explicit"}
        self.discharge(adoption, decision, f"adopt {candidate}")
        self.record(
            "selection",
            {"role": "incumbent", "version": candidate, "adoption": adoption},
        )
        return f"{candidate[:12]} is the incumbent"


class ProgramBench:
    """Ordinary tasks: re-implement a program; labelled by its hidden tests, beyond reach."""

    def __init__(self, terms: dict):
        self.terms = terms

    def environment(self) -> dict:
        return {"family": "programbench", "codex": self.terms["codex_sha256"]}

    def evaluator(self) -> dict:
        return {"programbench": self.terms["programbench_head"], "metric": "pass_rate"}

    def run_and_label(self, host: Host, bundle: Path, task: str, run_dir: Path) -> dict:
        import procontract_evaluation as evaluation

        common = ["--arm", "on", "--instance", task, "--run-dir", str(run_dir)]
        common += ["--codex-bin", self.terms["codex_bin"]]
        prepare = common + [
            "--prompt",
            self.terms["task_prompt"],
            "--policy",
            str(bundle),
        ]
        if (
            subprocess.run([*host.runner, "prepare", *prepare], check=False).returncode
            != 0
        ):
            return {
                "validity": "invalid",
                "reason": "prepare failed",
                "pass_rate": None,
            }
        subprocess.run(
            [
                *host.runner,
                "run",
                *common,
                "--deadline-secs",
                str(self.terms["task_deadline_secs"]),
            ],
            check=False,
        )
        summary = (
            json.loads((run_dir / "run.json").read_text())
            if (run_dir / "run.json").exists()
            else {}
        )
        if (summary.get("turn_statuses") or [""])[-1] == "failed" or summary.get(
            "server_exited_early"
        ):
            return {
                "validity": "invalid",
                "reason": "the executor turn failed",
                "pass_rate": None,
                "run": summary,
            }
        archive = run_dir / "submission.tar.gz"
        evaluation.package(run_dir / "workspace", archive)
        programbench = Path(self.terms["programbench"])
        subprocess.run(
            ["uv", "run", "programbench", "blob", "sync", task],
            cwd=programbench,
            capture_output=True,
            check=False,
        )
        outcome = evaluation.evaluate_package(
            archive,
            task,
            run_dir / "eval",
            ["uv", "run", "programbench"],
            programbench,
            self.terms["hf_revision"],
            set(),
        )
        label = {
            "task": task,
            "evaluator_epoch": store.digest("epoch", self.evaluator()),
            **outcome,
        }
        rate = (outcome.get("outcome") or {}).get("pass_rate")
        return {
            "validity": outcome["validity"],
            "pass_rate": rate,
            "status": summary.get("status"),
            "cost": summary.get("cost"),
            "failures": failure_excerpt(run_dir / "eval"),
            "label": label,
        }

    def witness(self, host: Host, vid: str) -> str:
        """The candidate's bundle actually ran: its lane identity and its executor instructions
        appear in a development run. An empty string means the witness holds."""
        bundle = host.version_dir(vid) / "bundle"
        task = host.terms["pools"]["dev"][0]
        result = host.measure(vid, task, "dev")
        if result["validity"] != "valid":
            return "its first development run was not valid"
        run_dir = Path(result["run_dir"])
        texts = [
            (bundle / name).read_text()
            for name in ("drafter.md", "prober.md", "reviewer.md")
        ]
        expected = store.digest("policy_bundle", texts)
        seen = {
            e["event"]["identities"]["policies"].get("bundle")
            for e in store.events(run_dir / "codex-home" / "pro_contract")
            if e["event"]["identities"]["policies"]
        }
        if expected not in seen:
            return "the lane did not run the candidate's worker instructions"
        executor = (bundle / "executor.md").read_text().strip()
        if executor:
            rollouts = list((run_dir / "codex-home" / "sessions").rglob("*.jsonl"))
            needle = json.dumps(executor[:200])[1:-1]
            if not any(needle in path.read_text(errors="replace") for path in rollouts):
                return "the executor did not receive the candidate's executor.md"
        return ""


def failure_excerpt(eval_dir: Path, limit: int = 40) -> str:
    """The last record of each failing hidden test, bounded: development evidence only."""
    paths = sorted(eval_dir.glob("attempt-*/*/*.eval.json"))
    if not paths:
        return ""
    last: dict = {}
    for result in json.loads(paths[-1].read_text()).get("test_results") or []:
        last[(result.get("branch", ""), result["name"])] = result
    lines = []
    for (_, name), result in sorted(last.items()):
        if result["status"] not in ("passed", "skipped") and len(lines) < limit:
            message = (result.get("extra") or {}).get("message") or ""
            lines.append(
                f"{name.rsplit('.', 1)[-1]}: {message.splitlines()[0][:200] if message else result['status']}"
            )
    return "\n".join(lines) + ("\n" if lines else "")


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def paired_delta(a: dict[str, float], b: dict[str, float]) -> float:
    shared = [task for task in a if task in b]
    return mean(a[task] - b[task] for task in shared) if shared else 0.0


def cmd_init(args) -> None:
    camp: Path = args.camp
    if (camp / "campaign.json").exists():
        sys.exit(f"{camp} already holds a campaign")
    pools = json.loads(args.pools.read_text())
    rng = random.Random(args.seed)
    dev = args.dev or rng.sample(sorted(pools["dev"]), args.dev_tasks)
    # Confirmation draws on a sealed pool no research view or selection has read.
    sealed = json.loads(args.sealed.read_text())[args.sealed_pool]
    confirm = rng.sample(sorted(sealed), min(args.confirm_pool, len(sealed)))
    codex = Path(args.codex_bin).resolve()
    terms = {
        "schema": 1,
        "seed": args.seed,
        "model": "gpt-5.6-luna",
        "effort": "max",
        "codex_bin": str(codex),
        "codex_sha256": subprocess.run(
            ["sha256sum", str(codex)], capture_output=True, text=True, check=True
        ).stdout.split()[0],
        "task_prompt": str(args.task_prompt.resolve()),
        "research_image": args.research_image,
        "programbench": str(args.programbench),
        "programbench_head": subprocess.run(
            ["git", "-C", str(args.programbench), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown",
        "hf_revision": args.hf_revision,
        "pools": {"dev": dev, "confirm": confirm},
        "budgets": {"research_steps": args.research_steps},
        "gates": {
            "dev_min_delta": args.dev_min_delta,
            "parent_regression_tolerance": args.parent_tolerance,
            "confirm_tasks": args.confirm_tasks,
            "confirm_min_delta": args.confirm_min_delta,
            "confirm_min_wins": args.confirm_min_wins,
        },
        "mutable": args.mutable,
        "adoption": args.adoption,
        "parallel": args.parallel,
        "task_deadline_secs": args.task_deadline_secs,
        "research_deadline_secs": args.research_deadline_secs,
    }
    camp.mkdir(parents=True)
    (camp / "campaign.json").write_text(json.dumps(terms, indent=2) + "\n")
    host = Host(camp)
    host.issue("campaign", terms, {"class": "campaign_report"}, "human")
    v0 = host.register(
        V0_BUNDLE, None, "operator", "Version 0: the shipped policy bundle.\n"
    )
    adoption = f"adoption.{v0[:16]}"
    host.issue(
        adoption,
        {"campaign": host.campaign_hash(), "candidate": v0, "bootstrap": True},
        {"class": "bootstrap"},
        "human",
    )
    host.propose(adoption, v0)
    host.support(
        adoption, {"bootstrap": "operator-seeded"}, {"operator": True}, "within"
    )
    host.adopt(v0)
    print(
        json.dumps(
            {"campaign": str(camp), "v0": v0, "dev": dev, "confirm": confirm}, indent=2
        )
    )


def cmd_step(args) -> None:
    host = Host(args.camp)
    for _ in range(args.count):
        print(host.step(), flush=True)


def cmd_adopt(args) -> None:
    host = Host(args.camp)
    matches = [vid for vid in host.versions() if vid.startswith(args.version)]
    if len(matches) != 1:
        sys.exit(f"{args.version} names {len(matches)} versions")
    print(host.adopt(matches[0]))


def cmd_status(args) -> None:
    host = Host(args.camp)
    incumbent = host.incumbent()
    roles = {}
    for event in host.events("selection"):
        roles.setdefault(event["body"]["version"], []).append(event["body"]["role"])
    rows = []
    for vid, manifest in host.versions().items():
        rows.append(
            {
                "version": vid[:12],
                "parent": (manifest["lineage"]["parent"] or "")[:12],
                "incumbent": vid == incumbent,
                "roles": roles.get(vid, []),
                "dev_mean": round(mean(results.values()), 3)
                if (results := host.dev_results(vid))
                else None,
            }
        )
    print(
        json.dumps(
            {
                "incumbent": incumbent[:12],
                "versions": rows,
                "confirm_tasks_left": host.confirm_budget_left(),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--camp", type=Path, required=True)
    init.add_argument("--pools", type=Path, required=True)
    init.add_argument("--codex-bin", required=True)
    init.add_argument("--task-prompt", type=Path, required=True)
    init.add_argument("--research-image", required=True)
    init.add_argument("--programbench", type=Path, default=Path.home() / "ProgramBench")
    init.add_argument("--hf-revision", required=True)
    init.add_argument("--seed", type=int, default=20261006)
    init.add_argument("--dev", nargs="+")
    init.add_argument("--dev-tasks", type=int, default=3)
    init.add_argument(
        "--sealed", type=Path, required=True, help="the operator's sealed pool lists"
    )
    init.add_argument(
        "--sealed-pool", default="select", help="the sealed pool confirmation draws on"
    )
    init.add_argument("--confirm-pool", type=int, default=8)
    init.add_argument("--confirm-tasks", type=int, default=4)
    init.add_argument("--research-steps", type=int, default=2)
    init.add_argument("--dev-min-delta", type=float, default=0.0)
    init.add_argument("--parent-tolerance", type=float, default=0.05)
    init.add_argument("--confirm-min-delta", type=float, default=0.0)
    init.add_argument("--confirm-min-wins", type=int, default=3)
    init.add_argument("--mutable", nargs="+", default=BUNDLE_FILES)
    init.add_argument(
        "--adoption", choices=["explicit", "presumed"], default="explicit"
    )
    init.add_argument("--parallel", type=int, default=4)
    init.add_argument("--task-deadline-secs", type=int, default=5 * 3600)
    init.add_argument("--research-deadline-secs", type=int, default=3600)
    step = sub.add_parser("step")
    step.add_argument("--camp", type=Path, required=True)
    step.add_argument("--count", type=int, default=1)
    adopt = sub.add_parser("adopt")
    adopt.add_argument("--camp", type=Path, required=True)
    adopt.add_argument("--version", required=True)
    status = sub.add_parser("status")
    status.add_argument("--camp", type=Path, required=True)
    args = parser.parse_args()
    {"init": cmd_init, "step": cmd_step, "adopt": cmd_adopt, "status": cmd_status}[
        args.command
    ](args)


if __name__ == "__main__":
    main()
