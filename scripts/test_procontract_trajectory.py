import json
import tempfile
import unittest
from pathlib import Path

import procontract_trajectory as trajectory

ORACLE = [r"\./executable"]
MELODY = Path(
    "/home/duozhou/run-artifacts/procontract-rsi-m0-20261001/rsi-campaign-1/runs/"
    "dev-22ef8184d57d-yoav-lavi__melody.f4af9b4/attempt-1"
)
MELODY_THREAD = "01a10b16-1d57-7c91-8b65-586b714b4586"


def rec(second: int, type_: str, payload: dict) -> str:
    return json.dumps(
        {"timestamp": f"2026-10-05T08:00:{second:02d}.000Z", "type": type_, "payload": payload}
    )


def message(second: int, role: str, text: str) -> str:
    kind = "output_text" if role == "assistant" else "input_text"
    content = [{"type": kind, "text": text}]
    return rec(second, "response_item", {"type": "message", "role": role, "content": content})


def call(second: int, call_id: str, code: str) -> str:
    return rec(
        second,
        "response_item",
        {"type": "custom_tool_call", "call_id": call_id, "name": "exec", "input": code},
    )


def output(second: int, call_id: str, text: str) -> str:
    body = [{"type": "input_text", "text": "Script completed\nWall time 0.1 seconds\nOutput:\n"}]
    body.append({"type": "input_text", "text": text})
    return rec(
        second,
        "response_item",
        {"type": "custom_tool_call_output", "call_id": call_id, "output": body},
    )


def tokens(second: int, total: int) -> str:
    usage = {"total_token_usage": {"total_tokens": total}}
    return rec(second, "event_msg", {"type": "token_count", "info": usage})


def exec_code(cmd: str) -> str:
    return "const r = await tools.exec_command({cmd:" + json.dumps(cmd) + ",workdir:\"/w\"});"


def two_turns(note: str) -> list[str]:
    return [
        rec(0, "session_meta", {"id": "t1"}),
        rec(1, "event_msg", {"type": "task_started"}),
        message(1, "developer", "<skills_instructions>boilerplate"),
        message(1, "user", "<environment_context>cwd</environment_context>"),
        message(1, "user", "Build the program."),
        message(2, "assistant", "Looking around."),
        call(3, "c1", exec_code("ls -la")),
        output(4, "c1", "file-a\nfile-b"),
        tokens(4, 100),
        call(5, "c2", exec_code("./executable --help")),
        output(6, "c2", "usage"),
        tokens(6, 250),
        rec(7, "event_msg", {"type": "task_complete", "last_agent_message": "Done."}),
        rec(10, "event_msg", {"type": "task_started"}),
        message(10, "user", note),
        call(11, "c3", exec_code("cargo test")),
        output(12, "c3", "ok"),
        tokens(12, 400),
        rec(13, "compacted", {"message": "Summary: I believed X."}),
        rec(14, "event_msg", {"type": "task_complete", "last_agent_message": "Fixed."}),
    ]


def write_rollout(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\nnot json\n")
    return path


NOTE = '<codex_internal_context source="pro_contract">\nFix the thing.\n</codex_internal_context>'


class ReadTest(unittest.TestCase):
    def events(self, note=NOTE):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(Path(tmp, "rollout-t1.jsonl"), two_turns(note))
            return trajectory.read(path, ORACLE)

    def test_events_come_in_order_with_turn_time_and_tokens(self):
        events = self.events()
        self.assertEqual(
            [e["kind"] for e in events],
            ["turn_start", "user", "message", "call", "call", "turn_end",
             "turn_start", "note", "call", "compaction", "turn_end"],
        )
        self.assertEqual([e["turn"] for e in events], [1] * 6 + [2] * 5)
        self.assertEqual(events[3]["t"], 3.0)
        self.assertEqual([e["tokens"] for e in events if e["kind"] == "call"], [0, 100, 250])
        self.assertEqual(events[5]["text"], "Done.")

    def test_boilerplate_is_skipped_and_the_task_prompt_kept(self):
        events = self.events()
        self.assertEqual([e["text"] for e in events if e["kind"] == "user"], ["Build the program."])

    def test_calls_are_indexed_matched_to_outputs_and_flagged_for_the_oracle(self):
        calls = [e for e in self.events() if e["kind"] == "call"]
        self.assertEqual([c["index"] for c in calls], [1, 2, 3])
        self.assertEqual([c["oracle"] for c in calls], [False, True, False])
        self.assertEqual(calls[0]["output"], "file-a\nfile-b")
        self.assertIn("ls -la", calls[0]["command"])

    def test_a_note_carries_its_text_bytes_and_clipping(self):
        note = next(e for e in self.events() if e["kind"] == "note")
        self.assertEqual(note["text"], NOTE)
        self.assertEqual((note["bytes"], note["clipped"]), (len(NOTE.encode()), False))

    def test_a_clipped_note_is_recognized(self):
        clipped = NOTE.replace("Fix the thing.", "[1234 bytes omitted]\nthe tail")
        note = next(e for e in self.events(clipped) if e["kind"] == "note")
        self.assertTrue(note["clipped"])

    def test_a_compaction_keeps_the_summary(self):
        events = self.events()
        self.assertEqual(
            [e["text"] for e in events if e["kind"] == "compaction"], ["Summary: I believed X."]
        )

    def test_long_output_keeps_head_and_tail(self):
        body = "H" * 3000 + "M" * 5000 + "T" * 3000
        lines = [
            rec(1, "event_msg", {"type": "task_started"}),
            call(2, "c", exec_code("x")),
            output(3, "c", body),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(Path(tmp, "rollout-t1.jsonl"), lines)
            out = trajectory.read(path, ORACLE)[1]["output"]
        self.assertTrue(out.startswith("H" * 2048) and out.endswith("T" * 2048))
        self.assertIn("chars omitted", out)
        self.assertNotIn("M", out)
        self.assertLess(len(out), 4200)

    def test_a_long_command_is_bounded(self):
        lines = [call(2, "c", "x" * 20000)]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(Path(tmp, "rollout-t1.jsonl"), lines)
            command = trajectory.read(path, ORACLE)[0]["command"]
        self.assertLess(len(command), 8300)
        self.assertIn("omitted", command)


class StatsTest(unittest.TestCase):
    def test_counts_turns_and_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(Path(tmp, "rollout-t1.jsonl"), two_turns(NOTE))
            result = trajectory.stats(trajectory.read(path, ORACLE))
        self.assertEqual(
            (result["calls"], result["oracle_calls"], result["tokens"], result["compactions"]),
            (3, 1, 400, 1),
        )
        self.assertEqual(result["wall_secs"], 14)
        self.assertEqual(
            result["turns"],
            [
                {"calls": 2, "oracle_calls": 1, "tokens": 250},
                {"calls": 1, "oracle_calls": 0, "tokens": 150},
            ],
        )
        self.assertEqual(result["notes"], [{"turn": 2, "bytes": len(NOTE.encode()), "clipped": False}])

    def test_no_events_gives_zeros(self):
        result = trajectory.stats([])
        self.assertEqual((result["calls"], result["turns"], result["tokens"]), (0, [], 0))


class RenderTest(unittest.TestCase):
    def rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_rollout(Path(tmp, "rollout-t1.jsonl"), two_turns(NOTE))
            return trajectory.render(trajectory.read(path, ORACLE), "# Run")

    def test_header_legend_and_prefixes(self):
        text = self.rendered()
        self.assertTrue(text.startswith("# Run\n"))
        self.assertIn("reasoning is encrypted", text.lower())
        self.assertIn("[0:00:05] #2 tok=100 [oracle] CALL: ./executable --help", text)
        self.assertIn("TURN 2 START", text)

    def test_notes_and_compactions_are_in_full(self):
        text = self.rendered()
        self.assertIn(NOTE, text)
        self.assertIn("Summary: I believed X.", text)

    def test_excerpts_are_bounded(self):
        events = [
            {"kind": "call", "turn": 1, "t": 1.0, "tokens": 5, "index": 1, "oracle": False,
             "command": "c" * 5000, "output": "o" * 5000},
            {"kind": "turn_end", "turn": 1, "t": 2.0, "tokens": 5, "text": "f" * 9000},
        ]
        text = trajectory.render(events)
        self.assertLess(text.count("c"), 800 + 100)
        self.assertLess(text.count("o"), 600 + 100)
        self.assertLess(text.count("f"), 3100)


class RolloutSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        sessions = self.run / "codex-home" / "sessions" / "2026"
        write_rollout(sessions / "rollout-aaa.jsonl", ["{}"] * 10)
        write_rollout(sessions / "rollout-bbb.jsonl", ["{}"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_largest_when_no_thread_is_given(self):
        self.assertEqual(trajectory.executor_rollout(self.run).name, "rollout-aaa.jsonl")

    def test_the_named_thread_over_the_largest(self):
        self.assertEqual(trajectory.executor_rollout(self.run, "bbb").name, "rollout-bbb.jsonl")

    def test_an_unknown_thread_falls_back_to_the_largest(self):
        self.assertEqual(trajectory.executor_rollout(self.run, "zzz").name, "rollout-aaa.jsonl")

    def test_no_rollout_is_none(self):
        self.assertIsNone(trajectory.executor_rollout(self.run / "absent"))


class WriteTest(unittest.TestCase):
    def test_writes_both_files_and_returns_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, dest = Path(tmp, "run"), Path(tmp, "out")
            write_rollout(run / "codex-home" / "sessions" / "rollout-t1.jsonl", two_turns(NOTE))
            result = trajectory.write(run, dest, ORACLE, "t1")
            lines = (dest / "events.jsonl").read_text().splitlines()
            self.assertEqual(result["calls"], 3)
            self.assertEqual(len(lines), 11)
            self.assertEqual(json.loads(lines[0])["kind"], "turn_start")
            self.assertIn("TURN 1 START", (dest / "trajectory.md").read_text())

    def test_no_rollout_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(trajectory.write(Path(tmp), Path(tmp, "out"), ORACLE))
            self.assertFalse(Path(tmp, "out").exists())


class CopyFinalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name, "ws")
        self.dest = Path(self.tmp.name, "final")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel: str, data: bytes | str):
        path = self.ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())

    def test_text_files_are_copied_in_sorted_order_with_relative_paths(self):
        self.put("src/main.rs", "fn main() {}")
        self.put("README.md", "docs")
        self.put("a/b/c.txt", "é")
        copied, omitted = trajectory.copy_final(self.ws, self.dest)
        self.assertEqual(copied, ["README.md", "a/b/c.txt", "src/main.rs"])
        self.assertEqual(omitted, 0)
        self.assertEqual((self.dest / "a" / "b" / "c.txt").read_text(), "é")

    def test_skip_rules(self):
        self.put("keep.rs", "ok")
        self.put(".git/config", "x")
        self.put("target/debug/x.rs", "x")
        self.put("node_modules/p/i.js", "x")
        self.put("sub/executable", "text but named executable")
        self.put("blob.bin", b"\xff\xfe\x00\x01")
        self.put("nul.txt", b"a\x00b")
        (self.ws / "link.rs").symlink_to(self.ws / "keep.rs")
        (self.ws / "linkdir").symlink_to(self.ws / "sub")
        copied, omitted = trajectory.copy_final(self.ws, self.dest)
        self.assertEqual(copied, ["keep.rs"])
        self.assertEqual(omitted, 0)

    def test_a_file_over_the_file_cap_is_omitted_and_counted(self):
        self.put("big.txt", "x" * 100)
        self.put("small.txt", "x" * 10)
        self.put("bigbin", b"\xff" * 100)
        copied, omitted = trajectory.copy_final(self.ws, self.dest, file_cap=50)
        self.assertEqual((copied, omitted), (["small.txt"], 1))

    def test_nothing_is_added_once_the_total_cap_would_be_exceeded(self):
        for name in "abcd":
            self.put(f"{name}.txt", "x" * 40)
        self.put("e.txt", "x")
        copied, omitted = trajectory.copy_final(self.ws, self.dest, total_cap=100)
        self.assertEqual((copied, omitted), (["a.txt", "b.txt"], 3))

    def test_an_empty_workspace_copies_nothing(self):
        self.ws.mkdir()
        self.assertEqual(trajectory.copy_final(self.ws, self.dest), ([], 0))


@unittest.skipUnless(MELODY.exists(), "the campaign's melody run is not available")
class RealRunTest(unittest.TestCase):
    def test_melody_matches_the_study(self):
        rollout = trajectory.executor_rollout(MELODY, MELODY_THREAD)
        self.assertIn(MELODY_THREAD, rollout.name)
        self.assertEqual(rollout, trajectory.executor_rollout(MELODY))
        result = trajectory.stats(trajectory.read(rollout, [r"\./executable"]))
        self.assertEqual(result["calls"], 425)
        self.assertEqual(len(result["turns"]), 2)
        self.assertEqual(result["compactions"], 2)


if __name__ == "__main__":
    unittest.main()
