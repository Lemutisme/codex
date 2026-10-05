use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::Coverage;
use super::MAX_EXPLORATION_CASES;
use super::ProbeInput;
use super::explore_prompt;
use super::explore_schema;
use super::parse_exploration;
use super::parse_probe;
use super::write_prompt;
use super::write_schema;
use crate::WorkerError;

fn input() -> ProbeInput<'static> {
    ProbeInput {
        intake_text: "Implement this program from scratch so that it behaves exactly like the reference.",
        base_view: "=== README.md ===\n# dutree\nUsage: dutree [options] <path>\n",
        reference_help: "$ executable --help\nUsage: dutree [options] <path>\n[exit status 0]\n",
    }
}

fn assert_strict(value: &Value) {
    if let Some(object) = value.as_object() {
        if object.get("type") == Some(&json!("object")) {
            let mut required: Vec<&str> = object["required"]
                .as_array()
                .expect("required")
                .iter()
                .filter_map(Value::as_str)
                .collect();
            let mut properties: Vec<&str> = object["properties"]
                .as_object()
                .expect("properties")
                .keys()
                .map(String::as_str)
                .collect();
            required.sort_unstable();
            properties.sort_unstable();
            assert_eq!(required, properties);
            assert_eq!(object["additionalProperties"], json!(false));
        }
        object.values().for_each(assert_strict);
    } else if let Some(items) = value.as_array() {
        items.iter().for_each(assert_strict);
    }
}

#[test]
fn both_schemas_are_strict() {
    assert_strict(&explore_schema());
    assert_strict(&write_schema());
}

#[test]
fn the_prompts_carry_the_request_the_documentation_and_the_help() {
    for prompt in [
        explore_prompt(&input()),
        write_prompt(&input(), "$ executable -s .\n[exit status 0]\n"),
    ] {
        assert!(prompt.contains(input().intake_text), "{prompt}");
        assert!(prompt.contains("# dutree"), "{prompt}");
        assert!(prompt.contains("Usage: dutree"), "{prompt}");
        assert!(prompt.contains("never see that implementation"), "{prompt}");
    }
    assert!(explore_prompt(&input()).contains("Turn 1 of 2"));
    let write = write_prompt(&input(), "$ executable -s .\n[exit status 0]\n");
    assert!(write.contains("Turn 2 of 2"), "{write}");
    assert!(
        write.contains("<reference_observations>\n$ executable -s ."),
        "{write}"
    );
}

#[test]
fn the_prompts_stay_bounded() {
    let huge = "y".repeat(1_000_000);
    let input = ProbeInput {
        intake_text: &huge,
        base_view: &huge,
        reference_help: &huge,
    };
    let prompt = write_prompt(&input, &huge);
    assert!(prompt.len() < 200_000, "prompt is {} bytes", prompt.len());
}

#[test]
fn exploration_is_capped() {
    let cases: Vec<Value> = (0..=MAX_EXPLORATION_CASES)
        .map(|index| json!({"id": format!("e{index}"), "args": ["--help"]}))
        .collect();
    let message = json!({"cases": cases}).to_string();
    assert!(matches!(
        parse_exploration(&message),
        Err(WorkerError::Malformed(_))
    ));
    let message = json!({"cases": [{"id": "e1", "args": ["help", "sub"]}]}).to_string();
    assert_eq!(parse_exploration(&message).expect("valid").len(), 1);
}

#[test]
fn a_probe_returns_its_plan_and_cases() {
    let message = json!({
        "coverage_plan": [{"family": "sizes", "surface": "-s", "description": "summary sizes"}],
        "cases": [{"id": "s1", "family": "sizes", "args": ["-s", "tree"], "dirs": ["tree"]}],
    })
    .to_string();
    let probe = parse_probe(&message).expect("valid");
    assert_eq!(
        probe.coverage_plan,
        vec![Coverage {
            family: "sizes".to_string(),
            surface: "-s".to_string(),
            description: "summary sizes".to_string(),
        }]
    );
    assert_eq!(probe.cases[0].dirs, vec!["tree".to_string()]);
}

#[test]
fn a_malformed_probe_is_rejected() {
    assert!(matches!(
        parse_probe("here are the cases"),
        Err(WorkerError::Malformed(_))
    ));
    let escaping = json!({
        "coverage_plan": [],
        "cases": [{"id": "x", "args": [], "files": [{"path": "../x", "text": "", "repeat": 1}]}],
    })
    .to_string();
    assert!(matches!(
        parse_probe(&escaping),
        Err(WorkerError::Malformed(_))
    ));
}

#[test]
fn the_policy_digest_is_the_probers_own() {
    assert_eq!(super::policy_digest(), super::policy_digest());
    assert_ne!(
        super::policy_digest(),
        crate::workers::drafter::policy_digest()
    );
}
