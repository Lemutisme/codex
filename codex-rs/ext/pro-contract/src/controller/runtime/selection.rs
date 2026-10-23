//! Selected observations over an already frozen handoff. Capture does not schedule acceptance.

use std::sync::Arc;

use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::{Handoff, ThreadRuntime};
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
    pub(super) async fn select_handoff(self: Arc<Self>, handoff: Handoff) {
        if let Err(reason) = self.progress_ready().await {
            self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                .await;
            return;
        }
        let outcome = Verdict::NotVerified {
            class: NotVerifiedClass::InsufficientEvidence,
            reason: "The handoff was captured. No check, diagnosis or acceptance verification has been selected for this snapshot.".into(),
        };
        let mut public = PublicEvidence::capture(
            &handoff.contract,
            handoff.subject.subject_hash,
            &handoff.policy,
            None,
            None,
            &outcome,
        );
        public.assessment_scope = Some("handoff".into());
        public.delivery_message = handoff.response.handle();
        match self
            .retain_work_observation(&handoff, &public, "handoff_ready", None, None)
            .await
        {
            Ok((handle, basis)) => {
                self.choose_continuation(handoff, public, handle, basis, outcome)
                    .await
            }
            Err(reason) => {
                self.not_verified(NotVerifiedClass::Infrastructure, &reason)
                    .await
            }
        }
    }

    pub(super) async fn retain_work_observation(
        &self,
        handoff: &Handoff,
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
        handoff: &Handoff,
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
        self.record_status(
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
