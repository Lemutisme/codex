use super::*;

fn fixture(directory: PathBuf, lifetime: Duration) -> Result<InspectionGrant, String> {
    InspectionGrant::open(
        crate::CheckEnvironment {
            inputs: Vec::new(),
            docker: "docker".into(),
            image: "pinned-image".into(),
            user: "1000:1000".into(),
            candidate_mount: "/candidate".into(),
            timeout_secs: 30,
            build_command: None,
            candidate_command: None,
        },
        crate::ReviewExecution {
            max_calls: 2,
            timeout_secs: 10,
            max_output_bytes: 4096,
        },
        directory,
        Digest::of(b"frozen subject"),
        &crate::Terms {
            context: Vec::new(),
            intake_text: "original task".into(),
            requirements: vec![],
            out_of_scope: vec![],
            process_constraints: vec![],
        },
        lifetime,
    )
}

#[test]
fn restart_preserves_reservations_and_the_original_deadline() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("grant");
    let first = fixture(path.clone(), Duration::from_secs(30)).unwrap();
    first
        .reserve(
            &json!({"malformed":"still spends a reservation"}),
            Duration::from_secs(60),
        )
        .unwrap();
    let restored = fixture(path, Duration::from_secs(3600)).unwrap();
    assert_eq!(restored.deadline_ms, first.deadline_ms);
    let (work, remaining) = restored
        .reserve(&json!({}), Duration::from_secs(60))
        .unwrap();
    assert_eq!(work.file_name().unwrap(), "call-1");
    assert!(remaining <= Duration::from_secs(30));
    assert!(
        restored
            .reserve(&json!({}), Duration::from_secs(60))
            .is_err()
    );
}

#[test]
fn expired_or_unknown_actions_cannot_obtain_a_fresh_dispatch() {
    let root = tempfile::tempdir().unwrap();
    let expired = fixture(root.path().join("expired"), Duration::ZERO).unwrap();
    assert!(
        expired
            .reserve(&json!({}), Duration::from_secs(60))
            .is_err()
    );
    let live = fixture(root.path().join("live"), Duration::from_secs(60)).unwrap();
    let (work, _) = live.reserve(&json!({}), Duration::from_secs(60)).unwrap();
    std::fs::create_dir_all(work.join("action")).unwrap();
    std::fs::write(
        work.join("action/execution.json"),
        r#"{"state":"running","shutdown_confirmed":false}"#,
    )
    .unwrap();
    let restored = fixture(live.directory, Duration::from_secs(3600)).unwrap();
    assert!(
        restored
            .reserve(&json!({}), Duration::from_secs(60))
            .unwrap_err()
            .contains("unresolved")
    );
}

#[test]
fn recovered_evidence_requires_the_same_grant_and_content_identity() {
    let root = tempfile::tempdir().unwrap();
    let store = crate::BlobStore::open(&root.path().join("blobs")).unwrap();
    let grant = fixture(root.path().join("grant"), Duration::from_secs(60)).unwrap();
    let (work, _) = grant.reserve(&json!({}), Duration::from_secs(60)).unwrap();
    std::fs::create_dir(&work).unwrap();
    let document = grant
        .retain(
            &work,
            json!({"stdout":"observed","execution":{"shutdown_confirmed":true}}),
            &store,
        )
        .unwrap();
    let restored = fixture(grant.directory, Duration::from_secs(600)).unwrap();
    assert_eq!(restored.history(&store).unwrap(), vec![document]);
    std::fs::write(work.join("result.json"), r#"{"stdout":"fabricated"}"#).unwrap();
    assert!(restored.history(&store).is_err());
}

#[test]
fn confirmed_shutdown_without_a_caller_result_preserves_spent_slot_and_allows_next_action() {
    let root = tempfile::tempdir().unwrap();
    let grant = fixture(root.path().join("grant"), Duration::from_secs(60)).unwrap();
    let (work, _) = grant
        .reserve(&json!({"first":true}), Duration::from_secs(60))
        .unwrap();
    std::fs::create_dir_all(work.join("action")).unwrap();
    std::fs::write(
        work.join("action/execution.json"),
        r#"{"state":"cancelled","shutdown_confirmed":true}"#,
    )
    .unwrap();
    let (next, _) = grant
        .reserve(&json!({"next":true}), Duration::from_secs(60))
        .unwrap();
    assert_ne!(work, next);
    assert!(!work.join("result.json").exists());
}
