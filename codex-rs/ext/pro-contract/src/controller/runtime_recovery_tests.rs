//! Controller integration tests: rebuild the runtime over the same persistent institution.

use std::sync::Arc;

use pretty_assertions::assert_eq;

use super::CONTRACT_DRAFT;
use super::FakePorts;
use super::INTAKE;
use super::Lane;
use super::STATUS_KIND;
use super::SUPPORT_REVIEW;
use super::Stores;
use super::ThreadRuntime;
use super::lane;
use crate::StepOutcome;

async fn restart(lane: &mut Lane) {
    lane.runtime.stop().await;
    let old = &lane.runtime;
    let runtime = Arc::new(ThreadRuntime::new(
        lane.thread_id,
        old.settings.clone(),
        old.profile.clone(),
        old.policies.clone(),
        Stores {
            dir: old.dir.clone(),
            ledger: old.ledger.clone(),
            store: old.store.clone(),
        },
        old.ports.clone(),
    ));
    runtime.restore().await;
    lane.runtime = runtime;
}

#[tokio::test]
async fn supported_contract_restores_and_verifies_a_new_handoff_without_redrafting() {
    let mut lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    let status = lane.wait_for("supported").await;
    let contract = lane.contract().await;
    let events = lane.ledger.events().await.unwrap();
    let base = lane.runtime.work_dir().join("base/answer.txt");
    std::fs::write(&base, "tampered scratch copy").unwrap();
    restart(&mut lane).await;
    assert_eq!(std::fs::read_to_string(base).unwrap(), "not yet");
    assert_eq!(lane.status().await, Some(status));
    assert_eq!(lane.contract().await, contract);
    assert_eq!(lane.ledger.events().await.unwrap(), events);
    assert!(lane.runtime.brief().await.is_some());
    lane.runtime
        .intake("Do not issue another contract".to_string())
        .await;
    lane.executor_turn("second", "done").await;
    lane.wait_for("supported").await;
    assert_eq!(lane.ports.draft_prompts.lock().unwrap().len(), 1);
    assert_eq!(lane.contract().await.unwrap().generation, 2);
    assert_eq!(*lane.ports.checked.lock().unwrap(), vec!["done", "done"]);
}

#[tokio::test]
async fn interrupted_repair_is_not_replayed_or_refunded() {
    let mut lane =
        lane(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail, StepOutcome::Fail])).await;
    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "almost").await;
    let repairing = lane.wait_for("repairing").await;
    restart(&mut lane).await;
    let restored = lane.status().await.unwrap();
    assert_eq!(
        (
            restored.contract_id,
            restored.repairs_used,
            restored.phase.as_str()
        ),
        (repairing.contract_id, 1, "not_verified")
    );
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
    lane.executor_turn("next-human-turn", "still not").await;
    let failed = lane.wait_for("did_not_pass").await;
    assert_eq!(failed.repairs_used, 1);
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn accepted_defeat_consumes_allowance_even_with_stale_status() {
    let mut lane =
        lane(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail, StepOutcome::Fail])).await;
    lane.runtime.intake(INTAKE.to_string()).await;
    let before_repair = lane.wait_for("working").await;
    lane.executor_turn("first", "almost").await;
    lane.wait_for("repairing").await;
    lane.ledger
        .put_record(STATUS_KIND, &lane.thread_id.to_string(), &before_repair)
        .await
        .unwrap();
    restart(&mut lane).await;
    assert_eq!(lane.status().await.unwrap().repairs_used, 1);
    lane.executor_turn("second", "still not").await;
    lane.wait_for("did_not_pass").await;
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn changed_capture_policy_blocks_recovery_without_erasing_responsibility() {
    let mut lane = lane(FakePorts::new(CONTRACT_DRAFT)).await;
    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    let contract = lane.contract().await.unwrap();
    lane.runtime.stop().await;
    Arc::get_mut(&mut lane.runtime)
        .expect("no active worker")
        .profile
        .excluded_paths
        .push("answer.txt".to_string());
    restart(&mut lane).await;
    assert_eq!(lane.contract().await, Some(contract.clone()));
    let blocked = lane.status().await.unwrap();
    assert_eq!(
        (
            blocked.contract_id,
            blocked.phase.as_str(),
            blocked.class.as_str()
        ),
        (Some(contract.id.0), "not_verified", "infrastructure")
    );
    lane.runtime.intake(INTAKE.to_string()).await;
    lane.executor_turn("must-not-verify", "done").await;
    assert!(lane.ports.checked.lock().unwrap().is_empty());
    assert_eq!(lane.ports.draft_prompts.lock().unwrap().len(), 1);
}
