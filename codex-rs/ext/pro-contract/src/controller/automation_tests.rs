use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;

use codex_extension_api::ThreadIdleCause;
use codex_pro_contract::ContractId;
use codex_pro_contract::Digest;
use codex_protocol::ThreadId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

use super::STATUS_KIND;
use super::StatusRecord;
use super::Stores;
use super::ThreadRuntime;
use crate::BlobStore;
use crate::CheckEnvironment;
use crate::CheckError;
use crate::CheckReceipts;
use crate::EvaluationProfile;
use crate::EvidencePolicy;
use crate::Ledger;
use crate::Settings;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::WorkerError;
use crate::WorkerSettings;
use crate::controller::ports::PortFuture;
use crate::controller::ports::Ports;
use crate::workers::runtime::WorkerTurn;

const INTAKE: &str = "Please make answer.txt say done.";
const CONTRACT_DRAFT: &str = r#"{"decision":"contract","reason":"","requirements":[{"id":"R1","text":"answer.txt says done","source_quote":"make answer.txt say done","inferred":false}],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
const DECLINED_DRAFT: &str = r#"{"decision":"none","reason":"a question, not a task","requirements":[],"out_of_scope":[],"differential_cases":[],"candidate_tests":false}"#;
const SUPPORT_REVIEW: &str = r#"{"verdict":"support","coverage":[{"requirement_id":"R1","evidence":"answer.txt"}],"findings":[],"terms_gap":[],"missing":"","residual":""}"#;
const CANNOT_JUDGE_REVIEW: &str = r#"{"verdict":"cannot_judge","coverage":[],"findings":[],"terms_gap":[],"missing":"the output is not visible","residual":""}"#;

/// Scripted workers, checks and repair submission.
struct FakePorts {
    draft: &'static str,
    draft_gate: Option<Arc<Notify>>,
    reviews: Mutex<VecDeque<&'static str>>,
    check_outcomes: Mutex<VecDeque<StepOutcome>>,
    repair_error: Option<String>,
    /// The candidate's answer.txt at each check run.
    checked: Mutex<Vec<String>>,
    /// (residual, previous turn id) of each repair submission.
    repairs: Mutex<Vec<(String, String)>>,
}

impl FakePorts {
    fn new(draft: &'static str) -> Self {
        Self {
            draft,
            draft_gate: None,
            reviews: Mutex::new(VecDeque::new()),
            check_outcomes: Mutex::new(VecDeque::new()),
            repair_error: None,
            checked: Mutex::new(Vec::new()),
            repairs: Mutex::new(Vec::new()),
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
    fn run_worker(&self, turn: WorkerTurn) -> PortFuture<'_, Result<String, WorkerError>> {
        Box::pin(async move {
            match turn.trigger {
                "pro_contract_draft" => {
                    if let Some(gate) = &self.draft_gate {
                        gate.notified().await;
                    }
                    Ok(self.draft.to_string())
                }
                "pro_contract_review" => self
                    .reviews
                    .lock()
                    .unwrap()
                    .pop_front()
                    .map(str::to_string)
                    .ok_or_else(|| WorkerError::Failed("no scripted review".to_string())),
                other => Err(WorkerError::Failed(format!("unexpected trigger {other}"))),
            }
        })
    }

    fn probe_reference<'a>(
        &'a self,
        _env: &'a CheckEnvironment,
        _reference: &'a str,
    ) -> PortFuture<'a, Result<String, CheckError>> {
        Box::pin(async { Ok("usage: reference".to_string()) })
    }

    fn run_checks<'a>(
        &'a self,
        _env: &'a CheckEnvironment,
        candidate: &'a Path,
        _policy: &'a EvidencePolicy,
    ) -> PortFuture<'a, Result<CheckReceipts, CheckError>> {
        Box::pin(async move {
            let answer = std::fs::read_to_string(candidate.join("answer.txt")).unwrap_or_default();
            self.checked.lock().unwrap().push(answer);
            let outcome = self
                .check_outcomes
                .lock()
                .unwrap()
                .pop_front()
                .ok_or(CheckError::TimedOut)?;
            let detail = match outcome {
                StepOutcome::Pass => String::new(),
                StepOutcome::Fail => "answer.txt does not say done".to_string(),
            };
            Ok(CheckReceipts {
                steps: vec![StepReceipt {
                    step: "build".to_string(),
                    outcome,
                    detail,
                }],
                environment: vec!["fake toolchain".to_string()],
                complete: true,
                environment_digest: Digest::of(b"environment"),
                evaluator_digest: Digest::of(b"evaluator"),
            })
        })
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
            docker: "docker".to_string(),
            image: "unused".to_string(),
            user: "1000:1000".to_string(),
            candidate_mount: "/candidate".to_string(),
            timeout_secs: 60,
            build_command: None,
            candidate_command: None,
        },
        reference_command: None,
    };
    let settings = Settings {
        evaluation: Some(profile.clone()),
        repair_attempts: 1,
        worker: WorkerSettings::default(),
    };
    let ports = Arc::new(ports);
    let thread_id = ThreadId::new();
    let runtime = Arc::new(ThreadRuntime::new(
        thread_id,
        settings,
        profile,
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
    lane.executor_turn("turn-2", "still not").await;
    let status = lane.wait_for("did_not_pass").await;

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
    assert!(lane.ports.checked.lock().unwrap().is_empty());
}

#[tokio::test]
async fn only_the_first_human_turn_is_intake() {
    let lane = lane(FakePorts::new(DECLINED_DRAFT)).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("abstained").await;
    lane.runtime.intake("Another request.".to_string()).await;

    let intake: Option<(String, Digest, crate::CapturePolicy)> = lane
        .ledger
        .record("intake", &lane.thread_id.to_string())
        .await
        .expect("intake record");
    assert_eq!(intake.map(|(text, _, _)| text), Some(INTAKE.to_string()));
}
