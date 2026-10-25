//! Selected observations over an already frozen handoff. Capture does not schedule acceptance.

use std::sync::Arc;

use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::{Phase, ThreadRuntime, WorkSnapshot};
use crate::controller::decision::{NotVerifiedClass, Verdict};
use crate::controller::work::PublicEvidence;

/// Local observation does not run withheld acceptance cases or decide their eligibility.
/// The original issued policy is retained unchanged for formal verification.
pub(super) fn public_checks_policy(policy: &crate::EvidencePolicy) -> crate::EvidencePolicy {
    let mut public = policy.clone();
    public.sealed.clear();
    public.sealed_threshold_permille = None;
    public.min_sealed_qualified = None;
    public.min_success_permille = None;
    public.preparation_failure = None;
    public
}

impl ThreadRuntime {
    pub(super) async fn select_handoff(self: Arc<Self>, handoff: WorkSnapshot) {
        let outcome = Verdict::NotVerified {
            class: NotVerifiedClass::InsufficientEvidence,
            reason: "The handoff was captured. No check, diagnosis or acceptance verification has been selected for this snapshot.".into(),
        };
        self.select_snapshot(handoff, outcome, "handoff").await;
    }

    /// An interrupted executor supplied work, not a delivery or an acceptance claim.
    /// Lifecycle callers invoke this only after that executor stopped. The existing
    /// selector decides whether the retained work calls for checks, repair or rest.
    pub(super) async fn select_interrupted(self: Arc<Self>, reason: String, epoch: u64) {
        let snapshot = {
            let mut state = self.state.lock().await;
            if state.epoch != epoch
                || state.phase != Phase::Working
                || state.last_idle != Some(codex_extension_api::ThreadIdleCause::Failed)
            {
                return;
            }
            match (&state.frozen, &state.contract) {
                (Some(frozen), Some(active))
                    if active.contract.standing == codex_pro_contract::Standing::Outstanding =>
                {
                    let snapshot = WorkSnapshot {
                        capture: crate::controller::observations::CaptureKind::Interrupted,
                        response: super::delivery::ResponseCapture::Absent,
                        epoch: state.epoch,
                        contract: active.contract.clone(),
                        subject: frozen.subject.clone(),
                        turn_id: frozen.turn_id.clone(),
                        policy: active.policy.clone(),
                        terms: active.terms.clone(),
                        base: active.base.clone(),
                    };
                    state.phase = Phase::Verifying;
                    Some(snapshot)
                }
                (_, Some(active))
                    if active.contract.standing != codex_pro_contract::Standing::Outstanding =>
                {
                    return;
                }
                _ => None,
            }
        };
        let Some(snapshot) = snapshot else {
            self.not_verified_for(
                epoch,
                NotVerifiedClass::NoHandoff,
                "interrupted work snapshot unavailable",
            )
            .await;
            return;
        };
        if let Err(error) = self
            .append_event(
                ExperimentKind::Capture,
                None,
                json!({
                    "phase":"interrupted_snapshot", "thread_id":self.thread_id.to_string(),
                    "contract_id":snapshot.contract.id, "turn_id":snapshot.turn_id,
                    "execution_epoch":snapshot.epoch, "subject_hash":snapshot.subject.subject_hash,
                    "reason":reason, "handoff":false, "completion_certified":false,
                }),
            )
            .await
        {
            self.not_verified_for(epoch, NotVerifiedClass::Infrastructure, &error)
                .await;
            return;
        }
        self.select_snapshot(
            snapshot,
            Verdict::NotVerified {
                class: NotVerifiedClass::ExecutionInterrupted,
                reason,
            },
            "interruption",
        )
        .await;
    }

    async fn select_snapshot(
        self: Arc<Self>,
        handoff: WorkSnapshot,
        outcome: Verdict,
        scope: &str,
    ) {
        if let Err(reason) = self.progress_ready().await {
            self.not_verified_for(handoff.epoch, NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        let mut public = PublicEvidence::capture(
            &handoff.contract,
            handoff.subject.subject_hash,
            &handoff.policy,
            None,
            None,
            &outcome,
        );
        public.assessment_scope = Some(scope.into());
        public.delivery_message = handoff.response.handle();
        match self
            .retain_work_observation(
                &handoff,
                &public,
                if scope == "handoff" {
                    "handoff_ready"
                } else {
                    "work_ready"
                },
                None,
                None,
            )
            .await
        {
            Ok((handle, basis)) => {
                self.choose_continuation(handoff, public, handle, basis, outcome)
                    .await
            }
            Err(reason) => {
                self.not_verified_for(handoff.epoch, NotVerifiedClass::Infrastructure, &reason)
                    .await
            }
        }
    }

    pub(super) async fn retain_work_observation(
        &self,
        handoff: &WorkSnapshot,
        public: &PublicEvidence,
        phase: &str,
        selection: Option<Digest>,
        question: Option<&str>,
    ) -> Result<(Digest, Digest), String> {
        let handle = self
            .store
            .put(&serde_json::to_vec(public).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        let basis = self.append_event(ExperimentKind::Execution, public.evaluator_digest, json!({
            "phase":phase,"contract_id":handoff.contract.id,"generation":handoff.contract.generation,
            "subject_hash":handoff.subject.subject_hash,"turn_id":handoff.turn_id,
            "execution_epoch":handoff.epoch,"continuation":selection,
            "assessment_scope":public.assessment_scope,"question":question,"public_evidence":handle,
        })).await?;
        Ok((handle, basis))
    }

    pub(super) async fn observe_handoff(
        &self,
        handoff: &WorkSnapshot,
        selection: Digest,
        question: Option<String>,
        reusable_checks: Option<crate::CheckReceipts>,
        prior: Option<serde_json::Value>,
    ) -> Result<super::verification::Assessment, String> {
        self.progress_ready().await?;
        self.action_seconds(None, 1).await?;
        let work = self
            .work_dir()
            .join("selected")
            .join(selection.to_string())
            .join("candidate");
        self.append_event(
            ExperimentKind::Execution,
            None,
            json!({
                "phase":"work_assessment_reserved","continuation":selection,
                "contract_id":handoff.contract.id,"subject_hash":handoff.subject.subject_hash,
                "assessment_scope":if question.is_some() {"diagnosis"} else {"checks"},
            }),
        )
        .await?;
        self.materialize(&handoff.subject, &work).await?;
        // Adaptive observations do not query or reveal withheld acceptance cases.
        let mut local = handoff.clone();
        local.policy = public_checks_policy(&handoff.policy);
        let diagnosis = super::verification::Diagnosis {
            question: question.clone(),
            prior,
            checks: reusable_checks,
        };
        self.record_status_for(
            handoff.epoch,
            "observing",
            "running the selected frozen observation",
            false,
        )
        .await;
        Ok(self
            .assess_snapshot(
                &local,
                &work,
                None,
                false,
                question.is_some(),
                Some(&diagnosis),
            )
            .await)
    }
}
