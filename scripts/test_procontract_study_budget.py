"""Durable study-wide launch accounting, without models or external services."""

import contextlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import procontract_study_budget as budget


class StudyBudgetTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "budget.sqlite"
        self.study = "a" * 64
        self.limits = {
            "task_launches": 2,
            "learning_launches": 2,
            "allocated_seconds": 100,
        }
        budget.initialize(self.database, self.study, self.limits)

    def new_database(self, name):
        self.database = self.database.with_name(name + ".sqlite")
        budget.initialize(self.database, self.study, self.limits)

    def reserve(self, claim_key, kind="task", seconds=10, **overrides):
        request = {
            "database": self.database,
            "study_sha256": self.study,
            "key": claim_key,
            "kind": kind,
            "deadline_secs": seconds,
            "limits": self.limits,
            "identity": {"policy": "b" * 64},
        }
        return budget.reserve(**(request | overrides))

    def report(self):
        return budget.status(self.database, self.study, self.limits)

    def test_each_kind_has_a_cap_and_denial_does_not_consume_a_launch(self):
        self.limits = {
            "task_launches": 1,
            "learning_launches": 1,
            "allocated_seconds": 30,
        }
        self.new_database("kind-caps")
        self.assertIsInstance(self.reserve("task"), dict)
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve("extra-task")
        self.reserve("learning", "learning", 20)
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve("extra-learning", "learning", 1)
        expected = {
            "study_sha256": self.study,
            "limits": self.limits,
            "reserved": self.limits,
            "remaining": {
                "task_launches": 0,
                "learning_launches": 0,
                "allocated_seconds": 0,
            },
        }
        report = self.report()
        self.assertEqual({key: report[key] for key in expected}, expected)

    def test_allocated_seconds_are_shared_across_task_and_learning(self):
        self.limits["allocated_seconds"] = 15
        self.new_database("seconds-cap")
        self.reserve("task", seconds=10)
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve("learning", "learning", 6)
        self.reserve("learning", "learning", 5)
        self.assertEqual(
            self.report()["reserved"],
            {"task_launches": 1, "learning_launches": 1, "allocated_seconds": 15},
        )

    def test_claim_is_not_a_repeatable_permission_even_with_equal_identity(self):
        self.reserve("once")
        before = self.report()
        for identity in ({"policy": "b" * 64}, {"policy": "c" * 64}):
            with self.subTest(identity=identity):
                with self.assertRaises(budget.AlreadyClaimed):
                    self.reserve("once", identity=identity)
        self.assertEqual(self.report(), before)

    def test_concurrent_connections_cannot_overdraw_the_last_launch(self):
        self.limits["task_launches"] = 1
        self.new_database("concurrent-cap")

        def compete(index):
            try:
                self.reserve(f"concurrent-{index}")
                return True
            except budget.BudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(compete, range(16)))
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(
            self.report()["reserved"],
            {"task_launches": 1, "learning_launches": 0, "allocated_seconds": 10},
        )

    def test_commit_survives_process_exit_before_the_caller_records_success(self):
        script = """
import json, os, sys
from pathlib import Path
import procontract_study_budget as budget
budget.reserve(database=Path(sys.argv[1]), study_sha256=sys.argv[2], key="child",
               kind="learning", deadline_secs=13, limits=json.loads(sys.argv[3]),
               identity={"producer": "child"})
os._exit(23)
"""
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(self.database),
                self.study,
                json.dumps(self.limits),
            ],
            cwd=Path(__file__).parent,
            check=False,
        )
        self.assertEqual(child.returncode, 23)
        with self.assertRaises(budget.AlreadyClaimed):
            self.reserve("child", "learning", 13, identity={"producer": "child"})
        self.assertEqual(
            self.report()["reserved"],
            {"task_launches": 0, "learning_launches": 1, "allocated_seconds": 13},
        )

    def test_invalid_requests_are_rejected_instead_of_coerced(self):
        requests = [
            {"study_sha256": "A" * 64},
            {"study_sha256": "a" * 63},
            {"key": ""},
            {"key": "x" * 4097},
            {"kind": "evaluation"},
            {"deadline_secs": True},
            {"deadline_secs": 0},
            {"deadline_secs": -1},
            {"deadline_secs": 2**64},
            {"identity": []},
            {"identity": {"nonfinite": float("nan")}},
            {"limits": {}},
            {"limits": self.limits | {"extra": 1}},
        ]
        requests += [
            {"limits": self.limits | {name: value}}
            for name in self.limits
            for value in (True, 0, -1)
        ]
        for request in requests:
            with self.subTest(request=request):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.reserve("invalid", **request)

    def test_operator_plan_is_bound_even_without_any_authorized_reservation(self):
        with self.assertRaises(budget.BudgetExceeded):
            self.reserve("too-large", seconds=101)
        self.assertEqual(
            self.report()["reserved"],
            {"task_launches": 0, "learning_launches": 0, "allocated_seconds": 0},
        )
        for changed in (
            {"study_sha256": "c" * 64},
            {"limits": self.limits | {"allocated_seconds": 101}},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(budget.PlanMismatch):
                    self.reserve("changed", **changed)
                with self.assertRaises(budget.PlanMismatch):
                    budget.status(
                        self.database,
                        changed.get("study_sha256", self.study),
                        changed.get("limits", self.limits),
                    )

    def test_reserve_and_status_never_create_a_missing_database(self):
        missing = self.database.with_name("missing.sqlite")
        with self.assertRaises(budget.CorruptBudget):
            self.reserve("missing", database=missing)
        with self.assertRaises(budget.CorruptBudget):
            budget.status(missing, self.study, self.limits)
        self.assertFalse(missing.exists())
        self.reserve("existing")
        before = self.database.read_bytes()
        self.report()
        self.assertEqual(self.database.read_bytes(), before)

    def test_initialize_never_resets_existing_or_partial_studies(self):
        self.reserve("spent")
        before = self.database.read_bytes()
        for study in (self.study, "c" * 64):
            with self.assertRaises(budget.PlanMismatch):
                budget.initialize(self.database, study, self.limits)
            self.assertEqual(self.database.read_bytes(), before)
        partial = self.database.with_name("partial.sqlite")
        partial.touch()
        with self.assertRaises(budget.PlanMismatch):
            budget.initialize(partial, self.study, self.limits)
        with self.assertRaises(budget.CorruptBudget):
            self.reserve("partial", database=partial)
        self.database.unlink()
        with self.assertRaises(budget.CorruptBudget):
            self.reserve("spent")
        self.assertFalse(self.database.exists())

    def test_corrupt_database_is_never_replaced_with_an_empty_budget(self):
        self.database.write_bytes(b"not a sqlite database")
        before = self.database.read_bytes()
        with self.assertRaises(budget.CorruptBudget):
            self.reserve("corrupt")
        with self.assertRaises(budget.CorruptBudget):
            self.report()
        self.assertEqual(self.database.read_bytes(), before)

    def test_corrupt_or_rebound_reservation_rows_fail_closed(self):
        self.reserve("original")
        for identity in ("not-json", json.dumps({"policy": "c" * 64})):
            with self.subTest(identity=identity):
                with (
                    contextlib.closing(sqlite3.connect(self.database)) as connection,
                    connection,
                ):
                    connection.execute(
                        "UPDATE reservations SET identity_json = ? WHERE key = ?",
                        (identity, "original"),
                    )
                with self.assertRaises(budget.CorruptBudget):
                    self.reserve("another")
                with self.assertRaises(budget.CorruptBudget):
                    self.report()

    def test_missing_plan_or_unknown_schema_cannot_reset_an_unspent_budget(self):
        for index, statement in enumerate(
            ("DELETE FROM plan", "PRAGMA user_version = 2")
        ):
            with self.subTest(statement=statement):
                self.new_database(f"corrupt-{index}")
                with self.assertRaises(budget.BudgetExceeded):
                    self.reserve("too-large", seconds=101)
                self.assertEqual(
                    self.report()["reserved"],
                    {
                        "task_launches": 0,
                        "learning_launches": 0,
                        "allocated_seconds": 0,
                    },
                )
                with (
                    contextlib.closing(sqlite3.connect(self.database)) as connection,
                    connection,
                ):
                    connection.execute(statement)
                for study in (self.study, "c" * 64):
                    with self.assertRaises(budget.CorruptBudget):
                        self.reserve("replacement", study_sha256=study)
                    with self.assertRaises(budget.CorruptBudget):
                        budget.status(self.database, study, self.limits)


if __name__ == "__main__":
    unittest.main()
