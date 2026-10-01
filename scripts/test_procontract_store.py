import os
import tempfile
import unittest
from pathlib import Path

import procontract_store as store


class StoreWrapperTest(unittest.TestCase):
    def test_capture_materialize_and_events_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "ws")
            root.mkdir()
            Path(root, "main.rs").write_text("fn main() {}\n")
            Path(root, "executable").write_text("reference")
            st = Path(tmp, "store")

            captured = store.capture(st, root, ["executable"])
            Path(root, "main.rs").write_text("mutated\n")
            store.materialize(st, captured["subject_hash"], Path(tmp, "out"))
            store.append(st, "assignment", store.identities(), {"run_id": "r1"})

            self.assertEqual(Path(tmp, "out", "main.rs").read_text(), "fn main() {}\n")
            self.assertFalse(Path(tmp, "out", "executable").exists())
            self.assertEqual(
                [e["event"]["body"]["run_id"] for e in store.events(st)], ["r1"]
            )


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    unittest.main()
