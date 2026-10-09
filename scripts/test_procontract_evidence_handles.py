"""Host-issued reference integration through the production evidence service; no model calls."""

import json
import unittest

import procontract_fixed_auditor_role as role
import procontract_compliance_evidence as evidence
from test_procontract_fixed_auditor_role import pack, serve


class HandleTests(unittest.TestCase):
    def setup_service(self, count=1):
        service = role.EvidenceService([pack(index) for index in range(count)])
        serve(service)
        answers = []
        for pack_id, value in service.by_id.items():
            text, success = service.call(
                dict(
                    op="read",
                    pack_id=pack_id,
                    file_id="f0000",
                    offset=0,
                    max_bytes=2000,
                )
            )
            self.assertTrue(success)
            self.assertLessEqual(len(text.encode()), evidence.MAX_RESPONSE)
            handle = json.loads(text)["citation_id"]
            answers.append(
                dict(
                    pack_id=pack_id,
                    reviewed_file_ids=list(value._sources),
                    opaque_files=[],
                    requirements={
                        key: dict(
                            status="supported_within_evidence", citations=[handle]
                        )
                        for key in evidence.REQUIREMENTS
                    },
                )
            )
        return service, dict(schema=2, audits=answers)

    def test_native_v2_needs_no_model_hash_range_or_quote_and_replays(self):
        service, answer = self.setup_service()
        result = service.validate(role.encoded(answer))
        self.assertTrue(result[0]["accepted"])
        self.assertEqual(service.validate(role.encoded(answer)), result)
        self.assertEqual(
            result[0]["native_audit_sha256"], role.digest(answer["audits"][0])
        )

    def test_issued_handle_cannot_cross_pack_or_be_invented(self):
        service, answer = self.setup_service(8)
        self.assertTrue(
            all(row["accepted"] for row in service.validate(role.encoded(answer)))
        )
        finding = answer["audits"][0]["requirements"]["rust_from_scratch"]
        for handle in [
            "c999999",
            answer["audits"][1]["requirements"]["rust_from_scratch"]["citations"][0],
        ]:
            finding["citations"] = [handle]
            with self.assertRaises(ValueError):
                service.validate(role.encoded(answer))

    def test_semantic_unknown_is_not_repaired_by_valid_handles(self):
        service, answer = self.setup_service()
        answer["audits"][0]["requirements"]["no_install_or_external_network"][
            "status"
        ] = "unknown"
        self.assertFalse(service.validate(role.encoded(answer))[0]["accepted"])

    def test_unicode_and_escaped_text_remain_bounded_and_byte_exact(self):
        value = evidence.EvidencePack(
            "a" * 64, [("submission", "data.json", ('"\\\n中文' * 200).encode())], []
        )
        service = role.EvidenceService([value])
        offset = 0
        while offset < len(value._sources["f0000"][1]):
            text, success = service.call(
                dict(
                    op="read",
                    pack_id="p0",
                    file_id="f0000",
                    offset=offset,
                    max_bytes=2000,
                )
            )
            self.assertTrue(success)
            self.assertLessEqual(len(text.encode()), evidence.MAX_RESPONSE)
            response = json.loads(text)
            normalized = service.handles.normalize(
                "p0",
                service.packs[0],
                dict(
                    pack_id="p0",
                    reviewed_file_ids=[],
                    opaque_files=[],
                    requirements={
                        "x": dict(status="unknown", citations=[response["citation_id"]])
                    },
                ),
            )
            service.packs[0].citation(normalized["requirements"]["x"]["citations"][0])
            offset = response["next_offset"]


if __name__ == "__main__":
    unittest.main()
