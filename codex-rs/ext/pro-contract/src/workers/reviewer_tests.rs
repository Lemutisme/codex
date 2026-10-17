use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::Coverage;
use super::Finding;
use super::ReviewVerdict;
use super::TermsGap;
use super::parse;
use super::schema;
use crate::Requirement;
use crate::Terms;
use crate::WorkerError;

fn terms() -> Terms {
    Terms {
        intake_text: "Implement the tool. Keep exit codes identical.".to_string(),
        requirements: vec![
            Requirement {
                id: "R1".to_string(),
                text: "Behaves like the reference.".to_string(),
                source_quote: "Implement the tool.".to_string(),
                inferred: false,
            },
            Requirement {
                id: "R2".to_string(),
                text: "Exit codes match.".to_string(),
                source_quote: "Keep exit codes identical.".to_string(),
                inferred: false,
            },
        ],
        out_of_scope: vec![],
        process_constraints: vec![],
    }
}

#[test]
fn process_obligations_have_legal_ids_and_missing_process_evidence_stays_partial() {
    let mut terms = terms();
    terms.process_constraints.push(crate::ProcessConstraint {
        text: "Read the retained feedback".into(),
        source_quote: "Read the retained feedback".into(),
    });
    let schema = super::schema_for(&terms);
    assert_eq!(
        schema["properties"]["gaps"]["items"]["properties"]["requirement_id"]["enum"],
        json!(["R1", "R2", "process:0"])
    );
    let mut value = review("support");
    value["coverage"] =
        json!([{"requirement_id":"R1","evidence":"e1"},{"requirement_id":"R2","evidence":"e2"}]);
    let parsed = parse(&message(value.clone()), &terms).unwrap();
    let ReviewVerdict::Partial {
        coverage, missing, ..
    } = parsed.verdict
    else {
        panic!("missing process obligation was waived");
    };
    assert_eq!(coverage.len(), 2);
    assert_eq!(missing[0].requirement_id, "process:0");
    value["gaps"] = json!([{"requirement_id":"invented-process","reason":"not observed"}]);
    assert!(parse(&message(value.clone()), &terms).is_err());
    value["gaps"] = json!([{"requirement_id":"process:0","reason":"not observed"}]);
    assert!(parse(&message(value), &terms).is_ok());
}

#[test]
fn an_execution_finding_cannot_become_an_artifact_repair_instruction() {
    let mut terms = terms();
    terms.process_constraints.push(crate::ProcessConstraint {
        text: "Publish before editing".into(),
        source_quote: "Publish before editing".into(),
    });
    let mut value = review("defeat");
    value["findings"] = json!([
        {"requirement_id":"process:0","location":"history","counterexample":"edited before initial publication"},
        {"requirement_id":"R1","location":"artifact","counterexample":"wrong output"}
    ]);
    let parsed = parse(&message(value), &terms).unwrap();
    assert_eq!(parsed.actionable_findings().len(), 1);
    assert_eq!(parsed.actionable_findings()[0].requirement_id, "R1");
    assert_eq!(parsed.execution_findings()[0].requirement_id, "process:0");
}

fn message(value: Value) -> String {
    serde_json::to_string(&value).expect("json")
}

fn review(verdict: &str) -> Value {
    json!({
        "verdict": verdict,
        "coverage": [],
        "findings": [],
        "terms_gap": [],
        "missing": "",
        "residual": ""
    })
}

#[test]
fn the_schema_is_strict() {
    fn assert_strict(value: &Value) {
        if let Some(object) = value.as_object() {
            if object.get("type") == Some(&json!("object")) {
                let mut required: Vec<&str> = object["required"]
                    .as_array()
                    .expect("required")
                    .iter()
                    .map(|value| value.as_str().expect("name"))
                    .collect();
                required.sort_unstable();
                let mut names: Vec<&str> = object["properties"]
                    .as_object()
                    .expect("properties")
                    .keys()
                    .map(String::as_str)
                    .collect();
                names.sort_unstable();
                assert_eq!(required, names);
                assert_eq!(object["additionalProperties"], json!(false));
            }
            object.values().for_each(assert_strict);
        } else if let Some(items) = value.as_array() {
            items.iter().for_each(assert_strict);
        }
    }
    assert_strict(&schema());
}

#[test]
fn support_requires_coverage_of_every_requirement() {
    let mut value = review("support");
    value["coverage"] = json!([{"requirement_id": "R1", "evidence": "differential D1 passed"}]);
    let ReviewVerdict::Partial {
        coverage, missing, ..
    } = parse(&message(value), &terms()).unwrap().verdict
    else {
        panic!("partial judgment lost")
    };
    assert_eq!(coverage[0].requirement_id, "R1");
    assert_eq!(missing[0].requirement_id, "R2");
}

#[test]
fn partial_judgments_retain_findings_and_scope_gaps_and_reject_contradictions() {
    let mut value = review("partial");
    value["findings"] = json!([{"requirement_id":"R1","location":"lemma 2","counterexample":"fails at dimension two"}]);
    value["gaps"] = json!([{"requirement_id":"R2","reason":"binary data not yet inspected"}]);
    let parsed = parse(&message(value.clone()), &terms()).unwrap();
    assert_eq!(parsed.actionable_findings().len(), 1);
    assert!(
        matches!(parsed.verdict, ReviewVerdict::Partial { ref missing, .. } if missing.len()==1)
    );
    value["coverage"] = json!([{"requirement_id":"R1","evidence":"e1"}]);
    assert!(parse(&message(value), &terms()).is_err());
}

#[test]
fn a_complete_support_is_accepted() {
    let mut value = review("support");
    value["coverage"] = json!([
        {"requirement_id": "R1", "evidence": "D1 passed"},
        {"requirement_id": "R2", "evidence": "D2 passed"}
    ]);
    assert_eq!(
        parse(&message(value), &terms()).expect("verdict").verdict,
        ReviewVerdict::Support {
            coverage: vec![
                Coverage {
                    requirement_id: "R1".to_string(),
                    evidence: "D1 passed".to_string()
                },
                Coverage {
                    requirement_id: "R2".to_string(),
                    evidence: "D2 passed".to_string()
                },
            ]
        }
    );
}

#[test]
fn a_terms_gap_is_kept_beside_the_verdict() {
    let mut value = review("support");
    value["coverage"] = json!([
        {"requirement_id": "R1", "evidence": "e"},
        {"requirement_id": "R2", "evidence": "e"}
    ]);
    value["terms_gap"] =
        json!([{"element": "error messages", "reason": "requested but not a requirement"}]);
    let review = parse(&message(value), &terms()).expect("verdict");
    assert!(
        matches!(review.verdict, ReviewVerdict::Support { .. }),
        "{review:?}"
    );
    assert_eq!(
        review.terms_gap,
        vec![TermsGap {
            affected_requirements: None,
            element: "error messages".to_string(),
            reason: "requested but not a requirement".to_string()
        }]
    );
}

#[test]
fn scoped_terms_gaps_validate_ids_and_leave_only_unaffected_findings_actionable() {
    let mut value = review("defeat");
    value["findings"] = json!([
        {"requirement_id":"R1","location":"a","counterexample":"real mismatch"},
        {"requirement_id":"R2","location":"b","counterexample":"disputed demand"}
    ]);
    value["terms_gap"] = json!([{"element":"widened scope","reason":"not requested","affected_requirements":["R2"]}]);
    let parsed = parse(&message(value.clone()), &terms()).unwrap();
    assert_eq!(
        parsed
            .actionable_findings()
            .iter()
            .map(|f| f.requirement_id.as_str())
            .collect::<Vec<_>>(),
        vec!["R1"]
    );
    value["terms_gap"][0]["affected_requirements"] = json!(["R9"]);
    assert!(matches!(
        parse(&message(value), &terms()),
        Err(WorkerError::Malformed(_))
    ));
}

#[test]
fn a_defeat_needs_findings_on_known_requirements() {
    let mut value = review("defeat");
    value["residual"] = json!("fix it");
    assert!(matches!(
        parse(&message(value.clone()), &terms()),
        Err(WorkerError::Malformed(_))
    ));
    value["findings"] = json!([{"requirement_id": "R9", "location": "x", "counterexample": "y"}]);
    assert!(matches!(
        parse(&message(value.clone()), &terms()),
        Err(WorkerError::Malformed(_))
    ));
    value["findings"] =
        json!([{"requirement_id": "R2", "location": "main.rs", "counterexample": "exit 1 vs 2"}]);
    assert_eq!(
        parse(&message(value), &terms()).expect("verdict").verdict,
        ReviewVerdict::Defeat {
            findings: vec![Finding {
                requirement_id: "R2".to_string(),
                location: "main.rs".to_string(),
                counterexample: "exit 1 vs 2".to_string()
            }],
            residual: "fix it".to_string()
        }
    );
}

#[test]
fn cannot_judge_must_say_what_is_missing() {
    let value = review("cannot_judge");
    assert!(matches!(
        parse(&message(value), &terms()),
        Err(WorkerError::Malformed(_))
    ));
}

#[test]
fn an_unknown_verdict_is_malformed() {
    assert!(matches!(
        parse(&message(review("approve")), &terms()),
        Err(WorkerError::Malformed(_))
    ));
}

#[test]
fn the_policy_digest_covers_the_evidence_protocol() {
    let without_view =
        crate::digest_of("reviewer_policy", &(super::DEFAULT_INSTRUCTIONS, schema()));
    assert_ne!(
        super::policy_digest(super::DEFAULT_INSTRUCTIONS),
        without_view
    );
}
