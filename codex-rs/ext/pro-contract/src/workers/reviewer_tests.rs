use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::Coverage;
use super::Finding;
use super::ReviewInput;
use super::ReviewVerdict;
use super::TermsGap;
use super::parse;
use super::prompt;
use super::schema;
use crate::OutOfScope;
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
    }
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
fn the_prompt_carries_intake_and_requirements_and_stays_bounded() {
    let terms = terms();
    let huge = "y".repeat(super::CANDIDATE_VIEW.cap * 2);
    let text = prompt(&ReviewInput {
        terms: &terms,
        check_summary: "build: pass",
        candidate_view: &huge,
    });
    assert!(text.contains("Implement the tool. Keep exit codes identical."));
    assert!(text.contains("R2"));
    assert!(text.contains("build: pass"));
    assert!(
        text.len() < super::CANDIDATE_VIEW.cap + super::super::PROMPT_EVIDENCE_CAP,
        "prompt is {} bytes",
        text.len()
    );
}

#[test]
fn support_requires_coverage_of_every_requirement() {
    let mut value = review("support");
    value["coverage"] = json!([{"requirement_id": "R1", "evidence": "differential D1 passed"}]);
    assert_eq!(
        parse(&message(value), &terms()).expect("verdict"),
        ReviewVerdict::CannotJudge {
            missing: "no coverage for requirement R2".to_string()
        }
    );
}

#[test]
fn a_complete_support_is_accepted() {
    let mut value = review("support");
    value["coverage"] = json!([
        {"requirement_id": "R1", "evidence": "D1 passed"},
        {"requirement_id": "R2", "evidence": "D2 passed"}
    ]);
    assert_eq!(
        parse(&message(value), &terms()).expect("verdict"),
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
fn a_terms_gap_overrides_support() {
    let mut value = review("support");
    value["coverage"] = json!([
        {"requirement_id": "R1", "evidence": "e"},
        {"requirement_id": "R2", "evidence": "e"}
    ]);
    value["terms_gap"] =
        json!([{"element": "error messages", "reason": "requested but not a requirement"}]);
    assert_eq!(
        parse(&message(value), &terms()).expect("verdict"),
        ReviewVerdict::TermsGap {
            gaps: vec![TermsGap {
                element: "error messages".to_string(),
                reason: "requested but not a requirement".to_string()
            }]
        }
    );
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
        parse(&message(value), &terms()).expect("verdict"),
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
fn the_prompt_respects_the_evidence_caps_and_says_what_to_do_about_omissions() {
    let huge = "x".repeat(super::super::PROMPT_EVIDENCE_CAP * 2);
    let huge_view = "v".repeat(super::CANDIDATE_VIEW.cap * 2);
    let terms = Terms {
        intake_text: huge.clone(),
        requirements: vec![Requirement {
            id: "R1".to_string(),
            text: huge.clone(),
            source_quote: "q".to_string(),
            inferred: false,
        }],
        out_of_scope: vec![OutOfScope {
            element: huge.clone(),
            human_statement: None,
            non_substantive: true,
        }],
    };
    let input = ReviewInput {
        terms: &terms,
        check_summary: &huge,
        candidate_view: &huge_view,
    };

    let prompt = prompt(&input);

    // The fixed part (instructions, tags, separators) is what an all-empty prompt weighs.
    let empty_terms = Terms {
        intake_text: String::new(),
        requirements: vec![],
        out_of_scope: vec![],
    };
    let fixed = super::prompt(&ReviewInput {
        terms: &empty_terms,
        check_summary: "",
        candidate_view: "",
    })
    .len();
    let evidence = prompt.len() - fixed;
    let omission_notes = 5 * 64;
    // Terms and receipts share the evidence cap; the candidate view has its own.
    assert!(
        evidence <= super::super::PROMPT_EVIDENCE_CAP + super::CANDIDATE_VIEW.cap + omission_notes,
        "evidence is {evidence} bytes"
    );
    assert!(
        prompt.contains("answer cannot_judge and name the omitted files in missing"),
        "the instructions must say what to do when file contents are omitted"
    );
}

#[test]
fn a_candidate_view_of_several_hundred_kilobytes_reaches_the_reviewer_intact() {
    let terms = terms();
    let view = format!("{}END-OF-VIEW", "fn f() {}\n".repeat(30_000));
    let text = prompt(&ReviewInput {
        terms: &terms,
        check_summary: "build: pass",
        candidate_view: &view,
    });
    assert!(text.contains(&view), "the view was cut");
}

#[test]
fn the_policy_digest_covers_the_candidate_view_policy() {
    let without_view = crate::digest_of("reviewer_policy", &(super::INSTRUCTIONS, schema()));
    assert_ne!(super::policy_digest(), without_view);
}
