use crate::ProContractProposalMode;
use crate::Runtime;
use crate::RuntimeRole;
use crate::binding::AttemptSchedule;
use crate::compiler::compile_spec;
use crate::compiler::latest_user_request;
use crate::now_millis;
use crate::replay::ReplayVerifier;
use crate::runner;
use crate::tool_spec::propose_revision_spec;
use crate::tool_spec::propose_spec;
use crate::tool_spec::report_blocked_spec;
use crate::tool_spec::report_ready_spec;
use crate::tool_spec::status_spec;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_extension_api::FunctionCallError;
use codex_extension_api::JsonToolOutput;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolExecutor;
use codex_extension_api::ToolName;
use codex_extension_api::ToolOutput;
use codex_extension_api::ToolSpec;
use codex_pro_contract::ArtifactPath;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::Command;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Decision;
use codex_pro_contract::Evidence;
use codex_pro_contract::INSTITUTION_ACTOR;
use codex_pro_contract::ProtectedFile;
use codex_pro_contract::ReplayCheck;
use codex_pro_contract::ReplayPolicy;
use codex_pro_contract::Requirement;
use codex_pro_contract::Resolution;
use codex_pro_contract::Status;
use codex_pro_contract::Trigger;
use serde::Deserialize;
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;

pub(crate) const PROPOSE_TOOL_NAME: &str = "contract_propose";
pub(crate) const STATUS_TOOL_NAME: &str = "contract_status";
pub(crate) const REPORT_READY_TOOL_NAME: &str = "contract_report_ready";
pub(crate) const REPORT_BLOCKED_TOOL_NAME: &str = "contract_report_blocked";
pub(crate) const PROPOSE_REVISION_TOOL_NAME: &str = "contract_propose_revision";

#[derive(Clone, Copy)]
pub(crate) enum ToolKind {
    Propose,
    Status,
    ReportReady,
    ReportBlocked,
    ProposeRevision,
}

impl ToolKind {
    pub(crate) fn for_runtime(
        role: RuntimeRole,
        proposal_mode: ProContractProposalMode,
    ) -> &'static [Self] {
        match (role, proposal_mode) {
            (RuntimeRole::Principal, ProContractProposalMode::PrincipalOnly) => &[],
            (RuntimeRole::Principal, ProContractProposalMode::HostApprovedModelTool) => {
                &[Self::Propose, Self::Status]
            }
            (RuntimeRole::Executor, _) => &[
                Self::Status,
                Self::ReportReady,
                Self::ReportBlocked,
                Self::ProposeRevision,
            ],
        }
    }
}

#[derive(Clone)]
pub(crate) struct ContractTool {
    kind: ToolKind,
    runtime: Arc<Runtime>,
}

impl ContractTool {
    pub(crate) fn new(kind: ToolKind, runtime: Arc<Runtime>) -> Self {
        Self { kind, runtime }
    }
}

impl<'call> ToolExecutor<ToolCall<'call>> for ContractTool {
    fn tool_name(&self) -> ToolName {
        ToolName::plain(match self.kind {
            ToolKind::Propose => PROPOSE_TOOL_NAME,
            ToolKind::Status => STATUS_TOOL_NAME,
            ToolKind::ReportReady => REPORT_READY_TOOL_NAME,
            ToolKind::ReportBlocked => REPORT_BLOCKED_TOOL_NAME,
            ToolKind::ProposeRevision => PROPOSE_REVISION_TOOL_NAME,
        })
    }

    fn spec(&self) -> ToolSpec {
        match self.kind {
            ToolKind::Propose => propose_spec(),
            ToolKind::Status => status_spec(),
            ToolKind::ReportReady => report_ready_spec(),
            ToolKind::ReportBlocked => report_blocked_spec(),
            ToolKind::ProposeRevision => propose_revision_spec(),
        }
    }

    fn handle<'a>(
        &'a self,
        invocation: ToolCall<'call>,
    ) -> codex_extension_api::ToolExecutorFuture<'a>
    where
        'call: 'a,
    {
        Box::pin(async move {
            match self.kind {
                ToolKind::Propose => self.propose(invocation).await,
                ToolKind::Status => self.status(invocation).await,
                ToolKind::ReportReady => self.report_ready(invocation).await,
                ToolKind::ReportBlocked => self.report_blocked(invocation).await,
                ToolKind::ProposeRevision => self.propose_revision(invocation).await,
            }
        })
    }
}

#[derive(Deserialize)]
struct ProposeArgs {
    trigger: Option<Trigger>,
    goal: Option<String>,
    claim: String,
    brief: Option<String>,
    artifacts: Vec<String>,
    execution_policy: Option<String>,
    replay: Option<ReplayArgs>,
    #[serde(default)]
    completion: ProposalCompletion,
    budget: Option<BudgetArgs>,
    resolution: Option<ResolutionArgs>,
    authority: Option<Vec<String>>,
    requires: Option<Vec<Requirement>>,
}

#[derive(Deserialize)]
struct BudgetArgs {
    turns: u64,
    actions: u64,
    deadline: u64,
}

#[derive(Deserialize)]
struct ResolutionArgs {
    max_attempts: u64,
    retry_delay_ms: u64,
}

#[derive(Clone, Copy, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ProposalCompletion {
    #[default]
    Admission,
    Terminal,
}

#[derive(Deserialize)]
struct ReplayArgs {
    checks: Vec<ReplayCheckArgs>,
    #[serde(default)]
    protected: Vec<ProtectedFileArgs>,
}

#[derive(Deserialize)]
struct ReplayCheckArgs {
    argv: Vec<String>,
    cwd: Option<String>,
    timeout_ms: u64,
    exit: i32,
}

#[derive(Deserialize)]
struct ProtectedFileArgs {
    path: String,
    sha256: String,
}

#[derive(Deserialize)]
struct ReportReadyArgs {
    summary: String,
    #[serde(default)]
    uncertainties: Vec<String>,
    environment_id: Option<String>,
}

#[derive(Deserialize)]
struct StatusArgs {
    contract_id: Option<String>,
}

#[derive(Deserialize)]
struct ReportBlockedArgs {
    reason: String,
}

#[derive(Deserialize)]
struct ProposeRevisionArgs {
    reason: String,
    goal: Option<String>,
    brief: Option<String>,
    artifacts: Option<Vec<String>>,
    replay: Option<ReplayArgs>,
}

impl ContractTool {
    async fn propose(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ProposeArgs = parse_args(&invocation)?;
        let claim = args.claim.trim();
        if claim.is_empty() {
            return model_error("contract claim must be non-empty");
        }
        let paths = args
            .artifacts
            .into_iter()
            .map(ArtifactPath::new)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        let artifacts = ArtifactSpec::new(paths)
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        let replay = args
            .replay
            .map(|replay| replay_policy(replay, artifacts.clone()))
            .transpose()?;
        let goal = args.goal.unwrap_or_else(|| claim.to_string());
        if goal.trim().is_empty() {
            return model_error("contract goal must be non-empty");
        }
        let budget = args.budget.map_or_else(
            || Budget {
                turns: 1_000,
                actions: 4_000,
                deadline: now_millis().saturating_add(6 * 60 * 60 * 1_000),
            },
            |budget| Budget {
                turns: budget.turns,
                actions: budget.actions,
                deadline: budget.deadline,
            },
        );
        let resolution = args.resolution.map_or(
            Resolution {
                max_attempts: 3,
                retry_delay_ms: 0,
            },
            |resolution| Resolution {
                max_attempts: resolution.max_attempts,
                retry_delay_ms: resolution.retry_delay_ms,
            },
        );
        let spec = ContractSpec {
            trigger: args.trigger.unwrap_or(Trigger::Immediate),
            goal,
            brief: args.brief.unwrap_or_default(),
            artifacts,
            requires: args.requires.unwrap_or_default(),
            authority: args.authority.unwrap_or_else(|| {
                vec![
                    "filesystem.read".to_string(),
                    "filesystem.write".to_string(),
                    "process.execute".to_string(),
                ]
            }),
            budget,
            evidence: Evidence {
                claim: claim.to_string(),
                replay,
            },
            resolution,
        };
        let request = latest_user_request(invocation.conversation_history.items());
        let compiled = compile_spec(spec, request.as_deref())
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        let compiler_manifest_hash = compiled.manifest_hash;
        let launched = runner::launch(&self.runtime, compiled.spec, args.execution_policy)
            .await
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        if launched.executor_thread_id.is_none() {
            crate::start_recovery_if_needed(&self.runtime).await;
        }
        let contract_id = launched.binding.contract_id.clone();
        let executor_thread_id = launched.executor_thread_id;
        let (state, binding) = match args.completion {
            ProposalCompletion::Admission => (launched.transition.state, launched.binding),
            ProposalCompletion::Terminal => loop {
                let state = self
                    .runtime
                    .ledger
                    .state(&self.runtime.ledger_scope)
                    .await
                    .map_err(internal_error)?;
                let contract = state.contracts.get(&contract_id).ok_or_else(|| {
                    FunctionCallError::Fatal("contract disappeared while waiting".to_string())
                })?;
                if matches!(
                    contract.status,
                    Status::Verification
                        | Status::Escalated
                        | Status::Discharged
                        | Status::Released
                ) {
                    let binding = self
                        .runtime
                        .bindings
                        .get_by_contract(&contract_id)
                        .await
                        .map_err(internal_error)?
                        .ok_or_else(|| {
                            FunctionCallError::Fatal(
                                "execution binding disappeared while waiting".to_string(),
                            )
                        })?;
                    break (state, binding);
                }
                if now_millis() >= contract.spec.budget.deadline {
                    let transition = self
                        .runtime
                        .ledger
                        .apply(
                            &self.runtime.ledger_scope,
                            Command::Escalate {
                                actor: INSTITUTION_ACTOR.to_string(),
                                contract_id: contract.id.clone(),
                                revision: contract.revision,
                                reason: "contract deadline exhausted while awaiting terminal state"
                                    .to_string(),
                                time: now_millis(),
                            },
                        )
                        .await
                        .map_err(internal_error)?;
                    require_accepted(&transition.decision)?;
                    continue;
                }
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            },
        };
        json_output(json!({
            "contract": state.contracts[&contract_id],
            "executionBinding": binding,
            "executorThreadId": executor_thread_id,
            "compilerManifestHash": compiler_manifest_hash,
            "quiet": false,
        }))
    }

    async fn status(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: StatusArgs = parse_args(&invocation)?;
        let contract_id = args
            .contract_id
            .as_deref()
            .unwrap_or(&self.runtime.contract_id);
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.ledger_scope)
            .await
            .map_err(internal_error)?;
        let binding = self
            .runtime
            .bindings
            .get_by_contract(contract_id)
            .await
            .map_err(internal_error)?;
        let quiet = self
            .runtime
            .ledger
            .quiet(&self.runtime.ledger_scope)
            .await
            .map_err(internal_error)?;
        json_output(json!({
            "contract": state.contracts.get(contract_id),
            "executionBinding": binding,
            "quiet": quiet.quiet,
            "quietSnapshot": quiet,
        }))
    }

    async fn report_ready(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ReportReadyArgs = parse_args(&invocation)?;
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.ledger_scope)
            .await
            .map_err(internal_error)?;
        let contract = state
            .contracts
            .get(&self.runtime.contract_id)
            .ok_or_else(|| FunctionCallError::RespondToModel("contract not found".to_string()))?;
        let environment = select_environment(&invocation, args.environment_id.as_deref())?;
        if environment.environment_id != LOCAL_ENVIRONMENT_ID {
            let message = "contract subject capture requires the local execution environment";
            self.escalate_contract(contract, message).await?;
            return model_error(message);
        }
        let subjects = self.runtime.subjects.clone();
        let workspace = PathBuf::from(environment.cwd.as_path());
        let spec_hash = contract.spec_hash.clone();
        let artifacts = contract.spec.artifacts.clone();
        let replay_policy = contract.spec.evidence.replay.clone();
        let captured = match tokio::task::spawn_blocking(move || {
            subjects.capture(&workspace, spec_hash, &artifacts)
        })
        .await
        {
            Ok(Ok(captured)) => captured,
            Ok(Err(error)) => {
                let message = format!("contract handoff capture unavailable: {error}");
                self.escalate_contract(contract, &message).await?;
                return model_error(&message);
            }
            Err(error) => {
                let message = format!("contract handoff capture failed: {error}");
                self.escalate_contract(contract, &message).await?;
                return model_error(&message);
            }
        };
        let replay = match replay_policy {
            Some(policy) => {
                let verifier = ReplayVerifier::new(
                    self.runtime.subjects.clone(),
                    Arc::clone(&self.runtime.environment_manager),
                    self.runtime.replay_reports.clone(),
                );
                match verifier
                    .verify(
                        &contract.id,
                        &policy,
                        &captured,
                        &environment.environment_id,
                        &environment.file_system_sandbox_context,
                    )
                    .await
                {
                    Ok(replay) => Some(replay),
                    Err(error) => {
                        let message = format!(
                            "independent replay unavailable for {}: {error}",
                            captured.coordinate.hash
                        );
                        self.escalate_contract(contract, &message).await?;
                        return model_error(&message);
                    }
                }
            }
            None => None,
        };
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.ledger_scope,
                Command::ReportReady {
                    actor: INSTITUTION_ACTOR.to_string(),
                    contract_id: contract.id.clone(),
                    revision: contract.revision,
                    summary: args.summary,
                    uncertainties: args.uncertainties,
                    subject: captured.coordinate.clone(),
                    replay: replay.clone(),
                    time: now_millis(),
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)?;
        let schedule =
            if transition.state.contracts[&self.runtime.contract_id].status == Status::Dormant {
                AttemptSchedule::At(
                    now_millis().saturating_add(contract.spec.resolution.retry_delay_ms),
                )
            } else {
                AttemptSchedule::Immediate
            };
        self.runtime
            .bindings
            .suspend_attempt(&self.runtime.thread_scope, schedule)
            .await
            .map_err(internal_error)?;
        json_output(json!({
            "contract": transition.state.contracts[&self.runtime.contract_id],
            "subject": captured,
            "replay": replay,
            "quiet": false,
        }))
    }

    async fn report_blocked(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ReportBlockedArgs = parse_args(&invocation)?;
        if args.reason.trim().is_empty() {
            return model_error("blocked reason must be non-empty");
        }
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.ledger_scope)
            .await
            .map_err(internal_error)?;
        let contract = state
            .contracts
            .get(&self.runtime.contract_id)
            .ok_or_else(|| FunctionCallError::RespondToModel("contract not found".to_string()))?;
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.ledger_scope,
                Command::ReportBlocked {
                    actor: INSTITUTION_ACTOR.to_string(),
                    contract_id: contract.id.clone(),
                    revision: contract.revision,
                    reason: args.reason,
                    time: now_millis(),
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)?;
        self.runtime
            .bindings
            .suspend_attempt(
                &self.runtime.thread_scope,
                AttemptSchedule::At(
                    now_millis().saturating_add(contract.spec.resolution.retry_delay_ms),
                ),
            )
            .await
            .map_err(internal_error)?;
        json_output(json!({
            "contract": transition.state.contracts[&self.runtime.contract_id],
            "quiet": false,
        }))
    }

    async fn propose_revision(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ProposeRevisionArgs = parse_args(&invocation)?;
        if args.reason.trim().is_empty() {
            return model_error("revision reason must be non-empty");
        }
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.ledger_scope)
            .await
            .map_err(internal_error)?;
        let contract = state
            .contracts
            .get(&self.runtime.contract_id)
            .ok_or_else(|| FunctionCallError::RespondToModel("contract not found".to_string()))?;
        let mut spec = contract.spec.clone();
        if let Some(goal) = args.goal {
            if goal.trim().is_empty() {
                return model_error("revision goal must be non-empty");
            }
            spec.goal = goal;
        }
        if let Some(brief) = args.brief {
            spec.brief = brief;
        }
        if let Some(paths) = args.artifacts {
            spec.artifacts = ArtifactSpec::new(
                paths
                    .into_iter()
                    .map(ArtifactPath::new)
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?,
            )
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        }
        if let Some(replay) = args.replay {
            spec.evidence.replay = Some(replay_policy(replay, spec.artifacts.clone())?);
        }
        let spec_hash = codex_pro_contract::hash_spec(&spec).map_err(internal_error)?;
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.ledger_scope,
                Command::PetitionRevision {
                    actor: contract.executor.clone(),
                    contract_id: contract.id.clone(),
                    spec,
                    spec_hash,
                    reason: args.reason,
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)?;
        self.runtime
            .bindings
            .suspend_attempt(&self.runtime.thread_scope, AttemptSchedule::AwaitRevision)
            .await
            .map_err(internal_error)?;
        json_output(json!({
            "contract": transition.state.contracts[&self.runtime.contract_id],
            "quiet": false,
        }))
    }

    async fn escalate_contract(
        &self,
        contract: &codex_pro_contract::Contract,
        reason: &str,
    ) -> Result<(), FunctionCallError> {
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.ledger_scope,
                Command::Escalate {
                    actor: INSTITUTION_ACTOR.to_string(),
                    contract_id: contract.id.clone(),
                    revision: contract.revision,
                    reason: reason.to_string(),
                    time: now_millis(),
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)
    }
}

fn replay_policy(
    replay: ReplayArgs,
    artifacts: ArtifactSpec,
) -> Result<ReplayPolicy, FunctionCallError> {
    let checks = replay
        .checks
        .into_iter()
        .map(|check| {
            Ok(ReplayCheck {
                argv: check.argv,
                cwd: check
                    .cwd
                    .filter(|cwd| cwd != ".")
                    .map(ArtifactPath::new)
                    .transpose()
                    .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?,
                timeout_ms: check.timeout_ms,
                exit: check.exit,
            })
        })
        .collect::<Result<Vec<_>, FunctionCallError>>()?;
    let protected = replay
        .protected
        .into_iter()
        .map(|file| {
            Ok(ProtectedFile {
                path: ArtifactPath::new(file.path)
                    .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?,
                sha256: file.sha256,
            })
        })
        .collect::<Result<Vec<_>, FunctionCallError>>()?;
    Ok(ReplayPolicy {
        checks,
        protected,
        artifacts,
    })
}

fn select_environment<'a, 'call>(
    invocation: &'a ToolCall<'call>,
    environment_id: Option<&str>,
) -> Result<&'a codex_extension_api::ToolEnvironment<'call>, FunctionCallError> {
    if let Some(environment_id) = environment_id {
        return invocation
            .environments
            .iter()
            .find(|environment| environment.environment_id == environment_id)
            .ok_or_else(|| {
                FunctionCallError::RespondToModel(format!(
                    "unknown environment_id: {environment_id}"
                ))
            });
    }
    if invocation.environments.len() == 1 {
        return Ok(&invocation.environments[0]);
    }
    model_error("environment_id is required when the turn has multiple environments")
}

fn parse_args<T: for<'de> Deserialize<'de>>(
    invocation: &ToolCall<'_>,
) -> Result<T, FunctionCallError> {
    serde_json::from_str(invocation.function_arguments()?)
        .map_err(|error| FunctionCallError::RespondToModel(format!("invalid arguments: {error}")))
}

fn require_accepted(decision: &Decision) -> Result<(), FunctionCallError> {
    match decision {
        Decision::Accepted => Ok(()),
        Decision::Rejected { reason } => Err(FunctionCallError::RespondToModel(reason.clone())),
    }
}

fn internal_error(error: impl std::fmt::Display) -> FunctionCallError {
    FunctionCallError::Fatal(error.to_string())
}

fn model_error<T>(message: &str) -> Result<T, FunctionCallError> {
    Err(FunctionCallError::RespondToModel(message.to_string()))
}

fn json_output(value: serde_json::Value) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    Ok(Box::new(JsonToolOutput::new(value)))
}
