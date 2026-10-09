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
