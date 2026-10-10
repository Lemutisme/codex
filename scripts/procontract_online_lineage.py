"""Durable experimental learning lineage; no inference or stable promotion authority."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from procontract_online import (
    OBSERVATION_BYTES,
    PACKET_BYTES,
    digest,
    encoded,
    proposal,
    seed,
)


class Lineage:
    """Single-writer experimental lineage with transactional claims and monotone evidence.

    A crash leaves claims spent. This API has no operation granting stable adoption,
    rewriting feedback, clearing exposure, or obtaining additional inference budget.
    """

    def __init__(self, root):
        self.root = Path(root).absolute()
        if any(path.is_symlink() for path in (self.root, *self.root.parents)):
            raise ValueError("redirected online lineage")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "lineage.sqlite"
        if self.path.is_symlink():
            raise ValueError("redirected online database")
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            value = seed()
            db.execute(
                "INSERT OR IGNORE INTO versions VALUES (?,?)",
                (digest(value), encoded(value).decode()),
            )
            db.execute(
                "INSERT OR IGNORE INTO state VALUES ('current',?)", (digest(value),)
            )

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, key, kind, body):
        db.execute(
            "INSERT INTO events(key,kind,body) VALUES (?,?,?)",
            (key, kind, encoded(body).decode()),
        )

    def current(self):
        with self.transaction() as db:
            return json.loads(
                db.execute(
                    "SELECT body FROM versions WHERE id=(SELECT value FROM state WHERE key='current')"
                ).fetchone()[0]
            )

    def events(self):
        with self.transaction() as db:
            return [
                {"key": key, "kind": kind, "body": json.loads(body)}
                for key, kind, body in db.execute(
                    "SELECT key,kind,body FROM events ORDER BY seq"
                )
            ]

    def begin(self, episode, total_secs, research_secs):
        if type(episode) is not str or not episode or len(episode.encode()) > 256:
            raise ValueError("invalid episode identity")
        if (
            any(type(v) is not int for v in (total_secs, research_secs))
            or not 0 < research_secs < total_secs <= 18000
        ):
            raise ValueError("invalid bounded episode allocation")
        with self.transaction() as db:
            parent = db.execute(
                "SELECT value FROM state WHERE key='current'"
            ).fetchone()[0]
            body = {
                "episode": episode,
                "parent": parent,
                "total_secs": total_secs,
                "research_secs": research_secs,
                "executor_secs": total_secs - research_secs,
            }
            self._event(db, f"episode:{episode}", "episode", body)
        return body

    def claim(self, episode, observations):
        if len(encoded(observations)) > OBSERVATION_BYTES:
            raise ValueError("feedback packet exceeds bound")
        with self.transaction() as db:
            row = db.execute(
                "SELECT body FROM events WHERE key=?", (f"episode:{episode}",)
            ).fetchone()
            if row is None:
                raise ValueError("episode was not reserved")
            parent = json.loads(row[0])["parent"]
            if (
                db.execute("SELECT value FROM state WHERE key='current'").fetchone()[0]
                != parent
            ):
                raise ValueError("stale episode parent")
            program = json.loads(
                db.execute(
                    "SELECT body FROM versions WHERE id=?", (parent,)
                ).fetchone()[0]
            )
            rewards = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT body FROM events WHERE kind='reward' ORDER BY seq DESC LIMIT 2"
                )
            ]
            previous = db.execute(
                "SELECT body FROM events WHERE kind='trial' ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            packet = {
                "parent": parent,
                "program": program,
                "observations": observations,
                "past_rewards": rewards,
                "previous_trial": json.loads(previous[0]) if previous else None,
            }
            if len(encoded(packet)) > PACKET_BYTES:
                raise ValueError("combined research packet exceeds bound")
            self._event(
                db,
                f"claim:{episode}",
                "claim",
                {
                    "packet": packet,
                    "packet_sha256": digest(packet),
                    "producer_method": digest(program["research"]),
                },
            )
        return packet

    def register(self, episode, raw):
        program, explanation = proposal(raw)
        with self.transaction() as db:
            row = db.execute(
                "SELECT body FROM events WHERE key=?", (f"claim:{episode}",)
            ).fetchone()
            if row is None:
                raise ValueError("proposal has no claimed research attempt")
            claim = json.loads(row[0])
            candidate = digest(program)
            if candidate == claim["packet"]["parent"]:
                raise ValueError("proposal is unchanged")
            db.execute(
                "INSERT OR IGNORE INTO versions VALUES (?,?)",
                (candidate, encoded(program).decode()),
            )
            self._event(
                db,
                f"proposal:{episode}",
                "proposal",
                {
                    "candidate": candidate,
                    "parent": claim["packet"]["parent"],
                    "producer_method": claim["producer_method"],
                    **explanation,
                },
            )
        return program

    def dispatch(self, episode, receipt):
        # The trusted runtime supplies the receipt. Persist every outcome; a model
        # cannot manufacture an ACK through its proposal schema.
        if type(receipt) is not dict or receipt.get("outcome") not in (
            "accepted",
            "error",
            "timeout",
            "unacknowledged",
        ):
            raise ValueError("invalid steering receipt")
        with self.transaction() as db:
            row = db.execute(
                "SELECT body FROM events WHERE key=?", (f"proposal:{episode}",)
            ).fetchone()
            if row is None:
                raise ValueError("dispatch without registered proposal")
            proposed = json.loads(row[0])
            current = db.execute(
                "SELECT value FROM state WHERE key='current'"
            ).fetchone()[0]
            if current != proposed["parent"]:
                raise ValueError("stale publication parent")
            self._event(
                db,
                f"dispatch:{episode}",
                "dispatch",
                {
                    "candidate": proposed["candidate"],
                    "receipt": receipt,
                    "certification": "none",
                },
            )
            # ACK allows experimental inheritance, not a performance claim. The
            # independent report still requires activity AFTER the dispatch.
            if receipt["outcome"] == "accepted":
                db.execute(
                    "UPDATE state SET value=? WHERE key='current'",
                    (proposed["candidate"],),
                )

    def finish_trial(self, episode, *, status, reason, commands_after_ack):
        if (
            status
            not in {
                "observing",
                "researching",
                "candidate",
                "experimental",
                "rejected",
                "not_applied",
            }
            or type(reason) is not str
            or len(reason.encode()) > 300
            or type(commands_after_ack) is not int
            or commands_after_ack < 0
        ):
            raise ValueError("invalid bounded trial feedback")
        with self.transaction() as db:
            if (
                db.execute(
                    "SELECT 1 FROM events WHERE key=?", (f"episode:{episode}",)
                ).fetchone()
                is None
            ):
                raise ValueError("trial without reserved episode")
            self._event(
                db,
                f"trial:{episode}",
                "trial",
                {
                    "episode": episode,
                    "status": status,
                    "reason": reason,
                    "commands_after_ack": commands_after_ack,
                    "scope": "runtime_observation_not_quality_reward",
                },
            )

    def reward(self, episode, *, resolved, total, submission_sha256, evaluator_sha256):
        if (
            any(type(v) is not int for v in (resolved, total))
            or not 0 <= resolved <= total
            or total <= 0
        ):
            raise ValueError("reward requires a valid fixed-denominator outcome")
        import re

        if any(
            type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None
            for v in (submission_sha256, evaluator_sha256)
        ):
            raise ValueError("reward must bind frozen submission and evaluator")
        with self.transaction() as db:
            row = db.execute(
                "SELECT body FROM events WHERE key=?", (f"episode:{episode}",)
            ).fetchone()
            if row is None:
                raise ValueError("reward without episode")
            parent = json.loads(row[0])["parent"]
            dispatched = db.execute(
                "SELECT body FROM events WHERE key=?", (f"dispatch:{episode}",)
            ).fetchone()
            effective = json.loads(dispatched[0]) if dispatched else None
            value = {
                "episode": episode,
                "initial_version": parent,
                "experimental_version": effective["candidate"]
                if effective and effective["receipt"]["outcome"] == "accepted"
                else None,
                "resolved": resolved,
                "total": total,
                "submission_sha256": submission_sha256,
                "evaluator_sha256": evaluator_sha256,
                "credit": "episode_return_not_isolated_causal_effect",
            }
            self._event(db, f"reward:{episode}", "reward", value)
        return value
