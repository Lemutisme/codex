//! Calibrate the actual frozen invocations against the reference before candidate judgment.
//! This establishes readiness, not coverage or candidate correctness.

use std::path::Path;

use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::ThreadRuntime;
use crate::EvidencePolicy;

impl ThreadRuntime {
    pub(super) async fn calibrate(&self, policy: &EvidencePolicy, base: &Path) -> Option<String> {
        let (Some(reference), Some(_)) = (&policy.reference_command, &policy.candidate_command)
        else {
            return None;
        };
        let observed = self
            .ports
            .observe(&self.profile.check, base, reference, &policy.sealed)
            .await;
        let (qualified, succeeded, failure) = match &observed {
            Ok(observations) => {
                let qualified = observations
                    .iter()
                    .filter(|o| o.stable && o.exit.is_some_and(|rc| !matches!(rc, 124 | 137)))
                    .count();
                let succeeded = observations
                    .iter()
                    .filter(|o| o.stable && o.exit == Some(0))
                    .count();
                let complete = observations
                    .iter()
                    .map(|o| &o.id)
                    .eq(policy.sealed.iter().map(|c| &c.id));
                let ready = complete
                    && qualified >= policy.min_sealed_qualified as usize
                    && succeeded as u64 * 1000
                        >= u64::from(policy.min_success_permille) * qualified as u64;
                let failure = (!ready).then(|| format!(
                    "reference calibration incomplete: {qualified}/{} stable qualified invocations, {succeeded} successful; requires {} qualified and {}‰ successful (complete={complete})",
                    policy.sealed.len(), policy.min_sealed_qualified, policy.min_success_permille,
                ));
                (qualified, succeeded, failure)
            }
            Err(error) => (
                0,
                0,
                Some(format!("reference calibration could not run: {error}")),
            ),
        };
        // Only aggregate readiness is shown to executors. Exact reference observations stay
        // in the private immutable journal and never enter the public evidence projection.
        let committed = self
            .append_event(
                ExperimentKind::Probe,
                None,
                json!({
                    "thread_id": self.thread_id.to_string(), "phase": "calibration",
                    "qualified": qualified, "succeeded": succeeded,
                    "observations": observed.as_ref().ok(), "failure": failure,
                }),
            )
            .await;
        match committed {
            Ok(_) => failure,
            Err(reason) => Some(format!(
                "reference calibration could not be retained: {reason}"
            )),
        }
    }
}
