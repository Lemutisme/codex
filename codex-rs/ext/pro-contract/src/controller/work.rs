//! Working evidence, separate from authority, execution budgets and model context.
//!
//! Only host observations close a recorded counterexample. This is a mechanical frontier of
//! public checks, not an oracle for arbitrary hypotheses or a new settlement rule.

use std::collections::BTreeMap;

use codex_pro_contract::Contract;
use codex_pro_contract::ContractId;
use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;

use super::decision::EvidenceBlocker;
use super::decision::Verdict;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvidencePolicy;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::workers::reviewer::Finding;
use crate::workers::reviewer::Review;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct PublicCheck {
    pub receipt: StepReceipt,
    pub invocation: Option<DifferentialCase>,
    pub command: Option<String>,
}

/// The executor-visible projection is constructed before storage. Sealed cases, their IDs,
/// invocations and individual outputs are never admitted to this type by `capture`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct PublicEvidence {
    pub contract_id: ContractId,
    pub revision: u32,
    pub generation: u64,
    pub subject_hash: Digest,
    pub evidence_policy_hash: Digest,
    pub environment_digest: Option<Digest>,
    pub evaluator_digest: Option<Digest>,
    pub pipeline_complete: bool,
    /// Operation that produced this record; absent in older retained evidence.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub assessment_scope: Option<String>,
    /// The checker already bounds detail; exact recall preserves those available bytes only.
    pub capture_boundary: String,
    pub checks: Vec<PublicCheck>,
    pub findings: Vec<Finding>,
    pub blocker: Option<EvidenceBlocker>,
    /// Retained local judgments, including coverage and scoped unknowns. An unavailable
    /// requirement does not erase an independently inspected one. Bound to this subject only.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub review: Option<Review>,
    /// Independent of checker findings: a failed check must not hide reviewer timeout.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub review_error: Option<String>,
    /// Explicit diagnostic judgments retained before a final response, including timeout.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub review_checkpoints: Vec<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution: Option<crate::ExecutionReceipt>,
    /// Host-linked computations remain readable even when the final review is partial.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub inspections: Vec<Digest>,
    /// The host-captured final response, treated as a communication artifact, not truth.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub delivery_message: Option<Digest>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub host_observations: Option<Digest>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub inspection_actions: Vec<crate::ExecutionReceipt>,
}

impl PublicEvidence {
    pub(super) fn capture(
        contract: &Contract,
        subject_hash: Digest,
        policy: &EvidencePolicy,
        receipts: Option<&CheckReceipts>,
        review: Option<&Review>,
        verdict: &Verdict,
    ) -> Self {
        let checks = receipts
            .into_iter()
            .flat_map(|r| &r.steps)
            .filter_map(|receipt| {
                let (invocation, command) = match receipt.step.as_str() {
                    "build" => (None, policy.build_command.clone()),
                    "candidate_tests" => (None, Some("cargo test --offline".into())),
                    step => {
                        let id = step.strip_prefix("public:")?;
                        let case = policy.differential.iter().find(|case| case.id == id)?;
                        (Some(case.clone()), policy.candidate_command.clone())
                    }
                };
                Some(PublicCheck {
                    receipt: receipt.clone(),
                    invocation,
                    command,
                })
            })
            .collect();
        let findings = review
            .into_iter()
            .flat_map(Review::actionable_findings)
            .cloned()
            .collect();
        let blocker = match verdict {
            Verdict::Defeat { blocker, .. } => blocker.clone(),
            Verdict::NotVerified { class, reason } => Some(EvidenceBlocker {
                class: *class,
                reason: reason.clone(),
            }),
            Verdict::Support => None,
        };
        Self {
            contract_id: contract.id.clone(), revision: contract.revision,
            generation: contract.generation, subject_hash,
            evidence_policy_hash: contract.bindings.evidence_policy_hash,
            environment_digest: receipts.map(|r| r.environment_digest),
            evaluator_digest: receipts.map(|r| r.evaluator_digest),
            pipeline_complete: receipts.is_some_and(|r| r.complete),
            assessment_scope: None,
            capture_boundary: "Checker receipts retain at most 4,000 detail bytes per step, with omission markers; they are not complete raw process streams. This archive preserves the received public receipt and invocation exactly. Sealed cases are excluded.".into(),
            checks, findings, blocker, review: review.cloned(), execution: receipts.and_then(|r| r.execution.clone()),
            inspections: Vec::new(), review_error: None, review_checkpoints: Vec::new(), delivery_message: None, host_observations: None, inspection_actions: Vec::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct OpenCheck {
    pub step: String,
    pub evidence: Digest,
    pub generation: u64,
    pub subject_hash: Digest,
}

/// A later passing result closes only that same registered check under the current policy.
/// Omitted checks and unqualified results leave earlier counterexamples available for work.
pub(super) fn frontier<'a>(
    contract: &Contract,
    records: impl IntoIterator<Item = (Digest, &'a PublicEvidence)>,
) -> Vec<OpenCheck> {
    let mut open = BTreeMap::new();
    let mut records: Vec<_> = records.into_iter().collect();
    // A superseded verifier can finish after a newer candidate. Arrival order must not undo
    // a later replay of the same frozen check.
    records.sort_by_key(|(_, record)| record.generation);
    for (handle, record) in records {
        if record.contract_id != contract.id
            || record.revision != contract.revision
            || record.evidence_policy_hash != contract.bindings.evidence_policy_hash
        {
            continue;
        }
        for check in &record.checks {
            match check.receipt.outcome {
                StepOutcome::Fail if record.pipeline_complete || check.receipt.complete => {
                    open.insert(
                        check.receipt.step.clone(),
                        OpenCheck {
                            step: check.receipt.step.clone(),
                            evidence: handle,
                            generation: record.generation,
                            subject_hash: record.subject_hash,
                        },
                    );
                }
                StepOutcome::Pass if record.pipeline_complete || check.receipt.complete => {
                    open.remove(&check.receipt.step);
                }
                StepOutcome::Fail
                | StepOutcome::Pass
                | StepOutcome::Unqualified
                | StepOutcome::Blocked => {}
            }
        }
    }
    open.into_values().collect()
}
