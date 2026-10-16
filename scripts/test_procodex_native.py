"""Opt-in real native/controller/evidence integration, exclusively against a local fake provider.

Set PROCODEX_NATIVE_PACKAGE and PROCODEX_TEST_IMAGE; no real credential or model is used.
"""

import http.server
import contextlib
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import tempfile
import threading
import time
import unittest

import procodex
from procontract_benchmark_runner import AppServer


def text_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from text_values(item)
    elif isinstance(value, str):
        yield value
        if value.startswith(("{", "[")):
            try:
                yield from text_values(json.loads(value))
            except ValueError:
                pass


def custom_call(body, code, name):
    roots = list(body.get("tools", []))
    for value in body.get("input", []):
        if value.get("type") == "additional_tools":
            roots.extend(value.get("tools", []))

    def walk(items, namespace=None):
        for item in items:
            if item.get("type") == "namespace":
                yield from walk(item.get("tools", []), item["name"])
            elif item.get("name") == "exec":
                yield item, namespace

    found = list(walk(roots))
    if len(found) != 1:
        raise AssertionError("one code-mode exec expected")
    tool, namespace = found[0]
    if tool["type"] != "custom":
        raise AssertionError("custom exec expected")
    return dict(
        type="custom_tool_call",
        call_id=name,
        name="exec",
        input=code,
        **({"namespace": namespace} if namespace else {}),
    )


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE"),
    "set native package for the isolated no-model integration",
)
class NativeEvidenceTest(unittest.TestCase):
    def test_real_executor_and_reviewer_use_frozen_handles(self):
        succession = getattr(self, "succession_fixture", False)
        probe_fixture = getattr(self, "probe_fixture", False)
        scoped_review = getattr(self, "scoped_review_fixture", False)
        partial_review = getattr(self, "partial_review_fixture", False)
        computation = getattr(self, "computation_fixture", False)
        dialogue_probe = getattr(self, "dialogue_probe_fixture", False)
        partial_checks = getattr(self, "partial_checks_fixture", False)
        repair_review = scoped_review or partial_review
        task_text = getattr(self, "task_text", "Make answer.txt contain ready.")
        package = Path(os.environ["PROCODEX_NATIVE_PACKAGE"]).resolve()
        image = os.environ["PROCODEX_TEST_IMAGE"]
        with tempfile.TemporaryDirectory(prefix="procodex-native-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "answer.txt").write_text("not ready\n")
            if computation:
                import io, struct, zipfile
                header=b"{'descr': '<f8', 'fortran_order': False, 'shape': (3,), }\n"
                output=io.BytesIO()
                with zipfile.ZipFile(output,"w") as archive:
                    archive.writestr("x.npy",b"\x93NUMPY\x01\x00"+struct.pack("<H",len(header))+header+struct.pack("<3d",1.,2.,3.))
                (workspace/"numbers.npz").write_bytes(output.getvalue())
            if partial_review:
                (workspace/"numeric-attachment.bin").write_bytes(b"\x00\xffunknown-format")
            if dialogue_probe:
                program = '''#!/usr/local/bin/python3
import os,sys,time
from pathlib import Path
if '--help' in sys.argv:
 print('bounded dialog reference');sys.exit(0)
with open('/dev/tty','r+b',buffering=0) as tty:
 for query,reply in [(b'CAP?',b'supported\\n'),(b'PIXELS?',b'800x240\\n')]:
  tty.write(query)
  assert tty.readline()==reply
if 'block' in sys.argv:time.sleep(30)
print(VALUE)
'''
                for name, value in [('reference.py',"'ready'"),('candidate.py',"Path(__file__).resolve().with_name('answer.txt').read_text().strip()")]:
                    (workspace/name).write_text(program.replace('VALUE',value));(workspace/name).chmod(0o755)
            if probe_fixture:
                documentation = "Documented interface: return ready. 文档\n" * 2700
                self.assertTrue(96_000 < len(documentation.encode()) < 119_000)
                (workspace / "README.md").write_text(documentation)
            source = root / "source"
            source.mkdir()
            counts = {}
            worker_keys = {}
            requests = []
            errors = []
            review_code = r"""
function decode(x) {
 if (typeof x === "string") { try { return decode(JSON.parse(x)); } catch (_) { return x; } }
 if (Array.isArray(x)) return decode(x[0]);
 if (x && (x.source_id !== undefined || x.entry !== undefined)) return x;
 if (x && x.text !== undefined) return decode(x.text);
 if (x && x.content !== undefined) return decode(x.content);
 if (x && x.content_items !== undefined) return decode(x.content_items);
 if (x && x.output !== undefined) return decode(x.output);
 return x;
}
for (const source of ["human_request", "contract_terms"]) {
 let offset = 0;
 for (let i = 0; i < 100; i++) {
  const value = decode(await tools.read_evidence({op:"read", source_id:source, offset}));
  if (value.eof) break; offset = value.next_offset;
 }
}
let denied;
try { denied = decode(await tools.read_evidence({op:"read",source_id:"/etc/passwd",offset:0})); }
catch (error) { denied = String(error); }
let id;
for (let offset = 0; offset < 50;) {
 const value = decode(await tools.read_evidence({op:"index",source_id:"",offset}));
 if (value.entry && value.entry.path === "answer.txt") { id = value.entry.source_id; break; }
 if (value.eof) break; offset = value.next_offset;
}
const artifact = decode(await tools.read_evidence({op:"read",source_id:id,offset:0}));
text({fixtureCitation:artifact.citation_id, artifact:artifact.text, denied});
"""
            if computation:
                review_code = review_code.replace('text({fixtureCitation:artifact.citation_id, artifact:artifact.text, denied});',r'''
let binary;
for (let offset=0; offset<50;) {
 const page=decode(await tools.read_evidence({op:"index",source_id:"",offset}));
 if (page.entry?.path==="numbers.npz") {binary=page.entry.source_id;break;}
 if(page.eof)break;offset=page.next_offset;
}
if(!binary)throw new Error("binary source missing");
const code="import struct,zipfile\nfrom pathlib import Path\nassert Path('/evidence/"+id.replace(":","-")+"').read_text().strip()=='ready'\ndata=zipfile.ZipFile('/evidence/"+binary.replace(":","-")+"').read('x.npy')\nn=struct.unpack('<H',data[8:10])[0]\nassert struct.unpack('<3d',data[10+n:])==(1.,2.,3.)\nprint('ready: frozen numeric sum is 6')\n";
const computation=decode(await tools.inspect_evidence({source_ids:[id,binary],requirements:["R1"],python:code}));
if(computation.execution_state!=="completed")throw new Error(JSON.stringify(computation));
let result="", citation;
for(let offset=0,i=0;i<100;i++) {
 const page=decode(await tools.read_evidence({op:"read",source_id:computation.source_id,offset}));
 result+=page.text;citation=page.citation_id;
 if(page.eof)break;offset=page.next_offset;
}
const checked=JSON.parse(result);
if(!checked.stdout.includes("sum is 6"))throw new Error("wrong frozen data");
text({fixtureCitation:citation,artifact:artifact.text,denied,frozenComputation:true,computation:checked});
''')
            successor_recall = r"""
function decode(x) {
 if (typeof x === "string") { try { return decode(JSON.parse(x)); } catch (_) { return x; } }
 if (Array.isArray(x)) return decode(x[0]);
 if (x && (x.entries !== undefined || x.handle !== undefined)) return x;
 if (x && x.text !== undefined) return decode(x.text);
 if (x && x.content !== undefined) return decode(x.content);
 if (x && x.content_items !== undefined) return decode(x.content_items);
 if (x && x.output !== undefined) return decode(x.output);
 return x;
}
const frontier = decode(await tools.contract_read_evidence({op:"frontier"}));
if (!frontier.entries?.some(x => x.step === "build")) throw new Error("missing prior build counterexample");
const handle = frontier.entries.find(x => x.step === "build").evidence;
let offset = 0, evidence = "";
for (let i = 0; i < 100; i++) {
 const page = decode(await tools.contract_read_evidence({op:"read", handle, offset}));
 evidence += page.text;
 if (page.eof) break;
 if (!(page.next_offset > offset)) throw new Error("recall made no progress");
 offset = page.next_offset;
}
const record = JSON.parse(evidence);
if (!record.checks.some(x => x.receipt.step === "build" && x.receipt.outcome === "fail")) throw new Error("wrong evidence");
if (record.checks.some(x => x.receipt.step.startsWith("sealed:"))) throw new Error("sealed disclosure");
text({publicEvidenceRecall:true, handle, originalSubject:record.subject_hash});
"""
            if partial_checks:
                successor_recall=successor_recall.replace('"build"','"public:D1"')

            def dialog_case(id, args):
                return dict(id=id,family="answer",args=args,stdin="\x00probe input",
                    env=[dict(name="PC_PROBE_STATE",value="kept")],
                    files=[dict(path="probe-input.txt",text="probe fixture",repeat=1)],
                    terminal=dict(rows=31,cols=97,input="",dialogue=[
                        dict(expect="CAP?",send="supported\n"),dict(expect="PIXELS?",send="800x240\n")]))

            class Provider(http.server.BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def log_message(self, *args):
                    pass

                def do_GET(self):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

                def do_POST(self):
                    try:
                        if (
                            self.headers.get("Authorization")
                            != "Bearer LOCAL_FIXTURE_ONLY"
                        ):
                            raise AssertionError("unexpected credential")
                        length = int(self.headers["Content-Length"])
                        if not 0 < length <= 2 << 20:
                            raise AssertionError("request bound")
                        body = json.loads(self.rfile.read(length))
                        requests.append(body)
                        if len(requests) > 32:
                            raise AssertionError("fixture request budget")
                        schema = (
                            body.get("text", {}).get("format", {}).get("schema", {})
                        )
                        props = schema.get("properties", {})
                        role = (
                            "draft"
                            if "differential_cases" in props
                            else "review"
                            if "coverage" in props
                            else "probe"
                            if "coverage_plan" in props
                            else "explore"
                            if "cases" in props
                            else "executor"
                        )
                        if role == "executor" and "pro_contract_successor" in "\n".join(
                            text_values(body.get("input", []))
                        ):
                            role = "successor"
                        counts[role] = counts.get(role, 0) + 1
                        worker_keys.setdefault(role, set()).add(body.get("prompt_cache_key"))
                        if role == "draft":
                            message = dict(
                                decision="contract",
                                reason="",
                                requirements=[
                                    dict(
                                        id="R1",
                                        text="answer.txt contains ready",
                                        source_id="request:0",
                                        inferred=False,
                                    )
                                ],
                                out_of_scope=[],
                                process_constraints=[],
                                differential_cases=[],
                                candidate_tests=False,
                            )
                            if repair_review:
                                message["requirements"].append(dict(id="R2", text="Check the numerical attachment" if partial_review else "Preserve an unrequested extra artifact", source_id="request:0", inferred=True))
                            if partial_checks:
                                message["differential_cases"]=[dialog_case("D1",["ready"]),dialog_case("D2",["block"])]
                        elif role in ("explore", "probe"):
                            packet_parts = {}
                            for text in text_values(body.get("input", [])):
                                if "<external_pro_contract_packet_" in text and "tokens truncated" in text:
                                    raise AssertionError("worker packet was truncated by the transport")
                                for match in re.finditer(
                                    r"<external_pro_contract_packet_(\d+)>(.*?)</external_pro_contract_packet_\1>",
                                    text,
                                    re.DOTALL,
                                ):
                                    packet_parts[int(match.group(1))] = match.group(2)
                            packet_text = "".join(packet_parts[key] for key in sorted(packet_parts))
                            if not 95_000 <= len(packet_text.encode()) <= 96_000:
                                raise AssertionError("large probe fixture must reach the transport intact within its budget")
                            if role == "probe":
                                invocations = [json.loads(value) for value in re.findall(r"Invocation JSON[^\n]*\n(\{[^\n]*\})\n\[stdout\]", packet_text)]
                                observed = next((value for value in invocations if value.get("id") == "c0"), None)
                                if not observed or observed.get("env", {}).get("PC_PROBE_STATE") != "kept" or observed.get("stdin") != "\x00probe input" or observed.get("terminal", {}).get("cols") != 97 or observed.get("files", [{}])[0].get("text") != "probe fixture":
                                    raise AssertionError("reference input state did not reach the fresh suite-writing worker")
                                if dialogue_probe and observed.get("terminal",{}).get("dialogue",[])!=dialog_case("x",[])["terminal"]["dialogue"]:
                                    raise AssertionError("terminal dialogue lost in observation handoff")
                            count = 4
                            if role == "explore":
                                count = 125 if len(worker_keys[role]) == 1 else 1
                            message = dict(
                                cases=[
                                    dict(id=f"c{i}", family="answer", args=["ready"])
                                    for i in range(count)
                                ]
                            )
                            if role == "explore":
                                for case in message["cases"]:
                                    case.update(stdin="\x00probe input",env=[dict(name="PC_PROBE_STATE",value="kept")],
                                                files=[dict(path="probe-input.txt",text="probe fixture",repeat=1)],
                                                terminal=dict(rows=31,cols=97,input="q"))
                            if role == "probe":
                                message["coverage_plan"] = [
                                    dict(family="answer", surface="stdout", description="ready")
                                ]
                            if dialogue_probe:
                                message["cases"]=[dialog_case(case["id"],case["args"]) for case in message["cases"]]
                        elif role == "review" and counts[role] % 2 == 1:
                            if computation:
                                # A mutable workspace change must not change inspected bytes.
                                (workspace/"numbers.npz").write_bytes(b"changed after candidate capture")
                            items = [custom_call(body, review_code, "review-evidence")]
                            message = None
                        elif role == "review":
                            candidates = [
                                match.group(1)
                                for value in text_values(body)
                                if (
                                    match := re.search(
                                        r'"fixtureCitation"\s*:\s*"(e[0-9]+)"', value
                                    )
                                )
                            ]
                            if not candidates:
                                raise AssertionError(
                                    "review evidence did not return a handle"
                                )
                            flattened = "\n".join(text_values(body))
                            if "ready" not in flattened or "Refused:" not in flattened:
                                raise AssertionError("missing artifact or refusal")
                            message = dict(
                                verdict="support",
                                coverage=[
                                    dict(requirement_id="R1", evidence=candidates[-1])
                                ],
                                findings=[],
                                terms_gap=[],
                                missing="",
                                residual="",
                            )
                            if scoped_review:
                                message["terms_gap"] = [dict(element="extra artifact", reason="not requested", affected_requirements=["R2"])]
                                if counts[role] == 2:
                                    message.update(verdict="defeat", coverage=[], findings=[dict(requirement_id="R1",location="answer.txt",counterexample="contains first failed instead of ready")],residual="invent an unrequested extra artifact")
                                else:
                                    message["coverage"].append(dict(requirement_id="R2",evidence=candidates[-1]))
                            if partial_review:
                                message.update(verdict="partial",gaps=[dict(requirement_id="R2",reason="numeric format is not yet assessable")])
                                if counts[role]==2:
                                    message.update(coverage=[],findings=[dict(requirement_id="R1",location="answer.txt",counterexample="contains first failed instead of ready")])
                        elif counts[role] == 1 or (repair_review and role == "executor" and counts[role] == 3):
                            answer = (
                                "first failed"
                                if (succession or repair_review) and role == "executor" and counts[role] == 1
                                else "ready"
                            )
                            items = [
                                custom_call(
                                    body,
                                    (successor_recall if role == "successor" else "")
                                    + "const r = await tools.exec_command({cmd:"
                                    + json.dumps(f"printf '{answer}\\n' > answer.txt")
                                    + ",yield_time_ms:1000,max_output_tokens:1000});text(r);",
                                    "write-answer",
                                )
                            ]
                            message = None
                        else:
                            message = "Fixture completed."
                        if message is not None:
                            items = [
                                dict(
                                    type="message",
                                    id=f"message-{len(requests)}",
                                    role="assistant",
                                    content=[
                                        dict(
                                            type="output_text",
                                            text=json.dumps(message)
                                            if isinstance(message, dict)
                                            else message,
                                        )
                                    ],
                                )
                            ]
                        response_id = f"local-{len(requests)}"
                        events = [
                            dict(type="response.created", response=dict(id=response_id))
                        ]
                        events += [
                            dict(type="response.output_item.done", item=item)
                            for item in items
                        ]
                        events += [
                            dict(
                                type="response.completed",
                                response=dict(
                                    id=response_id,
                                    usage=dict(
                                        input_tokens=10,
                                        output_tokens=10,
                                        total_tokens=20,
                                    ),
                                ),
                            )
                        ]
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        for event in events:
                            self.wfile.write(
                                f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
                            )
                        self.wfile.flush()
                    except Exception as error:
                        errors.append(str(error))
                        self.send_error(500, "fixture failure")

            provider = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            provider.daemon_threads = True
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            (source / "config.toml").write_text(
                procodex.toml(
                    dict(
                        model_provider="fixture",
                        model_providers=dict(
                            fixture=dict(
                                name="Local fixture",
                                base_url=f"http://127.0.0.1:{provider.server_port}/v1",
                                env_key="PROCODEX_FIXTURE_KEY",
                                wire_api="responses",
                                supports_websockets=False,
                                request_max_retries=0,
                                stream_max_retries=0,
                            )
                        ),
                    )
                )
            )
            home, native_config = procodex.configure(
                package,
                workspace,
                root / "state",
                source,
                image,
                None if repair_review else 'python3 -c \'from pathlib import Path; assert Path("answer.txt").read_text().strip() == "ready"\'',
                isolation="container-only",
                successor_sessions=2 if succession else 0,
                task_seconds=3600,
            )
            if probe_fixture:
                settings_path = home / "pro_contract/settings.json"
                settings = json.loads(settings_path.read_text())
                settings["evaluation"]["reference_command"] = "/bin/echo"
                settings["evaluation"]["check"]["candidate_command"] = "/bin/echo"
                settings["evidence"] = dict(
                    min_sealed_qualified=4,
                    min_success_permille=500,
                    sealed_threshold_permille=750,
                )
                settings_path.write_text(json.dumps(settings))
            if computation or dialogue_probe:
                settings_path=home/"pro_contract/settings.json"
                settings=json.loads(settings_path.read_text())
                if computation:settings["review_execution"]=dict(max_calls=2,timeout_secs=10,max_output_bytes=8192)
                if dialogue_probe:
                    settings["evaluation"]["reference_command"]="/pc-base/reference.py"
                    settings["evaluation"]["check"]["candidate_command"]="./candidate.py"
                if partial_checks:
                    settings["evaluation"]["check"]["build_command"]="chmod +x ./candidate.py"
                    settings["evaluation"]["check"]["timeout_secs"]=4
                settings_path.write_text(json.dumps(settings))
            env = {
                **os.environ,
                "CODEX_HOME": str(home),
                "PROCODEX_FIXTURE_KEY": "LOCAL_FIXTURE_ONLY",
            }
            for key in (
                "OPENAI_API_KEY",
                "OPENAI_API_KEY_FILE",
                "CODEX_ROLLOUT_TRACE_ROOT",
            ):
                env.pop(key, None)
            server = AppServer(
                [
                    str(package / "bin/codex"),
                    "--enable",
                    "pro_contract",
                    "--disable",
                    "hooks",
                    "app-server",
                ],
                env,
                root / "rpc.jsonl",
                root / "stderr.log",
                cwd=workspace,
            )

            def handle(value):
                if "id" in value and "method" in value:
                    server.refuse(value)

            status = None
            try:
                server.request(
                    "initialize",
                    dict(
                        clientInfo=dict(name="procodex-fixture", version="1"),
                        capabilities=dict(experimentalApi=True),
                    ),
                    handle,
                )
                server.notify("initialized")
                thread = server.request(
                    "thread/start",
                    dict(
                        model=getattr(self, "model", "gpt-5.6-luna"),
                        cwd="/workspace",
                        sandbox=native_config["sandbox_mode"],
                        approvalPolicy="never",
                    ),
                    handle,
                )["thread"]["id"]
                server.request(
                    "turn/start",
                    dict(
                        threadId=thread,
                        input=[
                            dict(
                                type="text",
                                text=task_text,
                                text_elements=[],
                            )
                        ],
                    ),
                    handle,
                )
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    try:
                        handle(server.messages.get(timeout=0.1))
                    except queue.Empty:
                        pass
                    database = home / "pro_contract/ledger_1.sqlite"
                    if database.exists():
                        with contextlib.closing(
                            sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                        ) as connection:
                            row = connection.execute(
                                "SELECT json FROM records WHERE kind='status' AND key=?",
                                (thread,),
                            ).fetchone()
                        if row:
                            status = json.loads(row[0])
                            if status.get("resting"):
                                break
                self.assertEqual(errors, [])
                self.assertEqual((workspace / "answer.txt").read_text(), "ready\n")
                self.assertIsNotNone(status)
                self.assertEqual(status["phase"], "not_verified" if repair_review or partial_checks else "supported", status)
                if not partial_checks:self.assertGreaterEqual(counts.get("review", 0), 2)
                if repair_review:
                    self.assertEqual(status["class"], "reviewer_unable" if partial_review else "terms_gap")
                    self.assertEqual(counts.get("review"), 4)
                    self.assertEqual(status["repairs_used"], 1)
                    with contextlib.closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as connection:
                        commands=[json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events WHERE contract_id=? ORDER BY seq",(thread+".1",))]
                    self.assertEqual(commands,["issue","propose","defeat","propose"])
                if probe_fixture:
                    self.assertEqual(len(worker_keys.get("explore", set())), 2)
                    self.assertEqual(len(worker_keys.get("probe", set())), 1)
                if succession:
                    self.assertTrue(any("publicEvidenceRecall" in text and "true" in text
                        for request in requests for item in request.get("input", [])
                        if item.get("type") in ("custom_tool_call_output", "function_call_output")
                        for text in text_values(item)),
                        "the real successor must consume retained public evidence before repairing")
                    self.assertEqual(len(worker_keys.get("draft", set())), 1)
                    self.assertEqual(counts.get("successor"), 2)
                    successor_requests = [
                        body
                        for body in requests
                        if "pro_contract_successor"
                        in "\n".join(text_values(body.get("input", [])))
                    ]
                    first = successor_requests[0]
                    original = next(
                        body
                        for body in requests
                        if body.get("prompt_cache_key") == thread
                    )
                    self.assertNotEqual(
                        first.get("prompt_cache_key"), original.get("prompt_cache_key")
                    )
                    self.assertFalse(
                        any(
                            item.get("type")
                            in ("function_call_output", "custom_tool_call_output")
                            for item in first["input"]
                        )
                    )
                    self.assertIn(
                        "original_task", "\n".join(text_values(first["input"]))
                    )
                    # Field names can straddle the 768-byte context parts. Check
                    # the reconstructed packet, not a substring of its wrappers.
                    parts = {}
                    for text in text_values(first["input"]):
                        for match in re.finditer(
                            r"<external_pro_contract_successor_(\d+)>(.*?)</external_pro_contract_successor_\1>",
                            text,
                            re.DOTALL,
                        ):
                            parts[int(match.group(1))] = match.group(2)
                    self.assertEqual(sorted(parts), list(range(len(parts))))
                    packet = json.loads("".join(parts[index] for index in sorted(parts)))
                    self.assertGreater(packet["owner_authorization_revision"], 0)
                    self.assertEqual(packet["original_task"], task_text)
                    self.assertIn(task_text, [
                        entry["text"] for entry in packet["current_owner_instructions"]
                        if entry["role"] == "user"
                    ])
                    with contextlib.closing(
                        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                    ) as connection:
                        commands = [
                            json.loads(row[0])["command"]["type"]
                            for row in connection.execute(
                                "SELECT command_json FROM events ORDER BY seq"
                            )
                        ]
                        budget = json.loads(
                            connection.execute(
                                "SELECT json FROM records WHERE kind='succession' AND key=?",
                                (thread,),
                            ).fetchone()[0]
                        )
                    self.assertEqual(commands, ["issue", "propose", "defeat", "propose"] + ([] if partial_checks else ["support"]))
                    self.assertEqual((budget["launches"], budget["pending"]), (1, None))
                    self.assertNotEqual(budget["executors"], [thread])
                    if partial_checks:
                        self.assertEqual(status["class"],"infrastructure")
                        self.assertEqual(counts.get("review",0),0)
                        with contextlib.closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as connection:
                            verifications=[json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events WHERE kind='verification' ORDER BY seq")]
                        self.assertEqual([r["verdict"] for r in verifications],["defeat","not_verified"])
                        self.assertTrue(all(not r["receipts"]["complete"] for r in verifications))
                        self.assertTrue(all(r["receipts"]["execution"]["shutdown_confirmed"] for r in verifications))
                        self.assertEqual([next(s["outcome"] for s in r["receipts"]["steps"] if s["step"]=="public:D1") for r in verifications],["fail","pass"])
                if computation:
                    self.assertTrue(any("frozenComputation" in text and "true" in text
                        for request in requests for item in request.get("input",[])
                        if item.get("type") in ("custom_tool_call_output","function_call_output") for text in text_values(item)))
                    with contextlib.closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as connection:
                        verified=json.loads(connection.execute("SELECT event_json FROM experiment_events WHERE kind='verification' ORDER BY seq DESC LIMIT 1").fetchone()[0])["body"]
                    def blob(handle):
                        return json.loads((home/"pro_contract/blobs"/handle[:2]/handle).read_text())
                    public=blob(verified["public_evidence"])
                    self.assertEqual(len(public["inspections"]),1)
                    retained=blob(public["inspections"][0])
                    self.assertEqual(retained["subject_hash"],public["subject_hash"])
                    self.assertEqual(retained["execution"]["state"],"completed")
                    self.assertEqual(len(retained["inputs"]),2)
                if succession and getattr(self, "benchmark_binding_fixture", False):
                    import procontract_benchmark_runner as runner
                    import procontract_succession_binding as binding

                    audit = binding.snapshot(
                        home, thread, {"max_sessions": 2, "total_secs": 3600}
                    )
                    cost = runner.rollout_costs(
                        home, successor_ids=audit["executors"]
                    )
                    self.assertEqual(
                        (audit["issue_count"], audit["launches"], audit["pending"]),
                        (1, 1, None),
                    )
                    self.assertEqual(
                        cost["successors_included_in_workers"]["rollouts"], 1
                    )
                    self.assertEqual(
                        cost["successors_included_in_workers"]["usage"][
                            "total_tokens"
                        ],
                        counts["successor"] * 20,
                    )
                    self.assertEqual(
                        cost["executor"]["total_tokens"]
                        + cost["workers"]["total_tokens"],
                        len(requests) * 20,
                    )
            finally:
                server.close()
                server.process.stdout.close()
                server._log.close()
                provider.shutdown()
                provider.server_close()
                output = os.environ.get("PROCODEX_TEST_REPORT")
                if output:
                    import shutil

                    destination = Path(output)
                    destination.mkdir(parents=True, exist_ok=True)
                    for name in ("rpc.jsonl", "stderr.log"):
                        shutil.copy2(root / name, destination / name)
                    (destination / "result.json").write_text(
                        json.dumps(
                            dict(
                                status=status,
                                counts=counts,
                                worker_keys={key: sorted(value) for key, value in worker_keys.items()},
                                errors=errors,
                                task_bytes=len(task_text.encode()),
                                probe_fixture=probe_fixture,
                                computation_fixture=computation,partial_review_fixture=partial_review,
                                dialogue_probe_fixture=dialogue_probe,partial_checks_fixture=partial_checks,
                                real_provider_calls=0,
                            ),
                            indent=2,
                        )
                    )
                    (destination / "requests.json").write_text(
                        json.dumps(requests, indent=2)
                    )
                    if computation or partial_checks or dialogue_probe:
                        shutil.copytree(home/"pro_contract/work",destination/"work",dirs_exist_ok=True,symlinks=True)
                    database = home / "pro_contract/ledger_1.sqlite"
                    if database.exists():
                        with contextlib.closing(sqlite3.connect(database)) as source_db:
                            with contextlib.closing(
                                sqlite3.connect(destination / "ledger.sqlite")
                            ) as target_db:
                                source_db.backup(target_db)
                            public = destination / "public-evidence"
                            for (raw,) in source_db.execute("SELECT event_json FROM experiment_events"):
                                event = json.loads(raw)
                                handle = event.get("body", {}).get("public_evidence")
                                if event.get("kind") != "verification" or not isinstance(handle, str):
                                    continue
                                blob = home / "pro_contract/blobs" / handle[:2] / handle
                                if blob.is_file():
                                    public.mkdir(exist_ok=True)
                                    shutil.copy2(blob, public / handle)


if __name__ == "__main__":
    unittest.main()
