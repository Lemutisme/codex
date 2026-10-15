//! Frozen-artifact verification, durable evidence, and the resulting continuation decision.

use std::sync::Arc;
use std::time::Duration;

use codex_pro_contract::Command;
use codex_pro_contract::Contract;
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
use super::Handoff;
use super::Phase;
use super::ThreadRuntime;
use crate::CheckReceipts;
use crate::Subject;
use crate::digest_of;
use crate::workers::reviewer;
use crate::workers::runtime::WorkerTurn;

const CHECK_SUMMARY_CAP: usize = 15_000;

impl ThreadRuntime {
    pub(super) async fn verify(self: Arc<Self>, handoff: Handoff) {
        let Handoff {
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
            self.not_verified(
                NotVerifiedClass::Infrastructure,
                &format!("materialization failed: {error}"),
            )
            .await;
            return;
        }
        let checks = self
            .ports
            .run_checks(&self.profile.check, &work, &base.dir, &policy)
            .await;
        // The reviewer is asked only when the mechanical evidence leaves the decision to it.
        let review = match (&checks, decision::mechanical_verdict(&checks, &policy)) {
            (Ok(receipts), None) => {
                let summary = decision::review_summary(receipts, &policy);
                let evidence = crate::workers::review_evidence::ReviewEvidence::new(
                    subject.clone(),
                    self.store.clone(),
                    &terms,
                    crate::workers::bounded(&summary, CHECK_SUMMARY_CAP),
                );
                let message = match evidence {
                    Ok(evidence) => {
                        self.ports
                            .run_worker(WorkerTurn {
                                prompt: evidence.prompt(&self.policies.reviewer),
                                schema: reviewer::schema(),
                                trigger: "pro_contract_review",
                                deadline: Duration::from_secs(self.settings.worker.deadline_secs),
                                evidence: Some(evidence),
                            })
                            .await
                    }
                    Err(error) => Err(error),
                };
                Some(message.and_then(|message| reviewer::parse(&message, &terms)))
            }
            _ => None,
        };
        let mut verdict = decide(&checks, review.as_ref(), &policy);
        let mut public = super::super::work::PublicEvidence::capture(
            &contract,
            subject.subject_hash,
            &policy,
            checks.as_ref().ok(),
            review.as_ref().and_then(|r| r.as_ref().ok()),
            &verdict,
        );
        if matches!(verdict, Verdict::Support) {
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
                self.not_verified(
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
                self.not_verified(
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
        match verdict {
            Verdict::Support => {
                self.support(contract, &subject, base.subject, checks.ok(), review)
                    .await
            }
            Verdict::Defeat { residual, blocker } => {
                self.defeat(
                    Handoff {
                        epoch,
                        contract,
                        subject,
                        turn_id,
                        policy,
                        terms,
                        base,
                    },
                    residual,
                    blocker,
                    verification,
                )
                .await
            }
            Verdict::NotVerified { class, reason } => self.not_verified(class, &reason).await,
        }
    }

    async fn support(
        &self,
        contract: Contract,
        subject: &Subject,
        base_subject: Digest,
        receipts: Option<CheckReceipts>,
        review: Option<Result<reviewer::Review, crate::WorkerError>>,
    ) {
        let Some(receipts) = receipts else {
            self.not_verified(NotVerifiedClass::Infrastructure, "support without receipts")
                .await;
            return;
        };
        let review = review.and_then(Result::ok);
        let evidence_hash = digest_of("evidence", &(&receipts, &review));
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
            // The request (in the terms), the base workspace, the cases and the oracle image.
            basis: digest_of(
                "basis",
                &(
                    contract.bindings.terms_hash,
                    base_subject,
                    contract.bindings.evidence_policy_hash,
                    receipts.environment_digest,
                ),
            ),
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
                self.rest(
                    "supported",
                    "checks passed · review supported · on evidence within the executor's reach (diligence)",
                )
                .await
            }
            Err(error) => {
                self.not_verified(
                    NotVerifiedClass::Infrastructure,
                    &format!("support failed: {error}"),
                )
                .await
            }
        }
    }

    async fn defeat(
        self: Arc<Self>,
        handoff: Handoff,
        residual: String,
        blocker: Option<super::super::decision::EvidenceBlocker>,
        verification: Digest,
    ) {
        let Handoff {
            contract,
            subject,
            turn_id,
            epoch,
            ..
        } = handoff;
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
                    defeater: verification,
                },
                &format!("defeat:{}:{}", contract.id.0, contract.generation),
            )
            .await;
        if let Err(error) = defeated {
            self.not_verified(
                NotVerifiedClass::Infrastructure,
                &format!("defeat failed: {error}"),
            )
            .await;
            return;
        }
        if let Some(blocker) = blocker {
            self.not_verified(
                blocker.class,
                &format!(
                    "candidate defeated; continuation blocked: {}",
                    blocker.reason
                ),
            )
            .await;
            return;
        }
        let residual = format!(
            "{residual}\nRecover prior public checks and exact retained details with contract_read_evidence; earlier counterexamples remain in the archive."
        );
        if self.settings.succession.is_some() {
            Box::pin(self.succeed(subject.subject_hash, residual, turn_id, epoch)).await;
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
            state.repair_note = Some(residual.clone());
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
