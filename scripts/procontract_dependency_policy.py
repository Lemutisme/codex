"""Future-only, operator-pinned dependency rules; receipts are not compliance proofs.

The live inspector must independently hash the declared files in each pinned image.
This loader executes no manifest data and never resolves image paths on the host.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from types import MappingProxyType

from procontract_canonical_registry import HEX256, TASK_ID

POLICY = "rust-preinstalled-v1"
MAX_BYTES, MAX_PROMPT_BYTES = 1 << 20, 7500
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}")
USES = ("build", "runtime", "exploration")


def _require(condition, message):
    if not condition:
        raise ValueError(f"dependency policy {message}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "has duplicate JSON keys")
        result[key] = value
    return result


def _number(_value):
    raise ValueError("dependency policy permits no floating-point values")


def _read(path, limit):
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "path must be absolute")
    try:
        for parent in path.parents:
            _require(stat.S_ISDIR(parent.lstat().st_mode), "parent must not be linked")
        before = path.lstat()
        _require(
            stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "requires an independent regular file",
        )
        flags = (
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(path, flags), "rb") as source:
            opened = os.fstat(source.fileno())
            _require(
                stat.S_ISREG(opened.st_mode)
                and opened.st_nlink == 1
                and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                "file changed while opening",
            )
            raw = source.read(limit + 1)
            after = os.fstat(source.fileno())
        _require(len(raw) <= limit, "file exceeds byte limit")
        _require(
            opened.st_nlink == after.st_nlink
            and opened.st_size == after.st_size == len(raw)
            and opened.st_mtime_ns == after.st_mtime_ns,
            "file changed while reading",
        )
        return raw
    except OSError as error:
        raise ValueError("dependency policy file cannot be read safely") from error


def validate_allowed(allowed):
    """Return canonical (name, kind, uses) tuples; permit no free-form instructions."""
    _require(isinstance(allowed, list) and 1 <= len(allowed) <= 64, "invalid allowlist")
    result = {}
    for item in allowed:
        _require(
            isinstance(item, dict) and set(item) == {"name", "kind", "uses"},
            "invalid allowlist fields",
        )
        name, kind, uses = item["name"], item["kind"], item["uses"]
        _require(isinstance(name, str) and NAME.fullmatch(name), "invalid item name")
        _require(kind in ("tool", "library"), "invalid item kind")
        _require(
            isinstance(uses, list)
            and 1 <= len(uses) <= len(USES)
            and all(isinstance(use, str) and use in USES for use in uses)
            and len(set(uses)) == len(uses),
            "invalid item uses",
        )
        key = f"{kind}:{name}"
        _require(key not in result, "duplicate allowed item")
        result[key] = (name, kind, tuple(use for use in USES if use in uses))
    return tuple(result[key] for key in sorted(result))


def validate_items(items, allowed):
    """Validate exact per-image file receipts, not the truth of their content hashes."""
    expected = {f"{kind}:{name}" for name, kind, _uses in validate_allowed(allowed)}
    _require(
        isinstance(items, dict) and set(items) == expected, "image inventory differs"
    )
    result = {}
    for key, item in items.items():
        _require(
            isinstance(item, dict) and set(item) == {"path", "sha256"},
            "invalid image item fields",
        )
        value = item["path"]
        _require(isinstance(value, str) and len(value) <= 512, "invalid image path")
        path = PurePosixPath(value)
        _require(
            re.fullmatch(r"/(usr|bin|sbin|lib|lib64|opt)(/[A-Za-z0-9_.+@:-]+)+", value)
            and str(path) == value
            and ".." not in path.parts,
            "image path must remain within approved system roots",
        )
        _require(
            isinstance(item["sha256"], str) and HEX256.fullmatch(item["sha256"]),
            "invalid image item digest",
        )
        result[key] = {"path": value, "sha256": item["sha256"]}
    return result


def render_prompt(allowed):
    """Full task requirements fit the native isolated-role initial-message limit."""
    rows = [
        f"- {kind} {name}: {', '.join(uses)}."
        for name, kind, uses in validate_allowed(allowed)
    ]
    text = "Explicitly permitted preinstalled external dependencies (allowed uses):\n"
    text += "\n".join(rows)
    text += """

Implement the program from scratch in Rust. Rust's standard library is permitted.
Only the external tools and libraries listed above may be used, and only for their
listed uses. They must already exist in the pinned cleanroom image. A use permitted
for exploration is not permission to use it at build time or runtime. No external
network access, downloads, dependency installation (including offline installation), or
vendoring of pre-existing implementation code is allowed. Do not use other external
crates, libraries, tools, or programs as implementation dependencies. This permission
does not permit reuse of the reference program or its source code.

Rust's standard library and a permitted tool include their normal preinstalled
runtime/toolchain components; this does not permit adding packages or directly using
other third-party libraries from your implementation. Shell builtins belong to the
listed shell. Local loopback communication is permitted for probing or implementing
the documented interface, not external access or downloads. Processing caller data
or executing a caller-supplied command, when required by that interface, is program
behavior rather than an implementation dependency. Never use this distinction to
delegate your implementation to the reference or to a hard-coded unlisted program.

You are in /workspace. It contains program documentation and ./executable, the
compiled reference implementation. During exploration only, you may execute the
reference as a black box to observe behavior. Do not read, copy, disassemble,
decompile, reuse, or invoke the reference from your implementation or compile.sh.
Do not overwrite or delete the reference while working; build to another location.

Match the reference's command-line interface, standard output, standard error, exit
codes, and observable behavior. Write source code in /workspace and provide
/workspace/compile.sh. When run from the root of a clean copy of your submission,
compile.sh must build your Rust implementation and place its binary at ./executable.
The original ./executable and ./target are excluded from the submission. compile.sh
must rebuild your Rust executable from submitted source, not prior task-build outputs.
A hidden test suite compares
your implementation with the reference. These requirements apply to every role,
including exploration, drafting, review, compilation, and final execution.
"""
    raw = text.encode("utf-8")
    _require(len(raw) <= MAX_PROMPT_BYTES, "rendered prompt exceeds native role limit")
    return raw


@dataclass(frozen=True)
class Policy:
    path: Path
    digest: str
    _prompt: bytes
    _images: object

    @property
    def images(self):
        return tuple(sorted(self._images))

    def items(self, image):
        return {key: dict(value) for key, value in self._images[image].items()}

    def prompt(self):
        return self._prompt

    def required_paths(self):
        return (self.path,)

    def verify_source(self):
        _require(
            hashlib.sha256(_read(self.path, MAX_BYTES)).hexdigest() == self.digest,
            "source identity changed",
        )

    def validate_campaign(self, terms):
        self.verify_source()
        _require(terms.get("submission_policy") == POLICY, "campaign rule differs")
        _require(isinstance(terms.get("task_prompt"), str), "missing campaign prompt")
        raw = _read(terms["task_prompt"], MAX_PROMPT_BYTES)
        _require(
            raw == self.prompt()
            and hashlib.sha256(raw).hexdigest() == terms.get("task_prompt_sha256"),
            "campaign prompt differs",
        )


def load(path, expected_sha256, tasks):
    """Read a closed, pinned manifest for the exact task -> image map supplied by host."""
    _require(
        isinstance(expected_sha256, str) and HEX256.fullmatch(expected_sha256),
        "requires an external SHA-256 pin",
    )
    path = Path(path)
    raw = _read(path, MAX_BYTES)
    _require(
        hashlib.sha256(raw).hexdigest() == expected_sha256, "source identity differs"
    )
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_float=_number,
            parse_constant=_number,
        )
        _require(
            isinstance(data, dict)
            and set(data)
            == {"schema", "policy", "allowed", "tasks", "images", "prompt_sha256"}
            and type(data["schema"]) is int
            and data["schema"] == 1
            and data["policy"] == POLICY,
            "unsupported schema",
        )
        _require(
            isinstance(data["tasks"], dict) and 1 <= len(data["tasks"]) <= 4096,
            "invalid task inventory",
        )
        for task, image in data["tasks"].items():
            _require(
                TASK_ID.fullmatch(task)
                and isinstance(image, str)
                and IMAGE.fullmatch(image),
                "invalid pinned task image",
            )
        _require(data["tasks"] == tasks, "task image inventory differs")
        _require(
            isinstance(data["images"], dict)
            and set(data["images"]) == set(data["tasks"].values()),
            "image inventory differs",
        )
        images = {
            image: MappingProxyType(
                {
                    key: MappingProxyType(item)
                    for key, item in validate_items(items, data["allowed"]).items()
                }
            )
            for image, items in data["images"].items()
        }
        prompt = render_prompt(data["allowed"])
        _require(
            data["prompt_sha256"] == hashlib.sha256(prompt).hexdigest(),
            "prompt digest differs",
        )
        return Policy(path, expected_sha256, prompt, MappingProxyType(images))
    except (KeyError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("malformed dependency policy") from error
