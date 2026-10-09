"""No model calls: fixed evidence/protocol, durable reservation and replay regressions."""

import hashlib
import json
import unittest

import procontract_compliance_evidence as evidence
import procontract_fixed_auditor_role as role

PROVIDER = {"base_url": "http://127.0.0.1:1/v1", "env_key": "FIXED_AUDITOR_TEST_KEY"}
LIMITS = {"task_launches": 12, "learning_launches": 21, "allocated_seconds": 291600}


def pack(number=0):
    return evidence.EvidencePack(
        hashlib.sha256(str(number).encode()).hexdigest(),
        [
            ("submission", "main.rs", b"fn main() {}\n"),
            ("submission", "compile.sh", b"rustc main.rs\n"),
            ("commands", "commands.json", b"[]"),
            ("image_proof", "image.json", b"{}"),
            ("clean_build", "compile.json", b'{"returncode":0}'),
        ],
        [],
    )


def receipt(value):
    return {
        "schema": 1,
        "pack_sha256": value.digest,
        "submission_sha256": value.submission_sha256,
        "artifacts": {"opaque-run/submission.tar.gz": value.submission_sha256},
    }


def answer(value, status="supported_within_evidence"):
    meta, data = value._sources["f0000"]
    citation = {
        "file_id": "f0000",
        "sha256": meta["sha256"],
        "start": 0,
        "end": 2,
        "quote": "fn",
    }
    return {
        "schema": 1,
        "pack_sha256": value.digest,
        "submission_sha256": value.submission_sha256,
        "reviewed_file_ids": list(value._sources),
        "requirements": {
            key: {"status": status, "citations": [citation]}
            for key in evidence.REQUIREMENTS
        },
        "opaque_files": [],
    }


def serve(service):
    rows = []
    for pack_id, value in service.by_id.items():
        for cursor in range(len(value._sources)):
            args = {"op": "index", "pack_id": pack_id, "cursor": cursor}
            text, success = service.call(args)
            rows.append(
                {
                    "arguments": args,
                    "authorized": True,
                    "success": success,
                    "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )
        for file_id, (meta, data) in value._sources.items():
            if meta["encoding"] == "opaque":
                continue
            offset = 0
            while offset < len(data):
                args = {
                    "op": "read",
                    "pack_id": pack_id,
                    "file_id": file_id,
                    "offset": offset,
                    "max_bytes": 2000,
                }
                text, success = service.call(args)
                rows.append(
                    {
                        "arguments": args,
                        "authorized": True,
                        "success": success,
                        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
                offset = json.loads(text)["next_offset"]
    return rows


class ServiceTests(unittest.TestCase):
    def test_full_service_then_exact_citation_accepts(self):
        service = role.EvidenceService([pack()])
        rows = serve(service)
        result = service.validate(
            role.encoded({"schema": 1, "audits": [answer(service.packs[0])]})
        )
        self.assertEqual((len(rows), result[0]["accepted"]), (10, True))

    def test_prior_coverage_cannot_skip_new_service(self):
        old = role.EvidenceService([pack()])
        serve(old)
        fresh = role.EvidenceService(old.packs)
        result = fresh.validate(
            role.encoded({"schema": 1, "audits": [answer(fresh.packs[0])]})
        )
        self.assertFalse(result[0]["accepted"])

    def test_invalid_path_and_extra_fields_refused(self):
        service = role.EvidenceService([pack()])
        for args in (
            {"op": "read", "pack_id": "../../etc/passwd"},
            {"op": "index", "pack_id": "p0", "cursor": 0, "path": "/etc/passwd"},
            {"op": "index", "pack_id": [], "cursor": 0},
            {"op": "index", "pack_id": "p0", "cursor": True},
        ):
            self.assertFalse(service.call(args)[1])

    def test_forged_citation_and_duplicate_json_rejected(self):
        service = role.EvidenceService([pack()])
        serve(service)
        value = answer(service.packs[0])
        value["requirements"]["rust_from_scratch"]["citations"][0]["quote"] = "xx"
        with self.assertRaises(ValueError):
            service.validate(role.encoded({"schema": 1, "audits": [value]}))
        with self.assertRaises(ValueError):
            service.validate(b'{"schema":1,"schema":1,"audits":[]}')

    def test_eight_pack_identity_order_and_schema_bound(self):
        service = role.EvidenceService([pack(number) for number in range(8)])
        self.assertLessEqual(len(role.encoded(role.output_schema(service.packs))), 3500)
        self.assertLessEqual(len(service.prompt().encode()), 3500)
        serve(service)
        results = [answer(value) for value in service.packs]
        with self.assertRaises(ValueError):
            service.validate(
                role.encoded({"schema": 1, "audits": list(reversed(results))})
            )
        self.assertTrue(
            all(
                row["accepted"]
                for row in service.validate(
                    role.encoded({"schema": 1, "audits": results})
                )
            )
        )

    def test_identical_packs_still_require_independent_id_coverage(self):
        service = role.EvidenceService([pack() for _ in range(8)])
        self.assertEqual(len(service.by_id), 8)
        serve(service)
        result = service.validate(
            role.encoded(
                {"schema": 1, "audits": [answer(value) for value in service.packs]}
            )
        )
        self.assertTrue(all(row["accepted"] for row in result))

    def test_eight_distinct_large_opaque_inventories_use_static_schema(self):
        packs = []
        for number in range(8):
            sources = [
                (meta["kind"], meta["path"], raw)
                for meta, raw in pack(number)._sources.values()
            ]
            sources += [
                (
                    "submission",
                    f"data-{number}-{index}.bin",
                    bytes([255, number, index]),
                )
                for index in range(20 + number)
            ]
            packs.append(
                evidence.EvidencePack(pack(number).submission_sha256, sources, [])
            )
        service = role.EvidenceService(packs)
        self.assertLessEqual(len(role.encoded(role.output_schema(service.packs))), 3500)
        self.assertLessEqual(len(service.prompt().encode()), 3500)
        serve(service)
        audits = []
        for value in service.packs:
            result = answer(value)
            citation = result["requirements"]["rust_from_scratch"]["citations"]
            result["opaque_files"] = [
                {
                    "file_id": key,
                    "sha256": meta["sha256"],
                    "classification": "inert_data_not_dependency",
                    "citations": citation,
                }
                for key, (meta, _) in value._sources.items()
                if meta["encoding"] == "opaque"
            ]
            audits.append(result)
        checked = service.validate(role.encoded({"schema": 1, "audits": audits}))
        self.assertTrue(all(row["accepted"] for row in checked))
        self.assertTrue(
            all(
                "normalized_result_sha256" in row and "result_sha256" not in row
                for row in checked
            )
        )
        audits[0]["opaque_files"].append(audits[0]["opaque_files"][0])
        with self.assertRaises(ValueError):
            service.validate(role.encoded({"schema": 1, "audits": audits}))

    def test_eight_legitimate_build_attempts_can_include_failed_and_missing_script(
        self,
    ):
        # Scripted verdicts test lane eligibility, not the semantic truth of an audit.
        packs = []
        for number in range(8):
            failed = number % 2 == 1
            sources = [
                (meta["kind"], meta["path"], raw)
                for meta, raw in pack(number)._sources.values()
                if meta["kind"] != "clean_build"
                and not (failed and meta["path"] == "compile.sh")
            ]
            build = {
                "command": "chmod +x ./compile.sh && ./compile.sh",
                "returncode": 1 if failed else 0,
                "output": "chmod: compile.sh: No such file" if failed else "",
                "eval_sha256": hashlib.sha256(str(number).encode()).hexdigest(),
            }
            sources.append(
                ("clean_build", "host-canonical-compile.json", role.encoded(build))
            )
            packs.append(
                evidence.EvidencePack(pack(number).submission_sha256, sources, [])
            )
        service = role.EvidenceService(packs)
        serve(service)
        audits = []
        for value in service.packs:
            result = answer(value)
            key, (meta, data) = next(
                (key, row)
                for key, row in value._sources.items()
                if row[0]["kind"] == "clean_build"
            )
            result["requirements"]["authenticated_build_attempt"]["citations"] = [
                {
                    "file_id": key,
                    "sha256": meta["sha256"],
                    "start": 0,
                    "end": len(data),
                    "quote": data.decode(),
                }
            ]
            audits.append(result)
        checked = service.validate(role.encoded({"schema": 1, "audits": audits}))
        self.assertEqual([row["accepted"] for row in checked], [True] * 8)
        audits[1]["requirements"]["no_reference_content_or_reuse"]["status"] = (
            "violation"
        )
        checked = service.validate(role.encoded({"schema": 1, "audits": audits}))
        self.assertEqual(
            [row["accepted"] for row in checked], [True, False] + [True] * 6
        )

    def test_source_derived_role_does_not_accept_evolved_instructions(self):
        value = role.descriptor(PROVIDER)
        value["instructions_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            role.validate_descriptor(value)
        with self.assertRaises(ValueError):
            role.config({**PROVIDER, "instructions": "evolved"})
        with self.assertRaises(ValueError):
            role.validate_descriptor({})


if __name__ == "__main__":
    unittest.main()
