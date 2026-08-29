use crate::Runtime;
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
use codex_pro_contract::Command;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Decision;
use codex_pro_contract::Draft;
use codex_pro_contract::INSTITUTION_ACTOR;
use codex_pro_contract::Status;
use codex_pro_contract::hash_spec;
use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use serde::Deserialize;
use serde_json::json;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

pub(crate) const PROPOSE_TOOL_NAME: &str = "contract_propose";
pub(crate) const STATUS_TOOL_NAME: &str = "contract_status";
pub(crate) const REPORT_READY_TOOL_NAME: &str = "contract_report_ready";

#[derive(Clone, Copy)]
pub(crate) enum ToolKind {
    Propose,
    Status,
    ReportReady,
}

impl ToolKind {
    pub(crate) const ALL: [Self; 3] = [Self::Propose, Self::Status, Self::ReportReady];
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

impl ToolExecutor<ToolCall> for ContractTool {
    fn tool_name(&self) -> ToolName {
        ToolName::plain(match self.kind {
            ToolKind::Propose => PROPOSE_TOOL_NAME,
            ToolKind::Status => STATUS_TOOL_NAME,
            ToolKind::ReportReady => REPORT_READY_TOOL_NAME,
        })
    }

    fn spec(&self) -> ToolSpec {
        match self.kind {
            ToolKind::Propose => propose_spec(),
            ToolKind::Status => status_spec(),
            ToolKind::ReportReady => report_ready_spec(),
        }
    }

    fn handle(&self, invocation: ToolCall) -> codex_extension_api::ToolExecutorFuture<'_> {
        Box::pin(async move {
            match self.kind {
                ToolKind::Propose => self.propose(invocation).await,
                ToolKind::Status => self.status(invocation).await,
                ToolKind::ReportReady => self.report_ready(invocation).await,
            }
        })
    }
}

#[derive(Deserialize)]
struct ProposeArgs {
    claim: String,
    artifacts: Vec<String>,
    execution_policy: Option<String>,
}

#[derive(Deserialize)]
struct ReportReadyArgs {
    summary: String,
    #[serde(default)]
    uncertainties: Vec<String>,
    environment_id: Option<String>,
}

impl ContractTool {
    async fn propose(
        &self,
        invocation: ToolCall,
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
        let spec = ContractSpec {
            claim: claim.to_string(),
            artifacts: ArtifactSpec::new(paths)
                .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?,
            requires: Vec::new(),
        };
        let spec_hash = hash_spec(&spec).map_err(internal_error)?;
        let binding = self
            .runtime
            .bindings
            .bind_once(
                &self.runtime.scope,
                &self.runtime.contract_id,
                1,
                args.execution_policy,
            )
            .await
            .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.scope,
                Command::Issue {
                    actor: self.runtime.issuer.clone(),
                    draft: Draft {
                        id: self.runtime.contract_id.clone(),
                        scope: self.runtime.scope.clone(),
                        spec_hash,
                        spec,
                        issuer: self.runtime.issuer.clone(),
                        executor: self.runtime.executor.clone(),
                    },
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)?;
        let contract = &transition.state.contracts[&self.runtime.contract_id];
        let transition = if contract.status == Status::Dormant {
            self.runtime
                .ledger
                .apply(
                    &self.runtime.scope,
                    Command::Activate {
                        actor: INSTITUTION_ACTOR.to_string(),
                        contract_id: self.runtime.contract_id.clone(),
                        revision: contract.revision,
                    },
                )
                .await
                .map_err(internal_error)?
        } else {
            transition
        };
        require_accepted(&transition.decision)?;
        json_output(json!({
            "contract": transition.state.contracts[&self.runtime.contract_id],
            "executionBinding": binding,
            "quiet": false,
        }))
    }

    async fn status(&self, invocation: ToolCall) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let _: serde_json::Value = parse_args(&invocation)?;
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.scope)
            .await
            .map_err(internal_error)?;
        let binding = self
            .runtime
            .bindings
            .get(&self.runtime.scope)
            .await
            .map_err(internal_error)?;
        json_output(json!({
            "contract": state.contracts.get(&self.runtime.contract_id),
            "executionBinding": binding,
            "quiet": codex_pro_contract::quiet(&state, &self.runtime.scope),
        }))
    }

    async fn report_ready(
        &self,
        invocation: ToolCall,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ReportReadyArgs = parse_args(&invocation)?;
        let state = self
            .runtime
            .ledger
            .state(&self.runtime.scope)
            .await
            .map_err(internal_error)?;
        let contract = state
            .contracts
            .get(&self.runtime.contract_id)
            .ok_or_else(|| FunctionCallError::RespondToModel("contract not found".to_string()))?;
        let environment = select_environment(&invocation, args.environment_id.as_deref())?;
        if environment.environment_id != LOCAL_ENVIRONMENT_ID {
            return model_error(
                "contract subject capture currently requires the local execution environment",
            );
        }
        let subjects = self.runtime.subjects.clone();
        let workspace = PathBuf::from(environment.cwd.as_path());
        let spec_hash = contract.spec_hash.clone();
        let artifacts = contract.spec.artifacts.clone();
        let captured = tokio::task::spawn_blocking(move || {
            subjects.capture(&workspace, spec_hash, &artifacts)
        })
        .await
        .map_err(|error| FunctionCallError::Fatal(error.to_string()))?
        .map_err(|error| FunctionCallError::RespondToModel(error.to_string()))?;
        let transition = self
            .runtime
            .ledger
            .apply(
                &self.runtime.scope,
                Command::ReportReady {
                    actor: INSTITUTION_ACTOR.to_string(),
                    contract_id: contract.id.clone(),
                    revision: contract.revision,
                    summary: args.summary,
                    uncertainties: args.uncertainties,
                    subject: captured.coordinate.clone(),
                },
            )
            .await
            .map_err(internal_error)?;
        require_accepted(&transition.decision)?;
        json_output(json!({
            "contract": transition.state.contracts[&self.runtime.contract_id],
            "subject": captured,
            "quiet": false,
        }))
    }
}

fn select_environment<'a>(
    invocation: &'a ToolCall,
    environment_id: Option<&str>,
) -> Result<&'a codex_extension_api::ToolEnvironment, FunctionCallError> {
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

fn parse_args<T: for<'de> Deserialize<'de>>(invocation: &ToolCall) -> Result<T, FunctionCallError> {
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

fn propose_spec() -> ToolSpec {
    let properties = BTreeMap::from([
        ("claim".to_string(), JsonSchema::string(None)),
        (
            "artifacts".to_string(),
            JsonSchema::array(
                JsonSchema::string(None),
                Some("Complete relative delivery paths to freeze at handoff.".to_string()),
            ),
        ),
        (
            "execution_policy".to_string(),
            JsonSchema::string(Some(
                "Optional executor guidance selected outside the Contract. It does not alter Contract identity, revision, evidence, or settlement. Do not invent it."
                    .to_string(),
            )),
        ),
    ]);
    function_tool(
        PROPOSE_TOOL_NAME,
        "Propose one durable completion contract and optionally bind externally selected execution guidance. The binding is separate from Contract terms and cannot settle responsibility.",
        properties,
        vec!["claim", "artifacts"],
    )
}

fn status_spec() -> ToolSpec {
    function_tool(
        STATUS_TOOL_NAME,
        "Read the current durable contract and quiet status.",
        BTreeMap::new(),
        Vec::new(),
    )
}

fn report_ready_spec() -> ToolSpec {
    let properties = BTreeMap::from([
        ("summary".to_string(), JsonSchema::string(None)),
        (
            "uncertainties".to_string(),
            JsonSchema::array(JsonSchema::string(None), None),
        ),
        (
            "environment_id".to_string(),
            JsonSchema::string(Some(
                "Required only when more than one execution environment is active.".to_string(),
            )),
        ),
    ]);
    function_tool(
        REPORT_READY_TOOL_NAME,
        "Freeze the declared artifacts and petition for independent verification. This never discharges the contract.",
        properties,
        vec!["summary"],
    )
}

fn function_tool(
    name: &str,
    description: &str,
    properties: BTreeMap<String, JsonSchema>,
    required: Vec<&str>,
) -> ToolSpec {
    ToolSpec::Function(ResponsesApiTool {
        name: name.to_string(),
        description: description.to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(required.into_iter().map(str::to_string).collect()),
            Some(false.into()),
        ),
        output_schema: None,
    })
}
