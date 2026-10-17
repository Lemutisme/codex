//! The lane's effects outside its own state — hidden workers, reference observations, container
//! checks and the repair turn — behind one seam, so the lane itself is testable without a model or Docker.

use crate::CheckEnvironment;
use crate::CheckError;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvidencePolicy;
use crate::ObservationBatch;
use crate::WorkerError;
use crate::workers::runtime::WorkerTurn;
use codex_protocol::ThreadId;
use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use tokio::sync::watch;

pub(crate) type PortFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// The model and effort the hidden workers actually use.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct WorkerIdentity {
    pub model: Option<String>,
    pub effort: Option<String>,
}

pub(crate) trait Ports: Send + Sync {
    fn interrupt_executor(&self) -> PortFuture<'_, Result<(), String>> {
        Box::pin(async { Err("executor interruption is unavailable".into()) })
    }

    fn capture_barrier<'a>(
        &'a self,
        profile: &'a crate::EvaluationProfile,
        label: &'a str,
    ) -> PortFuture<'a, Result<super::capture_barrier::CaptureBarrier, String>> {
        Box::pin(super::capture_barrier::CaptureBarrier::acquire(
            profile, label,
        ))
    }

    /// Runs a fresh executor under the parent's authority; returns only after its shutdown.
    fn run_successor(&self, turn: SuccessorTurn) -> PortFuture<'_, Result<SuccessorExit, String>>;
    /// Runs one strict-JSON turn on a hidden worker and returns its final message.
    fn run_worker(&self, turn: WorkerTurn) -> PortFuture<'_, Result<String, WorkerError>>;

    /// Runs `cases` on the reference only, twice each, over the base workspace.
    fn observe<'a>(
        &'a self,
        env: &'a CheckEnvironment,
        base: &'a Path,
        reference: &'a str,
        cases: &'a [DifferentialCase],
    ) -> PortFuture<'a, Result<ObservationBatch, CheckError>>;

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

pub(crate) struct SuccessorTurn {
    pub id: ThreadId,
    pub environment_id: String,
    pub packet: String,
    pub deadline_ms: u64,
    pub cancel: watch::Receiver<bool>,
    pub evidence: super::archive::EvidenceAccess,
    pub progress: Option<super::evidence_tool::ProgressAccess>,
}

pub(crate) struct SuccessorHandoff {
    pub turn_id: String,
    pub summary: String,
    /// Actual delivered text; the bounded continuation summary is not delivery evidence.
    pub final_message: Option<String>,
}

pub(crate) enum SuccessorExit {
    /// Admission failed before a child existed; safe to clear the pending reservation.
    Rejected(String),
    Handoff(SuccessorHandoff),
    Stopped(String),
}
