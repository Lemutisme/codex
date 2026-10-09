"""Portable synthetic native trace transport; the real binding/reader validate its bytes."""

import json

import procontract_native_trace_binding as binding

STORAGE = {
    "mount_id": "4",
    "device": "0:100",
    "max_bytes": binding.PROFILE["max_bytes"],
    "max_inodes": binding.PROFILE["max_inodes"],
    "allocated_bytes": 0,
    "used_inodes": 1,
    "exhausted": False,
}
TRACE = "e3ecbbf6-e106-4a10-958d-fba819f53287"
CALLS = ("0a66763f-006c-44d6-991c-45cfa9204d32", "b5596971-5d97-45a4-923e-142c3244b9f3")


def provision(run, manifest, terms):
    if "native_notice_trace" not in terms:
        return None
    binding.descriptor(run, manifest)
    return {
        "descriptor_sha256": manifest["native_notice_trace"]["sha256"],
        "storage": STORAGE,
    }


class Trace:
    def __init__(self, run, manifest, terms, *, outcome="observed"):
        binding.prepare(run, manifest, terms)
        self.observer = binding.Observer(run, manifest, latest_dispatch=1000000)
        self.run, self.outcome, self.events, self.bundle = run, outcome, [], None

    def request(self, method, params, handle, timeout):
        assert method == "turn/steer"
        thread, turn = params["threadId"], params["expectedTurnId"]
        self.observer.thread_id = thread
        self.bundle = self.run / binding.ROOT / f"trace-{TRACE}-{thread}"
        (self.bundle / "payloads").mkdir(parents=True)
        (self.bundle / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trace_id": TRACE,
                    "rollout_id": thread,
                    "root_thread_id": thread,
                    "started_at_unix_ms": 1000,
                    "raw_event_log": "trace.jsonl",
                    "payloads_dir": "payloads",
                }
            )
        )

        def event(kind, **payload):
            self.events.append(
                {
                    "schema_version": 1,
                    "seq": len(self.events) + 1,
                    "wall_time_unix_ms": 1000 + len(self.events),
                    "rollout_id": thread,
                    "thread_id": thread if kind.startswith("inference_") else None,
                    "codex_turn_id": turn if kind.startswith("inference_") else None,
                    "payload": {"type": kind, **payload},
                }
            )

        event("thread_started", thread_id=thread, agent_path="/root")
        for index, call in enumerate(CALLS):
            inputs = [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Synthetic task"}],
                }
            ]
            if index:
                inputs.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": params["input"][0]["text"],
                            }
                        ],
                    }
                )
            for offset, kind, body in (
                (
                    1,
                    "inference_request",
                    {
                        "input": inputs,
                        "client_metadata": {"thread_id": thread, "turn_id": turn},
                    },
                ),
                (
                    2,
                    "inference_response",
                    {"response_id": f"response-{index}", "output_items": []},
                ),
            ):
                number = index * 2 + offset
                (self.bundle / f"payloads/{number}.json").write_text(json.dumps(body))
                ref = {
                    "raw_payload_id": f"raw_payload:{number}",
                    "kind": {"type": kind},
                    "path": f"payloads/{number}.json",
                }
                if offset == 1:
                    event(
                        "inference_started",
                        inference_call_id=call,
                        thread_id=thread,
                        codex_turn_id=turn,
                        request_payload=ref,
                    )
                else:
                    event(
                        "inference_completed",
                        inference_call_id=call,
                        response_id=f"response-{index}",
                        response_payload=ref,
                    )
        self.write_events(self.events[:2])
        self.observer.before_send({"id": 7, "method": method, "params": params})
        return {"turnId": turn}

    def write_events(self, events):
        (self.bundle / "trace.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events)
        )

    def finish(self, delivery, closed):
        if self.bundle is not None:
            self.write_events(
                self.events if self.outcome == "observed" else self.events[:3]
            )
        return self.observer.after_run(delivery, closed)
