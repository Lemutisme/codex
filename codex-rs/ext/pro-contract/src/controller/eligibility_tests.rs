use std::path::PathBuf;

use pretty_assertions::assert_eq;

use super::Eligibility;
use super::EligibilityFacts;
use super::eligibility;
use crate::CheckEnvironment;
use crate::EvaluationProfile;
use crate::Settings;
use crate::WorkerSettings;

fn settings() -> Settings {
    Settings {
        evaluation: Some(EvaluationProfile {
            environment_id: "cleanroom".to_string(),
            workspace_container_root: "/workspace".to_string(),
            workspace_host_root: PathBuf::from("/tmp/ws"),
            excluded_paths: vec![],
            check: CheckEnvironment {
                docker: "docker".to_string(),
                image: "img".to_string(),
                user: "1000:1000".to_string(),
                candidate_mount: "/candidate".to_string(),
                timeout_secs: 60,
                build_command: None,
                candidate_command: None,
            },
            reference_command: None,
        }),
        repair_attempts: 1,
        worker: WorkerSettings::default(),
    }
}

fn facts(settings: &Settings) -> EligibilityFacts<'_> {
    EligibilityFacts {
        feature_enabled: true,
        internal_or_subagent: false,
        persistent: true,
        settings: Some(settings),
        environment_ids: vec!["cleanroom"],
        mcp_server_count: 0,
        notify_configured: false,
        hooks_enabled: false,
    }
}

#[test]
fn the_configured_isolated_environment_is_eligible() {
    let settings = settings();
    assert_eq!(
        eligibility(&facts(&settings)),
        Eligibility::Eligible(settings.evaluation.as_ref().expect("profile"))
    );
}

#[test]
fn a_disabled_feature_or_an_internal_thread_is_inactive() {
    let settings = settings();
    let off = EligibilityFacts {
        feature_enabled: false,
        ..facts(&settings)
    };
    let worker = EligibilityFacts {
        internal_or_subagent: true,
        ..facts(&settings)
    };
    assert_eq!(
        (eligibility(&off), eligibility(&worker)),
        (Eligibility::Inactive, Eligibility::Inactive)
    );
}

#[test]
fn without_the_evaluation_grant_the_thread_abstains() {
    let settings = Settings {
        evaluation: None,
        ..settings()
    };
    let no_file = EligibilityFacts {
        settings: None,
        ..facts(&settings)
    };
    assert!(matches!(eligibility(&facts(&settings)), Eligibility::Abstain(_)));
    assert!(matches!(eligibility(&no_file), Eligibility::Abstain(_)));
}

#[test]
fn any_other_environment_selection_abstains() {
    let settings = settings();
    for ids in [vec![], vec!["local"], vec!["cleanroom", "local"]] {
        let case = EligibilityFacts {
            environment_ids: ids.clone(),
            ..facts(&settings)
        };
        assert!(
            matches!(eligibility(&case), Eligibility::Abstain(_)),
            "{ids:?}"
        );
    }
}

#[test]
fn reachable_host_capabilities_abstain() {
    let settings = settings();
    let cases = [
        EligibilityFacts {
            mcp_server_count: 1,
            ..facts(&settings)
        },
        EligibilityFacts {
            notify_configured: true,
            ..facts(&settings)
        },
        EligibilityFacts {
            hooks_enabled: true,
            ..facts(&settings)
        },
        EligibilityFacts {
            persistent: false,
            ..facts(&settings)
        },
    ];
    for case in cases {
        assert!(matches!(eligibility(&case), Eligibility::Abstain(_)));
    }
}
