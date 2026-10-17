//! Codex-specific implementation of the controller ports.

use std::path::Path;
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

use super::ports::{PortFuture, Ports, WorkerIdentity};
use crate::checks;
use crate::workers::runtime::{WorkerTurn, run_turn, worker_config};
use crate::{
    CheckEnvironment, CheckError, CheckReceipts, DifferentialCase, EvidencePolicy,
    ObservationBatch, WorkerError, WorkerSettings,
};

/// The real ports: hidden threads on the host's thread manager and Docker checks.
pub(crate) struct CodexPorts {
    pub thread_id: ThreadId,
    pub manager: Weak<ThreadManager>,
    pub config: Config,
    pub worker: WorkerSettings,
}

impl Ports for CodexPorts {
    fn interrupt_executor(&self) -> PortFuture<'_, Result<(), String>> {
        Box::pin(async move {
            let manager = self.manager.upgrade().ok_or("thread manager is gone")?;
            let thread = manager
                .get_thread(self.thread_id)
                .await
                .map_err(|e| e.to_string())?;
            thread
                .submit(codex_protocol::protocol::Op::Interrupt)
                .await
                .map_err(|e| e.to_string())?;
            // Shut down only this actor. A backend may be shared with other threads;
            // deleting containers by a workspace label would exceed this authority.
            tokio::time::timeout(
                std::time::Duration::from_secs(10),
                thread.shutdown_and_wait(),
            )
            .await
            .map_err(|_| "executor shutdown timed out")?
            .map_err(|e| e.to_string())?;
            Ok(())
        })
    }

    fn run_successor(
        &self,
        turn: super::ports::SuccessorTurn,
    ) -> PortFuture<'_, Result<super::ports::SuccessorExit, String>> {
        Box::pin(async move {
            let manager = self.manager.upgrade().ok_or("thread manager is gone")?;
            super::successor::run(&manager, self.thread_id, self.config.clone(), turn).await
        })
    }
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
    ) -> PortFuture<'a, Result<ObservationBatch, CheckError>> {
        Box::pin(checks::observe_batch(env, base, reference, cases))
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
