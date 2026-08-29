use codex_tools::ToolName;
use codex_tools::ToolPayload;

use crate::ContentItemKind;
use crate::ExtensionData;
use crate::ExtensionFuture;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionReminder {
    text: String,
    content_kind: ContentItemKind,
}

impl ExecutionReminder {
    /// Maximum UTF-8 payload accepted for one model-visible reminder.
    pub const MAX_BYTES: usize = 4_096;

    /// Creates a bounded reminder, returning `None` when its payload is too large.
    pub fn new(text: impl Into<String>, content_kind: ContentItemKind) -> Option<Self> {
        let text = text.into();
        (text.len() <= Self::MAX_BYTES).then_some(Self { text, content_kind })
    }

    /// Consumes the reminder into the host fragment fields.
    pub fn into_parts(self) -> (String, ContentItemKind) {
        (self.text, self.content_kind)
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ExecutionPermit {
    pub valid_until: Option<u64>,
    pub reminders: Vec<ExecutionReminder>,
}

/// Decision returned by a host execution-admission contributor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ExecutionAdmission {
    Permit(ExecutionPermit),
    Deny { reason: String },
}

/// Stable host state exposed before one provider sampling request.
pub struct SamplingAdmissionInput<'a> {
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub turn_id: &'a str,
}

/// Finalized tool identity exposed immediately before tool execution.
pub struct ToolAdmissionInput<'a> {
    pub session_store: &'a ExtensionData,
    pub thread_store: &'a ExtensionData,
    pub turn_store: &'a ExtensionData,
    pub turn_id: &'a str,
    pub call_id: &'a str,
    pub tool_name: &'a ToolName,
    pub payload: &'a ToolPayload,
}

/// Stable host state used to filter one model-visible tool definition.
pub struct ToolVisibilityInput<'a> {
    /// Session-scoped extension state.
    pub session_store: &'a ExtensionData,
    /// Thread-scoped extension state.
    pub thread_store: &'a ExtensionData,
    /// Sampling-step extension state.
    pub step_store: &'a ExtensionData,
    /// Final host tool identity whose definition is being projected.
    pub tool_name: &'a ToolName,
}

/// Model-visible projection decision; execution admission remains authoritative.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ToolVisibility {
    /// Preserve the visibility selected by the host tool planner.
    Inherit,
    /// Keep the runtime registered for stale-call rejection but hide its definition.
    Hidden,
}

/// A fail-closed gate for provider sampling and finalized tool calls.
///
/// Implementations must base decisions only on host-authenticated state. Tool
/// input is sensitive and must not be logged. Contributors run in registration
/// order, and the first denial prevents the operation from starting.
pub trait ExecutionAdmissionContributor: Send + Sync {
    /// Narrows the model-visible tool projection without granting execution authority.
    fn tool_visibility(&self, _input: ToolVisibilityInput<'_>) -> ToolVisibility {
        ToolVisibility::Inherit
    }

    fn admit_sampling<'a>(
        &'a self,
        _input: SamplingAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        Box::pin(std::future::ready(ExecutionAdmission::Permit(
            ExecutionPermit::default(),
        )))
    }

    fn admit_tool<'a>(
        &'a self,
        _input: ToolAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        Box::pin(std::future::ready(ExecutionAdmission::Permit(
            ExecutionPermit::default(),
        )))
    }
}
