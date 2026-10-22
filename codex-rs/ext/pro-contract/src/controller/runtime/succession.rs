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
use crate::controller::ports::SuccessorExit;
use crate::controller::ports::SuccessorTurn;
use crate::controller::succession_budget::Budget;
use crate::controller::succession_budget::KIND;
use crate::controller::succession_budget::Lesson;
use crate::controller::succession_budget::now_ms;
use crate::controller::successor;

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
                "fresh executor {id}; same responsibility, {} launches; explicit session limit {:?}; original deadline {:?}",
                reserved.launches, reserved.grant.max_sessions, reserved.deadline_ms
            ),
            /*resting*/ false,
        )
        .await;
        self.record_event(ExperimentKind::Execution, /*check_pipeline*/ None, json!({
            "thread_id": self.thread_id.to_string(), "executor_thread_id": id.to_string(),
            "phase": "successor_reserved", "launch": reserved.launches,
            "deadline_ms": reserved.deadline_ms, "executor_deadline_ms":deadline_ms, "packet_sha256": super::digest_of("successor_packet", &packet)
        })).await;
        let result = self
            .ports
            .run_successor(SuccessorTurn {
                id,
                environment_id: self.profile.environment_id.clone(),
                packet,
                deadline_ms,
                cancel: cancel_rx,
                evidence: self.evidence_access(),
                progress: self.progress_enabled().then(|| {
                    super::super::evidence_tool::ProgressAccess {
                        runtime: Arc::downgrade(&self),
                        epoch,
                        deadline_ms,
                    }
                }),
            })
            .await;
        self.record_event(
            ExperimentKind::Execution,
            /*check_pipeline*/ None,
            json!({
                "thread_id": self.thread_id.to_string(), "executor_thread_id": id.to_string(),
                "phase": if matches!(&result, Ok(SuccessorExit::Rejected(_))) { "successor_rejected" } else { "successor_returned" },
                "shutdown_confirmed": result.is_ok(),
                "admission_rejected": matches!(&result, Ok(SuccessorExit::Rejected(_))),
                "reason": match &result {
                    Ok(SuccessorExit::Rejected(reason) | SuccessorExit::Stopped(reason) | SuccessorExit::Interrupted(reason)) => Some(reason),
                    _ => None,
                },
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
            Ok(SuccessorExit::Interrupted(reason)) => {
                self.not_verified(NotVerifiedClass::ExecutionInterrupted, &reason)
                    .await;
                return;
            }
            Ok(SuccessorExit::Rejected(reason)) => {
                self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                    .await;
                return;
            }
            Ok(SuccessorExit::Stopped(reason)) | Err(reason) => {
                let class = if reserved
                    .deadline_ms
                    .is_some_and(|end| now_ms().is_ok_and(|now| now >= end))
                {
                    NotVerifiedClass::BudgetExhausted
                } else {
                    NotVerifiedClass::NoHandoff
                };
                self.not_verified(class, &reason).await;
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
                response: self.capture_response(
                    &captured,
                    &format!("{id}:{}", handoff.turn_id),
                    handoff.final_message.as_deref(),
                ),
                turn_id: format!("{id}:{}", handoff.turn_id),
                subject: captured,
            });
            state.last_idle = Some(ThreadIdleCause::Completed);
            state.phase = Phase::Working;
        }
        if let Err(reason) = self.commit_delivery().await {
            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        Box::pin(self.promote()).await;
    }

    async fn prepare_successor(
        &self,
        subject: Digest,
        residual: String,
        previous_turn: &str,
        epoch: u64,
    ) -> Result<(Budget, Option<u64>, String, ThreadId), String> {
        let key = self.thread_id.to_string();
        let previous: Budget = self
            .ledger
            .record(KIND, &key)
            .await
            .map_err(|e| e.to_string())?
            .ok_or("no original succession grant; resume cannot create one")?;
        let id = ThreadId::new();
        let (reserved, mut deadline_ms) =
            previous.reserve(id.to_string(), Lesson { subject, residual }, now_ms()?)?;
        if let Some(seconds) = self
            .settings
            .progress
            .as_ref()
            .and_then(|progress| progress.executor_slice_secs)
        {
            let local = now_ms()?
                .checked_add(
                    seconds
                        .checked_mul(1000)
                        .ok_or("executor allowance overflow")?,
                )
                .ok_or("executor deadline overflow")?;
            deadline_ms = crate::controller::succession_budget::earliest(deadline_ms, Some(local));
        }
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
                return Err("owner superseded the assessed handoff".into());
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
            "prior_assessments_and_selected_work": reserved.lessons,
            "previous_executor_claim_untrusted": reserved.previous_executor_claim,
            "executor_deadline_ms": deadline_ms,
            "original_task_deadline_ms": reserved.deadline_ms,
            "progress_publication": self.progress_enabled().then_some("publish_progress is available under the original publication and task grants shared with the prior executor."),
            "public_evidence": "Use contract_read_evidence: frontier for open public checks, index for the complete retained verification history, read for exact available details. Recent failure summaries are an index, not the full evidence. Preserve unrelated work and runnable probes in the workspace.",
            "strategy": self.policies.work_method,
            "declared_task_inputs": self.input_capabilities()
            })).map_err(|e| e.to_string())?
        };
        successor::packet(&packet)?; // Validate all context bounds before spending a launch.
        reserved
            .replace(&self.ledger, &key, Some(&previous))
            .await?;
        Ok((reserved, deadline_ms, packet, id))
    }
}
