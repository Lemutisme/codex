use std::collections::BTreeMap;

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

/// A constraint on how the work is done rather than on what it produces (for example "do not read
/// the reference executable"). It binds the executor, but only the artifact can be judged.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessConstraint {
    pub text: String,
    /// The verbatim span of the human request this constraint comes from.
    pub source_quote: String,
}

/// The contract's terms: frozen at Issue and hashed into `terms_hash`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Terms {
    /// The human request, verbatim.
    pub intake_text: String,
    pub requirements: Vec<Requirement>,
    pub out_of_scope: Vec<OutOfScope>,
    #[serde(default)]
    pub process_constraints: Vec<ProcessConstraint>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    ChecksAndReview,
    ReviewOnly,
}

/// One invocation run against both the candidate and the reference; only the invocation and its
/// fixtures are frozen, never the expected output.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DifferentialCase {
    pub id: String,
    pub args: Vec<String>,
    pub stdin: Option<String>,
    /// Files written into the case directory, over the base workspace, before each run.
    #[serde(default)]
    pub files: Vec<FixtureFile>,
    /// Empty directories created in the case directory before each run.
    #[serde(default)]
    pub dirs: Vec<String>,
    /// Environment variables set for both programs.
    #[serde(default)]
    pub env: BTreeMap<String, String>,
    /// Coverage tag; the only detail of a sealed case an executor may see.
    #[serde(default)]
    pub family: String,
}

/// A fixture file whose content is `text` repeated `repeat` times.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FixtureFile {
    /// Relative to the case directory, without `..`.
    pub path: String,
    pub text: String,
    #[serde(default = "one")]
    pub repeat: u32,
}

fn one() -> u32 {
    1
}

impl FixtureFile {
    /// The file's content.
    pub fn content(&self) -> String {
        self.text.repeat(self.repeat as usize)
    }

    /// The content's length, computed without building it.
    pub fn len(&self) -> usize {
        self.text.len().saturating_mul(self.repeat as usize)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
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
    /// Public cases: drafted up front and shown in residuals.
    pub differential: Vec<DifferentialCase>,
    /// The black-box reference program the differential cases compare against.
    pub reference_command: Option<String>,
    /// Sealed cases: written by the prober, never shown to the executor.
    #[serde(default)]
    pub sealed: Vec<DifferentialCase>,
    /// The sealed pass rate support needs, in permille.
    #[serde(default = "default_sealed_threshold_permille")]
    pub sealed_threshold_permille: u16,
    /// Fewest qualified sealed cases that count as evidence.
    #[serde(default = "default_min_sealed_qualified")]
    pub min_sealed_qualified: u32,
    /// Smallest share, in permille, of qualified sealed cases whose reference run succeeds.
    #[serde(default = "default_min_success_permille")]
    pub min_success_permille: u16,
}

pub fn default_sealed_threshold_permille() -> u16 {
    950
}

pub fn default_min_sealed_qualified() -> u32 {
    100
}

pub fn default_min_success_permille() -> u16 {
    500
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

impl CapturePolicy {
    /// The capture policy every ProContract capture uses: version 1, 64 MiB per file, 1 GiB in total.
    pub fn standard(excluded_paths: Vec<String>) -> Self {
        Self {
            version: 1,
            excluded_paths,
            max_file_bytes: 64 << 20,
            max_total_bytes: 1 << 30,
        }
    }
}
