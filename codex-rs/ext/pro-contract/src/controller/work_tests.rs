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
async fn unresolved_inspection_blocks_support_and_repair_while_retaining_the_local_review() {
    const DEFEAT: &str = r#"{"verdict":"defeat","coverage":[],"findings":[{"requirement_id":"R1","location":"answer.txt","counterexample":"wrong answer"}],"terms_gap":[],"missing":"","residual":"fix answer.txt"}"#;
    for (review, corrupt) in [(SUPPORT_REVIEW, false), (DEFEAT, false), (DEFEAT, true)] {
        let gate = Arc::new(Notify::new());
        let mut ports = FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[review]);
        ports.review_gate = Some(gate.clone());
        let mut lane = lane(ports).await;
        Arc::get_mut(&mut lane.runtime)
            .unwrap()
            .settings
            .review_execution = Some(crate::ReviewExecution {
            max_calls: 2,
            timeout_secs: 10,
            max_output_bytes: 4096,
        });
        lane.runtime.intake(INTAKE.into()).await;
        lane.wait_for("working").await;
        lane.executor_turn("first", "done").await;
        tokio::time::timeout(Duration::from_secs(5), async {
            while lane.ports.review_prompts.lock().unwrap().is_empty() {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        let contract = lane.contract().await.unwrap();
        let grant = lane
            ._dirs
            .path()
            .join("pro_contract/work")
            .join(contract.id.0.replace(['/', '.'], "_"))
            .join(contract.generation.to_string())
            .join("candidate.review");
        assert!(grant.join("grant.json").exists());
        let action = grant.join("call-0/action");
        std::fs::create_dir_all(&action).unwrap();
        let receipt = crate::ExecutionReceipt {
            run_id: "interrupted-inspection".into(),
            binding: Digest::of(b"interrupted action"),
            state: crate::ExecutionState::Running,
            started_ms: 1,
            finished_ms: None,
            exit_code: None,
            shutdown_confirmed: false,
            stdout_digest: None,
            stderr_digest: None,
            truncated: false,
            detail: String::new(),
        };
        std::fs::write(
            action.join("execution.json"),
            if corrupt {
                b"broken journal".to_vec()
            } else {
                serde_json::to_vec(&receipt).unwrap()
            },
        )
        .unwrap();
        gate.notify_one();
        let status = lane.wait_for("not_verified").await;
        assert_eq!(status.class, "infrastructure");
        assert!(lane.ports.repairs.lock().unwrap().is_empty());
        assert!(lane.contract().await.unwrap().support.is_none());
        let index = query(&lane, Operation::Index, None, 0).await;
        let handle = serde_json::from_value(index["entries"][0]["handle"].clone()).unwrap();
        let public: Value = serde_json::from_str(&read(&lane, handle).await).unwrap();
        assert!(public["review"].is_object());
        if !corrupt {
            assert_eq!(public["inspection_actions"][0]["run_id"], receipt.run_id);
            assert_eq!(public["inspection_actions"][0]["shutdown_confirmed"], false);
        }
    }
}

#[tokio::test]
async fn computations_are_retained_with_the_task_but_unlinked_or_foreign_blobs_are_not_readable() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("first", "done").await;
    lane.wait_for("supported").await;
    let index = query(&lane, Operation::Index, None, 0).await;
    let handle: Digest = serde_json::from_value(index["entries"][0]["handle"].clone()).unwrap();
    let mut record: crate::controller::work::PublicEvidence =
        serde_json::from_str(&read(&lane, handle).await).unwrap();
    let document =
        json!({"subject_hash":record.subject_hash,"stdout":"checked frozen numeric data"})
            .to_string();
    let computed = lane.runtime.store.put(document.as_bytes()).unwrap();
    let foreign = lane
        .runtime
        .store
        .put(
            json!({"subject_hash":Digest::of(b"foreign subject"),"stdout":"foreign"})
                .to_string()
                .as_bytes(),
        )
        .unwrap();
    record.inspections = vec![computed, foreign];
    let public = lane
        .runtime
        .store
        .put(&serde_json::to_vec(&record).unwrap())
        .unwrap();
    lane.runtime.append_event(ExperimentKind::Verification,None,json!({"contract_id":record.contract_id.0,
        "generation":record.generation,"subject_hash":record.subject_hash,"public_evidence":public})).await.unwrap();
    assert_eq!(read(&lane, computed).await, document);
    lane.runtime.restore().await;
    assert_eq!(read(&lane, computed).await, document);
    let access = lane.runtime.evidence_access();
    assert!(
        access
            .read(
                Query {
                    op: Operation::Read,
                    handle: Some(foreign),
                    offset: 0
                },
                4096
            )
            .await
            .is_err()
    );
    let unlinked = lane
        .runtime
        .store
        .put(
            json!({"subject_hash":record.subject_hash,"stdout":"not linked"})
                .to_string()
                .as_bytes(),
        )
        .unwrap();
    assert!(
        access
            .read(
                Query {
                    op: Operation::Read,
                    handle: Some(unlinked),
                    offset: 0
                },
                4096
            )
            .await
            .is_err()
    );
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
async fn candidate_repair_continues_without_erasing_independent_evidence_blockage() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail, StepOutcome::Pass]);
    ports.sealed_qualified = 0;
    let lane = reference_lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("failed-without-evidence", "failed")
        .await;
    let status = lane.wait_for("repairing").await;
    assert!(status.detail.contains("Acceptance remains blocked"));
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
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
    lane.executor_turn("candidate-repaired", "done").await;
    assert_eq!(
        lane.wait_for("not_verified").await.class,
        "insufficient_evidence"
    );
    assert!(lane.contract().await.unwrap().support.is_none());
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn admission_and_delivery_survive_a_declined_draft_and_restart() {
    let lane = lane(FakePorts::new(DECLINED_DRAFT)).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("abstained").await;
    lane.executor_turn("delivered-without-contract", "done")
        .await;
    let events = lane.ledger.experiments().await.unwrap();
    let intake = events
        .iter()
        .find(|e| e.event.kind == ExperimentKind::Intake)
        .unwrap();
    let deliveries: Vec<_> = events
        .iter()
        .filter(|e| e.event.body["phase"] == "task_delivery")
        .collect();
    assert_eq!(deliveries.len(), 1);
    assert_eq!(deliveries[0].event.body["intake"], json!(intake.hash));
    assert!(lane.contract().await.is_none());
    lane.runtime.restore().await;
    lane.runtime.restore().await;
    lane.runtime
        .intake("must not renew the original admission".into())
        .await;
    lane.executor_turn("second-delivery", "revised").await;
    let events = lane.ledger.experiments().await.unwrap();
    assert_eq!(
        events
            .iter()
            .filter(|e| e.event.kind == ExperimentKind::Intake)
            .count(),
        1
    );
    assert_eq!(
        events
            .iter()
            .filter(|e| e.event.body["phase"] == "task_delivery")
            .count(),
        2
    );
}

#[tokio::test]
async fn calibration_failure_cannot_be_erased_by_later_green_candidate_checks() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.observation_exit = 2;
    let lane = reference_lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    lane.executor_turn("green-but-uncalibrated", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert!(status.detail.contains("0 successful"));
    assert!(lane.contract().await.unwrap().support.is_none());
    assert_eq!(lane.ports.reviews.lock().unwrap().len(), 1);
    let events = lane.ledger.experiments().await.unwrap();
    let calibration = events
        .iter()
        .find(|e| e.event.body["phase"] == "calibration")
        .unwrap();
    let issued = events
        .iter()
        .find(|e| e.event.kind == ExperimentKind::Issue)
        .unwrap();
    assert!(calibration.seq < issued.seq);
    assert!(issued.event.body["evidence_policy"]["preparation_failure"].is_string());
}

#[tokio::test]
async fn scoped_review_defeat_repairs_only_the_unaffected_requirement_and_never_settles_the_gap() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false},{"id":"R2","text":"preserve an extra evidence file","source_quote":"make answer.txt say done","inferred":true}],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
    const DEFEAT: &str = r#"{"verdict":"defeat","coverage":[],"findings":[{"requirement_id":"R1","location":"answer.txt","counterexample":"says failed instead of done"}],"terms_gap":[{"element":"extra preservation","reason":"not requested","affected_requirements":["R2"]}],"missing":"","residual":"also invent an extra preservation requirement"}"#;
    const GREEN_WITH_GAP: &str = r#"{"verdict":"support","coverage":[{"requirement_id":"R1","evidence":"answer.txt"},{"requirement_id":"R2","evidence":"answer.txt"}],"findings":[],"terms_gap":[{"element":"extra preservation","reason":"not requested","affected_requirements":["R2"]}],"missing":"","residual":""}"#;
    let lane = lane(
        FakePorts::new(DRAFT)
            .checks(&[StepOutcome::Pass, StepOutcome::Pass])
            .reviews(&[DEFEAT, GREEN_WITH_GAP]),
    )
    .await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    let terms = lane.contract().await.unwrap().bindings.terms_hash;
    lane.executor_turn("failed", "failed").await;
    let status = lane.wait_for("repairing").await;
    assert!(status.detail.contains("R1") && !status.detail.contains("also invent"));
    assert_eq!(lane.ports.repairs.lock().unwrap().len(), 1);
    lane.executor_turn("repaired", "done").await;
    assert_eq!(lane.wait_for("not_verified").await.class, "terms_gap");
    let contract = lane.contract().await.unwrap();
    assert_eq!(contract.bindings.terms_hash, terms);
    assert!(contract.support.is_none());
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
