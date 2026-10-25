use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

fn choose(ports: &FakePorts, action: &str, requirements: serde_json::Value) {
    let choice = if action == "rest" {
        json!({"action":"rest","reason":"No useful work selected."})
    } else {
        json!({"action":action,"requirements":requirements,"next_step":"Inspect the retained output with the available tools."})
    };
    ports
        .continuation_choices
        .lock()
        .unwrap()
        .push_back(json!({"choice":choice}).to_string());
}

fn observe(ports: &FakePorts, action: &str) {
    let choice = if action == "diagnose" {
        json!({"action":"diagnose","question":"Does the retained artifact satisfy R1?"})
    } else {
        json!({"action":action,"reason":"Reassess the same retained work using another observation."})
    };
    ports
        .continuation_choices
        .lock()
        .unwrap()
        .push_back(json!({"choice":choice}).to_string());
}

#[tokio::test]
async fn late_submission_outcomes_cannot_replace_a_new_owner_turn_status() {
    for error in [None, Some("late submission rejection".to_string())] {
        let gate = Arc::new(Notify::new());
        let mut ports = FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[CANNOT_JUDGE_REVIEW]);
        ports.repair_gate = Some(gate.clone());
        ports.repair_error = error;
        choose(&ports, "resume", json!(["R1"]));
        let lane = lane(ports).await;
        lane.runtime.intake(INTAKE.into()).await;
        lane.wait_for("working").await;
        lane.executor_turn("first", "done").await;
        tokio::time::timeout(Duration::from_secs(5), async {
            while lane.ports.repairs.lock().unwrap().is_empty() {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        })
        .await
        .unwrap();
        lane.runtime.turn_started().await;
        lane.runtime
            .record_status("working", "new owner turn", false)
            .await;
        let expected = lane.status().await;
        gate.notify_one();
        let mut tasks = std::mem::take(&mut *lane.runtime.tasks.lock().unwrap());
        while let Some(result) = tasks.join_next().await {
            result.unwrap();
        }
        assert_eq!(
            lane.status().await,
            expected,
            "old acknowledgement is historical, not the current disposition"
        );
        assert_eq!(
            lane.runtime.state.lock().await.phase,
            super::super::Phase::Working
        );
        let journal = lane.ledger.experiments().await.unwrap();
        assert_eq!(
            journal
                .iter()
                .filter(|r| r.event.body["phase"] == "continuation_submission")
                .count(),
            1
        );
        assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
        assert_eq!(
            lane.status().await.unwrap().repairs_used,
            1,
            "a superseded result does not refund the original admission"
        );
    }
}

#[tokio::test]
async fn selected_verification_after_defeat_uses_current_responsibility() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Fail, StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    observe(&ports, "verify");
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("delivery", "done").await;
    lane.wait_for("supported").await;
    let commands: Vec<_> = lane
        .ledger
        .events()
        .await
        .unwrap()
        .into_iter()
        .map(|e| e.command.command.kind())
        .collect();
    use codex_pro_contract::CommandKind::*;
    assert_eq!(commands, vec![Issue, Propose, Defeat, Propose, Support]);
    let prompts = lane.ports.continuation_prompts.lock().unwrap();
    let facts: serde_json::Value =
        serde_json::from_str(prompts[0].rsplit_once("\n\n").unwrap().1).unwrap();
    assert_eq!(facts["responsibility"]["version"], 3);
    assert_eq!(facts["responsibility"]["generation"], 2);
    assert!(facts["responsibility"]["candidate"].is_null());
    assert_eq!(facts["assessment"]["generation"], 1);
    let public: serde_json::Value = serde_json::from_slice(
        &lane
            .runtime
            .store
            .get(&serde_json::from_value(facts["public_evidence"].clone()).unwrap())
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        public["generation"], 1,
        "advancing responsibility must not rewrite historical evidence"
    );
}

#[tokio::test]
async fn local_observations_after_defeat_preserve_work_for_selected_verification() {
    for interrupted in [false, true] {
        for action in ["check", "diagnose"] {
            let ports = FakePorts::new(CONTRACT_DRAFT)
                .checks(&[StepOutcome::Fail, StepOutcome::Pass, StepOutcome::Pass])
                .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]);
            if interrupted {
                observe(&ports, "verify");
            }
            observe(&ports, action);
            observe(&ports, "verify");
            let lane = lane(ports).await;
            lane.runtime.intake(INTAKE.into()).await;
            lane.wait_for("working").await;
            if interrupted {
                lane.runtime.turn_started().await;
                lane.write_answer("done");
                lane.runtime.turn_stopped("interrupted".into()).await;
                lane.runtime.thread_idle(ThreadIdleCause::Failed).await;
            } else {
                lane.executor_turn("delivery", "done").await;
            }
            lane.wait_for("supported").await;
            let events = lane.ledger.events().await.unwrap();
            let commands: Vec<_> = events.iter().map(|e| e.command.command.kind()).collect();
            use codex_pro_contract::CommandKind::*;
            assert_eq!(
                commands,
                vec![Issue, Propose, Defeat, Propose, Support],
                "{interrupted}/{action}"
            );
            let subject = lane
                .contract()
                .await
                .unwrap()
                .candidate
                .unwrap()
                .subject_hash;
            let journal = lane.ledger.experiments().await.unwrap();
            let observations: Vec<_> = journal
                .iter()
                .filter(|r| r.event.body["phase"] == "work_assessed")
                .collect();
            assert_eq!(observations.len(), 1);
            assert_eq!(
                observations[0].event.body["generation"], 2,
                "local observation does not propose"
            );
            assert_eq!(observations[0].event.body["subject_hash"], json!(subject));
            assert!(lane.ports.repairs.lock().unwrap().is_empty());
        }
    }
}

#[tokio::test]
async fn resting_after_defeat_does_not_create_another_proposal() {
    let ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    choose(&ports, "rest", json!([]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("delivery", "done").await;
    lane.wait_for("did_not_pass").await;
    let contract = lane.contract().await.unwrap();
    assert_eq!(contract.version, 3);
    assert!(contract.candidate.is_none());
    assert_eq!(lane.ledger.events().await.unwrap().len(), 3);
}

#[tokio::test]
async fn repeated_defeats_retire_only_their_proposals_without_losing_the_artifact() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Fail, StepOutcome::Fail, StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    observe(&ports, "verify");
    observe(&ports, "verify");
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("delivery", "done").await;
    lane.wait_for("supported").await;
    let contract = lane.contract().await.unwrap();
    assert_eq!(contract.version, 7);
    assert_eq!(contract.generation, 5);
    let journal = lane.ledger.experiments().await.unwrap();
    let verifications: Vec<_> = journal
        .iter()
        .filter(|r| r.event.kind == ExperimentKind::Verification)
        .collect();
    assert_eq!(
        verifications
            .iter()
            .map(|r| r.event.body["generation"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        vec![1, 3, 5]
    );
    for event in verifications {
        assert_eq!(
            event.event.body["subject_hash"],
            json!(contract.candidate.unwrap().subject_hash)
        );
    }
    assert_eq!(
        *lane.ports.checked.lock().unwrap(),
        vec!["done", "done", "done"]
    );
}

#[tokio::test]
async fn root_failure_during_preparation_retains_work_for_strategy_without_a_delivery() {
    let gate = Arc::new(Notify::new());
    let mut ports = FakePorts::new(CONTRACT_DRAFT);
    ports.draft_gate = Some(gate.clone());
    choose(&ports, "rest", json!([]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("drafting").await;
    lane.runtime.turn_started().await;
    lane.write_answer("partial work");
    lane.runtime.turn_stopped("failed-root".into()).await;
    lane.runtime.thread_idle(ThreadIdleCause::Failed).await;
    assert_eq!(lane.status().await.unwrap().phase, "drafting");
    assert!(!lane.status().await.unwrap().resting);
    gate.notify_one();
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "execution_interrupted");
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
    assert!(lane.ports.checked.lock().unwrap().is_empty());
    assert_eq!(
        lane.ledger.events().await.unwrap().len(),
        1,
        "capturing partial work must not Propose it"
    );
    let journal = lane.ledger.experiments().await.unwrap();
    assert!(
        !journal
            .iter()
            .any(|r| r.event.body["phase"] == "task_delivery")
    );
    assert!(
        journal
            .iter()
            .any(|r| r.event.body["phase"] == "interrupted_snapshot")
    );
    let handle = journal
        .iter()
        .find(|r| r.event.body["phase"] == "work_ready")
        .unwrap()
        .event
        .body["public_evidence"]
        .clone();
    let page = lane
        .runtime
        .evidence_access()
        .read(
            serde_json::from_value(json!({"op":"read", "handle":handle})).unwrap(),
            16384,
        )
        .await
        .unwrap();
    let retained: serde_json::Value = serde_json::from_str(page["text"].as_str().unwrap()).unwrap();
    assert_eq!(retained["assessment_scope"], "interruption");
    let prompts = lane.ports.continuation_prompts.lock().unwrap();
    let facts: serde_json::Value =
        serde_json::from_str(prompts[0].rsplit_once("\n\n").unwrap().1).unwrap();
    assert_eq!(facts["assessment"]["stage"], "interruption");
}

#[tokio::test]
async fn failed_root_can_select_local_work_without_an_extra_user_instruction() {
    let ports = FakePorts::new(CONTRACT_DRAFT);
    choose(&ports, "resume", json!(["R1"]));
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.runtime.turn_started().await;
    lane.write_answer("partial");
    lane.runtime.turn_stopped("failed-root".into()).await;
    lane.runtime.thread_idle(ThreadIdleCause::Failed).await;
    lane.wait_for("repairing").await;
    let repairs = lane.ports.repairs.lock().unwrap().clone();
    assert_eq!(repairs.len(), 1);
    assert_eq!(repairs[0].1, "failed-root");
    assert_eq!(lane.ledger.events().await.unwrap().len(), 1);
}

#[tokio::test]
async fn a_superseded_interruption_cannot_rest_or_dispatch_work_for_the_new_owner_turn() {
    let lane = lane(FakePorts::new(CONTRACT_DRAFT)).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let old_epoch = lane.runtime.turn_started().await;
    lane.write_answer("old partial work");
    lane.runtime.turn_stopped("old-failure".into()).await;
    lane.runtime.turn_started().await;
    Arc::clone(&lane.runtime)
        .select_interrupted("late failure".into(), old_epoch)
        .await;
    assert_eq!(lane.status().await.unwrap().phase, "working");
    assert!(lane.ports.continuation_prompts.lock().unwrap().is_empty());
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
}

#[tokio::test]
async fn known_exhaustion_retains_the_handoff_without_starting_a_selector() {
    let mut lane = lane(FakePorts::new(CONTRACT_DRAFT)).await;
    let path = lane._dirs.path().join("resources.json");
    let write = |remaining: u64| {
        std::fs::write(&path,json!({
        "schema":"task_resources/v1","allocation_id":"shared-task","observed_at":1.0,
        "model_requests":{"limit":1,"reserved":1-remaining,"remaining":remaining},"time":{"deadline":null}
    }).to_string()).unwrap()
    };
    write(1);
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .resource_snapshot = Some(path.clone());
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    write(0);
    lane.executor_turn("delivery", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(status.class, "budget_exhausted");
    assert!(lane.ports.handoff_prompts.lock().unwrap().is_empty());
    assert!(lane.ports.checked.lock().unwrap().is_empty());
    assert_eq!(lane.ledger.events().await.unwrap().len(), 2);
    assert!(lane.contract().await.unwrap().support.is_none());
}

#[tokio::test]
async fn a_handoff_can_rest_without_scheduling_checks_review_or_support() {
    let ports = FakePorts::new(CONTRACT_DRAFT);
    ports.handoff_choices.lock().unwrap().push_back(json!({"choice":{
        "action":"rest","reason":"Deliver the captured partial work; further information is unavailable."
    }}).to_string());
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("delivery", "partial work").await;
    lane.wait_for("not_verified").await;
    assert!(lane.ports.checked.lock().unwrap().is_empty());
    assert!(lane.ports.review_prompts.lock().unwrap().is_empty());
    assert_eq!(lane.ledger.events().await.unwrap().len(), 2);
    assert!(lane.contract().await.unwrap().support.is_none());
}

#[tokio::test]
async fn selected_checks_and_focused_diagnosis_reuse_receipts_without_acceptance() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.handoff_choices.lock().unwrap().push_back(
        json!({"choice":{
            "action":"check","reason":"Observe the public build first."
        }})
        .to_string(),
    );
    ports.continuation_choices.lock().unwrap().extend([
        json!({"choice":{"action":"diagnose","question":"Does the captured answer contain the requested text?"}}).to_string(),
        json!({"choice":{"action":"rest","reason":"Local observation delivered; no acceptance claim requested by this strategy."}}).to_string(),
    ]);
    let lane = reference_lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("delivery", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    assert!(
        lane.ports
            .sealed_checked
            .lock()
            .unwrap()
            .iter()
            .all(Vec::is_empty)
    );
    let mut observation_errors = Vec::new();
    for record in lane.ledger.experiments().await.unwrap() {
        if record.event.body["phase"] == "work_assessed" {
            let handle: Digest =
                serde_json::from_value(record.event.body["public_evidence"].clone()).unwrap();
            let document: serde_json::Value =
                serde_json::from_slice(&lane.runtime.store.get(&handle).unwrap()).unwrap();
            observation_errors.push(document["review_error"].clone());
        }
    }
    assert_eq!(
        lane.ports.review_prompts.lock().unwrap().len(),
        1,
        "{status:?}; {observation_errors:?}"
    );
    assert!(
        lane.ports.review_contexts.lock().unwrap().iter().any(
            |value| value["question"] == "Does the captured answer contain the requested text?"
        )
    );
    assert!(lane.contract().await.unwrap().support.is_none());
    assert_eq!(lane.ledger.events().await.unwrap().len(), 2);
    assert_eq!(
        lane.runtime
            .state
            .lock()
            .await
            .contract
            .as_ref()
            .unwrap()
            .policy
            .min_sealed_qualified,
        Some(4),
        "local observations must not relax the original acceptance policy"
    );
    let records = lane.ledger.experiments().await.unwrap();
    assert_eq!(
        records
            .iter()
            .filter(|r| r.event.body["phase"] == "work_assessed")
            .count(),
        2
    );
    assert!(
        !records
            .iter()
            .any(|r| r.event.kind == ExperimentKind::Verification)
    );
}

#[tokio::test]
async fn a_selected_check_can_guide_repair_before_formal_verification() {
    let ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Fail, StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.handoff_choices.lock().unwrap().push_back(
        json!({"choice":{
            "action":"check","reason":"Inspect the captured artifact."
        }})
        .to_string(),
    );
    let lane = lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "wrong").await;
    lane.wait_for("repairing").await;
    assert!(lane.ports.review_prompts.lock().unwrap().is_empty());
    lane.executor_turn("second", "done").await;
    lane.wait_for("supported").await;
    let commands: Vec<_> = lane
        .ledger
        .events()
        .await
        .unwrap()
        .iter()
        .map(|e| e.command.command.kind())
        .collect();
    assert_eq!(
        commands,
        vec![
            codex_pro_contract::CommandKind::Issue,
            codex_pro_contract::CommandKind::Propose,
            codex_pro_contract::CommandKind::Propose,
            codex_pro_contract::CommandKind::Support
        ]
    );
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
    lane.runtime
        .append_event(
            codex_pro_contract_store::ExperimentKind::Execution,
            None,
            json!({
                "phase":"successor_returned","continuation":codex_pro_contract::Digest::ZERO,
                "exit":"handoff","handoff_turn_id":"unrelated-turn"
            }),
        )
        .await
        .unwrap();
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
    let execution = &facts["previous_choice"]["execution_records"][0]["event"];
    assert_eq!(
        facts["previous_choice"]["execution_records"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(execution["phase"], "continuation_submission");
    assert_eq!(execution["submitted"], true);
    assert_eq!(
        execution["continuation"],
        facts["previous_choice"]["record"]
    );
    assert!(facts["previous_choice"]["delivery"].is_null());
    assert_eq!(facts["assessed_turn_id"], "second");
    assert_eq!(
        facts["capabilities"]["executor"]["actions"],
        json!(["resume"])
    );
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
async fn local_observations_do_not_erase_an_unrelated_scope_dispute() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false},{"id":"R2","text":"An extra goal","source_quote":"make answer.txt say done","inferred":true}],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
    const REVIEW: &str = r#"{"assessments":[{"requirement_id":"R1","observations":"","judgment":{"status":"unresolved","missing":"Need output."}}],"terms_gap":[{"element":"extra goal","reason":"Not requested.","affected_requirements":["R2"],"discrepancy":{"kind":"added","request_quote":null}}]}"#;
    const LOCAL: &str = r#"{"assessments":[{"requirement_id":"R1","observations":"Locally inspected.","judgment":{"status":"unresolved","missing":"Need another observation."}}],"terms_gap":[]}"#;
    for action in ["check", "diagnose"] {
        let ports = FakePorts::new(DRAFT)
            .checks(&[StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[REVIEW, LOCAL]);
        ports.handoff_choices.lock().unwrap().extend([
        json!({"choice":{"action":"verify","reason":"Establish the current assessment."}})
            .to_string(),
        json!({"choice":if action=="check" { json!({"action":"check","reason":"Observe the changed artifact."}) } else { json!({"action":"diagnose","question":"Inspect only R1."}) }}).to_string(),
    ]);
        choose(&ports, "resume", json!(["R1"]));
        choose(&ports, "resume", json!(["R2"]));
        let mut lane = lane(ports).await;
        Arc::get_mut(&mut lane.runtime)
            .unwrap()
            .settings
            .repair_attempts = 2;
        lane.runtime.intake(INTAKE.into()).await;
        lane.wait_for("working").await;
        lane.executor_turn("first", "done").await;
        lane.wait_for("repairing").await;
        lane.executor_turn("second", "done").await;
        lane.wait_for("not_verified").await;
        assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
        let prompts = lane.ports.continuation_prompts.lock().unwrap();
        let facts: serde_json::Value =
            serde_json::from_str(prompts.last().unwrap().rsplit_once("\n\n").unwrap().1).unwrap();
        assert_eq!(
            facts["assessment"]["stage"],
            if action == "check" {
                "checks"
            } else {
                "diagnosis"
            }
        );
        assert_eq!(facts["allowed_requirements"], json!(["R1"]));
    }
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
