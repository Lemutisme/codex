use super::*;
use crate::controller::archive::{Operation, Query};
use crate::{ProgressSettings, SuccessionSettings};
use pretty_assertions::{assert_eq, assert_ne};

#[tokio::test]
async fn publication_caller_loss_does_not_abandon_the_owned_assessment() {
    let gate = Arc::new(Notify::new());
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.review_gate = Some(Arc::clone(&gate));
    let lane = progressing(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let runtime = Arc::clone(&lane.runtime);
    let caller = tokio::spawn(async move {
        runtime
            .publish_progress_with_review("lost-caller".into(), "one".into(), None, true)
            .await
    });
    let until = tokio::time::Instant::now() + Duration::from_secs(5);
    while lane.ports.review_prompts.lock().unwrap().is_empty() {
        assert!(tokio::time::Instant::now() < until);
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    caller.abort();
    let _ = caller.await;
    gate.notify_one();
    loop {
        if lane.runtime.progress_ready().await.is_ok() {
            break;
        }
        assert!(tokio::time::Instant::now() < until);
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    let receipt = lane
        .runtime
        .publish_progress_with_review("lost-caller".into(), "one".into(), None, true)
        .await
        .unwrap();
    assert_eq!(receipt["reused"], true);
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    assert_eq!(
        lane.runtime.remaining_task_budget().await.unwrap()["publications_used"],
        1
    );
}

#[tokio::test]
async fn abort_without_a_deadline_retains_responsibility_and_a_stale_abort_cannot_stop_new_work() {
    let mut lane = progressing(FakePorts::new(CONTRACT_DRAFT)).await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .succession
        .as_mut()
        .unwrap()
        .total_secs = None;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let original = lane.runtime.remaining_task_budget().await.unwrap();
    let old = lane.runtime.turn_started().await;
    let current = lane.runtime.turn_started().await;
    lane.runtime.turn_aborted(old).await;
    assert!(!lane.status().await.unwrap().resting);
    lane.runtime.turn_aborted(current).await;
    let stopped = lane.wait_for("not_verified").await;
    assert_eq!(stopped.class, "no_handoff");
    assert_eq!(
        lane.contract().await.unwrap().standing,
        codex_pro_contract::Standing::Outstanding
    );
    lane.runtime.turn_started().await;
    lane.wait_for("working").await;
    assert_eq!(
        lane.runtime.remaining_task_budget().await.unwrap()["started_ms"],
        original["started_ms"]
    );
    assert_eq!(lane.ledger.events().await.unwrap().len(), 1);
}

#[tokio::test]
async fn progress_and_recovery_do_not_require_succession_or_a_finite_task_lifetime() {
    let mut lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    let runtime = Arc::get_mut(&mut lane.runtime).unwrap();
    runtime.settings.succession = None;
    runtime.settings.progress.as_mut().unwrap().assessment_secs = 5;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let before = lane.runtime.remaining_task_budget().await.unwrap();
    assert!(before["deadline_ms"].is_null());
    assert!(before["remaining_ms"].is_null());
    assert_eq!(before["session_limit"], 0);
    let result = lane
        .runtime
        .publish_progress("work".into(), "turn".into())
        .await
        .unwrap();
    assert_eq!(result["completion_certified"], false);
    lane.runtime.restore().await;
    assert_eq!(
        lane.runtime
            .publish_progress("work".into(), "turn".into())
            .await
            .unwrap()["handle"],
        result["handle"]
    );
    let after = lane.runtime.remaining_task_budget().await.unwrap();
    assert_eq!(before["started_ms"], after["started_ms"]);
    assert!(after["deadline_ms"].is_null());
    assert_eq!(after["publications_used"], 1);
    assert_eq!(lane.ledger.events().await.unwrap().len(), 1);
}

#[tokio::test]
async fn diagnostic_checkpoints_survive_timeout_and_continue_without_replaying_unchanged_checks() {
    use super::super::ProgressAssessment;
    let lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&["CHECKPOINT_TIMEOUT", SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let budget = lane.runtime.remaining_task_budget().await.unwrap();
    let request = ProgressAssessment {
        review: true,
        question: Some("Does answer.txt match the requested content?".into()),
        assessment_secs: Some(360),
        ..Default::default()
    };
    let first = lane
        .runtime
        .publish_assessment(
            "diagnose".into(),
            "working-turn".into(),
            None,
            request.clone(),
        )
        .await
        .unwrap();
    assert_eq!(first["review_available"], false);
    assert_eq!(first["completion_certified"], false);
    assert_eq!(first["review_checkpoints"].as_array().unwrap().len(), 1);
    let checkpoint = serde_json::from_value(first["review_checkpoints"][0].clone()).unwrap();
    let archived = lane
        .runtime
        .evidence_access()
        .read(
            Query {
                op: Operation::Read,
                handle: Some(checkpoint),
                offset: 0,
            },
            8192,
        )
        .await
        .unwrap();
    assert!(
        archived["text"]
            .as_str()
            .unwrap()
            .contains("not yet differs from ready")
    );
    assert!(lane.contract().await.unwrap().candidate.is_none());
    assert!(lane.ports.review_deadlines.lock().unwrap()[0] > Duration::from_secs(120));
    let retry = lane
        .runtime
        .publish_assessment(
            "diagnose".into(),
            "working-turn".into(),
            None,
            request.clone(),
        )
        .await
        .unwrap();
    assert_eq!(retry["handle"], first["handle"]);
    assert_eq!(lane.ports.review_deadlines.lock().unwrap().len(), 1);
    let mut changed_request = request.clone();
    changed_request.question = Some("A different question".into());
    assert!(
        lane.runtime
            .publish_assessment(
                "diagnose".into(),
                "working-turn".into(),
                None,
                changed_request
            )
            .await
            .is_err()
    );

    let mut continuation = request.clone();
    continuation.continue_from = Some(serde_json::from_value(first["handle"].clone()).unwrap());
    let second = lane
        .runtime
        .publish_assessment(
            "continue".into(),
            "working-turn".into(),
            None,
            continuation.clone(),
        )
        .await
        .unwrap();
    assert_eq!(second["checks_reused"], true);
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    assert!(
        lane.ports
            .review_contexts
            .lock()
            .unwrap()
            .iter()
            .any(|v| v["checkpoints"].as_array().is_some_and(|a| !a.is_empty()))
    );
    assert!(
        lane.ports
            .review_contexts
            .lock()
            .unwrap()
            .iter()
            .any(|v| v["question"] == "Does answer.txt match the requested content?")
    );
    lane.write_answer("ready");
    continuation.continue_from = Some(checkpoint);
    let third = lane
        .runtime
        .publish_assessment(
            "new-version".into(),
            "working-turn".into(),
            None,
            continuation,
        )
        .await
        .unwrap();
    assert_ne!(first["subject_hash"], third["subject_hash"]);
    assert_eq!(third["checks_reused"], false);
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 2);
    assert_eq!(
        lane.runtime.remaining_task_budget().await.unwrap()["deadline_ms"],
        budget["deadline_ms"]
    );
    assert!(lane.contract().await.unwrap().candidate.is_none());
}

#[tokio::test]
async fn diagnosis_cannot_import_arbitrary_handles_or_extend_the_original_grant() {
    use super::super::ProgressAssessment;
    let lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let arbitrary = lane
        .runtime
        .store
        .put(br#"{"kind":"review_checkpoint_v1"}"#)
        .unwrap();
    let invalid = ProgressAssessment {
        review: true,
        continue_from: Some(arbitrary),
        ..Default::default()
    };
    assert!(
        lane.runtime
            .publish_assessment("foreign".into(), "turn".into(), None, invalid)
            .await
            .is_err()
    );
    assert_eq!(
        lane.runtime.remaining_task_budget().await.unwrap()["publications_used"],
        0
    );
    let request = ProgressAssessment {
        review: true,
        assessment_secs: Some(u64::MAX),
        ..Default::default()
    };
    // A current root cannot borrow a successor owner token. Test the actual parent
    // clamp by shortening the original grant's deadline in this isolated fixture.
    let mut budget: crate::controller::succession_budget::Budget = lane
        .ledger
        .record(
            crate::controller::succession_budget::KIND,
            &lane.thread_id.to_string(),
        )
        .await
        .unwrap()
        .unwrap();
    let old = budget.clone();
    budget.grant.total_secs = Some(40);
    let deadline = budget.started_ms + 40_000;
    budget.deadline_ms = Some(deadline);
    assert!(
        lane.ledger
            .compare_exchange_record(
                crate::controller::succession_budget::KIND,
                &lane.thread_id.to_string(),
                Some(&old),
                &budget
            )
            .await
            .unwrap()
    );
    lane.runtime
        .publish_assessment("bounded".into(), "turn".into(), None, request)
        .await
        .unwrap();
    assert!(lane.ports.review_deadlines.lock().unwrap()[0] <= Duration::from_secs(40));
    assert_eq!(
        lane.runtime.remaining_task_budget().await.unwrap()["deadline_ms"],
        deadline
    );
}

async fn progressing(ports: FakePorts) -> Lane {
    let mut lane = lane(ports).await;
    let runtime = Arc::get_mut(&mut lane.runtime).unwrap();
    runtime.settings.succession = Some(SuccessionSettings {
        max_sessions: Some(1),
        total_secs: Some(3600),
    });
    runtime.settings.progress = Some(ProgressSettings {
        executor_label: "procontract.task=test".into(),
        max_publications: Some(3),
        assessment_secs: 120,
        executor_slice_secs: Some(1800),
    });
    lane
}

#[tokio::test]
async fn requested_diagnosis_survives_failed_checks_and_cannot_be_replaced_by_cached_checks() {
    let lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Fail])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let checks = lane
        .runtime
        .publish_progress("checks".into(), "working-turn".into())
        .await
        .unwrap();
    assert!(lane.ports.review_prompts.lock().unwrap().is_empty());
    assert!(
        lane.runtime
            .publish_progress_with_review("checks".into(), "working-turn".into(), None, true)
            .await
            .is_err()
    );
    let diagnosis = lane
        .runtime
        .publish_progress_with_review("diagnosis".into(), "working-turn".into(), None, true)
        .await
        .unwrap();
    assert_ne!(checks["handle"], diagnosis["handle"]);
    assert_eq!(diagnosis["review_available"], true);
    assert_eq!(diagnosis["completion_certified"], false);
    assert_eq!(lane.ports.review_prompts.lock().unwrap().len(), 1);
    let repeated = lane
        .runtime
        .publish_progress_with_review("diagnosis".into(), "working-turn".into(), None, true)
        .await
        .unwrap();
    assert_eq!(repeated["handle"], diagnosis["handle"]);
    assert_eq!(lane.ports.review_prompts.lock().unwrap().len(), 1);
    let handle = serde_json::from_value(diagnosis["handle"].clone()).unwrap();
    let document: serde_json::Value =
        serde_json::from_slice(&lane.runtime.store.get(&handle).unwrap()).unwrap();
    assert_eq!(
        document["public"]["checks"][0]["receipt"]["outcome"],
        "fail"
    );
    assert!(document["public"]["review"].is_object());
    let observations =
        serde_json::from_value(document["public"]["host_observations"].clone()).unwrap();
    let observed: serde_json::Value =
        serde_json::from_slice(&lane.runtime.store.get(&observations).unwrap()).unwrap();
    assert!(
        observed["delivery"].is_null(),
        "a progress snapshot is not a final-response delivery"
    );
    lane.wait_for("working").await;
}

#[tokio::test]
async fn publications_without_a_count_ceiling_still_share_one_original_deadline() {
    let mut lane = progressing(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Pass])).await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .profile
        .check
        .build_command = Some("host check".into());
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .settings
        .progress
        .as_mut()
        .unwrap()
        .max_publications = None;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let before = lane.runtime.remaining_task_budget().await.unwrap();
    for index in 0..10 {
        lane.runtime
            .publish_progress(format!("snapshot-{index}"), "working-turn".into())
            .await
            .unwrap();
    }
    let after = lane.runtime.remaining_task_budget().await.unwrap();
    assert_eq!(before["deadline_ms"], after["deadline_ms"]);
    assert_eq!(after["publications_used"], 10);
    assert!(after["publication_limit"].is_null());
}

#[tokio::test]
async fn feedback_access_is_bound_to_completed_native_call_and_frozen_before_handoff() {
    use crate::controller::observations::AccessOutcome;
    let lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let publication = lane
        .runtime
        .publish_progress("initial".into(), "root-turn".into())
        .await
        .unwrap();
    let handle = serde_json::from_value(publication["handle"].clone()).unwrap();
    let access = lane.runtime.evidence_access();
    let caller = serde_json::json!({"executor":lane.thread_id.to_string(),"turn":"root-turn","invocation":"read-1"});
    let query = || Query {
        op: Operation::Read,
        handle: Some(handle),
        offset: 0,
    };
    let response = access
        .read_observed(query(), 8192, caller.clone())
        .await
        .unwrap();
    assert_eq!(response["handle"], publication["handle"]);
    access
        .finish_access(caller, AccessOutcome::Completed)
        .await
        .unwrap();
    let unfinished = serde_json::json!({"executor":lane.thread_id.to_string(),"turn":"root-turn","invocation":"read-2"});
    access
        .read_observed(query(), 8192, unfinished.clone())
        .await
        .unwrap();
    // A new access object (as on restart) cannot infer completion of the earlier call.
    lane.runtime
        .evidence_access()
        .finish_access(unfinished.clone(), AccessOutcome::Completed)
        .await
        .unwrap();
    lane.executor_turn("delivered", "ready").await;
    lane.wait_for("supported").await;
    let events = lane.ledger.experiments().await.unwrap();
    let verification = events
        .iter()
        .find(|r| r.event.kind == ExperimentKind::Verification)
        .unwrap();
    let public_handle =
        serde_json::from_value(verification.event.body["public_evidence"].clone()).unwrap();
    let public: serde_json::Value =
        serde_json::from_slice(&lane.runtime.store.get(&public_handle).unwrap()).unwrap();
    let context_handle = serde_json::from_value(public["host_observations"].clone()).unwrap();
    let frozen = lane.runtime.store.get(&context_handle).unwrap();
    let context: serde_json::Value = serde_json::from_slice(&frozen).unwrap();
    assert_eq!(context["delivery"]["receipt"], context["capture_receipt"]);
    assert_eq!(context["delivery"]["subject_hash"], context["subject_hash"]);
    assert_eq!(context["delivery"]["turn_id"], "delivered");
    let capture = events
        .iter()
        .find(|event| serde_json::json!(event.hash) == context["capture_receipt"])
        .unwrap();
    assert_eq!(
        context["delivery"]["response_capture"],
        capture.event.body["response"]
    );
    assert_eq!(context["feedback_access"][0]["outcome"], "completed");
    assert_eq!(context["feedback_access"][1]["outcome"], "unknown");
    assert_eq!(
        context["feedback_access"][0]["returned_bytes_sha256"],
        serde_json::json!(Digest::of(response["text"].as_str().unwrap().as_bytes()))
    );
    access
        .finish_access(unfinished, AccessOutcome::Completed)
        .await
        .unwrap();
    assert_eq!(lane.runtime.store.get(&context_handle).unwrap(), frozen);
    let (contract, terms, base, subject, epoch) = {
        let state = lane.runtime.state.lock().await;
        let active = state.contract.as_ref().unwrap();
        (
            active.contract.clone(),
            active.terms.clone(),
            active.base.subject,
            state.frozen.as_ref().unwrap().subject.clone(),
            state.epoch,
        )
    };
    let binding = lane.ledger.subject_binding(&base).await.unwrap().unwrap();
    let baseline =
        codex_pro_contract_store::load_subject(&lane.runtime.store, &binding.manifest, &base)
            .unwrap();
    let rebuilt = crate::controller::observations::snapshot(
        &lane.ledger,
        &lane.runtime.store,
        crate::controller::observations::AssessmentScope {
            contract: &contract,
            terms: &terms,
            subject: &subject,
            baseline: &baseline,
            owner_thread: &lane.thread_id.to_string(),
            turn: "delivered",
            epoch,
            capture: crate::controller::observations::CaptureKind::Delivery,
        },
    )
    .await
    .unwrap();
    assert_eq!(
        rebuilt, context,
        "late completion entered the earlier capture prefix"
    );
    assert_eq!(
        lane.ledger
            .record::<u32>("evidence_access_budget_v1", &lane.runtime.contract_id().0)
            .await
            .unwrap(),
        Some(2)
    );
    assert_eq!(lane.ledger.events().await.unwrap().len(), 3); // Issue, Propose, Support only.
    let first = lane.contract().await.unwrap().support.unwrap().coordinate;
    lane.executor_turn("same-artifact-new-history", "ready")
        .await;
    lane.wait_for("supported").await;
    let second = lane.contract().await.unwrap().support.unwrap().coordinate;
    assert_eq!(first.subject_hash, second.subject_hash);
    assert_ne!(
        first.basis, second.basis,
        "different execution history shared an incomplete source basis"
    );
}

#[tokio::test]
async fn publication_retains_feedback_without_proposing_and_reuses_identical_work() {
    let mut lane = progressing(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Fail, StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW, SUPPORT_REVIEW]),
    )
    .await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .profile
        .check
        .build_command = Some("host check".into());
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
