use super::ReviewEvidence;
use crate::BlobStore;
use crate::CapturePolicy;
use crate::Terms;
use crate::capture;
use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn fixture(text: &str) -> (tempfile::TempDir, ReviewEvidence) {
    let root = tempfile::tempdir().unwrap();
    let workspace = root.path().join("workspace");
    std::fs::create_dir(&workspace).unwrap();
    std::fs::write(workspace.join("hindsight.json"), text).unwrap();
    let store = BlobStore::open(&root.path().join("blobs")).unwrap();
    let subject = capture(
        &workspace,
        &CapturePolicy {
            version: 1,
            excluded_paths: vec![],
            max_file_bytes: 1 << 20,
            max_total_bytes: 1 << 24,
        },
        &store,
    )
    .unwrap();
    let evidence = ReviewEvidence::new(
        subject,
        store,
        &Terms {
            context: Vec::new(),
            intake_text: "Write hindsight.json".to_string(),
            requirements: vec![crate::Requirement {
                id: "R1".to_string(),
                text: "hindsight.json exists".to_string(),
                source_quote: "Write hindsight.json".to_string(),
                inferred: false,
            }],
            out_of_scope: vec![],
            process_constraints: vec![],
        },
        "build passed".to_string(),
    )
    .unwrap();
    (root, evidence)
}

fn read(evidence: &mut ReviewEvidence, request: Value) -> Value {
    let response = evidence.respond(request);
    assert!(response.success);
    let DynamicToolCallOutputContentItem::InputText { text } = &response.content_items[0] else {
        panic!("text");
    };
    assert!(text.len() <= super::MAX_REPLY);
    serde_json::from_str(text).unwrap()
}

fn document(evidence: &mut ReviewEvidence, id: &str) -> (String, Value) {
    let mut offset = 0;
    let mut result = String::new();
    loop {
        let page = read(
            evidence,
            json!({"op":"read","source_id":id,"offset":offset}),
        );
        result.push_str(page["text"].as_str().unwrap());
        if page["eof"] == true {
            return (result, page["citation_id"].clone());
        }
        offset = page["next_offset"].as_u64().unwrap();
    }
}

async fn checkpoint_fixture() -> (tempfile::TempDir, ReviewEvidence, crate::Ledger) {
    let (root, evidence) = fixture("artifact");
    let config = codex_state::SqliteConfig::new_for_testing(
        codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(root.path()).unwrap(),
    );
    let ledger = crate::Ledger::open(&config, root.path()).await.unwrap();
    let evidence = evidence.with_protocol_log(
        ledger.clone(),
        Default::default(),
        json!({
            "contract_id":"task","revision":1,"formal":false,"assessment_id":"one",
        }),
    );
    (root, evidence, ledger)
}

#[tokio::test]
async fn checkpoints_resolve_citations_are_durable_and_do_not_relabel_changed_work() {
    let (_root, mut evidence, ledger) = checkpoint_fixture().await;
    document(&mut evidence, "human_request");
    document(&mut evidence, "contract_terms");
    let (_, citation) = document(&mut evidence, "file:0");
    let request = json!({"checkpoint_id":"one","review":{
        "assessments":[{"requirement_id":"R1","observations":"The file is present.",
            "judgment":{"status":"supported","evidence":citation}}],"terms_gap":[],"missing":""}});
    let first = evidence.record_checkpoint(request.clone()).await;
    assert!(first.success);
    assert!(evidence.record_checkpoint(request.clone()).await.success);
    assert_eq!(ledger.experiments().await.unwrap().len(), 1);
    let event = ledger.experiments().await.unwrap().remove(0).event;
    let handle = serde_json::from_value(event.body["handle"].clone()).unwrap();
    let retained: Value = serde_json::from_slice(&evidence.store.get(&handle).unwrap()).unwrap();
    assert_eq!(retained["completion_certified"], false);
    assert_eq!(retained["review"]["verdict"]["type"], "support");
    assert!(
        retained["review"]["verdict"]["coverage"][0]["evidence"]
            .as_str()
            .unwrap()
            .contains("sha256")
    );
    let mut changed = request.clone();
    changed["review"]["assessments"][0]["observations"] = json!("changed work");
    assert!(!evidence.record_checkpoint(changed).await.success);
    // Recreate the evidence capability: receipt recall does not depend on its
    // previous citation counter or worker history, and performs no new action.
    let restored = ReviewEvidence::new(
        evidence.subject.clone(),
        evidence.store.clone(),
        &evidence.terms,
        "checks".into(),
    )
    .unwrap()
    .with_protocol_log(
        ledger.clone(),
        Default::default(),
        evidence.protocol_log.as_ref().unwrap().2.clone(),
    );
    assert!(restored.record_checkpoint(request).await.success);
    assert_eq!(ledger.experiments().await.unwrap().len(), 1);
}

#[tokio::test]
async fn invalid_checkpoint_does_not_discard_prior_valid_work_or_create_new_obligations() {
    let (_root, evidence, ledger) = checkpoint_fixture().await;
    let valid = json!({"checkpoint_id":"finding","review":{
        "assessments":[{"requirement_id":"R1","observations":"Local observation.",
            "judgment":{"status":"defeated","findings":[{"location":"artifact","counterexample":"observed wrong value"}],"missing":"other behavior unexamined"}}],
        "terms_gap":[],"missing":""}});
    assert!(evidence.record_checkpoint(valid.clone()).await.success);
    let mut invalid = valid;
    invalid["checkpoint_id"] = json!("invalid");
    invalid["review"]["assessments"][0]["requirement_id"] = json!("invented-obligation");
    assert!(!evidence.record_checkpoint(invalid).await.success);
    assert_eq!(ledger.experiments().await.unwrap().len(), 1);
    let unissued = json!({"checkpoint_id":"false-support","review":{
        "assessments":[{"requirement_id":"R1","observations":"claim",
            "judgment":{"status":"supported","evidence":"e99"}}],"terms_gap":[],"missing":""}});
    assert!(!evidence.record_checkpoint(unissued).await.success);
    assert_eq!(ledger.experiments().await.unwrap().len(), 1);
}

#[test]
fn prior_diagnosis_is_context_and_cannot_be_cited_as_current_artifact_or_execution_proof() {
    let (_root, evidence) = fixture("new artifact");
    let mut evidence = evidence
        .with_diagnosis(
            Some("Investigate the remaining issue"),
            Some(json!({
                "subject_hash":"old-subject","review":{"verdict":"support"}
            })),
        )
        .unwrap();
    document(&mut evidence, "human_request");
    document(&mut evidence, "contract_terms");
    let (_, prior) = document(&mut evidence, "prior_assessment");
    let response = json!({"assessments":[{"requirement_id":"R1","observations":"prior claim",
        "judgment":{"status":"supported","evidence":prior}}],"terms_gap":[],"missing":""});
    assert!(
        evidence
            .resolve_review(&response.to_string())
            .unwrap_err()
            .to_string()
            .contains("not observed evidence")
    );
}

#[test]
fn execution_coverage_requires_scoped_host_evidence_and_rejects_self_attestation() {
    let (_root, previous) = fixture("artifact");
    let mut terms = previous.terms.clone();
    terms.process_constraints.push(crate::ProcessConstraint {
        text: "Access the feedback".into(),
        source_quote: "Access the feedback".into(),
    });
    let subject = previous.subject.clone();
    let mut evidence = ReviewEvidence::new(subject.clone(), previous.store, &terms, "checks".into()).unwrap()
        .with_delivery_message(json!({"kind":"native_final_response","subject_hash":subject.subject_hash,
            "complete":true,"text":"I read the feedback."})).unwrap()
        .with_host_observations(json!({"kind":"host_observations_v1","subject_hash":subject.subject_hash,
            "terms_hash":crate::digest_of("terms",&terms),"observation":"native tool completed with the recorded feedback bytes"})).unwrap();
    for id in ["human_request", "contract_terms"] {
        document(&mut evidence, id);
    }
    let (_, artifact) = document(&mut evidence, "file:0");
    let (_, claim) = document(&mut evidence, "delivery_message");
    let (_, observed) = document(&mut evidence, "host_observations");
    let response = |citation: Value| {
        json!({"verdict":"support","coverage":[
        {"requirement_id":"R1","evidence":artifact},{"requirement_id":"process:0","evidence":citation}],
        "findings":[],"gaps":[],"terms_gap":[],"missing":"","residual":""}).to_string()
    };
    assert!(evidence.resolve_review(&response(claim)).is_err());
    // Even a successful computation over artifact bytes cannot attest a past read.
    evidence.computations.push(
        json!({"execution":{"state":"completed","shutdown_confirmed":true,"truncated":false},
        "output_truncated":false,"requirements":["process:0"],"stdout":"feedback read"})
        .to_string(),
    );
    let (_, computation) = document(&mut evidence, "computation:0");
    assert!(evidence.resolve_review(&response(computation)).is_err());
    assert!(evidence.resolve_review(&response(observed)).is_ok());
    assert!(evidence.with_host_observations(json!({"kind":"host_observations_v1",
        "subject_hash":codex_pro_contract::Digest::of(b"foreign"),"terms_hash":crate::digest_of("terms",&terms)})).is_err());
}

#[test]
fn a_host_check_receipt_can_evidence_a_check_execution_obligation() {
    let (_root, previous) = fixture("artifact");
    let mut terms = previous.terms.clone();
    terms.process_constraints.push(crate::ProcessConstraint {
        text: "Run the configured check".into(),
        source_quote: "Run the configured check".into(),
    });
    let mut evidence = ReviewEvidence::new(
        previous.subject,
        previous.store,
        &terms,
        "Host checker action after capture: configured check completed successfully.".into(),
    )
    .unwrap();
    for id in ["human_request", "contract_terms"] {
        document(&mut evidence, id);
    }
    let (_, artifact) = document(&mut evidence, "file:0");
    let (_, check) = document(&mut evidence, "check_receipts");
    let message = json!({"verdict":"support","coverage":[
        {"requirement_id":"R1","evidence":artifact},
        {"requirement_id":"process:0","evidence":check}],
        "findings":[],"gaps":[],"terms_gap":[],"missing":"","residual":""})
    .to_string();
    let resolved = evidence.resolve_review(&message).unwrap();
    let value: Value = serde_json::from_str(&resolved).unwrap();
    let citation: Value =
        serde_json::from_str(value["coverage"][1]["evidence"].as_str().unwrap()).unwrap();
    assert_eq!(citation["source_id"], "check_receipts");
    assert!(
        citation["quote"]
            .as_str()
            .unwrap()
            .contains("after capture")
    );
}

#[test]
fn scoped_judgments_resolve_support_citations_without_promoting_observations() {
    let (_root, mut evidence) = fixture("artifact");
    for id in ["human_request", "contract_terms"] {
        document(&mut evidence, id);
    }
    let (_, citation) = document(&mut evidence, "file:0");
    let mut message = json!({"assessments":[{
        "requirement_id":"R1", "observations":"Some local behavior is visible.",
        "judgment":{"status":"supported", "evidence":citation}
    }],"terms_gap":[],"missing":""});
    let resolved = evidence.resolve_review(&message.to_string()).unwrap();
    let value: Value = serde_json::from_str(&resolved).unwrap();
    let bound: Value =
        serde_json::from_str(value["coverage"][0]["evidence"].as_str().unwrap()).unwrap();
    assert_eq!(bound["source_id"], "file:0");
    assert_eq!(
        value["observations"][0]["detail"],
        "Some local behavior is visible."
    );
    message["assessments"][0]["judgment"]["evidence"] = json!("e99999");
    assert!(evidence.resolve_review(&message.to_string()).is_err());
    message["assessments"][0]["judgment"] = json!({"status":"defeated",
        "findings":[{"location":"artifact", "counterexample":"The boundary case fails."}], "missing":""});
    let parsed = super::super::reviewer::parse(
        &evidence.resolve_review(&message.to_string()).unwrap(),
        &evidence.terms,
    )
    .unwrap();
    assert_eq!(parsed.actionable_findings().len(), 1);
    assert_eq!(parsed.observations.len(), 1);
}

#[test]
fn computation_intent_is_not_an_artificial_requirement_boundary() {
    let (_root, original) = fixture("artifact");
    let mut terms = original.terms.clone();
    terms.requirements.push(crate::Requirement {
        id: "R2".into(),
        text: "The artifact has eight bytes".into(),
        source_quote: "The artifact has eight bytes".into(),
        inferred: false,
    });
    let mut evidence =
        ReviewEvidence::new(original.subject, original.store, &terms, "checks".into()).unwrap();
    for source in ["human_request", "contract_terms"] {
        document(&mut evidence, source);
    }
    let mut computation = json!({"subject_hash":evidence.subject.subject_hash,
        "requirements":["R1"], "execution":{"state":"completed", "shutdown_confirmed":true, "truncated":false},
        "output_truncated":false, "stdout":"artifact content and length=8"});
    evidence.computations.push(computation.to_string());
    let (_, citation) = document(&mut evidence, "computation:0");
    let response = json!({"assessments":[{"requirement_id":"R2", "observations":"Same observed bytes also establish their length.",
        "judgment":{"status":"supported", "evidence":citation}}], "terms_gap":[], "missing":""}).to_string();
    assert!(evidence.resolve_review(&response).is_ok());
    computation["subject_hash"] = json!(codex_pro_contract::Digest::of(b"another subject"));
    evidence.computations[0] = computation.to_string();
    let error = evidence.resolve_review(&response).unwrap_err().to_string();
    assert!(
        error.contains("R2")
            && error.contains(citation.as_str().unwrap())
            && error.contains("another frozen subject")
    );
    computation["subject_hash"] = json!(evidence.subject.subject_hash);
    computation["output_truncated"] = json!(true);
    evidence.computations[0] = computation.to_string();
    assert!(
        evidence
            .resolve_review(&response)
            .unwrap_err()
            .to_string()
            .contains("truncated")
    );
}

#[test]
fn delivery_response_is_subject_bound_and_truncated_text_cannot_support_coverage() {
    let (_root, evidence) = fixture("artifact");
    assert!(evidence.with_delivery_message(json!({
        "kind":"native_final_response", "subject_hash":codex_pro_contract::Digest::of(b"foreign"),
        "complete":true, "text":"foreign response"
    })).is_err());
    for complete in [false, true] {
        let (_root, evidence) = fixture("artifact");
        let response = json!({"kind":"native_final_response", "subject_hash":evidence.subject.subject_hash,
            "complete":complete, "text":"Requested final explanation, not independent proof."});
        let mut evidence = evidence.with_delivery_message(response.clone()).unwrap();
        for id in ["human_request", "contract_terms"] {
            document(&mut evidence, id);
        }
        let (text, citation) = document(&mut evidence, "delivery_message");
        assert_eq!(serde_json::from_str::<Value>(&text).unwrap(), response);
        let review =
            json!({"verdict":"support", "coverage":[{"requirement_id":"R1","evidence":citation}],
            "findings":[],"terms_gap":[],"missing":"","residual":""})
            .to_string();
        assert_eq!(evidence.resolve_review(&review).is_ok(), complete);
    }
}

#[tokio::test]
async fn frozen_binary_computation_has_scoped_citations_and_cannot_write_or_claim_failed_checks() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let (root, mut evidence) = fixture("placeholder");
    let workspace = root.path().join("workspace");
    let generated = std::process::Command::new("python3")
        .args([
            "-c",
            r#"
import io,struct,sys,zipfile
header=b"{'descr': '<f8', 'fortran_order': False, 'shape': (3,), }\n"
npy=b'\x93NUMPY\x01\x00'+struct.pack('<H',len(header))+header+struct.pack('<3d',1.,2.,3.)
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as z:z.writestr('x.npy',npy)
sys.stdout.buffer.write(out.getvalue())
"#,
        ])
        .output()
        .unwrap();
    assert!(generated.status.success());
    std::fs::write(workspace.join("hindsight.json"), generated.stdout).unwrap();
    evidence.subject = capture(
        &workspace,
        &CapturePolicy::standard(vec![]),
        &evidence.store,
    )
    .unwrap();
    // The computation must see the captured version, not this mutable workspace.
    std::fs::write(workspace.join("hindsight.json"), "changed after freeze").unwrap();
    let environment = crate::CheckEnvironment {
        inputs: Vec::new(),
        docker: "docker".into(),
        image,
        user: "1000:1000".into(),
        candidate_mount: "/candidate".into(),
        timeout_secs: 30,
        build_command: None,
        candidate_command: None,
    };
    let grant = crate::ReviewExecution {
        max_calls: 2,
        timeout_secs: 10,
        max_output_bytes: 4096,
    };
    evidence = evidence
        .with_execution(
            environment,
            grant,
            root.path().join("review"),
            std::time::Duration::from_secs(60),
        )
        .unwrap();
    let code = r#"import ast,struct,zipfile
from pathlib import Path
data=zipfile.ZipFile('/evidence/file-0').read('x.npy')
assert data[:8]==b'\x93NUMPY\x01\x00'
n=struct.unpack('<H',data[8:10])[0]
header=ast.literal_eval(data[10:10+n].decode())
assert header['descr']=='<f8' and header['shape']==(3,)
assert struct.unpack('<3d',data[10+n:])==(1.,2.,3.)
try:
 Path('/evidence/file-0').write_bytes(b'changed')
 raise AssertionError('frozen evidence was writable')
except PermissionError: pass
except OSError as error: assert error.errno==30
assert not Path('/workspace').exists()
Path('/tmp/result').write_text('scratch is writable')
print('sum=6; original frozen bytes; isolated writable scratch')
"#;
    let response = evidence
        .inspect(
            json!({"source_ids":["file:0"],"requirements":["R1"],"python":code}),
            std::time::Duration::from_secs(20),
        )
        .await;
    assert!(response.success, "{response:?}");
    for id in ["human_request", "contract_terms"] {
        document(&mut evidence, id);
    }
    let (text, citation) = document(&mut evidence, "computation:0");
    let result: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(result["execution"]["state"], "completed", "{result}");
    assert!(result["stdout"].as_str().unwrap().contains("sum=6"));
    let supported = |citation: Value| {
        json!({"verdict":"support","coverage":[{"requirement_id":"R1","evidence":citation}],
        "findings":[],"terms_gap":[],"missing":"","residual":""})
        .to_string()
    };
    assert!(evidence.resolve_review(&supported(citation)).is_ok());
    let response = evidence.inspect(json!({"source_ids":[],"requirements":["R1"],"python":"assert False, 'counterexample'"}),std::time::Duration::from_secs(20)).await;
    assert!(response.success);
    let (text, citation) = document(&mut evidence, "computation:1");
    let failed: Value = serde_json::from_str(&text).unwrap();
    assert_ne!(failed["execution"]["state"], "completed");
    assert!(evidence.resolve_review(&supported(citation)).is_err());
    let refused = evidence
        .inspect(
            json!({"source_ids":[],"requirements":["R1"],"python":"print('third')"}),
            std::time::Duration::from_secs(20),
        )
        .await;
    assert!(!refused.success);
}

#[test]
fn frozen_data_is_paged_and_support_references_resolve_without_model_hashes() {
    let (root, mut evidence) = fixture(&"\"中文\\\n".repeat(1000));
    let original = std::fs::read_to_string(root.path().join("workspace/hindsight.json")).unwrap();
    std::fs::write(
        root.path().join("workspace/hindsight.json"),
        "changed later",
    )
    .unwrap();
    let mut restored = String::new();
    let mut offset = 0;
    let handle = loop {
        let chunk = read(
            &mut evidence,
            json!({"op":"read","source_id":"file:0","offset":offset}),
        );
        restored.push_str(chunk["text"].as_str().unwrap());
        if chunk["eof"] == true {
            break chunk["citation_id"].clone();
        }
        offset = chunk["next_offset"].as_u64().unwrap();
    };
    assert_eq!(restored, original);
    for source in ["human_request", "contract_terms"] {
        let chunk = read(
            &mut evidence,
            json!({"op":"read","source_id":source,"offset":0}),
        );
        assert_eq!(chunk["eof"], true);
    }
    let result = evidence.resolve_review(&json!({"verdict":"support","findings":[],"terms_gap":[],"missing":"","residual":"","coverage":[{"requirement_id":"R1","evidence":handle}]}).to_string()).unwrap();
    let result: Value = serde_json::from_str(&result).unwrap();
    let cited: Value =
        serde_json::from_str(result["coverage"][0]["evidence"].as_str().unwrap()).unwrap();
    assert_eq!(cited["source_id"], "file:0");
    assert_eq!(
        cited["quote"].as_str().unwrap(),
        &original
            [cited["start"].as_u64().unwrap() as usize..cited["end"].as_u64().unwrap() as usize]
    );
}

#[test]
fn arbitrary_paths_writes_and_unissued_or_request_only_citations_are_refused() {
    let (_root, mut evidence) = fixture(&"\"中文\\\n".repeat(1000));
    for request in [
        json!({"op":"read","source_id":"/etc/passwd","offset":0}),
        json!({"op":"write","source_id":"file:0","offset":0}),
        json!({"op":"read","source_id":"file:0","offset":0,"path":"/etc/passwd"}),
    ] {
        assert!(!evidence.respond(request).success);
    }
    for handle in ["e0", "file:0", "e99999"] {
        assert!(evidence.resolve_review(&json!({"verdict":"support","findings":[],"terms_gap":[],"missing":"","residual":"","coverage":[{"requirement_id":"R1","evidence":handle}]}).to_string()).is_err());
    }
    let chunk = read(
        &mut evidence,
        json!({"op":"read","source_id":"human_request","offset":0}),
    );
    assert!(evidence.resolve_review(&json!({"verdict":"support","findings":[],"terms_gap":[],"missing":"","residual":"","coverage":[{"requirement_id":"R1","evidence":chunk["citation_id"]}]}).to_string()).is_err());
}

#[test]
fn prompt_is_bounded_and_documents_are_accessible_without_dumping_artifacts() {
    let (_root, mut evidence) = fixture(&"\"中文\\\n".repeat(1000));
    assert!(
        evidence
            .prompt(crate::workers::reviewer::DEFAULT_INSTRUCTIONS)
            .len()
            < 4096
    );
    let request = read(
        &mut evidence,
        json!({"op":"read","source_id":"human_request","offset":0}),
    );
    assert_eq!(request["text"], "Write hindsight.json");
    let checks = read(
        &mut evidence,
        json!({"op":"read","source_id":"check_receipts","offset":0}),
    );
    assert_eq!(checks["text"], "build passed");
}

#[test]
fn baseline_identity_compares_frozen_entries_not_later_workspace_bytes() {
    let (root, mut evidence) = fixture("original");
    let baseline = evidence.subject.clone();
    evidence = evidence.with_baseline(baseline);
    std::fs::write(
        root.path().join("workspace/hindsight.json"),
        "later mutable work",
    )
    .unwrap();
    let same = read(
        &mut evidence,
        json!({"op":"index","source_id":"","offset":3}),
    );
    assert_eq!(same["entry"]["matches_original_entry"], true);
    evidence.subject = capture(
        &root.path().join("workspace"),
        &CapturePolicy::standard(vec![]),
        &evidence.store,
    )
    .unwrap();
    let changed = read(
        &mut evidence,
        json!({"op":"index","source_id":"","offset":3}),
    );
    assert_eq!(changed["entry"]["matches_original_entry"], false);
}
