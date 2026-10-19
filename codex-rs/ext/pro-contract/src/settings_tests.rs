use std::path::PathBuf;

use pretty_assertions::assert_eq;

use super::CheckEnvironment;
use super::EvaluationProfile;
use super::EvidenceSettings;
use super::Settings;
use super::SettingsError;
use super::WorkerSettings;

fn write_settings(home: &std::path::Path, text: &str) {
    std::fs::create_dir_all(home.join("pro_contract")).expect("mkdir");
    std::fs::write(home.join("pro_contract/settings.json"), text).expect("write");
}

#[test]
fn a_missing_settings_file_means_no_settings() {
    let home = tempfile::tempdir().expect("tempdir");
    assert_eq!(Settings::load(home.path()).expect("load"), None);
}

#[test]
fn an_evaluation_profile_loads_with_defaults() {
    let home = tempfile::tempdir().expect("tempdir");
    write_settings(
        home.path(),
        r#"{
          "evaluation": {
            "environment_id": "cleanroom",
            "workspace_container_root": "/workspace",
            "workspace_host_root": "/tmp/ws",
            "excluded_paths": [".git", "target", "executable"],
            "check": {
              "docker": "docker",
              "image": "img:tag",
              "user": "1000:1000",
              "candidate_mount": "/candidate",
              "timeout_secs": 600,
              "build_command": "./compile.sh",
              "candidate_command": "./executable"
            },
            "reference_command": "/workspace/executable"
          }
        }"#,
    );
    assert_eq!(
        Settings::load(home.path()).expect("load"),
        Some(Settings {
            review_execution: None,
            progress: None,
            evaluation: Some(EvaluationProfile {
                environment_id: "cleanroom".to_string(),
                workspace_container_root: "/workspace".to_string(),
                workspace_host_root: PathBuf::from("/tmp/ws"),
                excluded_paths: vec![
                    ".git".to_string(),
                    "target".to_string(),
                    "executable".to_string()
                ],
                check: CheckEnvironment {
                    inputs: Vec::new(),
                    docker: "docker".to_string(),
                    image: "img:tag".to_string(),
                    user: "1000:1000".to_string(),
                    candidate_mount: "/candidate".to_string(),
                    timeout_secs: 600,
                    build_command: Some("./compile.sh".to_string()),
                    candidate_command: Some("./executable".to_string()),
                },
                reference_command: Some("/workspace/executable".to_string()),
            }),
            repair_attempts: 1,
            succession: None,
            worker: WorkerSettings {
                model: None,
                reasoning_effort: None,
                deadline_secs: 900,
            },
            evidence: EvidenceSettings {
                sealed_threshold_permille: None,
                min_sealed_qualified: None,
                min_success_permille: None,
            },
            policy: None,
        })
    );
}

#[test]
fn evidence_settings_are_read_and_default_field_by_field() {
    let home = tempfile::tempdir().expect("tempdir");
    write_settings(
        home.path(),
        r#"{"evaluation": null, "evidence": {"sealed_threshold_permille": 900}}"#,
    );
    assert_eq!(
        Settings::load(home.path())
            .expect("load")
            .expect("settings")
            .evidence,
        EvidenceSettings {
            sealed_threshold_permille: Some(900),
            min_sealed_qualified: None,
            min_success_permille: None,
        }
    );
}

#[test]
fn unknown_fields_are_rejected() {
    let home = tempfile::tempdir().expect("tempdir");
    write_settings(home.path(), r#"{"evaluation": null, "surprise": true}"#);
    assert!(matches!(
        Settings::load(home.path()),
        Err(SettingsError::Parse { .. })
    ));
}
#[test]
fn progress_does_not_invent_an_executor_window_or_publication_quota() {
    let progress: super::ProgressSettings = serde_json::from_value(serde_json::json!({
        "executor_label":"procontract.task=test", "assessment_secs":120
    }))
    .unwrap();
    assert_eq!(progress.executor_slice_secs, None);
    assert_eq!(progress.max_publications, None);
    let value = serde_json::to_value(progress).unwrap();
    assert!(value.get("executor_slice_secs").is_none());
    assert!(value.get("max_publications").is_none());
}
