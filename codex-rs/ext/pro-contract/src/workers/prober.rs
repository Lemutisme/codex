//! The prober writes the sealed cases: a broad, documentation-driven differential suite frozen at
//! Issue and never shown to the executor. It sees the verbatim request, the base workspace's
//! documentation and what the reference does; never the drafter's terms nor any candidate. It
//! works in two turns: it proposes exploration cases, which the lane runs on the reference only,
//! then writes the sealed cases knowing how the reference behaves.

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;

use super::PROMPT_EVIDENCE_CAP;
use super::WORKER_PACKET_CAP;
use super::WorkerError;
use super::bounded;
use super::cases;
use super::strict_object;
use crate::DifferentialCase;
use crate::controller::views::ViewOrder;
use crate::controller::views::ViewPolicy;

/// Most exploration cases one probe may run on the reference.
pub(crate) const MAX_EXPLORATION_CASES: usize = 30;
/// Most sealed cases one probe may freeze.
pub(crate) const MAX_SEALED_CASES: usize = 300;
/// The documentation is the specification, so the prober reads more of it than the drafter.
pub(crate) const BASE_VIEW: ViewPolicy = ViewPolicy {
    cap: 120_000,
    order: ViewOrder::DocumentationFirst,
};
/// Bytes of the reference's help shown to both prober turns: one observation of two streams at the
/// checks' per-stream bound, with room for its framing.
pub(crate) const REFERENCE_HELP_CAP: usize = 36_000;
/// Bytes of reference observations shown to the writing turn.
pub(crate) const OBSERVATIONS_CAP: usize = 40_000;

/// Everything the prober may see, and how it is told to work.
pub(crate) struct ProbeInput<'a> {
    /// The version's probing instructions.
    pub instructions: &'a str,
    pub intake_text: &'a str,
    /// Documentation-first view of the base workspace, already bounded by the caller.
    pub base_view: &'a str,
    /// The reference's help output.
    pub reference_help: &'a str,
}

/// One surface of the documented interface and how the cases cover it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct Coverage {
    pub family: String,
    pub surface: String,
    pub description: String,
}

/// A validated probe: the coverage plan and the sealed cases.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Probe {
    pub coverage_plan: Vec<Coverage>,
    pub cases: Vec<DifferentialCase>,
}

#[derive(Debug, thiserror::Error)]
#[error("{stage}: {source}")]
pub(crate) struct ProbeFailure {
    pub stage: &'static str,
    pub source: WorkerError,
}

/// The built-in instructions: version 0 of this part of a policy bundle.
pub(crate) const DEFAULT_INSTRUCTIONS: &str = include_str!("../../policies/prober.md");

const EXPLORE: &str = "Turn 1 of 2: explore. Propose at most 30 exploration cases whose reference behavior you need \
to see before writing the suite: the help of each subcommand, one sample of each documented input format, typical \
combinations whose output format is unclear. They run on the reference only, twice each.";

const WRITE: &str = "Turn 2 of 2: write the sealed suite. Using the documentation and the reference observations \
below, return the coverage plan and 150 to 300 cases.";

fn instructions(policy: &str, turn: &str) -> String {
    format!(
        "{policy}\n\nCases: {}\n\n{turn}\nRespond with JSON only, matching the schema.",
        cases::CASE_RULES
    )
}

fn prompt(input: &ProbeInput<'_>, turn: &str, observations: &str) -> Result<String, WorkerError> {
    let policy = instructions(input.instructions, turn);
    let render = |parts: &[String]| {
        format!(
            "{policy}\n\n<human_request>\n{}\n</human_request>\n\n<documentation>\n{}\n</documentation>\n\n<reference_help>\n{}\n</reference_help>\n\n<reference_observations>\n{}\n</reference_observations>\n",
            parts[0], parts[1], parts[2], parts[3],
        )
    };
    let mut parts = vec![String::new(); 4];
    let mut available = WORKER_PACKET_CAP
        .checked_sub(render(&parts).len())
        .ok_or_else(|| {
            WorkerError::InputBudget("prober policy and framing exceed the packet budget".into())
        })?;
    let sources = [
        input.intake_text,
        input.base_view,
        input.reference_help,
        observations,
    ];
    let mut budgets = [
        PROMPT_EVIDENCE_CAP / 6,
        BASE_VIEW.cap,
        REFERENCE_HELP_CAP,
        OBSERVATIONS_CAP,
    ];
    for (budget, source) in budgets.iter_mut().zip(sources) {
        *budget = (*budget).min(source.len());
    }
    // Preserve the request's own allowance before sharing the remaining budget
    // among evidence sections, including UTF-8 omission markers.
    parts[0] = bounded(sources[0], budgets[0].min(available));
    available -= parts[0].len();
    let requested: usize = budgets[1..].iter().sum();
    for index in 1..parts.len() {
        let cap = if requested > available {
            budgets[index] * available / requested
        } else {
            budgets[index]
        };
        parts[index] = bounded(sources[index], cap);
    }
    Ok(render(&parts))
}

pub(crate) fn explore_prompt(input: &ProbeInput<'_>) -> Result<String, WorkerError> {
    prompt(input, EXPLORE, "")
}

pub(crate) fn write_prompt(
    input: &ProbeInput<'_>,
    observations: &str,
) -> Result<String, WorkerError> {
    prompt(input, WRITE, observations)
}

pub(crate) fn explore_schema() -> Value {
    strict_object(json!({
        "cases": {"type": "array", "maxItems": MAX_EXPLORATION_CASES, "items": cases::case_schema()},
    }))
}

pub(crate) fn write_schema() -> Value {
    strict_object(json!({
        "coverage_plan": {"type": "array", "items": strict_object(json!({
            "family": {"type": "string"},
            "surface": {"type": "string"},
            "description": {"type": "string"},
        }))},
        "cases": {"type": "array", "maxItems": MAX_SEALED_CASES, "items": cases::case_schema()},
    }))
}

/// Identity of this worker's policy: both turns' instructions, schemas and the view it reads.
pub(crate) fn policy_digest(policy: &str) -> codex_pro_contract::Digest {
    crate::digest_of(
        "prober_policy",
        &(
            instructions(policy, EXPLORE),
            instructions(policy, WRITE),
            explore_schema(),
            write_schema(),
            BASE_VIEW,
            WORKER_PACKET_CAP,
            super::WORKER_PACKET_PART_CAP,
            REFERENCE_HELP_CAP,
            OBSERVATIONS_CAP,
        ),
    )
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawExploration {
    cases: Vec<cases::RawCase>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawProbe {
    coverage_plan: Vec<Coverage>,
    cases: Vec<cases::RawCase>,
}

pub(crate) fn parse_exploration(message: &str) -> Result<Vec<DifferentialCase>, WorkerError> {
    let raw: RawExploration = serde_json::from_str(message.trim())
        .map_err(|error| WorkerError::Malformed(error.to_string()))?;
    cases::validate_cases(raw.cases, MAX_EXPLORATION_CASES)
}

pub(crate) fn parse_probe(message: &str) -> Result<Probe, WorkerError> {
    let raw: RawProbe = serde_json::from_str(message.trim())
        .map_err(|error| WorkerError::Malformed(error.to_string()))?;
    Ok(Probe {
        coverage_plan: raw.coverage_plan,
        cases: cases::validate_cases(raw.cases, MAX_SEALED_CASES)?,
    })
}

#[cfg(test)]
#[path = "prober_tests.rs"]
mod tests;
