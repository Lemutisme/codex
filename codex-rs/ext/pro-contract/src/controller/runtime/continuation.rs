//! Execute a context-selected continuation without changing the assessment or grant.

use std::sync::Arc;

use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::{Handoff, Phase, ThreadRuntime};
use crate::controller::decision::{NotVerifiedClass, Verdict};
use crate::controller::succession_budget::{Budget, KIND};
use crate::controller::work::PublicEvidence;
use crate::workers::continuation::{self, Action};

impl ThreadRuntime {
    /// Return only capabilities already admitted by the existing configuration.
    /// In particular, an exhausted nonzero successor grant is not a local-work grant.
    async fn continuation_actions(&self) -> Result<Vec<Action>, (NotVerifiedClass, String)> {
        self.action_seconds(None, 1)
            .await
            .map_err(|reason| (NotVerifiedClass::BudgetExhausted, reason))?;
        let local_available = self.state.lock().await.repairs_used < self.settings.repair_attempts;
        if self
            .settings
            .succession
            .as_ref()
            .is_some_and(|g| g.max_sessions != Some(0))
        {
            let budget: Budget = self
                .ledger
                .record(KIND, &self.thread_id.to_string())
                .await
                .map_err(|e| (NotVerifiedClass::Infrastructure, e.to_string()))?
                .ok_or_else(|| {
                    (
                        NotVerifiedClass::Infrastructure,
                        "original successor grant unavailable".into(),
                    )
                })?;
            if budget.pending.is_some() {
                return Err((
                    NotVerifiedClass::Infrastructure,
                    "previous executor lifetime is unresolved".into(),
                ));
            }
            if budget
                .grant
                .max_sessions
                .is_none_or(|limit| budget.launches < limit)
            {
                return Ok(vec![Action::Successor, Action::Rest]);
            }
        } else if local_available {
            return Ok(vec![Action::Resume, Action::Rest]);
        }
        Ok(vec![Action::Rest])
    }

    pub(super) async fn choose_continuation(
        self: Arc<Self>,
        handoff: Handoff,
        public: PublicEvidence,
        public_handle: Digest,
        verification: Digest,
        outcome: Verdict,
    ) {
        let (assessment, detail, class) = match outcome {
            Verdict::NotVerified { class, reason } => ("not_verified", reason, Some(class)),
            Verdict::Defeat { residual, blocker } => {
                let gap = blocker.map_or_else(String::new, |b| {
                    format!(
                        "\nAcceptance remains blocked ({}): {}.",
                        b.class.as_str(),
                        b.reason
                    )
                });
                ("defeat", format!("{residual}{gap}"), None)
            }
            Verdict::Support => return,
        };
        let review = public.review.as_ref();
        let obligations = handoff.terms.obligations();
        let allowed: Vec<String> = obligations
            .iter()
            .filter(|o| {
                review.is_none_or(|r| {
                    !r.scope_disputed(&o.id)
                        && !r
                            .execution_findings()
                            .iter()
                            .any(|f| f.requirement_id == o.id)
                })
            })
            .map(|o| o.id.clone())
            .collect();
        let actions = match self.continuation_actions().await {
            Ok(actions) => actions,
            Err((class, reason)) => {
                if self.state.lock().await.epoch == handoff.epoch {
                    self.not_verified(class, &reason).await;
                }
                return;
            }
        };
        if self.state.lock().await.epoch != handoff.epoch {
            return;
        }
        if allowed.is_empty() || actions == [Action::Rest] {
            self.finish_continuation(class, &detail).await;
            return;
        }
        let previous_choice = match self.ledger.experiments().await {
            Ok(journal) => {
            journal.into_iter().rev().find(|r| {
                r.event.body["phase"] == "continuation_decision"
                    && r.event.body["contract_id"] == json!(handoff.contract.id)
            }).map(|r| {
                let b = r.event.body;
                json!({"choice":b["choice"],"error":b["error"],
                    "verification":b["verification"],"subject_hash":b["subject_hash"],
                    "public_evidence":b["public_evidence"],
                    "meaning":"Previous selection is a historical intention, not proof that it was executed or achieved its expected result. Compare it with current observations; older assessments remain in the public archive."})
            })
            }
            Err(reason) => Some(json!({"unavailable":reason.to_string()})),
        };
        let observation_scope = public.host_observations.map(|handle| {
            let document = self.store.get(&handle).map_err(|e| e.to_string())
                .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).map_err(|e| e.to_string()));
            match document {
                Ok(doc) if doc["subject_hash"] == json!(handoff.subject.subject_hash)
                    && doc["terms_hash"] == json!(crate::digest_of("terms", &handoff.terms)) => {
                    json!({"handle":handle,"available_fields":doc.as_object().map(|o| o.keys().collect::<Vec<_>>()),"limits":doc["limits"]})
                }
                Ok(_) => json!({"handle":handle,"unavailable":"observation binding differs"}),
                Err(reason) => json!({"handle":handle,"unavailable":reason}),
            }
        });
        // Quotations remain retrievable from public_handle. They are not needed to
        // choose work from the already bound judgments and explicit capabilities.
        let facts = json!({
            "contract_id":handoff.contract.id, "subject_hash":handoff.subject.subject_hash,
            "verification":verification,"public_evidence":public_handle,
            "original_request":handoff.terms.intake_text,
            "obligations":obligations.iter().map(|o| json!({"id":o.id,"scope":o.scope,"text":o.text})).collect::<Vec<_>>(),
            "assessment":{"decision":assessment,"detail":detail,
                "review":review.map(|r| json!({"verdict":r.verdict,"terms_gap":r.terms_gap,"observations":r.observations})),
                "public_check_outcomes":public.checks.iter().map(|c|json!({"step":c.receipt.step,"outcome":c.receipt.outcome})).collect::<Vec<_>>()},
            "allowed_requirements":allowed,"available_actions":actions,
            "previous_choice":previous_choice,
            "capabilities":{"public_evidence_read":true,"frozen_progress_assessment":self.progress_enabled(),
                "independent_diagnosis":self.progress_enabled(),"environment":self.profile.environment_id,
                "public_checks":public.checks.iter().map(|c| json!({"step":c.receipt.step,"command":c.command,"invocation":c.invocation})).collect::<Vec<_>>(),
                "host_observation_scope":observation_scope,
                "assessment_scope":"Progress assessment observes the configured checks and frozen artifacts. It does not retrospectively attest arbitrary executor commands; self-authored logs do not become host receipts."},
            "task_budget":self.remaining_task_budget().await.ok(),
            "meaning":"Only listed obligation scopes may be selected. Evidence limitations do not grant completion. Original permissions and resource allocations remain binding."
        });
        let prompt = format!("{}\n\n{}", self.policies.continuation, facts);
        if self.state.lock().await.epoch != handoff.epoch {
            return;
        }
        self.record_status("deciding", "selecting work under the original grant", false)
            .await;
        let response = self
            .run_worker(
                prompt.clone(),
                continuation::schema(&actions, &allowed),
                "pro_contract_continuation",
            )
            .await;
        let interrupted = matches!(&response, Err(crate::WorkerError::Interrupted(_)));
        let choice = response
            .as_ref()
            .map_err(ToString::to_string)
            .and_then(|message| {
                continuation::parse(message, &actions, &allowed).map_err(|e| e.to_string())
            });
        let local_used = {
            let mut state = self.state.lock().await;
            if state.epoch != handoff.epoch || state.phase != Phase::Verifying {
                return;
            }
            if matches!(&choice, Ok(c) if c.action == Action::Resume) {
                state.repairs_used = state.repairs_used.saturating_add(1);
            }
            state.repairs_used
        };
        // Persist the selection and local reservation before any dispatch. Recovery
        // retains spent work even if submission fails or the process stops here.
        let recorded = self
            .append_event(
                ExperimentKind::Execution,
                None,
                json!({
                    "phase":"continuation_decision","thread_id":self.thread_id.to_string(),
                    "execution_epoch":handoff.epoch,"assessed_turn_id":handoff.turn_id,
                    "contract_id":handoff.contract.id,"subject_hash":handoff.subject.subject_hash,
                    "verification":verification,"public_evidence":public_handle,
                    "input_hash":crate::digest_of("continuation_input", &prompt),
                    "response":response.as_ref().ok(),"error":choice.as_ref().err(),
                    "choice":choice.as_ref().ok(),"local_repairs_used":local_used,
                }),
            )
            .await;
        if let Err(reason) = recorded {
            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        if self.state.lock().await.epoch != handoff.epoch {
            return;
        }
        let choice = match choice {
            Ok(choice) => choice,
            Err(reason) => {
                self.finish_continuation(
                    if interrupted {
                        Some(NotVerifiedClass::ExecutionInterrupted)
                    } else {
                        class
                    },
                    &format!("{detail}\nContinuation unavailable: {reason}"),
                )
                .await;
                return;
            }
        };
        if choice.action == Action::Rest {
            self.finish_continuation(class, &format!("{detail}\nStrategy: {}", choice.next_step))
                .await;
            return;
        }
        let note = format!(
            "Continue the original task within these selected obligation scopes: {}.\nStrategy next step: {}\nFrozen assessment (unchanged): {}\nRead retained public evidence {} with contract_read_evidence. Other scope disputes and evidence gaps remain recorded; continuing does not certify acceptance or authorize work on disputed obligations.",
            choice.requirements.join(", "),
            choice.next_step,
            detail,
            public_handle,
        );
        if choice.action == Action::Successor {
            Box::pin(self.succeed(
                handoff.subject.subject_hash,
                note,
                handoff.turn_id,
                handoff.epoch,
            ))
            .await;
            return;
        }
        // Recheck actual time after the selection call. Its model requests are
        // already charged by the same gateway as every other role.
        if let Err(reason) = self
            .action_seconds(None, self.settings.worker.deadline_secs)
            .await
        {
            self.not_verified(NotVerifiedClass::BudgetExhausted, &reason)
                .await;
            return;
        }
        {
            let mut state = self.state.lock().await;
            if state.epoch != handoff.epoch {
                return;
            }
            state.phase = Phase::Working;
            state.repair_note = Some(note.clone());
        }
        match self
            .ports
            .submit_repair(note.clone(), handoff.turn_id)
            .await
        {
            Ok(()) => self.record_status("repairing", &note, false).await,
            Err(reason) => {
                self.rest(
                    "did_not_pass",
                    &format!("repair could not start: {reason}\n{note}"),
                )
                .await
            }
        }
    }

    async fn finish_continuation(&self, class: Option<NotVerifiedClass>, detail: &str) {
        match class {
            Some(class) => self.not_verified(class, detail).await,
            None => self.rest("did_not_pass", detail).await,
        }
    }
}
