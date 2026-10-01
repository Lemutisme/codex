//! Per-thread automation lane: intake → draft → Issue → frozen candidate → checks and review →
//! Support or Defeat → one repair. Every state change is written to the ledger's status record.

use std::collections::HashSet;
use std::future::Future;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::PoisonError;
use std::time::Duration;

use codex_extension_api::ThreadIdleCause;
use codex_pro_contract::AuthenticatedCommand;
use codex_pro_contract::Bindings;
use codex_pro_contract::Command;
use codex_pro_contract::Contract;
use codex_pro_contract::ContractId;
use codex_pro_contract::Coordinate;
use codex_pro_contract::Digest;
use codex_pro_contract::OwnerId;
use codex_pro_contract::Provenance;
use codex_pro_contract::Role;
use codex_pro_contract::Target;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use super::decision::Verdict;
use super::decision::brief_text;
use super::decision::decide;
use super::identity;
use super::ports::Ports;
use super::views::workspace_view;
use crate::BlobStore;
use crate::CapturePolicy;
use crate::CheckReceipts;
use crate::EvaluationProfile;
use crate::EvidencePolicy;
use crate::Ledger;
use crate::Settings;
use crate::Subject;
use crate::Terms;
use crate::capture;
use crate::digest_of;
use crate::materialize;
use crate::workers::drafter;
use crate::workers::reviewer;
use crate::workers::runtime::WorkerTurn;
use codex_pro_contract_store::ExperimentEvent;
use codex_pro_contract_store::ExperimentKind;
use codex_pro_contract_store::Identities;
use codex_pro_contract_store::SubjectBinding;
use codex_pro_contract_store::persist_manifest;

/// Ledger record kind for the per-thread status the runner reads.
pub(crate) const STATUS_KIND: &str = "status";
const CAPTURE_TIMEOUT: Duration = Duration::from_secs(60);
const BASE_VIEW_CAP: usize = 30_000;
const CANDIDATE_VIEW_CAP: usize = 40_000;
const CHECK_SUMMARY_CAP: usize = 15_000;

/// The status record: what the automation lane is doing, and whether it has come to rest.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StatusRecord {
    pub thread_id: String,
    pub contract_id: Option<String>,
    /// `abstained`, `idle`, `drafting`, `working`, `checking`, `repairing`, `supported`,
    /// `did_not_pass` or `not_verified`.
    pub phase: String,
    pub detail: String,
    /// No further automation will happen without new human input.
    pub resting: bool,
    pub repairs_used: u32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Phase {
    #[default]
    Idle,
    Drafting,
    Working,
    Verifying,
    Resting,
}

struct ActiveContract {
    contract: Contract,
    terms: Terms,
    policy: EvidencePolicy,
    brief: String,
}

/// The workspace frozen at the end of the executor's last turn.
struct Frozen {
    turn_id: String,
    subject: Subject,
}

#[derive(Default)]
struct State {
    phase: Phase,
    contract: Option<ActiveContract>,
    frozen: Option<Frozen>,
    /// How the thread last came to rest; cleared when a turn starts.
    last_idle: Option<ThreadIdleCause>,
    proposed_turns: HashSet<String>,
    repairs_used: u32,
}

/// Everything the automation lane needs for one thread.
pub(crate) struct ThreadRuntime {
    thread_id: ThreadId,
    settings: Settings,
    profile: EvaluationProfile,
    capture_policy: CapturePolicy,
    dir: PathBuf,
    ledger: Ledger,
    store: BlobStore,
    ports: Arc<dyn Ports>,
    state: tokio::sync::Mutex<State>,
    tasks: std::sync::Mutex<tokio::task::JoinSet<()>>,
}

/// Where the lane keeps its durable state: the ledger and the content-addressed blobs.
pub(crate) struct Stores {
    pub dir: PathBuf,
    pub ledger: Ledger,
    pub store: BlobStore,
}

/// What the brief section needs to render.
pub(crate) struct BriefView {
    pub contract_id: String,
    pub revision: u32,
    pub text: String,
}

impl ThreadRuntime {
    pub(crate) fn new(
        thread_id: ThreadId,
        settings: Settings,
        profile: EvaluationProfile,
        stores: Stores,
        ports: Arc<dyn Ports>,
    ) -> Self {
        let Stores { dir, ledger, store } = stores;
        let capture_policy = CapturePolicy::standard(profile.excluded_paths.clone());
        Self {
            thread_id,
            settings,
            profile,
            capture_policy,
            dir,
            ledger,
            store,
            ports,
            state: tokio::sync::Mutex::new(State::default()),
            tasks: std::sync::Mutex::new(tokio::task::JoinSet::new()),
        }
    }

    fn spawn(&self, task: impl Future<Output = ()> + Send + 'static) {
        self.tasks
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .spawn(task);
    }

    /// Cancels and joins background work at thread teardown.
    pub(crate) async fn stop(&self) {
        let mut tasks =
            std::mem::take(&mut *self.tasks.lock().unwrap_or_else(PoisonError::into_inner));
        tasks.shutdown().await;
    }

    fn contract_id(&self) -> ContractId {
        ContractId(format!("{}.1", self.thread_id))
    }

    pub(crate) async fn record_status(&self, phase: &str, detail: &str, resting: bool) {
        let (repairs_used, contract_id) = {
            let state = self.state.lock().await;
            (
                state.repairs_used,
                state
                    .contract
                    .as_ref()
                    .map(|active| active.contract.id.0.clone()),
            )
        };
        let status = StatusRecord {
            thread_id: self.thread_id.to_string(),
            contract_id,
            phase: phase.to_string(),
            detail: detail.to_string(),
            resting,
            repairs_used,
        };
        if let Err(error) = self
            .ledger
            .put_record(STATUS_KIND, &self.thread_id.to_string(), &status)
            .await
        {
            tracing::warn!("pro_contract could not record status: {error}");
        }
    }

    async fn rest(&self, phase: &str, detail: &str) {
        self.state.lock().await.phase = Phase::Resting;
        self.record_status(phase, detail, /*resting*/ true).await;
    }

    async fn capture_workspace(&self) -> Result<Subject, String> {
        let root = self.profile.workspace_host_root.clone();
        let policy = self.capture_policy.clone();
        let store = self.store.clone();
        let task = tokio::task::spawn_blocking(move || {
            let subject = capture(&root, &policy, &store)?;
            let manifest = persist_manifest(&subject, &store)?;
            Ok::<_, codex_pro_contract_store::CaptureError>((subject, manifest))
        });
        let (subject, manifest) = match tokio::time::timeout(CAPTURE_TIMEOUT, task).await {
            Ok(Ok(Ok(captured))) => captured,
            Ok(Ok(Err(error))) => return Err(error.to_string()),
            Ok(Err(error)) => return Err(format!("capture task failed: {error}")),
            Err(_) => return Err("capture exceeded its time cap".to_string()),
        };
        let binding = SubjectBinding {
            manifest,
            capture_policy: digest_of("capture_policy", &self.capture_policy),
        };
        self.ledger
            .bind_subject(&subject.subject_hash, &binding)
            .await
            .map_err(|error| error.to_string())?;
        Ok(subject)
    }

    /// Intake at the dispatch of the first human turn: freeze the base, then draft in the
    /// background. Contributes nothing to the executor's context.
    pub(crate) async fn intake(self: &Arc<Self>, text: String) {
        {
            let mut state = self.state.lock().await;
            if state.phase != Phase::Idle {
                return;
            }
            state.phase = Phase::Drafting;
        }
        let base = match self.capture_workspace().await {
            Ok(base) => base,
            Err(error) => {
                self.rest("abstained", &format!("base capture failed: {error}"))
                    .await;
                return;
            }
        };
        self.record_event(
            ExperimentKind::Intake,
            /*check_pipeline*/ None,
            json!({
                "thread_id": self.thread_id.to_string(),
                "text": text,
                "base_subject": base.subject_hash,
                "capture_policy": digest_of("capture_policy", &self.capture_policy),
            }),
        )
        .await;
        self.record_status("drafting", "", /*resting*/ false).await;
        let runtime = Arc::clone(self);
        self.spawn(async move { runtime.draft(text, base).await });
    }

    fn identities(&self, check_pipeline: Option<Digest>) -> Identities {
        identity::identities(&self.ports.worker_identity(), check_pipeline)
    }

    /// Appends an immutable research event stamped with the current producer identities.
    async fn record_event(
        &self,
        kind: ExperimentKind,
        check_pipeline: Option<Digest>,
        body: serde_json::Value,
    ) {
        let event = ExperimentEvent {
            kind,
            identities: self.identities(check_pipeline),
            body,
        };
        if let Err(error) = self.ledger.append_experiment(&event).await {
            tracing::warn!("pro_contract could not record {kind:?}: {error}");
        }
    }

    async fn draft(self: Arc<Self>, text: String, base: Subject) {
        let base_view = workspace_view(&base, &self.store, BASE_VIEW_CAP);
        let reference_observations = match &self.profile.reference_command {
            Some(reference) => {
                match self
                    .ports
                    .probe_reference(&self.profile.check, reference)
                    .await
                {
                    Ok(output) => Some(format!("$ {reference} --help\n{output}")),
                    Err(error) => Some(format!("reference probe failed: {error}")),
                }
            }
            None => None,
        };
        let input = drafter::DraftInput {
            intake_text: &text,
            base_view: &base_view,
            reference_observations: reference_observations.as_deref(),
            reference_command: self.profile.reference_command.as_deref(),
            build_command: self.profile.check.build_command.as_deref(),
            candidate_command: self.profile.check.candidate_command.as_deref(),
        };
        let message = match self
            .run_worker(
                drafter::prompt(&input),
                drafter::schema(),
                "pro_contract_draft",
            )
            .await
        {
            Ok(message) => message,
            Err(error) => {
                self.rest("abstained", &format!("drafter failed: {error}"))
                    .await;
                return;
            }
        };
        self.record_event(
            ExperimentKind::Draft,
            /*check_pipeline*/ None,
            json!({"thread_id": self.thread_id.to_string(), "message": message}),
        )
        .await;
        match drafter::parse(&message, &input) {
            Ok(drafter::Draft::Contract {
                terms,
                evidence_policy,
            }) => self.issue(terms, evidence_policy).await,
            Ok(drafter::Draft::None { reason }) => {
                self.rest("abstained", &format!("drafter declined: {reason}"))
                    .await;
            }
            Err(error) => {
                self.rest("abstained", &format!("draft rejected: {error}"))
                    .await;
            }
        }
    }

    async fn run_worker(
        &self,
        prompt: String,
        schema: serde_json::Value,
        trigger: &'static str,
    ) -> Result<String, crate::WorkerError> {
        self.ports
            .run_worker(WorkerTurn {
                prompt,
                schema,
                trigger,
                deadline: Duration::from_secs(self.settings.worker.deadline_secs),
            })
            .await
    }

    async fn issue(self: Arc<Self>, terms: Terms, policy: EvidencePolicy) {
        let contract_id = self.contract_id();
        let bindings = Bindings {
            terms_hash: digest_of("terms", &terms),
            capture_policy_hash: digest_of("capture_policy", &self.capture_policy),
            evidence_policy_hash: digest_of("evidence_policy", &policy),
        };
        let command = AuthenticatedCommand {
            contract_id: contract_id.clone(),
            expected_version: 0,
            role: Role::Issuer,
            provenance: Provenance::Delegate,
            command: Command::Issue {
                owner: OwnerId("operator".to_string()),
                bindings,
            },
        };
        let contract = match self
            .ledger
            .apply(&command, &format!("issue:{}", contract_id.0))
            .await
        {
            Ok(contract) => contract,
            Err(error) => {
                self.rest("abstained", &format!("issue failed: {error}"))
                    .await;
                return;
            }
        };
        self.record_event(
            ExperimentKind::Issue,
            /*check_pipeline*/ None,
            json!({
                "contract_id": contract_id.0,
                "terms": terms,
                "evidence_policy": policy,
                "capture_policy": digest_of("capture_policy", &self.capture_policy),
            }),
        )
        .await;
        let brief = brief_text(&contract_id.0, contract.revision, &terms, &policy);
        let last_idle = {
            let mut state = self.state.lock().await;
            state.contract = Some(ActiveContract {
                contract,
                terms,
                policy,
                brief,
            });
            state.phase = Phase::Working;
            state.last_idle
        };
        self.record_status("working", "", /*resting*/ false).await;
        // The executor may already have handed off while the contract was being drafted.
        match last_idle {
            Some(ThreadIdleCause::Completed) => self.promote().await,
            Some(cause) => self.executor_stopped(cause).await,
            None => {}
        }
    }

    async fn executor_stopped(&self, cause: ThreadIdleCause) {
        self.rest(
            "not_verified",
            &format!("the executor turn ended without a handoff ({cause:?})"),
        )
        .await;
    }

    pub(crate) async fn brief(&self) -> Option<BriefView> {
        let state = self.state.lock().await;
        state.contract.as_ref().map(|active| BriefView {
            contract_id: active.contract.id.0.clone(),
            revision: active.contract.revision,
            text: active.brief.clone(),
        })
    }

    /// A new turn supersedes whatever the previous one froze.
    pub(crate) async fn turn_started(&self) {
        let mut state = self.state.lock().await;
        state.frozen = None;
        state.last_idle = None;
    }

    /// Freezes the candidate at the turn-end boundary, before completion is emitted.
    pub(crate) async fn turn_stopped(&self, turn_id: String) {
        if !matches!(
            self.state.lock().await.phase,
            Phase::Drafting | Phase::Working
        ) {
            return;
        }
        let frozen = match self.capture_workspace().await {
            Ok(subject) => Some(Frozen { turn_id, subject }),
            Err(error) => {
                tracing::warn!("pro_contract candidate capture failed: {error}");
                None
            }
        };
        self.state.lock().await.frozen = frozen;
    }

    /// The thread came to rest: a completed turn is the executor's handoff.
    pub(crate) async fn thread_idle(self: &Arc<Self>, cause: ThreadIdleCause) {
        let phase = {
            let mut state = self.state.lock().await;
            state.last_idle = Some(cause);
            state.phase
        };
        if phase != Phase::Working {
            return;
        }
        if cause == ThreadIdleCause::Completed {
            let runtime = Arc::clone(self);
            self.spawn(async move { runtime.promote().await });
        } else {
            self.executor_stopped(cause).await;
        }
    }

    /// Promotes the frozen candidate of the last completed turn and verifies it.
    async fn promote(self: Arc<Self>) {
        let handoff = {
            let mut state = self.state.lock().await;
            if state.phase != Phase::Working || state.last_idle != Some(ThreadIdleCause::Completed)
            {
                return;
            }
            match (state.frozen.as_ref(), state.contract.as_ref()) {
                (Some(frozen), _) if state.proposed_turns.contains(&frozen.turn_id) => return,
                (Some(frozen), Some(active)) => {
                    let values = (
                        active.contract.clone(),
                        frozen.subject.clone(),
                        frozen.turn_id.clone(),
                        active.policy.clone(),
                        active.terms.clone(),
                    );
                    state.proposed_turns.insert(values.2.clone());
                    state.phase = Phase::Verifying;
                    Some(values)
                }
                (None, _) => None,
                (Some(_), None) => return,
            }
        };
        let Some((contract, subject, turn_id, policy, terms)) = handoff else {
            self.rest("not_verified", "no candidate was frozen at the handoff")
                .await;
            return;
        };
        self.record_status("checking", "", /*resting*/ false).await;
        let proposed = match self
            .apply(
                &contract,
                Role::Executor,
                Provenance::Automation,
                Command::Propose {
                    subject_hash: subject.subject_hash,
                },
                &format!("propose:{}:{turn_id}", contract.id.0),
            )
            .await
        {
            Ok(contract) => contract,
            Err(error) => {
                self.rest("not_verified", &format!("propose failed: {error}"))
                    .await;
                return;
            }
        };
        self.verify(proposed, subject, turn_id, policy, terms).await;
    }

    async fn apply(
        &self,
        contract: &Contract,
        role: Role,
        provenance: Provenance,
        command: Command,
        key: &str,
    ) -> Result<Contract, crate::LedgerError> {
        let next = self
            .ledger
            .apply(
                &AuthenticatedCommand {
                    contract_id: contract.id.clone(),
                    expected_version: contract.version,
                    role,
                    provenance,
                    command,
                },
                key,
            )
            .await?;
        if let Some(active) = self.state.lock().await.contract.as_mut() {
            active.contract = next.clone();
        }
        Ok(next)
    }

    async fn verify(
        self: Arc<Self>,
        contract: Contract,
        subject: Subject,
        turn_id: String,
        policy: EvidencePolicy,
        terms: Terms,
    ) {
        let work = self
            .dir
            .join("work")
            .join(contract.id.0.replace(['/', '.'], "_"))
            .join(contract.generation.to_string())
            .join("candidate");
        let _ = tokio::fs::remove_dir_all(&work).await;
        let materialized = {
            let (subject, store, work) = (subject.clone(), self.store.clone(), work.clone());
            tokio::task::spawn_blocking(move || {
                std::fs::create_dir_all(&work)
                    .map_err(|error| error.to_string())
                    .and_then(|()| {
                        materialize(&subject, &store, &work).map_err(|error| error.to_string())
                    })
            })
            .await
            .map_err(|error| error.to_string())
            .and_then(|result| result)
        };
        if let Err(error) = materialized {
            self.rest("not_verified", &format!("materialization failed: {error}"))
                .await;
            return;
        }
        let checks = self
            .ports
            .run_checks(&self.profile.check, &work, &policy)
            .await;
        let all_passed = checks.as_ref().is_ok_and(|receipts| {
            receipts.complete
                && receipts
                    .steps
                    .iter()
                    .all(|step| step.outcome == crate::StepOutcome::Pass)
        });
        let review = if all_passed {
            let receipts = checks.as_ref().ok();
            let summary = receipts.map(render_receipts).unwrap_or_default();
            let view = workspace_view(&subject, &self.store, CANDIDATE_VIEW_CAP);
            let input = reviewer::ReviewInput {
                terms: &terms,
                check_summary: &crate::workers::bounded(&summary, CHECK_SUMMARY_CAP),
                candidate_view: &view,
            };
            let message = self
                .run_worker(
                    reviewer::prompt(&input),
                    reviewer::schema(),
                    "pro_contract_review",
                )
                .await;
            Some(message.and_then(|message| reviewer::parse(&message, &terms)))
        } else {
            None
        };
        let verdict = decide(&checks, review.as_ref(), &policy);
        let (verdict_name, detail) = match &verdict {
            Verdict::Support => ("support", ""),
            Verdict::Defeat { residual } => ("defeat", residual.as_str()),
            Verdict::NotVerified { reason } => ("not_verified", reason.as_str()),
        };
        self.record_event(
            ExperimentKind::Verification,
            checks
                .as_ref()
                .ok()
                .map(|receipts| receipts.evaluator_digest),
            json!({
                "contract_id": contract.id.0,
                "generation": contract.generation,
                "subject_hash": subject.subject_hash,
                "verdict": verdict_name,
                "detail": detail,
                "receipts": checks.as_ref().ok(),
                "check_error": checks.as_ref().err().map(ToString::to_string),
                "review": review.as_ref().and_then(|review| review.as_ref().ok()),
            }),
        )
        .await;
        match verdict {
            Verdict::Support => self.support(contract, &subject, checks.ok(), review).await,
            Verdict::Defeat { residual } => {
                self.defeat(contract, &subject, residual, turn_id).await
            }
            Verdict::NotVerified { reason } => self.rest("not_verified", &reason).await,
        }
    }

    async fn support(
        &self,
        contract: Contract,
        subject: &Subject,
        receipts: Option<CheckReceipts>,
        review: Option<Result<reviewer::ReviewVerdict, crate::WorkerError>>,
    ) {
        let Some(receipts) = receipts else {
            self.rest("not_verified", "support without receipts").await;
            return;
        };
        let review = review.and_then(Result::ok);
        let evidence_hash = digest_of("evidence", &(&receipts, &review));
        let worker = self.ports.worker_identity();
        let evaluator_digest = digest_of(
            "evaluator",
            &(
                receipts.evaluator_digest,
                reviewer::policy_digest(),
                &worker.model,
                &worker.effort,
            ),
        );
        let coordinate = Coordinate {
            contract_id: contract.id.clone(),
            revision: contract.revision,
            terms_hash: contract.bindings.terms_hash,
            generation: contract.generation,
            subject_hash: subject.subject_hash,
            capture_policy_hash: contract.bindings.capture_policy_hash,
            evidence_policy_hash: contract.bindings.evidence_policy_hash,
            environment_digest: receipts.environment_digest,
            evaluator_digest,
            evidence_hash,
        };
        let certificate = digest_of("certificate", &(&coordinate, &receipts, &review));
        match self
            .apply(
                &contract,
                Role::Verifier,
                Provenance::Automation,
                Command::Support {
                    certificate,
                    coordinate,
                },
                &format!("support:{}:{}", contract.id.0, contract.generation),
            )
            .await
        {
            Ok(_) => {
                self.rest("supported", "checks passed · review supported")
                    .await
            }
            Err(error) => {
                self.rest("not_verified", &format!("support failed: {error}"))
                    .await
            }
        }
    }

    async fn defeat(
        &self,
        contract: Contract,
        subject: &Subject,
        residual: String,
        turn_id: String,
    ) {
        let defeated = self
            .apply(
                &contract,
                Role::Verifier,
                Provenance::Automation,
                Command::Defeat {
                    target: Target::Candidate {
                        generation: contract.generation,
                        subject_hash: subject.subject_hash,
                    },
                    defeater: digest_of("defeater", &residual),
                },
                &format!("defeat:{}:{}", contract.id.0, contract.generation),
            )
            .await;
        if let Err(error) = defeated {
            self.rest("not_verified", &format!("defeat failed: {error}"))
                .await;
            return;
        }
        let allowance_left = self.state.lock().await.repairs_used < self.settings.repair_attempts;
        if !allowance_left {
            self.rest("did_not_pass", &residual).await;
            return;
        }
        {
            // Working before the repair turn starts, so its end is frozen however fast it is.
            let mut state = self.state.lock().await;
            state.repairs_used += 1;
            state.phase = Phase::Working;
        }
        match self.ports.submit_repair(residual.clone(), turn_id).await {
            Ok(()) => {
                self.record_status("repairing", &residual, /*resting*/ false)
                    .await;
            }
            Err(reason) => {
                self.rest(
                    "did_not_pass",
                    &format!("repair could not start: {reason}\n{residual}"),
                )
                .await;
            }
        }
    }
}

fn render_receipts(receipts: &CheckReceipts) -> String {
    let mut text = format!("environment: {}\n", receipts.environment.join(" | "));
    for step in &receipts.steps {
        text.push_str(&format!("{}: {:?}\n", step.step, step.outcome));
        if !step.detail.is_empty() {
            text.push_str(&crate::workers::bounded(&step.detail, 800));
            text.push('\n');
        }
    }
    text
}

#[cfg(test)]
#[path = "automation_tests.rs"]
mod tests;
