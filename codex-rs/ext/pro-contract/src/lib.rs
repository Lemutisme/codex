//! Codex lifecycle adapter for the ProContract settlement kernel.

mod binding;
mod principal;
mod tool;

use binding::BindingStore;
use codex_core::context::ProContractExecutionPolicy;
use codex_extension_api::ContextContributor;
use codex_extension_api::ContextualUserFragment;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::PromptFragment;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolContributor;
use codex_extension_api::ToolExecutor;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_pro_contract::Ledger;
use codex_pro_contract::SubjectStore;
use codex_state::SqliteConfig;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

pub use principal::PrincipalError;
pub use principal::ProContractPrincipal;
use tool::ContractTool;
use tool::ToolKind;

#[derive(Clone, Debug)]
pub struct ProContractExtensionConfig {
    pub enabled: bool,
    pub sqlite: SqliteConfig,
}

#[derive(Clone)]
struct Runtime {
    ledger: Ledger,
    bindings: BindingStore,
    subjects: SubjectStore,
    scope: String,
    contract_id: String,
    issuer: String,
    executor: String,
    policy_projected: Arc<AtomicBool>,
}

#[derive(Clone)]
struct Extension<C> {
    config: Arc<dyn Fn(&C) -> ProContractExtensionConfig + Send + Sync>,
}

impl<C> ThreadLifecycleContributor<C> for Extension<C>
where
    C: Send + Sync + 'static,
{
    fn on_thread_start<'a>(&'a self, input: ThreadStartInput<'a, C>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let config = (self.config)(input.config);
            if !config.enabled || !input.persistent_thread_state_available {
                return;
            }
            let scope = input.thread_store.level_id().to_string();
            let (ledger, bindings) = match open_stores(&config.sqlite).await {
                Ok(stores) => stores,
                Err(error) => {
                    tracing::warn!("failed to initialize ProContract ledger: {error}");
                    return;
                }
            };
            input.thread_store.insert(Runtime {
                ledger,
                bindings,
                subjects: SubjectStore::new(config.sqlite.home().join("pro-contract-subjects")),
                contract_id: format!("pct_{scope}"),
                issuer: format!("principal:{scope}"),
                executor: format!("codex:{scope}"),
                policy_projected: Arc::new(AtomicBool::new(false)),
                scope,
            });
        })
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
            if runtime.policy_projected.load(Ordering::Acquire) {
                return Vec::new();
            }
            let binding = match runtime.bindings.get(&runtime.scope).await {
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
        let binding = match runtime.bindings.get(&runtime.scope).await {
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
    ) -> Vec<Arc<dyn ToolExecutor<ToolCall>>> {
        let Some(runtime) = thread_store.get::<Runtime>() else {
            return Vec::new();
        };
        ToolKind::ALL
            .into_iter()
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

async fn open_stores(sqlite: &SqliteConfig) -> Result<(Ledger, BindingStore), PrincipalError> {
    let pool = sqlite
        .open_read_write_pool(&sqlite.home().join("pro_contract_1.sqlite"))
        .await?;
    let bindings = BindingStore::initialize(pool.clone())
        .await
        .map_err(|error| PrincipalError::Binding(error.to_string()))?;
    let ledger = Ledger::initialize(pool).await?;
    Ok((ledger, bindings))
}

pub fn install<C>(
    registry: &mut ExtensionRegistryBuilder<C>,
    config: impl Fn(&C) -> ProContractExtensionConfig + Send + Sync + 'static,
) where
    C: Send + Sync + 'static,
{
    let extension = Arc::new(Extension {
        config: Arc::new(config),
    });
    registry.thread_lifecycle_contributor(extension.clone());
    registry.prompt_contributor(extension.clone());
    registry.turn_input_contributor(extension.clone());
    registry.tool_contributor(extension);
}

#[cfg(test)]
#[path = "tests.rs"]
mod tests;
