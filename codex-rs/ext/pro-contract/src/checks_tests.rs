use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::Observation;
use super::StepOutcome;
use super::StepReceipt;
use super::expected_steps;
use super::parse_observations;
use super::parse_output;
use super::pipeline_script;
use super::shell_quote;
use super::write_case_inputs;
use crate::CheckEnvironment;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::FixtureFile;

fn case(id: &str, args: &[&str]) -> DifferentialCase {
    DifferentialCase {
        id: id.to_string(),
        args: args.iter().map(ToString::to_string).collect(),
        ..Default::default()
    }
}

fn policy() -> EvidencePolicy {
    EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: true,
        differential: vec![
            case("D1", &["hello world", "it's"]),
            DifferentialCase {
                stdin: Some("a,b\n1,2\n".to_string()),
                ..case("D2", &[])
            },
        ],
        reference_command: Some("/workspace/executable".to_string()),
        sealed: vec![case("S1", &["-s", "tree"])],
        sealed_threshold_permille: 950,
        min_sealed_qualified: 100,
        min_success_permille: 500,
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
    let script = pipeline_script(&policy(), "/candidate", 300);
    assert_eq!(script, pipeline_script(&policy(), "/candidate", 300));
    assert!(
        script.contains("run_case 'public:D1' /pc/cases/0 /tmp/pc-diff/0 'hello world' 'it'\\''s'"),
        "{script}"
    );
    assert!(
        script.contains("run_case 'sealed:S1' /pc/cases/2 /tmp/pc-diff/2 '-s' 'tree'"),
        "{script}"
    );
    // The mounted subject is only read; building happens in a private copy.
    assert!(
        script.contains("cp -R '/candidate'/. /tmp/pc-work/"),
        "{script}"
    );
    assert!(
        script.contains("CANDIDATE='/tmp/pc-work/executable'"),
        "{script}"
    );
    assert!(
        script.contains("REFERENCE='/workspace/executable'"),
        "{script}"
    );
    assert!(
        !script.contains("a,b"),
        "stdin is a case input file, not part of the script"
    );
}

#[test]
fn expected_steps_follow_the_policy_order_public_before_sealed() {
    assert_eq!(
        expected_steps(&policy()),
        vec![
            "build".to_string(),
            "candidate_tests".to_string(),
            "public:D1".to_string(),
            "public:D2".to_string(),
            "sealed:S1".to_string(),
        ]
    );
}

#[test]
fn without_a_reference_there_are_no_case_steps() {
    let policy = EvidencePolicy {
        reference_command: None,
        differential: vec![],
        ..policy()
    };
    assert_eq!(
        expected_steps(&policy),
        vec!["build".to_string(), "candidate_tests".to_string()]
    );
    assert!(!pipeline_script(&policy, "/candidate", 300).contains("run_case"));
}

#[test]
fn output_lines_become_receipts_with_channels_exits_and_logs() {
    let stdout = "@@ENV rustc 1.92.0\n@@PC build pass\n@@LOG candidate_tests error[E0425]\n@@PC candidate_tests fail\n@@PC public:D1 pass rc,out,err,files 0\n@@LOG public:D2 differing channels: err\n@@PC public:D2 fail rc,err 2\n@@PC sealed:S1 unqualified - 1\nnoise\n";
    let (steps, environment, complete) = parse_output(stdout, &policy());
    assert_eq!(
        (steps, environment, complete),
        (
            vec![
                StepReceipt::new("build", StepOutcome::Pass, ""),
                StepReceipt::new("candidate_tests", StepOutcome::Fail, "error[E0425]\n"),
                StepReceipt {
                    stable: vec![
                        "rc".to_string(),
                        "out".to_string(),
                        "err".to_string(),
                        "files".to_string()
                    ],
                    reference_exit: Some(0),
                    ..StepReceipt::new("public:D1", StepOutcome::Pass, "")
                },
                StepReceipt {
                    stable: vec!["rc".to_string(), "err".to_string()],
                    reference_exit: Some(2),
                    ..StepReceipt::new("public:D2", StepOutcome::Fail, "differing channels: err\n")
                },
                StepReceipt {
                    reference_exit: Some(1),
                    ..StepReceipt::new("sealed:S1", StepOutcome::Unqualified, "")
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

#[test]
fn observations_collect_each_cases_streams() {
    let stdout = "@@OUT help Usage: tool\n@@OUT help   -s summary\n@@ERR help note\n@@OBS help 0 stable\n@@OBS quiet 2 unstable\n";
    assert_eq!(
        parse_observations(stdout),
        vec![
            Observation {
                id: "help".to_string(),
                exit: Some(0),
                stable: true,
                stdout: "Usage: tool\n  -s summary\n".to_string(),
                stderr: "note\n".to_string(),
            },
            Observation {
                id: "quiet".to_string(),
                exit: Some(2),
                stable: false,
                stdout: String::new(),
                stderr: String::new(),
            },
        ]
    );
}

#[test]
fn case_inputs_are_written_inside_their_directory() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let inputs = DifferentialCase {
        stdin: Some("input".to_string()),
        files: vec![FixtureFile {
            path: "tree/a.txt".to_string(),
            text: "ab".to_string(),
            repeat: 3,
        }],
        dirs: vec!["tree/empty".to_string()],
        env: [("NO_COLOR".to_string(), "1".to_string())].into(),
        ..case("c", &[])
    };
    write_case_inputs(dir.path(), &inputs)?;
    assert_eq!(std::fs::read_to_string(dir.path().join("stdin"))?, "input");
    assert_eq!(
        std::fs::read_to_string(dir.path().join("env"))?,
        "NO_COLOR=1\n"
    );
    assert_eq!(
        std::fs::read_to_string(dir.path().join("fixture/tree/a.txt"))?,
        "ababab"
    );
    assert!(dir.path().join("fixture/tree/empty").is_dir());

    let escaping = DifferentialCase {
        dirs: vec!["../outside".to_string()],
        ..case("e", &[])
    };
    assert!(write_case_inputs(&dir.path().join("e"), &escaping).is_err());
    assert!(!dir.path().join("outside").exists());
    Ok(())
}

fn test_env(image: String, timeout_secs: u64) -> CheckEnvironment {
    CheckEnvironment {
        docker: "docker".to_string(),
        image,
        user: "1000:1000".to_string(),
        candidate_mount: "/candidate".to_string(),
        timeout_secs,
        build_command: None,
        candidate_command: None,
    }
}

fn write_executable(path: &std::path::Path, text: &str) -> std::io::Result<()> {
    std::fs::write(path, text)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
}

/// A reference program for the container tests, kept in the base workspace. `flaky` exits 0
/// then 1 across calls in one container, so its exit status is unstable.
const REFERENCE: &str = r#"#!/bin/sh
case "$1" in
  cat) cat "$2" ;;
  err) echo "bad value" >&2; exit 3 ;;
  time) date +%s%N ;;
  flaky) if [ -f /tmp/flaky ]; then rm /tmp/flaky; exit 1; else touch /tmp/flaky; exit 0; fi ;;
  write) echo hi > made.txt ;;
  env) echo "$GREETING" ;;
  slow) echo done ;;
  *) echo "$@" ;;
esac
"#;

/// The candidate agrees except on stderr for `err`, the written file for `write`, and hangs on
/// `slow`.
const CANDIDATE: &str = r#"#!/bin/sh
case "$1" in
  cat) cat "$2" ;;
  err) echo "different" >&2; exit 3 ;;
  time) echo 0 ;;
  flaky) exit 0 ;;
  write) echo ho > made.txt ;;
  env) echo "$GREETING" ;;
  slow) sleep 30 ;;
  *) echo "$@" ;;
esac
"#;

/// Runs only when `PRO_CONTRACT_TEST_IMAGE` names a local image with `bash`, coreutils, `diff`,
/// `sha256sum` and `timeout`.
#[tokio::test]
async fn a_real_container_run_judges_every_channel() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dirs = tempfile::tempdir().expect("tempdir");
    let base = dirs.path().join("base");
    let candidate = dirs.path().join("candidate");
    std::fs::create_dir_all(&base).expect("base");
    std::fs::create_dir_all(&candidate).expect("candidate");
    std::fs::write(base.join("README.md"), "# tool\n").expect("readme");
    write_executable(&base.join("reference.sh"), REFERENCE).expect("reference");
    write_executable(
        &candidate.join("compile.sh"),
        &format!("#!/bin/sh\ncat > executable <<'EOF'\n{CANDIDATE}EOF\nchmod +x executable\n"),
    )
    .expect("compile.sh");
    let policy = EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: false,
        differential: vec![case("readme", &["cat", "README.md"]), case("err", &["err"])],
        reference_command: Some("/pc-base/reference.sh".to_string()),
        sealed: vec![
            DifferentialCase {
                files: vec![FixtureFile {
                    path: "in/data.txt".to_string(),
                    text: "xy".to_string(),
                    repeat: 4,
                }],
                ..case("fixture", &["cat", "in/data.txt"])
            },
            case("time", &["time"]),
            case("flaky", &["flaky"]),
            case("write", &["write"]),
            DifferentialCase {
                env: [("GREETING".to_string(), "hello there".to_string())].into(),
                ..case("env", &["env"])
            },
            case("slow", &["slow"]),
        ],
        sealed_threshold_permille: 950,
        min_sealed_qualified: 1,
        min_success_permille: 0,
    };

    let receipts = super::run(&test_env(image, 300), &candidate, &base, &policy)
        .await
        .expect("run");

    let outcomes: Vec<(String, StepOutcome, Vec<String>)> = receipts
        .steps
        .iter()
        .map(|step| (step.step.clone(), step.outcome, step.stable.clone()))
        .collect();
    let all = |channels: &[&str]| channels.iter().map(ToString::to_string).collect::<Vec<_>>();
    assert_eq!(
        outcomes,
        vec![
            ("build".to_string(), StepOutcome::Pass, vec![]),
            (
                "public:readme".to_string(),
                StepOutcome::Pass,
                all(&["rc", "out", "err", "files"])
            ),
            (
                "public:err".to_string(),
                StepOutcome::Fail,
                all(&["rc", "out", "err", "files"])
            ),
            (
                "sealed:fixture".to_string(),
                StepOutcome::Pass,
                all(&["rc", "out", "err", "files"])
            ),
            (
                "sealed:time".to_string(),
                StepOutcome::Pass,
                all(&["rc", "err", "files"])
            ),
            ("sealed:flaky".to_string(), StepOutcome::Unqualified, vec![]),
            (
                "sealed:write".to_string(),
                StepOutcome::Fail,
                all(&["rc", "out", "err", "files"])
            ),
            (
                "sealed:env".to_string(),
                StepOutcome::Pass,
                all(&["rc", "out", "err", "files"])
            ),
            (
                "sealed:slow".to_string(),
                StepOutcome::Fail,
                all(&["rc", "out", "err", "files"])
            ),
        ]
    );
    assert!(receipts.complete);
    let err = &receipts.steps[2];
    assert_eq!(err.reference_exit, Some(3));
    assert!(
        err.detail.contains("differing channels: err"),
        "{}",
        err.detail
    );
    assert!(err.detail.contains("different"), "{}", err.detail);
    assert!(
        receipts.steps[6]
            .detail
            .contains("differing channels: files"),
        "{}",
        receipts.steps[6].detail
    );
}

#[tokio::test]
async fn a_failed_build_fails_every_case_without_running_it() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dirs = tempfile::tempdir().expect("tempdir");
    let (base, candidate) = (dirs.path().join("base"), dirs.path().join("candidate"));
    std::fs::create_dir_all(&base).expect("base");
    std::fs::create_dir_all(&candidate).expect("candidate");
    write_executable(&candidate.join("compile.sh"), "#!/bin/sh\nexit 1\n").expect("compile.sh");
    let policy = EvidencePolicy {
        candidate_tests: false,
        reference_command: Some("/bin/echo".to_string()),
        ..policy()
    };

    let receipts = super::run(&test_env(image, 120), &candidate, &base, &policy)
        .await
        .expect("run");

    assert!(receipts.complete);
    assert!(
        receipts
            .steps
            .iter()
            .all(|step| step.outcome == StepOutcome::Fail),
        "{receipts:?}"
    );
}

#[tokio::test]
async fn observing_runs_the_reference_twice_over_the_base() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let base = tempfile::tempdir().expect("base");
    std::fs::write(base.path().join("README.md"), "# tool\n").expect("readme");
    write_executable(&base.path().join("reference.sh"), REFERENCE).expect("reference");
    let cases = vec![
        case("readme", &["cat", "README.md"]),
        case("err", &["err"]),
        case("time", &["time"]),
    ];

    let observations = super::observe(
        &test_env(image, 120),
        base.path(),
        "/pc-base/reference.sh",
        &cases,
    )
    .await
    .expect("observe");

    assert_eq!(
        observations
            .iter()
            .map(|observation| (
                observation.id.as_str(),
                observation.exit,
                observation.stable
            ))
            .collect::<Vec<_>>(),
        vec![
            ("readme", Some(0), true),
            ("err", Some(3), true),
            ("time", Some(0), false)
        ]
    );
    assert_eq!(observations[0].stdout, "# tool\n");
    assert_eq!(observations[1].stderr, "bad value\n");
}

#[tokio::test]
async fn a_hanging_build_is_the_candidates_failure_not_an_infrastructure_timeout() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dirs = tempfile::tempdir().expect("tempdir");
    let (base, candidate) = (dirs.path().join("base"), dirs.path().join("candidate"));
    std::fs::create_dir_all(&base).expect("base");
    std::fs::create_dir_all(&candidate).expect("candidate");
    std::fs::write(candidate.join("compile.sh"), "#!/bin/sh\nsleep 600\n").expect("compile.sh");
    let policy = EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("chmod +x ./compile.sh && ./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: false,
        differential: vec![],
        reference_command: None,
        sealed: vec![],
        sealed_threshold_permille: 950,
        min_sealed_qualified: 100,
        min_success_permille: 500,
    };
    // Each step gets a sixth of the container budget: 10 s here.
    let receipts = super::run(&test_env(image, 60), &candidate, &base, &policy)
        .await
        .expect("run");

    assert_eq!(receipts.steps.len(), 1, "{receipts:?}");
    assert_eq!(receipts.steps[0].outcome, StepOutcome::Fail);
    assert!(
        receipts.steps[0].detail.contains("timed out after 10 s"),
        "{}",
        receipts.steps[0].detail
    );
    assert!(receipts.complete);
}

#[test]
fn a_failure_log_keeps_its_head_and_its_tail() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let log = dir.path().join("build.log");
    std::fs::write(
        &log,
        format!("FIRST\n{}\nLAST-ERROR\n", "noise\n".repeat(2000)),
    )?;
    let output = std::process::Command::new("bash")
        .arg("-c")
        .arg(format!("{}\nlog build {}", super::PRELUDE, log.display()))
        .output()?;
    let stdout = String::from_utf8_lossy(&output.stdout);

    assert!(stdout.contains("@@LOG build FIRST"), "{stdout}");
    assert!(stdout.contains("@@LOG build LAST-ERROR"), "{stdout}");
    assert!(stdout.contains("bytes omitted"), "{stdout}");
    Ok(())
}

#[test]
fn an_observed_stream_keeps_its_head_and_its_tail_up_to_the_larger_bound() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    let help = dir.path().join("out");
    let observe = |text: String| -> std::io::Result<String> {
        std::fs::write(&help, text)?;
        let output = std::process::Command::new("bash")
            .arg("-c")
            .arg(format!(
                "OBSERVATION_CAP={}\n{}\n{}\nobs '@@OUT help ' {}",
                super::OBSERVATION_STREAM_CAP,
                super::PRELUDE,
                super::CASE_RUNNER,
                help.display()
            ))
            .output()?;
        Ok(String::from_utf8_lossy(&output.stdout).into_owned())
    };

    // 10 KB used to lose its second half at 2000 bytes; now it is whole.
    let whole = observe(format!("FIRST\n{}LAST\n", "option line\n".repeat(800)))?;
    assert!(whole.contains("@@OUT help LAST"), "{whole}");
    assert!(!whole.contains("bytes omitted"), "{whole}");

    let cut = observe(format!("FIRST\n{}LAST\n", "option line\n".repeat(5000)))?;
    assert!(cut.contains("@@OUT help FIRST"), "{cut}");
    assert!(cut.contains("@@OUT help LAST"), "{cut}");
    assert!(cut.contains("bytes omitted"), "{cut}");
    Ok(())
}
