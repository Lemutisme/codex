//! Producer identities for experiment events: which harness, policies and model made a record.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use codex_pro_contract::Digest;
use codex_pro_contract_store::Identities;
use sha2::Digest as _;

use super::ports::WorkerIdentity;
use crate::workers::drafter;
use crate::workers::prober;
use crate::workers::reviewer;

/// SHA-256 of the running harness executable, computed once.
pub(crate) fn harness_sha256() -> Option<String> {
    static HARNESS: OnceLock<Option<String>> = OnceLock::new();
    HARNESS
        .get_or_init(|| {
            let bytes = std::env::current_exe().and_then(std::fs::read).ok()?;
            Some(format!("{:x}", sha2::Sha256::digest(bytes)))
        })
        .clone()
}

/// The identities stamped on an event: harness, worker policies, and the worker's model.
pub(crate) fn identities(worker: &WorkerIdentity, check_pipeline: Option<Digest>) -> Identities {
    let mut policies = BTreeMap::from([
        ("drafter".to_string(), drafter::policy_digest()),
        ("prober".to_string(), prober::policy_digest()),
        ("reviewer".to_string(), reviewer::policy_digest()),
    ]);
    if let Some(check_pipeline) = check_pipeline {
        policies.insert("check_pipeline".to_string(), check_pipeline);
    }
    Identities {
        harness: harness_sha256(),
        policies,
        model: worker.model.clone(),
        effort: worker.effort.clone(),
        evaluator_epoch: None,
    }
}
