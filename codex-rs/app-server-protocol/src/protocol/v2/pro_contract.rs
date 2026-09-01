use crate::JsonSchema;
use crate::TS;
use codex_utils_path_uri::LegacyAppPathString;
use serde::Deserialize;
use serde::Serialize;

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type", export_to = "v2/")]
pub enum ProContractTrigger {
    Immediate,
    Time { trigger_at: i64 },
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractRequirement {
    pub contract_id: String,
    pub revision: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractBudget {
    pub turns: u64,
    pub actions: u64,
    /// Absolute Unix time in seconds.
    pub deadline_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReplayCheck {
    pub argv: Vec<String>,
    pub cwd: Option<String>,
    pub timeout_ms: u64,
    pub exit: i32,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractProtectedFile {
    pub path: String,
    pub sha256: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReplayPolicy {
    pub checks: Vec<ProContractReplayCheck>,
    pub protected: Vec<ProContractProtectedFile>,
    pub artifacts: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractEvidence {
    pub claim: String,
    pub replay: Option<ProContractReplayPolicy>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractResolution {
    pub max_attempts: u64,
    pub retry_delay_ms: u64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractSpec {
    pub trigger: ProContractTrigger,
    pub goal: String,
    pub brief: String,
    pub artifacts: Vec<String>,
    pub requires: Vec<ProContractRequirement>,
    pub authority: Vec<String>,
    pub budget: ProContractBudget,
    pub evidence: ProContractEvidence,
    pub resolution: ProContractResolution,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ProContractStatus {
    Dormant,
    Active,
    Verification,
    Escalated,
    Discharged,
    Released,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractSubject {
    pub hash: String,
    pub spec_hash: String,
    pub artifacts: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReplayResult {
    pub policy_hash: String,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub passed: bool,
    pub summary: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractHandoff {
    pub summary: String,
    pub uncertainties: Vec<String>,
    pub subject: ProContractSubject,
    pub replay: Option<ProContractReplayResult>,
    pub created_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ProContractChallengeDisclosure {
    Executor,
    Sealed,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractChallenge {
    pub revision: u64,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub disclosure: ProContractChallengeDisclosure,
    pub summary: Option<String>,
    pub created_at: i64,
    pub attestation_id: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractBlocked {
    pub reason: String,
    pub reported_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractEscalation {
    pub reason: String,
    pub created_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractPendingRevision {
    pub spec: ProContractSpec,
    pub spec_hash: String,
    pub reason: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractInfo {
    pub id: String,
    pub scope: String,
    pub spec: ProContractSpec,
    pub issuer: String,
    pub executor: String,
    pub spec_hash: String,
    pub revision: u64,
    pub status: ProContractStatus,
    pub blocked: Option<ProContractBlocked>,
    pub handoff: Option<ProContractHandoff>,
    pub challenge: Option<ProContractChallenge>,
    pub pending_revision: Option<ProContractPendingRevision>,
    pub attestation_id: Option<String>,
    pub escalation: Option<ProContractEscalation>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractExecutionInfo {
    pub contract_id: String,
    pub revision: u64,
    pub executor_thread_id: Option<String>,
    pub execution_policy: Option<String>,
    pub execution_policy_hash: Option<String>,
    pub dispatched: bool,
    pub awaiting_revision_decision: bool,
    pub attempts: u64,
    pub turns_used: u64,
    pub actions_used: u64,
    /// Absolute Unix time in seconds, or zero when immediately runnable.
    pub next_action_at: i64,
    pub turns_limit: u64,
    pub actions_limit: u64,
    /// Absolute Unix time in seconds.
    pub deadline_at: i64,
    pub max_attempts: u64,
    pub lease_owner: Option<String>,
    /// Absolute Unix time in seconds, or zero when no lease is held.
    pub lease_expires_at: i64,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractQuiet {
    pub scope: String,
    pub quiet: bool,
    pub frontier: u64,
    pub ledger_hash: String,
    pub state_hash: String,
    pub outstanding: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractIssueParams {
    pub thread_id: String,
    pub spec: ProContractSpec,
    #[ts(optional = nullable)]
    pub execution_policy: Option<String>,
    #[ts(optional = nullable)]
    pub original_request: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractIssueResponse {
    pub contract: ProContractInfo,
    pub execution: ProContractExecutionInfo,
    pub compiler_manifest_hash: String,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReadParams {
    pub thread_id: String,
    pub contract_id: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReadResponse {
    pub contract: ProContractInfo,
    pub execution: Option<ProContractExecutionInfo>,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractQuietParams {
    pub thread_id: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractQuietResponse {
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractHandoffMaterializeParams {
    pub thread_id: String,
    pub contract_id: String,
    pub destination: LegacyAppPathString,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractHandoffMaterializeResponse {
    pub subject: ProContractSubject,
    pub destination: LegacyAppPathString,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractAttestParams {
    pub thread_id: String,
    pub contract_id: String,
    pub revision: u64,
    pub spec_hash: String,
    pub subject_hash: String,
    pub evidence_hash: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractChallengeParams {
    pub thread_id: String,
    pub contract_id: String,
    pub revision: u64,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub disclosure: ProContractChallengeDisclosure,
    #[ts(optional = nullable)]
    pub summary: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ProContractRevisionDecision {
    Accept,
    Reject,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractRevisionDecideParams {
    pub thread_id: String,
    pub contract_id: String,
    pub revision: u64,
    pub spec_hash: String,
    pub decision: ProContractRevisionDecision,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractResumeParams {
    pub thread_id: String,
    pub contract_id: String,
    pub revision: u64,
    pub spec_hash: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReleaseParams {
    pub thread_id: String,
    pub contract_id: String,
    pub revision: u64,
    pub spec_hash: String,
    pub reason: String,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractAttestResponse {
    pub contract: ProContractInfo,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractChallengeResponse {
    pub contract: ProContractInfo,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractRevisionDecideResponse {
    pub contract: ProContractInfo,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractResumeResponse {
    pub contract: ProContractInfo,
    pub quiet: ProContractQuiet,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ProContractReleaseResponse {
    pub contract: ProContractInfo,
    pub quiet: ProContractQuiet,
}
