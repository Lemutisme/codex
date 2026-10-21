use crate::function_tool::FunctionCallError;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::CoreToolRuntime;
use crate::tools::registry::ToolExecutor;
use crate::tools::registry::ToolExposure;
use codex_protocol::dynamic_tools::DynamicToolFunctionSpec;
use codex_protocol::dynamic_tools::DynamicToolNamespaceSpec;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::items::DynamicToolCallItem;
use codex_protocol::items::DynamicToolCallStatus;
use codex_protocol::items::TurnItem;
use codex_protocol::models::FunctionCallOutputContentItem;
use codex_protocol::models::ResponseInputItem;
use codex_tools::ResponsesApiNamespace;
use codex_tools::ResponsesApiNamespaceTool;
use codex_tools::ToolName;
use codex_tools::ToolSearchInfo;
use codex_tools::ToolSearchSourceInfo;
use codex_tools::ToolSpec;
use codex_tools::default_namespace_description;
use codex_tools::dynamic_tool_to_responses_api_tool;
use serde_json::Value;
use std::time::Instant;
use tokio::sync::oneshot;
use tracing::warn;

pub struct DynamicToolHandler {
    tool_name: ToolName,
    spec: ToolSpec,
    exposure: ToolExposure,
}

struct DynamicToolOutput {
    content: FunctionToolOutput,
    structured: Option<serde_json::Map<String, Value>>,
}

impl From<DynamicToolResponse> for DynamicToolOutput {
    fn from(response: DynamicToolResponse) -> Self {
        Self {
            content: FunctionToolOutput::from_content(
                response
                    .content_items
                    .into_iter()
                    .map(FunctionCallOutputContentItem::from)
                    .collect(),
                Some(response.success),
            ),
            structured: response.structured_content,
        }
    }
}

impl ToolOutput for DynamicToolOutput {
    fn log_output(&self) -> String {
        self.content.log_output()
    }
    fn success_for_logging(&self) -> bool {
        self.content.success_for_logging()
    }
    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        self.content.to_response_item(call_id, payload)
    }
    fn code_mode_result(&self, payload: &ToolPayload) -> Value {
        self.structured.as_ref().map_or_else(
            || self.content.code_mode_result(payload),
            |value| Value::Object(value.clone()),
        )
    }
}

impl DynamicToolHandler {
    pub fn new(tool: &DynamicToolFunctionSpec) -> Option<Self> {
        Self::from_parts(tool, /*namespace*/ None)
    }

    pub fn new_in_namespace(
        namespace: &DynamicToolNamespaceSpec,
        tool: &DynamicToolFunctionSpec,
    ) -> Option<Self> {
        Self::from_parts(tool, Some(namespace))
    }

    fn from_parts(
        tool: &DynamicToolFunctionSpec,
        namespace: Option<&DynamicToolNamespaceSpec>,
    ) -> Option<Self> {
        let tool_name = ToolName::new(
            namespace.map(|namespace| namespace.name.clone()),
            tool.name.clone(),
        );
        let mut output_tool = dynamic_tool_to_responses_api_tool(tool).ok()?;
        // Exposure controls deferral; tool search restores this marker for deferred results.
        output_tool.defer_loading = None;
        let spec = match namespace {
            Some(namespace) => ToolSpec::Namespace(ResponsesApiNamespace {
                name: namespace.name.clone(),
                description: if namespace.description.trim().is_empty() {
                    default_namespace_description(&namespace.name)
                } else {
                    namespace.description.clone()
                },
                tools: vec![ResponsesApiNamespaceTool::Function(output_tool)],
            }),
            None => ToolSpec::Function(output_tool),
        };
        Some(Self {
            tool_name,
            spec,
            exposure: if tool.defer_loading {
                ToolExposure::Deferred
            } else {
                ToolExposure::Direct
            },
        })
    }
}

impl ToolExecutor<ToolInvocation> for DynamicToolHandler {
    fn tool_name(&self) -> ToolName {
        self.tool_name.clone()
    }

    fn spec(&self) -> ToolSpec {
        self.spec.clone()
    }

    fn exposure(&self) -> ToolExposure {
        self.exposure
    }

    fn search_info(&self) -> Option<ToolSearchInfo> {
        ToolSearchInfo::from_tool_spec(
            self.spec(),
            Some(ToolSearchSourceInfo {
                name: "Dynamic tools".to_string(),
                description: Some("Tools provided by the current Codex thread.".to_string()),
            }),
        )
    }

    fn handle<'a>(&'a self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'a>
    where
        ToolInvocation: 'a,
    {
        Box::pin(self.handle_call(invocation))
    }
}

impl DynamicToolHandler {
    async fn handle_call(
        &self,
        invocation: ToolInvocation,
    ) -> Result<Box<dyn crate::tools::context::ToolOutput>, FunctionCallError> {
        let ToolInvocation {
            session,
            turn,
            call_id,
            payload,
            ..
        } = invocation;

        let arguments = match payload {
            ToolPayload::Function { arguments } => arguments,
            _ => {
                return Err(FunctionCallError::RespondToModel(
                    "dynamic tool handler received unsupported payload".to_string(),
                ));
            }
        };

        let args: Value = parse_arguments(&arguments)?;
        let response = request_dynamic_tool(
            &session,
            turn.as_ref(),
            call_id,
            self.tool_name.clone(),
            args,
        )
        .await
        .ok_or_else(|| {
            FunctionCallError::RespondToModel(
                "dynamic tool call was cancelled before receiving a response".to_string(),
            )
        })?;

        Ok(boxed_tool_output(DynamicToolOutput::from(response)))
    }
}

impl CoreToolRuntime for DynamicToolHandler {
    fn is_third_party_tool(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod structured_output_tests {
    use super::*;
    use codex_protocol::dynamic_tools::DynamicToolCallOutputContentItem;
    use serde_json::json;

    #[test]
    fn explicit_structured_output_reaches_code_mode_without_reinterpreting_legacy_text() {
        let payload = ToolPayload::Function {
            arguments: "{}".into(),
        };
        let text = r#"{"next_offset":4,"eof":true}"#;
        let response = DynamicToolResponse {
            content_items: vec![DynamicToolCallOutputContentItem::InputText { text: text.into() }],
            success: true,
            structured_content: None,
        };
        let legacy = DynamicToolOutput::from(response.clone());
        assert_eq!(legacy.code_mode_result(&payload), json!(text));
        let mut response = response;
        response.structured_content = Some(serde_json::from_str(text).unwrap());
        let structured = DynamicToolOutput::from(response);
        assert_eq!(structured.code_mode_result(&payload)["next_offset"], 4);
        assert_eq!(structured.code_mode_result(&payload)["eof"], true);
        assert_eq!(
            structured.to_response_item("call", &payload),
            legacy.to_response_item("call", &payload)
        );
        assert!(structured.success_for_logging());
    }
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "active turn checks and dynamic tool response registration must remain atomic"
)]
async fn request_dynamic_tool(
    session: &Session,
    turn_context: &TurnContext,
    call_id: String,
    tool_name: ToolName,
    arguments: Value,
) -> Option<DynamicToolResponse> {
    let namespace = tool_name.namespace;
    let tool = tool_name.name;
    let (tx_response, rx_response) = oneshot::channel();
    let event_id = call_id.clone();
    let prev_entry = {
        let mut active = session.active_turn.lock().await;
        match active.as_mut() {
            Some(at) => {
                let mut ts = at.turn_state.lock().await;
                ts.insert_pending_dynamic_tool(call_id.clone(), tx_response)
            }
            None => None,
        }
    };
    if prev_entry.is_some() {
        warn!("Overwriting existing pending dynamic tool call for call_id: {event_id}");
    }

    let started_at = Instant::now();
    session
        .emit_turn_item_started(
            turn_context,
            &TurnItem::DynamicToolCall(DynamicToolCallItem {
                id: call_id.clone(),
                namespace: namespace.clone(),
                tool: tool.clone(),
                arguments: arguments.clone(),
                status: DynamicToolCallStatus::InProgress,
                content_items: None,
                success: None,
                error: None,
                duration: None,
            }),
        )
        .await;
    let response = rx_response.await.ok();

    let item = match &response {
        Some(response) => DynamicToolCallItem {
            id: call_id,
            namespace,
            tool,
            arguments,
            status: if response.success {
                DynamicToolCallStatus::Completed
            } else {
                DynamicToolCallStatus::Failed
            },
            content_items: Some(response.content_items.clone()),
            success: Some(response.success),
            error: None,
            duration: Some(started_at.elapsed()),
        },
        None => DynamicToolCallItem {
            id: call_id,
            namespace,
            tool,
            arguments,
            status: DynamicToolCallStatus::Failed,
            content_items: Some(Vec::new()),
            success: Some(false),
            error: Some("dynamic tool call was cancelled before receiving a response".to_string()),
            duration: Some(started_at.elapsed()),
        },
    };
    session
        .emit_turn_item_completed(turn_context, TurnItem::DynamicToolCall(item))
        .await;

    response
}
