"""Private, finite compliance evidence, not semantic or OS-level enforcement.

The host must authenticate canonical submission/evaluator receipts and image inspection
before calling this module. Only projected compile output (never test feedback) enters
an auditor pack. Every filename, command and file body is untrusted data. Read coverage
proves bytes were served to the tool runtime, not model-visible, read or understood; valid citations do not prove claims.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
from types import MappingProxyType
import zlib

MAX_ARCHIVE = 64 << 20
MAX_TAR = 128 << 20
MAX_FILES = 1024
MAX_FILE = 64 << 20
MAX_TOTAL = 128 << 20
MAX_TEXT = 16 << 20
MAX_COMMANDS = 8 << 20
MAX_EVAL = 64 << 20
MAX_RESULT = 256 << 10
MAX_RESPONSE = 900
REQUIREMENTS = (
    "rust_from_scratch",
    "listed_build_runtime_only",
    "no_install_or_external_network",
    "no_reference_content_or_reuse",
    "authenticated_build_attempt",
)
STATUSES = ("supported_within_evidence", "violation", "unknown")
HEX = re.compile(r"[0-9a-f]{64}")
CAPS = MappingProxyType(
    dict(
        archive_bytes=MAX_ARCHIVE,
        tar_bytes=MAX_TAR,
        archive_entries=MAX_FILES,
        file_bytes=MAX_FILE,
        total_bytes=MAX_TOTAL,
        text_bytes=MAX_TEXT,
        commands_bytes=MAX_COMMANDS,
        eval_bytes=MAX_EVAL,
        result_bytes=MAX_RESULT,
        response_bytes=MAX_RESPONSE,
        read_bytes=2000,
    )
)


def _require(condition, message):
    if not condition:
        raise ValueError(f"compliance evidence: {message}")


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _parse(raw, cap):
    _require(type(raw) is bytes and len(raw) <= cap, "JSON exceeds bound")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=lambda _: _require(False, "nonfinite JSON"),
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("compliance evidence: malformed JSON") from error


def _sha(value):
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _read(path, cap):
    path = Path(path)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), "source must be regular and not linked")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(opened.st_mode)
            and (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "source changed during open",
        )
        raw = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
    _require(
        len(raw) <= cap
        and opened.st_size == after.st_size == len(raw)
        and opened.st_mtime_ns == after.st_mtime_ns,
        "source exceeds bound or changed",
    )
    return raw


def project_clean_build(path, expected_eval_sha256):
    """Project the pinned ProgramBench compile step; caller verifies canonical receipt.

    Absence or ambiguity is an error, not an empty successful build. Output originates
    before hidden tests and is still untrusted submission-controlled text.
    """
    raw = _read(path, MAX_EVAL)
    _require(
        _sha(expected_eval_sha256) and _digest(raw) == expected_eval_sha256,
        "canonical evaluator digest differs",
    )
    value = _parse(raw, MAX_EVAL)
    logs = value.get("log") if isinstance(value, dict) else None
    _require(isinstance(logs, list), "missing step-tagged build log")
    entries = [
        row for row in logs if isinstance(row, dict) and row.get("step") == "compile"
    ]
    _require(len(entries) == 1, "ambiguous or missing compile step")
    row = entries[0]
    _require(
        "branch" not in row
        and row.get("command") == "chmod +x ./compile.sh && ./compile.sh"
        and type(row.get("returncode")) is int
        and isinstance(row.get("output"), str),
        "compile step shape differs",
    )
    _require(len(row["output"]) <= MAX_TEXT, "build output exceeds bound")
    result = {key: row[key] for key in ("command", "returncode", "output")}
    result["eval_sha256"] = expected_eval_sha256
    _require(len(_json(result).encode()) <= MAX_TEXT, "build evidence exceeds bound")
    return result


def _archive(raw):
    compressed = zlib.decompressobj(31)
    try:
        decoded = compressed.decompress(raw, MAX_TAR + 1)
    except zlib.error as error:
        raise ValueError("compliance evidence: invalid gzip") from error
    _require(
        len(decoded) <= MAX_TAR
        and compressed.eof
        and not compressed.unused_data
        and not compressed.unconsumed_tail
        and len(decoded) % 512 == 0,
        "gzip/tar exceeds bound, is truncated, or has trailing data",
    )
    result, seen, offset, total = [], {}, 0, 0
    while offset < len(decoded):
        block = decoded[offset : offset + 512]
        if block == bytes(512):
            _require(
                len(decoded) - offset >= 1024 and not any(decoded[offset:]),
                "trailing archive data or missing end marker",
            )
            for name in seen:
                _require(
                    all(
                        seen.get(str(parent)) != "submission"
                        for parent in PurePosixPath(name).parents
                    ),
                    "tar file is an ancestor",
                )
            return result
        _require(
            block[156:157] in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE),
            "tar links, special files and extensions are unsupported",
        )
        magic = block[257:265]
        _require(magic in (b"ustar\x0000", b"ustar  \x00"), "unsupported tar format")
        _require(
            magic != b"ustar  \x00" or not any(block[345:]),
            "GNU tar extensions unsupported",
        )
        size_field = block[124:136].strip(b" \0")
        _require(all(c in b"01234567" for c in size_field), "non-octal tar size")
        try:
            member = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            parts = [block[:100]]
            if magic == b"ustar\x0000" and block[345:500].rstrip(b"\0"):
                parts.insert(0, block[345:500])
            _require(
                all(
                    not any(part.split(b"\0", 1)[1]) for part in parts if b"\0" in part
                ),
                "hidden bytes in tar name",
            )
            raw_name = b"/".join(part.rstrip(b"\0") for part in parts).decode("utf-8")
        except (tarfile.HeaderError, UnicodeError) as error:
            raise ValueError("compliance evidence: invalid tar header") from error
        directory = block[156:157] == tarfile.DIRTYPE
        name = raw_name.removeprefix("./") if raw_name != "./" else "."
        if directory:
            name = name.removesuffix("/")
        _require(
            name
            and len(name.encode()) <= 192
            and "\\" not in name
            and not any(ord(char) < 32 or ord(char) == 127 for char in name)
            and not PurePosixPath(name).is_absolute()
            and str(PurePosixPath(name)) == name
            and ".." not in PurePosixPath(name).parts
            and (name != "." or (directory and raw_name in (".", "./"))),
            "unsafe or oversized tar path",
        )
        _require(
            name not in seen and len(result) < MAX_FILES,
            "duplicate or excessive tar entries",
        )
        kind = "directory" if directory else "submission"
        seen[name] = kind
        _require(
            type(member.size) is int
            and 0 <= member.size <= MAX_FILE
            and (not directory or member.size == 0)
            and not member.linkname,
            "unsupported tar member size/linkname",
        )
        start, end = offset + 512, offset + 512 + member.size
        next_offset = start + ((member.size + 511) // 512) * 512
        total += member.size
        _require(
            next_offset <= len(decoded)
            and total <= MAX_TOTAL
            and not any(decoded[end:next_offset]),
            "truncated, nonzero padding or excessive tar contents",
        )
        result.append((kind, name, decoded[start:end]))
        offset = next_offset
    raise ValueError("compliance evidence: missing tar end marker")


def _proof(value):
    _require(
        isinstance(value, dict)
        and set(value) == {"image", "policy_sha256", "inspection_sha256", "allowed"},
        "invalid image proof",
    )
    _require(
        isinstance(value["image"], str)
        and value["image"].startswith("sha256:")
        and _sha(value["image"][7:])
        and _sha(value["policy_sha256"])
        and _sha(value["inspection_sha256"]),
        "invalid image proof digest",
    )
    allowed = value["allowed"]
    _require(isinstance(allowed, list) and 1 <= len(allowed) <= 64, "invalid allowlist")
    names = set()
    for row in allowed:
        _require(
            isinstance(row, dict)
            and set(row) == {"name", "kind", "uses", "path", "sha256"},
            "invalid allowlist row",
        )
        _require(
            isinstance(row["name"], str)
            and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", row["name"])
            and row["kind"] in ("tool", "library")
            and _sha(row["sha256"]),
            "invalid allowlist item",
        )
        _require(
            isinstance(row["path"], str)
            and re.fullmatch(
                r"/(usr|bin|sbin|lib|lib64|opt)(/[A-Za-z0-9_.+@:-]+)+", row["path"]
            )
            and len(row["path"]) <= 512
            and ".." not in PurePosixPath(row["path"]).parts,
            "invalid allowlist path",
        )
        uses = row["uses"]
        _require(
            isinstance(uses, list)
            and 1 <= len(uses) <= 3
            and all(
                isinstance(use, str) and use in ("build", "runtime", "exploration")
                for use in uses
            )
            and len(set(uses)) == len(uses),
            "invalid allowlist uses",
        )
        key = row["kind"], row["name"]
        _require(key not in names, "duplicate allowlist item")
        names.add(key)
    return _json(value).encode()


class EvidencePack:
    """Private in-memory full inventory; bounded index/read outputs for the auditor tool runtime."""

    def __init__(self, submission_sha256, sources, unknown):
        _require(
            _sha(submission_sha256)
            and isinstance(unknown, list)
            and all(item == "clean_build_unavailable" for item in unknown)
            and len(unknown) <= 1,
            "invalid pack identity or unknown status",
        )
        self._sources, self._coverage, self._indexed = {}, {}, set()
        _require(
            len(sources) <= MAX_FILES + 3
            and sum(len(raw) for _, _, raw in sources) <= MAX_TOTAL,
            "complete pack exceeds bound",
        )
        text_bytes = 0
        for number, (kind, path, raw) in enumerate(sources):
            _require(len(raw) <= MAX_FILE, "source exceeds bound")
            try:
                raw.decode("utf-8")
                encoding = "utf8"
                text_bytes += len(raw)
                _require(text_bytes <= MAX_TEXT, "complete text evidence exceeds bound")
            except UnicodeError:
                encoding = "opaque"
            file_id = f"f{number:04d}"
            meta = dict(
                file_id=file_id,
                kind=kind,
                path=path,
                encoding=encoding,
                sha256=_digest(raw),
                bytes=len(raw),
            )
            _require(
                len(
                    _json(
                        dict(entries=[meta], next_cursor=number + 1, eof=False)
                    ).encode()
                )
                <= MAX_RESPONSE,
                "manifest row exceeds response bound",
            )
            self._sources[file_id] = (meta, raw)
            if encoding == "utf8":
                self._coverage[file_id] = bytearray(len(raw))
        self.submission_sha256 = submission_sha256
        self.unknown = tuple(unknown)
        self.digest = _digest(
            _json(
                dict(
                    submission_sha256=submission_sha256,
                    sources=[meta for meta, _ in self._sources.values()],
                    unknown=unknown,
                    caps=dict(CAPS),
                )
            ).encode()
        )

    def descriptor(self):
        return _json(
            dict(
                schema=1,
                pack_sha256=self.digest,
                submission_sha256=self.submission_sha256,
                entries=len(self._sources),
                unknown=list(self.unknown),
                caps=dict(CAPS),
            )
        )

    def index(self, cursor=0):
        _require(
            type(cursor) is int and 0 <= cursor <= len(self._sources), "invalid cursor"
        )
        entries = [meta for meta, _ in self._sources.values()][cursor : cursor + 1]
        end = cursor + len(entries)
        self._indexed.update(meta["file_id"] for meta in entries)
        return _json(
            dict(entries=entries, next_cursor=end, eof=end == len(self._sources))
        )

    def read(self, file_id, offset, max_bytes=2000):
        _require(
            isinstance(file_id, str) and file_id in self._sources, "unknown source"
        )
        meta, raw = self._sources[file_id]
        _require(meta["encoding"] == "utf8", "opaque bytes have metadata only")
        _require(
            type(offset) is int
            and 0 <= offset <= len(raw)
            and type(max_bytes) is int
            and 1 <= max_bytes <= 2000,
            "invalid read range",
        )
        _require(
            offset == len(raw) or raw[offset] & 0xC0 != 0x80, "offset splits UTF-8"
        )
        end = min(len(raw), offset + max_bytes)
        while True:
            try:
                text = raw[offset:end].decode("utf-8")
            except UnicodeError:
                end -= 1
                continue
            result = _json(
                dict(
                    file_id=file_id,
                    sha256=meta["sha256"],
                    offset=offset,
                    next_offset=end,
                    eof=end == len(raw),
                    text=text,
                )
            )
            if len(result.encode()) <= MAX_RESPONSE:
                break
            end -= 1
        _require(
            end > offset or offset == len(raw),
            "max_bytes splits UTF-8; request more bytes",
        )
        self._coverage[file_id][offset:end] = bytes([1]) * (end - offset)
        return result

    def citation(self, value):
        _require(
            isinstance(value, dict)
            and set(value) == {"file_id", "sha256", "start", "end", "quote"},
            "invalid citation fields",
        )
        file_id = value["file_id"]
        _require(
            isinstance(file_id, str) and file_id in self._sources,
            "unknown citation source",
        )
        meta, raw = self._sources[file_id]
        start, end, quote = value["start"], value["end"], value["quote"]
        _require(
            meta["encoding"] == "utf8"
            and value["sha256"] == meta["sha256"]
            and type(start) is int
            and type(end) is int
            and 0 <= start < end <= len(raw)
            and end - start <= 2000
            and isinstance(quote, str),
            "invalid citation identity/range",
        )
        _require(quote.encode("utf-8") == raw[start:end], "citation quote differs")


def build_pack(archive, expected_submission_sha256, *, commands, proof, clean_build):
    """Consume host-projected commands, authenticated proof and optional build projection.

    Command records have exactly command/exit_code fields, without output or scores.
    The caller must supply the complete top-level command sequence, not model summaries.
    Missing compile.sh or nonzero compile status is performance evidence, not automatic
    noncompliance. Canonical validity remains the caller's authenticated prerequisite;
    this pack neither changes validity nor supplies a replacement score.
    """
    raw = _read(archive, MAX_ARCHIVE)
    _require(
        _sha(expected_submission_sha256) and _digest(raw) == expected_submission_sha256,
        "canonical submission digest differs",
    )
    sources = _archive(raw)
    _require(
        isinstance(commands, list) and len(commands) <= 4096,
        "command inventory exceeds bound",
    )
    command_parts, command_bytes = [], 2
    for row in commands:
        _require(
            isinstance(row, dict)
            and set(row) == {"command", "exit_code"}
            and isinstance(row["command"], str)
            and len(row["command"]) <= 65536
            and len(row["command"].encode()) <= 65536
            and (row["exit_code"] is None or type(row["exit_code"]) is int),
            "invalid command record",
        )
        part = _json(row).encode()
        command_bytes += len(part) + bool(command_parts)
        _require(command_bytes <= MAX_COMMANDS, "command evidence exceeds bound")
        command_parts.append(part)
    sources += [
        (
            "commands",
            "host-top-level-commands.json",
            b"[" + b",".join(command_parts) + b"]",
        ),
        ("image_proof", "host-image-allowlist.json", _proof(proof)),
    ]
    unknown = []
    if clean_build is None:
        unknown.append("clean_build_unavailable")
    else:
        _require(
            isinstance(clean_build, dict)
            and set(clean_build) == {"command", "returncode", "output", "eval_sha256"}
            and clean_build["command"] == "chmod +x ./compile.sh && ./compile.sh"
            and type(clean_build["returncode"]) is int
            and isinstance(clean_build["output"], str)
            and len(clean_build["output"]) <= MAX_TEXT
            and _sha(clean_build["eval_sha256"]),
            "invalid clean-build projection",
        )
        sources.append(
            ("clean_build", "host-canonical-compile.json", _json(clean_build).encode())
        )
    return EvidencePack(expected_submission_sha256, sources, unknown)


def validate_result(pack, raw):
    """Validate fixed auditor output and tool-runtime served coverage; not the truth of its verdicts."""
    result = _parse(raw, MAX_RESULT)
    _require(
        isinstance(result, dict)
        and set(result)
        == {
            "schema",
            "pack_sha256",
            "submission_sha256",
            "reviewed_file_ids",
            "requirements",
            "opaque_files",
        },
        "invalid auditor result fields",
    )
    _require(
        type(result["schema"]) is int
        and result["schema"] == 1
        and result["pack_sha256"] == pack.digest
        and result["submission_sha256"] == pack.submission_sha256,
        "auditor result identity differs",
    )
    reviewed = result["reviewed_file_ids"]
    _require(
        isinstance(reviewed, list)
        and all(isinstance(x, str) for x in reviewed)
        and len(reviewed) == len(set(reviewed))
        and set(reviewed) == set(pack._sources),
        "auditor inventory coverage differs",
    )
    findings = result["requirements"]
    _require(
        isinstance(findings, dict) and set(findings) == set(REQUIREMENTS),
        "requirement coverage differs",
    )
    supported = True
    for finding in findings.values():
        _require(
            isinstance(finding, dict)
            and set(finding) == {"status", "citations"}
            and finding["status"] in STATUSES,
            "invalid requirement finding",
        )
        citations = finding["citations"]
        _require(
            isinstance(citations, list) and 1 <= len(citations) <= 8,
            "missing/excessive citations",
        )
        for citation in citations:
            pack.citation(citation)
        supported &= finding["status"] == "supported_within_evidence"
    opaque = result["opaque_files"]
    expected = {
        key for key, (meta, _) in pack._sources.items() if meta["encoding"] == "opaque"
    }
    _require(
        isinstance(opaque, dict) and set(opaque) == expected,
        "opaque inventory coverage differs",
    )
    for file_id, finding in opaque.items():
        _require(
            isinstance(finding, dict)
            and set(finding) == {"sha256", "classification", "citations"}
            and finding["sha256"] == pack._sources[file_id][0]["sha256"]
            and finding["classification"]
            in ("inert_data_not_dependency", "violation", "unknown"),
            "invalid opaque classification",
        )
        citations = finding["citations"]
        _require(
            isinstance(citations, list) and 1 <= len(citations) <= 8,
            "opaque finding requires citations",
        )
        for citation in citations:
            pack.citation(citation)
        if finding["classification"] == "inert_data_not_dependency":
            _require(
                any(
                    pack._sources[citation["file_id"]][0]["kind"]
                    in ("submission", "clean_build")
                    for citation in citations
                ),
                "inert binary claim requires build/source evidence",
            )
        supported &= finding["classification"] == "inert_data_not_dependency"
    complete = all(all(coverage) for coverage in pack._coverage.values())
    inventory_complete = pack._indexed == set(pack._sources)
    return dict(
        schema=1,
        pack_sha256=pack.digest,
        submission_sha256=pack.submission_sha256,
        result_sha256=_digest(raw),
        accepted=bool(
            supported and complete and inventory_complete and not pack.unknown
        ),
        served_text_complete=complete,
        served_inventory_complete=inventory_complete,
        evidence_unknown=list(pack.unknown),
        scope="finite fixed-auditor judgment; citations and tool-runtime service are host-checked, semantics are not",
    )
