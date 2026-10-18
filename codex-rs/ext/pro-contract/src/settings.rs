use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;

/// File under `CODEX_HOME/pro_contract/` holding the extension's settings.
pub const SETTINGS_FILE: &str = "settings.json";

/// Extension settings, kept outside `config.toml` so strict configuration loading is unaffected.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    /// The pre-authorized evaluation Principal grant (spec §13.1). Without it no contract is
    /// ever issued in this slice.
    pub evaluation: Option<EvaluationProfile>,
    /// Automatic repairs per work episode.
    #[serde(default = "default_repair_attempts")]
    pub repair_attempts: u32,
    /// Opt-in fresh executor sessions under one intake-time grant. Legacy settings keep
    /// same-thread repair behavior; a successor never issues a new contract or grant.
    #[serde(default)]
    pub succession: Option<SuccessionSettings>,
    #[serde(default)]
    pub worker: WorkerSettings,
    #[serde(default)]
    pub evidence: EvidenceSettings,
    /// Explicit host grant for read-only computations over selected frozen evidence. Uses the
    /// existing check image/runtime; absence keeps artifact review entirely container-free.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub review_execution: Option<ReviewExecution>,
    /// Bounded, same-turn publication and public assessment under the original task grant.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub progress: Option<ProgressSettings>,
    /// Context bundle: `work_method.md` replaces the executor strategy; `drafter.md`,
    /// `prober.md` and `reviewer.md` replace the corresponding worker instructions.
    #[serde(default)]
    pub policy: Option<PathBuf>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewExecution {
    pub max_calls: u32,
    pub timeout_secs: u64,
    pub max_output_bytes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProgressSettings {
    /// Provisioner-owned Docker label, not a model-selected container or path.
    pub executor_label: String,
    /// Optional explicit count grant; absent means the original task deadline bounds use.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_publications: Option<u32>,
    pub assessment_secs: u64,
    pub executor_slice_secs: u64,
}

/// An operator's finite grant for replacing failed executor contexts, not resetting a task.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SuccessionSettings {
    /// Optional explicit count grant; absent means the original task deadline bounds use.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_sessions: Option<u32>,
    /// Wall-clock lifetime from original intake, including the original executor.
    pub total_secs: u64,
}

/// Explicit quantitative acceptance criteria, when supplied by the task owner.
/// Absent cutoffs leave evidence interpretation to the review strategy.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceSettings {
    #[serde(default)]
    pub sealed_threshold_permille: Option<u16>,
    #[serde(default)]
    pub min_sealed_qualified: Option<u32>,
    #[serde(default)]
    pub min_success_permille: Option<u16>,
}

/// The evaluation profile of spec §13: an isolated container executor environment and a
/// container check environment, both described explicitly by the operator.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationProfile {
    /// The only environment the executor may use; it must be an isolated container.
    pub environment_id: String,
    /// The workspace root as the executor sees it inside the container.
    pub workspace_container_root: String,
    /// The same workspace as a host directory (the bind-mount source), read by capture.
    pub workspace_host_root: PathBuf,
    /// Paths relative to the workspace root that are never part of the subject.
    pub excluded_paths: Vec<String>,
    pub check: CheckEnvironment,
    /// A black-box reference program available inside the check environment, if any.
    pub reference_command: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CheckEnvironment {
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub inputs: Vec<TaskInput>,
    pub docker: String,
    pub image: String,
    pub user: String,
    /// Where the materialized candidate is mounted inside the check container.
    pub candidate_mount: String,
    pub timeout_secs: u64,
    /// Shell command, run in the candidate root, that builds the candidate.
    pub build_command: Option<String>,
    /// Path of the built candidate program, relative to the candidate root.
    pub candidate_command: Option<String>,
}

/// Provisioner-owned input files, independent of the candidate workspace.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskInput {
    pub name: String,
    pub source: PathBuf,
    pub digest: codex_pro_contract::Digest,
}

impl CheckEnvironment {
    pub(crate) fn input_mount_args(&self) -> Result<Vec<String>, String> {
        let mut names = std::collections::BTreeSet::new();
        let mut args = Vec::new();
        for input in &self.inputs {
            if input.name.is_empty()
                || input.name.len() > 128
                || !input
                    .name
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
                || input.name == "."
                || input.name == ".."
                || !names.insert(&input.name)
                || !input.source.is_absolute()
                || input.source.to_string_lossy().contains([',', '\n', '\0'])
            {
                return Err("invalid declared task input mount".into());
            }
            args.extend([
                "--mount".to_string(),
                format!(
                    "type=bind,src={},dst=/inputs/{},readonly",
                    input.source.display(),
                    input.name
                ),
            ]);
        }
        Ok(args)
    }

    pub(crate) fn input_capabilities(&self) -> Vec<serde_json::Value> {
        self.inputs.iter().map(|input| serde_json::json!({
            "name":input.name,"path":format!("/inputs/{}",input.name),"sha256":input.digest,"access":"read_only",
            "scope":"declared task input available to checks and enabled frozen computations; availability does not attest executor access"
        })).collect()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerSettings {
    /// Worker model; the parent thread's model when absent.
    pub model: Option<String>,
    /// Worker reasoning effort; the parent thread's effort when absent.
    pub reasoning_effort: Option<String>,
    /// Deadline for one worker turn.
    #[serde(default = "default_worker_deadline_secs")]
    pub deadline_secs: u64,
}

impl Default for WorkerSettings {
    fn default() -> Self {
        Self {
            model: None,
            reasoning_effort: None,
            deadline_secs: default_worker_deadline_secs(),
        }
    }
}

fn default_repair_attempts() -> u32 {
    1
}

fn default_worker_deadline_secs() -> u64 {
    900
}

#[derive(Debug, thiserror::Error)]
pub enum SettingsError {
    #[error("failed to read {path}: {source}")]
    Read {
        path: PathBuf,
        source: std::io::Error,
    },
    #[error("invalid {path}: {source}")]
    Parse {
        path: PathBuf,
        source: serde_json::Error,
    },
}

impl Settings {
    /// Loads `CODEX_HOME/pro_contract/settings.json`; a missing file means no settings.
    pub fn load(codex_home: &Path) -> Result<Option<Settings>, SettingsError> {
        let path = codex_home.join("pro_contract").join(SETTINGS_FILE);
        let text = match std::fs::read_to_string(&path) {
            Ok(text) => text,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(source) => return Err(SettingsError::Read { path, source }),
        };
        serde_json::from_str(&text)
            .map(Some)
            .map_err(|source| SettingsError::Parse { path, source })
    }
}

#[cfg(test)]
#[path = "settings_tests.rs"]
mod tests;
