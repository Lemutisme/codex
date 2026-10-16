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
    assert!(text.len() <= 900);
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
