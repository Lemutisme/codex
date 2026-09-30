//! Runs one strict-JSON turn on a hidden, isolated, tool-less worker thread.
//!
//! The worker starts from fresh history with an empty extension registry
//! (`SessionIsolation::Isolated`), no environment and no tools, so it can only read what the
//! prompt gives it. It is registered as an internal extension worker, invisible to clients.

use std::collections::HashMap;
use std::time::Duration;

use codex_core::NewThread;
use codex_core::StartIfIdleSubmission;
use codex_core::StartThreadOptions;
use codex_core::ThreadManager;
use codex_core::TurnInputRequest;
use codex_core::TurnStartOptions;
use codex_core::config::Config;
use codex_core::config::Constrained;
use codex_extension_api::SessionIsolation;
use codex_extension_api::ToolPolicy;
use codex_features::Feature;
use codex_protocol::models::BaseInstructionsProvenance;
use codex_protocol::openai_models::ReasoningEffort;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::InternalSessionSource;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadSource;
use codex_protocol::user_input::UserInput;
use serde_json::Value;

use super::WorkerError;
use crate::WorkerSettings;

const WORKER_BASE_INSTRUCTIONS: &str = "You are a careful, independent evaluator working for an \
automatic Principal. You have no tools. Follow the instructions in the user message exactly, judge only \
the evidence it contains, and answer with a single JSON object that matches the required schema.";

/// How long to wait for a worker to shut down after its turn.
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

/// One worker turn.
pub(crate) struct WorkerTurn {
    pub prompt: String,
    pub schema: Value,
    pub trigger: &'static str,
    pub deadline: Duration,
}

/// Derives a worker configuration from the parent thread's configuration.
pub(crate) fn worker_config(
    parent: &Config,
    settings: &WorkerSettings,
) -> Result<Config, WorkerError> {
    let start = |message: String| WorkerError::Start(message);
    let mut config = parent.clone();
    if let Some(model) = &settings.model {
        config.model = Some(model.clone());
    }
    if let Some(effort) = &settings.reasoning_effort {
        let effort: ReasoningEffort = serde_json::from_value(Value::String(effort.clone()))
            .map_err(|error| start(format!("invalid worker reasoning effort: {error}")))?;
        config.model_reasoning_effort = Some(effort);
    }
    config.base_instructions = Some(WORKER_BASE_INSTRUCTIONS.to_string());
    config.base_instructions_provenance = Some(BaseInstructionsProvenance::Custom);
    config.developer_instructions = None;
    config.model_post_turn_compact_threshold_percent = 0;
    config.include_skill_instructions = false;
    config.include_apps_instructions = false;
    config.memories.use_memories = false;
    config.memories.dedicated_tools = false;
    config.notify = None;
    config.permissions.approval_policy = Constrained::allow_only(AskForApproval::Never);
    if let Some(read_only) = config
        .permissions
        .permission_profile()
        .intersect_with_read_only()
    {
        config
            .permissions
            .set_permission_profile(read_only)
            .map_err(|error| start(format!("cannot restrict worker permissions: {error}")))?;
    }
    config
        .mcp_servers
        .set(HashMap::new())
        .map_err(|error| start(format!("cannot clear worker MCP servers: {error}")))?;
    for feature in [
        Feature::Collab,
        Feature::MultiAgentV2,
        Feature::GuardianV2,
        Feature::TokenBudget,
        Feature::ContextManagement,
        Feature::CodexHooks,
        Feature::Apps,
        Feature::Plugins,
        Feature::WebSearchRequest,
        Feature::WebSearchCached,
        Feature::Goals,
        Feature::ProContract,
    ] {
        config.features.disable(feature).map_err(|error| {
            start(format!(
                "cannot disable `features.{}` for the worker: {error}",
                feature.key()
            ))
        })?;
    }
    Ok(config)
}

/// Starts a hidden worker, runs one turn, returns its final message, and removes the worker.
pub(crate) async fn run_turn(
    manager: &ThreadManager,
    config: Config,
    turn: WorkerTurn,
) -> Result<String, WorkerError> {
    let mut options = StartThreadOptions::new(config);
    options.session_source = Some(SessionSource::Internal(
        InternalSessionSource::ExtensionWorker,
    ));
    options.thread_source = Some(ThreadSource::Feature("pro_contract".to_string()));
    options.environments = Some(Vec::new());
    options
        .thread_extension_init
        .insert(SessionIsolation::Isolated);
    options.thread_extension_init.insert(ToolPolicy {
        allowed_tools: Some(Vec::new()),
        require_managed_sandbox: false,
        require_unified_exec: false,
        expose_additional_permissions: false,
    });
    let NewThread {
        thread_id, thread, ..
    } = manager
        .start_thread(options)
        .await
        .map_err(|error| WorkerError::Start(error.to_string()))?;
    let result = async {
        let request = TurnInputRequest::user_input(vec![UserInput::Text {
            text: turn.prompt,
            text_elements: Vec::new(),
        }])
        .on_start(TurnStartOptions {
            turn_trigger: Some(turn.trigger.to_string()),
            final_output_json_schema: Some(turn.schema),
            ..Default::default()
        });
        let turn_id = match thread
            .start_turn_if_idle(request)
            .await
            .map_err(|error| WorkerError::NotStarted(error.to_string()))?
        {
            StartIfIdleSubmission::Started { turn_id } => turn_id,
            StartIfIdleSubmission::NotSubmitted { reason } => {
                return Err(WorkerError::NotStarted(format!("{reason:?}")));
            }
        };
        let deadline = tokio::time::sleep(turn.deadline);
        tokio::pin!(deadline);
        let mut last_error = None;
        loop {
            tokio::select! {
                _ = &mut deadline => {
                    let _ = thread.submit(Op::Interrupt).await;
                    return Err(WorkerError::TimedOut);
                }
                event = thread.next_event() => {
                    let event = event.map_err(|error| WorkerError::Failed(error.to_string()))?;
                    if event.id != turn_id {
                        continue;
                    }
                    match event.msg {
                        EventMsg::TurnComplete(complete) if complete.turn_id == turn_id => {
                            return complete.last_agent_message.ok_or_else(|| {
                                WorkerError::Failed(
                                    last_error.unwrap_or_else(|| "no final message".to_string()),
                                )
                            });
                        }
                        EventMsg::TurnAborted(_) => return Err(WorkerError::Aborted),
                        EventMsg::Error(error) => last_error = Some(error.message),
                        _ => {}
                    }
                }
            }
        }
    }
    .await;
    if tokio::time::timeout(SHUTDOWN_TIMEOUT, thread.shutdown_and_wait())
        .await
        .is_err()
    {
        tracing::warn!("pro_contract worker {thread_id} did not shut down in time");
    }
    manager.remove_thread(&thread_id).await;
    result
}
