//! The drafter turns a frozen intake into terms and an evidence policy. It sees only the
//! verbatim human request and the base workspace, never the executor's live work.

use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::PROMPT_EVIDENCE_CAP;
use super::WorkerError;
use super::bounded;
use super::strict_object;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::OutOfScope;
use crate::Requirement;
use crate::Terms;

/// Most differential cases a draft may freeze.
const MAX_DIFFERENTIAL_CASES: usize = 40;
/// Largest stdin a differential case may carry.
const MAX_CASE_STDIN_BYTES: usize = 4096;

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
        evidence_policy: EvidencePolicy,
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
- Never add goals the human did not ask for.
- differential_cases: when a reference program is available, list invocations whose standard output and exit \
status must be identical for the candidate and the reference. Only the invocation is frozen, never an expected \
output. Exercise the documented interface broadly: help and version output, typical inputs, options, boundaries \
and error cases. Each case gives args (the argument vector after the program name) and optional stdin text of at \
most 4096 bytes. At most 40 cases. Leave the list empty when there is no reference program.
- candidate_tests: true when the candidate's own test suite must also pass.
- The verifier also builds the candidate with the configured build command.
Respond with JSON only, matching the schema.";

pub(crate) fn prompt(input: &DraftInput<'_>) -> String {
    let reference = match (input.reference_command, input.reference_observations) {
        (Some(command), observations) => format!(
            "<reference_program command=\"{command}\">\n{}\n</reference_program>",
            bounded(observations.unwrap_or(""), PROMPT_EVIDENCE_CAP / 6)
        ),
        (None, _) => "<reference_program>none</reference_program>".to_string(),
    };
    format!(
        "{INSTRUCTIONS}\n\n<human_request>\n{}\n</human_request>\n\n<base_workspace>\n{}\n</base_workspace>\n\n{reference}\n",
        bounded(input.intake_text, PROMPT_EVIDENCE_CAP / 6),
        bounded(input.base_view, PROMPT_EVIDENCE_CAP / 2),
    )
}

/// Identity of this worker's policy: its instructions and output schema.
pub(crate) fn policy_digest() -> codex_pro_contract::Digest {
    crate::digest_of("drafter_policy", &(INSTRUCTIONS, schema()))
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
        "differential_cases": {"type": "array", "items": strict_object(json!({
            "id": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
            "stdin": {"type": ["string", "null"]},
        }))},
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
    if raw.differential_cases.len() > MAX_DIFFERENTIAL_CASES {
        return malformed(format!(
            "{} differential cases exceed the limit of {MAX_DIFFERENTIAL_CASES}",
            raw.differential_cases.len()
        ));
    }
    if input.reference_command.is_none() && !raw.differential_cases.is_empty() {
        return malformed("differential cases need a reference program".to_string());
    }
    let mut case_ids = std::collections::BTreeSet::new();
    for case in &raw.differential_cases {
        let plain = !case.id.is_empty()
            && case.id.len() <= 40
            && case
                .id
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'));
        if !plain {
            return malformed(format!(
                "differential case id {:?} is not a plain token",
                case.id
            ));
        }
        if !case_ids.insert(case.id.as_str()) {
            return malformed(format!("duplicate differential case id {}", case.id));
        }
        if case
            .stdin
            .as_ref()
            .is_some_and(|stdin| stdin.len() > MAX_CASE_STDIN_BYTES)
        {
            return malformed(format!("differential case {} stdin is too large", case.id));
        }
    }
    Ok(Draft::Contract {
        terms: Terms {
            intake_text: input.intake_text.to_string(),
            requirements: raw.requirements,
            out_of_scope: raw.out_of_scope,
        },
        evidence_policy: EvidencePolicy {
            class: EvidenceClass::ChecksAndReview,
            build_command: input.build_command.map(str::to_string),
            candidate_command: input.candidate_command.map(str::to_string),
            candidate_tests: raw.candidate_tests,
            differential: raw.differential_cases,
            reference_command: input.reference_command.map(str::to_string),
        },
    })
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawDraft {
    decision: String,
    reason: String,
    requirements: Vec<Requirement>,
    out_of_scope: Vec<OutOfScope>,
    differential_cases: Vec<DifferentialCase>,
    candidate_tests: bool,
}

#[cfg(test)]
#[path = "drafter_tests.rs"]
mod tests;
