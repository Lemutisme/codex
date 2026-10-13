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
        max_sessions,
        total_secs: 3600,
    });
    *lane.ports.successor_workspace.lock().unwrap() = Some(lane.workspace.clone());
    *lane.ports.successor_answers.lock().unwrap() = answers
        .iter()
        .map(std::string::ToString::to_string)
        .collect();
    lane
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
    assert_eq!(second["original_task"], INTAKE);
    assert_eq!(
        second["remaining_failures_and_prior_failed_artifacts"]
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
