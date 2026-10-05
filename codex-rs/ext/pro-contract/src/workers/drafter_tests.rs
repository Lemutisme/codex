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
use crate::FixtureFile;
use crate::ProcessConstraint;
use crate::Requirement;
use crate::Terms;
use crate::WorkerError;

const INTAKE: &str =
    "Implement the program so it behaves like the reference.\nKeep the exit codes identical.";

fn input() -> DraftInput<'static> {
    DraftInput {
        instructions: super::DEFAULT_INSTRUCTIONS,
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
            "process_constraints": [{
                "text": "Never rename the workspace.",
                "source_quote": "keep the exit codes identical"
            }],
            "differential_cases": [{
                "id": "D1",
                "family": "help",
                "args": ["--help"],
                "stdin": null,
                "files": [{"path": "in.txt", "text": "x", "repeat": 2}],
                "dirs": [],
                "env": [{"name": "NO_COLOR", "value": "1"}]
            }],
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
                    source_quote: "Keep the exit codes identical".to_string(),
                    inferred: false,
                }],
                out_of_scope: vec![],
                process_constraints: vec![ProcessConstraint {
                    text: "Never rename the workspace.".to_string(),
                    source_quote: "Keep the exit codes identical".to_string(),
                }],
            },
            evidence_policy: Box::new(EvidencePolicy {
                class: EvidenceClass::ChecksAndReview,
                build_command: Some("./compile.sh".to_string()),
                candidate_command: Some("./executable".to_string()),
                candidate_tests: true,
                differential: vec![DifferentialCase {
                    id: "D1".to_string(),
                    args: vec!["--help".to_string()],
                    stdin: None,
                    files: vec![FixtureFile {
                        path: "in.txt".to_string(),
                        text: "x".to_string(),
                        repeat: 2,
                    }],
                    dirs: vec![],
                    env: [("NO_COLOR".to_string(), "1".to_string())].into(),
                    family: "help".to_string(),
                }],
                reference_command: Some("/workspace/executable".to_string()),
                sealed: vec![],
                sealed_threshold_permille: 950,
                min_sealed_qualified: 100,
                min_success_permille: 500,
            }),
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
fn a_quote_with_slipped_punctuation_is_stored_as_the_verbatim_intake_span() {
    let draft = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{
                "id": "R1",
                "text": "Behave like the reference.",
                "source_quote": "implement the program, so it behaves like the reference.)",
                "inferred": false
            }],
            "out_of_scope": [{
                "element": "anything else",
                "human_statement": "keep the exit-codes identical",
                "non_substantive": false
            }],
            "differential_cases": [],
            "candidate_tests": false
        })),
        &input(),
    )
    .expect("draft");
    let Draft::Contract { terms, .. } = draft else {
        panic!("expected a contract");
    };
    assert_eq!(
        terms.requirements[0].source_quote,
        "Implement the program so it behaves like the reference"
    );
    assert_eq!(
        terms.out_of_scope[0].human_statement.as_deref(),
        Some("Keep the exit codes identical")
    );
}

#[test]
fn a_quote_made_only_of_punctuation_is_rejected() {
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{"id": "R1", "text": "t", "source_quote": ".", "inferred": false}],
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

#[test]
fn a_case_id_that_is_not_a_plain_token_is_rejected() {
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{"id": "R1", "text": "t", "source_quote": "Keep the exit codes identical.", "inferred": false}],
            "out_of_scope": [],
            "differential_cases": [{"id": "../x; rm", "args": [], "stdin": null}],
            "candidate_tests": false
        })),
        &input(),
    );
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}

#[test]
fn a_process_constraint_must_quote_the_request() {
    let result = parse(
        &message(json!({
            "decision": "contract",
            "reason": "r",
            "requirements": [{"id": "R1", "text": "t", "source_quote": "Keep the exit codes identical.", "inferred": false}],
            "out_of_scope": [],
            "process_constraints": [{"text": "Never look at the reference.", "source_quote": "never look"}],
            "differential_cases": [],
            "candidate_tests": false
        })),
        &input(),
    );
    assert!(matches!(result, Err(WorkerError::Malformed(_))));
}

#[test]
fn the_instructions_route_process_constraints_away_from_out_of_scope() {
    let prompt = prompt(&input());
    assert!(prompt.contains("process_constraints"), "{prompt}");
    assert!(prompt.contains("never belong in out_of_scope"), "{prompt}");
    assert!(
        prompt.contains("fresh copy of the base workspace"),
        "{prompt}"
    );
}
