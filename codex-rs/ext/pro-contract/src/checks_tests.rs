use pretty_assertions::assert_eq;

use super::StepOutcome;
use super::StepReceipt;
use super::expected_steps;
use super::parse_output;
use super::pipeline_script;
use super::shell_quote;
use crate::CheckEnvironment;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;

fn policy() -> EvidencePolicy {
    EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: true,
        differential: vec![
            DifferentialCase {
                id: "D1".to_string(),
                args: vec!["hello world".to_string(), "it's".to_string()],
                stdin: None,
            },
            DifferentialCase {
                id: "D2".to_string(),
                args: vec![],
                stdin: Some("a,b\n1,2\n".to_string()),
            },
        ],
        reference_command: Some("/workspace/executable".to_string()),
    }
}

#[test]
fn shell_quote_survives_spaces_and_single_quotes() {
    assert_eq!(shell_quote("plain"), "'plain'");
    assert_eq!(shell_quote("it's here"), "'it'\\''s here'");
    assert_eq!(shell_quote(""), "''");
}

#[test]
fn the_script_is_deterministic_and_quotes_every_argument() {
    let script = pipeline_script(&policy(), "/candidate");
    assert_eq!(script, pipeline_script(&policy(), "/candidate"));
    assert!(script.contains("'hello world' 'it'\\''s'"), "{script}");
    assert!(script.contains("cd '/candidate'"), "{script}");
    assert!(
        !script.contains("a,b"),
        "stdin must be encoded, not inlined"
    );
}

#[test]
fn expected_steps_follow_the_policy_order() {
    assert_eq!(
        expected_steps(&policy()),
        vec![
            "build".to_string(),
            "candidate_tests".to_string(),
            "differential:D1".to_string(),
            "differential:D2".to_string()
        ]
    );
}

#[test]
fn without_a_reference_there_are_no_differential_steps() {
    let policy = EvidencePolicy {
        reference_command: None,
        differential: vec![],
        ..policy()
    };
    assert_eq!(
        expected_steps(&policy),
        vec!["build".to_string(), "candidate_tests".to_string()]
    );
}

#[test]
fn output_lines_become_receipts_with_their_logs() {
    let stdout = "@@ENV rustc 1.92.0\n@@PC build pass\n@@LOG candidate_tests error[E0425]\n@@PC candidate_tests fail\n@@PC differential:D1 pass\n@@LOG differential:D2 -expected\n@@PC differential:D2 fail\nnoise\n";
    let (steps, environment, complete) = parse_output(stdout, &policy());
    assert_eq!(
        (steps, environment, complete),
        (
            vec![
                StepReceipt {
                    step: "build".to_string(),
                    outcome: StepOutcome::Pass,
                    detail: String::new(),
                },
                StepReceipt {
                    step: "candidate_tests".to_string(),
                    outcome: StepOutcome::Fail,
                    detail: "error[E0425]\n".to_string(),
                },
                StepReceipt {
                    step: "differential:D1".to_string(),
                    outcome: StepOutcome::Pass,
                    detail: String::new(),
                },
                StepReceipt {
                    step: "differential:D2".to_string(),
                    outcome: StepOutcome::Fail,
                    detail: "-expected\n".to_string(),
                },
            ],
            vec!["rustc 1.92.0".to_string()],
            true
        )
    );
}

#[test]
fn a_pipeline_that_stops_early_is_incomplete() {
    let (steps, _, complete) = parse_output("@@PC build pass\n", &policy());
    assert_eq!((steps.len(), complete), (1, false));
}

/// Runs only when `PRO_CONTRACT_TEST_IMAGE` names a local image with `bash`, `base64` and
/// `timeout`; uses `/bin/echo` as the reference program.
#[tokio::test]
async fn a_real_container_run_passes_and_fails_the_right_cases() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dir = tempfile::tempdir().expect("tempdir");
    std::fs::write(
        dir.path().join("compile.sh"),
        "#!/bin/sh\nprintf '#!/bin/sh\\necho \"$@\"\\n' > executable\nchmod +x executable\n",
    )
    .expect("compile.sh");
    let status = std::process::Command::new("chmod")
        .args(["-R", "a+rwX"])
        .arg(dir.path())
        .status()
        .expect("chmod");
    assert!(status.success());
    std::fs::set_permissions(
        dir.path().join("compile.sh"),
        std::os::unix::fs::PermissionsExt::from_mode(0o777),
    )
    .expect("chmod compile.sh");
    let policy = EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: false,
        differential: vec![
            DifferentialCase {
                id: "same".to_string(),
                args: vec!["hello".to_string()],
                stdin: None,
            },
            DifferentialCase {
                id: "differs".to_string(),
                args: vec!["--version".to_string()],
                stdin: None,
            },
        ],
        reference_command: Some("/bin/echo".to_string()),
    };
    let env = CheckEnvironment {
        docker: "docker".to_string(),
        image,
        user: "1000:1000".to_string(),
        candidate_mount: "/candidate".to_string(),
        timeout_secs: 120,
        build_command: None,
        candidate_command: None,
    };
    let receipts = super::run(&env, dir.path(), &policy).await.expect("run");
    let outcomes: Vec<(String, StepOutcome)> = receipts
        .steps
        .iter()
        .map(|step| (step.step.clone(), step.outcome))
        .collect();
    assert_eq!(
        outcomes,
        vec![
            ("build".to_string(), StepOutcome::Pass),
            ("differential:same".to_string(), StepOutcome::Pass),
            ("differential:differs".to_string(), StepOutcome::Fail),
        ]
    );
    assert!(receipts.complete);
}

#[tokio::test]
async fn a_reference_probe_reports_bounded_output_and_exit_status() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let env = CheckEnvironment {
        docker: "docker".to_string(),
        image,
        user: "1000:1000".to_string(),
        candidate_mount: "/candidate".to_string(),
        timeout_secs: 120,
        build_command: None,
        candidate_command: None,
    };

    let output = super::probe_reference(
        &env,
        "/bin/sh",
        &[
            "-c".to_string(),
            "yes probe | head -c 20000; exit 3".to_string(),
        ],
    )
    .await
    .expect("probe");

    assert!(output.starts_with("probe\nprobe\n"), "{output}");
    assert!(output.len() < 8100, "{} bytes", output.len());
    assert!(output.trim_end().ends_with("[exit status 3]"), "{output}");
}
