//! Per-thread automation lane: intake → draft and probe → Issue → frozen candidate → checks and
//! review → judgment and evidence readiness → bounded continuation. Authority is kernel-owned;
//! public working evidence is retained independently of executor history and status summaries.

mod continuation;
mod delivery;
mod preparation;
mod progress;
mod recovery;
mod succession;
mod verification;
pub(crate) use progress::ProgressAssessment;

use std::collections::HashSet;
use std::future::Future;
use std::path::Path;
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
use codex_pro_contract::Digest;
use codex_pro_contract::OwnerId;
use codex_pro_contract::Provenance;
use codex_pro_contract::Role;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use super::decision::NotVerifiedClass;
use super::decision::brief_text;
use super::identity;
use super::ports::Ports;
use super::views::ViewOrder;
use super::views::ViewPolicy;
use super::views::workspace_view;
use crate::BlobStore;
use crate::CapturePolicy;
use crate::DifferentialCase;
use crate::EvaluationProfile;
use crate::EvidencePolicy;
use crate::Ledger;
use crate::Observation;
use crate::Settings;
use crate::Subject;
use crate::Terms;
use crate::capture;
use crate::digest_of;
use crate::materialize;
use crate::workers::cases;
use crate::workers::drafter;
use crate::workers::policies::Policies;
use crate::workers::prober;
use crate::workers::runtime::WorkerTurn;
use codex_pro_contract_store::ExperimentEvent;
use codex_pro_contract_store::ExperimentKind;
use codex_pro_contract_store::Identities;
use codex_pro_contract_store::SubjectBinding;
use codex_pro_contract_store::persist_manifest;

/// Ledger record kind for the per-thread status the runner reads.
pub(crate) const STATUS_KIND: &str = "status";
const CAPTURE_TIMEOUT: Duration = Duration::from_secs(60);
const BASE_VIEW: ViewPolicy = ViewPolicy {
    cap: 30_000,
    order: ViewOrder::DocumentationFirst,
};

/// The status record: what the automation lane is doing, and whether it has come to rest.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StatusRecord {
    pub thread_id: String,
    pub contract_id: Option<String>,
    /// `abstained`, `idle`, `drafting`, `working`, `checking`, `repairing`, `supported`,
    /// `deciding`, `succeeding`, `did_not_pass` or `not_verified`.
    pub phase: String,
    pub detail: String,
    /// The controller has no scheduled action. This is not task completion:
    /// an authorized caller can start another turn under the same responsibility.
    pub resting: bool,
    pub repairs_used: u32,
    /// Why the lane rests `not_verified` (`infrastructure`, `insufficient_evidence`,
    /// `reviewer_unable`, `execution_interrupted`, `terms_gap` or `no_handoff`); empty otherwise.
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub class: String,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Phase {
    #[default]
    Idle,
    Drafting,
    Working,
    Verifying,
    Resting,
    RecoveryBlocked,
    Succeeding,
}

struct ActiveContract {
    contract: Contract,
    terms: Terms,
    policy: EvidencePolicy,
    brief: String,
    base: Base,
}

/// The workspace as it was at intake: every case runs over it, and evidence depends on it.
#[derive(Clone)]
struct Base {
    dir: PathBuf,
    subject: Digest,
}

/// Everything verification needs about one handoff.
struct Handoff {
    response: delivery::ResponseCapture,
    epoch: u64,
    contract: Contract,
    subject: Subject,
    turn_id: String,
    policy: EvidencePolicy,
    terms: Terms,
    base: Base,
}

/// The workspace frozen at the end of the executor's last turn.
#[derive(Clone)]
struct Frozen {
    response: delivery::ResponseCapture,
    turn_id: String,
    subject: Subject,
}

#[derive(Default)]
struct State {
    phase: Phase,
    /// Durable original intake, independent of optional model-authored contract terms.
    admission: Option<Digest>,
    delivered_turns: HashSet<String>,
    contract: Option<ActiveContract>,
    /// Retain the responsibility identity even when its execution data cannot be recovered.
    recovered_contract_id: Option<ContractId>,
    frozen: Option<Frozen>,
    /// How the thread last came to rest; cleared when a turn starts.
    last_idle: Option<ThreadIdleCause>,
    proposed_turns: HashSet<String>,
    repairs_used: u32,
    /// The note of the repair turn in flight; compaction drops the copy in history.
    repair_note: Option<String>,
    epoch: u64,
    successor: Option<succession::Control>,
    deadline_watch: bool,
}

/// Everything the automation lane needs for one thread.
pub(crate) struct ThreadRuntime {
    thread_id: ThreadId,
    settings: Settings,
    profile: EvaluationProfile,
    capture_policy: CapturePolicy,
    /// The worker instructions of the running version's policy bundle.
    policies: Policies,
    dir: PathBuf,
    ledger: Ledger,
    store: BlobStore,
    ports: Arc<dyn Ports>,
    state: tokio::sync::Mutex<State>,
    state_changed: tokio::sync::watch::Sender<()>,
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
    pub(super) fn work_method(&self) -> &str {
        &self.policies.work_method
    }

    pub(super) fn input_capabilities(&self) -> Vec<serde_json::Value> {
        self.profile.check.input_capabilities()
    }
    pub(crate) fn new(
        thread_id: ThreadId,
        settings: Settings,
        profile: EvaluationProfile,
        policies: Policies,
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
            policies,
            dir,
            ledger,
            store,
            ports,
            state: tokio::sync::Mutex::new(State::default()),
            state_changed: tokio::sync::watch::channel(()).0,
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
        self.cancel_successor().await;
        let mut tasks =
            std::mem::take(&mut *self.tasks.lock().unwrap_or_else(PoisonError::into_inner));
        tasks.shutdown().await;
    }

    fn contract_id(&self) -> ContractId {
        ContractId(format!("{}.1", self.thread_id))
    }

    pub(super) fn evidence_access(&self) -> super::archive::EvidenceAccess {
        super::archive::EvidenceAccess {
            contract_id: self.contract_id(),
            ledger: self.ledger.clone(),
            store: self.store.clone(),
            observations: Default::default(),
        }
    }

    pub(crate) async fn record_status(&self, phase: &str, detail: &str, resting: bool) {
        self.write_status(phase, "", detail, resting).await;
    }

    async fn write_status(&self, phase: &str, class: &str, detail: &str, resting: bool) {
        let (repairs_used, contract_id) = {
            let state = self.state.lock().await;
            (
                state.repairs_used,
                state
                    .contract
                    .as_ref()
                    .map(|active| active.contract.id.clone())
                    .or_else(|| state.recovered_contract_id.clone())
                    .map(|id| id.0),
            )
        };
        let status = StatusRecord {
            thread_id: self.thread_id.to_string(),
            contract_id,
            phase: phase.to_string(),
            detail: detail.to_string(),
            resting,
            repairs_used,
            class: class.to_string(),
        };
        if let Err(error) = self
            .ledger
            .put_record(STATUS_KIND, &self.thread_id.to_string(), &status)
            .await
        {
            tracing::warn!("pro_contract could not record status: {error}");
        }
        self.state_changed.send_replace(());
    }

    async fn rest(&self, phase: &str, detail: &str) {
        self.state.lock().await.phase = Phase::Resting;
        self.record_status(phase, detail, /*resting*/ true).await;
    }

    /// Rests without a judgment, recording why.
    async fn not_verified(&self, class: NotVerifiedClass, detail: &str) {
        self.state.lock().await.phase = Phase::Resting;
        self.write_status(
            "not_verified",
            class.as_str(),
            detail,
            /*resting*/ true,
        )
        .await;
    }

    /// Where this contract's materialized subjects live.
    fn work_dir(&self) -> PathBuf {
        self.dir
            .join("work")
            .join(self.contract_id().0.replace(['/', '.'], "_"))
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
        // Progress needs durable task identity/accounting, not permission to replace
        // executors or a finite lifetime. Preserve legacy same-thread repair when
        // succession is absent; the fallback grant admits no fresh executors.
        let task_grant = self.settings.succession.clone().or_else(|| {
            self.settings
                .progress
                .as_ref()
                .map(|_| crate::SuccessionSettings {
                    max_sessions: Some(0),
                    total_secs: None,
                })
        });
        if let Some(grant) = task_grant {
            let budget = super::succession_budget::now_ms()
                .and_then(|now| super::succession_budget::Budget::new(grant, now));
            let admitted = match budget {
                Ok(budget) => {
                    budget
                        .replace(
                            &self.ledger,
                            &self.thread_id.to_string(),
                            /*previous*/ None,
                        )
                        .await
                }
                Err(reason) => Err(reason),
            };
            if let Err(reason) = admitted {
                self.rest("abstained", &reason).await;
                return;
            }
        }
        let base = match self.capture_workspace().await {
            Ok(base) => base,
            Err(error) => {
                self.rest("abstained", &format!("base capture failed: {error}"))
                    .await;
                return;
            }
        };
        let admitted = self
            .append_event(
                ExperimentKind::Intake,
                /*check_pipeline*/ None,
                json!({
                    "thread_id": self.thread_id.to_string(),
                    "text": text,
                    "base_subject": base.subject_hash,
                    "capture_policy": digest_of("capture_policy", &self.capture_policy),
                    "progress": self.settings.progress,
                }),
            )
            .await;
        match admitted {
            Ok(receipt) => self.state.lock().await.admission = Some(receipt),
            Err(reason) => {
                self.not_verified(
                    NotVerifiedClass::Infrastructure,
                    &format!("task intake was not committed: {reason}"),
                )
                .await;
                return;
            }
        }
        if let Err(reason) = self.initialize_progress().await {
            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        self.arm_deadline().await;
        self.record_status("drafting", "", /*resting*/ false).await;
        let runtime = Arc::clone(self);
        self.spawn(async move { runtime.draft(text, base).await });
    }

    fn identities(&self, check_pipeline: Option<Digest>) -> Identities {
        identity::identities(
            &self.ports.worker_identity(),
            &self.policies,
            check_pipeline,
        )
    }

    /// Appends an immutable research event stamped with the current producer identities.
    async fn record_event(
        &self,
        kind: ExperimentKind,
        check_pipeline: Option<Digest>,
        body: serde_json::Value,
    ) {
        if let Err(error) = self.append_event(kind, check_pipeline, body).await {
            tracing::warn!("pro_contract could not record {kind:?}: {error}");
        }
    }

    async fn append_event(
        &self,
        kind: ExperimentKind,
        check_pipeline: Option<Digest>,
        body: serde_json::Value,
    ) -> Result<Digest, String> {
        let event = ExperimentEvent {
            kind,
            identities: self.identities(check_pipeline),
            body,
        };
        self.ledger
            .append_experiment(&event)
            .await
            .map(|record| record.hash)
            .map_err(|e| e.to_string())
    }

    async fn draft(self: Arc<Self>, text: String, base: Subject) {
        let base_dir = self.work_dir().join("base");
        if let Err(error) = self.materialize(&base, &base_dir).await {
            self.rest(
                "abstained",
                &format!("base materialization failed: {error}"),
            )
            .await;
            return;
        }
        let reference_help = match &self.profile.reference_command {
            Some(reference) => Some(self.reference_help(reference, &base_dir).await),
            None => None,
        };
        let base_view = workspace_view(&base, &self.store, BASE_VIEW);
        let input = drafter::DraftInput {
            instructions: &self.policies.drafter,
            intake_text: &text,
            base_view: &base_view,
            reference_observations: reference_help.as_deref(),
            reference_command: self.profile.reference_command.as_deref(),
            build_command: self.profile.check.build_command.as_deref(),
            candidate_command: self.profile.check.candidate_command.as_deref(),
        };
        // The prober is independent of the drafter: both start from the same request.
        let (message, sealed) = tokio::join!(
            self.run_worker(
                drafter::prompt(&input),
                drafter::schema_for(&text),
                "pro_contract_draft",
            ),
            self.probe(&text, &base, &base_dir, reference_help.as_deref()),
        );
        let message = match message {
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
            }) => {
                let (sealed, preparation_failure) = match sealed {
                    Ok(cases) => (cases, None),
                    Err(error) => (
                        Vec::new(),
                        Some(format!("evidence preparation failed: {error}")),
                    ),
                };
                let evidence = self.settings.evidence;
                let mut policy = EvidencePolicy {
                    sealed,
                    preparation_failure,
                    sealed_threshold_permille: evidence.sealed_threshold_permille,
                    min_sealed_qualified: evidence.min_sealed_qualified,
                    min_success_permille: evidence.min_success_permille,
                    ..*evidence_policy
                };
                if policy.preparation_failure.is_none() {
                    policy.preparation_failure = self.calibrate(&policy, &base_dir).await;
                }
                let base = Base {
                    dir: base_dir,
                    subject: base.subject_hash,
                };
                self.issue(terms, policy, base).await
            }
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

    /// Writes `subject` into a fresh `dir`.
    async fn materialize(&self, subject: &Subject, dir: &Path) -> Result<(), String> {
        let _ = tokio::fs::remove_dir_all(dir).await;
        let (subject, store, dir) = (subject.clone(), self.store.clone(), dir.to_path_buf());
        tokio::task::spawn_blocking(move || {
            std::fs::create_dir_all(&dir)
                .map_err(|error| error.to_string())
                .and_then(|()| {
                    materialize(&subject, &store, &dir).map_err(|error| error.to_string())
                })
        })
        .await
        .map_err(|error| error.to_string())
        .and_then(|result| result)
    }

    /// The reference's `--help`, observed over the base workspace, as worker-readable text.
    async fn reference_help(&self, reference: &str, base_dir: &Path) -> String {
        let help = vec![DifferentialCase {
            id: "help".to_string(),
            args: vec!["--help".to_string()],
            ..Default::default()
        }];
        match self.observe_bounded(base_dir, reference, &help).await {
            Ok(observations) => {
                cases::render_observations(&help, &observations, prober::REFERENCE_HELP_CAP)
            }
            Err(error) => format!("reference probe failed: {error}"),
        }
    }

    /// A failed prober is not an empty successful suite. Preserve its failure in the policy.
    async fn probe(
        &self,
        text: &str,
        base: &Subject,
        base_dir: &Path,
        reference_help: Option<&str>,
    ) -> Result<Vec<DifferentialCase>, prober::ProbeFailure> {
        let (Some(reference), Some(_)) = (
            self.profile.reference_command.as_deref(),
            self.profile.check.candidate_command.as_deref(),
        ) else {
            return Ok(Vec::new());
        };
        let base_view = workspace_view(base, &self.store, prober::BASE_VIEW);
        let input = prober::ProbeInput {
            instructions: &self.policies.prober,
            intake_text: text,
            base_view: &base_view,
            reference_help: reference_help.unwrap_or_default(),
        };
        let outcome = self.run_probe(&input, base_dir, reference).await;
        let thread_id = self.thread_id.to_string();
        let body = match &outcome {
            Ok((exploration, observations, probe)) => json!({
                "thread_id": thread_id,
                "exploration": exploration,
                "observations": observations,
                "coverage_plan": probe.coverage_plan,
                "cases": probe.cases,
            }),
            Err(error) => {
                json!({"thread_id": thread_id, "stage": error.stage, "error": error.to_string()})
            }
        };
        self.record_event(ExperimentKind::Probe, /*check_pipeline*/ None, body)
            .await;
        outcome.map(|(_, _, probe)| probe.cases)
    }

    /// Explores the reference, then writes the sealed suite knowing how it behaves.
    async fn run_probe(
        &self,
        input: &prober::ProbeInput<'_>,
        base_dir: &Path,
        reference: &str,
    ) -> Result<(Vec<DifferentialCase>, Vec<Observation>, prober::Probe), prober::ProbeFailure>
    {
        let exploration = self
            .probe_stage(input, None, prober::parse_exploration)
            .await?;
        // An intentionally empty exploration can write from documentation. A
        // failed reference execution is a different state and must stay visible.
        let observations = self
            .observe_bounded(base_dir, reference, &exploration)
            .await
            .map_err(|error| prober::ProbeFailure {
                stage: "reference_observation",
                source: crate::WorkerError::Failed(error.to_string()),
            })?;
        self.append_event(
            ExperimentKind::Probe,
            None,
            json!({
                "thread_id":self.thread_id.to_string(), "phase":"reference_observation",
                "observations":observations.observations, "complete":observations.complete,
                "execution":observations.execution,
            }),
        )
        .await
        .map_err(|error| prober::ProbeFailure {
            stage: "reference_observation",
            source: crate::WorkerError::Failed(error),
        })?;
        if observations
            .execution
            .as_ref()
            .is_some_and(|run| !run.shutdown_confirmed)
        {
            return Err(prober::ProbeFailure {
                stage: "reference_observation",
                source: crate::WorkerError::Failed(
                    "reference action shutdown is unconfirmed; reconcile before another action"
                        .into(),
                ),
            });
        }
        let observed = format!(
            "Reference action complete={}. Missing invocations are unobserved, not passes. Restore invocation capability before expanding variants.\n{}",
            observations.complete,
            cases::render_observations(&exploration, &observations, prober::OBSERVATIONS_CAP)
        );
        let minimum = self.settings.evidence.min_sealed_qualified;
        let probe = self
            .probe_stage(input, Some(&observed), |message| {
                let probe = prober::parse_probe(message)?;
                if let Some(minimum) = minimum
                    && probe.cases.len() < minimum as usize
                {
                    return Err(crate::WorkerError::Malformed(format!(
                        "sealed suite has {} cases; at least {minimum} are required before Issue",
                        probe.cases.len(),
                    )));
                }
                Ok(probe)
            })
            .await?;
        Ok((exploration, observations.observations, probe))
    }

    /// One correction turn for malformed structured output. Transport, timeout and
    /// input-budget failures are terminal; retries never grow the execution grant.
    async fn probe_stage<T>(
        &self,
        input: &prober::ProbeInput<'_>,
        observations: Option<&str>,
        parse: impl Fn(&str) -> Result<T, crate::WorkerError>,
    ) -> Result<T, prober::ProbeFailure> {
        let stage = if observations.is_some() {
            "sealed"
        } else {
            "exploration"
        };
        let mut correction = String::new();
        for attempt in 1..=2 {
            let instructions = format!("{}\n{correction}", input.instructions);
            let corrected = prober::ProbeInput {
                instructions: &instructions,
                ..*input
            };
            let prompt = match observations {
                Some(observed) => prober::write_prompt(&corrected, observed),
                None => prober::explore_prompt(&corrected),
            }
            .map_err(|source| prober::ProbeFailure { stage, source })?;
            let (schema, trigger) = if observations.is_some() {
                (prober::write_schema(), "pro_contract_probe")
            } else {
                (prober::explore_schema(), "pro_contract_explore")
            };
            let outcome = self
                .run_worker(prompt, schema, trigger)
                .await
                .and_then(|message| parse(&message));
            match outcome {
                Ok(value) => return Ok(value),
                Err(error @ crate::WorkerError::Malformed(_)) if attempt == 1 => {
                    self.record_event(
                        ExperimentKind::Probe,
                        None,
                        json!({
                            "thread_id": self.thread_id.to_string(), "phase": "correction",
                            "stage": stage, "attempt": attempt, "error": error.to_string(),
                        }),
                    )
                    .await;
                    correction = format!(
                        "The previous {stage} response was rejected: {}. Correct that error and return only this stage's JSON; do not produce the other stage's cases.",
                        crate::workers::bounded(&error.to_string(), 1200),
                    );
                }
                Err(source) => return Err(prober::ProbeFailure { stage, source }),
            }
        }
        unreachable!("the final attempt returns its outcome")
    }

    async fn observe_bounded(
        &self,
        base: &Path,
        reference: &str,
        cases: &[DifferentialCase],
    ) -> Result<crate::ObservationBatch, crate::CheckError> {
        let mut environment = self.profile.check.clone();
        environment.timeout_secs = self
            .action_seconds(None, environment.timeout_secs)
            .await
            .map_err(crate::CheckError::Launch)?;
        self.ports
            .observe(&environment, base, reference, cases)
            .await
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
                deadline: Duration::from_secs(
                    self.action_seconds(None, self.settings.worker.deadline_secs)
                        .await
                        .map_err(crate::WorkerError::Start)?,
                ),
                evidence: None,
            })
            .await
    }

    async fn issue(self: Arc<Self>, terms: Terms, policy: EvidencePolicy, base: Base) {
        // Issue freezes the obligation and its actual evidential limits. It does not assert
        // that preparation succeeded; an explicit preparation failure can never grant Support.
        let contract_id = self.contract_id();
        let bindings = Bindings {
            terms_hash: digest_of("terms", &terms),
            capture_policy_hash: digest_of("capture_policy", &self.capture_policy),
            evidence_policy_hash: digest_of("evidence_policy", &policy),
        };
        if let Err(reason) = self.action_seconds(None, 1).await {
            self.not_verified(NotVerifiedClass::BudgetExhausted, &reason)
                .await;
            return;
        }
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
        let committed = self
            .append_event(
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
        if let Err(reason) = committed {
            self.state.lock().await.recovered_contract_id = Some(contract_id);
            self.not_verified(
                NotVerifiedClass::Infrastructure,
                &format!("issued terms were not committed: {reason}"),
            )
            .await;
            return;
        }
        let brief = brief_text(&contract_id.0, contract.revision, &terms, &policy);
        let last_idle = {
            let mut state = self.state.lock().await;
            state.contract = Some(ActiveContract {
                contract,
                terms,
                policy,
                brief,
                base,
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
        self.not_verified(
            if cause == ThreadIdleCause::Failed {
                NotVerifiedClass::ExecutionInterrupted
            } else {
                NotVerifiedClass::NoHandoff
            },
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

    pub(crate) async fn admitted(&self) -> bool {
        self.state.lock().await.admission.is_some()
    }

    /// The repair note the executor has not yet answered with a handoff.
    pub(crate) async fn outstanding_repair(&self) -> Option<String> {
        let state = self.state.lock().await;
        state
            .repair_note
            .clone()
            .filter(|_| state.phase == Phase::Working)
    }

    /// A new turn supersedes whatever the previous one froze.
    pub(crate) async fn turn_started(self: &Arc<Self>) -> u64 {
        self.cancel_successor().await;
        self.arm_deadline().await;
        let (continuing, epoch) = {
            let mut state = self.state.lock().await;
            let continuing = state.phase == Phase::Resting
                && state.contract.as_ref().is_some_and(|active| {
                    active.contract.standing == codex_pro_contract::Standing::Outstanding
                });
            if continuing {
                state.phase = Phase::Working;
            }
            state.frozen = None;
            state.last_idle = None;
            (continuing, state.epoch)
        };
        if continuing {
            self.record_status(
                "working",
                "continuing the existing responsibility",
                /*resting*/ false,
            )
            .await;
        }
        epoch
    }

    /// Freezes the candidate at the turn-end boundary, before completion is emitted.
    #[cfg(test)]
    pub(crate) async fn turn_stopped(&self, turn_id: String) {
        self.turn_stopped_with_message(turn_id, None).await;
    }

    pub(crate) async fn turn_stopped_with_message(&self, turn_id: String, message: Option<&str>) {
        let epoch = {
            let state = self.state.lock().await;
            if state.admission.is_none()
                || matches!(state.phase, Phase::RecoveryBlocked | Phase::Succeeding)
            {
                return;
            }
            state.epoch
        };
        let frozen = match self.capture_workspace().await {
            Ok(subject) => {
                let response = self.capture_response(&subject, &turn_id, message);
                Some(Frozen {
                    turn_id,
                    subject,
                    response,
                })
            }
            Err(error) => {
                tracing::warn!("pro_contract candidate capture failed: {error}");
                None
            }
        };
        let mut state = self.state.lock().await;
        if state.epoch == epoch {
            state.frozen = frozen;
        }
    }

    /// The thread came to rest: a completed turn is the executor's handoff.
    pub(crate) async fn thread_idle(self: &Arc<Self>, cause: ThreadIdleCause) {
        self.thread_idle_for(cause, None).await;
    }

    pub(crate) async fn turn_aborted(self: &Arc<Self>, epoch: u64) {
        self.thread_idle_for(ThreadIdleCause::Interrupted, Some(epoch))
            .await;
    }

    async fn thread_idle_for(self: &Arc<Self>, cause: ThreadIdleCause, owner: Option<u64>) {
        if cause == ThreadIdleCause::Completed
            && let Err(reason) = self.commit_delivery().await
        {
            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        let phase = {
            let mut state = self.state.lock().await;
            if owner.is_some_and(|epoch| epoch != state.epoch) {
                return;
            }
            state.last_idle = Some(cause);
            state.phase
        };
        if phase == Phase::Succeeding && cause != ThreadIdleCause::Completed {
            self.cancel_successor().await;
            self.executor_stopped(cause).await;
            return;
        }
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
                    let values = Handoff {
                        response: frozen.response.clone(),
                        epoch: state.epoch,
                        contract: active.contract.clone(),
                        subject: frozen.subject.clone(),
                        turn_id: frozen.turn_id.clone(),
                        policy: active.policy.clone(),
                        terms: active.terms.clone(),
                        base: active.base.clone(),
                    };
                    state.proposed_turns.insert(values.turn_id.clone());
                    state.phase = Phase::Verifying;
                    state.repair_note = None;
                    Some(values)
                }
                (None, _) => None,
                (Some(_), None) => return,
            }
        };
        let Some(handoff) = handoff else {
            self.not_verified(
                NotVerifiedClass::NoHandoff,
                "no candidate was frozen at the handoff",
            )
            .await;
            return;
        };
        let contract = handoff.contract.clone();
        let (subject, turn_id) = (handoff.subject.clone(), handoff.turn_id.clone());
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
                self.not_verified(
                    NotVerifiedClass::Infrastructure,
                    &format!("propose failed: {error}"),
                )
                .await;
                return;
            }
        };
        self.verify(Handoff {
            contract: proposed,
            ..handoff
        })
        .await;
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
}

#[cfg(test)]
#[path = "automation_tests.rs"]
mod tests;
