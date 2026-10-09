"""Request-scoped references to slices already served by the fixed evidence service.

The model selects an ID. Only the host constructs hashes, byte ranges and quotes.
Handles carry no judgment and cannot substitute for full inventory/read coverage.
"""

import json

import procontract_compliance_evidence as evidence


class EvidenceHandles:
    def __init__(self):
        self.slices = {}

    def served(self, pack_id, response):
        value = json.loads(response)
        start, end = value["offset"], value["next_offset"]
        # The authenticated file hash remains host-owned; its removal leaves room for
        # the handle without increasing the existing 900-byte tool-output ceiling.
        value.pop("sha256")
        if start != end:
            if len(self.slices) >= 250000:
                raise ValueError("evidence handle budget exhausted")
            handle = f"c{len(self.slices)}"
            self.slices[handle] = (pack_id, value["file_id"], start, end)
            value["citation_id"] = handle
        result = evidence._json(value)
        if len(result.encode()) > evidence.MAX_RESPONSE:
            raise ValueError("evidence handle response exceeds bound")
        return result

    def normalize(self, pack_id, pack, result):
        if (
            not isinstance(result, dict)
            or set(result)
            != {"pack_id", "reviewed_file_ids", "requirements", "opaque_files"}
            or result["pack_id"] != pack_id
        ):
            raise ValueError("evidence handle pack identity differs")

        def citations(handles):
            if not isinstance(handles, list) or not 1 <= len(handles) <= 8:
                raise ValueError("missing/excessive evidence handles")
            resolved = []
            for handle in handles:
                if not isinstance(handle, str) or handle not in self.slices:
                    raise ValueError("unknown or unserved evidence handle")
                owner, file_id, start, end = self.slices[handle]
                if owner != pack_id:
                    raise ValueError("evidence handle belongs to another pack")
                meta, raw = pack._sources[file_id]
                resolved.append(
                    dict(
                        file_id=file_id,
                        sha256=meta["sha256"],
                        start=start,
                        end=end,
                        quote=raw[start:end].decode("utf-8"),
                    )
                )
            return resolved

        requirements = result["requirements"]
        if not isinstance(requirements, dict) or any(
            not isinstance(row, dict) or set(row) != {"status", "citations"}
            for row in requirements.values()
        ):
            raise ValueError("invalid handle findings")
        opaque = result["opaque_files"]
        if not isinstance(opaque, list):
            raise ValueError("invalid handle opaque inventory")
        normalized = []
        for row in opaque:
            if not isinstance(row, dict) or set(row) != {
                "file_id",
                "classification",
                "citations",
            }:
                raise ValueError("invalid handle opaque entry")
            file_id = row["file_id"]
            if not isinstance(file_id, str) or file_id not in pack._sources:
                raise ValueError("unknown opaque entry")
            normalized.append(
                {
                    **row,
                    "sha256": pack._sources[file_id][0]["sha256"],
                    "citations": citations(row["citations"]),
                }
            )
        return dict(
            schema=1,
            pack_sha256=pack.digest,
            submission_sha256=pack.submission_sha256,
            reviewed_file_ids=result["reviewed_file_ids"],
            opaque_files=normalized,
            requirements={
                key: {**row, "citations": citations(row["citations"])}
                for key, row in requirements.items()
            },
        )
