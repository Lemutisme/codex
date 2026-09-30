use std::path::PathBuf;

use pretty_assertions::assert_eq;

use super::CheckEnvironment;
use super::EvaluationProfile;
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
              "timeout_secs": 600
            },
            "reference_command": "/workspace/executable"
          }
        }"#,
    );
    assert_eq!(
        Settings::load(home.path()).expect("load"),
        Some(Settings {
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
                    docker: "docker".to_string(),
                    image: "img:tag".to_string(),
                    user: "1000:1000".to_string(),
                    candidate_mount: "/candidate".to_string(),
                    timeout_secs: 600,
                },
                reference_command: Some("/workspace/executable".to_string()),
            }),
            repair_attempts: 1,
            worker: WorkerSettings {
                model: None,
                reasoning_effort: None,
                deadline_secs: 900,
            },
        })
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
