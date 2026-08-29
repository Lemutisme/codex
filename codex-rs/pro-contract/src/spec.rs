use crate::ArtifactPath;
use crate::ArtifactSpec;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Trigger {
    Immediate,
    Time { at: u64 },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Budget {
    pub turns: u64,
    pub actions: u64,
    pub deadline: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplayCheck {
    pub argv: Vec<String>,
    pub cwd: Option<ArtifactPath>,
    pub timeout_ms: u64,
    pub exit: i32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProtectedFile {
    pub path: ArtifactPath,
    pub sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplayPolicy {
    pub checks: Vec<ReplayCheck>,
    pub protected: Vec<ProtectedFile>,
    pub artifacts: ArtifactSpec,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub claim: String,
    pub replay: Option<ReplayPolicy>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Resolution {
    pub max_attempts: u64,
    pub retry_delay_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Requirement {
    pub contract_id: String,
    pub revision: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ContractSpec {
    pub trigger: Trigger,
    pub goal: String,
    pub brief: String,
    pub artifacts: ArtifactSpec,
    pub requires: Vec<Requirement>,
    pub authority: Vec<String>,
    pub budget: Budget,
    pub evidence: Evidence,
    pub resolution: Resolution,
}
