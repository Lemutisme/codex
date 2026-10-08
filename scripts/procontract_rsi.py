#!/usr/bin/env python3
"""ProContract succession: the institution's side of recursive self-improvement.

A version is a policy bundle (executor.md, research.md, analyst.md, challenger.md, drafter.md,
prober.md, reviewer.md) run by one codex binary. Improving the method is an ordinary task whose
product may succeed the version that does the work (reach spec §5). This host stays outside every version's write authority: it
runs from its own checkout, holds the campaign ledger, chooses research parents, runs and measures
versions, and keeps every claim in the kernel through the store CLI.

  init     start a campaign: pools, budgets, gates; register v0 and adopt it as the first incumbent;
           with --instances, a stream instead: every instance once, in a committed random order
  stream   the next batch of a stream: run it with the current policy, then analyse, challenge and
           research, and the delivery becomes the policy of the batch after
  baseline run the root version once on every instance of a stream campaign, never shown to learning
  report   a stream against its baseline, paired by instance
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
Chance seldom rescues a family of such items, at a rate each task shows, so one run settles the
prediction, mechanically and from beyond the candidate's reach. A candidate is put forward only when
its signature is present, its prediction held and its development delta clears the gate.

Reach in practice:
- exploration (choosing a parent, putting a candidate forward) may use any information and needs no
  authority;
- adoption needs comparative support from beyond the candidate's reach: confirmation tasks that no
  research view and no earlier selection has read, run fresh for candidate and incumbent;
- a source read by a selection never certifies it again (exposure only accumulates).

A stream is test-time learning on the evaluation set itself (insight spec §14): each instance is run
once, by the policy current when its batch starts, and its hidden outcome is read only after that run,
as feedback after delivery. This ordering does not establish the absence of historical exposure;
stream scores are descriptive: a separate baseline campaign runs the root version on the same
instances, and the paired comparison is not causal certification of learning.

Every phase is resumable: runs are cached by directory, kernel commands are idempotent by key."""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_attribution as attribution
import procontract_comparison as comparison
import procontract_harness_program as harness_program
import procontract_outcomes as outcome_matrix
import procontract_release as release
import procontract_store as store
import procontract_succession as succession
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
# Before any evidence, one chance rescue in ten floor families: conservative, so early predictions
# need several rescues to hold. The same ten exposures weigh the pooled rate against a task's own.
PRIOR_RESCUE = (1, 10)
# A bytecode cache left by running a knowledge tool in place: never knowledge, never kept.
CACHE = "__pycache__"
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

Deliver ./EXPERIMENT.md (at most 32 KiB) with the sections {sections}. {prediction} No network is available. Tools:
python3, jq, grep, sed and awk are installed; rg is not.

If authorized in the editable files above, policy/harness.json is a pure convergence program
used by both task and research runs. Format: {{"schema":1,"when":predicate}}. Predicates are
{{"remaining_fraction_lte":[numerator,denominator]}}, {{"completed_turns_lte":integer}},
{{"repairs_used_gte":integer}}, {{"always":boolean}}, {{"all":[predicates]}},
{{"any":[predicates]}}, or {{"not":predicate}}. Keep it small and finite; no imports, external I/O or
budget changes are allowed. A true result requests bounded handoff guidance, not acceptance.
"""

PREDICT_ITEMS = """When you change a file that shapes how tasks are done ({task_files}), also deliver
./prediction.json, {{"rescue": {{"<task>": ["<item id>", ...]}}}}: the hidden items of development tasks
your change will make pass, chosen among those every stored run failed (the floor in
archive/tasks/<task>/outcomes.md), from several test families."""

PREDICT_CLASSES = """The next batch runs on tasks no run has seen, so no item can be named: state the
Prediction as the classes of the credit table (insight/*/hindsight.json) that will shrink in the next
batch's failures, and the Signature the next analysis will count there."""

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
PENDING_STREAM = (
    "Experiment {version} is pending: it set the policy of the latest batch, whose tasks no earlier run "
    "had seen. ./verdict.json must say whether its signature was present in that batch's trajectories."
)

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
        supplied = bundle_texts(bundle)
        files = {name: supplied.get(name, "") for name in BUNDLE_FILES}
        manifest = {
            "schema": 1,
            "binary": self.terms["codex_sha256"],
            "model": {"id": self.terms["model"], "effort": self.terms["effort"]},
            "bundle": {
                name: store.digest("bundle_file", text) for name, text in files.items()
            },
            "lineage": {"parent": parent, "proposed_by": proposed_by},
        }
        program = harness_program.load(bundle)
        if program is not None:
            manifest["harness"] = {
                "interpreter": harness_program.INTERPRETER,
                "sha256": program.digest,
            }
        vid = store.digest("version", manifest)
        target = self.version_dir(vid)
        if not target.exists():
            (target / "bundle").mkdir(parents=True)
            for name, text in files.items():
                (target / "bundle" / name).write_text(text)
            if program is not None:
                (target / "bundle" / harness_program.PROGRAM_FILE).write_bytes(
                    program.source
                )
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

    def validate_harness(
        self, vid: str, run_dir: Path | None = None, *, require_success: bool = True
    ) -> None:
        """Fail closed on source or activation drift, preserving a stop marker after execution."""
        marker = (
            run_dir / "harness-identity-failure.txt" if run_dir is not None else None
        )
        if marker is not None and marker.exists():
            raise RuntimeError(marker.read_text())
        version = self.versions()[vid]
        expected = version.get("harness")
        try:
            roles = bundle_texts(self.version_dir(vid) / "bundle")
            if set(roles) != set(BUNDLE_FILES) or any(
                store.digest("bundle_file", text) != version["bundle"][name]
                for name, text in roles.items()
            ):
                raise ValueError(
                    "version role files do not match their recorded identities"
                )
            program = harness_program.load(self.version_dir(vid) / "bundle")
            actual = (
                {"interpreter": harness_program.INTERPRETER, "sha256": program.digest}
                if program is not None
                else None
            )
            if actual != expected:
                raise ValueError("version bundle does not match its harness identity")
            if run_dir is not None:
                for name in ("manifest.json", "run.json"):
                    path = run_dir / name
                    if not path.exists() and (expected is None or not require_success):
                        continue  # Legacy runs did not carry program activation receipts.
                    summary = json.loads(path.read_text())
                    receipt = summary.get("harness_program")
                    actual = (
                        {key: receipt.get(key) for key in ("sha256", "interpreter")}
                        if isinstance(receipt, dict)
                        else None
                    )
                    if actual != expected:
                        raise ValueError(
                            f"{name} does not match the version's harness identity"
                        )
                    if (
                        require_success
                        and name == "run.json"
                        and runner_problem(summary)
                    ):
                        raise ValueError("the runner did not execute successfully")
        except (OSError, ValueError, AttributeError) as error:
            message = f"harness identity validation failed for {vid}: {error}"
            if marker is not None:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(message + "\n")
            raise RuntimeError(message) from error

    def measure(self, vid: str, task: str, purpose: str) -> dict:
        """Runs a version on one task and labels the result; cached by run directory."""
        limit = succession.task_attempt_limit(self.terms)
        self.validate_harness(vid)
        run_dir = self.camp / "runs" / f"{purpose}-{vid[:12]}-{task}"
        result_file = run_dir / "result.json"
        if list(run_dir.glob("attempt-*/harness-identity-failure.txt")):
            raise RuntimeError(
                "harness identity failure preserved; refusing another paid attempt"
            )
        # Invalid attempts consume their allowance too. Restarting never resets that budget.
        if result_file.exists():
            result = json.loads(result_file.read_text())
            if result["validity"] == "valid":
                self.validate_harness(vid, Path(result["run_dir"]))
            return succession.record_run(self, result)
        result = None
        run_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, limit + 1):
            attempt_dir = run_dir / f"attempt-{attempt}"
            receipt = run_dir / f"attempt-{attempt}.json"
            if receipt.exists():
                result = json.loads(receipt.read_text())
                self.validate_harness(
                    vid, attempt_dir, require_success=result["validity"] == "valid"
                )
            else:
                succession.receipt(
                    receipt,
                    {
                        "validity": "invalid",
                        "pass_rate": None,
                        "reason": "attempt interrupted before a terminal receipt",
                        "cost_unknown": True,
                    },
                )
                result = self.adapter.run_and_label(
                    self, self.version_dir(vid) / "bundle", task, attempt_dir
                )
                self.validate_harness(
                    vid, attempt_dir, require_success=result["validity"] == "valid"
                )
                succession.receipt(receipt, result)
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
        succession.receipt(result_file, result)
        return succession.record_run(self, result)

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
        while (
            (parent := versions[vid]["lineage"]["parent"]) is not None
            and versions[vid].get("harness") == versions[parent].get("harness")
            and all(
                versions[vid]["bundle"][name] == versions[parent]["bundle"][name]
                for name in TASK_FILES
            )
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
        """The valid runs the archive may show, by run name: every development run, every run of a
        stream (each read only after it ran), and every confirmation run of a spent task (a spent
        task never certifies again, so reading its runs costs nothing). Confirmation tasks not yet
        spent and baseline runs are never in it."""
        spent = set(self.used_confirmation_tasks())
        runs = {}
        for path in sorted((self.camp / "runs").glob("*/result.json")):
            result = json.loads(path.read_text())
            if result["validity"] == "valid" and (
                result["purpose"] in ("dev", "stream") or result["task"] in spent
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
        """The newest candidate measured on every development task, with its prediction settled, that
        no qualified analysis has yet settled: the experiment the next analysis must judge."""
        asked = {
            body["experiment"]
            for body in self.insights()
            if body["status"] == "qualified"
        }
        if self.stream:
            # The policy of the latest batch, when it changed how tasks are done since the batch before.
            policies = [batch["version"] for batch in self.batches()]
            changed = len(policies) > 1 and self.twin(policies[-1]) != self.twin(
                policies[-2]
            )
            return policies[-1] if changed and policies[-1] not in asked else None
        pending = None
        for event in self.events("selection"):
            body = event["body"]
            vid = body["version"]
            if (
                body["role"] == "qualified"
                and not body.get("method_only")
                and vid not in asked
                and len(self.dev_results(vid)) == len(self.terms["pools"]["dev"])
                and self.settlement(vid)
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
        recent = self.recent_runs()
        for name, result in runs.items():
            source = self.observe(name, result)
            if recent is None or name in recent:
                shutil.copytree(source, archive / "runs" / name)
            else:
                (archive / "runs" / name).mkdir(parents=True)
                for kept in ("summary.json", "outcomes.json", "failures.txt"):
                    shutil.copy(source / kept, archive / "runs" / name)
        self.write_outcomes(archive)
        self.write_attribution(archive)
        for body in self.insights():
            if body["status"] == "qualified":
                kept = self.camp / "insight" / str(body["k"])
                target = archive / "insight" / str(body["k"])
                target.mkdir(parents=True)
                for name in (
                    "ANALYSIS.md",
                    "CHALLENGE.md",
                    "hindsight.json",
                    "verdict.json",
                ):
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
        if self.stream:
            done = self.batches()
            lines += [
                "",
                f"Stream: {len(done)} of {self.batch_count()} batches run "
                f"({sum(len(batch['tasks']) for batch in done)} of {len(self.order())} "
                "tasks). Each task is run once, by the policy current when its batch began, and never "
                "again; the next batch runs on tasks no run has seen. Runs of the last "
                f"{self.terms['stream']['recent']} batches carry their trajectories and final "
                "workspaces; older runs keep their summary, outcomes and failures, and what was learned "
                "from them lives in knowledge/.",
            ]
            latest = self.latest_insight()
            if latest and (latest / "hindsight.json").exists():
                lines += [
                    "",
                    *failure_mass(json.loads((latest / "hindsight.json").read_text())),
                ]
            (archive / "README.md").write_text("\n".join([*lines, "", LAYOUT]) + "\n")
            return
        chance = self.chance(self.task_runs())
        per_task = ", ".join(
            f"{task} {t['rate']:.3f}" for task, t in sorted(chance["tasks"].items())
        )
        lines += [
            "",
            f"Chance rescue rate of a floor family: {chance['rate']:.3f} pooled ({chance['rescued']} of "
            f"{chance['exposed']} floor families passed in a held-out run, smoothed by a prior of "
            f"{PRIOR_RESCUE[0]} in {PRIOR_RESCUE[1]}); per task {per_task or 'none yet'}. A prediction "
            f"holds when chance alone would rarely rescue as many of its floor families as the candidate "
            f"does (p <= {self.terms['gates']['prediction_alpha']}).",
        ]
        latest = self.latest_insight()
        if latest and (latest / "hindsight.json").exists():
            lines += [
                "",
                *failure_mass(json.loads((latest / "hindsight.json").read_text())),
            ]
        (archive / "README.md").write_text("\n".join([*lines, "", LAYOUT]) + "\n")

    def task_runs(self) -> dict[str, list[dict]]:
        """Every observed run by task, as the outcome matrix reads them. A run's parent is the twin
        of its version's lineage parent, which is how the matrix draws lineage edges."""
        versions = self.versions()
        by_task: dict[str, list[dict]] = {}
        for name, result in self.observed().items():
            version = result["version"]
            parent = versions[version]["lineage"]["parent"]
            outcomes = json.loads(
                (self.observe(name, result) / "outcomes.json").read_text()
            )
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

    def chance(self, runs: dict[str, list[dict]]) -> dict:
        """The rate at which a floor family passes by chance, pooled and per task. Held-out runs
        against the floor of the others give the counts; the pooled rate is smoothed by PRIOR_RESCUE
        and each task's rate is its own counts weighed against the pooled rate, because tasks differ
        in noise by an order of magnitude."""
        counts = outcome_matrix.chance_rescues(runs)
        rescued = sum(r for r, _ in counts.values())
        exposed = sum(e for _, e in counts.values())
        rate = (rescued + PRIOR_RESCUE[0]) / (exposed + PRIOR_RESCUE[1])
        weight = PRIOR_RESCUE[1]
        return {
            "rate": rate,
            "rescued": rescued,
            "exposed": exposed,
            "tasks": {
                task: {
                    "rescued": r,
                    "exposed": e,
                    "rate": (r + rate * weight) / (e + weight),
                }
                for task, (r, e) in sorted(counts.items())
            },
        }

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
        returns the workspace it leaves. A durable claim precedes every paid launch. Recovery
        never relaunches a claimed attempt: without a trustworthy terminal receipt or a recorded
        exit it remains unreconciled, not stopped or failed. A later terminal receipt can settle
        that same claim. A failed prepare starts no agent and remains retryable."""
        run_dir = root / "run"
        ended = root / "ended-without-run-json"
        failed = root / "runner-failed.json"
        claim_path = root / "launch-claim.json"
        exit_path = root / "launch-exit.json"
        preparation = root / "prepare-only.json"
        self.validate_harness(parent)
        prompt = harness_program.read_regular(root / "prompt.md", MAX_BUNDLE_FILE)
        identity = {
            "parent": parent,
            "instance": instance,
            "instructions": instructions,
            "model": self.terms["model"],
            "effort": self.terms["effort"],
            "harness": self.versions()[parent].get("harness"),
            "binary": self.terms["codex_sha256"],
            "runner": self.runner,
            "image": self.terms["research_image"],
            "deadline_secs": deadline,
            "prompt": hashlib.sha256(prompt).hexdigest()
            if prompt is not None
            else None,
            "input": store.capture(self.store, root / "workspace", [])["subject_hash"]
            if (root / "workspace").is_dir()
            else None,
        }
        claim = None
        if claim_path.exists():
            try:
                claim = json.loads(claim_path.read_text())
                prepared = harness_program.read_regular(
                    run_dir / "manifest.json", MAX_BUNDLE_FILE
                )
                if (
                    type(claim["schema"]) is not int
                    or claim["schema"] != 1
                    or claim["identity"] != identity
                    or claim["prepared_manifest"]
                    != (
                        hashlib.sha256(prepared).hexdigest()
                        if prepared is not None
                        else None
                    )
                ):
                    raise ValueError("inputs changed")
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError(
                    "learning launch inputs changed or claim is unreadable; preserving the attempt"
                ) from error
        if (run_dir / "harness-identity-failure.txt").exists():
            self.validate_harness(parent, run_dir)
        if (
            not (run_dir / "run.json").exists()
            and not ended.exists()
            and not failed.exists()
            and claim is None
        ):
            if run_dir.exists() and any(run_dir.iterdir()) and not preparation.exists():
                raise RuntimeError(
                    "unreconciled legacy learning directory: no claim or trusted prepare-only "
                    "record; process state and cost remain unknown"
                )
            if preparation.exists() and json.loads(preparation.read_text()) != identity:
                raise RuntimeError(
                    "learning preparation inputs changed; preserving the attempt"
                )
            succession.receipt(preparation, identity)
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
                "--model",
                self.terms["model"],
                "--effort",
                self.terms["effort"],
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
            prepared = harness_program.read_regular(
                run_dir / "manifest.json", MAX_BUNDLE_FILE
            )
            claim = {
                "schema": 1,
                "identity": identity,
                "prepared_manifest": hashlib.sha256(prepared).hexdigest()
                if prepared is not None
                else None,
            }
            # Exclusive creation also leaves a blocking claim if the writer dies mid-write.
            with claim_path.open("x", encoding="utf-8") as handle:
                json.dump(claim, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            preparation.unlink()
            if os.name == "posix":
                directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            run = common + ["--deadline-secs", str(deadline)]
            completed = subprocess.run([*self.runner, "run", *run], check=False)
            succession.receipt(
                exit_path,
                {
                    "claim": store.digest("learning_launch", claim),
                    "returncode": completed.returncode,
                },
            )
            if completed.returncode:
                succession.receipt(
                    failed,
                    {"reason": "runner failed", "returncode": completed.returncode},
                )
            if not (run_dir / "run.json").exists():
                ended.write_text("the run ended without run.json\n")
        exited = None
        if claim is not None and exit_path.exists():
            try:
                exited = json.loads(exit_path.read_text())
                if (
                    exited["claim"] != store.digest("learning_launch", claim)
                    or type(exited["returncode"]) is not int
                ):
                    raise ValueError("exit belongs to another launch")
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError(
                    "unreconciled learning launch: invalid exit receipt"
                ) from error
            if exited["returncode"] and not failed.exists():
                succession.receipt(
                    failed,
                    {"reason": "runner failed", "returncode": exited["returncode"]},
                )
        if not failed.exists():
            terminal = False
            try:
                summary = json.loads((run_dir / "run.json").read_text())
                problem = runner_problem(summary)
                terminal = bool(problem) or (
                    isinstance(summary.get("turn_statuses"), list)
                    and bool(summary["turn_statuses"])
                    and summary["turn_statuses"][-1]
                    in ("completed", "interrupted", "failed")
                )
            except (OSError, ValueError, AttributeError):
                problem = "runner ended without a readable terminal receipt"
            if claim is not None and not terminal:
                if exited is None:
                    raise RuntimeError(
                        "unreconciled learning launch: process state and cost remain unknown; "
                        "preserving the claim and workspace without relaunching"
                    )
                problem = "runner exited without a trustworthy terminal receipt"
            if problem:
                succession.receipt(failed, {"reason": problem})
            else:
                self.validate_harness(parent, run_dir)
        if failed.exists():
            self.validate_harness(parent, run_dir, require_success=False)
        return run_dir / "workspace"

    def analyze(self, parent: str) -> int:
        """The analysis that covers every valid run stored now: the latest when the set of runs has
        not grown since and it qualified, otherwise a new one (a failed analysis is tried again on
        the next call, with the same experiment pending). An analyst explains the outcomes and
        settles the pending experiment; a challenger tries to defeat that; only a challenged
        delivery that qualifies becomes the campaign's, else the failure is recorded, the knowledge
        stays and the verdict is unknown. Each stage may retry once; finished runs are never run
        again."""
        self.validate_harness(parent)
        observed = self.observed()
        coverage = sorted(observed)
        previous = self.current_knowledge()
        knowledge = knowledge_identity(previous)
        pending = self.pending_experiment()
        identity = {
            "parent": parent,
            "coverage": coverage,
            "experiment": pending,
            "evidence": store.digest("analysis_evidence", observed),
            "protocol": store.digest(
                "analysis_protocol",
                [ANALYST_PROTOCOL, CHALLENGER_PROTOCOL, PENDING, PENDING_STREAM],
            ),
        }
        done = self.insights()
        prior_identity = dict(done[-1].get("analysis_identity", {})) if done else {}
        if pending is None:
            # A qualified verdict consumes its pending experiment, not the request's evidence.
            prior_identity["experiment"] = None
        if (
            done
            and done[-1]["status"] == "qualified"
            and prior_identity == identity
            and done[-1].get("knowledge_digest") == knowledge
        ):
            # The latest output is now current knowledge; it is not a new analysis input.
            return done[-1]["k"]
        k = len(done) + 1
        root = self.camp / "insight" / str(k)
        marker = root / "coverage.json"
        inputs = {**identity, "prior_knowledge": knowledge}
        if marker.exists() and json.loads(marker.read_text()) != inputs:
            raise RuntimeError(
                f"analysis {k} inputs changed; preserving its spent attempts at {root}"
            )
        root.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(inputs))
        note = (
            (PENDING_STREAM if self.stream else PENDING).format(version=pending[:12])
            if pending
            else NOT_PENDING
        )
        failing = {
            task: outcome_matrix.failed_items(runs)
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
            failing,
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
                failing,
                lambda partial: hand_over(analysis, partial, pending),
                "CHALLENGE.md",
            )
        body = {
            "k": k,
            "coverage": coverage,
            "analysis_identity": identity,
            "prior_knowledge": knowledge,
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
            body["knowledge_digest"] = knowledge_identity(root / "knowledge")
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
        failing: dict[str, set[str]],
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
            failure = base / "runner-failed.json"
            reason = (
                json.loads(failure.read_text())["reason"]
                if failure.exists()
                else delivery_problem(delivery, document, pending, failing)
            )
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
            prediction=PREDICT_CLASSES
            if self.stream
            else PREDICT_ITEMS.format(task_files=", ".join(TASK_FILES)),
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

    def research_failure(self, step: int) -> str | None:
        """Only the trusted runner's receipt, never a candidate-authored failure marker."""
        path = self.camp / "research" / f"step-{step}" / "runner-failed.json"
        return json.loads(path.read_text())["reason"] if path.exists() else None

    def qualify(self, delivery: Path, parent: str) -> tuple[bool, str, bool]:
        """Mechanical, complete criterion: an experiment record with every section, a bundle
        changed only within the campaign's mutable files, and task-shaping files that name no task
        the campaign has exposed. Returns (qualified, reason, changed)."""
        try:
            text = experiment_text(delivery)
        except ValueError as error:
            return False, f"invalid EXPERIMENT.md: {error}", False
        if not text.strip():
            return False, "no EXPERIMENT.md was delivered", False
        missing = [
            section
            for section in EXPERIMENT_SECTIONS
            if section.lower() not in text.lower()
        ]
        if missing:
            return False, f"EXPERIMENT.md lacks {', '.join(missing)}", False
        policy = delivery / "policy"
        try:
            files = bundle_texts(policy)
        except ValueError as error:
            return False, f"invalid policy bundle: {error}", False
        extra = (
            sorted(
                p.name
                for p in policy.iterdir()
                if p.name not in [*BUNDLE_FILES, harness_program.PROGRAM_FILE]
            )
            if policy.is_dir()
            else ["(missing policy/)"]
        )
        if extra:
            return (
                False,
                f"the bundle gained files outside the protocol: {', '.join(extra)}",
                False,
            )
        try:
            program = harness_program.load(policy)
        except ValueError as error:
            return False, f"invalid harness program: {error}", False
        parent_bundle = self.version_dir(parent) / "bundle"
        before_files = bundle_texts(parent_bundle)
        before_program = harness_program.load(parent_bundle)
        changed = []
        for name in [*BUNDLE_FILES, harness_program.PROGRAM_FILE]:
            if name == harness_program.PROGRAM_FILE:
                new = program.source if program is not None else b""
                before = before_program.source if before_program is not None else b""
            else:
                new, before = files.get(name, ""), before_files.get(name, "")
            if new != before:
                changed.append(name)
        outside = [name for name in changed if name not in self.terms["mutable"]]
        if outside:
            return (
                False,
                f"changed files the campaign does not allow: {', '.join(outside)}",
                False,
            )
        if leak := self.boundary(files, changed):
            return False, leak, False
        if (
            not self.stream
            and any(
                name in [*TASK_FILES, harness_program.PROGRAM_FILE] for name in changed
            )
            and (problem := self.prediction_problem(delivery / "prediction.json"))
        ):
            return False, problem, False
        return (
            True,
            "qualified" if changed else "a null experiment: the bundle is unchanged",
            bool(changed),
        )

    def prediction_problem(self, path: Path) -> str:
        """Why prediction.json cannot be settled by the candidate's runs, or an empty string. It
        names, per development task, hidden items the change will make pass. Only items on the floor
        count, where chance is quiet, and a family of them is one chance event, so even rescuing every
        one must be unlikely enough by chance alone for a single run to decide it."""
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
        for task, items in rescue.items():
            if task not in self.terms["pools"]["dev"]:
                return f"prediction.json names {task}, which is not a development task"
            known = {item for run in runs.get(task, []) for item in run["outcomes"]}
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item in known for item in items
            ):
                return f"prediction.json names items no run of {task} has"
        rates = self.rates(self.claims(rescue, runs), self.chance(runs))
        if not rates:
            return "none of the predicted items is failed by every stored run, so no run can decide the prediction"
        alpha = self.terms["gates"]["prediction_alpha"]
        if (p := outcome_matrix.rescue_tail(rates, len(rates))) > alpha:
            return (
                f"the predicted floor items fall in {len(rates)} test families, and chance alone "
                f"rescues them all with probability {p:.3f} > {alpha}: name floor items of more families"
            )
        return ""

    @staticmethod
    def claims(
        rescue: dict, runs: dict[str, list[dict]]
    ) -> dict[str, dict[str, list[str]]]:
        """The floor items a prediction names, per task and test family; items off the floor are
        dropped, for chance rescues them often."""
        claims = {
            task: outcome_matrix.by_family(
                set(items) & set(outcome_matrix.floor(runs.get(task, [])))
            )
            for task, items in sorted(rescue.items())
        }
        return {task: families for task, families in claims.items() if families}

    @staticmethod
    def rates(claims: dict, chance: dict) -> list[float]:
        """The chance of rescuing each claimed family: its task's rate, else the pooled one."""
        return [
            chance["tasks"].get(task, chance)["rate"]
            for task, families in claims.items()
            for _ in families
        ]

    def predict(self, candidate: str, delivery: Path) -> str:
        """Registers the candidate's prediction as a contract before any of its runs exist: the
        floor families it names and the chance rates are frozen in the terms, so the outcome cannot
        shape the claim."""
        contract = f"prediction.{candidate[:16]}"
        shutil.copy(delivery / "prediction.json", self.version_dir(candidate))
        rescue = json.loads((delivery / "prediction.json").read_text())["rescue"]
        runs = self.task_runs()
        self.issue(
            contract,
            {
                "experiment": candidate,
                "rescue": self.claims(rescue, runs),
                "chance": self.chance(runs),
                "alpha": self.terms["gates"]["prediction_alpha"],
            },
            {"class": "rescue", "rule": "tail of rescued floor families <= alpha"},
            "delegate",
        )
        return contract

    def settle(self, candidate: str) -> dict:
        """Settles the candidate's prediction from its development runs, mechanically: the hidden
        outcomes come from beyond its reach, and the rule was frozen before they existed. A frozen
        family is rescued when its runs pass any of its items; the prediction holds when chance
        alone would rarely rescue as many families, and is defeated otherwise. A task without a
        valid run leaves its families unrescued and the settlement void: the claim is not held on
        a subset that infrastructure chose."""
        contract = f"prediction.{candidate[:16]}"
        if settled := self.settlement(candidate):
            return settled
        terms = next(
            event["body"]["terms"]
            for event in self.events("issue")
            if event["body"]["contract_id"] == contract
        )
        runs = self.dev_runs(candidate)
        outcomes = {
            run["name"]: run["outcomes"]
            for group in self.task_runs().values()
            for run in group
        }
        tasks = {}
        for task, families in terms["rescue"].items():
            if task in runs:
                passed = outcomes[Path(runs[task]["run_dir"]).parent.name]
                tasks[task] = {
                    "predicted": len(families),
                    "rescued": sorted(
                        name
                        for name, items in families.items()
                        if any(passed.get(item, {}).get("passed") for item in items)
                    ),
                }
        void = sorted(set(terms["rescue"]) - set(tasks))
        rates = self.rates(terms["rescue"], terms["chance"])
        n = len(rates)
        k = sum(len(t["rescued"]) for t in tasks.values())
        p = outcome_matrix.rescue_tail(rates, k)
        settlement = {
            "experiment": candidate,
            "predicted": n,
            "rescued": k,
            "expected_by_chance": round(sum(rates), 3),
            "p": p,
            "alpha": terms["alpha"],
            "held": not void and p <= terms["alpha"],
            "void": void,
            "tasks": tasks,
        }
        reading = f"{k} of {n} floor families rescued, {sum(rates):.2f} expected by chance, p={p:.2g}"
        if void:
            reading = f"void, no valid run of {', '.join(void)}: {reading}"
        self.propose(
            contract,
            store.digest("runs", {task: runs[task]["run_dir"] for task in tasks}),
        )
        if settlement["held"]:
            self.support(contract, settlement, {"runs": sorted(tasks)}, "beyond")
            self.discharge(contract, self.presumed(), reading)
        else:
            self.release(contract, reading)
        (self.version_dir(candidate) / "settlement.json").write_text(
            json.dumps(settlement, indent=2) + "\n"
        )
        return settlement

    def settlement(self, vid: str) -> dict | None:
        """The host's settlement of a version's prediction, once it exists."""
        path = self.version_dir(vid) / "settlement.json"
        return json.loads(path.read_text()) if path.exists() else None

    def exposed_tasks(self) -> list[str]:
        """Tasks some view or selection has read: the development pool, the spent confirmation tasks
        and the tasks a stream has run."""
        streamed = [task for batch in self.batches() for task in batch["tasks"]]
        return [*self.terms["pools"]["dev"], *self.used_confirmation_tasks(), *streamed]

    def boundary(self, files: dict[str, str], changed: list[str]) -> str:
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
        for name in (name for name in changed if name in TASK_FILES and name in files):
            text = files[name]
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
        if not resuming and (candidate := self.unsettled()) is not None:
            return self.measure_candidate(last["step"], candidate)
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
        if failure := self.research_failure(step):
            self.release(improvement, failure)
            return f"step {step}: research failed ({failure}); the policy stays"
        try:
            experiment = experiment_text(delivery)
        except ValueError:
            experiment = ""  # Qualification records the rejection; never read through a bad path.
        ok, reason, changed = self.qualify(delivery, parent)
        subject = delivery_subject(delivery, experiment)
        self.propose(improvement, subject)
        if not ok:
            self.release(improvement, reason)
            return f"step {step}: research by {parent[:12]} did not qualify: {reason}"
        # The criterion is mechanical and complete, so the checks reach everything it asks. The
        # candidate and its prediction come before the discharge, so a host that stops in between
        # resumes here, where nothing has run; after it, a candidate resumes by its prediction.
        candidate = (
            self.register(delivery / "policy", parent, parent, experiment)
            if changed
            else None
        )
        method_only = candidate is not None and self.twin(candidate) != candidate
        if candidate and not method_only:
            self.predict(candidate, delivery)
        self.support(
            improvement, {"qualification": reason}, {"delivery": subject}, "beyond"
        )
        self.discharge(improvement, self.presumed(), reason)
        if not changed:
            return f"step {step}: {reason}"
        if method_only:
            # Only the research method changed: its tasks are its ancestor's by construction, so
            # nothing is measured and nothing is put forward; it shows its worth in its successors.
            self.record(
                "selection",
                {"role": "qualified", "version": candidate, "method_only": True},
            )
            return f"step {step}: candidate {candidate[:12]} changes only the research method; it continues in research"
        return self.measure_candidate(step, candidate)

    def unsettled(self) -> str | None:
        """A candidate whose prediction is registered and neither settled nor released: a host that
        stopped while measuring it resumes there."""
        for vid in self.versions():
            state = self.contract(f"prediction.{vid[:16]}")
            if state is not None and state["standing"] == "outstanding":
                return vid
        return None

    def measure_candidate(self, step: int, candidate: str) -> str:
        """Measures a candidate whose prediction is registered: its mechanism witness, its
        development runs, then both settlements, and the decision to put it forward."""
        parent = self.versions()[candidate]["lineage"]["parent"]
        witness = self.adapter.witness(self, candidate)
        if witness:
            self.release(f"prediction.{candidate[:16]}", witness)
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
            f"{settlement['rescued']} of {settlement['predicted']} families rescued, "
            f"p={settlement['p']:.2g}{' (void)' if settlement['void'] else ''}"
        )
        if (
            delta < gates["dev_min_delta"]
            or verdict != "present"
            or not settlement["held"]
            or self.confirm_budget_left() < gates["confirm_tasks"]
        ):
            return (
                f"step {step}: candidate {candidate[:12]} stays in research ({reading})"
            )
        self.record(
            "selection",
            {"role": "put_forward", "version": candidate, "dev_delta": delta},
        )
        return (
            f"step {step}: candidate {candidate[:12]} put forward ({reading}); "
            + self.confirm(candidate, incumbent)
        )

    # ---- the stream ---------------------------------------------------------------------------

    @property
    def stream(self) -> bool:
        return "stream" in self.terms

    def batches(self) -> list[dict]:
        """The batches a stream has run, in order: their number, policy and tasks (recorded as the
        assignment of those tasks to that policy)."""
        return [e["body"] for e in self.events("assignment") if "batch" in e["body"]]

    def order(self) -> list[str]:
        """The stream's instances in their committed order, less those a correction excluded (an
        instance found not to be part of the benchmark). Removing an element from a random
        permutation leaves a random permutation of the rest."""
        excluded = {
            event["body"]["exclude"]
            for event in self.events("correction")
            if "exclude" in event["body"]
        }
        return [task for task in self.terms["stream"]["order"] if task not in excluded]

    def batch_count(self) -> int:
        size = self.terms["stream"]["batch"]
        return -(-len(self.order()) // size)

    def recent_runs(self) -> set[str] | None:
        """In a stream, the runs of the last few batches: the ones a view shows in full. Everything
        in a campaign is recent."""
        if not self.stream:
            return None
        recent = self.batches()[-self.terms["stream"]["recent"] :]
        return {
            f"stream-{b['version'][:12]}-{task}" for b in recent for task in b["tasks"]
        }

    def stream_policy(self) -> str:
        """The policy the next batch runs with: the latest qualified delivery, else the root."""
        policies = [
            event["body"]["version"]
            for event in self.events("selection")
            if event["body"]["role"] == "stream_policy"
        ]
        return policies[-1] if policies else self.incumbent()

    def learned(self, b: int) -> bool:
        """Whether a stream has finished learning from batch b: its research was settled, or, after
        the last batch, an analysis covers every run."""
        if b == self.batch_count():
            done = self.insights()
            runs = {
                name
                for name, run in self.observed().items()
                if run["purpose"] == "stream"
            }
            return (
                bool(done)
                and done[-1]["status"] == "qualified"
                and runs <= set(done[-1]["coverage"])
            )
        state = self.contract(f"improvement.{b}")
        return state is not None and state["standing"] != "outstanding"

    def stream_step(self) -> str:
        """The next unit of a stream: learning from the latest batch when that is unfinished, else the
        next batch, run with the current policy on tasks no run has seen, then learning from it."""
        if outcome := release.advance(self):
            return outcome
        done = self.batches()
        if done and not self.learned(len(done)):
            outcome = self.learn(len(done))
            return outcome + (
                f"; {result}" if (result := release.advance(self)) else ""
            )
        b = len(done) + 1
        if b > self.batch_count():
            return "the stream is complete"
        size = self.terms["stream"]["batch"]
        tasks = self.order()[(b - 1) * size : b * size]
        policy = self.stream_policy()
        self.record("assignment", {"batch": b, "version": policy, "tasks": tasks})
        outcome = self.learn(b)
        return outcome + (f"; {result}" if (result := release.advance(self)) else "")

    def learn(self, b: int) -> str:
        """What a stream learns from batch b: an analysis of the runs so far, which also counts the
        signature of the change that set this batch's policy, then research whose qualified delivery
        sets the next batch's policy. Choosing a policy is exploration and needs no authority: the
        next batch measures it out of sample; baseline comparisons are descriptive, not causal
        certification of the learning method."""
        policy = self.batches()[b - 1]["version"]
        self.measure_all(
            [(policy, task) for task in self.batches()[b - 1]["tasks"]], "stream"
        )
        mean_rate = mean(
            r["pass_rate"]
            for r in self.observed().values()
            if r["version"] == policy and r["task"] in self.batches()[b - 1]["tasks"]
        )
        if b == self.batch_count():
            k = self.analyze(policy)
            status = self.insight(k)["status"]
            outcome = (
                "the stream is complete"
                if status == "qualified"
                else "analysis failed; no update"
            )
            return f"batch {b} (policy {policy[:12]}, mean {mean_rate:.3f}): {outcome}; analysis {k} {status}"
        improvement = f"improvement.{b}"
        self.issue(
            improvement,
            {
                "campaign": self.campaign_hash(),
                "parent": policy,
                "protocol": RESEARCH_PROTOCOL,
            },
            {
                "class": "qualification",
                "sections": EXPERIMENT_SECTIONS,
                "mutable": self.terms["mutable"],
            },
            "delegate",
        )
        k = self.analyze(policy)
        if self.insight(k)["status"] != "qualified":
            return f"batch {b}: analysis failed; knowledge and policy stay unchanged"
        delivery = self.research(policy, b)
        if failure := self.research_failure(b):
            self.release(improvement, failure)
            return f"batch {b}: research failed ({failure}); the policy stays"
        try:
            experiment = experiment_text(delivery)
        except ValueError:
            experiment = ""
        ok, reason, changed = self.qualify(delivery, policy)
        subject = delivery_subject(delivery, experiment)
        self.propose(improvement, subject)
        head = f"batch {b} (policy {policy[:12]}, mean {mean_rate:.3f})"
        if not ok:
            self.release(improvement, reason)
            return f"{head}: research did not qualify ({reason}); the policy stays"
        candidate = (
            self.register(delivery / "policy", policy, policy, experiment)
            if changed
            else None
        )
        self.support(
            improvement, {"qualification": reason}, {"delivery": subject}, "beyond"
        )
        self.discharge(improvement, self.presumed(), reason)
        if candidate is None:
            return f"{head}: {reason}; the policy stays"
        self.record(
            "selection", {"role": "stream_policy", "version": candidate, "batch": b + 1}
        )
        return f"{head}: batch {b + 1} runs with {candidate[:12]}"

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
        exposed = [
            task
            for event in self.events("exposure")
            if event["body"]["view"].startswith("confirmation:")
            for task in event["body"]["sources"]
        ]
        reserved = [
            task
            for event in self.events("assignment")
            if "confirmation" in event["body"]
            for task in event["body"]["tasks"]
        ]
        return list(dict.fromkeys([*reserved, *exposed]))

    def confirm_budget_left(self) -> int:
        return len(self.terms["pools"]["confirm"]) - len(self.used_confirmation_tasks())

    def confirm(self, candidate: str, incumbent: str) -> str:
        return succession.confirm(self, candidate, incumbent)

    def adopt(self, candidate: str, presumed: bool = False) -> str:
        return succession.adopt(self, candidate, presumed)


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

        self.await_images(task)
        common = ["--arm", "on", "--instance", task, "--run-dir", str(run_dir)]
        common += [
            "--codex-bin",
            self.terms["codex_bin"],
            "--model",
            self.terms["model"],
            "--effort",
            self.terms["effort"],
        ]
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
        completed = subprocess.run(
            [
                *host.runner,
                "run",
                *common,
                "--deadline-secs",
                str(self.terms["task_deadline_secs"]),
            ],
            check=False,
        )
        try:
            summary = json.loads((run_dir / "run.json").read_text())
            problem = runner_problem(summary)
        except (OSError, ValueError, AttributeError):
            summary, problem = {}, "runner ended without a readable terminal receipt"
        if completed.returncode or problem:
            return {
                "validity": "invalid",
                "reason": problem or "runner exited with a nonzero status",
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
        compact(run_dir)
        rate = (outcome.get("outcome") or {}).get("pass_rate")
        return {
            "validity": outcome["validity"],
            "pass_rate": rate,
            "status": summary.get("status"),
            "cost": summary.get("cost"),
            "failures": failure_excerpt(run_dir / "eval"),
            "label": label,
        }

    @staticmethod
    def await_images(task: str, poll_secs: int = 60) -> None:
        """Waits until both images a run needs are local: the cleanroom the executor works in and the
        task image the evaluator runs. A run started without them would end invalid, and a stream
        never runs an instance twice; the operator's pull fills them in, in the stream's order."""
        base = f"programbench/{task.replace('__', '_1776_')}"
        while any(
            subprocess.run(
                ["docker", "image", "inspect", f"{base}:{tag}"], capture_output=True
            ).returncode
            for tag in ("task_cleanroom", "task")
        ):
            time.sleep(poll_secs)

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
        try:
            host.validate_harness(vid, run_dir)
        except RuntimeError as error:
            return str(error)
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
        if executor and not executor_delivered(executor, run_dir):
            return "the executor did not receive the candidate's executor.md"
        return ""


def compact(run_dir: Path) -> None:
    """Compresses a labelled run's bulky logs: the app-server's protocol log and codex's log
    database, which no analysis reads (trajectories come from the session rollouts). Lossless, so a
    debugging session can still read them; it keeps a long stream within the disk."""
    for path in [
        run_dir / "app-server.jsonl",
        *(run_dir / "codex-home").glob("logs_*.sqlite*"),
    ]:
        if path.is_file():
            subprocess.run(["gzip", "-f", str(path)], check=False)


def executor_delivered(executor: str, run_dir: Path) -> bool:
    """Whether a run's rollouts carry the head of the executor instructions. Rollouts keep non-ASCII
    text as UTF-8, so the needle must not escape it: an en dash once made a delivered executor.md
    look undelivered."""
    needle = json.dumps(executor[:200], ensure_ascii=False)[1:-1]
    return any(
        needle in path.read_text(errors="replace")
        for path in (run_dir / "codex-home" / "sessions").rglob("*.jsonl")
    )


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
        if CACHE in rel.parts:
            continue
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


def delivery_subject(delivery: Path, experiment: str) -> str:
    """The content a research delivery is judged on: its experiment record and its bundle."""
    bundle = delivery / "policy"
    try:
        files = bundle_texts(bundle)
    except ValueError as error:
        files = {"invalid_bundle": str(error)}
    try:
        program = harness_program.load(bundle)
    except ValueError as error:
        # Qualification rejected it; do not follow a rejected link or open a special file.
        files[harness_program.PROGRAM_FILE] = {"invalid": str(error)}
    else:
        if program is not None:
            files[harness_program.PROGRAM_FILE] = program.source.decode("utf-8")
    return store.digest(
        "delivery",
        {
            "experiment": experiment,
            "bundle": files,
        },
    )


def hindsight_problem(path: Path, failing: dict[str, set[str]]) -> str:
    """Why hindsight.json is not a credit table over failing items, or an empty string. Each cluster
    names a task, items some run of it failed (each in one cluster only, or the mass is counted
    twice), how the information stood (CLASSES) and, for inputs never sent, where they could have
    come from (SOURCES)."""
    if path.is_symlink():
        return "hindsight.json is a link"
    try:
        table = json.loads(path.read_text())
    except (OSError, ValueError):
        return "hindsight.json is missing or not JSON"
    clusters = table.get("clusters") if isinstance(table, dict) else None
    if not isinstance(clusters, list):
        return "hindsight.json has no list of clusters"
    seen: set[tuple[str, str]] = set()
    for n, cluster in enumerate(clusters, 1):
        task = cluster.get("task") if isinstance(cluster, dict) else None
        if not isinstance(task, str) or task not in failing:
            return f"hindsight cluster {n} names no observed task"
        items = cluster.get("items")
        if (
            not isinstance(items, list)
            or not items
            or not all(
                isinstance(item, str) and item in failing[task] for item in items
            )
        ):
            return f"hindsight cluster {n} names items no run of {task} failed"
        claimed = {(task, item) for item in items}
        if len(claimed) < len(items) or claimed & seen:
            return f"hindsight cluster {n} names an item another cluster has"
        seen |= claimed
        if cluster.get("class") not in CLASSES:
            return f"hindsight cluster {n} has no class of {', '.join(CLASSES)}"
        source = cluster.get("source")
        if source is not None and not isinstance(source, str):
            return f"hindsight cluster {n} has a source that is not text"
        if cluster["class"] == "never_sent" and source not in SOURCES:
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
    workspace: Path, document: str, pending: str | None, failing: dict[str, set[str]]
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
    if problem := hindsight_problem(workspace / "hindsight.json", failing):
        return problem
    if problem := knowledge_problem(workspace / "knowledge"):
        return problem
    return verdict_problem(workspace / "verdict.json", pending) if pending else ""


def copy_knowledge(source: Path | None, dest: Path) -> None:
    """A copy of a knowledge directory; an empty directory when there is none (a campaign with
    neither seed nor analysis yet)."""
    if source is not None and source.is_dir():
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns(CACHE))
    else:
        dest.mkdir(parents=True)


def knowledge_identity(root: Path | None) -> str:
    """Content identity, independent of where a qualified knowledge snapshot was copied."""
    if root is not None and (problem := knowledge_problem(root)):
        raise ValueError(problem)
    files = (
        {
            path.relative_to(root).as_posix(): path.read_text()
            for path in sorted(root.rglob("*"))
            if CACHE not in path.relative_to(root).parts and path.is_file()
        }
        if root is not None
        else {}
    )
    return store.digest("knowledge", files)


def bundle_texts(bundle: Path) -> dict[str, str]:
    """Read only bounded regular role files; a candidate cannot redirect Host reads."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("policy must be a directory, not a link")
    texts = {}
    for name in BUNDLE_FILES:
        raw = harness_program.read_regular(bundle / name, MAX_BUNDLE_FILE)
        if raw is not None:
            try:
                texts[name] = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError(f"{name} is not UTF-8") from error
    return texts


def experiment_text(delivery: Path) -> str:
    """The bounded, non-linked experiment record, or an empty string when absent."""
    raw = harness_program.read_regular(delivery / "EXPERIMENT.md", MAX_BUNDLE_FILE)
    return raw.decode("utf-8") if raw is not None else ""


def runner_problem(summary: dict) -> str:
    """A failed runner cannot qualify its leftover workspace as a successful delivery."""
    if (
        summary.get("runner_error")
        or summary.get("server_exited_early")
        or (summary.get("turn_statuses") or [""])[-1] == "failed"
    ):
        return "the runner or executor turn failed"
    return ""


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
    if args.instances and args.knowledge:
        sys.exit(
            "a stream starts with empty knowledge; earlier hidden feedback may expose future tasks"
        )
    if (
        args.batch < 1
        or args.recent_batches < 1
        or args.release_every < 0
        or args.parallel < 1
    ):
        sys.exit(
            "batch, recent-batches and parallel must be positive; release-every cannot be negative"
        )
    if args.confirm_tasks < 1 or not 1 <= args.confirm_min_wins <= args.confirm_tasks:
        sys.exit("confirmation needs positive task and win counts, with wins <= tasks")
    rng = random.Random(args.seed)
    stream = None
    if args.instances:
        # A stream runs every instance once, in an order fixed now, before anything has run.
        instances = sorted(set(args.instances.read_text().split()))
        stream = {
            "order": rng.sample(instances, len(instances)),
            "batch": args.batch,
            "recent": args.recent_batches,
            "release_every": args.release_every,
        }
        dev, confirm = [], []
        if args.release_every:
            if args.sealed is None:
                sys.exit(
                    "stream releases need --sealed with an independent confirmation reserve"
                )
            sealed = json.loads(args.sealed.read_text())[args.sealed_pool]
            if set(instances) & set(sealed):
                sys.exit("stream and confirmation tasks must be disjoint")
            confirm = rng.sample(
                sorted(set(sealed)), min(args.confirm_pool, len(set(sealed)))
            )
            if len(confirm) < args.confirm_tasks:
                sys.exit("the confirmation reserve cannot cover one release")
    elif args.pools is None or args.sealed is None:
        sys.exit("a campaign needs --pools and --sealed (or --instances for a stream)")
    else:
        pools = json.loads(args.pools.read_text())
        dev = args.dev or rng.sample(sorted(pools["dev"]), args.dev_tasks)
        # Confirmation draws on a sealed pool no research view or selection has read.
        sealed = json.loads(args.sealed.read_text())[args.sealed_pool]
        confirm = rng.sample(sorted(sealed), min(args.confirm_pool, len(sealed)))
    codex = Path(args.codex_bin).resolve()
    terms = {
        "schema": 1,
        "seed": args.seed,
        "model": args.model,
        "effort": args.effort,
        "codex_bin": str(codex),
        "codex_sha256": subprocess.run(
            ["sha256sum", str(codex)], capture_output=True, text=True, check=True
        ).stdout.split()[0],
        "task_prompt": str(args.task_prompt.resolve()),
        "task_prompt_sha256": hashlib.sha256(args.task_prompt.read_bytes()).hexdigest(),
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
        "budgets": {
            "research_steps": args.research_steps,
            "task_attempts": args.task_attempts,
        },
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
    if stream:
        terms["stream"] = stream
    camp.mkdir(parents=True, exist_ok=True)
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


def cmd_stream(args) -> None:
    host = Host(args.camp)
    for _ in range(args.count):
        print(host.stream_step(), flush=True)


def cmd_baseline(args) -> None:
    """The root version once on every instance of a stream campaign. It runs in a campaign of its
    own, initialized like the stream's (so its root is the same version), and no view of the stream
    ever reads it."""
    host = Host(args.camp)
    root = next(
        vid
        for vid, manifest in host.versions().items()
        if manifest["lineage"]["parent"] is None
    )
    with ThreadPoolExecutor(args.parallel) as pool:
        list(pool.map(lambda task: host.measure(root, task, "baseline"), host.order()))
    print(f"baseline of {root[:12]}: {len(host.order())} instances measured")


def cmd_exclude(args) -> None:
    """Records, append-only, that an instance of a stream is not part of the benchmark; the order
    itself stays as committed."""
    host = Host(args.camp)
    if args.task not in host.terms["stream"]["order"]:
        sys.exit(f"{args.task} is not in the stream's order")
    # A correction to the instance set the evaluator defines, so it carries the evaluator's epoch.
    host.record(
        "correction",
        {"exclude": args.task, "reason": args.reason},
        epoch=store.digest("epoch", host.adapter.evaluator()),
    )
    print(f"{args.task} excluded: {len(host.order())} instances remain")


def cmd_report(args) -> None:
    report = stream_report(Host(args.camp), Host(args.baseline))
    (args.camp / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "batches"}, indent=2))
    for batch in report["batches"]:
        print(json.dumps(batch))


def stream_report(stream: Host, baseline: Host) -> dict:
    """The stream against its baseline, paired by instance: each task was run once by the stream's
    policy of the time and once by the root, so the task's difficulty cancels. Batch 1 runs the root
    in both, so its pairs measure the comparison's own noise."""

    comparison.validate_comparison(stream, baseline)
    coverage = comparison.coverage(stream, baseline)

    def results(host: Host, purpose: str) -> dict[str, float]:
        out = {}
        for path in sorted((host.camp / "runs").glob(f"{purpose}-*/result.json")):
            result = json.loads(path.read_text())
            if result["validity"] == "valid":
                out[result["task"]] = result["pass_rate"]
        return out

    ran, root = results(stream, "stream"), results(baseline, "baseline")
    paired = [
        task
        for batch in stream.batches()
        for task in batch["tasks"]
        if task in stream.order() and task in ran and task in root
    ]
    deltas = [ran[task] - root[task] for task in paired]
    rng = random.Random(0)
    boot = (
        sorted(mean(rng.choices(deltas, k=len(deltas))) for _ in range(2000))
        if deltas
        else [0.0]
    )
    return {
        **coverage,
        "pairs": len(paired),
        "stream_mean": round(mean(ran[task] for task in paired), 4),
        "baseline_mean": round(mean(root[task] for task in paired), 4),
        "mean_delta": round(mean(deltas), 4),
        "ci95": [
            round(boot[int(0.025 * len(boot))], 4),
            round(boot[int(0.975 * len(boot)) - 1], 4),
        ],
        "wins": sum(d > 0 for d in deltas),
        "losses": sum(d < 0 for d in deltas),
        "ties": sum(d == 0 for d in deltas),
        "batches": [
            {
                "batch": batch["batch"],
                "policy": batch["version"][:12],
                "pairs": len(
                    ds := [ran[t] - root[t] for t in batch["tasks"] if t in paired]
                ),
                "mean_delta": round(mean(ds), 4) if ds else None,
            }
            for batch in stream.batches()
        ],
    }


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
                "prediction": {
                    k: settled[k] for k in ("rescued", "predicted", "p", "held")
                }
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
                "exploration_head": host.stream_policy()[:12] if host.stream else None,
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
    init.add_argument("--pools", type=Path)
    init.add_argument("--codex-bin", required=True)
    init.add_argument("--model", default="gpt-5.6-luna")
    init.add_argument("--effort", default="max")
    init.add_argument("--task-prompt", type=Path, required=True)
    init.add_argument("--research-image", required=True)
    init.add_argument("--programbench", type=Path, default=Path.home() / "ProgramBench")
    init.add_argument("--hf-revision", required=True)
    init.add_argument("--seed", type=int, default=20261006)
    init.add_argument("--dev", nargs="+")
    init.add_argument("--dev-tasks", type=int, default=3)
    init.add_argument("--sealed", type=Path, help="the operator's sealed pool lists")
    init.add_argument(
        "--instances",
        type=Path,
        help="a file of instance ids: start a stream over them instead of a campaign",
    )
    init.add_argument(
        "--batch", type=int, default=16, help="instances per batch of a stream"
    )
    init.add_argument(
        "--release-every",
        type=int,
        default=0,
        help="confirm a tested stream policy every N batches; 0 disables releases",
    )
    init.add_argument(
        "--recent-batches",
        type=int,
        default=2,
        help="batches whose runs a stream's views show in full",
    )
    init.add_argument(
        "--sealed-pool", default="select", help="the sealed pool confirmation draws on"
    )
    init.add_argument("--confirm-pool", type=int, default=8)
    init.add_argument("--confirm-tasks", type=int, default=4)
    init.add_argument("--research-steps", type=int, default=2)
    init.add_argument("--task-attempts", type=int, choices=(1, 2), default=1)
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
    init.add_argument(
        "--mutable", nargs="+", default=[*BUNDLE_FILES, harness_program.PROGRAM_FILE]
    )
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
    stream = sub.add_parser("stream")
    stream.add_argument("--camp", type=Path, required=True)
    stream.add_argument("--count", type=int, default=1)
    baseline = sub.add_parser("baseline")
    baseline.add_argument("--camp", type=Path, required=True)
    baseline.add_argument("--parallel", type=int, default=8)
    exclude = sub.add_parser("exclude")
    exclude.add_argument("--camp", type=Path, required=True)
    exclude.add_argument("--task", required=True)
    exclude.add_argument("--reason", required=True)
    report = sub.add_parser("report")
    report.add_argument("--camp", type=Path, required=True)
    report.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    command = {
        "init": cmd_init,
        "step": cmd_step,
        "analyze": cmd_analyze,
        "adopt": cmd_adopt,
        "status": cmd_status,
        "stream": cmd_stream,
        "baseline": cmd_baseline,
        "exclude": cmd_exclude,
        "report": cmd_report,
    }[args.command]
    if args.command in {"status", "report"}:
        command(args)
    else:
        with succession.writer(args.camp):
            command(args)


if __name__ == "__main__":
    main()
