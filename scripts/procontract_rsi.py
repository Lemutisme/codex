#!/usr/bin/env python3
"""ProContract succession: the institution's side of recursive self-improvement.

A version is a policy bundle (executor.md, research.md, analyst.md, challenger.md, drafter.md,
prober.md, reviewer.md) run by one codex binary. Improving the method is an ordinary task whose
product may succeed the version that does the work (reach spec §5). This host stays outside every version's write authority: it
runs from its own checkout, holds the campaign ledger, chooses research parents, runs and measures
versions, and keeps every claim in the kernel through the store CLI.

  init     start a campaign: pools, budgets, gates; register v0 and adopt it as the first incumbent
  step     one research step: parent → analysis of what the runs show → research run → delivery →
           qualification → development evaluation → analysis that settles the experiment → (when
           it earns it) paired confirmation against the incumbent
  analyze  run the analysis that is due, if any (the host runs it inside every step)
  adopt    the human adopts a confirmed candidate (an explicit settlement)
  status   derived views: incumbent, versions, budgets, the latest verdicts and proposals

Observation and analysis (insight spec): every valid run is normalized into observations/ once; an
analyst run explains outcomes from trajectories and a challenger run tries to defeat the
explanation. Only a challenged delivery becomes the campaign's knowledge and verdict.

One run is a learning signal (insight spec §12): the analyst assigns credit for each failing
cluster by what the executor knew when (hindsight.json), and every measured experiment registers,
before its runs, which hidden items now failed by every stored run it will rescue (prediction.json).
Chance seldom rescues such an item, so one run settles the prediction, mechanically and from beyond
the candidate's reach. A candidate is put forward only when its signature is present, its prediction
held and its development delta clears the gate.

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
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_attribution as attribution
import procontract_outcomes as outcome_matrix
import procontract_store as store
import procontract_trajectory as trajectory

SCRIPTS = Path(__file__).resolve().parent
RUNNER = [sys.executable, str(SCRIPTS / "procontract_benchmark_runner.py")]
V0_BUNDLE = SCRIPTS.parent / "codex-rs" / "ext" / "pro-contract" / "policies"
BUNDLE_FILES = [
    "executor.md",
    "research.md",
    "analyst.md",
    "challenger.md",
    "drafter.md",
    "prober.md",
    "reviewer.md",
]
# The files that shape how a version does tasks; research.md, analyst.md and challenger.md shape
# only how it studies itself, so a version that changes only those is a twin of its parent.
TASK_FILES = ["executor.md", "drafter.md", "prober.md", "reviewer.md"]
MAX_BUNDLE_FILE = 32 << 10
KNOWLEDGE_CAP = 512 << 10
SIGNATURES = ("present", "partial", "absent")
# How the information stood for a failing cluster, and for one never sent, where it could come from.
CLASSES = ("never_sent", "never_compared", "left_unfixed", "too_shallow")
SOURCES = ("artifact", "convention", "prior", "unobservable")
# Before any evidence, one chance rescue in ten floor items: conservative, so early predictions
# need several rescues to hold.
PRIOR_RESCUE = (1, 10)
OUTCOME_MESSAGE_CAP = 1000
LATEST_ANALYSES = 5
PROPOSAL_LINES = 20
EXPERIMENT_SECTIONS = [
    "Mechanism",
    "Hypothesis",
    "Change",
    "Signature",
    "Prediction",
    "Falsifier",
    "Risks",
]
OWNER = "principal"
NOISE_FLOOR = 0.087
NOISE_SOURCE = "same-task repeat runs in corpus-v1, mean absolute difference"

RESEARCH_PROTOCOL = """This is a research task: improve how an agent works.

Your workspace holds:
- policy/: the policy bundle of version {parent}. You may edit only these files: {files}. Each must
  stay under 32 KiB. The bundle as you leave it is your candidate.
- archive/: evidence from earlier runs and research steps. Read it; do not change it.
  archive/knowledge/ is what the campaign has learned so far and archive/insight/ holds the
  analyses that produced it.

Deliver ./EXPERIMENT.md with the sections {sections}. When you change a file that shapes how tasks
are done ({task_files}), also deliver ./prediction.json, {{"rescue": {{"<task>": ["<item id>", ...]}}}}:
the hidden items your change will make pass, chosen among those every stored run failed (the floor in
archive/tasks/<task>/outcomes.md). No network is available. Tools: python3, jq, grep, sed and awk are
installed; rg is not.
"""

ANALYST_PROTOCOL = """This is an analysis task: explain what the agent did and why its runs scored as they did.

Your workspace holds:
- archive/: the evidence, read-only. Start with archive/README.md.
- knowledge/: what the campaign knows, as you inherited it. Edit it: UTF-8 text only, at most
  512 KiB in total.

{pending}
Deliver ./ANALYSIS.md and ./hindsight.json, and leave ./knowledge as the campaign should keep it. No
network is available. Tools: python3, jq, grep, sed and awk are installed; rg is not.
"""

CHALLENGER_PROTOCOL = """This is a challenge task: try to defeat an analysis of an agent's runs.

Your workspace holds:
- archive/: the evidence the analyst read, read-only. archive/knowledge/ is the knowledge before the
  analysis.
- ANALYSIS.md, hindsight.json, verdict.json (when an experiment is pending) and knowledge/: the
  analyst's delivery. You may amend knowledge/ (UTF-8 text only, at most 512 KiB in total),
  hindsight.json and verdict.json.

{pending}
Deliver ./CHALLENGE.md. No network is available. Tools: python3, jq, grep, sed and awk are
installed; rg is not.
"""

PENDING = (
    "Experiment {version} is pending: ./verdict.json must say whether its signature was present. The "
    "host has settled its prediction from the hidden outcomes (archive/versions/{version}/settlement.json)."
)
NOT_PENDING = "No experiment is pending."

LAYOUT = """Layout:
- versions/<id>/: a version's bundle and EXPERIMENT.md; its prediction.json and the host's
  settlement.json of it (rescued items against chance, from the hidden outcomes); and verdict.json
  once an analysis has counted its signature.
- runs/<run>/: one run per valid development task and per spent confirmation task. summary.json (the
  result and a per-turn trajectory block), outcomes.json (every hidden item: passed, message),
  failures.txt, trajectory.md (the executor's thread in order), events.jsonl (the same as records)
  and final/ (the text files the executor left).
- tasks/<task>/outcomes.md: the outcome matrix of one task across all the runs above.
- attribution/: per task, how a version's behavior and outcomes differ from its parent's.
- insight/<k>/: earlier analyses (ANALYSIS.md, CHALLENGE.md, hindsight.json, and the verdict.json
  that counted an experiment's signature).
- knowledge/: what the campaign knows (mechanisms, refuted beliefs, task dossiers, proposals).
  Read-only here.
Confirmation tasks that are not spent do not appear anywhere.
Tools: python3, jq, grep, sed and awk are installed; rg is not."""


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
        # Only valid measurements are kept: an invalid run is infrastructure, never a result, so a
        # later invocation measures again.
        if (
            result_file.exists()
            and json.loads(result_file.read_text())["validity"] == "valid"
        ):
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

    def twin(self, vid: str) -> str:
        """The earliest ancestor that does tasks exactly as `vid` does. Task behavior is measured
        once per twin: a change to the research method alone changes no task result."""
        versions = self.versions()
        while (parent := versions[vid]["lineage"]["parent"]) is not None and all(
            versions[vid]["bundle"][name] == versions[parent]["bundle"][name]
            for name in TASK_FILES
        ):
            vid = parent
        return vid

    def dev(self, vid: str) -> dict[str, float]:
        """Pass rate per development task (valid runs only), measuring what is missing."""
        vid = self.twin(vid)
        self.measure_all([(vid, task) for task in self.terms["pools"]["dev"]], "dev")
        return self.dev_results(vid)

    def dev_results(self, vid: str) -> dict[str, float]:
        """Development pass rates already measured; never starts a run."""
        return {
            task: result["pass_rate"] for task, result in self.dev_runs(vid).items()
        }

    def dev_runs(self, vid: str) -> dict[str, dict]:
        """Valid development results per task, as cached; never starts a run."""
        vid = self.twin(vid)
        results = {}
        for path in sorted((self.camp / "runs").glob(f"dev-{vid[:12]}-*/result.json")):
            result = json.loads(path.read_text())
            if result["validity"] == "valid":
                results[result["task"]] = result
        return results

    def attribution(
        self, vid: str, noise: float = NOISE_FLOOR
    ) -> tuple[str, list[dict]] | None:
        """The attribution rows of a version against its parent's twin over the tasks both have
        valid development results for; None for the root and for method-only versions."""
        parent = self.versions()[vid]["lineage"]["parent"]
        if parent is None or self.twin(vid) != vid:
            return None
        parent = self.twin(parent)
        child_runs, parent_runs = self.dev_runs(vid), self.dev_runs(parent)
        patterns = self.adapter.oracle_patterns()
        rows = []
        for task in sorted(child_runs.keys() & parent_runs.keys()):
            child, base = child_runs[task], parent_runs[task]
            rows.append(
                attribution.attribute(
                    base,
                    child,
                    self.adapter.items(Path(base["run_dir"])),
                    self.adapter.items(Path(child["run_dir"])),
                    attribution.behavior(base["run_dir"], patterns),
                    attribution.behavior(child["run_dir"], patterns),
                    noise,
                )
            )
        return (parent, rows) if rows else None

    # ---- observation and analysis -------------------------------------------------------------

    def observed(self) -> dict[str, dict]:
        """The valid runs the archive may show, by run name: every development run and every
        confirmation run of a spent task (a spent task never certifies again, so reading its runs
        costs nothing). Confirmation tasks not yet spent are never in it."""
        spent = set(self.used_confirmation_tasks())
        runs = {}
        for path in sorted((self.camp / "runs").glob("*/result.json")):
            result = json.loads(path.read_text())
            if result["validity"] == "valid" and (
                result["purpose"] == "dev" or result["task"] in spent
            ):
                runs[path.parent.name] = result
        return runs

    def observe(self, name: str, result: dict) -> Path:
        """Normalizes one valid run into observations/<name>/ once: what happened (trajectory) beside
        what the hidden tests said (outcomes). Built aside and renamed, so a directory that exists
        is complete; a run without a rollout has a null trajectory block and no trajectory files."""
        run_dir = Path(result["run_dir"])
        dest = self.camp / "observations" / name
        if dest.exists():
            return dest
        partial = dest.with_name(dest.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        status = result.get("status")
        stats = trajectory.write(
            run_dir,
            partial,
            self.adapter.oracle_patterns(),
            status.get("thread_id") if isinstance(status, dict) else None,
        )
        copied, omitted = trajectory.copy_final(
            run_dir / "workspace", partial / "final"
        )
        (partial / "outcomes.json").write_text(
            json.dumps(self.adapter.outcomes(run_dir), indent=2) + "\n"
        )
        (partial / "failures.txt").write_text(result.get("failures", ""))
        summary = {k: v for k, v in result.items() if k not in ("label", "failures")}
        summary["trajectory"] = stats
        summary["final"] = {"copied": len(copied), "omitted": omitted}
        (partial / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        partial.rename(dest)
        return dest

    def insights(self) -> list[dict]:
        """Every analysis recorded so far, in order (qualified or failed)."""
        return [event["body"] for event in self.events("insight")]

    def insight(self, k: int) -> dict:
        return self.insights()[k - 1]

    def latest_insight(self) -> Path | None:
        """The directory of the latest qualified analysis, if any."""
        for body in reversed(self.insights()):
            if body["status"] == "qualified":
                return self.camp / "insight" / str(body["k"])
        return None

    def current_knowledge(self) -> Path | None:
        """The latest qualified analysis's knowledge, else the campaign's seed, else none."""
        if latest := self.latest_insight():
            return latest / "knowledge"
        seed = self.camp / "knowledge-seed"
        return seed if seed.is_dir() else None

    def pending_experiment(self) -> str | None:
        """The newest candidate measured on every development task that no qualified analysis has
        yet settled: the experiment the next analysis must judge."""
        asked = {
            body["experiment"]
            for body in self.insights()
            if body["status"] == "qualified"
        }
        pending = None
        for event in self.events("selection"):
            body = event["body"]
            vid = body["version"]
            if (
                body["role"] == "qualified"
                and not body.get("method_only")
                and vid not in asked
                and len(self.dev_results(vid)) == len(self.terms["pools"]["dev"])
            ):
                pending = vid
        return pending

    def write_archive(self, archive: Path, parent: str) -> list[str]:
        """The archive every view shares: versions, observed runs, per-task matrices, attribution,
        completed analyses and the current knowledge. Returns its sources, the run names."""
        runs = self.observed()
        archive.mkdir(parents=True)
        self.write_readme(archive, parent)
        settled = {
            body["experiment"]: body["k"]
            for body in self.insights()
            if body["status"] == "qualified" and body["verdict"]
        }
        for vid in self.versions():
            vdir = archive / "versions" / vid[:12]
            vdir.mkdir(parents=True)
            shutil.copy(self.version_dir(vid) / "EXPERIMENT.md", vdir / "EXPERIMENT.md")
            shutil.copytree(self.version_dir(vid) / "bundle", vdir / "bundle")
            for name in ("prediction.json", "settlement.json"):
                if (self.version_dir(vid) / name).exists():
                    shutil.copy(self.version_dir(vid) / name, vdir)
            if vid in settled:
                shutil.copy(
                    self.camp / "insight" / str(settled[vid]) / "verdict.json", vdir
                )
        for name, result in runs.items():
            shutil.copytree(self.observe(name, result), archive / "runs" / name)
        self.write_outcomes(archive)
        self.write_attribution(archive)
        for body in self.insights():
            if body["status"] == "qualified":
                kept = self.camp / "insight" / str(body["k"])
                target = archive / "insight" / str(body["k"])
                target.mkdir(parents=True)
                for name in ("ANALYSIS.md", "CHALLENGE.md", "hindsight.json", "verdict.json"):
                    if (kept / name).exists():
                        shutil.copy(kept / name, target)
        copy_knowledge(self.current_knowledge(), archive / "knowledge")
        return list(runs)

    def write_readme(self, archive: Path, parent: str) -> None:
        pending = self.pending_experiment()
        lines = [
            "# Archive",
            "",
            f"Incumbent version: {self.incumbent()[:12]}. Research parent: {parent[:12]}.",
        ]
        if pending:
            lines.append(f"Pending experiment: {pending[:12]}")
        lines += [
            "Pass rates come from hidden tests the agent never sees (beyond its reach); 1.0 is perfect.",
            "",
            "| version | parent | development mean | tasks |",
            "|---|---|---|---|",
        ]
        for vid, manifest in self.versions().items():
            results = self.dev_results(vid)
            lines.append(
                f"| {vid[:12]} | {(manifest['lineage']['parent'] or '-')[:12]} | "
                f"{f'{mean(results.values()):.3f}' if results else '-'} | {len(results)} |"
            )
        rate, rescued, exposed = self.chance()
        lines += [
            "",
            f"Chance rescue rate of a floor item: {rate:.3f} ({rescued} of {exposed} floor items "
            f"passed in a held-out run, smoothed by a prior of {PRIOR_RESCUE[0]} in "
            f"{PRIOR_RESCUE[1]}). A prediction holds when chance alone would rarely rescue as many "
            f"of its floor items as the candidate does (p <= {self.terms['gates']['prediction_alpha']}).",
        ]
        latest = self.latest_insight()
        if latest and (latest / "hindsight.json").exists():
            lines += ["", *failure_mass(json.loads((latest / "hindsight.json").read_text()))]
        (archive / "README.md").write_text("\n".join([*lines, "", LAYOUT]) + "\n")

    def task_runs(self) -> dict[str, list[dict]]:
        """Every observed run by task, as the outcome matrix reads them. A run's parent is the twin
        of its version's lineage parent, which is how the matrix draws lineage edges."""
        versions = self.versions()
        by_task: dict[str, list[dict]] = {}
        for name, result in self.observed().items():
            version = result["version"]
            parent = versions[version]["lineage"]["parent"]
            outcomes = json.loads((self.observe(name, result) / "outcomes.json").read_text())
            by_task.setdefault(result["task"], []).append(
                {
                    "name": name,
                    "version": version,
                    "twin": self.twin(version),
                    "parent": self.twin(parent) if parent else None,
                    "purpose": result["purpose"],
                    "outcomes": outcomes,
                }
            )
        return by_task

    def floor(self, task: str) -> set[str]:
        """The items every stored run of `task` failed: no version has reached them, and chance
        seldom does, so they are where one run can decide a prediction."""
        return set(outcome_matrix.classify(self.task_runs().get(task, []))[1])

    def chance(self) -> tuple[float, int, int]:
        """The rate at which a floor item passes by chance, with its (rescued, exposed) counts:
        held-out runs against the floor of the others, smoothed by PRIOR_RESCUE."""
        rescued, exposed = outcome_matrix.chance_rescues(list(self.task_runs().values()))
        return (rescued + PRIOR_RESCUE[0]) / (exposed + PRIOR_RESCUE[1]), rescued, exposed

    def write_outcomes(self, archive: Path) -> None:
        """tasks/<task>/outcomes.md over all the observed runs of each task."""
        for task, group in self.task_runs().items():
            target = archive / "tasks" / task
            target.mkdir(parents=True)
            (target / "outcomes.md").write_text(
                outcome_matrix.render(task, outcome_matrix.matrix(group))
            )

    def write_attribution(self, archive: Path) -> None:
        noise = self.terms.get("noise_floor", NOISE_FLOOR)
        for vid in self.versions():
            if (found := self.attribution(vid, noise)) is None:
                continue
            parent, rows = found
            target = archive / "attribution" / f"{vid[:12]}-vs-{parent[:12]}.md"
            target.parent.mkdir(exist_ok=True)
            experiment = (self.version_dir(vid) / "EXPERIMENT.md").read_text()
            target.write_text(
                attribution.render(vid, parent, rows, experiment, noise, NOISE_SOURCE)
            )

    def stage_view(self, root: Path, view: str, parent: str, prompt: str, fill) -> None:
        """Builds root/workspace once: the archive plus whatever `fill(partial)` adds, with the
        agent's prompt beside it. It is built aside and renamed, so an existing workspace is a
        finished one, and the exposure of its sources is recorded before any agent can read it
        (and not twice when a crash falls between the record and the rename)."""
        workspace = root / "workspace"
        if workspace.exists():
            return
        partial = root / "workspace.partial"
        shutil.rmtree(partial, ignore_errors=True)
        sources = self.write_archive(partial / "archive", parent)
        fill(partial)
        (root / "prompt.md").write_text(prompt)
        exposure = {"view": view, "parent": parent, "sources": sources}
        if exposure not in [event["body"] for event in self.events("exposure")]:
            self.record("exposure", exposure)
        partial.rename(workspace)

    def run_agent(
        self, root: Path, instance: str, parent: str, instructions: str, deadline: int
    ) -> Path:
        """Runs a codex agent on the research image in root/workspace, no network and no
        reference, with the parent's bundle file `instructions` as its standing instructions;
        returns the workspace it leaves. A finished run (run.json) is never run again, and neither
        is one that ended without it: that attempt is spent and marked, so a resumed host judges
        what it left instead of paying for the attempt twice. A failed prepare starts no agent, so
        it stops the host, which resumes there."""
        run_dir = root / "run"
        ended = root / "ended-without-run-json"
        if not (run_dir / "run.json").exists() and not ended.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
            common = [
                "--arm",
                "on",
                "--instance",
                instance,
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
                instructions,
                "--workspace-from",
                str(root / "workspace"),
                "--no-reference",
            ]
            subprocess.run([*self.runner, "prepare", *prepare], check=True)
            run = common + ["--deadline-secs", str(deadline)]
            subprocess.run([*self.runner, "run", *run], check=False)
            if not (run_dir / "run.json").exists():
                ended.write_text("the run ended without run.json\n")
        return run_dir / "workspace"

    def analyze(self, parent: str) -> int:
        """The analysis that covers every valid run stored now: the latest when the set of runs has
        not grown since and it qualified, otherwise a new one (a failed analysis is tried again on
        the next call, with the same experiment pending). An analyst explains the outcomes and
        settles the pending experiment; a challenger tries to defeat that; only a challenged
        delivery that qualifies becomes the campaign's, else the failure is recorded, the knowledge
        stays and the verdict is unknown. Each stage may retry once; finished runs are never run
        again."""
        coverage = sorted(self.observed())
        done = self.insights()
        if (
            done
            and done[-1]["coverage"] == coverage
            and done[-1]["status"] == "qualified"
        ):
            return done[-1]["k"]
        k = len(done) + 1
        root = self.camp / "insight" / str(k)
        marker = root / "coverage.json"
        if marker.exists() and json.loads(marker.read_text()) != coverage:
            # Runs arrived after an interrupted attempt staged its views: start the analysis over.
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(coverage))
        pending = self.pending_experiment()
        previous = self.current_knowledge()
        note = PENDING.format(version=pending[:12]) if pending else NOT_PENDING
        known = {
            task: {item for run in runs for item in run["outcomes"]}
            for task, runs in self.task_runs().items()
        }
        analysis, reason = self.insight_stage(
            root,
            "analyst",
            f"analysis:{k}",
            k,
            parent,
            ANALYST_PROTOCOL.format(pending=note),
            pending,
            known,
            lambda partial: copy_knowledge(previous, partial / "knowledge"),
            "ANALYSIS.md",
        )
        challenge = None
        if analysis is not None:
            challenge, reason = self.insight_stage(
                root,
                "challenger",
                f"challenge:{k}",
                k,
                parent,
                CHALLENGER_PROTOCOL.format(pending=note),
                pending,
                known,
                lambda partial: hand_over(analysis, partial, pending),
                "CHALLENGE.md",
            )
        body = {
            "k": k,
            "coverage": coverage,
            "experiment": pending,
            "verdict": "unknown",
            "status": "failed",
            "reason": reason,
        }
        if challenge is not None:
            shutil.copy(analysis / "ANALYSIS.md", root)
            shutil.copy(challenge / "CHALLENGE.md", root)
            shutil.copy(challenge / "hindsight.json", root)
            if pending:
                shutil.copy(challenge / "verdict.json", root)
            shutil.rmtree(root / "knowledge", ignore_errors=True)
            copy_knowledge(challenge / "knowledge", root / "knowledge")
            verdict = (
                json.loads((root / "verdict.json").read_text())["signature"]
                if pending
                else None
            )
            body = {**body, "verdict": verdict, "status": "qualified"}
            del body["reason"]
        self.record("insight", body)
        return k

    def insight_stage(
        self,
        root: Path,
        role: str,
        view: str,
        k: int,
        parent: str,
        prompt: str,
        pending: str | None,
        known: dict[str, set[str]],
        fill,
        document: str,
    ) -> tuple[Path | None, str]:
        """One agent of an analysis, with one retry: the workspace of the first attempt whose
        delivery qualifies, else the reason the last did not. Attempts are directories, so a
        resumed analysis reads the finished ones and runs only what is missing."""
        deadline = self.terms.get(
            "analysis_deadline_secs", self.terms["research_deadline_secs"]
        )
        reason = ""
        for attempt in (1, 2):
            base = root / f"{role}-{attempt}"
            self.stage_view(base, view, parent, prompt, fill)
            delivery = self.run_agent(
                base, f"{role}-{k}-{attempt}", parent, f"{role}.md", deadline
            )
            reason = delivery_problem(delivery, document, pending, known)
            if not reason:
                return delivery, ""
        return None, f"{role}: {reason}"

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
        """The research view: the parent's bundle (editable) and the archive (valid development
        runs, spent confirmation runs, the analyses and the knowledge). Confirmation tasks not yet
        spent never enter it."""
        root = self.camp / "research" / f"step-{step}"
        prompt = RESEARCH_PROTOCOL.format(
            parent=parent[:12],
            files=", ".join(self.terms["mutable"]),
            sections=", ".join(EXPERIMENT_SECTIONS),
            task_files=", ".join(TASK_FILES),
        )
        self.stage_view(
            root,
            f"research:{step}",
            parent,
            prompt,
            lambda partial: shutil.copytree(
                self.version_dir(parent) / "bundle", partial / "policy"
            ),
        )
        return root

    def research(self, parent: str, step: int) -> Path:
        root = self.stage_research(parent, step)
        return self.run_agent(
            root,
            f"research-{step}",
            parent,
            "research.md",
            self.terms["research_deadline_secs"],
        )

    def qualify(self, delivery: Path, parent: str) -> tuple[bool, str, bool]:
        """Mechanical, complete criterion: an experiment record with every section, a bundle
        changed only within the campaign's mutable files, and task-shaping files that name no task
        the campaign has exposed. Returns (qualified, reason, changed)."""
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
        if leak := self.boundary(policy, changed):
            return False, leak, False
        if any(name in TASK_FILES for name in changed) and (
            problem := self.prediction_problem(delivery / "prediction.json")
        ):
            return False, problem, False
        return (
            True,
            "qualified" if changed else "a null experiment: the bundle is unchanged",
            bool(changed),
        )

    def prediction_problem(self, path: Path) -> str:
        """Why prediction.json cannot be settled by the candidate's runs, or an empty string. It
        names, per development task, hidden items the change will make pass; at least one must be
        on the floor, where chance is quiet, or no single run could decide it."""
        if path.is_symlink():
            return "prediction.json is a link"
        try:
            prediction = json.loads(path.read_text())
        except (OSError, ValueError):
            return "no prediction.json was delivered, or it is not JSON"
        rescue = prediction.get("rescue") if isinstance(prediction, dict) else None
        if not isinstance(rescue, dict) or not rescue:
            return "prediction.json names no items to rescue"
        runs = self.task_runs()
        decisive = 0
        for task, items in rescue.items():
            if task not in self.terms["pools"]["dev"]:
                return f"prediction.json names {task}, which is not a development task"
            known = {item for run in runs.get(task, []) for item in run["outcomes"]}
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item in known for item in items
            ):
                return f"prediction.json names items no run of {task} has"
            decisive += len(set(items) & self.floor(task))
        if not decisive:
            return "none of the predicted items is failed by every stored run, so no run can decide the prediction"
        return ""

    def predict(self, candidate: str, delivery: Path) -> str:
        """Registers the candidate's prediction as a contract before any of its runs exist: the
        floor items it names and the chance rate are frozen in the terms, so the outcome cannot
        shape the claim."""
        contract = f"prediction.{candidate[:16]}"
        shutil.copy(delivery / "prediction.json", self.version_dir(candidate))
        rescue = json.loads((delivery / "prediction.json").read_text())["rescue"]
        rate, rescued, exposed = self.chance()
        self.issue(
            contract,
            {
                "experiment": candidate,
                "rescue": {
                    task: sorted(set(items) & self.floor(task))
                    for task, items in sorted(rescue.items())
                },
                "chance": {"rate": rate, "rescued": rescued, "exposed": exposed},
                "alpha": self.terms["gates"]["prediction_alpha"],
            },
            {"class": "rescue", "rule": "binomial tail of rescued floor items <= alpha"},
            "delegate",
        )
        return contract

    def settle(self, candidate: str) -> dict:
        """Settles the candidate's prediction from its development runs, mechanically: the hidden
        outcomes come from beyond its reach, and the rule was frozen before they existed. Counts the
        frozen floor items its runs pass, against chance; discharges the prediction when chance
        alone would rarely rescue as many, and defeats it otherwise."""
        contract = f"prediction.{candidate[:16]}"
        settlement_file = self.version_dir(candidate) / "settlement.json"
        if settled := self.settlement(candidate):
            return settled
        terms = next(
            event["body"]["terms"]
            for event in self.events("issue")
            if event["body"]["contract_id"] == contract
        )
        runs = self.dev_runs(candidate)
        tasks = {}
        for task, items in terms["rescue"].items():
            if task in runs:
                passed = self.adapter.outcomes(Path(runs[task]["run_dir"]))
                tasks[task] = {
                    "predicted": len(items),
                    "rescued": sorted(i for i in items if passed.get(i, {}).get("passed")),
                }
        n = sum(t["predicted"] for t in tasks.values())
        k = sum(len(t["rescued"]) for t in tasks.values())
        rate = terms["chance"]["rate"]
        p = outcome_matrix.binomial_tail(n, k, rate)
        settlement = {
            "experiment": candidate,
            "predicted": n,
            "rescued": k,
            "expected_by_chance": round(n * rate, 3),
            "p": p,
            "alpha": terms["alpha"],
            "held": n > 0 and p <= terms["alpha"],
            "tasks": tasks,
        }
        reading = f"{k} of {n} floor items rescued, {n * rate:.2f} expected by chance, p={p:.2g}"
        self.propose(
            contract, store.digest("runs", {task: runs[task]["run_dir"] for task in tasks})
        )
        if settlement["held"]:
            self.support(contract, settlement, {"runs": sorted(tasks)}, "beyond")
            self.discharge(contract, self.presumed(), reading)
        else:
            self.release(contract, reading)
        settlement_file.write_text(json.dumps(settlement, indent=2) + "\n")
        return settlement

    def settlement(self, vid: str) -> dict | None:
        """The host's settlement of a version's prediction, once it exists."""
        path = self.version_dir(vid) / "settlement.json"
        return json.loads(path.read_text()) if path.exists() else None

    def exposed_tasks(self) -> list[str]:
        """Tasks some view or selection has read: the development pool and the spent confirmation
        tasks."""
        return [*self.terms["pools"]["dev"], *self.used_confirmation_tasks()]

    def boundary(self, policy: Path, changed: list[str]) -> str:
        """Why a changed task-shaping file crosses the boundary, or an empty string. Dossiers carry
        hidden-test detail for the research view only; the files that shape how a version does
        tasks must stay task-agnostic, so none may name an exposed task, as a whole word in any
        case. Confirmation on fresh tasks remains the certifier; this only keeps the leak out."""
        tokens = sorted(
            {
                token
                for task in self.exposed_tasks()
                for token in self.adapter.task_tokens(task)
            }
        )
        # A deleted file names nothing.
        for name in (
            name for name in changed if name in TASK_FILES and (policy / name).exists()
        ):
            text = (policy / name).read_text()
            for token in tokens:
                if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text, re.IGNORECASE):
                    return f"{name} names the exposed task token '{token}'"
        return ""

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
        # Research starts from evidence: the parent's development runs fill the archive it reads,
        # and an analysis of them (the first, or nothing new) comes before it.
        self.dev(parent)
        self.analyze(parent)
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
        if self.twin(candidate) != candidate:
            # Only the research method changed: its tasks are its ancestor's by construction, so
            # nothing is measured and nothing is put forward; it shows its worth in its successors.
            self.record(
                "selection",
                {"role": "qualified", "version": candidate, "method_only": True},
            )
            return f"step {step}: candidate {candidate[:12]} changes only the research method; it continues in research"
        self.predict(candidate, delivery)
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
        # The measured runs settle the experiment twice: the host settles its prediction from the
        # hidden outcomes, and a challenged analysis counts its signature in the trajectories.
        settlement = self.settle(candidate)
        self.analyze(parent)
        verdict = self.settled_verdict(candidate)
        gates = self.terms["gates"]
        reading = (
            f"development delta {delta:+.3f}; signature {verdict}; prediction "
            f"{settlement['rescued']} of {settlement['predicted']} rescued, p={settlement['p']:.2g}"
        )
        if (
            delta < gates["dev_min_delta"]
            or verdict != "present"
            or not settlement["held"]
            or self.confirm_budget_left() < gates["confirm_tasks"]
        ):
            return f"step {step}: candidate {candidate[:12]} stays in research ({reading})"
        self.record(
            "selection",
            {"role": "put_forward", "version": candidate, "dev_delta": delta},
        )
        return (
            f"step {step}: candidate {candidate[:12]} put forward ({reading}); "
            + self.confirm(candidate, incumbent)
        )

    def settled_verdict(self, candidate: str) -> str:
        """What the challenged analysis of this very candidate says of its signature, else unknown.
        The latest analysis may be about another experiment, or may have failed."""
        for body in self.insights():
            if body["status"] == "qualified" and body["experiment"] == candidate:
                return body["verdict"]
        return "unknown"

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

    def outcomes(self, run_dir: Path) -> dict[str, dict]:
        """Hidden tests by name: passed iff their last record says so, with the failure message
        (bounded); skipped tests are omitted. Keyed by name alone, so families group by the dotted
        name: in the campaigns read so far no name occurs on two branches, and a branch prefix
        would only break the dotted structure."""
        records = last_records(run_dir / "eval")
        return {
            name: {
                "passed": record["status"] == "passed",
                "message": trajectory.clip(
                    str((record.get("extra") or {}).get("message") or ""),
                    OUTCOME_MESSAGE_CAP,
                ),
            }
            for (_, name), record in records.items()
            if record["status"] != "skipped"
        }

    def items(self, run_dir: Path) -> dict[str, bool]:
        return {
            name: outcome["passed"] for name, outcome in self.outcomes(run_dir).items()
        }

    def task_tokens(self, task: str) -> set[str]:
        """The lowercase words that identify a task named owner__repo.commit, never the commit: its
        owner, its repository when that is distinctive (at least six characters or not plain
        letters and digits; a name like run, walk or dust is an ordinary word of policy text, which
        the owner and the full name still cover), and the full owner__repo. None is shorter than
        three characters."""
        owner, _, rest = task.partition("__")
        repo = rest.rsplit(".", 1)[0]
        tokens = {owner, f"{owner}__{repo}"}
        if len(repo) >= 6 or not repo.isalnum():
            tokens.add(repo)
        return {token.lower() for token in tokens if len(token) >= 3}

    def oracle_patterns(self) -> list[str]:
        """The reference program invoked, not merely mentioned: `executable` in command position,
        that is at the start of the text or after ; & | ( $( a quote, a newline (real or the
        JSON-escaped backslash-n) or a shell keyword (do then else in elif), optionally behind
        `exec`, `env`, `timeout <n>` or `VAR=x`. The candidate is also often built as ./executable
        in its own directory; the two cannot be told apart from the command text, and that
        ambiguity is inherent to this task family."""
        prefix = (
            r"(?:^|[;&|(\'\"\n]\s*|\\n\s*|\$\(\s*"
            r"|(?<![\w-])(?:do|then|else|elif|in)\s+)"
        )
        wrappers = r"(?:(?:exec|env)\s+|timeout\s+\S+\s+|\w+=\S*\s+)*"
        return [prefix + wrappers + r"(?:\./|/workspace/)executable\b"]

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


def last_records(eval_dir: Path) -> dict[tuple[str, str], dict]:
    """The last record of each hidden test, keyed by (branch, name), from the latest evaluation
    attempt. Missing directories, malformed files and records without a name or status yield
    nothing rather than an error."""
    paths = sorted(eval_dir.glob("attempt-*/*/*.eval.json"))
    if not paths:
        return {}
    try:
        results = json.loads(paths[-1].read_text()).get("test_results") or []
    except (OSError, ValueError, AttributeError):
        return {}
    return {
        (record.get("branch", ""), record["name"]): record
        for record in results
        if isinstance(record, dict) and record.get("name") and record.get("status")
    }


def failure_excerpt(eval_dir: Path, limit: int = 40) -> str:
    """The last record of each failing hidden test, bounded: development evidence only."""
    lines = []
    for (_, name), result in sorted(last_records(eval_dir).items()):
        if result["status"] not in ("passed", "skipped") and len(lines) < limit:
            message = (result.get("extra") or {}).get("message") or ""
            lines.append(
                f"{name.rsplit('.', 1)[-1]}: {message.splitlines()[0][:200] if message else result['status']}"
            )
    return "\n".join(lines) + ("\n" if lines else "")


def knowledge_problem(root: Path) -> str:
    """Why a knowledge directory is not acceptable, or an empty string: a real directory (a deleted
    or linked one would wipe the campaign's knowledge or pull in host paths), UTF-8 text files
    only, no links or special files, at most 512 KiB in total, so that it is distilled rather
    than dumped."""
    if root.is_symlink():
        return "knowledge/ is a link"
    if not root.is_dir():
        return "knowledge/ is missing"
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_symlink():
            return f"knowledge/{rel} is a link"
        if path.is_dir():
            continue
        if not path.is_file():
            return f"knowledge/{rel} is not a regular file"
        if not trajectory.utf8_text(path, KNOWLEDGE_CAP)[0]:
            return f"knowledge/{rel} is not UTF-8 text"
        total += path.stat().st_size
    if total > KNOWLEDGE_CAP:
        return f"knowledge holds {total} bytes, over 512 KiB"
    return ""


def verdict_problem(path: Path, pending: str) -> str:
    """Why verdict.json does not settle the pending experiment, or an empty string."""
    if path.is_symlink():
        return "verdict.json is a link"
    try:
        verdict = json.loads(path.read_text())
    except (OSError, ValueError):
        return "verdict.json is missing or not JSON"
    if not isinstance(verdict, dict) or verdict.get("signature") not in SIGNATURES:
        return "verdict.json has no signature of present, partial or absent"
    if str(verdict.get("experiment"))[:12] != pending[:12]:
        return f"verdict.json is not about the pending experiment {pending[:12]}"
    return ""


def hindsight_problem(path: Path, known: dict[str, set[str]]) -> str:
    """Why hindsight.json is not a credit table over items the runs have, or an empty string. Each
    cluster names a task, its failing items, how the information stood (CLASSES) and, for inputs
    never sent, where they could have come from (SOURCES)."""
    if path.is_symlink():
        return "hindsight.json is a link"
    try:
        table = json.loads(path.read_text())
    except (OSError, ValueError):
        return "hindsight.json is missing or not JSON"
    clusters = table.get("clusters") if isinstance(table, dict) else None
    if not isinstance(clusters, list):
        return "hindsight.json has no list of clusters"
    for n, cluster in enumerate(clusters, 1):
        if not isinstance(cluster, dict) or cluster.get("task") not in known:
            return f"hindsight cluster {n} names no observed task"
        items = cluster.get("items")
        if (
            not isinstance(items, list)
            or not items
            or not all(isinstance(item, str) and item in known[cluster["task"]] for item in items)
        ):
            return f"hindsight cluster {n} names items no run of {cluster['task']} has"
        if cluster.get("class") not in CLASSES:
            return f"hindsight cluster {n} has no class of {', '.join(CLASSES)}"
        if cluster["class"] == "never_sent" and cluster.get("source") not in SOURCES:
            return f"hindsight cluster {n} was never sent but has no source of {', '.join(SOURCES)}"
    return ""


def failure_mass(table: dict) -> list[str]:
    """README lines: the latest credit table summed by how the information stood."""
    mass: dict[tuple[str, str], tuple[int, set[str]]] = {}
    for cluster in table["clusters"]:
        key = (cluster["class"], cluster.get("source") or "-")
        items, tasks = mass.get(key, (0, set()))
        mass[key] = (items + len(cluster["items"]), tasks | {cluster["task"]})
    rows = sorted(mass.items(), key=lambda row: -row[1][0])
    return [
        "Where the failure mass sits (latest analysis, failing items by how the information stood):",
        "",
        "| class | source | items | tasks |",
        "|---|---|---|---|",
        *(f"| {c} | {s} | {n} | {len(t)} |" for (c, s), (n, t) in rows),
    ]


def delivery_problem(
    workspace: Path, document: str, pending: str | None, known: dict[str, set[str]]
) -> str:
    """Why an analyst's or challenger's delivery does not qualify, or an empty string: its document
    is not empty, its credit table and knowledge are acceptable, and with an experiment pending its
    verdict.json settles that experiment."""
    path = workspace / document
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.read_text(errors="replace").strip()
    ):
        return f"no {document} was delivered"
    if problem := hindsight_problem(workspace / "hindsight.json", known):
        return problem
    if problem := knowledge_problem(workspace / "knowledge"):
        return problem
    return verdict_problem(workspace / "verdict.json", pending) if pending else ""


def copy_knowledge(source: Path | None, dest: Path) -> None:
    """A copy of a knowledge directory; an empty directory when there is none (a campaign with
    neither seed nor analysis yet)."""
    if source is not None and source.is_dir():
        shutil.copytree(source, dest)
    else:
        dest.mkdir(parents=True)


def hand_over(analysis: Path, workspace: Path, pending: str | None) -> None:
    """The analyst's delivery, placed in the challenger's workspace."""
    shutil.copy(analysis / "ANALYSIS.md", workspace)
    shutil.copy(analysis / "hindsight.json", workspace)
    if pending:
        shutil.copy(analysis / "verdict.json", workspace)
    copy_knowledge(analysis / "knowledge", workspace / "knowledge")


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
    if args.knowledge and (problem := knowledge_problem(args.knowledge)):
        sys.exit(f"the seed knowledge is not acceptable: {problem}")
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
            "prediction_alpha": args.prediction_alpha,
        },
        "mutable": args.mutable,
        "adoption": args.adoption,
        "parallel": args.parallel,
        "task_deadline_secs": args.task_deadline_secs,
        "research_deadline_secs": args.research_deadline_secs,
        "analysis_deadline_secs": args.analysis_deadline_secs
        or args.research_deadline_secs,
    }
    camp.mkdir(parents=True)
    if args.knowledge:
        copy_knowledge(args.knowledge, camp / "knowledge-seed")
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
    # The sealed confirmation tasks stay sealed: only their count and commitment are shown.
    sealed_view = {"count": len(confirm), "commitment": store.digest("pool", confirm)}
    print(
        json.dumps(
            {"campaign": str(camp), "v0": v0, "dev": dev, "confirm": sealed_view},
            indent=2,
        )
    )


def cmd_step(args) -> None:
    host = Host(args.camp)
    for _ in range(args.count):
        print(host.step(), flush=True)


def cmd_analyze(args) -> None:
    """Runs the analysis that is due, with the latest research parent (the incumbent before any
    research)."""
    host = Host(args.camp)
    parents = [
        e["body"]["version"]
        for e in host.events("selection")
        if e["body"]["role"] == "research_parent"
    ]
    k = host.analyze(parents[-1] if parents else host.incumbent())
    body = host.insight(k)
    print(f"analysis {k}: {body['status']}, verdict {body['verdict']}")


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
                "prediction": {k: settled[k] for k in ("rescued", "predicted", "p", "held")}
                if (settled := host.settlement(vid))
                else None,
            }
        )
    knowledge = host.current_knowledge()
    proposals = knowledge / "proposals.md" if knowledge else None
    print(
        json.dumps(
            {
                "incumbent": incumbent[:12],
                "versions": rows,
                "confirm_tasks_left": host.confirm_budget_left(),
                "analyses": [
                    {
                        "k": body["k"],
                        "experiment": (body["experiment"] or "")[:12],
                        "verdict": body["verdict"],
                        "status": body["status"],
                    }
                    for body in host.insights()[-LATEST_ANALYSES:]
                ],
                "proposals": proposals.read_text().splitlines()[:PROPOSAL_LINES]
                if proposals and proposals.exists()
                else [],
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
    init.add_argument(
        "--prediction-alpha",
        type=float,
        default=0.01,
        help="how unlikely by chance a candidate's floor rescues must be for its prediction to hold",
    )
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
    init.add_argument(
        "--analysis-deadline-secs",
        type=int,
        help="the analyst's and the challenger's deadline (default: the research deadline)",
    )
    init.add_argument(
        "--knowledge",
        type=Path,
        help="a directory of UTF-8 text, at most 512 KiB, that seeds the campaign's knowledge",
    )
    step = sub.add_parser("step")
    step.add_argument("--camp", type=Path, required=True)
    step.add_argument("--count", type=int, default=1)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--camp", type=Path, required=True)
    adopt = sub.add_parser("adopt")
    adopt.add_argument("--camp", type=Path, required=True)
    adopt.add_argument("--version", required=True)
    status = sub.add_parser("status")
    status.add_argument("--camp", type=Path, required=True)
    args = parser.parse_args()
    {
        "init": cmd_init,
        "step": cmd_step,
        "analyze": cmd_analyze,
        "adopt": cmd_adopt,
        "status": cmd_status,
    }[args.command](args)


if __name__ == "__main__":
    main()
