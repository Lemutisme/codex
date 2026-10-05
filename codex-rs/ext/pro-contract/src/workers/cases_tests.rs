use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::RawCase;
use super::render_observations;
use super::validate_cases;
use crate::DifferentialCase;
use crate::FixtureFile;
use crate::Observation;
use crate::WorkerError;

fn raw(value: Value) -> Vec<RawCase> {
    serde_json::from_value(value).expect("raw cases")
}

fn malformed(value: Value) -> String {
    match validate_cases(raw(value), 10) {
        Err(WorkerError::Malformed(message)) => message,
        other => panic!("expected a malformed error, got {other:?}"),
    }
}

#[test]
fn a_full_case_becomes_a_differential_case() {
    let cases = validate_cases(
        raw(json!([{
            "id": "sizes.nested-1",
            "family": "directory sizes",
            "args": ["-s", "tree"],
            "stdin": null,
            "files": [{"path": "tree/a/big.bin", "text": "x", "repeat": 3000}],
            "dirs": ["tree/empty"],
            "env": [{"name": "NO_COLOR", "value": "1"}],
        }])),
        10,
    )
    .expect("valid");

    assert_eq!(
        cases,
        vec![DifferentialCase {
            id: "sizes.nested-1".to_string(),
            args: vec!["-s".to_string(), "tree".to_string()],
            stdin: None,
            files: vec![FixtureFile {
                path: "tree/a/big.bin".to_string(),
                text: "x".to_string(),
                repeat: 3000,
            }],
            dirs: vec!["tree/empty".to_string()],
            env: [("NO_COLOR".to_string(), "1".to_string())].into(),
            family: "directory sizes".to_string(),
        }]
    );
}

#[test]
fn optional_fields_default_to_empty() {
    let cases =
        validate_cases(raw(json!([{"id": "help", "args": ["--help"]}])), 10).expect("valid");
    assert_eq!(
        cases,
        vec![DifferentialCase {
            id: "help".to_string(),
            args: vec!["--help".to_string()],
            ..Default::default()
        }]
    );
}

#[test]
fn ids_must_be_plain_and_unique() {
    assert!(malformed(json!([{"id": "a b", "args": []}])).contains("plain token"));
    assert!(
        malformed(json!([{"id": "a", "args": []}, {"id": "a", "args": []}]))
            .contains("duplicate case id a")
    );
}

#[test]
fn fixtures_cannot_leave_the_case_directory() {
    for path in ["../escape", "/etc/passwd", "a/../../b", ""] {
        let message = malformed(json!([{
            "id": "c",
            "args": [],
            "files": [{"path": path, "text": "x", "repeat": 1}],
        }]));
        assert!(
            message.contains("leaves the case directory"),
            "{path}: {message}"
        );
    }
    let message = malformed(json!([{"id": "c", "args": [], "dirs": ["../up"]}]));
    assert!(message.contains("leaves the case directory"), "{message}");
}

#[test]
fn fixtures_are_bounded_after_repetition() {
    let message = malformed(json!([{
        "id": "c",
        "args": [],
        "files": [{"path": "big", "text": "0123456789", "repeat": 1_000_000}],
    }]));
    assert!(message.contains("fixtures are too large"), "{message}");
}

#[test]
fn environment_variables_are_named_plainly_and_hold_one_line() {
    for env in [
        json!([{"name": "lower", "value": "1"}]),
        json!([{"name": "9START", "value": "1"}]),
        json!([{"name": "OK", "value": "two\nlines"}]),
    ] {
        let message = malformed(json!([{"id": "c", "args": [], "env": env}]));
        assert!(
            message.contains("invalid environment variable"),
            "{message}"
        );
    }
    let message = malformed(json!([{
        "id": "c",
        "args": [],
        "env": [{"name": "A", "value": "1"}, {"name": "A", "value": "2"}],
    }]));
    assert!(message.contains("sets A twice"), "{message}");
}

#[test]
fn the_case_count_is_capped() {
    let many: Vec<Value> = (0..11)
        .map(|index| json!({"id": format!("c{index}"), "args": []}))
        .collect();
    assert!(malformed(Value::Array(many)).contains("exceed the limit of 10"));
}

#[test]
fn observations_show_the_invocation_fixtures_streams_and_stability() {
    let cases = vec![DifferentialCase {
        id: "a".to_string(),
        args: vec!["-s".to_string(), "two words".to_string()],
        stdin: Some("in".to_string()),
        dirs: vec!["tree".to_string()],
        ..Default::default()
    }];
    let observations = vec![Observation {
        id: "a".to_string(),
        exit: Some(2),
        stable: false,
        stdout: "out\n".to_string(),
        stderr: "warning\n".to_string(),
    }];

    let text = render_observations(&cases, &observations, 10_000);

    assert_eq!(
        text,
        "$ executable -s 'two words' < stdin\n[fixtures: tree]\nout\n[stderr]\nwarning\n[exit status 2, differs between two runs]\n\n"
    );
    assert!(render_observations(&cases, &observations, 20).len() < 60);
}
