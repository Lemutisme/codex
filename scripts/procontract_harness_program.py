"""Bounded, data-only steering predicates; evaluation has no external capabilities."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

PROGRAM_FILE = "harness.json"
INTERPRETER = "convergence-v1"
INTERPRETER_V2 = "bounded-steering-v2"
MAX_BYTES = 4096
MAX_NODES = 64
MAX_DEPTH = 8
MAX_INTEGER = (1 << 31) - 1
FACTS = frozenset(
    ("deadline_secs", "remaining_secs", "turns_completed", "repairs_used")
)
FACTS_V2 = FACTS | {"executor_command_completions_observed"}


def _integer(value) -> bool:
    return type(value) is int and 0 <= value <= MAX_INTEGER


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_number(value):
    raise ValueError("only bounded integers are allowed")


def _compile(node, depth, count, schema):
    count[0] += 1
    if depth > MAX_DEPTH or count[0] > MAX_NODES:
        raise ValueError("predicate exceeds its depth or node budget")
    if type(node) is not dict or len(node) != 1:
        raise ValueError("a predicate must be a single-key object")
    op, value = next(iter(node.items()))
    if op in ("all", "any"):
        if type(value) is not list:
            raise ValueError("all/any require a predicate list")
        value = tuple(_compile(child, depth + 1, count, schema) for child in value)
    elif op == "not":
        value = _compile(value, depth + 1, count, schema)
    elif op == "always":
        if type(value) is not bool:
            raise ValueError("always requires a boolean")
    elif op == "remaining_fraction_lte":
        if (
            type(value) is not list
            or len(value) != 2
            or not all(_integer(item) for item in value)
            or value[1] == 0
        ):
            raise ValueError(
                "a fraction requires two bounded integers and a positive denominator"
            )
        value = tuple(value)
    elif op in ("completed_turns_lte", "repairs_used_gte") or (
        schema == 2 and op == "command_completions_observed_gte"
    ):
        if not _integer(value):
            raise ValueError(
                "a turn/repair threshold requires a bounded nonnegative integer"
            )
    else:
        raise ValueError("unknown predicate")
    return op, value


def _evaluate(node, facts):
    op, value = node
    if op == "always":
        return value
    if op == "remaining_fraction_lte":
        numerator, denominator = value
        return (
            facts["remaining_secs"] * denominator <= facts["deadline_secs"] * numerator
        )
    if op == "completed_turns_lte":
        return facts["turns_completed"] <= value
    if op == "repairs_used_gte":
        return facts["repairs_used"] >= value
    if op == "command_completions_observed_gte":
        return facts["executor_command_completions_observed"] >= value
    if op == "all":
        return all(_evaluate(child, facts) for child in value)
    if op == "any":
        return any(_evaluate(child, facts) for child in value)
    if op == "not":
        return not _evaluate(value, facts)
    raise ValueError("unknown compiled predicate")


@dataclass(frozen=True)
class Program:
    """Immutable validated predicate/action and the identity of its exact source bytes."""

    digest: str
    _tree: tuple
    source: bytes = field(repr=False)
    schema: int = 1
    action: str = "converge"

    @property
    def interpreter(self) -> str:
        return INTERPRETER_V2 if self.schema == 2 else INTERPRETER

    def evaluate(self, facts) -> bool:
        if (
            type(facts) is not dict
            or facts.keys() != (FACTS_V2 if self.schema == 2 else FACTS)
            or not all(_integer(value) for value in facts.values())
            or facts["deadline_secs"] == 0
        ):
            raise ValueError(
                "facts must contain exactly four bounded integers and a positive deadline"
                if self.schema == 1
                else "facts must contain exactly five bounded integers and a positive deadline"
            )
        return _evaluate(self._tree, facts)


def read_regular(path: Path, max_bytes: int) -> bytes | None:
    """Snapshot one bounded regular file without following its link; missing means None.

    Callers own the trusted parent-directory boundary and consume these bytes rather than
    reopening the candidate-controlled path after validation.
    """
    if not _integer(max_bytes):
        raise ValueError("file byte limit must be a bounded nonnegative integer")
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("file could not be inspected safely") from error
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("file must be regular and non-linked")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ValueError("file changed while opening")
            raw = source.read(max_bytes + 1)
    except OSError as error:
        raise ValueError("file could not be read safely") from error
    if len(raw) > max_bytes:
        raise ValueError("file exceeds its byte budget")
    return raw


def load(bundle: Path | None) -> Program | None:
    """Load bounded UTF-8 source from a real bundle directory; missing means no program."""
    if bundle is None:
        return None
    try:
        root = bundle.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("bundle could not be inspected safely") from error
    if not stat.S_ISDIR(root.st_mode):
        raise ValueError("bundle must be a non-linked directory")
    raw = read_regular(bundle / PROGRAM_FILE, MAX_BYTES)
    if raw is None:
        return None
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_float=_invalid_number,
            parse_constant=_invalid_number,
        )
    except RecursionError as error:
        raise ValueError("harness program is too deeply nested") from error
    if (
        type(document) is not dict
        or type(document.get("schema")) is not int
        or document["schema"] not in (1, 2)
    ):
        raise ValueError("unsupported harness program schema")
    schema = document["schema"]
    keys = {"schema", "when"} if schema == 1 else {"schema", "action", "when"}
    if document.keys() != keys:
        raise ValueError("unsupported harness program schema")
    if schema == 2 and document["action"] not in ("checkpoint", "converge"):
        raise ValueError("unsupported harness program action")
    tree = _compile(document["when"], 1, [0], schema)
    return Program(
        hashlib.sha256(raw).hexdigest(),
        tree,
        raw,
        schema,
        document.get("action", "converge"),
    )
