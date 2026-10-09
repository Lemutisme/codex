"""Read-only receipts for one P/H episode; no inference, adoption or gate changes."""

import contextlib
import json
from pathlib import Path
import sqlite3
import statistics

from procontract_ph_protocol import digest, document, raw, require


def native_exited(summary):
    receipt = summary.get("native_process_exit")
    return (
        isinstance(receipt, dict)
        and set(receipt) == {"status", "returncode", "shutdown"}
        and receipt["status"] == "exited"
        and type(receipt["returncode"]) is int
        and receipt["shutdown"] in {"stdin_closed", "terminate", "kill"}
    )


class Audit:
    def __init__(self, host, sealed):
        self.host, self.sealed = host, sealed
        self.camp, self.terms = host.camp, host.terms
        self.paid_runs = {}

    def paid(self):
        import procontract_study_budget as budget
        import procontract_rsi as rsi

        balance = budget.status(
            self.camp / "study-budget.sqlite",
            self.terms["study"]["manifest_sha256"],
            self.sealed["limits"],
        )
        with contextlib.closing(
            sqlite3.connect(
                (self.camp / "study-budget.sqlite").resolve().as_uri() + "?mode=ro",
                uri=True,
            )
        ) as connection:
            rows = connection.execute(
                "SELECT key,kind,deadline_secs,identity_json,receipt_id,binding_sha256 FROM reservations"
            ).fetchall()
        require(
            len(rows) <= 25,
            "episode exceeded its maximum task/learning launch envelope",
        )
        self.paid_runs = {}
        for key, kind, deadline, encoded, receipt_id, binding in rows:
            run, identity = self.camp / key, json.loads(encoded)
            require(
                run.resolve().is_relative_to(self.camp) and ".." not in Path(key).parts,
                "paid receipt escapes campaign",
            )
            receipt = {
                "id": receipt_id,
                "key": key,
                "study_sha256": self.terms["study"]["manifest_sha256"],
                "kind": kind,
                "deadline_secs": deadline,
                "binding_sha256": binding,
            }
            require(
                document(run / "study-launch.json") == receipt
                and digest(run / "manifest.json") == identity["manifest_sha256"],
                "paid identity differs from reservation",
            )
            require(
                set(identity["configuration"])
                == {
                    "codex-home/config.toml",
                    "codex-home/environments.toml",
                    "codex-home/pro_contract/settings.json",
                }
                and all(
                    digest(run / name) == expected
                    for name, expected in identity["configuration"].items()
                ),
                "paid configuration changed",
            )
            manifest = document(run / "manifest.json")
            require(
                (
                    manifest["study_version"],
                    manifest["instructions"],
                    manifest["instance"],
                )
                == (identity["version"], identity["role"], identity["instance"]),
                "paid producer identity differs",
            )
            summary = document(run / "run.json")
            statuses = summary.get("turn_statuses")
            closed = native_exited(summary)
            terminal = (
                bool(rsi.runner_problem(summary))
                or isinstance(statuses, list)
                and bool(statuses)
                and statuses[-1] in {"completed", "interrupted", "failed"}
                or summary.get("deadline_hit") is True
                and closed
            )
            require(
                "native_process_exit" not in summary or closed,
                "native process exit remains unknown",
            )
            require(
                summary.get("study_launch") == receipt and terminal,
                "unknown paid launch; no continuation",
            )
            require(
                kind != "learning" or (run.parent / "launch-claim.json").is_file(),
                "learning reservation lacks its Host claim",
            )
            self.paid_runs[str(run)] = receipt
        claims = list(self.camp.glob("insight/*/*/launch-claim.json")) + list(
            self.camp.glob("research/*/launch-claim.json")
        )
        for path in claims:
            claim, exited = document(path), document(path.parent / "launch-exit.json")
            import procontract_store as store

            require(
                exited.get("claim") == store.digest("learning_launch", claim)
                and type(exited.get("returncode")) is int,
                "unknown learning launch; no continuation",
            )
        return balance

    def task(self, version, task, purpose):
        parent = self.camp / "runs" / f"{purpose}-{version[:12]}-{task}"
        result = document(parent / "result.json")
        run = parent / "attempt-1"
        require(
            (
                result.get("version"),
                result.get("task"),
                result.get("purpose"),
                result.get("run_dir"),
                result.get("validity"),
            )
            == (version, task, purpose, str(run), "valid")
            and [p.name for p in parent.glob("attempt-*") if p.is_dir()]
            == ["attempt-1"],
            "invalid or repurchased task",
        )
        self.host.validate_evaluator(result)
        self.runtime(run, version, "executor.md")
        require(
            document(run / "manifest.json")["instance"] == task,
            "task manifest names another task",
        )
        return result

    def runtime(self, run, parent, role):
        import procontract_rsi as rsi
        import procontract_canonical as canonical

        manifest, summary = document(run / "manifest.json"), document(run / "run.json")
        require(
            all(
                manifest.get(key) == self.terms[key]
                for key in ("model", "effort", "codex_bin", "codex_sha256")
            )
            and manifest.get("study") == self.terms["study"]
            and manifest.get("study_version") == parent
            and manifest.get("instructions") == role,
            "native prepared role/profile differs",
        )
        statuses = summary.get("turn_statuses")
        closed = native_exited(summary)
        terminal = (
            isinstance(statuses, list)
            and bool(statuses)
            and statuses[-1] in {"completed", "interrupted"}
            or summary.get("deadline_hit") is True
            and closed
        )
        require(
            terminal
            and not rsi.runner_problem(summary)
            and ("native_process_exit" not in summary or closed),
            "native role did not finish successfully",
        )
        require(
            str(run) in self.paid_runs
            and summary.get("study_launch") == self.paid_runs[str(run)],
            "native run lacks its paid reservation",
        )
        task = role == "executor.md"
        image = (
            canonical.registry().tasks[manifest["instance"]]["image"]
            if task
            else self.terms["research_image"]
        )
        require(
            manifest.get("image") == image
            and digest(run / "prompt.txt") == manifest.get("prompt_sha256")
            and (
                not task
                or manifest["prompt_sha256"] == self.terms["task_prompt_sha256"]
            ),
            "runtime prompt or image differs",
        )
        source = self.host.version_dir(parent) / "bundle"
        require(
            {p.name: raw(p) for p in source.iterdir()}
            == {p.name: raw(p) for p in (run / "policy").iterdir()},
            "executed bundle differs from registered producer",
        )
        self.host.validate_harness(parent)
        expected = self.host.versions()[parent].get("harness")
        for value in (manifest, summary):
            activation = value.get("harness_program")
            require(
                (
                    {k: activation.get(k) for k in ("sha256", "interpreter")}
                    if activation
                    else None
                )
                == expected,
                "runtime harness identity differs",
            )
        return {
            key: summary.get(key)
            for key in (
                "status",
                "turn_statuses",
                "deadline_hit",
                "native_process_exit",
            )
        }

    def role(self, root, parent, role):
        claim = document(root / "launch-claim.json")
        require(
            not (root / "runner-failed.json").exists()
            and claim["identity"]["parent"] == parent
            and claim["identity"]["instructions"] == role
            and claim["prepared_manifest"] == digest(root / "run/manifest.json"),
            "learning authority differs or failed",
        )
        import procontract_store as store

        require(
            document(root / "launch-exit.json")
            == {"claim": store.digest("learning_launch", claim), "returncode": 0},
            "learning launch did not exit successfully",
        )
        require(
            all(
                claim["identity"][key] == self.terms[field]
                for key, field in (
                    ("model", "model"),
                    ("effort", "effort"),
                    ("binary", "codex_sha256"),
                    ("image", "research_image"),
                )
            ),
            "learning launch profile differs",
        )
        return self.runtime(root / "run", parent, role)

    def analysis(self, batch):
        run = f"stream-{batch['version'][:12]}-{batch['tasks'][0]}"
        matches = [
            body
            for body in self.host.insights()
            if body.get("analysis_identity", {}).get("parent")
            == batch["expected_incumbent"]
            and run in body["coverage"]
            and body["experiment"]
            == (batch["version"] if batch["phase"] == "probe" else None)
        ]
        require(
            matches and matches[-1]["status"] == "qualified",
            "continuation analysis failed or missing",
        )
        insight = matches[-1]
        import procontract_store as store

        observed = self.host.observed()
        batches = self.host.batches()[: batch["batch"]]
        expected = {
            f"stream-{b['version'][:12]}-{task}" for b in batches for task in b["tasks"]
        }
        if batch["batch"] == 3:
            expected.update(
                f"confirm-{b['version'][:12]}-{task}"
                for b in batches[:2]
                for task in self.terms["pools"]["confirm"]
            )
        require(
            insight["analysis_identity"]["coverage"]
            == insight["coverage"]
            == sorted(expected)
            and expected <= observed.keys()
            and insight["analysis_identity"]["evidence"]
            == store.digest(
                "analysis_evidence",
                {name: observed[name] for name in insight["coverage"]},
            ),
            "analysis evidence differs from its recorded observation",
        )
        if batch["phase"] == "probe":
            require(
                insight["verdict"] == "present",
                "probe lacks a challenged present signature",
            )
        statuses = {}
        for role in ("analyst", "challenger"):
            roots = sorted(
                (self.camp / "insight" / str(insight["k"])).glob(f"{role}-*")
            )
            require(roots, "qualified insight lacks native role attempts")
            statuses[role] = self.role(
                roots[-1], batch["expected_incumbent"], f"{role}.md"
            )
        return {
            "k": insight["k"],
            "identity": insight["analysis_identity"],
            "native_statuses": statuses,
        }

    def research(self, phase, parent, candidate):
        import procontract_rsi as rsi

        root = self.camp / "research" / f"step-{phase}"
        status = self.role(root, parent, "research.md")
        state = self.host.contract(f"improvement.{phase}")
        require(state and state["standing"] == "discharged", "research did not qualify")
        delivery = root / "run/workspace"
        qualified, reason, changed = self.host.qualify(
            delivery, parent, allowed_files=self.terms["mutable"]
        )
        require(
            qualified and changed == (candidate is not None),
            "research qualification/change does not match result",
        )
        subject = rsi.delivery_subject(delivery, rsi.experiment_text(delivery))
        require(
            state["candidate"]["subject_hash"]
            == state["support"]["coordinate"]["subject_hash"]
            == subject,
            "qualification does not bind this delivery",
        )
        selected = [
            e["body"]
            for e in self.host.events("selection")
            if e["body"].get("role") == "stream_policy"
            and e["body"].get("batch") == phase + 1
        ]
        require(
            selected
            == (
                [{"role": "stream_policy", "version": candidate, "batch": phase + 1}]
                if candidate
                else []
            ),
            "successor selection is ambiguous",
        )
        if candidate:
            manifest = self.host.versions()[candidate]
            require(
                candidate != parent
                and manifest["lineage"] == {"parent": parent, "proposed_by": parent},
                "successor lineage differs",
            )
            self.host.validate_harness(candidate)
            require(
                {p.name: raw(p) for p in (delivery / "policy").iterdir()}
                == {
                    p.name: raw(p)
                    for p in (self.host.version_dir(candidate) / "bundle").iterdir()
                },
                "registered candidate differs from delivery",
            )
            require(
                raw(delivery / "EXPERIMENT.md")
                == raw(self.host.version_dir(candidate) / "EXPERIMENT.md"),
                "registered experiment differs from qualified delivery",
            )
            require(
                all(
                    manifest["bundle"][name]
                    == self.host.versions()[parent]["bundle"][name]
                    for name in ("analyst.md", "challenger.md", "research.md")
                ),
                "method policies changed",
            )
        return {
            "candidate": candidate,
            "native_status": status,
            "qualification": reason,
            "subject": subject,
        }

    def adoption(self, candidate, root, sequence):
        import procontract_store as store
        import procontract_succession as succession

        plans = [
            e["body"]
            for e in self.host.events("assignment")
            if "confirmation" in e["body"]
        ]
        gate = {
            key: self.terms["gates"][key]
            for key in ("confirm_tasks", "confirm_min_delta", "confirm_min_wins")
        }
        require(
            plans
            == [
                {
                    "confirmation": candidate,
                    "incumbent": root,
                    "incumbent_seq": sequence,
                    "tasks": self.terms["pools"]["confirm"],
                    "gate": gate,
                }
            ],
            "confirmation is not the single predeclared paired comparison",
        )
        pairs, counts = {}, {}
        for task in plans[0]["tasks"]:
            results = [
                self.task(version, task, "confirm") for version in (candidate, root)
            ]
            pairs[task] = [result["pass_rate"] for result in results]
            counts[task] = [result["label"]["outcome"] for result in results]
        deltas = [c - r for c, r in pairs.values()]
        evidence = {
            "pairs": pairs,
            "mean_delta": statistics.fmean(deltas),
            "wins": sum(d > 0 for d in deltas),
            "gate": gate,
        }
        contract = f"adoption.{candidate[:16]}"
        state = self.host.contract(contract)
        require(
            evidence["mean_delta"] >= gate["confirm_min_delta"]
            and evidence["wins"] >= gate["confirm_min_wins"]
            and state
            and state["standing"] == "discharged",
            "paired gate or adoption is not settled",
        )
        coordinate = state["support"]["coordinate"]
        require(
            state["candidate"]["subject_hash"]
            == coordinate["subject_hash"]
            == candidate
            and coordinate["evidence_hash"] == store.digest("evidence", evidence)
            and state["settlement"]["coordinate"] == coordinate,
            "adoption does not bind recomputed confirmation",
        )
        require(
            coordinate["basis"]
            == store.digest(
                "basis",
                {
                    "tasks": plans[0]["tasks"],
                    "evaluator": self.host.adapter.evaluator(),
                },
            )
            and coordinate["evaluator_digest"]
            == store.digest("evaluator", self.host.adapter.evaluator())
            and coordinate["environment_digest"]
            == store.digest("environment", self.host.adapter.environment()),
            "confirmation basis differs",
        )
        issues = [
            e["body"]
            for e in self.host.events("issue")
            if e["body"]["contract_id"] == contract
        ]
        require(
            len(issues) == 1
            and not issues[0]["terms"].get("bootstrap")
            and self.host.incumbent() == candidate
            and succession.incumbent_record(self.host)["seq"] > sequence,
            "candidate is not the actual nonbootstrap incumbent",
        )
        expected_terms = {
            "campaign": self.host.campaign_hash(),
            "candidate": candidate,
            "expected_incumbent": root,
            "incumbent_seq": sequence,
            "gate": gate,
        }
        policy = {
            "class": "paired_confirmation",
            "tasks": store.digest("pool", plans[0]["tasks"]),
            "gate": gate,
        }
        require(
            issues[0]["terms"] == expected_terms
            and issues[0]["evidence_policy"] == policy
            and state["bindings"]["terms_hash"] == store.digest("terms", expected_terms)
            and state["bindings"]["evidence_policy_hash"]
            == store.digest("evidence_policy", policy)
            and state["settlement"]["decision"] == self.host.presumed()
            and coordinate["reach"] == "beyond",
            "adoption differs from the predeclared automatic gate",
        )
        incumbents = [
            e["body"]
            for e in self.host.events("selection")
            if e["body"].get("role") == "incumbent"
        ]
        require(
            [e["version"] for e in incumbents] == [root, candidate]
            and incumbents[-1]["adoption"] == contract,
            "unexpected earned adoption",
        )
        pooled = [
            {
                key: sum(pair[arm][key] for pair in counts.values())
                for key in ("passed", "counted")
            }
            for arm in (0, 1)
        ]
        return {
            **evidence,
            "counts": counts,
            "pooled": pooled,
            "regressions": [t for t, (c, r) in pairs.items() if c < r],
            "claim": "four paired tasks; exploratory probe is unpaired",
        }
