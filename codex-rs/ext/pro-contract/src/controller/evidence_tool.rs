//! Codex tool adapter. Query semantics and task scoping live in the read-only archive.

use std::sync::Arc;

use codex_extension_api::ExtensionData;
use codex_extension_api::FunctionCallError;
use codex_extension_api::JsonToolOutput;
use codex_extension_api::ResponsesApiTool;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolContributor;
use codex_extension_api::ToolExecutor;
use codex_extension_api::ToolExecutorFuture;
use codex_extension_api::ToolName;
use codex_extension_api::ToolOutput;
use codex_extension_api::ToolSpec;
use codex_extension_api::parse_tool_input_schema;
use serde_json::json;

use super::archive::EvidenceAccess;
use super::archive::Query;

const NAME: &str = "contract_read_evidence";

fn access_context(
    thread: &str,
    turn: &str,
    call: &str,
    source: &codex_extension_api::ToolCallSource,
) -> serde_json::Value {
    let source = match source {
        codex_extension_api::ToolCallSource::Direct => json!({"kind":"direct"}),
        codex_extension_api::ToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        } => {
            json!({"kind":"code_mode","cell_id":cell_id,"runtime_tool_call_id":runtime_tool_call_id})
        }
    };
    json!({"thread_id":thread,"turn_id":turn,"call_id":call,"source":source})
}

pub(crate) struct EvidenceTools;

impl ToolContributor for EvidenceTools {
    fn tools(
        &self,
        _session: &ExtensionData,
        thread: &ExtensionData,
    ) -> Vec<Arc<dyn for<'call> ToolExecutor<ToolCall<'call>>>> {
        let access = thread.get::<EvidenceAccess>();
        let mut tools: Vec<Arc<dyn for<'call> ToolExecutor<ToolCall<'call>>>> =
            access.map_or_else(Vec::new, |access| {
                vec![
                    Arc::new(EvidenceTool(access, thread.level_id().to_string()))
                        as Arc<dyn for<'call> ToolExecutor<ToolCall<'call>>>,
                ]
            });
        if let Some(runtime) = thread.get::<super::runtime::ThreadRuntime>()
            && runtime.progress_enabled()
        {
            tools.push(Arc::new(ProgressTool(runtime, None)));
        } else if let Some(access) = thread.get::<ProgressAccess>()
            && let Some(runtime) = access.runtime.upgrade()
        {
            tools.push(Arc::new(ProgressTool(
                runtime,
                Some((access.epoch, access.deadline_ms)),
            )));
        }
        tools
    }
}

struct EvidenceTool(Arc<EvidenceAccess>, String);

impl codex_extension_api::ToolLifecycleContributor for EvidenceTools {
    fn on_tool_finish<'a>(
        &'a self,
        input: codex_extension_api::ToolFinishInput<'a>,
    ) -> codex_extension_api::ToolLifecycleFuture<'a> {
        Box::pin(async move {
            if input.tool_name.clone().with_default_namespace()
                != ToolName::plain(NAME).with_default_namespace()
            {
                return;
            }
            if let Some(access) = input.thread_store.get::<EvidenceAccess>() {
                let caller = access_context(
                    input.thread_store.level_id(),
                    input.turn_id,
                    input.call_id,
                    &input.source,
                );
                use super::observations::AccessOutcome;
                use codex_extension_api::ToolCallOutcome;
                let outcome = match input.outcome {
                    ToolCallOutcome::Completed { success: true } => AccessOutcome::Completed,
                    ToolCallOutcome::Completed { success: false } => AccessOutcome::Unsuccessful,
                    ToolCallOutcome::Blocked => AccessOutcome::Blocked,
                    ToolCallOutcome::Failed { .. } => AccessOutcome::Failed,
                    ToolCallOutcome::Aborted => AccessOutcome::Aborted,
                };
                if let Err(reason) = access.finish_access(caller, outcome).await {
                    // A prepared response without a finish remains explicitly unconfirmed.
                    tracing::warn!(
                        "pro_contract could not retain evidence-access completion: {reason}"
                    );
                }
            }
        })
    }
}

impl<'call> ToolExecutor<ToolCall<'call>> for EvidenceTool {
    fn tool_name(&self) -> ToolName {
        ToolName::plain(NAME)
    }

    fn spec(&self) -> ToolSpec {
        ToolSpec::Function(ResponsesApiTool {
            name: NAME.into(),
            description: "Read this task's immutable public verification evidence. frontier lists previously failed registered checks without a later complete passing replay; index lists every retained verification; read returns exact UTF-8 pages of an indexed handle. Offsets and next_offset are bytes for read, entries otherwise. Follow pages to eof. Public receipts may already contain capture omissions. Sealed checks are never exposed. This tool does not run checks, change authority or certify completion.".into(),
            strict: false, defer_loading: None, output_schema: None,
            parameters: parse_tool_input_schema(&json!({
                "type":"object", "properties":{
                    "op":{"type":"string", "enum":["index","frontier","read"]},
                    "handle":{"type":"string", "description":"Exact handle from index or frontier; required for read."},
                    "offset":{"type":"integer", "minimum":0}
                }, "required":["op"], "additionalProperties":false
            })).unwrap_or_else(|error| panic!("public evidence schema must parse: {error}")),
        })
    }

    fn supports_parallel_tool_calls(&self) -> bool {
        true
    }

    fn handle<'a>(&'a self, call: ToolCall<'call>) -> ToolExecutorFuture<'a>
    where
        'call: 'a,
    {
        Box::pin(async move {
            let raw = call.function_arguments()?;
            let error = FunctionCallError::RespondToModel;
            if raw.len() > 4096 {
                return Err(error("evidence query exceeds 4 KiB".into()));
            }
            let query: Query = serde_json::from_str(raw).map_err(|e| error(e.to_string()))?;
            let value = self
                .0
                .read_observed(
                    query,
                    call.response_byte_budget(8192),
                    access_context(&self.1, &call.turn_id, &call.call_id, &call.source),
                )
                .await
                .map_err(error)?;
            Ok(Box::new(JsonToolOutput::new(value).with_external_context()) as Box<dyn ToolOutput>)
        })
    }
}

#[derive(Clone)]
pub(crate) struct ProgressAccess {
    pub runtime: std::sync::Weak<super::runtime::ThreadRuntime>,
    pub epoch: u64,
    pub deadline_ms: u64,
}

struct ProgressTool(Arc<super::runtime::ThreadRuntime>, Option<(u64, u64)>);
impl<'call> ToolExecutor<ToolCall<'call>> for ProgressTool {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("publish_progress")
    }
    fn spec(&self) -> ToolSpec {
        ToolSpec::Function(ResponsesApiTool {
            name: "publish_progress".into(),
            description: "Capture a consistent frozen workspace and return bounded public assessment in this turn. review=true also requests independent artifact diagnosis, including when checks fail or their evidence is incomplete. Stop or finish background jobs first. Requests share the original task grant. A stable request_id reopens the same assessment; changing review requires a new ID. Read the retained checks and diagnosis with contract_read_evidence. This operation does not propose a candidate, grant Support, settle responsibility or finish the task.".into(),
            strict: false, defer_loading: None, output_schema: None,
            parameters: parse_tool_input_schema(&json!({"type":"object","properties":{
                "request_id":{"type":"string","minLength":1,"maxLength":128},
                "review":{"type":"boolean","description":"Request independent diagnosis of this snapshot in addition to its public checks; defaults to false."}},
                "required":["request_id"],"additionalProperties":false})).unwrap_or_else(|error| panic!("static progress schema must parse: {error}")),
        })
    }
    fn supports_parallel_tool_calls(&self) -> bool {
        false
    }
    fn handle<'a>(&'a self, call: ToolCall<'call>) -> ToolExecutorFuture<'a>
    where
        'call: 'a,
    {
        Box::pin(async move {
            #[derive(serde::Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Request {
                request_id: String,
                #[serde(default)]
                review: bool,
            }
            let raw = call.function_arguments()?;
            let error = FunctionCallError::RespondToModel;
            if raw.len() > 1024 {
                return Err(error("publication request exceeds 1 KiB".into()));
            }
            let request: Request = serde_json::from_str(raw).map_err(|e| error(e.to_string()))?;
            let mut value = self
                .0
                .publish_progress_with_review(
                    request.request_id,
                    call.turn_id,
                    self.1,
                    request.review,
                )
                .await
                .map_err(error)?;
            if let Ok(budget) = self.0.remaining_task_budget().await {
                value["budget"] = budget;
            }
            Ok(Box::new(JsonToolOutput::new(value).with_external_context()) as Box<dyn ToolOutput>)
        })
    }
}
