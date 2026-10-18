//! The reviewer judges a frozen candidate against frozen terms. It sees the verbatim intake,
//! the terms, bounded frozen artifacts and host-scoped observations. An executor's final
//! response is a communication artifact, not independent proof of its assertions.

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
#[serde(deny_unknown_fields)]
pub struct MissingEvidence {
    pub requirement_id: String,
    pub reason: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TermsGap {
    pub element: String,
    pub reason: String,
    /// Existing requirements whose authority/scope is disputed. An empty list identifies an
    /// omitted request element; None is an older unscoped gap and conservatively blocks repair.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub affected_requirements: Option<Vec<String>>,
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
    /// Local judgments survive independently of other requirements' evidence gaps.
    Partial {
        coverage: Vec<Coverage>,
        findings: Vec<Finding>,
        missing: Vec<MissingEvidence>,
        unscoped_missing: String,
    },
}

/// A validated review: the verdict, and separately whether the terms are faithful to the request.
/// A gap makes the verdict unusable for settlement but the verdict is kept for measurement.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Review {
    pub verdict: ReviewVerdict,
    /// Where the terms may have missed, widened or weakened part of the human request.
    pub terms_gap: Vec<TermsGap>,
    /// Derived by the host from the frozen catalog, never chosen by the reviewer.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub execution_obligations: Vec<String>,
}

impl Review {
    /// Only findings outside explicitly identified scope disputes can direct a bounded repair.
    pub(crate) fn actionable_findings(&self) -> Vec<&Finding> {
        let findings = match &self.verdict {
            ReviewVerdict::Defeat { findings, .. } | ReviewVerdict::Partial { findings, .. } => {
                findings
            }
            _ => return Vec::new(),
        };
        findings
            .iter()
            .filter(|finding| {
                !self.execution_obligations.contains(&finding.requirement_id)
                    && self.terms_gap.iter().all(|gap| {
                        gap.affected_requirements
                            .as_ref()
                            .is_some_and(|ids| !ids.contains(&finding.requirement_id))
                    })
            })
            .collect()
    }

    pub(crate) fn execution_findings(&self) -> Vec<&Finding> {
        let findings = match &self.verdict {
            ReviewVerdict::Defeat { findings, .. } | ReviewVerdict::Partial { findings, .. } => {
                findings
            }
            _ => return Vec::new(),
        };
        findings
            .iter()
            .filter(|f| self.execution_obligations.contains(&f.requirement_id))
            .collect()
    }
}

/// The built-in instructions: version 0 of this part of a policy bundle.
pub(crate) const DEFAULT_INSTRUCTIONS: &str = include_str!("../../policies/reviewer.md");

pub(crate) const OUTPUT_CONVENTIONS: &str = "Use [] for absent lists and \"\" for absent missing/residual text. Nonempty missing declares an unresolved evidence gap; describe only actual gaps.";

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest(policy: &str) -> codex_pro_contract::Digest {
    crate::digest_of(
        "reviewer_policy",
        &(
            policy,
            schema(),
            "scoped-obligations-and-host-check-receipts-v2",
            super::review_evidence::ReviewEvidence::tool(),
        ),
    )
}

pub(crate) fn schema() -> Value {
    let mut value = strict_object(json!({
        "verdict": {"type": "string", "enum": ["support", "defeat", "cannot_judge", "partial"]},
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
            "affected_requirements": {"type": "array", "items": {"type": "string"}},
        }))},
        "missing": {"type": "string"},
        "gaps": {"type":"array", "items": strict_object(json!({
            "requirement_id":{"type":"string"}, "reason":{"type":"string"},
        }))},
        "residual": {"type": "string"},
    }));
    value["description"] = json!(OUTPUT_CONVENTIONS);
    value
}

/// The wire field keeps its historical name; its values are exact catalog obligation IDs.
pub(crate) fn schema_for(terms: &Terms) -> Value {
    let mut value = schema();
    let ids: Vec<_> = terms.obligations().into_iter().map(|r| r.id).collect();
    for field in ["coverage", "findings", "gaps"] {
        value["properties"][field]["items"]["properties"]["requirement_id"]["enum"] = json!(ids);
    }
    value["properties"]["terms_gap"]["items"]["properties"]["affected_requirements"]["items"]["enum"] =
        json!(ids);
    value
}

pub(crate) fn parse(message: &str, terms: &Terms) -> Result<Review, WorkerError> {
    let raw: RawReview = serde_json::from_str(message.trim())
        .map_err(|error| WorkerError::Malformed(error.to_string()))?;
    let terms_gap = raw.terms_gap.clone();
    if let Some(id) = terms_gap
        .iter()
        .filter_map(|gap| gap.affected_requirements.as_ref())
        .flatten()
        .find(|id| !terms.obligations().iter().any(|r| &r.id == *id))
    {
        return Err(WorkerError::Malformed(format!(
            "terms gap names unknown requirement {id}"
        )));
    }
    Ok(Review {
        verdict: verdict(raw, terms)?,
        terms_gap,
        execution_obligations: terms
            .obligations()
            .into_iter()
            .filter(|r| r.scope == crate::ObligationScope::Execution)
            .map(|r| r.id)
            .collect(),
    })
}

fn verdict(raw: RawReview, terms: &Terms) -> Result<ReviewVerdict, WorkerError> {
    if !matches!(
        raw.verdict.as_str(),
        "support" | "defeat" | "cannot_judge" | "partial"
    ) {
        return Err(WorkerError::Malformed(format!(
            "unknown verdict {}",
            raw.verdict
        )));
    }
    let obligations = terms.obligations();
    let known = |id: &str| obligations.iter().any(|r| r.id == id);
    // New structured partial judgments also preserve mixed legacy responses. The host,
    // not the model's headline verdict, determines whether every obligation is supported.
    let mixed = raw.verdict == "partial"
        || !raw.gaps.is_empty()
        || (raw.verdict == "support"
            && (!raw.findings.is_empty()
                || obligations
                    .iter()
                    .any(|r| !raw.coverage.iter().any(|c| c.requirement_id == r.id))))
        || (raw.verdict != "support" && !raw.coverage.is_empty())
        || (raw.verdict == "cannot_judge" && !raw.findings.is_empty())
        || (!raw.missing.trim().is_empty()
            && (!raw.coverage.is_empty() || !raw.findings.is_empty()));
    if mixed {
        let mut missing = raw.gaps;
        let mut supported = std::collections::BTreeSet::new();
        for row in &raw.coverage {
            if !known(&row.requirement_id) || !supported.insert(&row.requirement_id) {
                return Err(WorkerError::Malformed(
                    "unknown or duplicate coverage requirement".into(),
                ));
            }
        }
        for id in raw
            .findings
            .iter()
            .map(|r| &r.requirement_id)
            .chain(missing.iter().map(|r| &r.requirement_id))
        {
            if !known(id) || supported.contains(id) {
                return Err(WorkerError::Malformed(
                    "unknown or contradictory requirement judgment".into(),
                ));
            }
        }
        if missing.iter().any(|gap| gap.reason.trim().is_empty()) {
            return Err(WorkerError::Malformed(
                "a scoped evidence gap must give its reason".into(),
            ));
        }
        for requirement in &obligations {
            if !supported.contains(&requirement.id)
                && !raw
                    .findings
                    .iter()
                    .any(|f| f.requirement_id == requirement.id)
                && !missing.iter().any(|g| g.requirement_id == requirement.id)
            {
                missing.push(MissingEvidence {
                    requirement_id: requirement.id.clone(),
                    reason: if raw.missing.trim().is_empty() {
                        "not assessed".into()
                    } else {
                        raw.missing.clone()
                    },
                });
            }
        }
        if raw.findings.is_empty() && missing.is_empty() && raw.missing.trim().is_empty() {
            return Ok(ReviewVerdict::Support {
                coverage: raw.coverage,
            });
        }
        return Ok(ReviewVerdict::Partial {
            coverage: raw.coverage,
            findings: raw.findings,
            missing,
            unscoped_missing: raw.missing,
        });
    }
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
            if let Some(uncovered) = obligations.iter().find(|requirement| {
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
    #[serde(default)]
    gaps: Vec<MissingEvidence>,
    residual: String,
}

#[cfg(test)]
#[path = "reviewer_tests.rs"]
mod tests;
