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

#[test]
fn varying_output_retains_stable_properties_but_unqualified_runs_do_not() {
    let rows = parse_observations(
        "@@OBS varying 0 unstable rc,err,files\n@@OBS stopped 137 unqualified rc,err,files\n@@OBS historical 0 unstable\n",
    );
    assert!(!rows[0].stable);
    assert!(rows[0].qualified());
    assert_eq!(rows[0].stable_channels, vec!["rc", "err", "files"]);
    assert!(!rows[1].qualified());
    assert!(rows[1].stable_channels.is_empty());
    assert!(!rows[2].qualified());
}

fn case(id: &str, args: &[&str]) -> DifferentialCase {
    DifferentialCase {
        id: id.to_string(),
        args: args.iter().map(ToString::to_string).collect(),
        ..Default::default()
    }
}

#[tokio::test]
async fn metadata_deadline_stops_a_wrapper_and_its_descendants() {
    let root = tempfile::tempdir().unwrap();
    let pidfile = root.path().join("pid");
    let result = super::command_output(
        "sh",
        &[
            "-c",
            "sleep 30 & echo $! > \"$1\"; wait",
            "metadata",
            pidfile.to_str().unwrap(),
        ],
        std::time::Duration::from_millis(150),
    )
    .await;
    assert!(matches!(result, Err(super::CheckError::Launch(_))));
    let pid = std::fs::read_to_string(pidfile).unwrap();
    for _ in 0..100 {
        let stat = std::fs::read_to_string(format!("/proc/{}/stat", pid.trim()));
        if stat.is_err() || stat.unwrap().split(") ").nth(1).unwrap().starts_with('Z') {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    panic!("metadata timeout left a running wrapper descendant");
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
        sealed_threshold_permille: Some(950),
        min_sealed_qualified: Some(100),
        min_success_permille: Some(500),
        preparation_failure: None,
    }
}

#[tokio::test]
async fn artifact_review_does_not_require_a_program_or_container() {
    let policy = EvidencePolicy {
        class: EvidenceClass::ReviewOnly,
        build_command: None,
        candidate_command: None,
        reference_command: None,
        candidate_tests: false,
        differential: Vec::new(),
        sealed: Vec::new(),
        ..policy()
    };
    let mut env = test_env("unused".into(), 1);
    env.docker = "/nonexistent/container-runtime".into();
    let root = tempfile::tempdir().unwrap();
    for class in [EvidenceClass::ReviewOnly, EvidenceClass::ChecksAndReview] {
        // Older frozen policies used ChecksAndReview even with no declared checks.
        let policy = EvidencePolicy {
            class,
            ..policy.clone()
        };
        let receipts = super::run(&env, root.path(), root.path(), &policy)
            .await
            .unwrap();
        assert!(receipts.complete && receipts.steps.is_empty());
        assert!(receipts.environment[0].contains("no program or container executed"));
    }
}

#[tokio::test]
async fn reference_adapter_rejects_failed_containers_and_incomplete_observations() {
    let root = tempfile::tempdir().unwrap();
    let executable = root.path().join("container-adapter");
    let mut env = test_env("fixture".into(), 2);
    env.docker = executable.display().to_string();
    for (output, exit) in [("@@OBS a 0 stable", 90), ("@@OBS unrelated 0 stable", 0)] {
        write_executable(
            &executable,
            &format!("#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {exit}\n"),
        )
        .unwrap();
        let result = super::observe(&env, root.path(), "/reference", &[case("a", &[])]).await;
        assert!(
            matches!(result, Err(super::CheckError::Launch(_))),
            "{result:?}"
        );
    }
}

#[tokio::test]
async fn case_environment_cannot_replace_the_timeout_or_terminal_interpreter() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let base = tempfile::tempdir().unwrap();
    let environment = [
        ("PATH".into(), String::new()),
        ("PYTHONHOME".into(), "/missing/python-home".into()),
    ]
    .into();
    let pipe = DifferentialCase {
        env: environment,
        ..case("pipe", &["ready"])
    };
    let terminal = DifferentialCase {
        id: "terminal".into(),
        terminal: Some(crate::Terminal {
            rows: 24,
            cols: 80,
            input: String::new(),
            dialogue: Vec::new(),
        }),
        ..pipe.clone()
    };
    let observed = super::observe(
        &test_env(image, 30),
        base.path(),
        "/bin/echo",
        &[pipe, terminal],
    )
    .await
    .unwrap();
    assert_eq!(observed.len(), 2);
    for value in observed {
        assert_eq!(
            (
                value.exit,
                value.stdout.as_str(),
                value.stderr.as_str(),
                value.stable
            ),
            (Some(0), "ready\n", "", true)
        );
    }
}

#[tokio::test]
async fn completed_special_exit_codes_qualify_and_an_actual_timeout_cannot_match_them() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let root = tempfile::tempdir().unwrap();
    let base = root.path().join("base");
    let candidate = root.path().join("candidate");
    std::fs::create_dir_all(&base).unwrap();
    std::fs::create_dir_all(&candidate).unwrap();
    let invocations = vec![
        case("pipe", &[]),
        DifferentialCase {
            terminal: Some(crate::Terminal {
                rows: 24,
                cols: 80,
                input: String::new(),
                dialogue: Vec::new(),
            }),
            ..case("pty", &[])
        },
    ];
    let policy = EvidencePolicy {
        build_command: None,
        candidate_tests: false,
        differential: invocations.clone(),
        sealed: vec![],
        reference_command: Some("/pc-base/reference".into()),
        ..policy()
    };
    let env = test_env(image, 30);
    for code in [124, 137] {
        let program = format!("#!/bin/sh\nexit {code}\n");
        write_executable(&base.join("reference"), &program).unwrap();
        write_executable(&candidate.join("executable"), &program).unwrap();
        let observations = super::observe(&env, &base, "/pc-base/reference", &invocations)
            .await
            .unwrap();
        assert!(
            observations
                .iter()
                .all(|o| o.stable && o.exit == Some(code))
        );
        let receipts = super::run(&env, &candidate, &base, &policy).await.unwrap();
        assert!(
            receipts.complete
                && receipts
                    .steps
                    .iter()
                    .all(|s| s.outcome == StepOutcome::Pass)
        );
    }
    write_executable(&candidate.join("executable"), "#!/bin/sh\nsleep 30\n").unwrap();
    let pipeline = root.path().join("pipeline-timeout");
    let script =
        pipeline_script(&policy, "/candidate", 5).replace("CASE_TIMEOUT=10", "CASE_TIMEOUT=0.2");
    super::write_pipeline(&pipeline, &script, invocations)
        .await
        .unwrap();
    let out = super::run_container(
        &env,
        &pipeline,
        &[(&base, "/pc-base"), (&candidate, "/candidate")],
        std::time::Duration::from_secs(30),
    )
    .await
    .unwrap();
    let (steps, _, complete) = parse_output(&out, &policy);
    assert!(
        complete
            && steps.iter().all(|s| s.outcome == StepOutcome::Fail
                && s.reference_exit == Some(137)
                && s.detail.contains("timed_out"))
    );
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
                stable_channels: Vec::new(),
                stdout: "Usage: tool\n  -s summary\n".to_string(),
                stderr: "note\n".to_string(),
            },
            Observation {
                id: "quiet".to_string(),
                exit: Some(2),
                stable: false,
                stable_channels: Vec::new(),
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
            path: ".//tree/a.txt".to_string(),
            text: "ab".to_string(),
            repeat: 3,
        }],
        dirs: vec!["././/tree/empty".to_string()],
        env: [("NO_COLOR".to_string(), "1".to_string())].into(),
        ..case("c", &[])
    };
    write_case_inputs(dir.path(), &inputs)?;
    assert_eq!(std::fs::read_to_string(dir.path().join("stdin"))?, "input");
    let environment = std::fs::read_to_string(dir.path().join("env"))?;
    assert_eq!(environment.lines().count(), 5);
    assert!(environment.lines().any(|line| line == "NO_COLOR=1"));
    assert!(environment.lines().any(|line| line == "HOME=/tmp/pc-home"));
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
        inputs: Vec::new(),
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
        sealed_threshold_permille: Some(950),
        min_sealed_qualified: Some(1),
        min_success_permille: Some(0),
        preparation_failure: None,
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
    assert!(receipts.complete, "{receipts:?}");
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
async fn a_failed_build_blocks_cases_without_claiming_they_ran() {
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

    assert!(receipts.complete, "{receipts:?}");
    assert!(
        receipts.steps.iter().all(|step| if step.step == "build" {
            step.outcome == StepOutcome::Fail
        } else {
            step.outcome == StepOutcome::Blocked && step.reference_exit.is_none()
        }),
        "{receipts:?}"
    );
}

#[tokio::test]
async fn a_real_terminal_pipeline_preserves_pipe_and_tty_semantics_and_detects_mismatch() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dirs = tempfile::tempdir().unwrap();
    let base = dirs.path().join("base");
    let candidate = dirs.path().join("candidate");
    std::fs::create_dir_all(&base).unwrap();
    std::fs::create_dir_all(&candidate).unwrap();
    let program = "#!/usr/bin/env python3\nimport os,sys\nassert os.isatty(1) and os.isatty(2)\nwith open('/dev/tty','rb',buffering=0) as f: key=f.read(1)\nprint('reference',os.isatty(0),tuple(os.get_terminal_size(1)),key)\nif not os.isatty(0): print(sys.stdin.read(),end='')\n";
    write_executable(&base.join("reference.py"), program).unwrap();
    write_executable(&candidate.join("executable"), program).unwrap();
    let terminal = Some(crate::Terminal {
        rows: 31,
        cols: 97,
        input: "q".into(),
        dialogue: Vec::new(),
    });
    let cases = vec![
        DifferentialCase {
            terminal: terminal.clone(),
            ..case("tty", &[])
        },
        DifferentialCase {
            terminal,
            stdin: Some("piped input\n".into()),
            ..case("pipe-and-tty", &[])
        },
    ];
    let policy = EvidencePolicy {
        build_command: None,
        candidate_tests: false,
        reference_command: Some("/pc-base/reference.py".into()),
        differential: cases.clone(),
        sealed: vec![],
        ..policy()
    };
    let env = test_env(image, 120);
    let observations = super::observe(&env, &base, "/pc-base/reference.py", &cases)
        .await
        .unwrap();
    assert!(observations.iter().all(|o| o.exit == Some(0) && o.stable));
    assert!(observations[0].stdout.contains("True (97, 31)"));
    assert!(observations[1].stdout.contains("False (97, 31)"));
    assert!(observations[1].stdout.contains("piped input"));
    let receipts = super::run(&env, &candidate, &base, &policy).await.unwrap();
    assert!(
        receipts.complete
            && receipts
                .steps
                .iter()
                .all(|s| s.outcome == StepOutcome::Pass)
    );
    write_executable(
        &candidate.join("executable"),
        &program.replace("'reference'", "'wrong'"),
    )
    .unwrap();
    let receipts = super::run(&env, &candidate, &base, &policy).await.unwrap();
    assert!(
        receipts.complete
            && receipts
                .steps
                .iter()
                .all(|s| s.outcome == StepOutcome::Fail)
    );
}

#[tokio::test]
async fn a_bounded_timeout_does_not_cancel_unrelated_cases() {
    let Ok(image) = std::env::var("PRO_CONTRACT_TEST_IMAGE") else {
        return;
    };
    let dirs = tempfile::tempdir().unwrap();
    let base = dirs.path().join("base");
    let candidate = dirs.path().join("candidate");
    let pipeline = dirs.path().join("pipeline");
    std::fs::create_dir_all(&base).unwrap();
    std::fs::create_dir_all(&candidate).unwrap();
    write_executable(
        &candidate.join("executable"),
        "#!/bin/sh\n[ \"$1\" = slow ] && sleep 30\nprintf '%s\\n' \"$@\"\n",
    )
    .unwrap();
    let policy = EvidencePolicy {
        build_command: None,
        candidate_tests: false,
        reference_command: Some("/bin/echo".into()),
        differential: vec![case("first", &["slow"]), case("later", &["ready"])],
        sealed: vec![],
        ..policy()
    };
    let script =
        pipeline_script(&policy, "/candidate", 5).replace("CASE_TIMEOUT=10", "CASE_TIMEOUT=1");
    super::write_pipeline(&pipeline, &script, policy.differential.clone())
        .await
        .unwrap();
    let stdout = super::run_container(
        &test_env(image, 30),
        &pipeline,
        &[(&base, "/pc-base"), (&candidate, "/candidate")],
        std::time::Duration::from_secs(30),
    )
    .await
    .unwrap();
    let (steps, _, complete) = parse_output(&stdout, &policy);
    assert!(complete);
    assert_eq!(steps[0].outcome, StepOutcome::Fail);
    assert_eq!(steps[1].outcome, StepOutcome::Pass);
    assert_eq!(steps[1].reference_exit, Some(0));
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
        sealed_threshold_permille: Some(950),
        min_sealed_qualified: Some(100),
        min_success_permille: Some(500),
        preparation_failure: None,
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
    assert!(receipts.complete, "{receipts:?}");
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
