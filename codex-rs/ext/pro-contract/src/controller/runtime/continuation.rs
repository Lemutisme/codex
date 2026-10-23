//! Execute a context-selected continuation without changing the assessment or grant.

use std::sync::Arc;
use std::time::Duration;

use codex_pro_contract::Digest;
use codex_pro_contract_store::{ExperimentKind, ExperimentRecord};
use serde_json::json;

use super::{Handoff, Phase, ThreadRuntime};
use crate::controller::decision::{NotVerifiedClass, Verdict};
use crate::controller::succession_budget::{Budget, KIND};
use crate::controller::work::PublicEvidence;
use crate::workers::continuation::{self, Action};

/// Correlate by the durable selection identity, never by whichever execution
/// happened most recently. Older records without this link stay unknown.
fn previous_selection(
    journal: &[ExperimentRecord],
    contract: &codex_pro_contract::ContractId,
) -> Option<serde_json::Value> {
    let selection = journal.iter().rev().find(|r| {
        r.event.body["phase"] == "continuation_decision"
            && r.event.body["contract_id"] == json!(contract)
            && !matches!(
                r.event.body["choice"]["action"].as_str(),
                Some("check" | "diagnose" | "verify")
            )
    })?;
    let body = &selection.event.body;
    let executions: Vec<_> = journal
        .iter()
        .filter(|r| r.event.body["continuation"] == json!(selection.hash))
        .map(|r| json!({"record":r.hash,"event":r.event.body}))
        .collect();
    let delivered_turn = executions
        .iter()
        .rev()
        .find_map(|r| r["event"]["handoff_turn_id"].as_str());
    let delivery = delivered_turn
        .and_then(|turn| {
            journal.iter().find(|r| {
                r.event.body["phase"] == "task_delivery"
                    && r.event.body["turn_id"] == turn
                    && r.event.body["thread_id"] == body["thread_id"]
            })
        })
        .map(|r| json!({"record":r.hash,"event":r.event.body}));
    Some(
        json!({"record":selection.hash,"choice":body["choice"],"error":body["error"],
        "verification":body["verification"],"subject_hash":body["subject_hash"],
        "public_evidence":body["public_evidence"],"execution_records":executions,"delivery":delivery,
        "meaning":"Selection, dispatch, executor return, captured delivery and assessed effects are distinct facts. Linked records describe what the host observed, not proof that the plan succeeded. Missing links, including legacy records, do not mean the action did not happen."}),
    )
}

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
        mut public: PublicEvidence,
        mut public_handle: Digest,
        mut verification: Digest,
        mut outcome: Verdict,
    ) {
        let mut reusable_checks = None;
        loop {
            if self.state.lock().await.epoch != handoff.epoch {
                return;
            }
            if let Err(reason) =
                crate::resources::require_model_capacity(self.settings.resource_snapshot.as_deref())
            {
                self.not_verified(NotVerifiedClass::BudgetExhausted, &reason.to_string())
                    .await;
                return;
            }
            let (assessment, detail, class) = match &outcome {
                Verdict::NotVerified { class, reason } => {
                    ("not_verified", reason.clone(), Some(*class))
                }
                Verdict::Defeat { residual, blocker } => {
                    let gap = blocker.as_ref().map_or_else(String::new, |b| {
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
            let review_history = match self.evidence_access().review_history().await {
                Ok(previous) => previous,
                Err(reason) => {
                    self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                        .await;
                    return;
                }
            };
            let review = public.review.as_ref();
            let previous_review = review_history.last();
            let obligations = handoff.terms.obligations();
            let allowed: Vec<String> = obligations
                .iter()
                .filter(|o| {
                    let mut blocked = false;
                    for evidence in &review_history {
                        let Some(r) = &evidence.review else {
                            continue;
                        };
                        if r.scope_disputed(&o.id)
                            || r.execution_findings()
                                .iter()
                                .any(|f| f.requirement_id == o.id)
                        {
                            blocked = true;
                        } else {
                            use crate::workers::reviewer::ReviewVerdict;
                            let reconsidered = match &r.verdict {
                                ReviewVerdict::Support { coverage } => {
                                    coverage.iter().any(|c| c.requirement_id == o.id)
                                }
                                ReviewVerdict::Defeat { findings, .. } => {
                                    findings.iter().any(|f| f.requirement_id == o.id)
                                }
                                ReviewVerdict::Partial {
                                    coverage, findings, ..
                                } => {
                                    coverage.iter().any(|c| c.requirement_id == o.id)
                                        || findings.iter().any(|f| f.requirement_id == o.id)
                                }
                                ReviewVerdict::CannotJudge { .. } => false,
                            };
                            // An omitted or unresolved local judgment does not erase a
                            // known restriction on an unrelated obligation.
                            if reconsidered {
                                blocked = false;
                            }
                        }
                    }
                    !blocked
                })
                .map(|o| o.id.clone())
                .collect();
            let mut actions = match self.continuation_actions().await {
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
            if allowed.is_empty() {
                actions.retain(|a| *a == Action::Rest);
            }
            actions.extend([Action::Check, Action::Diagnose, Action::Verify]);
            let previous_choice = match self.ledger.experiments().await {
                Ok(journal) => previous_selection(&journal, &handoff.contract.id),
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
            // The selector can read the immutable archive when this projection is insufficient.
            let facts = json!({
                "contract_id":handoff.contract.id, "subject_hash":handoff.subject.subject_hash,
                "assessed_turn_id":handoff.turn_id,
                "verification":verification,"public_evidence":public_handle,
                "original_request":handoff.terms.intake_text,
                "obligations":obligations.iter().map(|o| json!({"id":o.id,"scope":o.scope,"text":o.text})).collect::<Vec<_>>(),
                "assessment":{"stage":public.assessment_scope.as_deref().unwrap_or("verification"),
                    "subject_hash":public.subject_hash,"decision":assessment,"detail":detail,
                    "review":review.map(|r| json!({"verdict":r.verdict,"terms_gap":r.terms_gap,"observations":r.observations})),
                    "public_check_outcomes":public.checks.iter().map(|c|json!({"step":c.receipt.step,"outcome":c.receipt.outcome})).collect::<Vec<_>>()},
                "allowed_requirements":allowed,"available_actions":actions,
                "previous_choice":previous_choice,
                "prior_review":previous_review.filter(|_| review.is_none()).map(|p| json!({
                    "subject_hash":p.subject_hash,"review":p.review.as_ref().map(|r| json!({
                        "verdict":r.verdict,"terms_gap":r.terms_gap,"observations":r.observations}))})),
                "capabilities":{"public_evidence_read":true,
                    "handoff_observations":{
                        "check":"Run the declared public executable checks on this frozen subject; no independent judgment or withheld cases.",
                        "diagnose":"Ask a focused question of an independent reviewer over this subject and retained public evidence. Complete public checks from this selection loop may be reused. No acceptance is issued.",
                        "verify":"Run the original acceptance pipeline, including withheld cases and full review when applicable. Only this operation may issue Support."},
                    "declared_public_checks":{"build_command":handoff.policy.build_command,
                        "candidate_command":handoff.policy.candidate_command,"public_case_count":handoff.policy.differential.len(),
                        "candidate_tests":handoff.policy.candidate_tests},
                    "diagnostic_computation":self.settings.review_execution,
                    "environment":self.profile.environment_id,
                    "executor":{"actions":actions.iter().filter(|a| matches!(a, Action::Resume | Action::Successor)).collect::<Vec<_>>(),
                        "progress_publication":self.progress_enabled(),
                        "workspace":"The original mutable workspace and retained task files remain available.",
                        "tools":"An offered resume or successor uses the task's native execution/file tools in the declared environment, under the original permissions and resource limits. The selector can read public evidence; mutable execution is delegated through these actions.",
                        "reference_command":self.profile.reference_command,"task_inputs":self.input_capabilities()},
                    "public_checks":public.checks.iter().map(|c| json!({"step":c.receipt.step,"command":c.command,"invocation":c.invocation})).collect::<Vec<_>>(),
                    "host_observation_scope":observation_scope,
                    "assessment_scope":"Progress assessment observes the configured checks and frozen artifacts. It does not retrospectively attest arbitrary executor commands; self-authored logs do not become host receipts."},
                "execution_grant":self.remaining_task_budget().await.ok(),
                "allocator_resources":match crate::resources::read(self.settings.resource_snapshot.as_deref()) {
                    Ok(view) => json!(view), Err(reason) => json!({"unavailable":reason})
                },
                "meaning":"Only listed obligation scopes may be selected. Evidence limitations do not grant completion. Original permissions and resource allocations remain binding."
            });
            let prompt = format!("{}\n\n{}", self.policies.continuation, facts);
            if self.state.lock().await.epoch != handoff.epoch {
                return;
            }
            self.record_status("deciding", "selecting work under the original grant", false)
                .await;
            let response = match self
                .action_seconds(None, self.settings.worker.deadline_secs)
                .await
            {
                Ok(seconds) => {
                    self.ports
                        .run_worker(crate::workers::runtime::WorkerTurn {
                            prompt: prompt.clone(),
                            schema: continuation::schema(&actions, &allowed),
                            trigger: "pro_contract_continuation",
                            deadline: Duration::from_secs(seconds),
                            evidence: None,
                            archive: Some(self.evidence_access()),
                            resources: self.settings.resource_snapshot.clone(),
                        })
                        .await
                }
                Err(reason) => Err(crate::WorkerError::Start(reason)),
            };
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
                if matches!(&choice, Ok(c) if c.action() == Action::Resume) {
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
                    "basis":verification,"assessment_scope":public.assessment_scope,
                    "verification":(public.assessment_scope.as_deref().unwrap_or("verification")=="verification").then_some(verification),
                    "public_evidence":public_handle,
                    "input_hash":crate::digest_of("continuation_input", &prompt),
                    "response":response.as_ref().ok(),"error":choice.as_ref().err(),
                    "choice":choice.as_ref().ok(),"local_repairs_used":local_used,
                }),
            )
            .await;
            let decision = match recorded {
                Ok(decision) => decision,
                Err(reason) => {
                    self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                        .await;
                    return;
                }
            };
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
            match &choice {
                continuation::Choice::Verify { .. } => {
                    Box::pin(self.verify(handoff)).await;
                    return;
                }
                continuation::Choice::Check { .. } | continuation::Choice::Diagnose { .. } => {
                    let question = match &choice {
                        continuation::Choice::Diagnose { question } => Some(question.clone()),
                        _ => None,
                    };
                    let prior = Some(
                        json!({"handle":public_handle,"document":{"subject_hash":public.subject_hash,"public":public}}),
                    );
                    let checks = if question.is_some() {
                        reusable_checks.take()
                    } else {
                        None
                    };
                    let assessment = match self
                        .observe_handoff(&handoff, decision, question.clone(), checks, prior)
                        .await
                    {
                        Ok(assessment) => assessment,
                        Err(reason) => {
                            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                                .await;
                            return;
                        }
                    };
                    let retained = self
                        .retain_work_observation(
                            &handoff,
                            &assessment.public,
                            "work_assessed",
                            Some(decision),
                            question.as_deref(),
                        )
                        .await;
                    if self.state.lock().await.epoch != handoff.epoch {
                        return;
                    }
                    if !assessment.effects_resolved {
                        self.not_verified(
                            NotVerifiedClass::Infrastructure,
                            "selected observation has unresolved execution effects",
                        )
                        .await;
                        return;
                    }
                    let (handle, basis) = match retained {
                        Ok(value) => value,
                        Err(reason) => {
                            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                                .await;
                            return;
                        }
                    };
                    reusable_checks = assessment.checks.ok().filter(|r| r.complete);
                    public = assessment.public;
                    public_handle = handle;
                    verification = basis;
                    // A local observation never certifies whole-task acceptance.
                    outcome = match assessment.verdict {
                        Verdict::Support => Verdict::NotVerified {
                            class: NotVerifiedClass::InsufficientEvidence,
                            reason:
                                "Local diagnosis completed; full acceptance has not been requested."
                                    .into(),
                        },
                        other => other,
                    };
                    continue;
                }
                _ => {}
            }
            let (requirements, next_step) = match &choice {
                continuation::Choice::Rest { reason } => {
                    self.finish_continuation(class, &format!("{detail}\nStrategy: {reason}"))
                        .await;
                    return;
                }
                continuation::Choice::Resume {
                    requirements,
                    next_step,
                }
                | continuation::Choice::Successor {
                    requirements,
                    next_step,
                } => (requirements, next_step),
                continuation::Choice::Check { .. }
                | continuation::Choice::Diagnose { .. }
                | continuation::Choice::Verify { .. } => {
                    unreachable!("observation choices handled above")
                }
            };
            let note = format!(
                "Continue the original task within these selected obligation scopes: {}.\nStrategy next step: {}\nFrozen assessment (unchanged): {}\nRead retained public evidence {} with contract_read_evidence. Other scope disputes and evidence gaps remain recorded; continuing does not certify acceptance or authorize work on disputed obligations.",
                requirements.join(", "),
                next_step,
                detail,
                public_handle,
            );
            if choice.action() == Action::Successor {
                Box::pin(self.succeed(
                    decision,
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
            let result = self
                .ports
                .submit_repair(note.clone(), handoff.turn_id)
                .await;
            self.record_event(
                ExperimentKind::Execution,
                None,
                json!({
                    "phase":"continuation_submission","continuation":decision,
                    "thread_id":self.thread_id.to_string(),"action":"resume",
                    "submitted":result.is_ok(),"error":result.as_ref().err(),
                    "meaning":"Submission acknowledgement, not an execution or correctness receipt."
                }),
            )
            .await;
            match result {
                Ok(()) => self.record_status("repairing", &note, false).await,
                Err(reason) => {
                    self.rest(
                        "did_not_pass",
                        &format!("repair could not start: {reason}\n{note}"),
                    )
                    .await
                }
            }
            return;
        }
    }

    async fn finish_continuation(&self, class: Option<NotVerifiedClass>, detail: &str) {
        match class {
            Some(class) => self.not_verified(class, detail).await,
            None => self.rest("did_not_pass", detail).await,
        }
    }
}
