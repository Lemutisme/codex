//! The reviewer judges a frozen candidate against frozen terms. It sees the verbatim intake,
//! the terms, the check receipts and a bounded view of the candidate — never the executor's
//! transcript or final message.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::PROMPT_EVIDENCE_CAP;
use super::WorkerError;
use super::bounded;
use super::strict_object;
use crate::Terms;
use crate::controller::views::ViewOrder;
use crate::controller::views::ViewPolicy;

/// What the reviewer sees of the candidate: build files and sources before documentation, and
/// enough of them that a single-binary candidate of about 300 KB of source is shown whole while
/// the prompt stays well inside a 272K-token context window.
pub(crate) const CANDIDATE_VIEW: ViewPolicy = ViewPolicy {
    cap: 480_000,
    order: ViewOrder::SourcesFirst,
};

pub(crate) struct ReviewInput<'a> {
    /// The version's review instructions.
    pub instructions: &'a str,
    pub terms: &'a Terms,
    /// Check receipts rendered for the reviewer, already bounded by the caller.
    pub check_summary: &'a str,
    /// Candidate listing and file contents, already bounded by the caller.
    pub candidate_view: &'a str,
}

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

pub(crate) fn prompt(input: &ReviewInput<'_>) -> String {
    let requirements: String = input
        .terms
        .requirements
        .iter()
        .map(|requirement| {
            format!(
                "{}: {} (quote: \"{}\"{})\n",
                requirement.id,
                requirement.text,
                requirement.source_quote,
                if requirement.inferred {
                    ", inferred"
                } else {
                    ""
                }
            )
        })
        .collect();
    let out_of_scope: String = input
        .terms
        .out_of_scope
        .iter()
        .map(|element| {
            format!(
                "{} (human statement: {})\n",
                element.element,
                element
                    .human_statement
                    .as_deref()
                    .unwrap_or("none; non-substantive")
            )
        })
        .collect();
    let process_constraints: String = input
        .terms
        .process_constraints
        .iter()
        .map(|constraint| {
            format!(
                "{} (quote: \"{}\")\n",
                constraint.text, constraint.source_quote
            )
        })
        .collect();
    format!(
        "{}\n\n<human_request>\n{}\n</human_request>\n\n<requirements>\n{}</requirements>\n\n<process_constraints>\n{}</process_constraints>\n\n<out_of_scope>\n{}</out_of_scope>\n\n<check_receipts>\n{}\n</check_receipts>\n\n<candidate>\n{}\n</candidate>\n",
        input.instructions,
        bounded(&input.terms.intake_text, PROMPT_EVIDENCE_CAP / 8),
        bounded(&requirements, PROMPT_EVIDENCE_CAP / 8),
        bounded(&process_constraints, PROMPT_EVIDENCE_CAP / 16),
        bounded(&out_of_scope, PROMPT_EVIDENCE_CAP / 16),
        bounded(input.check_summary, PROMPT_EVIDENCE_CAP / 4),
        bounded(input.candidate_view, CANDIDATE_VIEW.cap),
    )
}

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest(policy: &str) -> codex_pro_contract::Digest {
    crate::digest_of("reviewer_policy", &(policy, schema(), CANDIDATE_VIEW))
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
