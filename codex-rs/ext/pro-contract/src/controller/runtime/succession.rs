//! One responsibility with replaceable executor sessions. Intake grants and spent launches
//! survive process restarts; successors never redraft, Issue, settle, or reset the workspace.

use std::sync::Arc;

use codex_extension_api::ThreadIdleCause;
use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use codex_protocol::ThreadId;
use serde_json::json;
use tokio::sync::watch;

use super::Frozen;
use super::Phase;
use super::ThreadRuntime;
use crate::controller::decision::NotVerifiedClass;
use crate::controller::succession_budget::Budget;
use crate::controller::succession_budget::KIND;
use crate::controller::succession_budget::Lesson;
use crate::controller::succession_budget::now_ms;
use crate::controller::successor;
use crate::controller::successor::SuccessorExit;
use crate::controller::successor::SuccessorTurn;

pub(super) struct Control {
    cancel: watch::Sender<bool>,
    finished: watch::Receiver<bool>,
}

impl ThreadRuntime {
    /// Runs before a new owner turn or teardown. Invalidate pending decisions first, then
    /// join the old executor before the owner can use the workspace again.
    pub(super) async fn cancel_successor(&self) {
        let control = {
            let mut state = self.state.lock().await;
            state.epoch += 1;
            if matches!(state.phase, Phase::Succeeding | Phase::Verifying)
                && state.contract.is_some()
            {
                state.phase = Phase::Working;
            }
            state.successor.take()
        };
        if let Some(mut control) = control {
            control.cancel.send_replace(/*value*/ true);
            while !*control.finished.borrow() {
                if control.finished.changed().await.is_err() {
                    break;
                }
            }
            let mut state = self.state.lock().await;
            if state.phase == Phase::Succeeding {
                state.phase = Phase::Working;
            }
        }
    }

    pub(super) async fn succeed(
        self: Arc<Self>,
        subject: Digest,
        residual: String,
        previous_turn: String,
        epoch: u64,
    ) {
        let result = self
            .prepare_successor(subject, residual, &previous_turn, epoch)
            .await;
        let (reserved, deadline_ms, packet, id) = match result {
            Ok(value) => value,
            Err(reason) => {
                if self.state.lock().await.epoch == epoch {
                    self.rest("did_not_pass", &reason).await;
                }
                return;
            }
        };
        let (cancel, cancel_rx) = watch::channel(/*init*/ false);
        let (finished, finished_rx) = watch::channel(/*init*/ false);
        let admitted = {
            let mut state = self.state.lock().await;
            if state.epoch != epoch {
                false
            } else {
                state.phase = Phase::Succeeding;
                state.successor = Some(Control {
                    cancel,
                    finished: finished_rx,
                });
                true
            }
        };
        if !admitted {
            let mut cancelled = reserved.clone();
            cancelled.pending = None;
            // This launch was never dispatched, but its allowance is still not refunded.
            let _ = cancelled
                .replace(&self.ledger, &self.thread_id.to_string(), Some(&reserved))
                .await;
            return;
        }
        self.record_status(
            "succeeding",
            &format!(
                "fresh executor {id}; same responsibility, {} of {} sessions; original deadline {}",
                reserved.launches, reserved.grant.max_sessions, reserved.deadline_ms
            ),
            /*resting*/ false,
        )
        .await;
        self.record_event(ExperimentKind::Execution, /*check_pipeline*/ None, json!({
            "thread_id": self.thread_id.to_string(), "executor_thread_id": id.to_string(),
            "phase": "successor_reserved", "launch": reserved.launches,
            "deadline_ms": reserved.deadline_ms, "packet_sha256": super::digest_of("successor_packet", &packet)
        })).await;
        let result = self
            .ports
            .run_successor(SuccessorTurn {
                id,
                environment_id: self.profile.environment_id.clone(),
                packet,
                deadline_ms,
                cancel: cancel_rx,
            })
            .await;
        self.record_event(
            ExperimentKind::Execution,
            /*check_pipeline*/ None,
            json!({
                "thread_id": self.thread_id.to_string(), "executor_thread_id": id.to_string(),
                "phase": "successor_returned", "shutdown_confirmed": result.is_ok(),
                "error": result.as_ref().err(),
            }),
        )
        .await;
        let result = match result {
            Ok(exit) => {
                let mut completed = reserved.clone();
                completed.pending = None;
                if let SuccessorExit::Handoff(handoff) = &exit {
                    completed.previous_executor_claim = handoff.summary.clone();
                }
                completed
                    .replace(&self.ledger, &self.thread_id.to_string(), Some(&reserved))
                    .await
                    .map(|()| exit)
            }
            Err(error) => Err(error), // Unknown lifetime/admission stays pending and spent.
        };
        finished.send_replace(/*value*/ true);
        {
            let mut state = self.state.lock().await;
            if state.epoch != epoch {
                return;
            }
            state.successor = None;
        }
        let handoff = match result {
            Ok(SuccessorExit::Handoff(handoff)) => handoff,
            Ok(SuccessorExit::Stopped(reason)) | Err(reason) => {
                self.not_verified(NotVerifiedClass::NoHandoff, &reason)
                    .await;
                return;
            }
        };
        let captured = match self.capture_workspace().await {
            Ok(subject) => subject,
            Err(reason) => {
                self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                    .await;
                return;
            }
        };
        {
            let mut state = self.state.lock().await;
            if state.epoch != epoch {
                return;
            }
            state.frozen = Some(Frozen {
                turn_id: format!("{id}:{}", handoff.turn_id),
                subject: captured,
            });
            state.last_idle = Some(ThreadIdleCause::Completed);
            state.phase = Phase::Working;
        }
        Box::pin(self.promote()).await;
    }

    async fn prepare_successor(
        &self,
        subject: Digest,
        residual: String,
        previous_turn: &str,
        epoch: u64,
    ) -> Result<(Budget, u64, String, ThreadId), String> {
        let key = self.thread_id.to_string();
        let previous: Budget = self
            .ledger
            .record(KIND, &key)
            .await
            .map_err(|e| e.to_string())?
            .ok_or("no original succession grant; resume cannot create one")?;
        let id = ThreadId::new();
        let reserve = self
            .profile
            .check
            .timeout_secs
            .saturating_add(self.settings.worker.deadline_secs)
            .saturating_add(/*rhs*/ 60);
        let (reserved, deadline_ms) = previous.reserve(
            id.to_string(),
            Lesson { subject, residual },
            now_ms()?,
            reserve,
        )?;
        let journal = self.ledger.experiments().await.map_err(|e| e.to_string())?;
        let intake = journal
            .iter()
            .find(|row| {
                row.event.kind == ExperimentKind::Intake
                    && row.event.body["thread_id"].as_str() == Some(&key)
            })
            .and_then(|row| row.event.body["text"].as_str())
            .ok_or("original authorized intake unavailable")?;
        let packet = {
            let state = self.state.lock().await;
            if state.epoch != epoch
                || state.phase != Phase::Verifying
                || state
                    .frozen
                    .as_ref()
                    .is_none_or(|f| f.turn_id != previous_turn)
            {
                return Err("owner superseded the failed handoff".into());
            }
            let active = state
                .contract
                .as_ref()
                .ok_or("responsibility unavailable")?;
            serde_json::to_string(&json!({
            "original_task": intake,
            "contract_id": active.contract.id.0,
            "immutable_bindings": active.contract.bindings,
            "requirements": active.terms,
            "remaining_failures_and_prior_failed_artifacts": reserved.lessons,
            "previous_executor_claim_untrusted": reserved.previous_executor_claim,
            "executor_deadline_ms": deadline_ms,
            "strategy": "Use the observed failures to choose a new discriminating experiment. Continue a sound approach or reimplement task-owned files if its assumptions are wrong. A fresh context does not justify repeating an unchanged approach. Preserve unrelated work; historical candidates and the original base remain frozen in the host ledger."
            })).map_err(|e| e.to_string())?
        };
        successor::packet(&packet)?; // Validate all context bounds before spending a launch.
        reserved
            .replace(&self.ledger, &key, Some(&previous))
            .await?;
        Ok((reserved, deadline_ms, packet, id))
    }
}
