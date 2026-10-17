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
                vec![Arc::new(EvidenceTool(access))
                    as Arc<dyn for<'call> ToolExecutor<ToolCall<'call>>>]
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

struct EvidenceTool(Arc<EvidenceAccess>);

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
                .read(query, call.response_byte_budget(8192))
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
            description: "Publish a consistent frozen workspace and receive bounded public checks or review in this same turn. Stop or finish background jobs first. Use after a coherent change or before spending most of the task budget. This spends the original finite publication grant. A stable request_id reopens its completed receipt without rerunning. Read full evidence with contract_read_evidence. This does not propose, accept or finish the task; repair observed failures and continue.".into(),
            strict: false, defer_loading: None, output_schema: None,
            parameters: parse_tool_input_schema(&json!({"type":"object","properties":{
                "request_id":{"type":"string","minLength":1,"maxLength":128}},
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
            }
            let raw = call.function_arguments()?;
            let error = FunctionCallError::RespondToModel;
            if raw.len() > 1024 {
                return Err(error("publication request exceeds 1 KiB".into()));
            }
            let request: Request = serde_json::from_str(raw).map_err(|e| error(e.to_string()))?;
            let value = match self.1 {
                None => {
                    self.0
                        .publish_progress(request.request_id, call.turn_id)
                        .await
                }
                Some(binding) => {
                    self.0
                        .publish_progress_for(request.request_id, call.turn_id, Some(binding))
                        .await
                }
            }
            .map_err(error)?;
            Ok(Box::new(JsonToolOutput::new(value).with_external_context()) as Box<dyn ToolOutput>)
        })
    }
}
