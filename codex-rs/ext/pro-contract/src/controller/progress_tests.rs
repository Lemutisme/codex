use super::*;
use crate::controller::archive::{Operation, Query};
use crate::{ProgressSettings, SuccessionSettings};
use pretty_assertions::{assert_eq, assert_ne};

async fn progressing(ports: FakePorts) -> Lane {
    let mut lane = lane(ports).await;
    let runtime = Arc::get_mut(&mut lane.runtime).unwrap();
    runtime.settings.succession = Some(SuccessionSettings {
        max_sessions: 1,
        total_secs: 3600,
    });
    runtime.settings.progress = Some(ProgressSettings {
        executor_label: "procontract.task=test".into(),
        max_publications: 3,
        assessment_secs: 120,
        executor_slice_secs: 1800,
    });
    lane
}

#[tokio::test]
async fn publication_retains_feedback_without_proposing_and_reuses_identical_work() {
    let lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let first = lane
        .runtime
        .publish_progress("first".into(), "one-turn".into())
        .await
        .unwrap();
    assert_eq!(first["completion_certified"], false);
    assert!(lane.contract().await.unwrap().candidate.is_none());
    let retry = lane
        .runtime
        .publish_progress("first".into(), "one-turn".into())
        .await
        .unwrap();
    assert_eq!(retry["handle"], first["handle"]);
    let same = lane
        .runtime
        .publish_progress("same-content".into(), "one-turn".into())
        .await
        .unwrap();
    assert_eq!(same["handle"], first["handle"]);
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    std::fs::write(lane.workspace.join("answer.txt"), "done").unwrap();
    let second = lane
        .runtime
        .publish_progress("second".into(), "one-turn".into())
        .await
        .unwrap();
    assert_ne!(second["subject_hash"], first["subject_hash"]);
    assert_eq!(lane.ledger.events().await.unwrap().len(), 1);
    let index = lane
        .runtime
        .evidence_access()
        .read(
            Query {
                op: Operation::Index,
                handle: None,
                offset: 0,
            },
            8192,
        )
        .await
        .unwrap();
    assert_eq!(index["entries"].as_array().unwrap().len(), 2);
    assert_eq!(index["entries"][0]["kind"], "progress");
    assert!(
        lane.runtime
            .publish_progress("fourth".into(), "one-turn".into())
            .await
            .unwrap_err()
            .contains("exhausted")
    );
    lane.runtime.restore().await;
    lane.runtime.turn_started().await;
    assert_eq!(
        lane.runtime
            .publish_progress("second".into(), "restored".into())
            .await
            .unwrap()["handle"],
        second["handle"]
    );
    lane.executor_turn("final", "done").await;
    lane.wait_for("supported").await;
    assert_eq!(lane.ledger.events().await.unwrap().len(), 3);
}

#[tokio::test]
async fn unknown_publication_is_not_replayed_or_used_for_acceptance_after_restart() {
    let lane = progressing(FakePorts::new(CONTRACT_DRAFT).checks(&[])).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let result = lane
        .runtime
        .publish_progress("unknown".into(), "one".into())
        .await
        .unwrap();
    assert_eq!(result["effects_resolved"], false);
    assert!(
        lane.runtime
            .publish_progress("retry".into(), "one".into())
            .await
            .is_err()
    );
    lane.runtime.restore().await;
    let status: StatusRecord = lane
        .ledger
        .record(STATUS_KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(status.phase, "not_verified");
    assert!(status.detail.contains("unresolved"));
    assert_eq!(lane.ledger.events().await.unwrap().len(), 1);
}

#[tokio::test]
async fn remaining_grant_can_fund_repair_without_reserving_all_verification_maxima() {
    let mut lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    let runtime = Arc::get_mut(&mut lane.runtime).unwrap();
    runtime.profile.check.timeout_secs = 1800;
    runtime.settings.worker.deadline_secs = 2400;
    *lane.ports.successor_workspace.lock().unwrap() = Some(lane.workspace.clone());
    lane.ports
        .successor_answers
        .lock()
        .unwrap()
        .push_back("done".into());
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let before: serde_json::Value = lane
        .ledger
        .record("succession", &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    lane.executor_turn("original", "bad").await;
    lane.wait_for("supported").await;
    let after: serde_json::Value = lane
        .ledger
        .record("succession", &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(after["launches"], 1);
    assert_eq!(after["deadline_ms"], before["deadline_ms"]);
    let packet: serde_json::Value =
        serde_json::from_str(&lane.ports.successor_packets.lock().unwrap()[0].1).unwrap();
    assert!(
        packet["executor_deadline_ms"].as_u64().unwrap() < before["deadline_ms"].as_u64().unwrap()
    );
}

#[tokio::test]
async fn completed_publication_recovers_a_crash_before_grant_finalization_without_reexecution() {
    let lane = progressing(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail])).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let receipt = lane
        .runtime
        .publish_progress("retained".into(), "one".into())
        .await
        .unwrap();
    // Preserve the record's serialized representation: CAS compares the exact prior bytes.
    let raw: Box<serde_json::value::RawValue> = lane
        .ledger
        .record("progress_grant_v1", &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    let value: serde_json::Value = serde_json::from_str(raw.get()).unwrap();
    let interrupted = raw
        .get()
        .replace("\"pending\":null", "\"pending\":\"retained\"")
        .replace(
            &format!("\"completed\":{}", value["completed"]),
            "\"completed\":[]",
        );
    let interrupted: Box<serde_json::value::RawValue> = serde_json::from_str(&interrupted).unwrap();
    lane.ledger
        .put_record(
            "progress_grant_v1",
            &lane.thread_id.to_string(),
            &interrupted,
        )
        .await
        .unwrap();
    lane.runtime.restore().await;
    lane.runtime.turn_started().await;
    let recovered = lane
        .runtime
        .publish_progress("retained".into(), "two".into())
        .await
        .unwrap();
    assert_eq!(recovered["handle"], receipt["handle"]);
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    let after: serde_json::Value = lane
        .ledger
        .record("progress_grant_v1", &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(after["used"], 1);
    assert_eq!(after["pending"], serde_json::Value::Null);
}

#[tokio::test]
async fn publication_waits_for_preparation_without_a_turn_boundary_or_an_extra_grant() {
    let gate = Arc::new(Notify::new());
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.draft_gate = Some(Arc::clone(&gate));
    let lane = progressing(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    let runtime = Arc::clone(&lane.runtime);
    let waiting = tokio::spawn(async move {
        runtime
            .publish_progress("early".into(), "same-turn".into())
            .await
    });
    tokio::task::yield_now().await;
    assert!(!waiting.is_finished());
    gate.notify_one();
    let response = waiting.await.unwrap().unwrap();
    assert_eq!(response["publication"], 1);
    assert!(lane.contract().await.unwrap().candidate.is_none());
}

#[tokio::test]
async fn executable_progress_does_not_start_a_full_review_before_acceptance() {
    let mut lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .profile
        .check
        .build_command = Some("test -f answer.txt".into());
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let response = lane
        .runtime
        .publish_progress("checked".into(), "same".into())
        .await
        .unwrap();
    assert!(
        response["feedback"]
            .as_str()
            .unwrap()
            .contains("Public executable checks completed")
    );
    assert!(lane.ports.review_prompts.lock().unwrap().is_empty());
    lane.executor_turn("delivery", "done").await;
    lane.wait_for("supported").await;
    assert_eq!(lane.ports.review_prompts.lock().unwrap().len(), 1);
}
