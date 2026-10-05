//! The drafter turns a frozen intake into terms and an evidence policy. It sees only the
//! verbatim human request and the base workspace, never the executor's live work.

use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::PROMPT_EVIDENCE_CAP;
use super::WorkerError;
use super::bounded;
use super::cases;
use super::strict_object;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::OutOfScope;
use crate::ProcessConstraint;
use crate::Requirement;
use crate::Terms;

/// Most public differential cases a draft may freeze.
const MAX_DIFFERENTIAL_CASES: usize = 40;

/// Everything the drafter may see.
pub(crate) struct DraftInput<'a> {
    pub intake_text: &'a str,
    /// Base workspace listing and documentation excerpts, already bounded by the caller.
    pub base_view: &'a str,
    /// Black-box observations of the reference program, if one exists.
    pub reference_observations: Option<&'a str>,
    pub reference_command: Option<&'a str>,
    /// Copied into the evidence policy; the drafter does not choose them.
    pub build_command: Option<&'a str>,
    pub candidate_command: Option<&'a str>,
}

/// A validated draft.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Draft {
    Contract {
        terms: Terms,
        evidence_policy: Box<EvidencePolicy>,
    },
    None {
        reason: String,
    },
}

const INSTRUCTIONS: &str = "You are the drafting worker of an automatic Principal. You turn a human request into \
contract terms that an independent verifier will check later. You never do the work yourself.

Rules:
- Decide \"contract\" when the request asks for substantive work on the workspace whose result can be checked. \
Decide \"none\" for questions, chat, exploration or trivial edits, and explain why in reason.
- Each requirement quotes, verbatim, the span of the human request it comes from (source_quote). Mark a \
requirement you infer rather than read as inferred=true, and still quote the span that motivates it.
- Cover every substantive element of the request; do not drop an element because it is hard to check. List an \
element in out_of_scope only when the human excluded it (quote that statement in human_statement) or when it is \
non-substantive (non_substantive=true and human_statement=null).
- process_constraints: constraints on how the work is done or what must not be touched (for example \
\"do not read the reference program\" or \"do not delete X while working\"), each with its verbatim source_quote. \
They bind the worker but are not requirements on the result and never belong in out_of_scope.
- Never add goals the human did not ask for.
- differential_cases: when a reference program is available, list invocations whose behavior must be identical \
for the candidate and the reference. Only the invocation is frozen, never an expected output. Exercise the \
documented interface broadly: help and version output, typical inputs on real files, options, boundaries and error \
cases. At most 40 cases. Leave the list empty when there is no reference program.
- candidate_tests: true when the candidate's own test suite must also pass.
- The verifier also builds the candidate with the configured build command.
Respond with JSON only, matching the schema.";

/// The full instructions: the drafting rules, then the case rules the prober shares.
fn instructions() -> String {
    format!(
        "{INSTRUCTIONS}\n\nDifferential cases: {}",
        cases::CASE_RULES
    )
}

pub(crate) fn prompt(input: &DraftInput<'_>) -> String {
    let reference = match (input.reference_command, input.reference_observations) {
        (Some(command), observations) => format!(
            "<reference_program command=\"{command}\">\n{}\n</reference_program>",
            bounded(observations.unwrap_or(""), PROMPT_EVIDENCE_CAP / 6)
        ),
        (None, _) => "<reference_program>none</reference_program>".to_string(),
    };
    format!(
        "{}\n\n<human_request>\n{}\n</human_request>\n\n<base_workspace>\n{}\n</base_workspace>\n\n{reference}\n",
        instructions(),
        bounded(input.intake_text, PROMPT_EVIDENCE_CAP / 6),
        bounded(input.base_view, PROMPT_EVIDENCE_CAP / 2),
    )
}

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest() -> codex_pro_contract::Digest {
    crate::digest_of("drafter_policy", &(instructions(), schema()))
}

pub(crate) fn schema() -> Value {
    strict_object(json!({
        "decision": {"type": "string", "enum": ["contract", "none"]},
        "reason": {"type": "string"},
        "requirements": {"type": "array", "items": strict_object(json!({
            "id": {"type": "string"},
            "text": {"type": "string"},
            "source_quote": {"type": "string"},
            "inferred": {"type": "boolean"},
        }))},
        "out_of_scope": {"type": "array", "items": strict_object(json!({
            "element": {"type": "string"},
            "human_statement": {"type": ["string", "null"]},
            "non_substantive": {"type": "boolean"},
        }))},
        "process_constraints": {"type": "array", "items": strict_object(json!({
            "text": {"type": "string"},
            "source_quote": {"type": "string"},
        }))},
        "differential_cases": {"type": "array", "items": cases::case_schema()},
        "candidate_tests": {"type": "boolean"},
    }))
}

/// Parses and validates the drafter's final message.
pub(crate) fn parse(message: &str, input: &DraftInput<'_>) -> Result<Draft, WorkerError> {
    let raw: RawDraft = serde_json::from_str(message.trim())
        .map_err(|error| WorkerError::Malformed(error.to_string()))?;
    match raw.decision.as_str() {
        "none" => Ok(Draft::None { reason: raw.reason }),
        "contract" => validate_contract(raw, input),
        other => Err(WorkerError::Malformed(format!("unknown decision {other}"))),
    }
}

/// The intake span a quote refers to: the quote's letters and digits must occur in the intake in
/// order and contiguously (ignoring case, whitespace and punctuation), and the span returned is
/// the intake's own text between the first and last matched character. Provenance thereby stays
/// verbatim even when the drafter slips on punctuation.
fn resolve_span(intake: &str, quote: &str) -> Option<String> {
    let skeleton = |text: &str| -> Vec<(usize, char)> {
        text.char_indices()
            .filter(|(_, c)| c.is_alphanumeric())
            .flat_map(|(index, c)| c.to_lowercase().map(move |lower| (index, lower)))
            .collect()
    };
    let needle: Vec<char> = skeleton(quote).into_iter().map(|(_, c)| c).collect();
    if needle.is_empty() {
        return None;
    }
    let haystack = skeleton(intake);
    let start = haystack
        .windows(needle.len())
        .position(|window| window.iter().map(|(_, c)| *c).eq(needle.iter().copied()))?;
    let first = haystack[start].0;
    let (last, _) = haystack[start + needle.len() - 1];
    let end = last + intake[last..].chars().next().map_or(0, char::len_utf8);
    Some(intake[first..end].to_string())
}

fn validate_contract(mut raw: RawDraft, input: &DraftInput<'_>) -> Result<Draft, WorkerError> {
    let malformed = |message: String| Err(WorkerError::Malformed(message));
    if raw.requirements.is_empty() {
        return malformed("a contract needs at least one requirement".to_string());
    }
    let mut ids = std::collections::BTreeSet::new();
    for requirement in &mut raw.requirements {
        if !ids.insert(requirement.id.clone()) {
            return malformed(format!("duplicate requirement id {}", requirement.id));
        }
        let Some(span) = resolve_span(input.intake_text, &requirement.source_quote) else {
            return malformed(format!(
                "requirement {} quotes text that is not in the request",
                requirement.id
            ));
        };
        requirement.source_quote = span;
    }
    for element in &mut raw.out_of_scope {
        if let Some(statement) = element.human_statement.as_mut() {
            let Some(span) = resolve_span(input.intake_text, statement) else {
                return malformed(format!(
                    "out-of-scope element {} cites a statement that is not in the request",
                    element.element
                ));
            };
            *statement = span;
        }
    }
    for constraint in &mut raw.process_constraints {
        let Some(span) = resolve_span(input.intake_text, &constraint.source_quote) else {
            return malformed(format!(
                "process constraint {:?} quotes text that is not in the request",
                constraint.text
            ));
        };
        constraint.source_quote = span;
    }
    if input.reference_command.is_none() && !raw.differential_cases.is_empty() {
        return malformed("differential cases need a reference program".to_string());
    }
    let differential = cases::validate_cases(raw.differential_cases, MAX_DIFFERENTIAL_CASES)?;
    Ok(Draft::Contract {
        terms: Terms {
            intake_text: input.intake_text.to_string(),
            requirements: raw.requirements,
            out_of_scope: raw.out_of_scope,
            process_constraints: raw.process_constraints,
        },
        evidence_policy: Box::new(EvidencePolicy {
            class: EvidenceClass::ChecksAndReview,
            build_command: input.build_command.map(str::to_string),
            candidate_command: input.candidate_command.map(str::to_string),
            candidate_tests: raw.candidate_tests,
            differential,
            reference_command: input.reference_command.map(str::to_string),
            sealed: Vec::new(),
            sealed_threshold_permille: codex_pro_contract_store::default_sealed_threshold_permille(
            ),
            min_sealed_qualified: codex_pro_contract_store::default_min_sealed_qualified(),
            min_success_permille: codex_pro_contract_store::default_min_success_permille(),
        }),
    })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawDraft {
    decision: String,
    reason: String,
    requirements: Vec<Requirement>,
    out_of_scope: Vec<OutOfScope>,
    #[serde(default)]
    process_constraints: Vec<ProcessConstraint>,
    differential_cases: Vec<cases::RawCase>,
    candidate_tests: bool,
}

#[cfg(test)]
#[path = "drafter_tests.rs"]
mod tests;
