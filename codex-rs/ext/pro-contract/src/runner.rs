use crate::ExecutorSeed;
use crate::Runtime;
use crate::RuntimeRole;
use crate::binding::AttemptSchedule;
use crate::binding::ExecutionBinding;
use crate::binding::ExecutionLimits;
use crate::binding::Reservation;
use crate::now_millis;
use codex_core::StartIfIdleSubmission;
use codex_core::StartThreadOptions;
use codex_core::TurnInputRequest;
use codex_extension_api::ExtensionDataInit;
use codex_pro_contract::Command;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Decision;
use codex_pro_contract::Draft;
use codex_pro_contract::INSTITUTION_ACTOR;
use codex_pro_contract::Status;
use codex_pro_contract::Transition;
use codex_pro_contract::hash_spec;
use codex_protocol::ThreadId;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::InternalSessionSource;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadSource;
use codex_protocol::user_input::UserInput;
use thiserror::Error;

const LEASE_HEARTBEAT_MS: u64 = 10_000;

#[derive(Debug)]
pub(crate) struct LaunchResult {
    pub(crate) transition: Transition,
    pub(crate) binding: ExecutionBinding,
    pub(crate) executor_thread_id: Option<ThreadId>,
}

#[derive(Debug, Error)]
pub(crate) enum RunnerError {
    #[error("ProContract executor launcher is unavailable")]
    LauncherUnavailable,
    #[error("ProContract executor configuration is unavailable")]
    ConfigUnavailable,
    #[error("contract proposal is not allowed from an executor thread")]
    ExecutorCannotPropose,
    #[error("contract storage failed: {0}")]
    Storage(String),
    #[error("contract command was rejected: {0}")]
    Rejected(String),
    #[error("contract executor could not start: {0}")]
    Launch(String),
}

pub(crate) async fn launch(
    runtime: &Runtime,
    spec: ContractSpec,
    execution_policy: Option<String>,
) -> Result<LaunchResult, RunnerError> {
    if runtime.role != RuntimeRole::Principal {
        return Err(RunnerError::ExecutorCannotPropose);
    }
    if runtime
        .bindings
        .get(&runtime.thread_scope)
        .await
        .map_err(storage)?
        .is_some()
    {
        return Err(RunnerError::ExecutorCannotPropose);
    }
    let executor_thread_id = ThreadId::new();
    let executor_scope = executor_thread_id.to_string();
    let contract_id = format!("pct_{executor_thread_id}");
    let executor = format!("codex:{executor_thread_id}");
    let spec_hash = hash_spec(&spec).map_err(storage)?;
    let issued = runtime
        .ledger
        .apply(
            &runtime.ledger_scope,
            Command::Issue {
                actor: runtime.issuer.clone(),
                draft: Draft {
                    id: contract_id.clone(),
                    scope: runtime.ledger_scope.clone(),
                    spec: spec.clone(),
                    issuer: runtime.issuer.clone(),
                    executor: executor.clone(),
                    spec_hash,
                },
            },
        )
        .await
        .map_err(storage)?;
    require_accepted(&issued)?;
    runtime
        .bindings
        .bind_once(
            &executor_scope,
            &runtime.ledger_scope,
            &contract_id,
            1,
            execution_policy,
            ExecutionLimits {
                turns: spec.budget.turns,
                actions: spec.budget.actions,
                deadline: spec.budget.deadline,
                max_attempts: spec.resolution.max_attempts,
            },
        )
        .await
        .map_err(storage)?;
    let initial_binding = runtime
        .bindings
        .get(&executor_scope)
        .await
        .map_err(storage)?
        .ok_or_else(|| RunnerError::Storage("execution binding disappeared".to_string()))?;
    let now = now_millis();
    let activate = Command::Activate {
        actor: INSTITUTION_ACTOR.to_string(),
        contract_id: contract_id.clone(),
        revision: 1,
        time: now,
    };
    if !matches!(
        codex_pro_contract::transition(&issued.state, activate.clone()).decision,
        Decision::Accepted
    ) {
        return Ok(LaunchResult {
            transition: issued,
            binding: initial_binding,
            executor_thread_id: None,
        });
    }
    let activated = runtime
        .ledger
        .apply(&runtime.ledger_scope, activate)
        .await
        .map_err(storage)?;
    require_accepted(&activated)?;
    let binding = match runtime
        .bindings
        .begin_attempt(&executor_scope, now_millis())
        .await
        .map_err(storage)?
    {
        Reservation::Reserved(binding) => *binding,
        Reservation::Denied { reason } => {
            if reason.exhausts_contract() {
                let _ = escalate(runtime, &contract_id, reason.message()).await;
            }
            return Err(RunnerError::Rejected(reason.message().to_string()));
        }
    };

    if let Err(error) = spawn_bound_executor(
        runtime,
        executor_thread_id,
        executor_scope,
        contract_id.clone(),
        executor_prompt(&spec, &issued.state, None, None),
        spec.authority.clone(),
    )
    .await
    {
        runtime
            .bindings
            .record_interruption(&contract_id)
            .await
            .map_err(storage)?;
        crate::start_recovery_if_needed(runtime).await;
        tracing::warn!("failed to start Contract executor; scheduling recovery: {error}");
        let binding = runtime
            .bindings
            .get_by_contract(&contract_id)
            .await
            .map_err(storage)?
            .ok_or_else(|| RunnerError::Storage("execution binding disappeared".to_string()))?;
        return Ok(LaunchResult {
            transition: activated,
            binding,
            executor_thread_id: None,
        });
    }
    Ok(LaunchResult {
        transition: activated,
        binding,
        executor_thread_id: Some(executor_thread_id),
    })
}

pub(crate) async fn recover(
    runtime: &Runtime,
    contract: &codex_pro_contract::Contract,
) -> Result<bool, RunnerError> {
    if contract.status == Status::Dormant {
        let state = runtime
            .ledger
            .state(&runtime.ledger_scope)
            .await
            .map_err(storage)?;
        let activate = Command::Activate {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: contract.id.clone(),
            revision: contract.revision,
            time: now_millis(),
        };
        if codex_pro_contract::transition(&state, activate.clone()).decision != Decision::Accepted {
            return Ok(false);
        }
        let transition = runtime
            .ledger
            .apply(&runtime.ledger_scope, activate)
            .await
            .map_err(storage)?;
        require_accepted(&transition)?;
    }
    let executor_thread_id = ThreadId::new();
    let executor_scope = executor_thread_id.to_string();
    let Some(claim) = runtime
        .bindings
        .claim_recovery(&contract.id, &executor_scope, now_millis())
        .await
        .map_err(storage)?
    else {
        return Ok(false);
    };
    let binding = claim.binding;
    let resume_rejected_revision = binding.resume_same_attempt
        && binding.revision == contract.revision
        && contract.pending_revision.is_none();
    let new_attempt = !resume_rejected_revision
        && (!claim.interrupted || binding.attempts == 0 || claim.context_changed);
    if binding.revision != contract.revision {
        runtime
            .bindings
            .revise_contract(
                &contract.id,
                contract.revision,
                ExecutionLimits {
                    turns: contract.spec.budget.turns,
                    actions: contract.spec.budget.actions,
                    deadline: contract.spec.budget.deadline,
                    max_attempts: contract.spec.resolution.max_attempts,
                },
            )
            .await
            .map_err(storage)?;
    }
    if new_attempt {
        if let Reservation::Denied { reason } = runtime
            .bindings
            .begin_attempt(&executor_scope, now_millis())
            .await
            .map_err(storage)?
        {
            runtime
                .bindings
                .abandon_claim(&contract.id)
                .await
                .map_err(storage)?;
            return Err(RunnerError::Rejected(reason.message().to_string()));
        }
    } else {
        runtime
            .bindings
            .resume_attempt(&executor_scope, now_millis())
            .await
            .map_err(storage)?;
    }
    let state = runtime
        .ledger
        .state(&runtime.ledger_scope)
        .await
        .map_err(storage)?;
    let prompt = executor_prompt(
        &contract.spec,
        &state,
        Some(
            "Resume after a transient executor interruption. Inspect and preserve useful work already present in the workspace.",
        ),
        contract
            .challenge
            .as_ref()
            .and_then(|challenge| challenge.summary.as_deref())
            .or_else(|| {
                contract
                    .blocked
                    .as_ref()
                    .map(|blocked| blocked.reason.as_str())
            }),
    );
    if let Err(error) = spawn_bound_executor(
        runtime,
        executor_thread_id,
        executor_scope,
        contract.id.clone(),
        prompt,
        contract.spec.authority.clone(),
    )
    .await
    {
        runtime
            .bindings
            .record_interruption(&contract.id)
            .await
            .map_err(storage)?;
        return Err(error);
    }
    Ok(true)
}

fn spawn_bound_executor<'a>(
    runtime: &'a Runtime,
    executor_thread_id: ThreadId,
    executor_scope: String,
    contract_id: String,
    prompt: String,
    authority: Vec<String>,
) -> std::pin::Pin<Box<dyn std::future::Future<Output = Result<(), RunnerError>> + Send + 'a>> {
    Box::pin(async move {
        let parent_config = runtime
            .executor_config
            .as_ref()
            .ok_or(RunnerError::ConfigUnavailable)?;
        let isolated =
            crate::executor_config::isolated(parent_config, &runtime.environments, &authority)
                .map_err(RunnerError::Launch)?;
        let mut options = StartThreadOptions::new(isolated.config);
        options.session_source = Some(SessionSource::Internal(InternalSessionSource::ProContract));
        options.thread_source = Some(ThreadSource::Feature("pro_contract".to_string()));
        options.environments = Some(isolated.environments);
        options.reserved_thread_id = Some(executor_thread_id);
        let mut init = ExtensionDataInit::new();
        init.insert(ExecutorSeed {
            ledger_scope: runtime.ledger_scope.clone(),
            contract_id: contract_id.clone(),
            issuer: runtime.issuer.clone(),
            authority,
        });
        options.thread_extension_init = init;
        let spawner = runtime
            .executor_spawner
            .as_ref()
            .ok_or(RunnerError::LauncherUnavailable)?;
        let spawned = spawner
            .spawn_internal_session(runtime.thread_id, options)
            .await
            .map_err(|error| RunnerError::Launch(error.to_string()))?;
        if spawned.thread_id != executor_thread_id {
            return Err(RunnerError::Launch(
                "host returned an unexpected executor thread identity".to_string(),
            ));
        }
        let monitor = tokio::spawn(monitor_executor(
            std::sync::Arc::clone(&spawned.thread),
            runtime.clone(),
            executor_scope,
            contract_id,
        ));
        if let Err(error) = start_attempt(&spawned.thread, prompt).await {
            monitor.abort();
            return Err(error);
        }
        Ok(())
    })
}

async fn monitor_executor(
    thread: std::sync::Arc<codex_core::CodexThread>,
    runtime: Runtime,
    executor_scope: String,
    contract_id: String,
) {
    let mut heartbeat = tokio::time::interval(std::time::Duration::from_millis(LEASE_HEARTBEAT_MS));
    heartbeat.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        let event = tokio::select! {
            event = thread.next_event() => match event {
                Ok(event) => event,
                Err(error) => {
                    tracing::warn!("ProContract executor event stream failed: {error}");
                    if let Err(error) = runtime
                        .bindings
                        .record_interruption(&contract_id)
                        .await
                    {
                        tracing::warn!("failed to record Contract interruption: {error}");
                    }
                    crate::start_recovery_if_needed(&runtime).await;
                    return;
                }
            },
            _ = heartbeat.tick() => {
                match runtime.bindings.heartbeat(&executor_scope, now_millis()).await {
                    Ok(true) => continue,
                    Ok(false) => {
                        tracing::warn!("ProContract executor lost its execution lease");
                        return;
                    }
                    Err(error) => {
                        tracing::warn!("failed to heartbeat ProContract executor: {error}");
                        return;
                    }
                }
            }
        };
        if !matches!(
            event.msg,
            EventMsg::TurnComplete(_) | EventMsg::TurnAborted(_)
        ) {
            continue;
        }
        let mut contract = match load_contract(&runtime, &contract_id).await {
            Some(contract) => contract,
            None => return,
        };
        let binding_before_decision = match runtime.bindings.get(&executor_scope).await {
            Ok(Some(binding)) => binding,
            Ok(None) => return,
            Err(error) => {
                tracing::warn!("failed to load Contract continuation fence: {error}");
                return;
            }
        };
        let revision_before_decision = binding_before_decision.revision;
        let awaited_revision_decision =
            contract.pending_revision.is_some() || binding_before_decision.resume_same_attempt;
        let mut next_heartbeat_at = now_millis();
        while contract.pending_revision.is_some() {
            let now = now_millis();
            if now >= contract.spec.budget.deadline {
                let _ = escalate(
                    &runtime,
                    &contract_id,
                    "revision decision deadline exhausted",
                )
                .await;
                return;
            }
            if now >= next_heartbeat_at {
                match runtime.bindings.heartbeat(&executor_scope, now).await {
                    Ok(true) => {
                        next_heartbeat_at = now.saturating_add(LEASE_HEARTBEAT_MS);
                    }
                    Ok(false) => return,
                    Err(error) => {
                        tracing::warn!("failed to heartbeat pending Contract revision: {error}");
                        return;
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
            contract = match load_contract(&runtime, &contract_id).await {
                Some(contract) => contract,
                None => return,
            };
        }
        match contract.status {
            Status::Verification | Status::Discharged | Status::Released | Status::Escalated => {
                if let Err(error) = runtime
                    .bindings
                    .suspend_attempt(&executor_scope, AttemptSchedule::Immediate)
                    .await
                {
                    tracing::warn!("failed to close ProContract execution lease: {error}");
                }
                return;
            }
            Status::Dormant => {
                let activated = runtime
                    .ledger
                    .apply(
                        &runtime.ledger_scope,
                        Command::Activate {
                            actor: INSTITUTION_ACTOR.to_string(),
                            contract_id: contract.id.clone(),
                            revision: contract.revision,
                            time: now_millis(),
                        },
                    )
                    .await;
                if !matches!(
                    activated,
                    Ok(Transition {
                        decision: Decision::Accepted,
                        ..
                    })
                ) {
                    return;
                }
            }
            Status::Active => {}
        }
        let revision_accepted = contract.revision != revision_before_decision;
        if awaited_revision_decision && !revision_accepted {
            if let Err(error) = runtime
                .bindings
                .resume_attempt(&executor_scope, now_millis())
                .await
            {
                tracing::warn!("failed to resume Contract attempt: {error}");
                let _ = escalate(&runtime, &contract_id, "attempt resume failed").await;
                return;
            }
            if let Err(error) = start_attempt(
                &thread,
                "The Principal rejected the proposed revision. Continue the same semantic attempt under the original Contract and call contract_report_ready or contract_report_blocked."
                    .to_string(),
            )
            .await
            {
                tracing::warn!("failed to resume Contract continuation: {error}");
                let _ = escalate(&runtime, &contract_id, "continuation dispatch failed").await;
                return;
            }
            continue;
        }
        let next_action_at = now_millis().saturating_add(contract.spec.resolution.retry_delay_ms);
        if let Err(error) = runtime
            .bindings
            .suspend_attempt(&executor_scope, AttemptSchedule::At(next_action_at))
            .await
        {
            tracing::warn!("failed to schedule Contract retry: {error}");
            let _ = escalate(&runtime, &contract_id, "retry scheduling failed").await;
            return;
        }
        if contract.spec.resolution.retry_delay_ms > 0 {
            tokio::time::sleep(std::time::Duration::from_millis(
                contract.spec.resolution.retry_delay_ms,
            ))
            .await;
        }
        let binding = match runtime.bindings.get(&executor_scope).await {
            Ok(Some(binding)) => binding,
            Ok(None) => return,
            Err(error) => {
                tracing::warn!("failed to load Contract binding: {error}");
                return;
            }
        };
        if binding.revision != contract.revision
            && let Err(error) = runtime
                .bindings
                .revise_contract(
                    &contract_id,
                    contract.revision,
                    ExecutionLimits {
                        turns: contract.spec.budget.turns,
                        actions: contract.spec.budget.actions,
                        deadline: contract.spec.budget.deadline,
                        max_attempts: contract.spec.resolution.max_attempts,
                    },
                )
                .await
        {
            tracing::warn!("failed to revise Contract binding: {error}");
            let _ = escalate(&runtime, &contract_id, "binding revision failed").await;
            return;
        }
        let executor_thread_id = ThreadId::new();
        let next_scope = executor_thread_id.to_string();
        match runtime
            .bindings
            .begin_new_attempt(&contract_id, &next_scope, now_millis())
            .await
        {
            Ok(Reservation::Reserved(_)) => {}
            Ok(Reservation::Denied { reason }) => {
                if reason.exhausts_contract() {
                    let _ = escalate(&runtime, &contract_id, reason.message()).await;
                }
                return;
            }
            Err(error) => {
                tracing::warn!("failed to reserve Contract attempt: {error}");
                let _ = escalate(&runtime, &contract_id, "attempt reservation failed").await;
                return;
            }
        }
        let state = match runtime.ledger.state(&runtime.ledger_scope).await {
            Ok(state) => state,
            Err(error) => {
                tracing::warn!("failed to load Contract continuation context: {error}");
                return;
            }
        };
        let Some(current) = state.contracts.get(&contract_id) else {
            return;
        };
        let challenge = current
            .challenge
            .as_ref()
            .and_then(|challenge| challenge.summary.as_deref())
            .or_else(|| {
                current
                    .blocked
                    .as_ref()
                    .map(|blocked| blocked.reason.as_str())
            });
        let continuation = challenge.map(|_| {
            "This is a residual-targeted continuation, not a new BROAD phase. Inspect the existing candidate and regression artifacts first, preserve acquired behavior, and repair the disclosed residual before opening new exploration."
        });
        let prompt = executor_prompt(&current.spec, &state, continuation, challenge);
        if let Err(error) = spawn_bound_executor(
            &runtime,
            executor_thread_id,
            next_scope,
            contract_id.clone(),
            prompt,
            current.spec.authority.clone(),
        )
        .await
        {
            tracing::warn!("failed to start fresh Contract attempt: {error}");
            let _ = runtime.bindings.record_interruption(&contract_id).await;
            crate::start_recovery_if_needed(&runtime).await;
        }
        return;
    }
}

async fn load_contract(
    runtime: &Runtime,
    contract_id: &str,
) -> Option<codex_pro_contract::Contract> {
    match runtime.ledger.state(&runtime.ledger_scope).await {
        Ok(state) => state.contracts.get(contract_id).cloned(),
        Err(error) => {
            tracing::warn!("failed to read Contract after executor turn: {error}");
            None
        }
    }
}

async fn start_attempt(
    thread: &codex_core::CodexThread,
    prompt: String,
) -> Result<(), RunnerError> {
    match thread
        .start_turn_if_idle(TurnInputRequest::user_input(vec![UserInput::Text {
            text: prompt,
            text_elements: Vec::new(),
        }]))
        .await
        .map_err(|error| RunnerError::Launch(error.to_string()))?
    {
        StartIfIdleSubmission::Started { .. } => Ok(()),
        StartIfIdleSubmission::NotSubmitted { reason } => Err(RunnerError::Launch(format!(
            "executor prompt was not submitted: {reason:?}"
        ))),
    }
}

async fn escalate(runtime: &Runtime, contract_id: &str, reason: &str) -> Result<(), RunnerError> {
    let state = runtime
        .ledger
        .state(&runtime.ledger_scope)
        .await
        .map_err(storage)?;
    let contract = state
        .contracts
        .get(contract_id)
        .ok_or_else(|| RunnerError::Storage("contract not found".to_string()))?;
    let transition = runtime
        .ledger
        .apply(
            &runtime.ledger_scope,
            Command::Escalate {
                actor: INSTITUTION_ACTOR.to_string(),
                contract_id: contract.id.clone(),
                revision: contract.revision,
                reason: reason.to_string(),
                time: now_millis(),
            },
        )
        .await
        .map_err(storage)?;
    require_accepted(&transition)
}

fn executor_prompt(
    spec: &ContractSpec,
    state: &codex_pro_contract::State,
    recovery: Option<&str>,
    challenge: Option<&str>,
) -> String {
    let mut sections = vec![if spec.brief.is_empty() {
        spec.goal.clone()
    } else {
        spec.brief.clone()
    }];
    if let Some(recovery) = recovery {
        sections.push(recovery.to_string());
    }
    sections.extend(spec.requires.iter().filter_map(|requirement| {
        state
            .contracts
            .get(&requirement.contract_id)
            .map(|dependency| {
                let summary = dependency
                    .handoff
                    .as_ref()
                    .map_or("", |handoff| handoff.summary.as_str());
                format!(
                    "Verified prerequisite: {}{}",
                    dependency.spec.goal,
                    if summary.is_empty() {
                        String::new()
                    } else {
                        format!("\n{summary}")
                    }
                )
            })
    }));
    if let Some(challenge) = challenge {
        sections.push(format!("Prior blocker or verifier challenge:\n{challenge}"));
    }
    sections.push("When ready, call contract_report_ready with completed checks and material uncertainties. If blocked, call contract_report_blocked. If the approved terms must change, call contract_propose_revision. A handoff is not settlement.".to_string());
    sections.join("\n\n")
}

fn require_accepted(transition: &Transition) -> Result<(), RunnerError> {
    match &transition.decision {
        Decision::Accepted => Ok(()),
        Decision::Rejected { reason } => Err(RunnerError::Rejected(reason.clone())),
    }
}

fn storage(error: impl std::fmt::Display) -> RunnerError {
    RunnerError::Storage(error.to_string())
}
