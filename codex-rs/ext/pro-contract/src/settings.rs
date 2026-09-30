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
    #[serde(default)]
    pub worker: WorkerSettings,
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
