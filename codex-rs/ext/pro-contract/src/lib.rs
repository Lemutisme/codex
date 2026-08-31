//! Codex lifecycle adapter for the ProContract settlement kernel.

mod binding;
mod compiler;
mod controller;
mod principal;
mod replay;
mod runner;
mod tool;
mod tool_spec;

use binding::BindingStore;
use binding::Reservation;
use codex_core::NewThread;
use codex_core::StartThreadOptions;
use codex_core::config::Config;
use codex_core::context::ProContractExecutionPolicy;
use codex_exec_server::EnvironmentManager;
use codex_extension_api::ContextContributor;
use codex_extension_api::ContextualUserFragment;
use codex_extension_api::ExecutionAdmission;
use codex_extension_api::ExecutionAdmissionContributor;
use codex_extension_api::ExecutionPermit;
use codex_extension_api::ExecutionReminder;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::InternalSessionSpawner;
use codex_extension_api::PromptFragment;
use codex_extension_api::SamplingAdmissionInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadReadyInput;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ThreadStopInput;
use codex_extension_api::ToolAdmissionInput;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolContributor;
use codex_extension_api::ToolExecutor;
use codex_extension_api::ToolVisibility;
use codex_extension_api::ToolVisibilityInput;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_pro_contract::Command;
use codex_pro_contract::INSTITUTION_ACTOR;
use codex_pro_contract::Ledger;
use codex_pro_contract::Status;
use codex_pro_contract::SubjectStore;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::protocol::InternalSessionSource;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::TurnEnvironmentSelection;
use codex_state::SqliteConfig;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const SETTLEMENT_WINDOW: u64 = 20;
const MAX_PROVIDER_TURN_MS: u64 = 15 * 60 * 1_000;
const SETTLEMENT_REMINDER: &str = "Settlement window active. Stop opening speculative work; petition verification when the evidence policy can adjudicate its claim, otherwise report blocked or petition revision.";

pub use controller::ProContractController;
pub use controller::ProContractControllerError;
pub use controller::ProContractExecution;
pub use controller::ProContractIssue;
pub use controller::ProContractIssueResult;
pub use principal::PrincipalAttestation;
pub use principal::PrincipalChallenge;
pub use principal::PrincipalContractCoordinate;
pub use principal::PrincipalError;
pub use principal::PrincipalRevisionDecision;
pub use principal::ProContractPrincipal;
pub use principal::RevisionDecision;
use tool::ContractTool;
use tool::ToolKind;

#[derive(Clone, Debug)]
pub struct ProContractExtensionConfig {
    pub enabled: bool,
    pub sqlite: SqliteConfig,
    pub environment_manager: Arc<EnvironmentManager>,
    pub executor_config: Config,
    pub proposal_mode: ProContractProposalMode,
}

/// Selects whether a host exposes model-authored Contract formation.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum ProContractProposalMode {
    /// Only an authenticated host controller may issue Contracts.
    #[default]
    PrincipalOnly,
    /// The host has independently authorized model proposals before installation.
    HostApprovedModelTool,
}

type ExecutorSpawner =
    dyn InternalSessionSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>;

#[derive(Clone)]
struct ExecutorSeed {
    ledger_scope: String,
    contract_id: String,
    issuer: String,
    authority: Vec<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RuntimeRole {
    Principal,
    Executor,
}

#[derive(Clone, Copy)]
struct ContractExecutorThread;

#[derive(Clone)]
struct Runtime {
    ledger: Ledger,
    bindings: BindingStore,
    subjects: SubjectStore,
    environment_manager: Arc<EnvironmentManager>,
    replay_reports: std::path::PathBuf,
    executor_config: Option<Config>,
    environments: Vec<TurnEnvironmentSelection>,
    executor_spawner: Option<Arc<ExecutorSpawner>>,
    thread_id: ThreadId,
    ledger_scope: String,
    thread_scope: String,
    contract_id: String,
    issuer: String,
    role: RuntimeRole,
    policy_projected: Arc<AtomicBool>,
    recovery_started: Arc<AtomicBool>,
    settlement_reminder_projected: Arc<AtomicBool>,
    proposal_mode: ProContractProposalMode,
    authority: Vec<String>,
}

#[derive(Clone)]
struct Extension<C> {
    config: Arc<dyn Fn(&C) -> ProContractExtensionConfig + Send + Sync>,
    executor_spawner: Arc<ExecutorSpawner>,
    owner: String,
    controller: ProContractController,
}

impl<C> ThreadLifecycleContributor<C> for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let config = (self.config)(input.config);
            let seed = input.thread_store.get::<ExecutorSeed>();
            let executor_thread = seed.is_some()
                || matches!(
                    input.session_source,
                    SessionSource::Internal(InternalSessionSource::ProContract)
                );
            if executor_thread {
                input.thread_store.insert(ContractExecutorThread);
            }
            if !config.enabled || !input.persistent_thread_state_available {
                return;
            }
            let thread_scope = input.thread_store.level_id().to_string();
            let Ok(thread_id) = ThreadId::from_string(&thread_scope) else {
                tracing::warn!("ProContract requires a UUID thread identity");
                return;
            };
            let (ledger, bindings) = match open_stores(&config.sqlite, &self.owner).await {
                Ok(stores) => stores,
                Err(error) => {
                    tracing::warn!("failed to initialize ProContract ledger: {error}");
                    return;
                }
            };
            let (ledger_scope, contract_id, issuer, role, authority) = if let Some(seed) = seed {
                (
                    seed.ledger_scope.clone(),
                    seed.contract_id.clone(),
                    seed.issuer.clone(),
                    RuntimeRole::Executor,
                    seed.authority.clone(),
                )
            } else if executor_thread {
                match bindings.for_session(&thread_scope).await {
                    Ok(Some(bound)) => {
                        let (issuer, authority) = match ledger.state(&bound.ledger_scope).await {
                            Ok(state) => state.contracts.get(&bound.contract_id).map_or_else(
                                || (String::new(), Vec::new()),
                                |contract| {
                                    (contract.issuer.clone(), contract.spec.authority.clone())
                                },
                            ),
                            Err(error) => {
                                tracing::warn!(
                                    "failed to recover ProContract executor identity: {error}"
                                );
                                (String::new(), Vec::new())
                            }
                        };
                        (
                            bound.ledger_scope,
                            bound.contract_id,
                            issuer,
                            RuntimeRole::Executor,
                            authority,
                        )
                    }
                    Ok(None) => (
                        thread_scope.clone(),
                        format!("pct_unbound_{thread_scope}"),
                        String::new(),
                        RuntimeRole::Executor,
                        Vec::new(),
                    ),
                    Err(error) => {
                        tracing::warn!("failed to locate ProContract executor binding: {error}");
                        (
                            thread_scope.clone(),
                            format!("pct_unbound_{thread_scope}"),
                            String::new(),
                            RuntimeRole::Executor,
                            Vec::new(),
                        )
                    }
                }
            } else {
                (
                    thread_scope.clone(),
                    format!("pct_{thread_scope}"),
                    format!("principal:{thread_scope}"),
                    RuntimeRole::Principal,
                    Vec::new(),
                )
            };
            let runtime = Runtime {
                ledger,
                bindings,
                subjects: SubjectStore::new(config.sqlite.home().join("pro-contract-subjects")),
                environment_manager: config.environment_manager,
                replay_reports: config.sqlite.home().join("pro-contract-replay"),
                executor_config: Some(config.executor_config),
                environments: input.environments.to_vec(),
                executor_spawner: Some(Arc::clone(&self.executor_spawner)),
                thread_id,
                contract_id,
                issuer,
                role,
                policy_projected: Arc::new(AtomicBool::new(false)),
                recovery_started: Arc::new(AtomicBool::new(false)),
                settlement_reminder_projected: Arc::new(AtomicBool::new(false)),
                proposal_mode: config.proposal_mode,
                authority,
                ledger_scope,
                thread_scope,
            };
            self.controller.register(runtime.clone());
            input.thread_store.insert(runtime);
        })
    }

    fn on_thread_ready<'a>(&'a self, input: ThreadReadyInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let Some(runtime) = input.thread_store.get::<Runtime>() else {
                return;
            };
            start_recovery_if_needed(runtime.as_ref()).await;
        })
    }

    fn on_thread_stop<'a>(&'a self, input: ThreadStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(runtime) = input.thread_store.get::<Runtime>() {
                self.controller.unregister(runtime.thread_id);
            }
        })
    }
}

async fn start_recovery_if_needed(runtime: &Runtime) {
    if runtime.role != RuntimeRole::Principal
        || runtime.recovery_started.swap(true, Ordering::AcqRel)
    {
        return;
    }
    let state = match runtime.ledger.state(&runtime.ledger_scope).await {
        Ok(state) => state,
        Err(error) => {
            tracing::warn!("failed to inspect ProContract recovery state: {error}");
            runtime.recovery_started.store(false, Ordering::Release);
            return;
        }
    };
    if state.contracts.values().any(|contract| {
        contract.scope == runtime.ledger_scope
            && matches!(contract.status, Status::Dormant | Status::Active)
    }) {
        tokio::spawn(recovery_loop(runtime.clone()));
    } else {
        runtime.recovery_started.store(false, Ordering::Release);
    }
}

struct RecoveryGuard(Arc<AtomicBool>);

impl Drop for RecoveryGuard {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

async fn recovery_loop(runtime: Runtime) {
    let _guard = RecoveryGuard(Arc::clone(&runtime.recovery_started));
    loop {
        let state = match runtime.ledger.state(&runtime.ledger_scope).await {
            Ok(state) => state,
            Err(error) => {
                tracing::warn!("failed to read ProContract recovery state: {error}");
                return;
            }
        };
        let candidates = state
            .contracts
            .values()
            .filter(|contract| {
                contract.scope == runtime.ledger_scope
                    && matches!(contract.status, Status::Dormant | Status::Active)
                    && contract.pending_revision.is_none()
            })
            .cloned()
            .collect::<Vec<_>>();
        if candidates.is_empty() {
            return;
        }
        for contract in candidates {
            if now_millis() >= contract.spec.budget.deadline {
                let _ = runtime
                    .ledger
                    .apply(
                        &runtime.ledger_scope,
                        Command::Escalate {
                            actor: INSTITUTION_ACTOR.to_string(),
                            contract_id: contract.id,
                            revision: contract.revision,
                            reason: "contract deadline exhausted during recovery".to_string(),
                            time: now_millis(),
                        },
                    )
                    .await;
                continue;
            }
            match runtime.bindings.get_by_contract(&contract.id).await {
                Ok(Some(_)) => {}
                Ok(None) => {
                    let _ = runtime
                        .ledger
                        .apply(
                            &runtime.ledger_scope,
                            Command::Escalate {
                                actor: INSTITUTION_ACTOR.to_string(),
                                contract_id: contract.id,
                                revision: contract.revision,
                                reason: "contract execution binding is missing".to_string(),
                                time: now_millis(),
                            },
                        )
                        .await;
                    continue;
                }
                Err(error) => {
                    tracing::warn!("failed to inspect ProContract execution binding: {error}");
                    continue;
                }
            }
            if let Err(error) = runner::recover(&runtime, &contract).await {
                tracing::warn!("failed to recover ProContract executor: {error}");
            }
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
}

impl<C> ContextContributor for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn contribute_thread_context<'a>(
        &'a self,
        _session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
    ) -> ExtensionFuture<'a, Vec<PromptFragment>> {
        execution_policy_fragments(thread_store)
    }
}

impl<C> ExecutionAdmissionContributor for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn tool_visibility(&self, input: ToolVisibilityInput<'_>) -> ToolVisibility {
        let Some(runtime) = input.thread_store.get::<Runtime>() else {
            return if input.thread_store.get::<ContractExecutorThread>().is_some() {
                ToolVisibility::Hidden
            } else {
                ToolVisibility::Inherit
            };
        };
        if runtime.role == RuntimeRole::Principal
            || settlement_tool(input.tool_name.name.as_str())
            || authorized_tool(&runtime.authority, input.tool_name)
        {
            ToolVisibility::Inherit
        } else {
            ToolVisibility::Hidden
        }
    }

    fn admit_sampling<'a>(
        &'a self,
        input: SamplingAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        Box::pin(async move {
            let Some(runtime) = input.thread_store.get::<Runtime>() else {
                return if input.thread_store.get::<ContractExecutorThread>().is_some() {
                    deny("contract execution state is unavailable")
                } else {
                    ExecutionAdmission::Permit(ExecutionPermit::default())
                };
            };
            let binding = match runtime_binding(&runtime).await {
                Ok(Some(binding)) => binding,
                Ok(None) if runtime.role == RuntimeRole::Principal => {
                    return ExecutionAdmission::Permit(ExecutionPermit::default());
                }
                Ok(None) => return deny("contract executor binding is no longer current"),
                Err(error) => return admission_error("read execution binding", error),
            };
            let state = match runtime.ledger.state(&runtime.ledger_scope).await {
                Ok(state) => state,
                Err(error) => return admission_error("read contract state", error),
            };
            let Some(contract) = state.contracts.get(&binding.contract_id) else {
                return deny("contract execution binding has no contract");
            };
            if contract.status != Status::Active
                || contract.revision != binding.revision
                || contract.pending_revision.is_some()
            {
                return deny("contract is not active at the bound revision");
            }
            let now = now_millis();
            match runtime
                .bindings
                .reserve_turn(&runtime.thread_scope, now)
                .await
            {
                Ok(Reservation::Reserved(binding)) => {
                    let settlement_window = binding.turns_limit.saturating_sub(binding.turns_used)
                        <= SETTLEMENT_WINDOW
                        || binding.actions_limit.saturating_sub(binding.actions_used)
                            <= SETTLEMENT_WINDOW;
                    let reminders = if settlement_window
                        && !runtime
                            .settlement_reminder_projected
                            .swap(true, Ordering::AcqRel)
                    {
                        ExecutionReminder::new(
                            SETTLEMENT_REMINDER,
                            codex_protocol::models::ContentItemKind(
                                "pro_contract.settlement_window".to_string(),
                            ),
                        )
                        .into_iter()
                        .collect()
                    } else {
                        Vec::new()
                    };
                    ExecutionAdmission::Permit(ExecutionPermit {
                        valid_until: Some(
                            binding
                                .deadline
                                .min(now.saturating_add(MAX_PROVIDER_TURN_MS)),
                        ),
                        reminders,
                    })
                }
                Ok(Reservation::Denied { reason }) => {
                    if reason.exhausts_contract()
                        && let Err(error) = runtime
                            .ledger
                            .apply(
                                &runtime.ledger_scope,
                                Command::Escalate {
                                    actor: INSTITUTION_ACTOR.to_string(),
                                    contract_id: contract.id.clone(),
                                    revision: contract.revision,
                                    reason: reason.message().to_string(),
                                    time: now_millis(),
                                },
                            )
                            .await
                    {
                        tracing::warn!("failed to escalate exhausted ProContract: {error}");
                    }
                    deny(reason.message())
                }
                Err(error) => admission_error("reserve provider turn", error),
            }
        })
    }

    fn admit_tool<'a>(
        &'a self,
        input: ToolAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        Box::pin(async move {
            let Some(runtime) = input.thread_store.get::<Runtime>() else {
                return if input.thread_store.get::<ContractExecutorThread>().is_some() {
                    deny("contract execution state is unavailable")
                } else {
                    ExecutionAdmission::Permit(ExecutionPermit::default())
                };
            };
            let binding = match runtime_binding(&runtime).await {
                Ok(Some(binding)) => binding,
                Ok(None) if runtime.role == RuntimeRole::Principal => {
                    return ExecutionAdmission::Permit(ExecutionPermit::default());
                }
                Ok(None) => return deny("contract executor binding is no longer current"),
                Err(error) => return admission_error("read execution binding", error),
            };
            let state = match runtime.ledger.state(&runtime.ledger_scope).await {
                Ok(state) => state,
                Err(error) => return admission_error("read contract state", error),
            };
            let Some(contract) = state.contracts.get(&binding.contract_id) else {
                return deny("contract execution binding has no contract");
            };
            if contract.status != Status::Active
                || contract.revision != binding.revision
                || contract.pending_revision.is_some()
            {
                return deny("contract is not active at the bound revision");
            }
            if settlement_tool(input.tool_name.name.as_str()) {
                return ExecutionAdmission::Permit(ExecutionPermit::default());
            }
            if !authorized_tool(&contract.spec.authority, input.tool_name) {
                return deny("contract authority does not permit this tool");
            }
            match runtime
                .bindings
                .reserve_action(&runtime.thread_scope, now_millis())
                .await
            {
                Ok(Reservation::Reserved(_)) => {
                    ExecutionAdmission::Permit(ExecutionPermit::default())
                }
                Ok(Reservation::Denied { reason }) => {
                    if reason.exhausts_contract()
                        && let Err(error) = runtime
                            .ledger
                            .apply(
                                &runtime.ledger_scope,
                                Command::Escalate {
                                    actor: INSTITUTION_ACTOR.to_string(),
                                    contract_id: contract.id.clone(),
                                    revision: contract.revision,
                                    reason: reason.message().to_string(),
                                    time: now_millis(),
                                },
                            )
                            .await
                    {
                        tracing::warn!("failed to escalate exhausted ProContract: {error}");
                    }
                    deny(reason.message())
                }
                Err(error) => admission_error("reserve contract action", error),
            }
        })
    }
}

async fn runtime_binding(
    runtime: &Runtime,
) -> Result<Option<binding::ExecutionBinding>, binding::BindingError> {
    runtime.bindings.get(&runtime.thread_scope).await
}

fn settlement_tool(name: &str) -> bool {
    matches!(
        name,
        "contract_status"
            | "contract_report_ready"
            | "contract_report_blocked"
            | "contract_propose_revision"
            | "update_plan"
            | "tool_search"
    )
}

fn authorized_tool(authority: &[String], tool_name: &codex_extension_api::ToolName) -> bool {
    let required = match tool_name.name.as_str() {
        "apply_patch" => "filesystem.write",
        "exec_command" | "write_stdin" => "process.execute",
        "view_image" => "filesystem.read",
        "web_search" => "network.access",
        name => {
            let exact = format!("tool:{name}");
            return authority.iter().any(|capability| capability == &exact);
        }
    };
    authority.iter().any(|capability| capability == required)
}

fn deny(reason: &str) -> ExecutionAdmission {
    ExecutionAdmission::Deny {
        reason: reason.to_string(),
    }
}

fn admission_error(operation: &str, error: impl std::fmt::Display) -> ExecutionAdmission {
    tracing::warn!("failed to {operation}: {error}");
    deny("contract execution admission is unavailable")
}

pub(crate) fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_millis() as u64)
}

impl<C> TurnInputContributor for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn contribute<'a>(
        &'a self,
        _input: TurnInputContext,
        _extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
        _session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        _turn_store: &'a ExtensionData,
    ) -> ExtensionFuture<'a, Vec<Box<dyn ContextualUserFragment + Send>>> {
        Box::pin(async move {
            let Some(runtime) = thread_store.get::<Runtime>() else {
                return Vec::new();
            };
            start_recovery_if_needed(runtime.as_ref()).await;
            if runtime.policy_projected.load(Ordering::Acquire) {
                return Vec::new();
            }
            let binding = match runtime.bindings.get(&runtime.thread_scope).await {
                Ok(binding) => binding,
                Err(error) => {
                    tracing::warn!("failed to read ProContract execution binding: {error}");
                    return Vec::new();
                }
            };
            let Some(policy) = binding.and_then(|binding| binding.execution_policy) else {
                return Vec::new();
            };
            if runtime.policy_projected.swap(true, Ordering::AcqRel) {
                return Vec::new();
            }
            vec![Box::new(ProContractExecutionPolicy::new(policy))
                as Box<dyn ContextualUserFragment + Send>]
        })
    }
}

fn execution_policy_fragments(
    thread_store: &ExtensionData,
) -> ExtensionFuture<'_, Vec<PromptFragment>> {
    Box::pin(async move {
        let Some(runtime) = thread_store.get::<Runtime>() else {
            return Vec::new();
        };
        let binding = match runtime.bindings.get(&runtime.thread_scope).await {
            Ok(binding) => binding,
            Err(error) => {
                tracing::warn!("failed to read ProContract execution binding: {error}");
                return Vec::new();
            }
        };
        let Some(policy) = binding.and_then(|binding| binding.execution_policy) else {
            return Vec::new();
        };
        runtime.policy_projected.store(true, Ordering::Release);
        let fragment = ProContractExecutionPolicy::new(policy);
        vec![PromptFragment::developer_policy(
            fragment.render(),
            fragment.content_kind(),
        )]
    })
}

impl<C> ToolContributor for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn tools(
        &self,
        _session_store: &ExtensionData,
        thread_store: &ExtensionData,
    ) -> Vec<Arc<dyn for<'call> ToolExecutor<ToolCall<'call>>>> {
        let Some(runtime) = thread_store.get::<Runtime>() else {
            return Vec::new();
        };
        ToolKind::for_runtime(runtime.role, runtime.proposal_mode)
            .iter()
            .copied()
            .map(|kind| Arc::new(ContractTool::new(kind, runtime.clone())) as Arc<_>)
            .collect()
    }
}

async fn open_ledger(sqlite: &SqliteConfig) -> Result<Ledger, PrincipalError> {
    let pool = sqlite
        .open_read_write_pool(&sqlite.home().join("pro_contract_1.sqlite"))
        .await?;
    Ledger::initialize(pool).await.map_err(Into::into)
}

async fn open_stores(
    sqlite: &SqliteConfig,
    owner: &str,
) -> Result<(Ledger, BindingStore), PrincipalError> {
    let pool = sqlite
        .open_read_write_pool(&sqlite.home().join("pro_contract_1.sqlite"))
        .await?;
    let ledger = Ledger::initialize(pool.clone()).await?;
    let bindings = BindingStore::initialize(pool.clone(), owner)
        .await
        .map_err(|error| PrincipalError::Binding(error.to_string()))?;
    Ok((ledger, bindings))
}

pub fn install<C, S>(
    registry: &mut ExtensionRegistryBuilder<C>,
    config: impl Fn(&C) -> ProContractExtensionConfig + Send + Sync + 'static,
    executor_spawner: S,
) where
    C: Send + Sync + 'static,
    S: InternalSessionSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr> + 'static,
{
    install_with_controller(
        registry,
        config,
        executor_spawner,
        ProContractController::new(),
    );
}

pub fn install_with_controller<C, S>(
    registry: &mut ExtensionRegistryBuilder<C>,
    config: impl Fn(&C) -> ProContractExtensionConfig + Send + Sync + 'static,
    executor_spawner: S,
    controller: ProContractController,
) where
    C: Send + Sync + 'static,
    S: InternalSessionSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr> + 'static,
{
    let extension = Arc::new(Extension {
        config: Arc::new(config),
        executor_spawner: Arc::new(executor_spawner),
        owner: ThreadId::new().to_string(),
        controller,
    });
    registry.thread_lifecycle_contributor(extension.clone());
    registry.execution_admission_contributor(extension.clone());
    registry.prompt_contributor(extension.clone());
    registry.turn_input_contributor(extension.clone());
    registry.tool_contributor(extension);
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;

#[cfg(test)]
#[path = "replay_integration_tests.rs"]
mod replay_integration_tests;
