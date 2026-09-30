use serde::Deserialize;
use serde::Serialize;

/// One numbered acceptance requirement, with the provenance the completeness review needs.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Requirement {
    pub id: String,
    pub text: String,
    /// The verbatim span of the human request this requirement comes from.
    pub source_quote: String,
    /// Whether the requirement is inferred rather than stated.
    pub inferred: bool,
}

/// A request element that was not turned into a requirement.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OutOfScope {
    pub element: String,
    /// The human statement that excluded it; `None` only for non-substantive elements.
    pub human_statement: Option<String>,
    pub non_substantive: bool,
}

/// The contract's terms: frozen at Issue and hashed into `terms_hash`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Terms {
    /// The human request, verbatim.
    pub intake_text: String,
    pub requirements: Vec<Requirement>,
    pub out_of_scope: Vec<OutOfScope>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    ChecksAndReview,
    ReviewOnly,
}

/// One invocation run against both the candidate and the reference; only the invocation is
/// frozen, not the expected output.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DifferentialCase {
    pub id: String,
    pub args: Vec<String>,
    pub stdin: Option<String>,
}

/// What evidence settles the claim; frozen at Issue and hashed into `evidence_policy_hash`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidencePolicy {
    pub class: EvidenceClass,
    /// Shell command, run in the candidate root, that builds the candidate.
    pub build_command: Option<String>,
    /// Path of the built candidate program, relative to the candidate root.
    pub candidate_command: Option<String>,
    /// Run the candidate's own `cargo test --offline` when it has a `Cargo.toml`.
    pub candidate_tests: bool,
    pub differential: Vec<DifferentialCase>,
    /// The black-box reference program the differential cases compare against.
    pub reference_command: Option<String>,
}

/// How the subject is captured; frozen at intake and hashed into `capture_policy_hash`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapturePolicy {
    pub version: u32,
    /// Paths relative to the workspace root that are never part of the subject. No ignore
    /// files are consulted, so editing `.gitignore` cannot hide anything.
    pub excluded_paths: Vec<String>,
    pub max_file_bytes: u64,
    pub max_total_bytes: u64,
}
