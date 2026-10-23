//! Controller integration: real ledger/capture/reducer, scripted isolated executors and checks.
use super::*;
use crate::SuccessionSettings;
use crate::controller::succession_budget::Budget;
use crate::controller::succession_budget::KIND;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

async fn successors(ports: FakePorts, max_sessions: u32, answers: &[&str]) -> Lane {
    let mut lane = lane(ports).await;
    Arc::get_mut(&mut lane.runtime).unwrap().settings.succession = Some(SuccessionSettings {
        max_sessions: Some(max_sessions),
        total_secs: Some(3600),
    });
    *lane.ports.successor_workspace.lock().unwrap() = Some(lane.workspace.clone());
    *lane.ports.successor_answers.lock().unwrap() = answers
        .iter()
        .map(std::string::ToString::to_string)
        .collect();
    lane
}

#[tokio::test]
async fn a_following_selection_observes_the_actual_executor_return_and_captured_subject() {
    let lane = successors(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
        2,
        &["still wrong", "done"],
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "wrong").await;
    lane.wait_for("supported").await;
    let prompts = lane.ports.continuation_prompts.lock().unwrap();
    assert_eq!(prompts.len(), 2);
    let facts: serde_json::Value =
        serde_json::from_str(prompts[1].rsplit_once("\n\n").unwrap().1).unwrap();
    let previous = &facts["previous_choice"];
    let records = previous["execution_records"].as_array().unwrap();
    assert_eq!(records.len(), 2);
    assert!(
        records
            .iter()
            .all(|r| r["event"]["continuation"] == previous["record"])
    );
    let returned = &records[1]["event"];
    assert_eq!(returned["exit"], "handoff");
    assert_eq!(returned["shutdown_confirmed"], true);
    assert_eq!(returned["handoff_turn_id"], facts["assessed_turn_id"]);
    assert_eq!(
        previous["delivery"]["event"]["subject_hash"],
        facts["subject_hash"]
    );
    assert_ne!(previous["subject_hash"], facts["subject_hash"]);
    // A successful executor return did not erase the new failing assessment.
    assert_eq!(facts["assessment"]["decision"], "defeat");
}

#[tokio::test]
async fn a_deadline_only_grant_keeps_authorized_same_thread_repair_without_new_executors() {
    let lane = successors(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
        0,
        &[],
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let original: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    let visible = lane.runtime.remaining_task_budget().await.unwrap();
    assert_eq!(
        visible["deadline_ms"],
        serde_json::json!(original.deadline_ms)
    );
    assert!(
        visible["publications_used"].is_null(),
        "no publication grant must not hide the task deadline"
    );
    lane.executor_turn("original", "wrong").await;
    let repairing = lane.wait_for("repairing").await;
    assert_eq!(repairing.repairs_used, 1);
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
    lane.executor_turn("repair", "ready").await;
    lane.wait_for("supported").await;
    let current: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(current.started_ms, original.started_ms);
    assert_eq!(current.deadline_ms, original.deadline_ms);
    assert_eq!(current.launches, 0);
    assert_eq!(lane.ports.successor_packets.lock().unwrap().len(), 0);
    assert_eq!(lane.ports.draft_prompts.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn open_ended_successor_is_cancelled_by_its_owner_without_settling_the_responsibility() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.successor_gate = Some(Arc::new(Notify::new()));
    let mut lane = successors(ports, 2, &["must not replace owner work"]).await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .succession
        .as_mut()
        .unwrap()
        .total_secs = None;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "failed").await;
    lane.wait_for("succeeding").await;
    lane.runtime.turn_started().await;
    lane.write_answer("new owner work");
    let budget: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(budget.deadline_ms, None);
    assert_eq!((budget.launches, budget.pending), (1, None));
    assert_eq!(
        std::fs::read_to_string(lane.workspace.join("answer.txt")).unwrap(),
        "new owner work"
    );
    assert_eq!(
        lane.contract().await.unwrap().standing,
        codex_pro_contract::Standing::Outstanding
    );
}

#[tokio::test]
async fn open_ended_successors_share_accounting_and_do_not_acquire_a_local_deadline() {
    let mut lane = successors(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
        2,
        &["ready"],
    )
    .await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .succession
        .as_mut()
        .unwrap()
        .total_secs = None;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "wrong").await;
    lane.wait_for("supported").await;
    let packets = lane.ports.successor_packets.lock().unwrap().clone();
    let packet: serde_json::Value = serde_json::from_str(&packets[0].1).unwrap();
    assert!(packet["original_task_deadline_ms"].is_null());
    assert!(packet["executor_deadline_ms"].is_null());
    let budget: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(budget.launches, 1);
    assert_eq!(budget.deadline_ms, None);
}

#[tokio::test]
async fn two_fresh_sessions_inherit_lessons_and_only_one_responsibility() {
    let lane = successors(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Fail, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
        /*max_sessions*/ 3,
        &["different failed approach", "done"],
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let before: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    lane.executor_turn("original-turn", "almost").await;
    lane.wait_for("supported").await;
    let packets = lane.ports.successor_packets.lock().unwrap().clone();
    assert_eq!(packets.len(), 2);
    assert_ne!(packets[0].0, packets[1].0);
    let second: serde_json::Value = serde_json::from_str(&packets[1].1).unwrap();
    for (_, packet) in &packets {
        let value: serde_json::Value = serde_json::from_str(packet).unwrap();
        assert_eq!(
            value["executor_deadline_ms"],
            serde_json::json!(before.deadline_ms)
        );
        assert_eq!(
            value["original_task_deadline_ms"],
            serde_json::json!(before.deadline_ms)
        );
    }
    assert_eq!(second["original_task"], INTAKE);
    assert_eq!(
        second["prior_assessments_and_selected_work"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        second["previous_executor_claim_untrusted"],
        "executor claims: different failed approach"
    );
    assert_eq!(
        *lane.ports.checked.lock().unwrap(),
        ["almost", "different failed approach", "done"]
    );
    assert_eq!(*lane.ports.repairs.lock().unwrap(), Vec::new());
    let commands: Vec<_> = lane
        .ledger
        .events()
        .await
        .unwrap()
        .into_iter()
        .map(|e| e.command.command)
        .collect();
    assert_eq!(
        commands
            .iter()
            .filter(|c| matches!(c, codex_pro_contract::Command::Issue { .. }))
            .count(),
        1
    );
    let after: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        (after.deadline_ms, after.launches, after.pending),
        (before.deadline_ms, 2, None)
    );
    assert_eq!(
        lane.contract().await.unwrap().standing,
        codex_pro_contract::Standing::Outstanding
    );
}

#[tokio::test]
async fn exhausted_grant_stays_spent_after_restore_and_new_owner_turn() {
    let lane = successors(
        FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail; 3]),
        /*max_sessions*/ 1,
        &["still failed"],
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "first failed").await;
    lane.wait_for("did_not_pass").await;
    let before: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    lane.runtime.restore().await;
    lane.executor_turn("human-continuation", "another failed")
        .await;
    lane.wait_for("did_not_pass").await;
    assert_eq!(lane.ports.successor_packets.lock().unwrap().len(), 1);
    assert_eq!(
        lane.ledger
            .record::<Budget>(KIND, &lane.thread_id.to_string())
            .await
            .unwrap(),
        Some(before)
    );
}

#[tokio::test]
async fn owner_input_joins_the_successor_before_reusing_the_workspace() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.successor_gate = Some(Arc::new(Notify::new()));
    let lane = successors(ports, /*max_sessions*/ 2, &["must never be written"]).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "failed").await;
    lane.wait_for("succeeding").await;
    lane.runtime.turn_started().await;
    lane.write_answer("new owner work");
    assert_eq!(
        std::fs::read_to_string(lane.workspace.join("answer.txt")).unwrap(),
        "new owner work"
    );
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    let budget: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!((budget.launches, budget.pending), (1, None));
}

#[tokio::test]
async fn rejected_admission_clears_pending_without_refunding_or_claiming_a_rollout() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.successor_rejection = Some("owner authorization incomplete".into());
    let lane = successors(ports, 2, &[]).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("original", "failed").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "infrastructure");
    assert!(lane.ports.successor_packets.lock().unwrap().is_empty());
    let budget: Budget = lane
        .ledger
        .record(KIND, &lane.thread_id.to_string())
        .await
        .unwrap()
        .unwrap();
    assert_eq!((budget.launches, budget.pending), (1, None));
    assert!(
        lane.ledger
            .experiments()
            .await
            .unwrap()
            .iter()
            .any(|r| r.event.body["phase"] == "successor_rejected")
    );
}
