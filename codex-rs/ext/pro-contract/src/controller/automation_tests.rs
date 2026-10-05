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
    /// The prober's second turn; `None` makes the prober fail.
    probe: Option<&'static str>,
    /// How many sealed cases pass in each check run; the rest fail.
    sealed_passing: usize,
    /// The sealed cases each check run received.
    sealed_checked: Mutex<Vec<Vec<DifferentialCase>>>,
    reviews: Mutex<VecDeque<&'static str>>,
    check_outcomes: Mutex<VecDeque<StepOutcome>>,
    repair_error: Option<String>,
    worker_model: &'static str,
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
            probe: Some(PROBE),
            sealed_passing: usize::MAX,
            sealed_checked: Mutex::new(Vec::new()),
            reviews: Mutex::new(VecDeque::new()),
            check_outcomes: Mutex::new(VecDeque::new()),
            repair_error: None,
            worker_model: "model-a",
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
                "pro_contract_explore" => Ok(EXPLORATION.to_string()),
                "pro_contract_probe" => self
                    .probe
                    .map(str::to_string)
                    .ok_or_else(|| WorkerError::Failed("the prober failed".to_string())),
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

    fn observe<'a>(
        &'a self,
        _env: &'a CheckEnvironment,
        base: &'a Path,
        _reference: &'a str,
        cases: &'a [DifferentialCase],
    ) -> PortFuture<'a, Result<Vec<Observation>, CheckError>> {
        Box::pin(async move {
            assert!(
                base.join("answer.txt").exists(),
                "observations run over the base"
            );
            Ok(cases
                .iter()
                .map(|case| Observation {
                    id: case.id.clone(),
                    exit: Some(0),
                    stable: true,
                    stdout: "usage: reference\n".to_string(),
                    stderr: String::new(),
                })
                .collect())
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
                StepOutcome::Pass | StepOutcome::Unqualified => String::new(),
            };
            let mut steps = vec![StepReceipt::new("build", outcome, detail)];
            steps.extend(policy.sealed.iter().enumerate().map(|(index, case)| {
                let outcome = if index < self.sealed_passing {
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
        evaluation: Some(profile.clone()),
        repair_attempts: 1,
        worker: WorkerSettings::default(),
        evidence: EvidenceSettings {
            sealed_threshold_permille: 750,
            min_sealed_qualified: 4,
            min_success_permille: 500,
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
            ExperimentKind::Verification
        ]
    );
    let verification = &events[3].event;
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
            ExperimentKind::Draft,
            ExperimentKind::Issue,
            ExperimentKind::Verification
        ]
    );
    let issue = &events[3].event.body;
    assert_eq!(
        issue["evidence_policy"]["sealed"].as_array().map(Vec::len),
        Some(4)
    );
    assert_eq!(issue["evidence_policy"]["sealed_threshold_permille"], 750);
    let verification = &events[4].event;
    assert_eq!(verification.body["sealed"]["qualified"], 4);
    assert!(verification.identities.policies.contains_key("prober"));
    let default = crate::workers::policies::Policies::default();
    assert_eq!(
        verification.identities.policies["bundle"],
        crate::digest_of(
            "policy_bundle",
            &serde_json::json!([default.drafter, default.prober, default.reviewer]),
        ),
        "a controller can recompute the bundle identity from the files"
    );
    let probe = &events[1].event.body;
    assert_eq!(probe["exploration"][0]["id"], "e1");
    assert_eq!(probe["observations"][0]["stdout"], "usage: reference\n");
}

#[tokio::test]
async fn a_failed_prober_still_issues_but_cannot_support() {
    let mut ports = FakePorts::new(CONTRACT_DRAFT)
        .checks(&[StepOutcome::Pass])
        .reviews(&[SUPPORT_REVIEW]);
    ports.probe = None;
    let lane = reference_lane(ports).await;

    lane.runtime.intake(INTAKE.to_string()).await;
    lane.wait_for("working").await;
    lane.executor_turn("turn-1", "done").await;
    let status = lane.wait_for("not_verified").await;

    assert_eq!(status.class, "insufficient_evidence");
    assert!(status.detail.contains("0 of 0 qualified"), "{status:?}");
    // The mechanical evidence decided; the reviewer was never asked.
    assert_eq!(lane.ports.reviews.lock().unwrap().len(), 1);
    let events = lane.ledger.experiments().await.expect("events");
    let probe = events
        .iter()
        .find(|record| record.event.kind == ExperimentKind::Probe)
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
