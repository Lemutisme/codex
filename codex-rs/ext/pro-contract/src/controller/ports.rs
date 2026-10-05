//! The lane's effects outside its own state — hidden workers, reference observations, container
//! checks and the repair turn — behind one seam, so the lane itself is testable without a model or Docker.

use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::sync::Weak;

use codex_core::ThreadManager;
use codex_core::TurnInput;
use codex_core::TurnInputRequest;
use codex_core::TurnInputSubmission;
use codex_core::TurnStartOptions;
use codex_core::config::Config;
use codex_core::context::ContextualUserFragment;
use codex_core::context::InternalContextSource;
use codex_core::context::InternalModelContextFragment;
use codex_protocol::ThreadId;

use crate::CheckEnvironment;
use crate::CheckError;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvidencePolicy;
use crate::Observation;
use crate::WorkerError;
use crate::WorkerSettings;
use crate::checks;
use crate::workers::runtime::WorkerTurn;
use crate::workers::runtime::run_turn;
use crate::workers::runtime::worker_config;

pub(crate) type PortFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// The model and effort the hidden workers actually use.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct WorkerIdentity {
    pub model: Option<String>,
    pub effort: Option<String>,
}

pub(crate) trait Ports: Send + Sync {
    /// Runs one strict-JSON turn on a hidden worker and returns its final message.
    fn run_worker(&self, turn: WorkerTurn) -> PortFuture<'_, Result<String, WorkerError>>;

    /// Runs `cases` on the reference only, twice each, over the base workspace.
    fn observe<'a>(
        &'a self,
        env: &'a CheckEnvironment,
        base: &'a Path,
        reference: &'a str,
        cases: &'a [DifferentialCase],
    ) -> PortFuture<'a, Result<Vec<Observation>, CheckError>>;

    /// Runs the check pipeline over the materialized candidate, with the base workspace under
    /// every case.
    fn run_checks<'a>(
        &'a self,
        env: &'a CheckEnvironment,
        candidate: &'a Path,
        base: &'a Path,
        policy: &'a EvidencePolicy,
    ) -> PortFuture<'a, Result<CheckReceipts, CheckError>>;

    /// The model and effort hidden workers run with; part of every judgment's identity.
    fn worker_identity(&self) -> WorkerIdentity;

    /// Starts the repair turn on the executor thread, continuing `previous_turn_id`.
    fn submit_repair(
        &self,
        residual: String,
        previous_turn_id: String,
    ) -> PortFuture<'_, Result<(), String>>;
}

/// The real ports: hidden threads on the host's thread manager and Docker checks.
pub(crate) struct CodexPorts {
    pub thread_id: ThreadId,
    pub manager: Weak<ThreadManager>,
    pub config: Config,
    pub worker: WorkerSettings,
}

impl Ports for CodexPorts {
    fn run_worker(&self, turn: WorkerTurn) -> PortFuture<'_, Result<String, WorkerError>> {
        Box::pin(async move {
            let manager = self
                .manager
                .upgrade()
                .ok_or_else(|| WorkerError::Start("thread manager is gone".to_string()))?;
            let config = worker_config(&self.config, &self.worker)?;
            run_turn(&manager, config, turn).await
        })
    }

    fn observe<'a>(
        &'a self,
        env: &'a CheckEnvironment,
        base: &'a Path,
        reference: &'a str,
        cases: &'a [DifferentialCase],
    ) -> PortFuture<'a, Result<Vec<Observation>, CheckError>> {
        Box::pin(checks::observe(env, base, reference, cases))
    }

    fn run_checks<'a>(
        &'a self,
        env: &'a CheckEnvironment,
        candidate: &'a Path,
        base: &'a Path,
        policy: &'a EvidencePolicy,
    ) -> PortFuture<'a, Result<CheckReceipts, CheckError>> {
        Box::pin(checks::run(env, candidate, base, policy))
    }

    fn worker_identity(&self) -> WorkerIdentity {
        WorkerIdentity {
            model: self
                .worker
                .model
                .clone()
                .or_else(|| self.config.model.clone()),
            effort: self.worker.reasoning_effort.clone().or_else(|| {
                self.config
                    .model_reasoning_effort
                    .as_ref()
                    .map(|effort| format!("{effort:?}").to_lowercase())
            }),
        }
    }

    fn submit_repair(
        &self,
        residual: String,
        previous_turn_id: String,
    ) -> PortFuture<'_, Result<(), String>> {
        Box::pin(async move {
            let manager = self
                .manager
                .upgrade()
                .ok_or_else(|| "thread manager is gone".to_string())?;
            let thread = manager
                .get_thread(self.thread_id)
                .await
                .map_err(|error| error.to_string())?;
            let item = ContextualUserFragment::into(InternalModelContextFragment::new(
                InternalContextSource::from_static("pro_contract"),
                residual,
            ));
            let request =
                TurnInputRequest::new(TurnInput::ResponseItem(item)).on_start(TurnStartOptions {
                    turn_trigger: Some("pro_contract_repair".to_string()),
                    ..Default::default()
                });
            match thread
                .continue_turn_if_idle(request, previous_turn_id)
                .await
                .map_err(|error| error.to_string())?
            {
                TurnInputSubmission::Started { .. } => Ok(()),
                other => Err(format!("{other:?}")),
            }
        })
    }
}
