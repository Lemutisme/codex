//! The reviewer judges a frozen candidate against frozen terms. It sees the verbatim intake,
//! the terms, the check receipts and bounded reads of the frozen candidate — never the executor's
//! transcript or final message.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::WorkerError;
use super::strict_object;
use crate::Terms;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Coverage {
    pub requirement_id: String,
    pub evidence: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Finding {
    pub requirement_id: String,
    pub location: String,
    pub counterexample: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TermsGap {
    pub element: String,
    pub reason: String,
}

/// The reviewer's judgment of the candidate against the terms.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ReviewVerdict {
    Support {
        coverage: Vec<Coverage>,
    },
    Defeat {
        findings: Vec<Finding>,
        residual: String,
    },
    CannotJudge {
        missing: String,
    },
}

/// A validated review: the verdict, and separately whether the terms are faithful to the request.
/// A gap makes the verdict unusable for settlement but the verdict is kept for measurement.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Review {
    pub verdict: ReviewVerdict,
    /// Where the terms may have missed, widened or weakened part of the human request.
    pub terms_gap: Vec<TermsGap>,
}

/// The built-in instructions: version 0 of this part of a policy bundle.
pub(crate) const DEFAULT_INSTRUCTIONS: &str = include_str!("../../policies/reviewer.md");

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest(policy: &str) -> codex_pro_contract::Digest {
    crate::digest_of(
        "reviewer_policy",
        &(
            policy,
            schema(),
            "frozen-evidence-read-handles-v2",
            super::review_evidence::ReviewEvidence::tool(),
        ),
    )
}

pub(crate) fn schema() -> Value {
    strict_object(json!({
        "verdict": {"type": "string", "enum": ["support", "defeat", "cannot_judge"]},
        "coverage": {"type": "array", "items": strict_object(json!({
            "requirement_id": {"type": "string"},
            "evidence": {"type": "string"},
        }))},
        "findings": {"type": "array", "items": strict_object(json!({
            "requirement_id": {"type": "string"},
            "location": {"type": "string"},
            "counterexample": {"type": "string"},
        }))},
        "terms_gap": {"type": "array", "items": strict_object(json!({
            "element": {"type": "string"},
            "reason": {"type": "string"},
        }))},
        "missing": {"type": "string"},
        "residual": {"type": "string"},
    }))
}

pub(crate) fn parse(message: &str, terms: &Terms) -> Result<Review, WorkerError> {
    let raw: RawReview = serde_json::from_str(message.trim())
        .map_err(|error| WorkerError::Malformed(error.to_string()))?;
    let terms_gap = raw.terms_gap.clone();
    Ok(Review {
        verdict: verdict(raw, terms)?,
        terms_gap,
    })
}

fn verdict(raw: RawReview, terms: &Terms) -> Result<ReviewVerdict, WorkerError> {
    let known = |id: &str| {
        terms
            .requirements
            .iter()
            .any(|requirement| requirement.id == id)
    };
    match raw.verdict.as_str() {
        "support" => {
            if let Some(unknown) = raw
                .coverage
                .iter()
                .find(|entry| !known(&entry.requirement_id))
            {
                return Err(WorkerError::Malformed(format!(
                    "coverage names unknown requirement {}",
                    unknown.requirement_id
                )));
            }
            if let Some(uncovered) = terms.requirements.iter().find(|requirement| {
                !raw.coverage
                    .iter()
                    .any(|entry| entry.requirement_id == requirement.id)
            }) {
                return Ok(ReviewVerdict::CannotJudge {
                    missing: format!("no coverage for requirement {}", uncovered.id),
                });
            }
            Ok(ReviewVerdict::Support {
                coverage: raw.coverage,
            })
        }
        "defeat" => {
            if raw.findings.is_empty() {
                return Err(WorkerError::Malformed(
                    "a defeat needs findings".to_string(),
                ));
            }
            if let Some(unknown) = raw
                .findings
                .iter()
                .find(|finding| !known(&finding.requirement_id))
            {
                return Err(WorkerError::Malformed(format!(
                    "finding names unknown requirement {}",
                    unknown.requirement_id
                )));
            }
            Ok(ReviewVerdict::Defeat {
                findings: raw.findings,
                residual: raw.residual,
            })
        }
        "cannot_judge" => {
            if raw.missing.trim().is_empty() {
                return Err(WorkerError::Malformed(
                    "cannot_judge must say what is missing".to_string(),
                ));
            }
            Ok(ReviewVerdict::CannotJudge {
                missing: raw.missing,
            })
        }
        other => Err(WorkerError::Malformed(format!("unknown verdict {other}"))),
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawReview {
    verdict: String,
    coverage: Vec<Coverage>,
    findings: Vec<Finding>,
    terms_gap: Vec<TermsGap>,
    missing: String,
    residual: String,
}

#[cfg(test)]
#[path = "reviewer_tests.rs"]
mod tests;
