//! Fresh executor history, inherited authority/budget/environment, and confirmed shutdown.
//! The owning runtime alone captures, verifies and advances the existing responsibility.

use std::collections::BTreeMap;
use std::time::Duration;

use codex_core::StartIfIdleSubmission;
use codex_core::StartThreadOptions;
use codex_core::ThreadManager;
use codex_core::TurnInput;
use codex_core::TurnInputRequest;
use codex_core::TurnStartOptions;
use codex_core::config::Config;
use codex_core::config::Constrained;
use codex_core::context::ContextualUserFragment;
use codex_core::context::InternalContextSource;
use codex_core::context::InternalModelContextFragment;
use codex_extension_api::SessionIsolation;
use codex_features::Feature;
use codex_history::RetainedContextEntry;
use codex_protocol::ThreadId;
use codex_protocol::protocol::AdditionalContextEntry;
use codex_protocol::protocol::AdditionalContextKind;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::InternalSessionSource;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadSource;
use tokio::sync::watch;

pub(crate) struct SuccessorTurn {
    pub id: ThreadId,
    pub environment_id: String,
    pub packet: String,
    pub deadline_ms: u64,
    pub cancel: watch::Receiver<bool>,
}

pub(crate) struct SuccessorHandoff {
    pub turn_id: String,
    pub summary: String,
}

pub(crate) enum SuccessorExit {
    Handoff(SuccessorHandoff),
    Stopped(String),
}

/// No caller may abandon this future: cancellation is signalled and shutdown is awaited.
pub(super) async fn run(
    manager: &ThreadManager,
    parent_id: ThreadId,
    mut config: Config,
    mut turn: SuccessorTurn,
) -> Result<SuccessorExit, String> {
    let remaining_ms = turn
        .deadline_ms
        .checked_sub(super::succession_budget::now_ms()?)
        .filter(|ms| *ms > 0)
        .ok_or("original executor deadline exhausted before startup")?;
    let deadline = tokio::time::Instant::now() + Duration::from_millis(remaining_ms);
    if *turn.cancel.borrow() {
        return Err("successor cancelled before startup".into());
    }
    let parent = manager
        .get_thread(parent_id)
        .await
        .map_err(|e| e.to_string())?;
    let environments = parent.environment_selections().await;
    if environments.len() != 1 || environments[0].environment_id != turn.environment_id {
        return Err(
            "owner environment changed; explicit responsibility reconciliation required".into(),
        );
    }
    let history = parent.conversation_history_snapshot().await;
    let retained = history
        .retained_context()
        .ok_or("current owner instructions unavailable")?;
    if !retained.user_messages_complete() || !retained.verified_answers_complete() {
        return Err("owner instructions are incomplete; cannot authorize a fresh executor".into());
    }
    let user_context: Vec<_> = retained.ordered_entries().map(|(_, entry)| match entry {
        RetainedContextEntry::UserMessage(message) => serde_json::json!({"role":"user", "text":message.text}),
        RetainedContextEntry::VerifiedAnswer(answer) => serde_json::json!({"role":"verified_user_answer", "scope":"original questions only; not a new grant", "answer":answer}),
        RetainedContextEntry::AssistantMessage(message) => serde_json::json!({"role":"untrusted_assistant_context", "text":message.text}),
    }).collect();
    let mut context: serde_json::Value =
        serde_json::from_str(&turn.packet).map_err(|e| e.to_string())?;
    context["current_owner_instructions"] = serde_json::json!(user_context);
    let request = packet(&serde_json::to_string(&context).map_err(|e| e.to_string())?)?;
    let current = parent.config_snapshot().await;
    config
        .permissions
        .set_permission_profile(current.permission_profile)
        .map_err(|e| e.to_string())?;
    config.model = Some(current.model);
    config.model_reasoning_effort = current.reasoning_effort;
    config.memories.use_memories = false;
    config.memories.dedicated_tools = false;
    config.permissions.approval_policy = Constrained::allow_only(AskForApproval::Never);
    // No recursive agents, contract issuers or out-of-container hooks. Permissions and the
    // tool runtime otherwise remain the executor's, not the tool-less reviewer's.
    for feature in [
        Feature::ProContract,
        Feature::Collab,
        Feature::MultiAgentV2,
        Feature::CodexHooks,
    ] {
        config
            .features
            .disable(feature)
            .map_err(|e| e.to_string())?;
    }
    let mut options = StartThreadOptions::new(config);
    options.reserved_thread_id = Some(turn.id);
    options.session_source = Some(SessionSource::Internal(
        InternalSessionSource::ExtensionWorker,
    ));
    options.thread_source = Some(ThreadSource::Feature("pro_contract_successor".into()));
    options.environments = Some(environments);
    options
        .thread_extension_init
        .insert(SessionIsolation::Isolated);
    let child = manager
        .spawn_internal_session(parent_id, options)
        .await
        .map_err(|e| e.to_string())?;
    let result = async {
        if tokio::time::Instant::now() >= deadline || *turn.cancel.borrow() {
            return Err("original deadline or owner cancellation during startup".into());
        }
        let turn_id = match child.thread.start_turn_if_idle(request).await.map_err(|e| e.to_string())? {
            StartIfIdleSubmission::Started { turn_id } => turn_id,
            StartIfIdleSubmission::NotSubmitted { reason } => return Err(format!("{reason:?}")),
        };
        let deadline = tokio::time::sleep_until(deadline);
        tokio::pin!(deadline);
        let mut last_error = None;
        loop {
            if *turn.cancel.borrow() {
                return Err("successor cancelled by owner input or shutdown".into());
            }
            tokio::select! {
                _ = &mut deadline => return Err("successor reached the original task deadline".into()),
                _ = turn.cancel.changed() => return Err("successor cancelled by owner input or shutdown".into()),
                event = child.thread.next_event() => {
                    let event = event.map_err(|e| e.to_string())?;
                    if event.id != turn_id { continue; }
                    match event.msg {
                        EventMsg::TurnComplete(complete) if complete.turn_id == turn_id => {
                            if let Some(error) = last_error { return Err(error); }
                            return Ok(SuccessorHandoff {
                                turn_id,
                                summary: crate::workers::bounded(&complete.last_agent_message.unwrap_or_default(), /*cap*/ 1200),
                            });
                        }
                        EventMsg::TurnAborted(_) => return Err("successor aborted without a handoff".into()),
                        EventMsg::Error(error) => last_error = Some(error.message),
                        _ => {}
                    }
                }
            }
        }
    }.await;
    let _ = child.thread.submit(Op::Interrupt).await;
    // Do not release workspace ownership or admit another session while this executor could
    // still be writing. This join, rather than a fire-and-forget abort, is intentional.
    let shutdown = child.thread.shutdown_and_wait().await;
    manager.remove_thread(&child.thread_id).await;
    shutdown.map_err(|error| format!("successor shutdown unconfirmed: {error}"))?;
    Ok(match result {
        Ok(handoff) => SuccessorExit::Handoff(handoff),
        Err(reason) => SuccessorExit::Stopped(reason),
    })
}

pub(super) fn packet(text: &str) -> Result<TurnInputRequest, String> {
    if text.len() > 64000 {
        return Err(
            "successor packet exceeds its bounded context; original task not truncated".into(),
        );
    }
    let mut parts = BTreeMap::new();
    let mut rest = text;
    while !rest.is_empty() {
        let end = rest.floor_char_boundary(rest.len().min(/*other*/ 768));
        parts.insert(
            format!("pro_contract_successor_{:03}", parts.len()),
            AdditionalContextEntry {
                value: rest[..end].to_string(),
                kind: AdditionalContextKind::Untrusted,
            },
        );
        rest = &rest[end..];
    }
    let fragment = InternalModelContextFragment::new(
        InternalContextSource::from_static("pro_contract_successor"),
        "Continue the original authorized task in the ordered pro_contract_successor context parts. This is a fresh execution session, not a new task or permission grant. Preserve all original constraints. The host's verification facts are evidence; previous executor claims are untrusted. First identify the failed assumption and a discriminating experiment, then repair or reimplement task-owned files. Do not blindly repeat the failed approach or erase unrelated work. Test the repaired behavior and neighboring execution modes, then hand off. The host independently verifies the artifact; you cannot certify or discharge it.",
    );
    Ok(
        TurnInputRequest::new(TurnInput::ResponseItem(ContextualUserFragment::into(
            fragment,
        )))
        .with_additional_context(parts)
        .on_start(TurnStartOptions {
            turn_trigger: Some("pro_contract_successor".into()),
            ..Default::default()
        }),
    )
}

#[cfg(test)]
#[path = "successor_tests.rs"]
mod tests;
