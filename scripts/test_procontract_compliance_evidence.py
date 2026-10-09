"""Discoverable fixture coverage for finite evidence admission; no provider calls."""

import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import procontract_compliance_evidence as evidence


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(entries):
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w", format=tarfile.USTAR_FORMAT) as output:
        for name, content, kind in entries:
            row = tarfile.TarInfo(name)
            row.type, row.size = kind, len(content)
            output.addfile(row, io.BytesIO(content))
    return gzip.compress(target.getvalue(), mtime=0)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "submission.tar.gz"
        self.raw = archive(
            [
                (".", b"", tarfile.DIRTYPE),
                (
                    "./compile.sh",
                    b"#!/bin/sh\nrustc main.rs -o executable\n",
                    tarfile.REGTYPE,
                ),
                ("./main.rs", b'fn main() { println!("hello"); }\n', tarfile.REGTYPE),
                ("./docs.gif", b"GIF\xff\x00", tarfile.REGTYPE),
            ]
        )
        self.path.write_bytes(self.raw)
        self.proof = dict(
            image="sha256:" + "a" * 64,
            policy_sha256="b" * 64,
            inspection_sha256="c" * 64,
            allowed=[
                dict(
                    name="rustc",
                    kind="tool",
                    uses=["build"],
                    path="/usr/bin/rustc",
                    sha256="d" * 64,
                )
            ],
        )
        self.build = dict(
            command="chmod +x ./compile.sh && ./compile.sh",
            returncode=0,
            output="",
            eval_sha256="e" * 64,
        )
        self.commands = [dict(command="rustc main.rs -o /tmp/probe", exit_code=0)]

    def pack(self, **kwargs):
        return evidence.build_pack(
            self.path,
            digest(self.path.read_bytes()),
            **dict(
                commands=self.commands,
                proof=self.proof,
                clean_build=self.build,
                **kwargs,
            ),
        )

    def deliver(self, pack):
        for cursor in range(len(pack._sources)):
            pack.index(cursor)
        for file_id, (meta, raw) in pack._sources.items():
            if meta["encoding"] != "utf8":
                continue
            offset = 0
            while offset < len(raw):
                output = pack.read(file_id, offset)
                self.assertLessEqual(len(output.encode()), 900)
                value = json.loads(output)
                self.assertEqual(
                    raw[offset : value["next_offset"]].decode(), value["text"]
                )
                offset = value["next_offset"]

    def result(self, pack):
        meta, raw = next(
            (meta, raw)
            for meta, raw in pack._sources.values()
            if meta["path"] == "compile.sh"
        )
        citation = dict(
            file_id=meta["file_id"],
            sha256=meta["sha256"],
            start=0,
            end=len(raw),
            quote=raw.decode(),
        )
        return dict(
            schema=1,
            pack_sha256=pack.digest,
            submission_sha256=pack.submission_sha256,
            reviewed_file_ids=list(pack._sources),
            requirements={
                name: dict(status="supported_within_evidence", citations=[citation])
                for name in evidence.REQUIREMENTS
            },
            opaque_files={
                key: dict(
                    sha256=meta["sha256"],
                    classification="inert_data_not_dependency",
                    citations=[citation],
                )
                for key, (meta, _) in pack._sources.items()
                if meta["encoding"] == "opaque"
            },
        )

    def validate(self, pack, result):
        return evidence.validate_result(pack, json.dumps(result).encode())

    def test_full_inventory_and_explicit_opaque_judgment_gate(self):
        pack = self.pack()
        self.deliver(pack)
        result = self.result(pack)
        receipt = self.validate(pack, result)
        self.assertEqual(
            receipt,
            dict(
                schema=1,
                pack_sha256=pack.digest,
                submission_sha256=digest(self.raw),
                result_sha256=digest(json.dumps(result).encode()),
                accepted=True,
                served_text_complete=True,
                served_inventory_complete=True,
                evidence_unknown=[],
                scope="finite fixed-auditor judgment; citations and tool-runtime service are host-checked, semantics are not",
            ),
        )
        self.assertEqual(
            [meta["path"] for meta, _ in pack._sources.values()],
            [
                ".",
                "compile.sh",
                "main.rs",
                "docs.gif",
                "host-top-level-commands.json",
                "host-image-allowlist.json",
                "host-canonical-compile.json",
            ],
        )

    def test_declared_coverage_without_delivery_cannot_pass(self):
        pack = self.pack()
        result = self.validate(pack, self.result(pack))
        self.assertFalse(result["accepted"])
        self.assertFalse(result["served_text_complete"])

    def test_claimed_inventory_without_served_metadata_cannot_pass(self):
        pack = self.pack()
        for file_id, (meta, raw) in pack._sources.items():
            if meta["encoding"] == "utf8":
                offset = 0
                while offset < len(raw):
                    offset = json.loads(pack.read(file_id, offset))["next_offset"]
        result = self.validate(pack, self.result(pack))
        self.assertTrue(result["served_text_complete"])
        self.assertFalse(result["served_inventory_complete"])
        self.assertFalse(result["accepted"])

    def test_opaque_unknown_or_violation_cannot_pass(self):
        pack = self.pack()
        self.deliver(pack)
        for status in ("unknown", "violation"):
            result = self.result(pack)
            next(iter(result["opaque_files"].values()))["classification"] = status
            self.assertFalse(self.validate(pack, result)["accepted"])
        with self.assertRaises(ValueError):
            pack.read("f0003", 0)

    def test_binary_inert_claim_requires_actual_build_or_source_citation(self):
        pack = self.pack()
        self.deliver(pack)
        result = self.result(pack)
        meta, raw = next(
            (meta, raw)
            for meta, raw in pack._sources.values()
            if meta["kind"] == "image_proof"
        )
        finding = next(iter(result["opaque_files"].values()))
        finding["citations"] = [
            dict(
                file_id=meta["file_id"],
                sha256=meta["sha256"],
                start=0,
                end=len(raw),
                quote=raw.decode(),
            )
        ]
        with self.assertRaises(ValueError):
            self.validate(pack, result)

    def test_all_five_requirements_have_exact_coverage(self):
        pack = self.pack()
        self.deliver(pack)
        for status in ("unknown", "violation"):
            result = self.result(pack)
            result["requirements"]["rust_from_scratch"]["status"] = status
            self.assertFalse(self.validate(pack, result)["accepted"])
        for key in evidence.REQUIREMENTS:
            result = self.result(pack)
            del result["requirements"][key]
            with self.assertRaises(ValueError):
                self.validate(pack, result)

    def test_binding_coverage_and_citation_forgery_rejected(self):
        pack = self.pack()
        self.deliver(pack)
        mutations = [
            lambda r: r.update(pack_sha256="0" * 64),
            lambda r: r.update(submission_sha256="0" * 64),
            lambda r: r.update(schema=True),
            lambda r: r["reviewed_file_ids"].pop(),
            lambda r: r["reviewed_file_ids"].append("f0000"),
            lambda r: r["opaque_files"].clear(),
        ]
        for mutate in mutations:
            result = self.result(pack)
            mutate(result)
            with self.assertRaises(ValueError):
                self.validate(pack, result)
        for key, value in (
            ("sha256", "0" * 64),
            ("quote", "invented"),
            ("start", True),
            ("end", 10000),
            ("file_id", "../secret"),
            ("unknown", "field"),
        ):
            result = copy.deepcopy(self.result(pack))
            result["requirements"]["rust_from_scratch"]["citations"][0][key] = value
            with self.assertRaises(ValueError):
                self.validate(pack, result)

    def test_missing_or_failed_clean_build_explicitly_blocks(self):
        for clean, unknown in (
            (None, "clean_build_unavailable"),
            ({**self.build, "returncode": 1}, "clean_build_failed"),
        ):
            pack = evidence.build_pack(
                self.path,
                digest(self.raw),
                commands=self.commands,
                proof=self.proof,
                clean_build=clean,
            )
            self.deliver(pack)
            receipt = self.validate(pack, self.result(pack))
            self.assertEqual(
                (receipt["accepted"], receipt["evidence_unknown"]), (False, [unknown])
            )

    def test_read_json_escaping_unicode_and_arbitrary_ranges_remain_bounded(self):
        raw = ('\\"\n\x00☃🙂' * 1500).encode()
        pack = evidence.EvidencePack("a" * 64, [("submission", "a.rs", raw)], [])
        self.deliver(pack)
        self.assertTrue(all(pack._coverage["f0000"]))
        snowman = raw.index("☃".encode())
        with self.assertRaises(ValueError):
            pack.read("f0000", snowman + 1)
        with self.assertRaises(ValueError):
            pack.read("f0000", snowman, 1)
        self.assertEqual(json.loads(pack.read("f0000", len(raw)))["text"], "")
        for offset, size in ((True, 10), (-1, 10), (0, True), (0, 2001), (0, 0)):
            with self.assertRaises(ValueError):
                pack.read("f0000", offset, size)

    def test_index_paging_never_omits_entries_and_fits_bound(self):
        pack = self.pack()
        rows, cursor = [], 0
        while True:
            output = pack.index(cursor)
            self.assertLessEqual(len(output.encode()), 900)
            value = json.loads(output)
            rows += value["entries"]
            cursor = value["next_cursor"]
            if value["eof"]:
                break
        self.assertEqual(rows, [meta for meta, _ in pack._sources.values()])
        self.assertLessEqual(len(pack.descriptor().encode()), 900)
        self.assertEqual(
            json.loads(pack.index(cursor)),
            dict(entries=[], next_cursor=cursor, eof=True),
        )

    def test_safe_tar_path_types_duplicates_and_trailing_data(self):
        for name, kind in (
            ("../a", tarfile.REGTYPE),
            ("/a", tarfile.REGTYPE),
            ("a/../b", tarfile.REGTYPE),
            ("a//b", tarfile.REGTYPE),
            ("a\\b", tarfile.REGTYPE),
            ("././a", tarfile.REGTYPE),
            ("a", tarfile.SYMTYPE),
            ("a", tarfile.LNKTYPE),
            ("a", tarfile.FIFOTYPE),
            ("a", tarfile.CHRTYPE),
            ("a", tarfile.GNUTYPE_SPARSE),
            ("a", tarfile.XHDTYPE),
        ):
            with self.subTest(name=name, kind=kind), self.assertRaises(ValueError):
                evidence._archive(archive([(name, b"", kind)]))
        with self.assertRaises(ValueError):
            evidence._archive(
                archive([("a", b"", tarfile.REGTYPE), ("./a", b"", tarfile.REGTYPE)])
            )
        with self.assertRaises(ValueError):
            evidence._archive(gzip.compress(gzip.decompress(self.raw) + b"X" * 512))
        with self.assertRaises(ValueError):
            evidence._archive(
                gzip.compress(gzip.decompress(self.raw) + gzip.decompress(self.raw))
            )

    def test_physical_tar_edge_cases_do_not_hide_members(self):
        for rows in (
            [("x", b"x", tarfile.REGTYPE), ("x/y", b"y", tarfile.REGTYPE)],
            [("x/y", b"y", tarfile.REGTYPE), ("x", b"x", tarfile.REGTYPE)],
            [("./x//", b"", tarfile.DIRTYPE)],
            [("./.", b"", tarfile.DIRTYPE)],
            [("././", b"", tarfile.DIRTYPE)],
            [("x/", b"", tarfile.AREGTYPE)],
            [("x", b"x", tarfile.GNUTYPE_LONGNAME)],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                evidence._archive(archive(rows))
        with self.assertRaises(ValueError):
            evidence._archive(self.raw + self.raw)
        with self.assertRaises(ValueError):
            evidence._archive(self.raw + b"trailing gzip junk")
        decoded = bytearray(gzip.decompress(archive([("x", b"a", tarfile.REGTYPE)])))
        decoded[513] = 1
        with self.assertRaises(ValueError):
            evidence._archive(gzip.compress(decoded))
        with self.assertRaises(ValueError):
            evidence._archive(gzip.compress(bytes(decoded[:1024])))
        target = io.BytesIO()
        with tarfile.open(
            fileobj=target, mode="w", format=tarfile.GNU_FORMAT
        ) as output:
            row = tarfile.TarInfo("./")
            row.type = tarfile.DIRTYPE
            output.addfile(row)
            row = tarfile.TarInfo("./compile.sh")
            row.size = 1
            output.addfile(row, io.BytesIO(b"x"))
        self.assertEqual(
            evidence._archive(gzip.compress(target.getvalue())),
            [("directory", ".", b""), ("submission", "compile.sh", b"x")],
        )

    def test_submission_and_host_projection_shapes_exclude_extra_fields(self):
        self.commands[0]["score"] = 1
        with self.assertRaises(ValueError):
            self.pack()
        del self.commands[0]["score"]
        self.proof["arm"] = "candidate"
        with self.assertRaises(ValueError):
            self.pack()
        del self.proof["arm"]
        self.build["hidden_test_feedback"] = "secret"
        with self.assertRaises(ValueError):
            self.pack()
        del self.build["hidden_test_feedback"]
        self.path.write_bytes(archive([("main.rs", b"fn main() {}", tarfile.REGTYPE)]))
        with self.assertRaises(ValueError):
            self.pack()

    def test_all_hard_caps_fail_closed_without_partial_pack(self):
        for name, bound in (
            ("MAX_ARCHIVE", 1),
            ("MAX_TAR", 512),
            ("MAX_FILES", 1),
            ("MAX_FILE", 1),
            ("MAX_TOTAL", 1),
            ("MAX_TEXT", 1),
        ):
            with (
                self.subTest(name=name),
                patch.object(evidence, name, bound),
                self.assertRaises(ValueError),
            ):
                self.pack()

    def test_command_json_escape_expansion_is_bounded_before_join(self):
        self.commands = [dict(command="\x00" * 20, exit_code=0) for _ in range(4)]
        with patch.object(evidence, "MAX_COMMANDS", 256), self.assertRaises(ValueError):
            self.pack()

    def test_archive_digest_and_symlink_are_rejected(self):
        with self.assertRaises(ValueError):
            evidence.build_pack(
                self.path,
                "0" * 64,
                commands=self.commands,
                proof=self.proof,
                clean_build=self.build,
            )
        link = self.path.with_name("linked.tar.gz")
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            evidence.build_pack(
                link,
                digest(self.raw),
                commands=self.commands,
                proof=self.proof,
                clean_build=self.build,
            )

    def test_caps_are_disclosed_and_bound_without_opaque_text_penalty(self):
        pack = evidence.EvidencePack(
            "a" * 64,
            [
                ("submission", "compile.sh", b"rustc main.rs"),
                ("submission", "demo.gif", b"\xff" * 4096),
            ],
            [],
        )
        descriptor = json.loads(pack.descriptor())
        self.assertEqual(descriptor["caps"], dict(evidence.CAPS))
        self.assertLessEqual(len(pack.descriptor().encode()), 900)
        with patch.object(evidence, "MAX_TEXT", 32):
            evidence.EvidencePack(
                "a" * 64,
                [
                    ("submission", "main.rs", b"x" * 32),
                    ("submission", "demo.gif", b"\xff" * 4096),
                ],
                [],
            )
            with self.assertRaises(ValueError):
                evidence.EvidencePack("a" * 64, [("submission", "a", b"x" * 33)], [])

    def test_pack_binds_commands_proof_and_binary_contents(self):
        old = self.pack().digest
        self.commands[0]["command"] += " --version"
        self.assertNotEqual(old, self.pack().digest)
        old = self.pack().digest
        self.proof["allowed"][0]["sha256"] = "f" * 64
        self.assertNotEqual(old, self.pack().digest)
        old = self.pack().digest
        self.path.write_bytes(
            archive(
                [
                    ("compile.sh", b"x", tarfile.REGTYPE),
                    ("docs.gif", b"\xff", tarfile.REGTYPE),
                ]
            )
        )
        self.assertNotEqual(old, self.pack().digest)

    def test_result_duplicate_json_keys_rejected(self):
        pack = self.pack()
        raw = json.dumps(self.result(pack)).encode()
        with self.assertRaises(ValueError):
            evidence.validate_result(pack, b'{"schema":1,' + raw[1:])

    def test_project_only_compile_and_exclude_hidden_fields(self):
        raw = json.dumps(
            dict(
                test_results=["HIDDEN"],
                score=0.999,
                log=[
                    dict(
                        step="compile",
                        command=self.build["command"],
                        returncode=0,
                        output="compile warning\n",
                        wall_time=1,
                    ),
                    dict(step="tests", branch="HIDDEN", output="SECRET"),
                ],
            )
        ).encode()
        path = self.path.with_name("canonical.eval.json")
        path.write_bytes(raw)
        projected = evidence.project_clean_build(path, digest(raw))
        self.assertEqual(
            projected,
            dict(
                command=self.build["command"],
                returncode=0,
                output="compile warning\n",
                eval_sha256=digest(raw),
            ),
        )
        self.assertNotIn("HIDDEN", json.dumps(projected))
        self.assertNotIn("SECRET", json.dumps(projected))
        with self.assertRaises(ValueError):
            evidence.project_clean_build(path, "0" * 64)

    def test_compile_projection_missing_ambiguous_branch_and_shape_unknown(self):
        compile_row = dict(
            step="compile", command=self.build["command"], returncode=0, output=""
        )
        for logs in (
            [],
            [compile_row, compile_row],
            [{**compile_row, "branch": "hidden"}],
            [{**compile_row, "returncode": True}],
            [{**compile_row, "command": "other"}],
        ):
            raw = json.dumps(dict(log=logs)).encode()
            path = self.path.with_name("canonical.eval.json")
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                evidence.project_clean_build(path, digest(raw))


if __name__ == "__main__":
    unittest.main()
