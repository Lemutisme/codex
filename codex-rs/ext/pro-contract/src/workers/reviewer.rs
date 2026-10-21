//! The reviewer judges a frozen candidate against frozen terms. It sees the verbatim intake,
//! the terms, bounded frozen artifacts and host-scoped observations. An executor's final
//! response is a communication artifact, not independent proof of its assertions.

use std::collections::BTreeMap;

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
    /// Issued ID on the model wire; stable key in `Review.citations` after resolution.
    /// Historical reviews retain their original inline evidence.
    pub evidence: String,
}

/// One host-bound evidence range, shared by every judgment that cites it.
/// Stored with the review so public paging and diagnostic continuation retain it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Citation {
    pub subject_hash: codex_pro_contract::Digest,
    pub terms_hash: codex_pro_contract::Digest,
    pub source_id: String,
    pub sha256: codex_pro_contract::Digest,
    pub start: usize,
    pub end: usize,
    pub quote: String,
}

/// A scoped observation is not a conclusion that the entire obligation is satisfied.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub requirement_id: String,
    pub detail: String,
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
    /// Host-derived evidence, not additional model output or authority.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub citations: BTreeMap<String, Citation>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub observations: Vec<Observation>,
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

pub(crate) const OUTPUT_CONVENTIONS: &str = "Give each assessed obligation exactly one judgment. observations records local facts, not complete support. Use supported only for the whole obligation, defeated for concrete counterexamples, unresolved for missing evidence. Partial positive observations can accompany either defeated or unresolved. Use [] for absent lists and \"\" for absent text.";

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest(policy: &str) -> codex_pro_contract::Digest {
    crate::digest_of(
        "reviewer_policy",
        &(
            policy,
            schema(),
            "scoped-observations-and-exclusive-conclusions-v3",
            "diagnostic-checkpoints-v2-derived-missing",
            "scoped-obligations-v2-interned-request-sources",
            "shared-bound-review-citations-v1",
            super::review_evidence::ReviewEvidence::tool(),
        ),
    )
}

pub(crate) fn schema() -> Value {
    let mut value = strict_object(json!({
        "assessments": {"type": "array", "items": strict_object(json!({
            "requirement_id": {"type": "string"},
            "observations": {"type": "string"},
            "judgment": {"anyOf": [
                strict_object(json!({
                    "status": {"type":"string", "enum":["supported"]},
                    "evidence": {
                        "type":"string", "pattern":"^e(0|[1-9][0-9]*)$",
                        "description":"One exact citation_id issued by read_evidence, for example e12. Put explanations in observations, never in this field. The host checks issuance, source and subject scope."
                    },
                })),
                strict_object(json!({
                    "status": {"type":"string", "enum":["defeated"]},
                    "findings": {"type":"array", "items": strict_object(json!({
                        "location":{"type":"string"}, "counterexample":{"type":"string"},
                    }))},
                    "missing": {"type":"string"},
                })),
                strict_object(json!({
                    "status": {"type":"string", "enum":["unresolved"]},
                    "missing": {"type":"string"},
                })),
            ]},
        }))},
        "terms_gap": {"type": "array", "items": strict_object(json!({
            "element": {"type": "string"},
            "reason": {"type": "string"},
            "affected_requirements": {"type": "array", "items": {"type": "string"}},
        }))},
    }));
    value["description"] = json!(OUTPUT_CONVENTIONS);
    value
}

/// The wire field keeps its historical name; its values are exact catalog obligation IDs.
pub(crate) fn schema_for(terms: &Terms) -> Value {
    let mut value = schema();
    let ids: Vec<_> = terms.obligations().into_iter().map(|r| r.id).collect();
    value["properties"]["assessments"]["items"]["properties"]["requirement_id"]["enum"] =
        json!(ids);
    value["properties"]["terms_gap"]["items"]["properties"]["affected_requirements"]["items"]["enum"] =
        json!(ids);
    value
}

pub(crate) fn parse(message: &str, terms: &Terms) -> Result<Review, WorkerError> {
    let raw = decode(message)?;
    let observations = raw.observations.clone();
    if let Some(row) = observations.iter().find(|row| {
        !terms
            .obligations()
            .iter()
            .any(|o| o.id == row.requirement_id)
    }) {
        return Err(WorkerError::Malformed(format!(
            "observation names unknown requirement {}",
            row.requirement_id
        )));
    }
    let terms_gap = raw.terms_gap.clone();
    let citations = raw.citations.clone();
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
        citations,
        observations,
        terms_gap,
        execution_obligations: terms
            .obligations()
            .into_iter()
            .filter(|r| r.scope == crate::ObligationScope::Execution)
            .map(|r| r.id)
            .collect(),
    })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScopedReview {
    assessments: Vec<Assessment>,
    terms_gap: Vec<TermsGap>,
    // Retain historical free-standing gaps. New responses express gaps on the
    // relevant judgment; omitting this redundant aggregate cannot erase them.
    #[serde(default)]
    missing: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Assessment {
    requirement_id: String,
    observations: String,
    judgment: Judgment,
}

#[derive(Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum Judgment {
    Supported {
        evidence: String,
    },
    Defeated {
        findings: Vec<Counterexample>,
        missing: String,
    },
    Unresolved {
        missing: String,
    },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Counterexample {
    location: String,
    counterexample: String,
}

/// Keep old retained responses readable; new workers use exclusive per-obligation judgments.
fn decode(message: &str) -> Result<RawReview, WorkerError> {
    let malformed = |error: serde_json::Error| WorkerError::Malformed(error.to_string());
    let shape: Value = serde_json::from_str(message).map_err(malformed)?;
    if shape.get("assessments").is_none() {
        return serde_json::from_str(message).map_err(malformed);
    }
    let scoped: ScopedReview = serde_json::from_str(message).map_err(malformed)?;
    let mut raw = RawReview {
        verdict: "partial".into(),
        citations: BTreeMap::new(),
        coverage: Vec::new(),
        findings: Vec::new(),
        gaps: Vec::new(),
        observations: Vec::new(),
        terms_gap: scoped.terms_gap,
        missing: scoped.missing,
        residual: String::new(),
    };
    let mut seen = std::collections::BTreeSet::new();
    for row in scoped.assessments {
        let id = row.requirement_id;
        if !seen.insert(id.clone()) {
            return Err(WorkerError::Malformed(format!(
                "duplicate assessment for {id}"
            )));
        }
        if !row.observations.trim().is_empty() {
            raw.observations.push(Observation {
                requirement_id: id.clone(),
                detail: row.observations,
            });
        }
        match row.judgment {
            Judgment::Supported { evidence } => {
                if evidence.trim().is_empty() {
                    return Err(WorkerError::Malformed(format!(
                        "supported obligation {id} needs evidence"
                    )));
                }
                raw.coverage.push(Coverage {
                    requirement_id: id,
                    evidence,
                });
            }
            Judgment::Defeated { findings, missing } => {
                if findings.is_empty()
                    || findings.iter().any(|f| f.counterexample.trim().is_empty())
                {
                    return Err(WorkerError::Malformed(format!(
                        "defeated obligation {id} needs a concrete counterexample"
                    )));
                }
                raw.findings.extend(findings.into_iter().map(|f| Finding {
                    requirement_id: id.clone(),
                    location: f.location,
                    counterexample: f.counterexample,
                }));
                if !missing.trim().is_empty() {
                    raw.gaps.push(MissingEvidence {
                        requirement_id: id,
                        reason: missing,
                    });
                }
            }
            Judgment::Unresolved { missing } => {
                if missing.trim().is_empty() {
                    return Err(WorkerError::Malformed(format!(
                        "unresolved obligation {id} needs its evidence gap"
                    )));
                }
                raw.gaps.push(MissingEvidence {
                    requirement_id: id,
                    reason: missing,
                });
            }
        }
    }
    Ok(raw)
}

/// Normalize only the wire representation. No observation is promoted to support.
pub(crate) fn normalize(message: &str) -> Result<Value, WorkerError> {
    serde_json::to_value(decode(message)?).map_err(|e| WorkerError::Malformed(e.to_string()))
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

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawReview {
    verdict: String,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    citations: BTreeMap<String, Citation>,
    coverage: Vec<Coverage>,
    findings: Vec<Finding>,
    terms_gap: Vec<TermsGap>,
    missing: String,
    #[serde(default)]
    gaps: Vec<MissingEvidence>,
    residual: String,
    #[serde(default)]
    observations: Vec<Observation>,
}

#[cfg(test)]
#[path = "reviewer_tests.rs"]
mod tests;
