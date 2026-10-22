use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_extension_api::ThreadIdleCause;
use codex_pro_contract::ContractId;
use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use codex_pro_contract_store::LEDGER_FILE;
use codex_protocol::ThreadId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use tokio::sync::Notify;

use super::STATUS_KIND;
use super::StatusRecord;
use super::Stores;
use super::ThreadRuntime;
use crate::BlobStore;
use crate::CheckEnvironment;
use crate::CheckError;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvaluationProfile;
use crate::EvidencePolicy;
use crate::EvidenceSettings;
use crate::Ledger;
use crate::Observation;
use crate::Settings;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::WorkerError;
use crate::WorkerSettings;
use crate::controller::ports::PortFuture;
use crate::controller::ports::Ports;
use crate::controller::ports::WorkerIdentity;
use crate::workers::runtime::WorkerTurn;

#[path = "continuation_tests.rs"]
mod continuation_tests;
#[path = "progress_tests.rs"]
mod progress_tests;
#[path = "runtime_recovery_tests.rs"]
mod recovery_tests;
#[path = "succession_tests.rs"]
mod succession_tests;
#[path = "work_tests.rs"]
mod work_tests;

const INTAKE: &str = "Please make answer.txt say done.";
const CONTRACT_DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false}],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
const DECLINED_DRAFT: &str = r#"{"decision":"none","reason":"a question, not a task","requirements":[],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
const SUPPORT_REVIEW: &str = r#"{"verdict":"support","coverage":[{"requirement_id":"R1","evidence":"answer.txt"}],"findings":[],"terms_gap":[],"missing":"","residual":""}"#;
const CANNOT_JUDGE_REVIEW: &str = r#"{"verdict":"cannot_judge","coverage":[],"findings":[],"terms_gap":[],"missing":"the output is not visible","residual":""}"#;
const EXPLORATION: &str = r#"{"cases":[{"id":"e1","args":["--help"]}]}"#;
const PROBE: &str = r#"{"coverage_plan":[{"family":"answer","surface":"answer.txt","description":"the answer"}],"cases":[{"id":"s1","family":"answer","args":["--sealed-secret","1"]},{"id":"s2","family":"answer","args":["--sealed-secret","2"]},{"id":"s3","family":"format","args":["--sealed-secret","3"]},{"id":"s4","family":"format","args":["--sealed-secret","4"]}]}"#;

/// Scripted workers, checks and repair submission.
struct FakePorts {
    draft: &'static str,
    draft_gate: Option<Arc<Notify>>,
    draft_prompts: Mutex<Vec<String>>,
    /// The prober's second turn; `None` makes the prober fail.
    probe: Option<&'static str>,
    exploration_responses: Mutex<VecDeque<String>>,
    probe_responses: Mutex<VecDeque<String>>,
    probe_calls: Mutex<Vec<&'static str>>,
    observation_error: bool,
    observation_exit: i32,
    /// How many sealed cases pass in each check run; the rest fail.
    sealed_passing: usize,
    sealed_qualified: usize,
    public_steps: Mutex<VecDeque<Vec<StepReceipt>>>,
    /// The sealed cases each check run received.
    sealed_checked: Mutex<Vec<Vec<DifferentialCase>>>,
    reviews: Mutex<VecDeque<&'static str>>,
    review_prompts: Mutex<Vec<String>>,
    review_contexts: Mutex<Vec<serde_json::Value>>,
    review_deadlines: Mutex<Vec<Duration>>,
    review_gate: Option<Arc<Notify>>,
    continuation_choices: Mutex<VecDeque<String>>,
    continuation_prompts: Mutex<Vec<String>>,
    continuation_gate: Option<Arc<Notify>>,
    check_outcomes: Mutex<VecDeque<StepOutcome>>,
    repair_error: Option<String>,
    worker_model: &'static str,
    /// The candidate's answer.txt at each check run.
    checked: Mutex<Vec<String>>,
    /// (residual, previous turn id) of each repair submission.
    repairs: Mutex<Vec<(String, String)>>,
    successor_workspace: Mutex<Option<std::path::PathBuf>>,
    successor_answers: Mutex<VecDeque<String>>,
    successor_packets: Mutex<Vec<(ThreadId, String)>>,
    successor_gate: Option<Arc<Notify>>,
    successor_rejection: Option<String>,
}

impl FakePorts {
    fn new(draft: &'static str) -> Self {
        Self {
            draft,
            draft_gate: None,
            draft_prompts: Mutex::new(Vec::new()),
            probe: Some(PROBE),
            exploration_responses: Mutex::default(),
            probe_responses: Mutex::default(),
            probe_calls: Mutex::default(),
            observation_error: false,
            observation_exit: 0,
            sealed_passing: usize::MAX,
            sealed_qualified: usize::MAX,
            public_steps: Mutex::default(),
            sealed_checked: Mutex::new(Vec::new()),
            reviews: Mutex::new(VecDeque::new()),
            review_prompts: Mutex::new(Vec::new()),
            review_contexts: Mutex::new(Vec::new()),
            review_deadlines: Mutex::new(Vec::new()),
            review_gate: None,
            continuation_choices: Mutex::default(),
            continuation_prompts: Mutex::default(),
            continuation_gate: None,
            check_outcomes: Mutex::new(VecDeque::new()),
            repair_error: None,
            worker_model: "model-a",
            checked: Mutex::new(Vec::new()),
            repairs: Mutex::new(Vec::new()),
            successor_workspace: Mutex::new(None),
            successor_answers: Mutex::new(VecDeque::new()),
            successor_packets: Mutex::new(Vec::new()),
            successor_gate: None,
            successor_rejection: None,
        }
    }

    fn checks(self, outcomes: &[StepOutcome]) -> Self {
        *self.check_outcomes.lock().unwrap() = outcomes.iter().copied().collect();
        self
    }

    fn reviews(self, reviews: &[&'static str]) -> Self {
        *self.reviews.lock().unwrap() = reviews.iter().copied().collect();
        self
    }
}

impl Ports for FakePorts {
    fn capture_barrier<'a>(
        &'a self,
        _: &'a crate::EvaluationProfile,
        _: &'a str,
    ) -> PortFuture<'a, Result<crate::controller::capture_barrier::CaptureBarrier, String>> {
        Box::pin(async { Ok(crate::controller::capture_barrier::CaptureBarrier::test_only()) })
    }

    fn run_successor(
        &self,
        mut turn: crate::controller::ports::SuccessorTurn,
    ) -> PortFuture<'_, Result<crate::controller::ports::SuccessorExit, String>> {
        Box::pin(async move {
            use crate::controller::ports::SuccessorExit;
            use crate::controller::ports::SuccessorHandoff;
            if let Some(reason) = &self.successor_rejection {
                return Ok(SuccessorExit::Rejected(reason.clone()));
            }
            self.successor_packets
                .lock()
                .unwrap()
                .push((turn.id, turn.packet));
            if let Some(gate) = &self.successor_gate {
                tokio::select! {
                    _ = gate.notified() => {},
                    _ = turn.cancel.changed() => return Ok(SuccessorExit::Stopped("cancelled".into())),
                }
            }
            let answer = self
                .successor_answers
                .lock()
                .unwrap()
                .pop_front()
                .ok_or("no scripted successor")?;
            let workspace = self
                .successor_workspace
                .lock()
                .unwrap()
                .clone()
                .ok_or("no workspace")?;
            std::fs::write(workspace.join("answer.txt"), &answer).map_err(|e| e.to_string())?;
            Ok(SuccessorExit::Handoff(SuccessorHandoff {
                turn_id: "fresh-turn".into(),
                summary: format!("executor claims: {answer}"),
                final_message: Some(format!("executor claims: {answer}")),
            }))
        })
    }
    fn run_worker(&self, turn: WorkerTurn) -> PortFuture<'_, Result<String, WorkerError>> {
        Box::pin(async move {
            match turn.trigger {
                "pro_contract_draft" => {
                    self.draft_prompts.lock().unwrap().push(turn.prompt);
                    if let Some(gate) = &self.draft_gate {
                        gate.notified().await;
                    }
                    Ok(self.draft.to_string())
                }
                "pro_contract_explore" => {
                    self.probe_calls.lock().unwrap().push(turn.trigger);
                    Ok(self
                        .exploration_responses
                        .lock()
                        .unwrap()
                        .pop_front()
                        .unwrap_or_else(|| EXPLORATION.to_string()))
                }
                "pro_contract_probe" => {
                    self.probe_calls.lock().unwrap().push(turn.trigger);
                    self.probe_responses
                        .lock()
                        .unwrap()
                        .pop_front()
                        .or_else(|| self.probe.map(str::to_string))
                        .ok_or_else(|| WorkerError::Failed("the prober failed".to_string()))
                }
                "pro_contract_continuation" => {
                    let facts: serde_json::Value =
                        serde_json::from_str(turn.prompt.rsplit_once("\n\n").unwrap().1).unwrap();
                    self.continuation_prompts.lock().unwrap().push(turn.prompt);
                    if let Some(gate) = &self.continuation_gate {
                        gate.notified().await;
                    }
                    if let Some(choice) = self.continuation_choices.lock().unwrap().pop_front() {
                        return if choice == "INTERRUPTED" {
                            Err(WorkerError::Interrupted(
                                "selection provider stopped".into(),
                            ))
                        } else {
                            Ok(choice)
                        };
                    }
                    let keep_working = facts["assessment"]["decision"] == "defeat";
                    let choice = if keep_working {
                        serde_json::json!({"action":facts["available_actions"][0],"requirements":facts["allowed_requirements"],"next_step":"Inspect the retained counterexample, repair it and replay its check."})
                    } else {
                        serde_json::json!({"action":"rest","reason":"No further useful action selected by the fixture strategy."})
                    };
                    Ok(serde_json::json!({"choice":choice}).to_string())
                }
                "pro_contract_review" => {
                    self.review_prompts.lock().unwrap().push(turn.prompt);
                    self.review_deadlines.lock().unwrap().push(turn.deadline);
                    let scripted = self.reviews.lock().unwrap().pop_front();
                    if let Some(gate) = &self.review_gate {
                        gate.notified().await;
                    }
                    if let Some(mut evidence) = turn.evidence {
                        let mut cursor = 0;
                        loop {
                            let response = evidence.respond(
                                serde_json::json!({"op":"index","source_id":"","offset":cursor}),
                            );
                            let codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem::InputText { text } = &response.content_items[0] else { panic!("text evidence"); };
                            let index: serde_json::Value = serde_json::from_str(text).unwrap();
                            if index["entry"]["path"] == "hindsight.json"
                                || matches!(
                                    index["entry"]["source_id"].as_str(),
                                    Some("diagnosis_request" | "prior_assessment")
                                )
                            {
                                let mut offset = 0;
                                let mut document = String::new();
                                loop {
                                    let response = evidence.respond(serde_json::json!({"op":"read","source_id":index["entry"]["source_id"],"offset":offset}));
                                    let codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem::InputText { text } = &response.content_items[0] else { panic!("text evidence"); };
                                    let chunk: serde_json::Value =
                                        serde_json::from_str(text).unwrap();
                                    document.push_str(chunk["text"].as_str().unwrap());
                                    if chunk["eof"] == true {
                                        break;
                                    }
                                    offset = chunk["next_offset"].as_u64().unwrap();
                                }
                                if index["entry"]["path"] == "hindsight.json" {
                                    self.review_prompts.lock().unwrap().push(document);
                                } else {
                                    self.review_contexts
                                        .lock()
                                        .unwrap()
                                        .push(serde_json::from_str(&document).unwrap());
                                }
                            }
                            if index["eof"] == true {
                                break;
                            }
                            cursor = index["next_offset"].as_u64().unwrap();
                        }
                        if scripted == Some("CHECKPOINT_TIMEOUT") {
                            let response = evidence.record_checkpoint(serde_json::json!({
                                "checkpoint_id":"observed-counterexample",
                                "review":{"assessments":[{"requirement_id":"R1","observations":"The current answer is not ready.",
                                    "judgment":{"status":"defeated","findings":[{"location":"answer.txt","counterexample":"not yet differs from ready"}],"missing":""}}],
                                    "terms_gap":[],"missing":""},
                            })).await;
                            assert!(response.success, "{response:?}");
                            return Err(WorkerError::TimedOut);
                        }
                    }
                    scripted
                        .map(str::to_string)
                        .ok_or_else(|| WorkerError::Failed("no scripted review".to_string()))
                }
                other => Err(WorkerError::Failed(format!("unexpected trigger {other}"))),
            }
        })
    }

    fn observe<'a>(
        &'a self,
        _env: &'a CheckEnvironment,
        base: &'a Path,
        _reference: &'a str,
        cases: &'a [DifferentialCase],
    ) -> PortFuture<'a, Result<crate::ObservationBatch, CheckError>> {
        Box::pin(async move {
            if self.observation_error {
                return Err(CheckError::TimedOut);
            }
            assert!(
                base.join("answer.txt").exists(),
                "observations run over the base"
            );
            Ok(crate::ObservationBatch {
                complete: true,
                execution: None,
                observations: cases
                    .iter()
                    .map(|case| Observation {
                        id: case.id.clone(),
                        exit: Some(self.observation_exit),
                        stable: true,
                        stable_channels: Vec::new(),
                        stdout: "usage: reference\n".to_string(),
                        stderr: String::new(),
                    })
                    .collect(),
            })
        })
    }

    fn run_checks<'a>(
        &'a self,
        _env: &'a CheckEnvironment,
        candidate: &'a Path,
        base: &'a Path,
        policy: &'a EvidencePolicy,
    ) -> PortFuture<'a, Result<CheckReceipts, CheckError>> {
        Box::pin(async move {
            assert_eq!(
                std::fs::read_to_string(base.join("answer.txt")).unwrap_or_default(),
                "not yet",
                "every case runs over the base workspace as it was at intake"
            );
            self.sealed_checked
                .lock()
                .unwrap()
                .push(policy.sealed.clone());
            let answer = std::fs::read_to_string(candidate.join("answer.txt")).unwrap_or_default();
            self.checked.lock().unwrap().push(answer);
            let outcome = self
                .check_outcomes
                .lock()
                .unwrap()
                .pop_front()
                .ok_or(CheckError::TimedOut)?;
            let detail = match outcome {
                StepOutcome::Fail => "answer.txt does not say done".to_string(),
                StepOutcome::Pass | StepOutcome::Unqualified | StepOutcome::Blocked => {
                    String::new()
                }
            };
            let mut steps = self
                .public_steps
                .lock()
                .unwrap()
                .pop_front()
                .unwrap_or_else(|| vec![StepReceipt::new("build", outcome, detail)]);
            steps.extend(policy.sealed.iter().enumerate().map(|(index, case)| {
                let outcome = if index >= self.sealed_qualified {
                    StepOutcome::Unqualified
                } else if index < self.sealed_passing {
                    StepOutcome::Pass
                } else {
                    StepOutcome::Fail
                };
                StepReceipt {
                    reference_exit: Some(0),
                    ..StepReceipt::new(format!("sealed:{}", case.id), outcome, "")
                }
            }));
            Ok(CheckReceipts {
                execution: None,
                steps,
                environment: vec!["fake toolchain".to_string()],
                complete: true,
                environment_digest: Digest::of(b"environment"),
                evaluator_digest: Digest::of(b"evaluator"),
            })
        })
    }

    fn worker_identity(&self) -> WorkerIdentity {
        WorkerIdentity {
            model: Some(self.worker_model.to_string()),
            effort: Some("max".to_string()),
        }
    }

    fn submit_repair(
        &self,
        residual: String,
        previous_turn_id: String,
    ) -> PortFuture<'_, Result<(), String>> {
        Box::pin(async move {
            self.repairs
                .lock()
                .unwrap()
                .push((residual, previous_turn_id));
            self.repair_error.clone().map_or(Ok(()), Err)
        })
    }
}

struct Lane {
    _dirs: tempfile::TempDir,
    workspace: std::path::PathBuf,
    thread_id: ThreadId,
    ledger: Ledger,
    ports: Arc<FakePorts>,
    runtime: Arc<ThreadRuntime>,
}

async fn lane(ports: FakePorts) -> Lane {
    lane_with(ports, None).await
}

/// A lane whose profile has a reference program, so the prober runs and sealed evidence applies;
/// support needs at least three of four sealed cases.
async fn reference_lane(ports: FakePorts) -> Lane {
    lane_with(ports, Some("/workspace/executable")).await
}

async fn lane_with(ports: FakePorts, reference: Option<&str>) -> Lane {
    let dirs = tempfile::tempdir().expect("tempdir");
    let workspace = dirs.path().join("workspace");
    let dir = dirs.path().join("pro_contract");
    std::fs::create_dir_all(&workspace).expect("workspace");
    std::fs::create_dir_all(&dir).expect("state dir");
    std::fs::write(workspace.join("answer.txt"), "not yet").expect("seed workspace");
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(dirs.path()).expect("absolute tempdir"),
    );
    let ledger = Ledger::open(&sqlite, &dir).await.expect("ledger");
    let store = BlobStore::open(&dir.join("blobs")).expect("blobs");
    let profile = EvaluationProfile {
        environment_id: "cleanroom".to_string(),
        workspace_container_root: "/workspace".to_string(),
        workspace_host_root: workspace.clone(),
        excluded_paths: Vec::new(),
        check: CheckEnvironment {
            inputs: Vec::new(),
            docker: "docker".to_string(),
            image: "unused".to_string(),
            user: "1000:1000".to_string(),
            candidate_mount: "/candidate".to_string(),
            timeout_secs: 60,
            build_command: None,
            candidate_command: reference.map(|_| "./executable".to_string()),
        },
        reference_command: reference.map(str::to_string),
    };
    let settings = Settings {
        review_execution: None,
        progress: None,
        evaluation: Some(profile.clone()),
        repair_attempts: 1,
        succession: None,
        worker: WorkerSettings::default(),
        evidence: EvidenceSettings {
            sealed_threshold_permille: Some(750),
            min_sealed_qualified: Some(4),
            min_success_permille: Some(500),
        },
        policy: None,
    };
    let ports = Arc::new(ports);
    let thread_id = ThreadId::new();
    let runtime = Arc::new(ThreadRuntime::new(
        thread_id,
        settings,
        profile,
        crate::workers::policies::Policies::default(),
        Stores {
            dir,
            ledger: ledger.clone(),
            store,
        },
        Arc::clone(&ports) as Arc<dyn Ports>,
    ));
    Lane {
        _dirs: dirs,
        workspace,
        thread_id,
        ledger,
        ports,
        runtime,
    }
}

impl Lane {
    fn write_answer(&self, text: &str) {
        std::fs::write(self.workspace.join("answer.txt"), text).expect("write answer");
    }

    /// One executor turn that writes `answer` and hands off.
    async fn executor_turn(&self, turn_id: &str, answer: &str) {
        self.runtime.turn_started().await;
        self.write_answer(answer);
        self.runtime.turn_stopped(turn_id.to_string()).await;
        self.runtime.thread_idle(ThreadIdleCause::Completed).await;
    }

    async fn status(&self) -> Option<StatusRecord> {
        self.ledger
            .record::<StatusRecord>(STATUS_KIND, &self.thread_id.to_string())
            .await
            .expect("status record")
    }

    async fn wait_for(&self, phase: &str) -> StatusRecord {
        for _ in 0..500 {
            if let Some(status) = self.status().await
                && status.phase == phase
            {
                return status;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("status never reached {phase}: {:?}", self.status().await);
    }

    async fn contract(&self) -> Option<codex_pro_contract::Contract> {
        self.ledger
            .contract(&ContractId(format!("{}.1", self.thread_id)))
            .await
            .expect("contract")
    }
}

#[tokio::test]
async fn declined_draft_rests_abstained_without_a_contract() {
    let lane = lane(FakePorts::new(DECLINED_DRAFT)).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    let status = lane.wait_for("abstained").await;

    assert!(status.resting);
    assert!(
        status.detail.contains("a question, not a task"),
        "{status:?}"
    );
    assert_eq!(lane.contract().await, None);
}

#[tokio::test]
async fn multiline_intake_reaches_contract_issue_without_losing_the_tail() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_id":"request:0","inferred":false}],"out_of_scope":[],"process_constraints":[],"differential_cases":[],"candidate_tests":false}"#;
    let lane = lane(FakePorts::new(DRAFT)).await;
    let request = format!(
        "answer.txt must say done.\n{}Never reuse the reference implementation.\n",
        "Preserve the existing constraint.\n".repeat(100)
    );
    lane.runtime.intake(request).await;
    lane.wait_for("working").await;
    {
        let prompts = lane.ports.draft_prompts.lock().unwrap();
        assert_eq!(prompts.len(), 1);
        assert!(prompts[0].contains("Never reuse the reference implementation."));
        assert!(!prompts[0].contains("request exceeds source budget"));
    }
    assert!(lane.contract().await.is_some());
}

#[tokio::test]
async fn benign_fixture_prefix_does_not_block_contract_issue() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false}],"out_of_scope":[],"differential_cases":[{"id":"save-txt","args":["./contract-txt-out"],"dirs":["./contract-txt-out"]}],"candidate_tests":false}"#;
    let lane = reference_lane(FakePorts::new(DRAFT)).await;
    lane.runtime.intake(INTAKE.to_string()).await;
    let status = lane.wait_for("working").await;
    assert!(lane.contract().await.is_some(), "{status:?}");
}

#[tokio::test]
async fn host_source_ids_and_required_artifacts_reach_the_real_controller_review() {
    const DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"hindsight.json contains the explanation","source_id":"request:0","inferred":false}],"out_of_scope":[],"process_constraints":[],"differential_cases":[],"candidate_tests":false}"#;
    let lane = lane(
        FakePorts::new(DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;
    lane.runtime
        .intake("Deliver hindsight.json with an explanation.".to_string())
        .await;
    lane.wait_for("working").await;
    let explanation = serde_json::json!({"explanation":"evidence ".repeat(8000)}).to_string();
    std::fs::write(lane.workspace.join("hindsight.json"), &explanation).unwrap();
    std::fs::write(lane.workspace.join("unrelated.rs"), " ".repeat(440_000)).unwrap();
    lane.executor_turn("turn-1", "done").await;
    lane.wait_for("supported").await;
    {
        let prompts = lane.ports.review_prompts.lock().unwrap();
        assert_eq!(prompts.len(), 2);
        assert!(prompts[0].len() < 4096);
        assert_eq!(prompts[1], explanation);
    }
    assert!(lane.contract().await.unwrap().support.is_some());
}

#[tokio::test]
async fn late_issue_verifies_the_artifact_frozen_at_handoff() {
    let gate = Arc::new(Notify::new());
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.draft_gate = Some(Arc::clone(&gate));
    let lane = lane(ports).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.executor_turn("turn-1", "done").await;
    // The workspace changes after the handoff; verification must not see it.
    lane.write_answer("edited after the handoff");
    gate.notify_one();
    let status = lane.wait_for("supported").await;

    assert!(status.resting);
    assert_eq!(
        *lane.ports.checked.lock().unwrap(),
        vec!["done".to_string()]
    );
    let contract = lane.contract().await.expect("issued contract");
    assert!(contract.support.is_some(), "{contract:?}");
    // The lane's own evidence is within the executor's reach: it measures diligence.
    assert_eq!(
        contract.support.as_ref().expect("support").coordinate.reach,
        codex_pro_contract::Reach::Within
    );
    assert!(status.detail.contains("diligence"), "{status:?}");
    let judged = contract.support.expect("support").coordinate.subject_hash;
    let binding = lane
        .ledger
        .subject_binding(&judged)
        .await
        .expect("binding read");
    assert!(
        binding.is_some(),
        "the judged subject must be resolvable from its hash"
    );
}

#[tokio::test]
async fn defeat_repairs_once_then_rests_did_not_pass() {
    let lane =
        lane(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail, StepOutcome::Fail])).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "almost").await;
    let repairing = lane.wait_for("repairing").await;
    assert!(!repairing.resting);
    assert_eq!(repairing.repairs_used, 1);
    // Until the executor hands off again, compaction may need the note stated anew.
    let outstanding = lane.runtime.outstanding_repair().await;
    assert_eq!(
        outstanding.as_deref(),
        Some(lane.ports.repairs.lock().unwrap()[0].0.as_str())
    );
    lane.executor_turn("turn-2", "still not").await;
    let status = lane.wait_for("did_not_pass").await;
    assert_eq!(lane.runtime.outstanding_repair().await, None);

    assert!(status.resting);
    let repairs = lane.ports.repairs.lock().unwrap().clone();
    assert_eq!(repairs.len(), 1, "{repairs:?}");
    assert_eq!(repairs[0].1, "turn-1");
    assert!(
        repairs[0].0.contains("answer.txt does not say done"),
        "{}",
        repairs[0].0
    );
    assert_eq!(
        *lane.ports.checked.lock().unwrap(),
        vec!["almost".to_string(), "still not".to_string()]
    );
    let contract = lane.contract().await.expect("issued contract");
    assert_eq!((contract.candidate, contract.support), (None, None));
}

#[tokio::test]
async fn cannot_judge_rests_not_verified_without_repair() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[CANNOT_JUDGE_REVIEW]),
    )
    .await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    let status = lane.wait_for("not_verified").await;

    assert!(status.resting);
    assert!(
        status.detail.contains("the output is not visible"),
        "{status:?}"
    );
    assert!(lane.ports.repairs.lock().unwrap().is_empty());
}

#[tokio::test]
async fn repair_that_cannot_start_rests_did_not_pass() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Fail]);
    ports.repair_error = Some("NotSubmitted { reason: Busy }".to_string());
    let lane = lane(ports).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "almost").await;
    let status = lane.wait_for("did_not_pass").await;

    assert!(status.resting);
    assert!(
        status.detail.contains("repair could not start"),
        "{status:?}"
    );
}

#[tokio::test]
async fn interrupted_turn_is_not_a_handoff() {
    let lane = lane(FakePorts::new(CONTRACT_DRAFT).checks(&[StepOutcome::Pass])).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.runtime.turn_started().await;
    lane.runtime.turn_stopped("turn-1".to_string()).await;
    lane.runtime.thread_idle(ThreadIdleCause::Interrupted).await;
    let status = lane.wait_for("not_verified").await;

    assert!(status.resting);
    assert_eq!(status.class, "no_handoff");
    assert!(lane.ports.checked.lock().unwrap().is_empty());
}

#[tokio::test]
async fn only_the_first_human_turn_is_intake() {
    let lane = lane(FakePorts::new(DECLINED_DRAFT)).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("abstained").await;
    lane.runtime.intake("Another request.".to_string()).await;

    let intakes: Vec<String> = lane
        .ledger
        .experiments()
        .await
        .expect("events")
        .into_iter()
        .filter(|record| record.event.kind == ExperimentKind::Intake)
        .map(|record| {
            record.event.body["text"]
                .as_str()
                .unwrap_or_default()
                .to_string()
        })
        .collect();
    assert_eq!(intakes, vec![INTAKE.to_string()]);
}

#[tokio::test]
async fn a_verification_is_an_immutable_event_with_identities() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    lane.wait_for("supported").await;

    let events = lane.ledger.experiments().await.expect("events");
    let kinds: Vec<ExperimentKind> = events.iter().map(|record| record.event.kind).collect();
    assert_eq!(
        kinds,
        vec![
            ExperimentKind::Intake,
            ExperimentKind::Draft,
            ExperimentKind::Issue,
            ExperimentKind::Capture,
            ExperimentKind::Verification
        ]
    );
    let verification = &events[4].event;
    assert_eq!(verification.body["verdict"], "support");
    assert_eq!(verification.identities.model.as_deref(), Some("model-a"));
    assert!(verification.identities.policies.contains_key("reviewer"));
    assert!(
        verification
            .identities
            .policies
            .contains_key("check_pipeline")
    );

    // The records table holds operational status only, read through a second pool on the file.
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(lane._dirs.path()).expect("absolute tempdir"),
    );
    let pool = sqlite
        .open_read_write_pool(&lane._dirs.path().join("pro_contract").join(LEDGER_FILE))
        .await
        .expect("ledger pool");
    let research_records: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM records WHERE kind != 'status'")
            .fetch_one(&pool)
            .await
            .expect("count records");
    assert_eq!(research_records, 0);
}

#[tokio::test]
async fn the_reviewer_model_is_part_of_the_certificates_evaluator() {
    let mut digests = Vec::new();
    for model in ["model-a", "model-b"] {
        let mut ports = FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]);
        ports.worker_model = model;
        let lane = lane(ports).await;
        lane.runtime.intake(INTAKE.to_string()).await;
        lane.wait_for("working").await;
        lane.executor_turn("turn-1", "done").await;
        lane.wait_for("supported").await;
        let contract = lane.contract().await.expect("contract");
        digests.push(
            contract
                .support
                .expect("support")
                .coordinate
                .evaluator_digest,
        );
    }

    assert_ne!(digests[0], digests[1]);
}

fn kinds(events: &[codex_pro_contract_store::ExperimentRecord]) -> Vec<ExperimentKind> {
    events.iter().map(|record| record.event.kind).collect()
}

#[tokio::test]
async fn sealed_cases_are_issued_checked_and_never_shown_to_the_executor() {
    let lane = reference_lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    let brief = lane.runtime.brief().await.expect("brief").text;
    assert!(
        brief.contains("sealed set whose contents are never shown"),
        "{brief}"
    );
    assert!(!brief.contains("--sealed-secret"), "{brief}");
    lane.executor_turn("turn-1", "done").await;
    lane.wait_for("supported").await;

    let sealed = lane.ports.sealed_checked.lock().unwrap().clone();
    assert_eq!(sealed.len(), 1);
    assert_eq!(
        sealed[0]
            .iter()
            .map(|case| case.id.as_str())
            .collect::<Vec<_>>(),
        vec!["s1", "s2", "s3", "s4"]
    );
    let events = lane.ledger.experiments().await.expect("events");
    assert_eq!(
        kinds(&events),
        vec![
            ExperimentKind::Intake,
            ExperimentKind::Probe,
            ExperimentKind::Probe,
            ExperimentKind::Draft,
            ExperimentKind::Probe,
            ExperimentKind::Issue,
            ExperimentKind::Capture,
            ExperimentKind::Verification
        ]
    );
    let issue = &events
        .iter()
        .find(|r| r.event.kind == ExperimentKind::Issue)
        .unwrap()
        .event
        .body;
    assert_eq!(
        issue["evidence_policy"]["sealed"].as_array().map(Vec::len),
        Some(4)
    );
    assert_eq!(issue["evidence_policy"]["sealed_threshold_permille"], 750);
    let verification = &events
        .iter()
        .find(|r| r.event.kind == ExperimentKind::Verification)
        .unwrap()
        .event;
    assert_eq!(verification.body["sealed"]["qualified"], 4);
    assert!(verification.identities.policies.contains_key("prober"));
    let default = crate::workers::policies::Policies::default();
    assert_eq!(
        verification.identities.policies["bundle"],
        crate::digest_of(
            "policy_bundle",
            &serde_json::json!([
                default.work_method,
                default.drafter,
                default.prober,
                default.reviewer,
                default.continuation
            ]),
        ),
        "a controller can recompute the bundle identity from the files"
    );
    let probe = &events
        .iter()
        .find(|record| {
            record.event.kind == ExperimentKind::Probe
                && record.event.body.get("exploration").is_some()
        })
        .unwrap()
        .event
        .body;
    assert_eq!(probe["exploration"][0]["id"], "e1");
    assert_eq!(probe["observations"][0]["stdout"], "usage: reference\n");
}

#[tokio::test]
async fn a_failed_prober_preserves_the_task_and_blocks_support_without_losing_delivery() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.probe = None;
    let lane = reference_lane(ports).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    let status = lane.wait_for("not_verified").await;
    assert!(
        status.detail.contains("evidence preparation failed"),
        "{status:?}"
    );
    assert!(lane.contract().await.unwrap().support.is_none());
    assert_eq!(lane.ports.checked.lock().unwrap().len(), 1);
    assert_eq!(lane.ports.reviews.lock().unwrap().len(), 1);
    let events = lane.ledger.experiments().await.expect("events");
    assert!(
        events
            .iter()
            .any(|row| row.event.kind == ExperimentKind::Issue)
    );
    assert_eq!(
        lane.ports.probe_calls.lock().unwrap().len(),
        2,
        "transport failures are not retried"
    );
    let probe = events
        .iter()
        .find(|record| {
            record.event.kind == ExperimentKind::Probe && record.event.body.get("error").is_some()
        })
        .expect("probe event");
    assert!(
        probe.event.body["error"]
            .as_str()
            .is_some_and(|error| error.contains("the prober failed")),
        "{:?}",
        probe.event.body
    );
}

#[tokio::test]
async fn overproduced_exploration_recovers_once_before_freezing_the_suite() {
    for count in [89, 125] {
        let ports = FakePorts::new(CONTRACT_DRAFT);
        ports.exploration_responses.lock().unwrap().push_back(serde_json::json!({
            "cases": (0..count).map(|i| serde_json::json!({"id":format!("e{i}"),"args":[]})).collect::<Vec<_>>()
        }).to_string());
        let lane = reference_lane(ports).await;
        lane.runtime.intake(INTAKE.into()).await;
        lane.wait_for("working").await;
        assert_eq!(
            *lane.ports.probe_calls.lock().unwrap(),
            [
                "pro_contract_explore",
                "pro_contract_explore",
                "pro_contract_probe"
            ]
        );
        let events = lane.ledger.experiments().await.unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|r| r.event.kind == ExperimentKind::Issue)
                .count(),
            1
        );
        assert!(events.iter().any(|r| r.event.body["phase"] == "correction"));
    }
}

#[tokio::test]
async fn insufficient_suite_is_explicitly_blocked_and_correction_is_bounded() {
    for insufficient in ["{\"coverage_plan\":[],\"cases\":[]}", "malformed"] {
        let mut ports = FakePorts::new(CONTRACT_DRAFT);
        ports.probe = Some(insufficient);
        let lane = reference_lane(ports).await;
        lane.runtime.intake(INTAKE.into()).await;
        lane.wait_for("working").await;
        assert!(lane.contract().await.unwrap().support.is_none());
        assert!(
            lane.runtime
                .state
                .lock()
                .await
                .contract
                .as_ref()
                .unwrap()
                .policy
                .preparation_failure
                .is_some()
        );
        assert_eq!(
            *lane.ports.probe_calls.lock().unwrap(),
            [
                "pro_contract_explore",
                "pro_contract_probe",
                "pro_contract_probe"
            ]
        );
        assert!(
            lane.ledger
                .experiments()
                .await
                .unwrap()
                .iter()
                .any(|r| r.event.kind == ExperimentKind::Issue)
        );
    }
}

#[tokio::test]
async fn failed_reference_observation_is_not_an_empty_successful_observation() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT);
    ports.observation_error = true;
    let lane = reference_lane(ports).await;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    assert!(
        lane.runtime
            .state
            .lock()
            .await
            .contract
            .as_ref()
            .unwrap()
            .policy
            .preparation_failure
            .as_ref()
            .unwrap()
            .contains("reference_observation")
    );
    assert!(lane.contract().await.unwrap().support.is_none());
    assert_eq!(
        *lane.ports.probe_calls.lock().unwrap(),
        ["pro_contract_explore"]
    );
}

#[tokio::test]
async fn reference_only_review_does_not_require_a_differential_suite() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT);
    ports.probe = None;
    let mut lane = reference_lane(ports).await;
    Arc::get_mut(&mut lane.runtime)
        .unwrap()
        .profile
        .check
        .candidate_command = None;
    lane.runtime.intake(INTAKE.into()).await;
    lane.wait_for("working").await;
    assert!(lane.ports.probe_calls.lock().unwrap().is_empty());
}

#[tokio::test]
async fn a_low_sealed_pass_rate_defeats_with_an_aggregate_residual() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass, StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.sealed_passing = 2;
    let lane = reference_lane(ports).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "almost").await;
    lane.wait_for("repairing").await;
    lane.executor_turn("turn-2", "still").await;
    let status = lane.wait_for("did_not_pass").await;

    let repairs = lane.ports.repairs.lock().unwrap().clone();
    assert_eq!(repairs.len(), 1);
    let residual = &repairs[0].0;
    assert!(
        residual.contains("2 of 4 independent sealed checks"),
        "{residual}"
    );
    assert!(residual.contains("format"), "{residual}");
    assert!(!residual.contains("--sealed-secret"), "{residual}");
    assert!(status.resting);
}

#[tokio::test]
async fn without_a_reference_the_prober_never_runs() {
    let lane = lane(
        FakePorts::new(CONTRACT_DRAFT)
            .checks(&[StepOutcome::Pass])
            .reviews(&[SUPPORT_REVIEW]),
    )
    .await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    lane.wait_for("supported").await;

    let events = lane.ledger.experiments().await.expect("events");
    assert!(!kinds(&events).contains(&ExperimentKind::Probe));
}
