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
            terminal: None,
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
fn current_directory_prefixes_are_valid_fixture_paths() {
    let cases = validate_cases(
        raw(json!([{
            "id": "save-txt", "args": ["./contract-txt-out"],
            "dirs": ["./contract-txt-out"],
            "files": [{"path": "././/inputs/a.txt", "text": "hello", "repeat": 1}],
        }])),
        /*max*/ 1,
    )
    .expect("relative current-directory prefixes are contained");
    assert_eq!(
        cases,
        vec![DifferentialCase {
            id: "save-txt".to_string(),
            args: vec!["./contract-txt-out".to_string()],
            dirs: vec!["./contract-txt-out".to_string()],
            files: vec![FixtureFile {
                path: "././/inputs/a.txt".to_string(),
                text: "hello".to_string(),
                repeat: 1
            }],
            ..Default::default()
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
    for path in [
        "../escape",
        "/etc/passwd",
        "a/../../b",
        "",
        ".",
        "././",
        "./../escape",
        "./a/../../b",
        "././../escape",
    ] {
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
        json!([{"name": "has-dash", "value": "1"}]),
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
fn lowercase_environment_variables_are_allowed() {
    let cases = validate_cases(
        raw(json!([{"id": "proxy", "args": [], "env": [{"name": "http_proxy", "value": "http://127.0.0.1:9"}]}])),
        10,
    )
    .expect("valid");
    assert_eq!(cases[0].env["http_proxy"], "http://127.0.0.1:9");
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
        env: [("TERM_PROGRAM".into(), "iTerm.app".into())].into(),
        files: vec![FixtureFile {
            path: "input.dat".into(),
            text: "quoted \"data\"\n\u{0}尾".into(),
            repeat: 2,
        }],
        terminal: Some(crate::Terminal {
            rows: 31,
            cols: 97,
            input: "q\n".into(),
        }),
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

    let invocation = text
        .split_once("not defaults):\n")
        .unwrap()
        .1
        .split_once("\n[stdout]\n")
        .unwrap()
        .0;
    assert_eq!(
        serde_json::from_str::<Value>(invocation).unwrap(),
        json!(cases[0])
    );
    assert!(text.contains("out\n") && text.contains("warning\n"));
    assert!(text.contains("[exit status 2, no stable completed observation]"));
    assert!(render_observations(&cases, &observations, 20).len() <= 20);
}

#[test]
fn bounded_observations_keep_later_invocations_and_make_missing_bytes_explicit() {
    let cases: Vec<_> = (0..30)
        .map(|i| DifferentialCase {
            id: format!("case-{i}"),
            args: vec!["same-command".into()],
            stdin: Some(format!("different input {i}")),
            env: [("CASE".into(), i.to_string())].into(),
            ..Default::default()
        })
        .collect();
    let observations: Vec<_> = cases
        .iter()
        .map(|case| Observation {
            id: case.id.clone(),
            exit: Some(0),
            stable: true,
            stdout: "large output 尾\n".repeat(1000),
            stderr: String::new(),
        })
        .collect();
    let text = render_observations(&cases, &observations, 12_000);
    assert!(text.len() <= 12_000 && text.contains("bytes omitted"));
    for case in &cases {
        assert!(
            text.contains(&format!("Case {}\n", case.id)),
            "missing {}",
            case.id
        );
    }
    for cap in [0, 1, 20, 200, 4096] {
        assert!(render_observations(&cases, &observations, cap).len() <= cap);
    }
}
