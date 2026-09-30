use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::Draft;
use super::DraftInput;
use super::parse;
use super::prompt;
use super::schema;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::Requirement;
use crate::Terms;
use crate::WorkerError;

const INTAKE: &str =
    "Implement the program so it behaves like the reference.\nKeep the exit codes identical.";

fn input() -> DraftInput<'static> {
    DraftInput {
        intake_text: INTAKE,
        base_view: "README.md (407 bytes)",
        reference_observations: Some("usage: tool [OPTIONS] [FILE]"),
        reference_command: Some("/workspace/executable"),
        build_command: Some("./compile.sh"),
        candidate_command: Some("./executable"),
    }
}

/// Every object in a strict schema must list all of its properties as required and forbid
/// additional properties.
fn assert_strict(value: &Value) {
    if let Some(object) = value.as_object() {
        if object.get("type") == Some(&json!("object")) {
            let properties = object["properties"].as_object().expect("properties");
            let mut required: Vec<&str> = object["required"]
                .as_array()
                .expect("required")
                .iter()
                .map(|value| value.as_str().expect("name"))
                .collect();
            required.sort_unstable();
            let mut names: Vec<&str> = properties.keys().map(String::as_str).collect();
            names.sort_unstable();
            assert_eq!(required, names);
            assert_eq!(object["additionalProperties"], json!(false));
        }
        for child in object.values() {
            assert_strict(child);
        }
    } else if let Some(items) = value.as_array() {
        for child in items {
            assert_strict(child);
        }
    }
}

#[test]
fn the_schema_is_strict() {
    assert_strict(&schema());
}

#[test]
fn the_prompt_carries_the_verbatim_intake_and_stays_bounded() {
    let huge = "x".repeat(200_000);
    let text = prompt(&DraftInput {
        base_view: &huge,
        ..input()
    });
    assert!(text.contains(INTAKE));
    assert!(text.contains("usage: tool [OPTIONS] [FILE]"));
    assert!(text.len() < 90_000, "prompt is {} bytes", text.len());
}

fn message(value: Value) -> String {
    serde_json::to_string(&value).expect("json")
}

#[test]
fn a_contract_draft_becomes_terms_and_an_evidence_policy() {
    let draft = parse(
        &message(json!({
            "decision": "contract",
            "reason": "substantive implementation request",
            "requirements": [{
                "id": "R1",
                "text": "Exit codes match the reference.",
                "source_quote": "Keep the exit codes   identical.",
                "inferred": false
            }],
            "out_of_scope": [],
            "differential_cases": [{"id": "D1", "args": ["--help"], "stdin": null}],
            "candidate_tests": true
        })),
        &input(),
    )
    .expect("draft");
    assert_eq!(
        draft,
        Draft::Contract {
            terms: Terms {
                intake_text: INTAKE.to_string(),
                requirements: vec![Requirement {
                    id: "R1".to_string(),
                    text: "Exit codes match the reference.".to_string(),
                    source_quote: "Keep the exit codes   identical.".to_string(),
                    inferred: false,
                }],
                out_of_scope: vec![],
            },
            evidence_policy: EvidencePolicy {
                class: EvidenceClass::ChecksAndReview,
                build_command: Some("./compile.sh".to_string()),
                candidate_command: Some("./executable".to_string()),
                candidate_tests: true,
                differential: vec![DifferentialCase {
                    id: "D1".to_string(),
                    args: vec!["--help".to_string()],
                    stdin: None,
                }],
                reference_command: Some("/workspace/executable".to_string()),
            },
        }
    );
}

#[test]
fn a_none_draft_records_its_reason() {
    let draft = parse(
        &message(json!({
            "decision": "none",
            "reason": "a question, not work",
            "requirements": [],
            "out_of_scope": [],
            "differential_cases": [],
            "candidate_tests": false
        })),
        &input(),
    )
    .expect("draft");
    assert_eq!(
        draft,
        Draft::None {
            reason: "a question, not work".to_string()
        }
    );
}

#[test]
fn a_quote_that_is_not_in_the_intake_is_rejected() {
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{
                "id": "R1",
                "text": "Use the csv crate.",
                "source_quote": "use the csv crate",
                "inferred": false
            }],
            "out_of_scope": [],
            "differential_cases": [],
            "candidate_tests": false
        })),
        &input(),
    );
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}

#[test]
fn a_contract_without_requirements_is_rejected() {
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [],
            "out_of_scope": [],
            "differential_cases": [],
            "candidate_tests": false
        })),
        &input(),
    );
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}

#[test]
fn too_many_differential_cases_are_rejected() {
    let cases: Vec<Value> = (0..41)
        .map(|index| json!({"id": format!("D{index}"), "args": [], "stdin": null}))
        .collect();
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{"id": "R1", "text": "t", "source_quote": "Keep the exit codes identical.", "inferred": false}],
            "out_of_scope": [],
            "differential_cases": cases,
            "candidate_tests": false
        })),
        &input(),
    );
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}

#[test]
fn prose_around_the_json_is_rejected() {
    let result = parse("Here is the draft: {}", &input());
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}
