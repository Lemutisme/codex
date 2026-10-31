"""Opt-in native/controller/evidence integration with a scripted local provider.

Set PROCODEX_NATIVE_PACKAGE and PROCODEX_TEST_IMAGE. The default fixture uses no
real model. An optional continuation callback is audited by its caller; synthetic
fixture usage does not measure that backend's requests or tokens.
"""

import http.server
import contextlib
import json
import os
from pathlib import Path
import queue
import re
import shlex
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


def continuation_facts(body):
    texts=list(text_values(body.get("input", [])));parts={}
    for text in texts:
        for match in re.finditer(r"<external_pro_contract_packet_(\d+)>(.*?)</external_pro_contract_packet_\1>",text,re.S):
            parts[int(match.group(1))]=match.group(2)
    if parts:texts.append("".join(parts[k] for k in sorted(parts)))
    for text in texts:
        for match in re.finditer(r'\{',text):
            try:value,_=json.JSONDecoder().raw_decode(text[match.start():])
            except ValueError:continue
            if "available_actions" in value and "assessment" in value:return value
    raise AssertionError("continuation capability packet missing")


def named_call(body, tool_name, payload, call_id):
    roots = list(body.get("tools", []))
    for value in body.get("input", []):
        if value.get("type") == "additional_tools":
            roots.extend(value.get("tools", []))

    def walk(items, namespace=None):
        for item in items:
            if item.get("type") == "namespace":
                yield from walk(item.get("tools", []), item["name"])
            elif item.get("name") == tool_name:
                yield item, namespace

    found = list(walk(roots))
    if len(found) != 1:
        raise AssertionError(f"one code-mode {tool_name} expected")
    tool, namespace = found[0]
    return dict(
        type="custom_tool_call" if tool["type"] == "custom" else "function_call",
        call_id=call_id,
        name=tool_name,
        **({"input":payload} if tool["type"] == "custom" else {"arguments":json.dumps(payload)}),
        **({"namespace": namespace} if namespace else {}),
    )


def custom_call(body, code, name):
    return named_call(body, "exec", code, name)


def pending_cell_wait(body, call_id):
    """Scripted execution must await yielded cells just as an actual agent does."""
    for item in reversed(body.get("input", [])):
        if item.get("type") in ("custom_tool_call_output", "function_call_output"):
            for text in text_values(item.get("output")):
                match = re.search(r"^Script running with cell ID (\S+)", text)
                if match:
                    return named_call(body,"wait",dict(cell_id=match.group(1),yield_time_ms=1000,max_tokens=4000),call_id)
            return None
    return None


@unittest.skipUnless(
    os.environ.get("PROCODEX_NATIVE_PACKAGE"),
    "set native package for the isolated no-model integration",
)
class NativeEvidenceTest(unittest.TestCase):
    def test_real_executor_and_reviewer_use_frozen_handles(self):
        deadline_fixture = getattr(self, "deadline_fixture", False)
        owner_cancel = getattr(self, "owner_cancel_fixture", False)
        transport_failure = getattr(self, "transport_failure_fixture", None)
        autonomous = getattr(self, "autonomous_fixture", False)
        failure_after_write = getattr(self, "failure_after_write_fixture", False)
        output_truncation = getattr(self, "output_truncation_fixture", False)
        stream_disconnect = getattr(self, "stream_disconnect_fixture", False)
        failure_before_issue = getattr(self, "failure_before_issue_fixture", False)
        failure_observed = threading.Event()
        observation_fixture = getattr(self, "observation_fixture", False)
        text_route = getattr(self, "text_route_fixture", False)
        missing_access = getattr(self, "missing_access_fixture", False)
        correction_exhausted = getattr(self, "correction_exhausted_fixture", False)
        protocol_correction = getattr(self, "protocol_correction_fixture", False) or correction_exhausted
        delivery_evidence = getattr(self, "delivery_evidence_fixture", False)
        check_execution = getattr(self, "check_execution_fixture", False)
        delivery_action = getattr(self, "delivery_action_fixture", False)
        final_response = "BEGIN-NATIVE-RESPONSE\n" + "原始交付内容\n" * 200 + "END-NATIVE-RESPONSE" if delivery_evidence else "Fixture completed."
        progression = getattr(self, "progress_fixture", False)
        publication_caller_loss = getattr(self, "publication_caller_loss_fixture", False)
        caller_loss_observed = []
        diagnostic_review = getattr(self, "diagnostic_review_fixture", False)
        initial_review_defeat = getattr(self, "initial_review_defeat_fixture", False)
        input_strategy = getattr(self, "input_strategy_fixture", False)
        resource_limit = getattr(self, "resource_limit_fixture", False)
        successor_progress = getattr(self, "successor_progress_fixture", False)
        late_successor = getattr(self, "late_successor_fixture", False)
        succession = getattr(self, "succession_fixture", False) or late_successor
        probe_fixture = getattr(self, "probe_fixture", False)
        scoped_review = getattr(self, "scoped_review_fixture", False)
        partial_review = getattr(self, "partial_review_fixture", False)
        local_binding_fault = getattr(self, "local_binding_fault_fixture", False)
        continuation_model = getattr(self, "continuation_model", None)
        selection_model = getattr(self, "selection_model", None)
        expected_phase = getattr(self, "expected_phase", None)
        continuation_unknown = getattr(self, "continuation_unknown_fixture", False)
        continuation_rest = getattr(self, "continuation_rest_fixture", False)
        continuation_history = getattr(self, "continuation_history_fixture", False)
        shared_citations = getattr(self, "shared_citations_fixture", False)
        structured_pages = getattr(self, "structured_pages_fixture", False)
        scoped_judgment = getattr(self, "scoped_judgment_fixture", False)
        cross_requirement_computation = getattr(self, "cross_requirement_computation_fixture", False)
        computation = getattr(self, "computation_fixture", False) or cross_requirement_computation
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
            if shared_citations:
                (workspace / "citation.txt").write_text("ready " + "x" * 4090)
            if input_strategy:
                (root/'source-input.txt').write_text('immutable source\n')
                (root/'strategy').mkdir()
                (root/'strategy/work_method.md').write_text('STRATEGY-NATIVE-MARKER: Preserve the supplied input and the runnable check across handoffs.')
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
            injected_failures = []
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
            if shared_citations:
                review_code = review_code.replace('value.entry.path === "answer.txt"', 'value.entry.path === "citation.txt"')
            if delivery_evidence:
                review_code += r'''
async function fullDocument(source) {
 let text="";
 for(let offset=0,i=0;i<100;i++) {
  const page=decode(await tools.read_evidence({op:"read",source_id:source,offset}));
  text+=page.text;if(page.eof)return text;offset=page.next_offset;
 }
 throw new Error("incomplete delivery evidence");
}
const response=JSON.parse(await fullDocument("delivery_message"));
const checks=await fullDocument("check_receipts");
if(response.kind!=="native_final_response" || !response.complete || !response.text.endsWith("END-NATIVE-RESPONSE") || response.original_bytes<=1200) throw new Error("actual response was truncated or mislabeled");
if(!checks.includes("host-configured command:") || !checks.includes("NATIVE-CHECK-PASSED")) throw new Error("command or successful check output missing");
text({deliveryEvidenceSeen:true,complete:response.complete});
'''
            if check_execution:
                review_code += r'''
const check=decode(await tools.read_evidence({op:"read",source_id:"check_receipts",offset:0}));
if(!check.eof || !check.text.includes("Host checker actions") || !check.text.includes("NATIVE-CHECK-PASSED")) throw new Error("scoped host check result missing");
text({checkCitation:check.citation_id});
'''
            if delivery_action:
                review_code += r'''
let receiptText="", receiptCitation;
for(let offset=0,i=0;i<100;i++) {
 const page=decode(await tools.read_evidence({op:"read",source_id:"host_observations",offset}));
 receiptText+=page.text;
 if(page.text.includes('"delivery"'))receiptCitation=page.citation_id;
 if(page.eof)break;offset=page.next_offset;
}
const observedDelivery=JSON.parse(receiptText);
if(!observedDelivery.delivery || observedDelivery.delivery.response_capture.state!=="available" || observedDelivery.delivery.subject_hash!==observedDelivery.subject_hash || !receiptCitation) throw new Error("native delivery action receipt missing");
text({deliveryActionCitation:receiptCitation});
'''
            if observation_fixture:
                review_code += r'''
async function observationDocument(source) {
 let text="", citation;
 for(let offset=0,i=0;i<100;i++) {
  const page=decode(await tools.read_evidence({op:"read",source_id:source,offset}));
  text+=page.text;if(!citation)citation=page.citation_id;
  if(page.eof)return {document:JSON.parse(text),citation};offset=page.next_offset;
 }
 throw new Error("incomplete host observations");
}
const catalog=(await observationDocument("contract_terms")).document;
const obligation=catalog.obligations.find(x=>x.scope==="execution");
if(!obligation)throw new Error("process obligation is not in the catalog");
const observed=await observationDocument("host_observations");
const h=observed.document;
const completed=h.feedback_access.filter(x=>x.outcome==="completed");
if(completed.some(x=>x.completion_sequence>h.journal_through_sequence))throw new Error("future access entered frozen context");
text({processObligation:obligation.id,hostCitation:observed.citation,completedAccesses:completed.length});
'''
            if computation:
                review_code = review_code.replace('text({fixtureCitation:artifact.citation_id, artifact:artifact.text, denied});',r'''
let binary;
for (let offset=0; offset<50;) {
 const page=decode(await tools.read_evidence({op:"index",source_id:"",offset}));
 if (page.entry?.path==="numbers.npz") {binary=page.entry.source_id;break;}
 if(page.eof)break;offset=page.next_offset;
}
if(!binary)throw new Error("binary source missing");
for(let i=0;i<3;i++) {
 let invalid;
 try { invalid=decode(await tools.inspect_evidence({source_ids:[id],requirements:[],python:"print('not admitted " + i + "')"})); }
 catch(error) { invalid=String(error); }
 if(invalid?.source_id)throw new Error("invalid computation was dispatched");
}
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
                            "continuation"
                            if "choice" in props
                            else "draft"
                            if "differential_cases" in props
                            else "review"
                            if "coverage" in props or "assessments" in props
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
                        if role == "continuation" and continuation_facts(body)["assessment"].get("stage") == "handoff":
                            role = "planning"
                        if failure_before_issue and role == "draft":
                            if not failure_observed.wait(10):
                                raise AssertionError("root did not reach the injected failure before Issue")
                        if role == transport_failure and not injected_failures and (not failure_after_write or counts.get(role,0) >= 1):
                            issued_at_failure = None
                            database = home / "pro_contract/ledger_1.sqlite"
                            if database.exists():
                                with sqlite3.connect(database) as connection:
                                    issued_at_failure = connection.execute("SELECT count(*) FROM contracts").fetchone()[0]
                            injected_failures.append(dict(role=role, request=len(requests), issued_contracts=issued_at_failure))
                            failure_observed.set()
                            if output_truncation or stream_disconnect:
                                self.send_response(200)
                                self.send_header("Content-Type", "text/event-stream")
                                self.send_header("Connection", "close")
                                self.end_headers()
                                self.close_connection = True
                                event=dict(type="response.incomplete",response=dict(id="injected-incomplete",incomplete_details=dict(reason="max_output_tokens")))
                                if stream_disconnect:
                                    event=dict(type="response.created",response=dict(id="injected-disconnect"))
                                self.wfile.write(("event: "+event["type"]+"\ndata: "+json.dumps(event)+"\n\n").encode())
                                self.wfile.flush()
                            else:
                                self.send_error(503, "injected provider interruption")
                            return
                        waiting = pending_cell_wait(body,f"wait-{len(requests)}") if role in ("executor","successor","planning","continuation") else None
                        if waiting is None:
                            counts[role] = counts.get(role, 0) + 1
                        if text_route and role == "executor" and counts[role] == 2:
                            observations = "\n".join(text_values([v.get("output") for v in body.get("input", []) if v.get("type", "").endswith("_call_output")]))
                            if "Tool observation incomplete" not in observations or "native-image-tool-disabled" not in observations:
                                raise AssertionError("text route must expose the unsupported observation and keep executing")
                            if "image_url" in json.dumps([v.get("output") for v in body.get("input", []) if v.get("type", "").endswith("_call_output")]):
                                raise AssertionError("image crossed the text gateway")
                        if late_successor and role == "successor" and counts[role] == 2:
                            # Real native clock/HTTP wait: this handoff fits the original
                            # grant but exceeds the former guessed verification reserve.
                            time.sleep(45)
                        worker_keys.setdefault(role, set()).add(body.get("prompt_cache_key"))
                        if input_strategy and role in ('executor','successor') and 'STRATEGY-NATIVE-MARKER' not in '\n'.join(text_values(body)):
                            raise AssertionError('selected strategy did not reach this executor context')
                        if input_strategy and role in ('executor','successor') and '/inputs/source.txt' not in '\n'.join(text_values(body)):
                            raise AssertionError('declared input capability did not reach this executor context')
                        if waiting is not None:
                            items = [waiting]
                            message = None
                        elif role == "draft":
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
                                context=[],
                                differential_cases=[],
                                candidate_tests=False,
                            )
                            if shared_citations:
                                message["requirements"] = [dict(id=f"R{i}", text=f"Retain citation.txt property {i}.", source_id="request:0", inferred=False) for i in range(19)]
                            if repair_review:
                                message["requirements"].append(dict(id="R2", text="Check the numerical attachment" if partial_review else "Preserve an unrequested extra artifact", source_id="request:0", inferred=True))
                            if cross_requirement_computation:
                                message["requirements"].append(dict(id="R2", text="The supplied numerical attachment sums to 6.", source_id="request:0", inferred=False))
                            if observation_fixture:
                                message["process_constraints"]=[dict(text="Obtain the retained feedback bytes before repairing the artifact.",source_id="request:0")]
                            if check_execution:
                                message["process_constraints"]=[dict(text="Run the configured check.",source_id="request:0")]
                            if delivery_action:
                                message["process_constraints"]=[dict(text="Submit with your final assistant response.",source_id="request:0")]
                            if partial_checks:
                                message["differential_cases"]=[dialog_case("D1",["ready"]),dialog_case("D2",["block"])]
                        elif role == "planning":
                            message=dict(choice=dict(action="verify",reason="The fixture strategy requests acceptance."))
                            if selection_model is not None:
                                selected=selection_model(body)
                                if isinstance(selected,list):items=selected;message=None
                                else:message=selected
                        elif role == "continuation":
                            facts=continuation_facts(body)
                            keep_working=(facts["assessment"]["decision"]=="defeat" or continuation_unknown or continuation_history or (autonomous and facts["assessment"]["stage"]=="interruption")) and not continuation_rest
                            if continuation_history and counts[role] == 2:
                                previous=facts['previous_choice']
                                returned=[r['event'] for r in previous['execution_records'] if r['event']['phase']=='successor_returned']
                                if len(returned)!=1 or returned[0]['exit']!='handoff' or previous['delivery']['event']['subject_hash']!=facts['subject_hash']:
                                    raise AssertionError('actual prior successor result missing from continuation context')
                            choice=(dict(action=facts["available_actions"][0], requirements=facts["allowed_requirements"],
                                next_step="Read the retained evidence, inspect answer.txt and replay its check.") if keep_working else
                                dict(action="rest",reason="No further useful work selected by this fixture strategy."))
                            if autonomous and failure_after_write and facts["assessment"]["stage"] == "interruption":
                                choice=dict(action="check",reason="Observe the retained interrupted work before choosing more execution.")
                            elif autonomous and failure_after_write and facts["assessment"]["stage"] == "checks":
                                choice=dict(action="verify",reason="The retained work passes its check; assess it without replaying the write.")
                            message=dict(choice=choice)
                            if continuation_model is not None:message=continuation_model(body)
                            if selection_model is not None:
                                selected=selection_model(body)
                                if isinstance(selected,list):items=selected;message=None
                                else:message=selected
                            if autonomous and facts["assessment"]["stage"] == "interruption" and "interrupted-archive-read" not in "\n".join(text_values(body.get("input",[]))):
                                code = 'const page=await tools.contract_read_evidence({op:"read",handle:'+json.dumps(facts['public_evidence'])+',offset:0});text(page);text("interrupted-archive-read");'
                                items=[custom_call(body,code,"read-interrupted-work")]
                                message=None
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
                        elif role == "review" and (
                            counts[role] in (1, 4) if local_binding_fault else
                            counts[role] % 2 == 1 and not (protocol_correction and counts[role]==3)
                        ):
                            if computation:
                                # A mutable workspace change must not change inspected bytes.
                                (workspace/"numbers.npz").write_bytes(b"changed after candidate capture")
                            prefix = r'''
const catalog = await tools.read_evidence({op:"list",source_id:"",offset:0});
if(typeof catalog!=="object" || !Array.isArray(catalog.entries))throw new Error("catalog must be structured");
const rejected = await tools.read_evidence({op:"read",source_id:"human_request"});
if(typeof rejected!=="string" || !rejected.startsWith("Refused:"))throw new Error("invalid query must stay rejected");
let documentText="", offset=0;
for (;;) {
 const page = await tools.read_evidence({op:"read",source_id:"contract_terms",offset});
 if(typeof page!=="object" || typeof page.text!=="string")throw new Error("page must be structured");
 documentText+=page.text;
 if(page.eof)break;
 if(!Number.isInteger(page.next_offset) || page.next_offset<=offset)throw new Error("cursor did not advance");
 offset=page.next_offset;
}
if(!JSON.parse(documentText).obligations.length)throw new Error("catalog missing obligations");
text({structuredEvidencePages:true});
''' if structured_pages else ""
                            items = [custom_call(body, prefix + review_code, "review-evidence")]
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
                            if delivery_evidence and '"deliveryEvidenceSeen":true' not in flattened.replace(" ", ""):
                                raise AssertionError("reviewer did not receive actual delivery and check evidence")
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
                            if (continuation_unknown or continuation_history) and counts[role]==2:
                                message.update(verdict="cannot_judge",coverage=[],missing="Need a further artifact observation; no defect or scope discrepancy established.")
                            if shared_citations:
                                message["coverage"] = [dict(requirement_id=f"R{i}", evidence=candidates[-1]) for i in range(19)]
                            if (diagnostic_review or initial_review_defeat) and counts[role] == 2:
                                message.update(verdict="defeat",coverage=[],
                                    findings=[dict(requirement_id="R1",location="answer.txt",counterexample="The frozen answer is not ready.")],
                                    residual="Write the required ready value and replay the check.")
                            if check_execution:
                                citation=re.search(r'"checkCitation"\s*:\s*"(e[0-9]+)"',flattened).group(1)
                                message["coverage"].append(dict(requirement_id="process:0",evidence=citation))
                            if cross_requirement_computation:
                                message["coverage"].append(dict(requirement_id="R2", evidence=candidates[-1]))
                            if delivery_action:
                                citation=re.search(r'"deliveryActionCitation"\s*:\s*"(e[0-9]+)"',flattened).group(1)
                                message["coverage"].append(dict(requirement_id="process:0",evidence=citation))
                            if observation_fixture:
                                identifier=re.search(r'"processObligation"\s*:\s*"([^"]+)"',flattened).group(1)
                                citation=re.search(r'"hostCitation"\s*:\s*"(e[0-9]+)"',flattened).group(1)
                                completed=int(re.search(r'"completedAccesses"\s*:\s*(\d+)',flattened).group(1))
                                if missing_access:
                                    if completed:raise AssertionError("missing access was fabricated")
                                    message.update(verdict="partial",gaps=[dict(requirement_id=identifier,reason="No completed feedback access is observed before the handoff.")])
                                else:
                                    if not completed:raise AssertionError("native completed access receipt missing")
                                    message["coverage"].append(dict(requirement_id=identifier,evidence=citation))
                            if protocol_correction and (counts[role]==2 or correction_exhausted):
                                message.update(verdict="partial",gaps=[dict(requirement_id="invented-process-id",reason="protocol fault injection")])
                            if protocol_correction and counts[role]==3:
                                if "sole protocol correction" not in flattened:raise AssertionError("correction was not scoped")
                            if scoped_review:
                                message["terms_gap"] = [dict(element="extra artifact", reason="not requested", affected_requirements=["R2"])]
                                if counts[role] == 2:
                                    message.update(verdict="defeat", coverage=[], findings=[dict(requirement_id="R1",location="answer.txt",counterexample="contains first failed instead of ready")],residual="invent an unrequested extra artifact")
                                else:
                                    message["coverage"].append(dict(requirement_id="R2",evidence=candidates[-1]))
                            if partial_review:
                                message.update(verdict="partial",gaps=[dict(requirement_id="R2",reason="numeric format is not yet assessable")])
                                if counts[role]==2 or (local_binding_fault and counts[role]==3):
                                    message.update(coverage=[],findings=[dict(requirement_id="R1",location="answer.txt",counterexample="contains not ready instead of ready" if progression else "contains first failed instead of ready")])
                            if scoped_judgment:
                                if "assessments" not in props:
                                    raise AssertionError("worker did not receive scoped judgment schema")
                                rows = []
                                for identifier in ("R1", "R2"):
                                    findings = [dict(location=f["location"], counterexample=f["counterexample"])
                                        for f in message["findings"] if f["requirement_id"] == identifier]
                                    gaps = [g["reason"] for g in message.get("gaps", []) if g["requirement_id"] == identifier]
                                    if findings:
                                        judgment = dict(status="defeated", findings=findings, missing="; ".join(gaps))
                                    elif gaps:
                                        judgment = dict(status="unresolved", missing="; ".join(gaps))
                                    else:
                                        evidence = next(c["evidence"] for c in message["coverage"] if c["requirement_id"] == identifier)
                                        judgment = dict(status="supported", evidence=evidence)
                                    rows.append(dict(requirement_id=identifier,
                                        observations="Some local examples pass." if findings else "",
                                        judgment=judgment))
                                message = dict(assessments=rows, terms_gap=message["terms_gap"], missing=message["missing"])
                            if local_binding_fault:
                                # Both the first answer and its correction contain a bad
                                # binding on R2. R1's real defect must still reach repair.
                                message["assessments"][1]["judgment"] = dict(
                                    status="supported", evidence="citation_id="+candidates[-1])
                        elif (deadline_fixture or owner_cancel) and role == "executor" and (not owner_cancel or counts[role] == 1):
                            heartbeat = "import time\nfrom pathlib import Path\nPath('answer.txt').write_text('ready\\n')\nfor i in range(900):\n Path('heartbeat.txt').write_text(str(i))\n time.sleep(.1)\n"
                            code = "text(await tools.exec_command(" + json.dumps(dict(cmd="python3 -c " + shlex.quote(heartbeat),yield_time_ms=30000,max_output_tokens=1000)) + "));"
                            items = [custom_call(body, code, "wait-for-original-deadline")]
                            message = None
                        elif progression and role == "executor" and counts[role] <= 4:
                            stage = counts[role]
                            if stage == 1:
                                code = "text(await tools.exec_command({cmd:\"printf 'not ready\\n' > answer.txt\",yield_time_ms:1000,max_output_tokens:1000}));"
                                if resource_limit:
                                    code = "try {text(await tools.exec_command(" + json.dumps(dict(cmd="python3 -c 'print(chr(120)*1048576)'",yield_time_ms=1000,max_output_tokens=1000)) + "));} catch(e) {text(String(e));} " + code
                            elif stage == 2:
                                # Wait for the independently drafted terms, without providing feedback.
                                until = time.monotonic() + 10
                                while time.monotonic() < until:
                                    database = home / "pro_contract/ledger_1.sqlite"
                                    if database.exists():
                                        with sqlite3.connect(database) as connection:
                                            if connection.execute("SELECT count(*) FROM events").fetchone()[0]: break
                                    time.sleep(.05)
                                code = 'text(await tools.publish_progress({request_id:"first"}));'
                                if diagnostic_review:
                                    code = 'text(await tools.publish_progress({request_id:"first",review:true}));'
                                if publication_caller_loss:
                                    # Fault injection: end this code-mode caller while its
                                    # publication is executing. No model inference is used.
                                    code = 'void tools.publish_progress({request_id:"first"}); await new Promise(r=>setTimeout(r,250)); text("discarded publication waiter");'
                            elif stage == 3:
                                if publication_caller_loss:
                                    database = home / "pro_contract/ledger_1.sqlite"
                                    until = time.monotonic() + 15
                                    while time.monotonic() < until:
                                        with sqlite3.connect(database) as connection:
                                            row = connection.execute("SELECT json FROM records WHERE kind='progress_grant_v1'").fetchone()
                                        grant = json.loads(row[0]) if row else {}
                                        if grant.get('pending') == 'first':
                                            caller_loss_observed.append(True)
                                        elif caller_loss_observed:
                                            break
                                        time.sleep(.025)
                                    if not caller_loss_observed or grant.get('pending') is not None:
                                        raise AssertionError('caller loss did not retain and finalize the admitted publication')
                                code = successor_recall[:successor_recall.index('const frontier')] + r"""
const index = decode(await tools.contract_read_evidence({op:"index"}));
const entry = index.entries.find(x=>x.kind==="progress");
if (!entry) throw new Error("missing progress publication");
let record="";
for (let offset=0,i=0;i<100;i++) {
 const page=decode(await tools.contract_read_evidence({op:"read",handle:entry.handle,offset}));
 record+=page.text;if(page.eof)break;offset=page.next_offset;
}
const evidence=JSON.parse(record);
if(evidence.scope!=="progress_only" || !(evidence.public.checks.some(x=>x.receipt.outcome==="fail") || evidence.public.findings.length)) throw new Error("missing actionable progress feedback");
if(evidence.public.checks.some(x=>x.receipt.step.startsWith("sealed:"))) throw new Error("sealed leak");
text({sameTurnFeedback:true,subject:evidence.subject_hash});
text(await tools.exec_command({cmd:"printf 'ready\n' > answer.txt",yield_time_ms:1000,max_output_tokens:1000}));
"""
                            else:
                                code = 'text(await tools.publish_progress({request_id:"second"}));text(await tools.publish_progress({request_id:"second"}));'
                            if missing_access and stage==3:
                                code='text(await tools.exec_command({cmd:"printf \'ready\\n\' > answer.txt",yield_time_ms:1000,max_output_tokens:1000}));'
                            items = [custom_call(body, code, f"progress-{stage}")]
                            message = None
                        elif continuation_unknown and role=="executor" and counts[role]==3:
                            command="python3 -c 'from pathlib import Path; assert Path(\"answer.txt\").read_text().strip()==\"ready\"'"
                            code='text(await tools.contract_read_evidence({op:"index",offset:0}));text(await tools.exec_command('+json.dumps(dict(cmd=command,yield_time_ms=1000,max_output_tokens=1000))+'));'
                            items=[custom_call(body,code,"inspect-unresolved-artifact")];message=None
                        elif counts[role] == 1 or (owner_cancel and role == "executor" and counts[role] == 2) or ((repair_review or transport_failure) and role == "executor" and counts[role] == 3) or (continuation_history and role == "successor" and counts[role] == 3):
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
                                    + ",yield_time_ms:1000,max_output_tokens:1000});text(r);"
                                    + ('text(await tools.publish_progress({request_id:"successor-check"}));' if successor_progress and role=="successor" else ""),
                                    "write-answer",
                                )
                            ]
                            message = None
                        else:
                            message = final_response
                        if text_route and role == "executor" and counts[role] == 1 and waiting is None:
                            prefix = '''
if (ALL_TOOLS.some(t => t.name === "view_image")) throw new Error("image tool advertised on text route");
let imageBlocked = false;
try { await tools.view_image({path:"/workspace/example.png"}); }
catch (e) { imageBlocked = true; text("native-image-tool-disabled: " + String(e)); }
if (!imageBlocked) throw new Error("unexpected image capability");
image("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=");
'''
                            items[0]["input"] = prefix + items[0]["input"]
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
                        if input_strategy and role in ('executor','successor'):
                            probe = """import json
from pathlib import Path
p=Path('/inputs/source.txt')
content=p.read_text()
denied=[]
for operation in [lambda:p.write_text('changed'),p.unlink]:
 try:operation();denied.append(False)
 except OSError:denied.append(True)
assert content=='immutable source\\n' and all(denied)
Path('input-check.json').write_text(json.dumps({'content':content,'write_denied':denied[0],'unlink_denied':denied[1]}))
"""
                            for item in items:
                                if item.get('type')=='custom_tool_call':
                                    item['input']='text(await tools.exec_command('+json.dumps(dict(cmd='python3 -c '+shlex.quote(probe),yield_time_ms=1000,max_output_tokens=1000))+'));'+item['input']
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
            provider_url = f"http://127.0.0.1:{provider.server_port}/v1"
            gateway = request_budget = None
            if transport_failure:
                from procontract_benchmark_gateway import Budget, Gateway
                request_budget = Budget(root/'requests.sqlite', seconds=getattr(self,'task_seconds',120), requests=1000)
                gateway = Gateway(request_budget, provider_url, api_key="LOCAL_FIXTURE_ONLY")
                gateway_thread = threading.Thread(target=gateway.serve_forever,daemon=True)
                gateway_thread.start()
                original_request_grant = request_budget.arm()
                provider_url = gateway.base_url
            (source / "config.toml").write_text(
                procodex.toml(
                    dict(
                        model_provider="fixture",
                        model_providers=dict(
                            fixture=dict(
                                name="Local fixture",
                                base_url=provider_url,
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
                None if repair_review else 'python3 -c \'from pathlib import Path; assert Path("answer.txt").read_text().strip() == "ready"; print("NATIVE-CHECK-PASSED")\'',
                isolation="container-only",
                successor_sessions=2 if succession else 0,
                task_seconds=getattr(self, "task_seconds", 75 if late_successor else 60 if deadline_fixture else 3600),
                continuous_work=progression or successor_progress or deadline_fixture or owner_cancel or protocol_correction or late_successor,
                inputs={"source.txt": root/"source-input.txt"} if input_strategy else None,
                strategy=root/"strategy" if input_strategy else None,
            )
            if input_strategy:
                (root/'source-input.txt').unlink()
                settings_path=home/'pro_contract/settings.json'
                settings=json.loads(settings_path.read_text())
                settings['evaluation']['check']['build_command'] += " && python3 -c \"from pathlib import Path; assert Path('/inputs/source.txt').read_text() == 'immutable source\\n'\""
                settings_path.write_text(json.dumps(settings))
            if publication_caller_loss:
                settings_path=home/'pro_contract/settings.json'
                settings=json.loads(settings_path.read_text())
                settings['evaluation']['check']['build_command']='sleep 2; '+settings['evaluation']['check']['build_command']
                settings_path.write_text(json.dumps(settings))
            if late_successor:
                # Keep the cross-version control compatible with the old required field.
                # This explicit ceiling exceeds the entire 75-second task grant; only
                # the old inferred verification reserve can end the executor too early.
                settings_path = home / "pro_contract/settings.json"
                settings = json.loads(settings_path.read_text())
                settings["progress"]["executor_slice_secs"] = 1800
                settings_path.write_text(json.dumps(settings))
            if resource_limit:
                environment_path = home / "environments.toml"
                environment_path.write_text(environment_path.read_text().replace("33554432", "4096"))
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

            completed_turns = []
            def handle(value):
                if "id" in value and "method" in value:
                    server.refuse(value)
                if value.get('method') == 'turn/completed':
                    completed_turns.append(value['params']['turn'])

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
                started_turn = server.request(
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
                interrupted = False
                resumed_turn = None
                cancelled_grant = None
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
                            if owner_cancel and not interrupted and status.get('contract_id') and (workspace/'heartbeat.txt').exists():
                                server.request('turn/interrupt', {'threadId':thread,'turnId':started_turn['turn']['id']},handle)
                                interrupted = True
                            if status.get("resting"):
                                if transport_failure and not autonomous and resumed_turn is None:
                                    self.assertEqual(status.get('class'),'execution_interrupted',status)
                                    with sqlite3.connect(database) as connection:
                                        cancelled_grant=json.loads(connection.execute("SELECT json FROM records WHERE kind='succession'").fetchone()[0])
                                        original_commands=[json.loads(r[0])['command']['type'] for r in connection.execute('SELECT command_json FROM events ORDER BY seq')]
                                    self.assertNotIn('support',original_commands)
                                    self.assertIsNone(cancelled_grant['pending'])
                                    self.assertEqual(server.close()['status'],'exited')
                                    if server.process.stdout:server.process.stdout.close()
                                    server=AppServer([str(package/'bin/codex'),'--enable','pro_contract','--disable','hooks','app-server'],env,root/'rpc.jsonl',root/'stderr.log',cwd=workspace)
                                    server.request('initialize',{'clientInfo':{'name':'interrupted-task-recovery','version':'1'},'capabilities':{'experimentalApi':True}},handle)
                                    server.notify('initialized')
                                    restored=server.request('thread/resume',{'threadId':thread},handle)
                                    self.assertEqual(restored['thread']['id'],thread)
                                    resumed_turn=server.request('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Continue the same task from its retained work.','text_elements':[]}]},handle)['turn']['id']
                                    continue
                                if owner_cancel and resumed_turn is None:
                                    self.assertTrue(interrupted)
                                    self.assertEqual(status.get('class'),'no_handoff',status)
                                    with sqlite3.connect(database) as connection:
                                        cancelled_grant=json.loads(connection.execute("SELECT json FROM records WHERE kind='succession'").fetchone()[0])
                                    self.assertIsNone(cancelled_grant['deadline_ms'])
                                    self.assertEqual(server.close()['status'],'exited')
                                    if server.process.stdout: server.process.stdout.close()
                                    heartbeat=(workspace/'heartbeat.txt').read_text()
                                    time.sleep(.4)
                                    self.assertEqual((workspace/'heartbeat.txt').read_text(),heartbeat,'interrupted command is still writing')
                                    server=AppServer([str(package/'bin/codex'),'--enable','pro_contract','--disable','hooks','app-server'],env,root/'rpc.jsonl',root/'stderr.log',cwd=workspace)
                                    server.request('initialize',{'clientInfo':{'name':'open-task-recovery','version':'1'},'capabilities':{'experimentalApi':True}},handle)
                                    server.notify('initialized')
                                    restored=server.request('thread/resume',{'threadId':thread},handle)
                                    self.assertEqual(restored['thread']['id'],thread)
                                    resumed_turn=server.request('turn/start',{'threadId':thread,'input':[{'type':'text','text':'Continue the same task from the retained work.','text_elements':[]}]},handle)['turn']['id']
                                    continue
                                if (owner_cancel or (transport_failure and not autonomous)) and not any(t['id']==resumed_turn and t['status']=='completed' for t in completed_turns):
                                    continue
                                break
                self.assertEqual(errors, [])
                if input_strategy:
                    self.assertEqual(json.loads((workspace/'input-check.json').read_text()),
                        {'content':'immutable source\n','write_denied':True,'unlink_denied':True})
                    self.assertEqual((home/'inputs/files/source.txt').read_text(),'immutable source\n')
                self.assertEqual((workspace / "answer.txt").read_text(), "first failed\n" if continuation_rest else "ready\n")
                self.assertIsNotNone(status)
                if transport_failure:
                    self.assertEqual(len(injected_failures),1)
                    with sqlite3.connect(database) as connection:
                        grant_row=connection.execute("SELECT json FROM records WHERE kind='succession'").fetchone()
                        restored_grant=json.loads(grant_row[0]) if grant_row else None
                        commands=[json.loads(r[0])['command']['type'] for r in connection.execute('SELECT command_json FROM events ORDER BY seq')]
                    if not autonomous:
                        self.assertEqual(restored_grant,cancelled_grant)
                    else:
                        self.assertIsNone(resumed_turn, "autonomous recovery must not inject another user turn")
                        if restored_grant is None:
                            self.assertFalse(succession)
                            self.assertIsNone(getattr(self, 'task_seconds', 120))
                        else:
                            self.assertIsNone(restored_grant['pending'])
                            self.assertEqual(restored_grant['launches'], 1 if succession else 0)
                        if failure_after_write:
                            self.assertEqual(counts[transport_failure],1, "the interrupted write must not be replayed")
                        if failure_before_issue:
                            self.assertEqual(injected_failures[0]['issued_contracts'],0)
                        with sqlite3.connect(database) as connection:
                            observed=[json.loads(r[0])['body'] for r in connection.execute('SELECT event_json FROM experiment_events')]
                        snapshots=[v for v in observed if v.get('phase')=='interrupted_snapshot']
                        self.assertEqual(len(snapshots),1)
                        self.assertFalse(snapshots[0]['handoff'])
                        self.assertFalse(any(v.get('phase')=='task_delivery' and v.get('turn_id')==snapshots[0]['turn_id'] for v in observed))
                    self.assertEqual(commands.count('issue'),1)
                    self.assertEqual(commands.count('support'),1)
                    self.assertEqual(counts.get('draft'),1)
                    counts_after = request_budget.status()
                    self.assertEqual(counts_after['used'],len(requests))
                    self.assertEqual(counts_after['started'],original_request_grant['started'])
                    self.assertEqual(counts_after['deadline'],original_request_grant['deadline'])
                    self.assertEqual(request_budget.db.execute('SELECT count(*) FROM requests WHERE http_status=503').fetchone()[0],0 if output_truncation or stream_disconnect else 1)
                self.assertEqual(status["phase"], expected_phase or ("did_not_pass" if continuation_rest else "not_verified" if repair_review or partial_checks or deadline_fixture or missing_access or correction_exhausted else "supported"), status)
                if getattr(self, 'task_seconds', 'finite') is None:
                    with sqlite3.connect(database) as connection:
                        grant_row=connection.execute("SELECT json FROM records WHERE kind='succession'").fetchone()
                        grant=json.loads(grant_row[0]) if grant_row else None
                        commands=[json.loads(r[0])['command']['type'] for r in connection.execute('SELECT command_json FROM events ORDER BY seq')]
                        all_events=[json.loads(r[0])['body'] for r in connection.execute('SELECT event_json FROM experiment_events')]
                    if grant is not None:
                        self.assertIsNone(grant['deadline_ms']);self.assertIsNone(grant['grant']['total_secs'])
                    else:
                        self.assertNotIn('succession',json.loads((home/'pro_contract/settings.json').read_text()))
                    self.assertEqual(commands.count('issue'),1)
                    self.assertFalse(any(e.get('phase')=='original_grant_expired' for e in all_events))
                    if owner_cancel:
                        self.assertEqual(grant['started_ms'],cancelled_grant['started_ms'])
                        self.assertEqual(counts.get('draft'),1)
                if missing_access:
                    self.assertEqual(status["class"],"reviewer_unable")
                    self.assertIn("No completed feedback access",status["detail"])
                if protocol_correction:
                    self.assertEqual(counts.get("review"),3)
                    self.assertEqual(len(worker_keys["review"]),1,"correction spawned a fresh reviewer")
                    with sqlite3.connect(database) as connection:
                        attempts=[json.loads(x[0])["body"] for x in connection.execute("SELECT event_json FROM experiment_events") if 'review_protocol_result' in x[0]]
                    self.assertEqual([(x["attempt"],x["valid"]) for x in attempts],[(0,False),(1,not correction_exhausted)])
                if continuation_rest:
                    self.assertEqual(counts.get("continuation"),1)
                    self.assertEqual(counts.get("successor",0),0)
                    self.assertEqual(status["repairs_used"],0)
                    with sqlite3.connect(database) as connection:
                        commands=[json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events ORDER BY seq")]
                    self.assertEqual(commands,["issue","propose","defeat"])
                if continuation_unknown and not transport_failure:
                    with sqlite3.connect(database) as connection:
                        commands=[json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events ORDER BY seq")]
                        selections=[json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events") if 'continuation_decision' in r[0] and json.loads(r[0])["body"].get('assessment_scope') != 'handoff']
                    self.assertEqual(commands,["issue","propose","propose","support"])
                    self.assertEqual(len(selections),1)
                    self.assertEqual(selections[0]["choice"]["action"],"resume")
                    self.assertEqual(selections[0]["local_repairs_used"],1)
                    self.assertEqual(counts.get("draft"),1)
                if shared_citations:
                    with sqlite3.connect(database) as connection:
                        attempts = [json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events") if 'review_protocol_result' in r[0]]
                    self.assertEqual(len(attempts), 1)
                    self.assertTrue(attempts[0]["valid"])
                    h = attempts[0]["resolved_response"]
                    resolved = json.loads((home/"pro_contract/blobs"/h[:2]/h).read_text())
                    self.assertEqual(len(resolved["coverage"]), 19)
                    self.assertEqual(len(resolved["citations"]), 1)
                    key = resolved["coverage"][0]["evidence"]
                    self.assertTrue(all(c["evidence"] == key for c in resolved["coverage"]))
                    self.assertEqual(len(resolved["citations"][key]["quote"].encode()), 4096)
                    self.assertLess(len(json.dumps(resolved)), 16384)
                if structured_pages:
                    self.assertTrue(any('"structuredEvidencePages":true' in text.replace(" ", "") for request in requests for text in text_values(request)))
                if delivery_evidence:
                    with sqlite3.connect(database) as connection:
                        deliveries=[json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events WHERE kind='capture'") if 'task_delivery' in r[0]]
                    self.assertEqual(len(deliveries), 2 if succession else 1)
                    for delivered in deliveries:
                        handle=delivered["response"]["handle"]
                        document=json.loads((home/"pro_contract/blobs"/handle[:2]/handle).read_text())
                        self.assertEqual(document["text"],final_response)
                        self.assertEqual(document["original_bytes"],len(final_response.encode()))
                        self.assertTrue(document["complete"])
                        self.assertEqual(document["subject_hash"],delivered["subject_hash"])
                        self.assertEqual(document["turn_id"],delivered["turn_id"])
                if not partial_checks and not deadline_fixture and not continuation_rest and expected_phase != 'not_verified':self.assertGreaterEqual(counts.get("review", 0), 2)
                if deadline_fixture:
                    until=time.monotonic()+20
                    expired=[]
                    while time.monotonic()<until and not expired:
                        with sqlite3.connect(database) as connection:
                            events=[json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events WHERE kind='execution'")]
                        expired=[r for r in events if r.get("phase")=="original_grant_expired"]
                        if not expired:time.sleep(.05)
                    self.assertEqual(len(expired),1)
                    self.assertTrue(expired[0]["interrupt_and_executor_shutdown_confirmed"],expired)
                    with sqlite3.connect(database) as connection:
                        commands=[json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events ORDER BY seq")]
                        grant=json.loads(connection.execute("SELECT json FROM records WHERE kind='succession'").fetchone()[0])
                    self.assertEqual(commands,["issue"])
                    self.assertEqual(grant["deadline_ms"]-grant["started_ms"],60000)
                    heartbeat_path=workspace/"heartbeat.txt"
                    heartbeat_before=heartbeat_path.read_text()
                    time.sleep(1)
                    self.assertEqual(heartbeat_path.read_text(),heartbeat_before,"task-owned background writes outlived confirmed shutdown")
                    with sqlite3.connect(database) as connection:
                        status=json.loads(connection.execute("SELECT json FROM records WHERE kind='status'").fetchone()[0])
                    self.assertEqual(status["class"],"budget_exhausted")
                if repair_review:
                    self.assertEqual(status["class"], "reviewer_unable" if partial_review else "terms_gap")
                    self.assertEqual(counts.get("review"), 6 if progression or local_binding_fault else 4)
                    self.assertEqual(status["repairs_used"], 0 if progression else 1)
                    with contextlib.closing(sqlite3.connect(database.as_uri()+"?mode=ro",uri=True)) as connection:
                        commands=[json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events WHERE contract_id=? ORDER BY seq",(thread+".1",))]
                    self.assertEqual(commands,["issue","propose"] if progression else ["issue","propose","defeat","propose"])
                    if local_binding_fault:
                        with sqlite3.connect(database) as connection:
                            protocol=[json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events") if 'review_protocol_result' in r[0]]
                        self.assertEqual([(p["attempt"],p["valid"]) for p in protocol],[(0,False),(1,False)]*2)
                        for p in protocol:
                            h=p["resolved_response"]
                            retained=json.loads((home/"pro_contract/blobs"/h[:2]/h).read_text())
                            self.assertEqual(retained["verdict"],"partial")
                            self.assertTrue(any(g["requirement_id"]=="R2" for g in retained["gaps"]))
                        self.assertEqual((workspace/"answer.txt").read_text().strip(),"ready")
                if progression:
                    if publication_caller_loss:
                        self.assertTrue(caller_loss_observed)
                    self.assertEqual(counts.get("executor"), 5)
                    self.assertEqual(any("sameTurnFeedback" in text for request in requests for text in text_values(request)),not missing_access)
                    with sqlite3.connect(database) as connection:
                        commands = [json.loads(r[0])["command"]["type"] for r in connection.execute("SELECT command_json FROM events ORDER BY seq")]
                        grant = json.loads(connection.execute("SELECT json FROM records WHERE kind='progress_grant_v1'").fetchone()[0])
                        observations = [json.loads(r[0])["body"] for r in connection.execute("SELECT event_json FROM experiment_events WHERE kind='execution' ORDER BY seq")]
                    self.assertEqual(commands, ["issue", "propose"] + ([] if partial_review or missing_access else ["support"]))
                    if resource_limit:
                        self.assertTrue(any("raw output limit" in text for request in requests for text in text_values(request)))
                    self.assertEqual(grant["used"], 2)
                    self.assertIsNone(grant["pending"])
                    self.assertEqual(len([r for r in observations if r.get("phase")=="progress_assessed"]), 2)
                    if diagnostic_review:
                        first=next(r for r in observations if r.get('phase')=='progress_assessed')
                        handle=first['public_evidence']
                        record=json.loads((home/'pro_contract/blobs'/handle[:2]/handle).read_text())
                        self.assertTrue(record['diagnostic_review'])
                        self.assertIn(record['public']['review']['verdict']['type'],('defeat','partial'))
                        self.assertEqual(len(record['public']['findings']),1)
                if probe_fixture:
                    self.assertEqual(len(worker_keys.get("explore", set())), 2)
                    self.assertEqual(len(worker_keys.get("probe", set())), 1)
                if successor_progress:
                    with sqlite3.connect(database) as connection:
                        grant = json.loads(connection.execute("SELECT json FROM records WHERE kind='progress_grant_v1'").fetchone()[0])
                    self.assertEqual(grant["used"], 1)
                    self.assertIsNone(grant["pending"])
                if succession and not transport_failure and not continuation_rest:
                    self.assertTrue(any("publicEvidenceRecall" in text and "true" in text
                        for request in requests for item in request.get("input", [])
                        if item.get("type") in ("custom_tool_call_output", "function_call_output")
                        for text in text_values(item)),
                        "the real successor must consume retained public evidence before repairing")
                    self.assertEqual(len(worker_keys.get("draft", set())), 1)
                    self.assertEqual(counts.get("successor"), 4 if continuation_history else 2)
                    if continuation_history:
                        self.assertEqual(counts.get("continuation"), 2,
                            "each complete selection input must reach the model in one request")
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
                    self.assertEqual(commands, ["issue", "propose", "defeat", "propose"] + (["propose"] if continuation_history else []) + ([] if partial_checks else ["support"]))
                    self.assertEqual((budget["launches"], budget["pending"]), (2 if continuation_history else 1, None))
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
                if gateway:
                    gateway.shutdown();gateway.server_close();gateway_thread.join()
                provider.shutdown()
                provider.server_close()
                self.native_counts = dict(counts)
                self.native_status = status
                database = home / "pro_contract/ledger_1.sqlite"
                if database.exists():
                    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
                        self.native_commands=[json.loads(v[0])['command']['type'] for v in connection.execute('SELECT command_json FROM events ORDER BY seq')]
                        self.native_events=[json.loads(v[0]) for v in connection.execute('SELECT event_json FROM experiment_events ORDER BY seq')]
                    self.native_public={}
                    for event in self.native_events:
                        if handle := event['body'].get('public_evidence'):
                            blob=home/'pro_contract/blobs'/handle[:2]/handle
                            if blob.exists():self.native_public[handle]=json.loads(blob.read_text())
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
                                local_binding_fault_fixture=local_binding_fault,
                                dialogue_probe_fixture=dialogue_probe,partial_checks_fixture=partial_checks,
                                real_provider_calls=0 if continuation_model is None and selection_model is None else None,
                                continuation_backend="scripted" if continuation_model is None and selection_model is None else "injected_callback",
                                usage_scope="Synthetic local-provider usage; an injected callback requires its own backend accounting.",
                                transport_failure_fixture=transport_failure,injected_failures=injected_failures,
                                request_budget=request_budget.status() if request_budget else None,
                                progress_fixture=progression,resource_limit_fixture=resource_limit,
                                publication_caller_loss_fixture=publication_caller_loss,caller_loss_observed=bool(caller_loss_observed),
                                successor_progress_fixture=successor_progress,deadline_fixture=deadline_fixture,
                                owner_cancel_fixture=owner_cancel,task_seconds=getattr(self,'task_seconds',75 if late_successor else 60 if deadline_fixture else 3600),
                            ),
                            indent=2,
                        )
                    )
                    (destination / "requests.json").write_text(
                        json.dumps(requests, indent=2)
                    )
                    if request_budget:
                        with sqlite3.connect(destination/'requests.sqlite') as saved:
                            request_budget.db.backup(saved)
                    if computation or partial_checks or dialogue_probe or progression or successor_progress:
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
                                body = event.get("body", {})
                                if body.get("phase") in ("review_protocol_result", "review_checkpoint"):
                                    for key in ("raw_response", "resolved_response", "handle"):
                                        h = body.get(key)
                                        if isinstance(h, str):
                                            blob = home/"pro_contract/blobs"/h[:2]/h
                                            if blob.is_file():
                                                public.mkdir(exist_ok=True)
                                                shutil.copy2(blob, public/h)
                                handle = event.get("body", {}).get("public_evidence")
                                public_event = event.get("kind") == "verification" or event.get("body",{}).get("phase") in ("progress_assessed","handoff_ready","work_assessed")
                                if not public_event or not isinstance(handle, str):
                                    continue
                                blob = home / "pro_contract/blobs" / handle[:2] / handle
                                if blob.is_file():
                                    public.mkdir(exist_ok=True)
                                    shutil.copy2(blob, public / handle)
                                    document=json.loads(blob.read_text())
                                    response=document.get("delivery_message") or document.get("public",{}).get("delivery_message")
                                    if response:
                                        shutil.copy2(home/"pro_contract/blobs"/response[:2]/response,public/response)
                                    observation=document.get("host_observations") or document.get("public",{}).get("host_observations")
                                    if observation:
                                        shutil.copy2(home/"pro_contract/blobs"/observation[:2]/observation,public/observation)
                if request_budget: request_budget.close()


if __name__ == "__main__":
    unittest.main()
