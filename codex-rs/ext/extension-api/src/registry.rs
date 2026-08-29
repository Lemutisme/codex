use std::sync::Arc;

use codex_protocol::protocol::ReviewDecision;

use crate::ApprovalAssessment;
use crate::ApprovalReviewContributor;
use crate::ApprovalReviewError;
use crate::ApprovalReviewInput;
use crate::ConfigContributor;
use crate::ContextContributor;
use crate::ExecutionAdmission;
use crate::ExecutionAdmissionContributor;
use crate::ExecutionPermit;
use crate::ExtensionData;
use crate::ExtensionEventSink;
use crate::ExtensionMetrics;
use crate::McpServerContributor;
use crate::NoopExtensionEventSink;
use crate::SamplingAdmissionInput;
use crate::SkillInvocationContributor;
use crate::ThreadLifecycleContributor;
use crate::TokenUsageContributor;
use crate::ToolAdmissionInput;
use crate::ToolContributor;
use crate::ToolLifecycleContributor;
use crate::ToolVisibility;
use crate::ToolVisibilityInput;
use crate::TurnInputContributor;
use crate::TurnItemContributor;
use crate::TurnLifecycleContributor;

const MAX_EXECUTION_REMINDERS: usize = 4;

/// Mutable registry used while hosts register typed runtime contributions.
pub struct ExtensionRegistryBuilder<C: Sync> {
    registry: ExtensionRegistry<C>,
}

impl<C: Sync> Default for ExtensionRegistryBuilder<C> {
    fn default() -> Self {
        Self {
            registry: ExtensionRegistry {
                event_sink: Arc::new(NoopExtensionEventSink),
                execution_admission_contributors: Vec::new(),
                thread_lifecycle_contributors: Vec::new(),
                turn_lifecycle_contributors: Vec::new(),
                config_contributors: Vec::new(),
                token_usage_contributors: Vec::new(),
                skill_invocation_contributors: Vec::new(),
                approval_review_contributors: Vec::new(),
                context_contributors: Vec::new(),
                mcp_server_contributors: Vec::new(),
                turn_input_contributors: Vec::new(),
                tool_contributors: Vec::new(),
                tool_lifecycle_contributors: Vec::new(),
                turn_item_contributors: Vec::new(),
            },
        }
    }
}

impl<C: Sync> ExtensionRegistryBuilder<C> {
    /// Creates an empty registry builder.
    pub fn new() -> Self {
        Self::default()
    }

    /// Creates an empty registry builder with a host-provided event sink.
    pub fn with_event_sink(event_sink: Arc<dyn ExtensionEventSink>) -> Self {
        let mut builder = Self::default();
        builder.registry.event_sink = event_sink;
        builder
    }

    /// Returns the host event sink to pass into extension constructors.
    pub fn event_sink(&self) -> Arc<dyn ExtensionEventSink> {
        Arc::clone(&self.registry.event_sink)
    }

    /// Registers a provider/tool execution-admission contributor.
    pub fn execution_admission_contributor(
        &mut self,
        contributor: Arc<dyn ExecutionAdmissionContributor>,
    ) {
        self.registry
            .execution_admission_contributors
            .push(contributor);
    }

    /// Registers one approval-review contributor.
    pub fn approval_review_contributor(&mut self, contributor: Arc<dyn ApprovalReviewContributor>) {
        self.registry.approval_review_contributors.push(contributor);
    }

    /// Registers one thread-lifecycle contributor.
    pub fn thread_lifecycle_contributor(
        &mut self,
        contributor: Arc<dyn ThreadLifecycleContributor<C>>,
    ) {
        self.registry
            .thread_lifecycle_contributors
            .push(contributor);
    }

    /// Registers one turn-lifecycle contributor.
    pub fn turn_lifecycle_contributor(&mut self, contributor: Arc<dyn TurnLifecycleContributor>) {
        self.registry.turn_lifecycle_contributors.push(contributor);
    }

    /// Registers one config contributor.
    pub fn config_contributor(&mut self, contributor: Arc<dyn ConfigContributor<C>>) {
        self.registry.config_contributors.push(contributor);
    }

    /// Registers one token-usage contributor.
    pub fn token_usage_contributor(&mut self, contributor: Arc<dyn TokenUsageContributor>) {
        self.registry.token_usage_contributors.push(contributor);
    }

    /// Registers one skill-invocation contributor.
    pub fn skill_invocation_contributor(
        &mut self,
        contributor: Arc<dyn SkillInvocationContributor>,
    ) {
        self.registry
            .skill_invocation_contributors
            .push(contributor);
    }

    /// Registers one prompt contributor.
    pub fn prompt_contributor(&mut self, contributor: Arc<dyn ContextContributor>) {
        self.registry.context_contributors.push(contributor);
    }

    /// Registers one runtime MCP server contributor.
    pub fn mcp_server_contributor(&mut self, contributor: Arc<dyn McpServerContributor<C>>) {
        self.registry.mcp_server_contributors.push(contributor);
    }

    /// Registers one turn-input contributor.
    pub fn turn_input_contributor(&mut self, contributor: Arc<dyn TurnInputContributor>) {
        self.registry.turn_input_contributors.push(contributor);
    }

    /// Registers one native tool contributor.
    pub fn tool_contributor(&mut self, contributor: Arc<dyn ToolContributor>) {
        self.registry.tool_contributors.push(contributor);
    }

    /// Registers one tool-lifecycle contributor.
    pub fn tool_lifecycle_contributor(&mut self, contributor: Arc<dyn ToolLifecycleContributor>) {
        self.registry.tool_lifecycle_contributors.push(contributor);
    }

    /// Registers one ordered turn-item contributor.
    pub fn turn_item_contributor(&mut self, contributor: Arc<dyn TurnItemContributor>) {
        self.registry.turn_item_contributors.push(contributor);
    }

    /// Finishes construction and returns the immutable registry.
    pub fn build(self) -> ExtensionRegistry<C> {
        self.registry
    }
}

/// Immutable typed registry produced after extensions are installed.
pub struct ExtensionRegistry<C: Sync> {
    event_sink: Arc<dyn ExtensionEventSink>,
    execution_admission_contributors: Vec<Arc<dyn ExecutionAdmissionContributor>>,
    thread_lifecycle_contributors: Vec<Arc<dyn ThreadLifecycleContributor<C>>>,
    turn_lifecycle_contributors: Vec<Arc<dyn TurnLifecycleContributor>>,
    config_contributors: Vec<Arc<dyn ConfigContributor<C>>>,
    token_usage_contributors: Vec<Arc<dyn TokenUsageContributor>>,
    skill_invocation_contributors: Vec<Arc<dyn SkillInvocationContributor>>,
    context_contributors: Vec<Arc<dyn ContextContributor>>,
    mcp_server_contributors: Vec<Arc<dyn McpServerContributor<C>>>,
    turn_input_contributors: Vec<Arc<dyn TurnInputContributor>>,
    tool_contributors: Vec<Arc<dyn ToolContributor>>,
    tool_lifecycle_contributors: Vec<Arc<dyn ToolLifecycleContributor>>,
    turn_item_contributors: Vec<Arc<dyn TurnItemContributor>>,
    approval_review_contributors: Vec<Arc<dyn ApprovalReviewContributor>>,
}

impl<C: Sync> ExtensionRegistry<C> {
    /// Returns the host event sink retained by this registry.
    pub fn event_sink(&self) -> Arc<dyn ExtensionEventSink> {
        Arc::clone(&self.event_sink)
    }

    /// Returns the registered execution-admission contributors.
    pub fn execution_admission_contributors(&self) -> &[Arc<dyn ExecutionAdmissionContributor>] {
        &self.execution_admission_contributors
    }

    /// Applies execution-admission contributors in registration order.
    pub async fn admit_sampling(&self, input: SamplingAdmissionInput<'_>) -> ExecutionAdmission {
        let mut permit = ExecutionPermit::default();
        for contributor in &self.execution_admission_contributors {
            match contributor
                .admit_sampling(SamplingAdmissionInput {
                    session_store: input.session_store,
                    thread_store: input.thread_store,
                    turn_store: input.turn_store,
                    turn_id: input.turn_id,
                })
                .await
            {
                ExecutionAdmission::Permit(contribution) => {
                    if let Some(valid_until) = contribution.valid_until {
                        permit.valid_until = Some(
                            permit
                                .valid_until
                                .map_or(valid_until, |current| current.min(valid_until)),
                        );
                    }
                    let remaining = MAX_EXECUTION_REMINDERS.saturating_sub(permit.reminders.len());
                    permit
                        .reminders
                        .extend(contribution.reminders.into_iter().take(remaining));
                }
                denial @ ExecutionAdmission::Deny { .. } => return denial,
            }
        }
        ExecutionAdmission::Permit(permit)
    }

    /// Applies tool-admission contributors in registration order.
    pub async fn admit_tool(&self, input: ToolAdmissionInput<'_>) -> ExecutionAdmission {
        for contributor in &self.execution_admission_contributors {
            match contributor
                .admit_tool(ToolAdmissionInput {
                    session_store: input.session_store,
                    thread_store: input.thread_store,
                    turn_store: input.turn_store,
                    turn_id: input.turn_id,
                    call_id: input.call_id,
                    tool_name: input.tool_name,
                    payload: input.payload,
                })
                .await
            {
                ExecutionAdmission::Permit(_) => {}
                denial @ ExecutionAdmission::Deny { .. } => return denial,
            }
        }
        ExecutionAdmission::Permit(ExecutionPermit::default())
    }

    pub fn tool_visibility(&self, input: ToolVisibilityInput<'_>) -> ToolVisibility {
        for contributor in &self.execution_admission_contributors {
            if contributor.tool_visibility(ToolVisibilityInput {
                session_store: input.session_store,
                thread_store: input.thread_store,
                step_store: input.step_store,
                tool_name: input.tool_name,
            }) == ToolVisibility::Hidden
            {
                return ToolVisibility::Hidden;
            }
        }
        ToolVisibility::Inherit
    }

    /// Returns the registered thread-lifecycle contributors.
    pub fn thread_lifecycle_contributors(&self) -> &[Arc<dyn ThreadLifecycleContributor<C>>] {
        &self.thread_lifecycle_contributors
    }

    /// Returns the registered turn-lifecycle contributors.
    pub fn turn_lifecycle_contributors(&self) -> &[Arc<dyn TurnLifecycleContributor>] {
        &self.turn_lifecycle_contributors
    }

    /// Returns the registered config contributors.
    pub fn config_contributors(&self) -> &[Arc<dyn ConfigContributor<C>>] {
        &self.config_contributors
    }

    /// Returns the registered token-usage contributors.
    pub fn token_usage_contributors(&self) -> &[Arc<dyn TokenUsageContributor>] {
        &self.token_usage_contributors
    }

    /// Returns the registered skill-invocation contributors.
    pub fn skill_invocation_contributors(&self) -> &[Arc<dyn SkillInvocationContributor>] {
        &self.skill_invocation_contributors
    }

    /// Whether any installed skill contributor needs a snapshot of host-owned skills.
    ///
    /// Registries without skill contributors retain legacy host discovery behavior.
    pub fn requires_host_skill_discovery(&self) -> bool {
        self.skill_invocation_contributors.is_empty()
            || self
                .skill_invocation_contributors
                .iter()
                .any(|contributor| contributor.requires_host_skill_discovery())
    }

    /// Returns the first full approval assessment claimed by a contributor.
    pub async fn full_approval_review(
        &self,
        input: ApprovalReviewInput<'_>,
    ) -> Option<Result<ApprovalAssessment, ApprovalReviewError>> {
        for contributor in &self.approval_review_contributors {
            if let Some(assessment) = contributor.full_review(&input).await {
                return Some(assessment);
            }
        }

        None
    }

    /// Returns the first fast approval decision claimed by a contributor.
    pub async fn fast_approval_decision(
        &self,
        session_store: &ExtensionData,
        thread_store: &ExtensionData,
        prompt: &str,
        extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
    ) -> Option<ReviewDecision> {
        for contributor in &self.approval_review_contributors {
            if let Some(decision) = contributor
                .fast_decision(
                    session_store,
                    thread_store,
                    prompt,
                    extension_metrics.clone(),
                )
                .await
            {
                return Some(decision);
            }
        }

        None
    }

    /// Returns the registered prompt contributors.
    pub fn context_contributors(&self) -> &[Arc<dyn ContextContributor>] {
        &self.context_contributors
    }

    /// Returns the registered runtime MCP server contributors.
    pub fn mcp_server_contributors(&self) -> &[Arc<dyn McpServerContributor<C>>] {
        &self.mcp_server_contributors
    }

    /// Returns the registered turn-input contributors.
    pub fn turn_input_contributors(&self) -> &[Arc<dyn TurnInputContributor>] {
        &self.turn_input_contributors
    }

    /// Returns the registered native tool contributors.
    pub fn tool_contributors(&self) -> &[Arc<dyn ToolContributor>] {
        &self.tool_contributors
    }

    /// Returns the registered tool-lifecycle contributors.
    pub fn tool_lifecycle_contributors(&self) -> &[Arc<dyn ToolLifecycleContributor>] {
        &self.tool_lifecycle_contributors
    }

    /// Returns the registered ordered turn-item contributors.
    pub fn turn_item_contributors(&self) -> &[Arc<dyn TurnItemContributor>] {
        &self.turn_item_contributors
    }
}

/// Creates an empty shared registry for hosts that do not register contributions.
pub fn empty_extension_registry<C: Sync>() -> Arc<ExtensionRegistry<C>> {
    Arc::new(ExtensionRegistryBuilder::new().build())
}
