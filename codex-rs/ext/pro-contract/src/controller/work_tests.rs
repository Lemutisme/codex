use super::*;
use crate::controller::archive::{Operation, Query};
use pretty_assertions::assert_eq;
use serde_json::{Value, json};

async fn query(lane: &Lane, op: Operation, handle: Option<Digest>, offset: usize) -> Value {
    lane.runtime
        .evidence_access()
        .read(Query { op, handle, offset }, 4096)
        .await
        .unwrap()
}

async fn read(lane: &Lane, handle: Digest) -> String {
    let mut offset = 0;
    let mut text = String::new();
    loop {
        let page = query(lane, Operation::Read, Some(handle), offset).await;
        text.push_str(page["text"].as_str().unwrap());
        if page["eof"] == true {
            break;
        }
        let next = page["next_offset"].as_u64().unwrap() as usize;
        assert!(next > offset);
        offset = next;
    }
    assert_eq!(Digest::of(text.as_bytes()), handle);
    text
}

#[tokio::test]
async fn public_evidence_survives_summary_bounds_restart_and_later_verifications() {
    let ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail; 5]);
    let detail = format!(
        "{}\noriginal counterexample 尾部\u{0}\n",
        "retained observation\n".repeat(180)
    );
    ports
        .public_steps
        .lock()
        .unwrap()
        .push_back(vec![StepReceipt::new("build", StepOutcome::Fail, &detail)]);
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "failed").await;
    lane.wait_for("repairing").await;
    let index = query(&lane, Operation::Index, None, 0).await;
    let handle: Digest = serde_json::from_value(index["entries"][0]["handle"].clone()).unwrap();
    let original = read(&lane, handle).await;
    let record: Value = serde_json::from_str(&original).unwrap();
    assert_eq!(record["checks"][0]["receipt"]["detail"], detail);
    for i in 0..4 {
        lane.executor_turn(&format!("later-{i}"), "still failed")
            .await;
        lane.wait_for("did_not_pass").await;
    }
    lane.runtime.restore().await;
    assert_eq!(read(&lane, handle).await, original);
    assert_eq!(query(&lane, Operation::Index, None, 0).await["total"], 5);
    assert_eq!(
        query(&lane, Operation::Frontier, None, 0).await["entries"][0]["step"],
        "build"
    );
    assert_eq!(
        lane.ports.checked.lock().unwrap().len(),
        5,
        "recall never executes a check"
    );
}

#[tokio::test]
async fn unrelated_green_check_cannot_erase_a_retained_counterexample_or_authorize_support() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Fail, StepOutcome::Pass, StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]);
    ports.public_steps.lock().unwrap().extend([
        vec![StepReceipt::new(
            "build",
            StepOutcome::Fail,
            "older public counterexample",
        )],
        vec![StepReceipt::new(
            "candidate_tests",
            StepOutcome::Pass,
            "narrow green batch",
        )],
        vec![StepReceipt::new(
            "build",
            StepOutcome::Pass,
            "original check replayed",
        )],
    ]);
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("failed", "first").await;
    lane.wait_for("repairing").await;
    lane.executor_turn("green-but-incomplete", "second").await;
    let blocked = lane.wait_for("not_verified").await;
    assert_eq!(blocked.class, "insufficient_evidence");
    assert!(lane.contract().await.unwrap().support.is_none());
    let frontier = query(&lane, Operation::Frontier, None, 0).await;
    assert_eq!(frontier["entries"][0]["step"], "build");
    lane.runtime.restore().await;
    lane.executor_turn("actual-replay", "done").await;
    lane.wait_for("supported").await;
    assert_eq!(query(&lane, Operation::Frontier, None, 0).await["total"], 0);
    assert_eq!(
        lane.contract().await.unwrap().standing,
        codex_pro_contract::Standing::Outstanding
    );
}

#[tokio::test]
async fn candidate_defeat_and_evidence_blockage_do_not_schedule_another_executor() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.sealed_qualified = 0;
    let lane = reference_lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("failed-without-evidence", "failed")
        .await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "insufficient_evidence");
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    assert!(lane.ports.successor_packets.lock().unwrap().is_empty());
    let events = lane.ledger.events().await.unwrap();
    assert!(events.iter().any(|e| matches!(
        e.command.command,
        codex_pro_contract::Command::Defeat { .. }
    )));
    let journal = lane.ledger.experiments().await.unwrap();
    let verification = journal
        .iter()
        .find(|r| r.event.kind == ExperimentKind::Verification)
        .unwrap();
    assert_eq!(verification.event.body["verdict"], "defeat");
    assert_eq!(
        verification.event.body["evidence_blocker"]["class"],
        "insufficient_evidence"
    );
    assert!(events.iter().any(|e| matches!(e.command.command, codex_pro_contract::Command::Defeat { defeater, .. } if defeater == verification.hash)));
}

#[tokio::test]
async fn evidence_reader_excludes_sealed_cases_and_rejects_foreign_or_arbitrary_blobs() {
    let lane = reference_lane(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail])).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "failed").await;
    lane.wait_for("repairing").await;
    let index = query(&lane, Operation::Index, None, 0).await;
    let handle: Digest = serde_json::from_value(index["entries"][0]["handle"].clone()).unwrap();
    let public = read(&lane, handle).await;
    assert!(!public.contains("--sealed-secret"));
    assert!(!public.contains("sealed:s1"));
    let arbitrary = lane.runtime.store.put(b"private host data").unwrap();
    let mut foreign: Value = serde_json::from_str(&public).unwrap();
    foreign["contract_id"] = json!("another-responsibility");
    let foreign = lane
        .runtime
        .store
        .put(&serde_json::to_vec(&foreign).unwrap())
        .unwrap();
    let mut foreign_event = lane
        .ledger
        .experiments()
        .await
        .unwrap()
        .into_iter()
        .find(|r| r.event.kind == ExperimentKind::Verification)
        .unwrap()
        .event;
    foreign_event.body["contract_id"] = json!("another-responsibility");
    foreign_event.body["public_evidence"] = json!(foreign);
    lane.ledger.append_experiment(&foreign_event).await.unwrap();
    let access = lane.runtime.evidence_access();
    for id in [arbitrary, foreign] {
        assert!(
            access
                .read(
                    Query {
                        op: Operation::Read,
                        handle: Some(id),
                        offset: 0
                    },
                    4096
                )
                .await
                .is_err()
        );
    }
    assert!(serde_json::from_value::<Query>(json!({"op":"read", "handle":"/etc/passwd"})).is_err());
    assert!(
        access
            .read(
                Query {
                    op: Operation::Read,
                    handle: Some(handle),
                    offset: 0
                },
                1
            )
            .await
            .is_err()
    );
    assert!(
        access
            .read(
                Query {
                    op: Operation::Read,
                    handle: Some(handle),
                    offset: usize::MAX
                },
                4096
            )
            .await
            .is_err()
    );
}

#[tokio::test]
async fn a_late_old_failure_does_not_reopen_a_newer_passing_replay() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("old", "failed").await;
    lane.wait_for("repairing").await;
    let old = lane
        .ledger
        .experiments()
        .await
        .unwrap()
        .into_iter()
        .find(|r| r.event.kind == ExperimentKind::Verification)
        .unwrap()
        .event;
    lane.executor_turn("new", "done").await;
    lane.wait_for("supported").await;
    // A superseded verification can arrive late; its candidate generation remains old.
    lane.ledger.append_experiment(&old).await.unwrap();
    assert_eq!(query(&lane, Operation::Frontier, None, 0).await["total"], 0);
}

#[tokio::test]
async fn unreadable_work_evidence_blocks_support_instead_of_forgetting_a_counterexample() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("old", "failed").await;
    lane.wait_for("repairing").await;
    let index = query(&lane, Operation::Index, None, 0).await;
    let hash = index["entries"][0]["handle"].as_str().unwrap();
    let path = lane
        ._dirs
        .path()
        .join("pro_contract/blobs")
        .join(&hash[..2])
        .join(hash);
    std::fs::write(path, "corrupted evidence").unwrap();
    lane.executor_turn("new", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "infrastructure");
    assert!(lane.contract().await.unwrap().support.is_none());
}
