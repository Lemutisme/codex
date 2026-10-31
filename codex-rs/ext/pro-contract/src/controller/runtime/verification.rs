//! Frozen-artifact verification, durable evidence, and the resulting continuation decision.

use std::sync::Arc;
use std::time::Duration;

use codex_pro_contract::Command;
use codex_pro_contract::Coordinate;
use codex_pro_contract::Digest;
use codex_pro_contract::Provenance;
use codex_pro_contract::Reach;
use codex_pro_contract::Role;
use codex_pro_contract::Target;
use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::super::decision;
use super::super::decision::NotVerifiedClass;
use super::super::decision::Verdict;
use super::super::decision::decide;
use super::ThreadRuntime;
use super::WorkSnapshot;
use crate::CheckReceipts;
use crate::digest_of;
use crate::workers::reviewer;
use crate::workers::runtime::WorkerTurn;

const CHECK_SUMMARY_CAP: usize = 15_000;

pub(super) struct Assessment {
    pub(super) checks: Result<CheckReceipts, crate::CheckError>,
    pub(super) review: Option<Result<reviewer::Review, crate::WorkerError>>,
    pub(super) verdict: Verdict,
    pub(super) effects_resolved: bool,
    pub(super) public: super::super::work::PublicEvidence,
}

#[derive(Default)]
pub(super) struct Diagnosis {
    pub(super) question: Option<String>,
    pub(super) prior: Option<serde_json::Value>,
    pub(super) checks: Option<CheckReceipts>,
}

impl ThreadRuntime {
    pub(super) async fn assess_snapshot(
        &self,
        handoff: &WorkSnapshot,
        work: &std::path::Path,
        deadline_ms: Option<u64>,
        formal: bool,
        diagnostic_review: bool,
        diagnosis: Option<&Diagnosis>,
    ) -> Assessment {
        let WorkSnapshot {
            contract,
            subject,
            terms,
            policy,
            base,
            ..
        } = handoff;
        let mut check_environment = self.profile.check.clone();
        check_environment.timeout_secs = self
            .action_seconds(deadline_ms, check_environment.timeout_secs)
            .await
            .unwrap_or(0);
        let checks = if let Some(receipts) = diagnosis.and_then(|d| d.checks.as_ref()) {
            Ok(receipts.clone())
        } else if check_environment.timeout_secs == 0 {
            Err(crate::CheckError::TimedOut)
        } else {
            self.ports
                .run_checks(&check_environment, work, &base.dir, policy)
                .await
        };
        let review_seconds = self
            .action_seconds(deadline_ms, self.settings.worker.deadline_secs)
            .await
            .unwrap_or(0);
        // Checking an artifact and asking for judgment are separate capabilities.
        let review_needed = formal || diagnostic_review;
        let mut host_observations = None;
        let assessment_id = digest_of(
            "assessment_action",
            &(
                contract.id.clone(),
                subject.subject_hash,
                &handoff.turn_id,
                work,
                formal,
            ),
        );
        let review = match (&checks, decision::mechanical_verdict(&checks, policy)) {
            (observations, mechanical)
                if review_needed
                    && review_seconds > 0
                    && (mechanical.is_none() || diagnostic_review) =>
            {
                let summary = match observations {
                    Ok(receipts) => decision::review_summary(receipts, policy),
                    Err(error) => format!(
                        "Check capability could not produce a result: {error}. No candidate failure or success follows from this method error."
                    ),
                };
                let baseline = self
                    .ledger
                    .subject_binding(&base.subject)
                    .await
                    .map_err(|e| crate::WorkerError::Start(e.to_string()))
                    .and_then(|binding| {
                        binding.ok_or_else(|| {
                            crate::WorkerError::Start(
                                "original task baseline is unavailable".into(),
                            )
                        })
                    })
                    .and_then(|binding| {
                        codex_pro_contract_store::load_subject(
                            &self.store,
                            &binding.manifest,
                            &base.subject,
                        )
                        .map_err(|e| crate::WorkerError::Start(e.to_string()))
                    });
                let observation = match &baseline {
                    Ok(baseline) => super::super::observations::snapshot(
                        &self.ledger,
                        &self.store,
                        super::super::observations::AssessmentScope {
                            contract,
                            terms,
                            subject,
                            baseline,
                            owner_thread: &self.thread_id.to_string(),
                            turn: &handoff.turn_id,
                            epoch: handoff.epoch,
                            capture: handoff.capture,
                        },
                    )
                    .await
                    .map_err(crate::WorkerError::Start),
                    Err(error) => Err(crate::WorkerError::Start(error.to_string())),
                }
                .map(|mut document| {
                    if !self.profile.check.inputs.is_empty() {
                        document["task_inputs"] =
                            serde_json::json!(self.profile.check.input_capabilities());
                    }
                    document
                });
                let evidence = baseline
                    .and_then(|baseline| {
                        crate::workers::review_evidence::ReviewEvidence::new(
                            (*subject).clone(),
                            self.store.clone(),
                            terms,
                            crate::workers::bounded(&summary, CHECK_SUMMARY_CAP),
                        )
                        .map(|evidence| evidence.with_baseline(baseline))
                    })
                    .and_then(|evidence| {
                        let document = observation?;
                        let evidence = evidence.with_host_observations(document.clone())?;
                        host_observations = Some(self.store.put(document.to_string().as_bytes())
                            .map_err(|e| crate::WorkerError::Start(e.to_string()))?);
                        Ok(evidence.with_protocol_log(self.ledger.clone(), self.identities(None), json!({
                            "contract_id":contract.id.0,"revision":contract.revision,"generation":contract.generation,
                            "turn_id":handoff.turn_id,"formal":formal,"host_observations":host_observations,
                            "assessment_id":assessment_id,
                        })))
                    })
                    .and_then(|evidence| if !formal {
                        evidence.with_diagnosis(diagnosis.and_then(|d| d.question.as_deref()), diagnosis.and_then(|d| d.prior.clone()))
                    } else { Ok(evidence) })
                    .and_then(|evidence| match handoff.response.handle() {
                        None => Ok(evidence),
                        Some(handle) => self
                            .store
                            .get(&handle)
                            .map_err(|e| crate::WorkerError::Start(e.to_string()))
                            .and_then(|bytes| {
                                serde_json::from_slice(&bytes)
                                    .map_err(|e| crate::WorkerError::Malformed(e.to_string()))
                            })
                            .and_then(|message| evidence.with_delivery_message(message)),
                    })
                    .and_then(|evidence| match &self.settings.review_execution {
                        Some(grant) => evidence.with_execution(
                            self.profile.check.clone(),
                            grant.clone(),
                            work.with_extension("review"),
                            Duration::from_secs(review_seconds),
                        ),
                        None => Ok(evidence),
                    });
                let message = match evidence {
                    Ok(evidence) => {
                        self.ports
                            .run_worker(WorkerTurn {
                                prompt: evidence.prompt(&self.policies.reviewer),
                                schema: reviewer::schema_for(terms),
                                trigger: "pro_contract_review",
                                deadline: Duration::from_secs(review_seconds),
                                evidence: Some(evidence),
                                archive: None,
                                resources: self.settings.resource_snapshot.clone(),
                            })
                            .await
                    }
                    Err(error) => Err(error),
                };
                Some(message.and_then(|message| reviewer::parse(&message, terms)))
            }
            _ => None,
        };
        let mut verdict = if !review_needed
            && decision::mechanical_verdict(&checks, policy).is_none()
        {
            Verdict::NotVerified { class: NotVerifiedClass::InsufficientEvidence,
                reason: "Public executable checks completed for this frozen snapshot. Independent review and full acceptance were not performed.".into() }
        } else {
            decide(&checks, review.as_ref(), policy)
        };
        // Keep independent computations even if their reviewer cannot finish judging.
        // Only the host's grant may link these handles into the public task archive.
        let inspection_history = if let Some(grant) = &self.settings.review_execution
            && work.with_extension("review").join("grant.json").exists()
        {
            match crate::inspection_grant::InspectionGrant::open(
                self.profile.check.clone(),
                grant.clone(),
                work.with_extension("review"),
                subject.subject_hash,
                terms,
                Duration::ZERO,
            ) {
                Ok(grant) => {
                    grant.wait_for_owned_actions().await;
                    grant
                        .history(&self.store)
                        .and_then(|history| Ok((history, grant.actions()?)))
                }
                Err(error) => Err(error),
            }
        } else {
            Ok((Vec::new(), Vec::new()))
        };
        if let Err(reason) = &inspection_history {
            verdict = Verdict::NotVerified {
                class: NotVerifiedClass::Infrastructure,
                reason: format!("inspection evidence could not be recovered: {reason}"),
            };
        }
        if let Ok((_, actions)) = &inspection_history
            && actions.iter().any(|action| !action.shutdown_confirmed)
        {
            verdict = Verdict::NotVerified {
                class: NotVerifiedClass::Infrastructure,
                reason:
                    "inspection shutdown remains unconfirmed; reconcile before further execution"
                        .into(),
            };
        }
        let effects_resolved = checks
            .as_ref()
            .is_ok_and(|r| r.execution.as_ref().is_none_or(|a| a.shutdown_confirmed))
            && inspection_history
                .as_ref()
                .is_ok_and(|(_, actions)| actions.iter().all(|a| a.shutdown_confirmed));
        let mut public = super::super::work::PublicEvidence::capture(
            contract,
            subject.subject_hash,
            policy,
            checks.as_ref().ok(),
            review.as_ref().and_then(|r| r.as_ref().ok()),
            &verdict,
        );
        public.assessment_scope = Some(
            if formal {
                "verification"
            } else if diagnostic_review {
                "diagnosis"
            } else {
                "checks"
            }
            .into(),
        );
        public.delivery_message = handoff.response.handle();
        public.review_error = review
            .as_ref()
            .and_then(|r| r.as_ref().err())
            .map(ToString::to_string);
        public.host_observations = host_observations;
        // Checkpoints are independent durable outputs. They do not replace the final
        // review or its error, and cannot issue Support through the acceptance path.
        match self.ledger.experiments().await {
            Ok(events) => {
                for event in events {
                    if event.event.body["phase"] == "review_checkpoint"
                        && event.event.body["binding"]["assessment_id"] == json!(assessment_id)
                        && let Ok(handle) =
                            serde_json::from_value(event.event.body["handle"].clone())
                    {
                        public.review_checkpoints.push(handle);
                    }
                }
            }
            Err(error) => tracing::warn!("pro_contract checkpoint index unavailable: {error}"),
        }
        if let Ok((documents, actions)) = inspection_history {
            public.inspections = documents
                .iter()
                .map(|text| Digest::of(text.as_bytes()))
                .collect();
            public.inspection_actions = actions;
        }
        if formal && matches!(verdict, Verdict::Support) {
            match self.evidence_access().unresolved_with(&public).await {
                Ok(open) if open.is_empty() => {}
                Ok(open) => {
                    verdict = Verdict::NotVerified {
                        class: NotVerifiedClass::InsufficientEvidence,
                        reason: format!(
                            "{} retained public counterexamples have no complete passing replay; inspect contract_read_evidence frontier",
                            open.len()
                        ),
                    };
                }
                Err(reason) => {
                    verdict = Verdict::NotVerified {
                        class: NotVerifiedClass::Infrastructure,
                        reason,
                    };
                }
            }
            public.blocker = match &verdict {
                Verdict::NotVerified { class, reason } => {
                    Some(super::super::decision::EvidenceBlocker {
                        class: *class,
                        reason: reason.clone(),
                    })
                }
                _ => None,
            };
        }
        Assessment {
            checks,
            review,
            verdict,
            public,
            effects_resolved,
        }
    }

    pub(super) async fn verify(self: Arc<Self>, mut handoff: WorkSnapshot) {
        let operation_epoch = handoff.epoch;
        if let Err(reason) = self.progress_ready().await {
            self.not_verified_for(operation_epoch, NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        if let super::delivery::ResponseCapture::Unavailable { reason } = &handoff.response {
            self.not_verified_for(
                operation_epoch,
                NotVerifiedClass::Infrastructure,
                &format!("delivery response could not be retained: {reason}"),
            )
            .await;
            return;
        }
        {
            let state = self.state.lock().await;
            if state.epoch != handoff.epoch || state.phase != super::Phase::Verifying {
                return;
            }
        }
        // Verification needs a current proposal for these exact bytes. Capture
        // origin does not determine whether the candidate still exists: Defeat
        // can retire any proposal while retaining the work for later observation.
        if handoff.contract.candidate.is_none_or(|candidate| {
            candidate.generation != handoff.contract.generation
                || candidate.subject_hash != handoff.subject.subject_hash
        }) && let Err(error) = self.propose_work(&mut handoff).await
        {
            self.not_verified_for(
                operation_epoch,
                NotVerifiedClass::Infrastructure,
                &format!("proposal of observed work failed: {error}"),
            )
            .await;
            return;
        }
        let WorkSnapshot {
            capture,
            response,
            epoch,
            contract,
            subject,
            turn_id,
            policy,
            terms,
            base,
        } = handoff;
        let work = self
            .work_dir()
            .join(contract.generation.to_string())
            .join("candidate");
        if let Err(error) = self.materialize(&subject, &work).await {
            self.not_verified_for(
                operation_epoch,
                NotVerifiedClass::Infrastructure,
                &format!("materialization failed: {error}"),
            )
            .await;
            return;
        }
        let assessment = self
            .assess_snapshot(
                &WorkSnapshot {
                    capture,
                    response: response.clone(),
                    epoch,
                    contract: contract.clone(),
                    subject: subject.clone(),
                    turn_id: turn_id.clone(),
                    policy: policy.clone(),
                    terms: terms.clone(),
                    base: base.clone(),
                },
                &work,
                None,
                true,
                false,
                None,
            )
            .await;
        let Assessment {
            checks,
            review,
            verdict,
            public,
            effects_resolved,
        } = assessment;
        let (verdict_name, class, detail) = match &verdict {
            Verdict::Support => ("support", "", ""),
            Verdict::Defeat { residual, .. } => ("defeat", "", residual.as_str()),
            Verdict::NotVerified { class, reason } => {
                ("not_verified", class.as_str(), reason.as_str())
            }
        };
        let public_evidence = match serde_json::to_vec(&public)
            .map_err(|e| e.to_string())
            .and_then(|bytes| self.store.put(&bytes).map_err(|e| e.to_string()))
        {
            Ok(handle) => handle,
            Err(reason) => {
                self.not_verified_for(
                    operation_epoch,
                    NotVerifiedClass::Infrastructure,
                    &format!("working evidence could not be retained: {reason}"),
                )
                .await;
                return;
            }
        };
        let verification = self.append_event(
            ExperimentKind::Verification,
            checks
                .as_ref()
                .ok()
                .map(|receipts| receipts.evaluator_digest),
            json!({
                "contract_id": contract.id.0,
                "generation": contract.generation,
                "subject_hash": subject.subject_hash,
                "public_evidence": public_evidence,
                "evidence_blocker": public.blocker,
                "verdict": verdict_name,
                "class": class,
                "detail": detail,
                "receipts": checks.as_ref().ok(),
                "sealed": checks.as_ref().ok().map(|receipts| decision::sealed_tally(receipts, &policy)),
                "check_error": checks.as_ref().err().map(ToString::to_string),
                "review": review.as_ref().and_then(|review| review.as_ref().ok()),
            }),
        )
        .await;
        let verification = match verification {
            Ok(handle) => handle,
            Err(reason) => {
                self.not_verified_for(
                    operation_epoch,
                    NotVerifiedClass::Infrastructure,
                    &format!("verification was not committed: {reason}"),
                )
                .await;
                return;
            }
        };
        if self.state.lock().await.epoch != epoch {
            return; // Owner input superseded this frozen handoff; do not schedule stale work.
        }
        let handoff = WorkSnapshot {
            capture,
            response,
            epoch,
            contract,
            subject,
            turn_id,
            policy,
            terms,
            base,
        };
        match verdict {
            Verdict::Support => {
                let basis = digest_of(
                    "basis",
                    &(
                        handoff.contract.bindings.terms_hash,
                        handoff.base.subject,
                        handoff.contract.bindings.evidence_policy_hash,
                        checks.as_ref().ok().map(|r| r.environment_digest),
                        public.host_observations,
                        handoff.response.handle(),
                    ),
                );
                self.support(handoff, basis, checks.ok(), review, verification)
                    .await
            }
            Verdict::Defeat { residual, blocker } => {
                self.defeat(
                    handoff,
                    residual,
                    blocker,
                    verification,
                    public,
                    public_evidence,
                )
                .await
            }
            Verdict::NotVerified { class, reason }
                if effects_resolved
                    && matches!(
                        class,
                        NotVerifiedClass::ReviewerUnable
                            | NotVerifiedClass::TermsGap
                            | NotVerifiedClass::ExecutionConstraint
                            | NotVerifiedClass::InsufficientEvidence
                            | NotVerifiedClass::ExecutionInterrupted
                            | NotVerifiedClass::Infrastructure
                    ) =>
            {
                self.choose_continuation(
                    handoff,
                    public,
                    public_evidence,
                    verification,
                    Verdict::NotVerified { class, reason },
                )
                .await;
            }
            Verdict::NotVerified { class, reason } => {
                self.not_verified_for(operation_epoch, class, &reason).await
            }
        }
    }

    async fn support(
        &self,
        handoff: WorkSnapshot,
        basis: Digest,
        receipts: Option<CheckReceipts>,
        review: Option<Result<reviewer::Review, crate::WorkerError>>,
        verification: Digest,
    ) {
        let WorkSnapshot {
            contract,
            subject,
            epoch,
            ..
        } = handoff;
        let Some(receipts) = receipts else {
            self.not_verified_for(
                epoch,
                NotVerifiedClass::Infrastructure,
                "support without receipts",
            )
            .await;
            return;
        };
        let review = review.and_then(Result::ok);
        // The committed verification links the complete host observation document as well
        // as artifact/check evidence. Its exact prefix cannot be replaced after Support.
        let evidence_hash = digest_of("evidence", &(&receipts, &review, verification));
        let worker = self.ports.worker_identity();
        let evaluator_digest = digest_of(
            "evaluator",
            &(
                receipts.evaluator_digest,
                reviewer::policy_digest(&self.policies.reviewer),
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
            // All supplied sources, including execution observations and the delivered response.
            basis,
            // Every source the lane draws on (the request, the workspace, the reference it queries)
            // was within the executor's reach: its support measures diligence and certifies
            // nothing beyond. Only the principal, or what the principal seals, is beyond.
            reach: Reach::Within,
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
                self.record_status_for(
                    epoch,
                    "supported",
                    "checks passed · review supported · on evidence within the executor's reach (diligence)",
                    true,
                )
                .await
            }
            Err(error) => {
                self.not_verified_for(epoch,
                    NotVerifiedClass::Infrastructure,
                    &format!("support failed: {error}"),
                )
                .await
            }
        }
    }

    async fn defeat(
        self: Arc<Self>,
        mut handoff: WorkSnapshot,
        residual: String,
        blocker: Option<super::super::decision::EvidenceBlocker>,
        verification: Digest,
        public: super::super::work::PublicEvidence,
        public_evidence: Digest,
    ) {
        let epoch = handoff.epoch;
        let contract = &handoff.contract;
        let subject = &handoff.subject;
        let defeated = self
            .apply(
                contract,
                Role::Verifier,
                Provenance::Automation,
                Command::Defeat {
                    target: Target::Candidate {
                        generation: contract.generation,
                        subject_hash: subject.subject_hash,
                    },
                    defeater: verification,
                },
                &format!("defeat:{}:{}", contract.id.0, contract.generation),
            )
            .await;
        match defeated {
            Ok(contract) => handoff.contract = contract,
            Err(error) => {
                self.not_verified_for(
                    epoch,
                    NotVerifiedClass::Infrastructure,
                    &format!("defeat failed: {error}"),
                )
                .await;
                return;
            }
        }
        // The operation context advances; public evidence still identifies the
        // generation and subject that were actually assessed before this Defeat.
        self.choose_continuation(
            handoff,
            public,
            public_evidence,
            verification,
            Verdict::Defeat { residual, blocker },
        )
        .await;
    }
}
