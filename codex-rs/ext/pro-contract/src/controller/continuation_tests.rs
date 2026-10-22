use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn choose(ports: &FakePorts, action: &str, requirements: serde_json::Value) {
    ports.continuation_choices.lock().unwrap().push_back(json!({
        "action":action,"requirements":requirements,"next_step":"Inspect the retained output with the available tools."
    }).to_string());
}

#[tokio::test]
async fn interrupted_strategy_selection_keeps_the_assessment_and_spends_no_execution() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[CANNOT_JUDGE_REVIEW]);
    ports
        .continuation_choices
        .lock()
        .unwrap()
        .push_back("INTERRUPTED".into());
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "execution_interrupted");
    assert_eq!(status.repairs_used, 0);
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    assert!(lane.contract().await.unwrap().candidate.is_some());
    assert_eq!(lane.ledger.events().await.unwrap().len(), 2);
}

#[tokio::test]
async fn a_later_choice_sees_the_prior_intention_and_observation_capability() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass, StepOutcome::Pass])
        .reviews(&[CANNOT_JUDGE_REVIEW, CANNOT_JUDGE_REVIEW]);
    choose(&ports, "resume", json!(["R1"]));
    choose(&ports, "rest", json!([]));
    let mut lane = lane(ports).await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .repair_attempts = 2;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .profile
        .check
        .build_command = Some("observe-answer".into());
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    lane.wait_for("repairing").await;
    lane.executor_turn("second", "done").await;
    lane.wait_for("not_verified").await;
    let facts: serde_json::Value = {
        let prompts = lane.ports.continuation_prompts.lock().unwrap();
        serde_json::from_str(prompts[1].rsplit_once("\n\n").unwrap().1).unwrap()
    };
    assert_eq!(facts["previous_choice"]["choice"]["action"], "resume");
    assert_eq!(
        facts["previous_choice"]["choice"]["requirements"],
        json!(["R1"])
    );
    assert!(facts["previous_choice"]["public_evidence"].is_string());
    assert_eq!(
        facts["capabilities"]["public_checks"][0]["command"],
        "observe-answer"
    );
    assert!(facts["capabilities"]["host_observation_scope"]["limits"].is_array());
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
    assert_eq!(lane.runtime.state.lock().await.repairs_used, 1);
}

#[tokio::test]
async fn evidence_gap_can_continue_without_manufacturing_a_defeat_or_new_issue() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass, StepOutcome::Pass])
        .reviews(&[CANNOT_JUDGE_REVIEW, SUPPORT_REVIEW]);
    choose(&ports, "resume", json!(["R1"]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    lane.wait_for("repairing").await;
    let contract = lane.contract().await.unwrap();
    assert!(contract.candidate.is_some());
    assert!(contract.support.is_none());
    assert!(
        lane.ports.repairs.lock().unwrap()[0]
            .0
            .contains("the output is not visible")
    );
    lane.executor_turn("second", "done").await;
    lane.wait_for("supported").await;
    let events = lane.ledger.events().await.unwrap();
    let commands: Vec<_> = events.iter().map(|e| e.command.command.kind()).collect();
    assert_eq!(
        commands,
        vec![
            codex_pro_contract::CommandKind::Issue,
            codex_pro_contract::CommandKind::Propose,
            codex_pro_contract::CommandKind::Propose,
            codex_pro_contract::CommandKind::Support
        ]
    );
    assert_eq!(lane.ports.continuation_prompts.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn strategy_can_rest_after_a_real_defect_without_spending_a_local_attempt() {
    let ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    choose(&ports, "rest", json!([]));
    let mut lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "almost").await;
    let status = lane.wait_for("did_not_pass").await;
    assert_eq!(status.repairs_used, 0);
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    super::recovery_tests::restart(&mut lane).await;
    assert_eq!(lane.status().await.unwrap().repairs_used, 0);
    assert!(lane.contract().await.unwrap().candidate.is_none());
}

#[tokio::test]
async fn unresolved_work_reservation_survives_restart_without_a_defeat() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[CANNOT_JUDGE_REVIEW]);
    choose(&ports, "resume", json!(["R1"]));
    let mut lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    lane.wait_for("repairing").await;
    // Simulate an older status write surviving a crash after durable reservation.
    let mut status = lane.status().await.unwrap();
    status.repairs_used = 0;
    lane.ledger
        .put_record(STATUS_KIND, &lane.thread_id.to_string(), &status)
        .await
        .unwrap();
    super::recovery_tests::restart(&mut lane).await;
    assert_eq!(lane.runtime.state.lock().await.repairs_used, 1);
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
    assert!(lane.contract().await.unwrap().support.is_none());
}

#[tokio::test]
async fn a_strategy_cannot_select_an_obligation_with_a_genuine_scope_dispute() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false},{"id":"R2","text":"An extra goal","source_quote":"make answer.txt say done","inferred":true}],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
    const REVIEW: &str = r#"{"assessments":[{"requirement_id":"R1","observations":"","judgment":{"status":"unresolved","missing":"Need to inspect output."}}],"terms_gap":[{"element":"extra goal","reason":"The request only asks for answer.txt; it does not require the extra goal.","affected_requirements":["R2"],"discrepancy":{"kind":"added","request_quote":null}}]}"#;
    let ports = FakePorts::new(DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[REVIEW]);
    choose(&ports, "resume", json!(["R2"]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "terms_gap");
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    let prompt = lane.ports.continuation_prompts.lock().unwrap()[0].clone();
    let facts: serde_json::Value =
        serde_json::from_str(prompt.rsplit_once("\n\n").unwrap().1).unwrap();
    assert_eq!(facts["allowed_requirements"], json!(["R1"]));
}

#[tokio::test]
async fn owner_input_fences_a_pending_strategy_selection() {
    let gate = Arc::new(Notify::new());
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[CANNOT_JUDGE_REVIEW]);
    ports.continuation_gate = Some(gate.clone());
    choose(&ports, "resume", json!(["R1"]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    lane.wait_for("deciding").await;
    lane.runtime.turn_started().await;
    gate.notify_one();
    tokio::time::sleep(Duration::from_millis(25)).await;
    lane.runtime.stop().await;
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    assert_eq!(lane.runtime.state.lock().await.repairs_used, 0);
}
