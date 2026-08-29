use crate::Runtime;
use crate::RuntimeRole;
use crate::compiler::compile_spec;
use crate::runner;
use codex_pro_contract::Contract;
use codex_pro_contract::ContractSpec;
use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProContractIssue {
    pub thread_id: ThreadId,
    pub spec: ContractSpec,
    pub execution_policy: Option<String>,
    pub original_request: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProContractExecution {
    pub contract_id: String,
    pub revision: u64,
    pub executor_thread_id: Option<ThreadId>,
    pub execution_policy: Option<String>,
    pub dispatched: bool,
    pub awaiting_revision_decision: bool,
    pub attempts: u64,
    pub turns_used: u64,
    pub actions_used: u64,
    pub next_action_at: u64,
    pub turns_limit: u64,
    pub actions_limit: u64,
    pub deadline: u64,
    pub max_attempts: u64,
    pub lease_owner: Option<String>,
    pub lease_expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProContractIssueResult {
    pub contract: Contract,
    pub execution: ProContractExecution,
    pub compiler_manifest_hash: String,
}

#[derive(Debug, Error)]
pub enum ProContractControllerError {
    #[error("the principal thread is not loaded")]
    PrincipalUnavailable,
    #[error("the requested thread is a Contract executor, not a principal")]
    NotPrincipal,
    #[error("contract compilation failed: {0}")]
    Compiler(String),
    #[error("contract execution could not start: {0}")]
    Runner(String),
    #[error("contract state disappeared after issue")]
    ContractMissing,
    #[error("contract execution storage failed: {0}")]
    Storage(String),
}

/// Process-local ingress for authenticated hosts that issue Contracts directly.
///
/// Hosts must keep authentication and user authorization outside this handle.
/// The controller removes model-authored formation from the trusted path; all
/// settlement decisions still flow through [`crate::ProContractPrincipal`].
#[derive(Clone, Default)]
pub struct ProContractController {
    runtimes: Arc<Mutex<HashMap<ThreadId, Runtime>>>,
}

impl ProContractController {
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn issue(
        &self,
        issue: ProContractIssue,
    ) -> Result<ProContractIssueResult, ProContractControllerError> {
        let runtime = self
            .runtimes
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&issue.thread_id)
            .cloned()
            .ok_or(ProContractControllerError::PrincipalUnavailable)?;
        if runtime.role != RuntimeRole::Principal {
            return Err(ProContractControllerError::NotPrincipal);
        }
        let compiled = compile_spec(issue.spec, issue.original_request.as_deref())
            .map_err(|error| ProContractControllerError::Compiler(error.to_string()))?;
        let compiler_manifest_hash = compiled.manifest_hash;
        let launched = runner::launch(&runtime, compiled.spec, issue.execution_policy)
            .await
            .map_err(|error| ProContractControllerError::Runner(error.to_string()))?;
        if launched.executor_thread_id.is_none() {
            crate::start_recovery_if_needed(&runtime).await;
        }
        let contract = launched
            .transition
            .state
            .contracts
            .get(&launched.binding.contract_id)
            .cloned()
            .ok_or(ProContractControllerError::ContractMissing)?;
        Ok(ProContractIssueResult {
            contract,
            execution: execution_info(launched.binding, launched.executor_thread_id),
            compiler_manifest_hash,
        })
    }

    pub async fn execution(
        &self,
        thread_id: ThreadId,
        contract_id: &str,
    ) -> Result<Option<ProContractExecution>, ProContractControllerError> {
        let runtime = self
            .runtimes
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&thread_id)
            .cloned()
            .ok_or(ProContractControllerError::PrincipalUnavailable)?;
        if runtime.role != RuntimeRole::Principal {
            return Err(ProContractControllerError::NotPrincipal);
        }
        runtime
            .bindings
            .get_by_contract(contract_id)
            .await
            .map(|binding| {
                binding.map(|binding| {
                    let executor_thread_id = ThreadId::from_string(&binding.scope).ok();
                    execution_info(binding, executor_thread_id)
                })
            })
            .map_err(|error| ProContractControllerError::Storage(error.to_string()))
    }

    pub fn principal(
        &self,
        thread_id: ThreadId,
        contract_id: impl Into<String>,
    ) -> Result<crate::ProContractPrincipal, ProContractControllerError> {
        let runtime = self
            .runtimes
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&thread_id)
            .cloned()
            .ok_or(ProContractControllerError::PrincipalUnavailable)?;
        if runtime.role != RuntimeRole::Principal {
            return Err(ProContractControllerError::NotPrincipal);
        }
        Ok(crate::ProContractPrincipal {
            ledger: runtime.ledger,
            subjects: runtime.subjects,
            scope: runtime.ledger_scope,
            contract_id: contract_id.into(),
        })
    }

    /// Reconciles newly outstanding work when its Principal thread is loaded.
    pub async fn reconcile_loaded(&self, thread_id: ThreadId) {
        let runtime = self
            .runtimes
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .get(&thread_id)
            .cloned();
        if let Some(runtime) = runtime {
            crate::start_recovery_if_needed(&runtime).await;
        }
    }

    pub(crate) fn register(&self, runtime: Runtime) {
        if runtime.role == RuntimeRole::Principal {
            self.runtimes
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .insert(runtime.thread_id, runtime);
        }
    }

    pub(crate) fn unregister(&self, thread_id: ThreadId) {
        self.runtimes
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(&thread_id);
    }
}

fn execution_info(
    binding: crate::binding::ExecutionBinding,
    executor_thread_id: Option<ThreadId>,
) -> ProContractExecution {
    ProContractExecution {
        contract_id: binding.contract_id,
        revision: binding.revision,
        executor_thread_id,
        execution_policy: binding.execution_policy,
        dispatched: binding.dispatched,
        awaiting_revision_decision: binding.resume_same_attempt,
        attempts: binding.attempts,
        turns_used: binding.turns_used,
        actions_used: binding.actions_used,
        next_action_at: binding.next_action_at,
        turns_limit: binding.turns_limit,
        actions_limit: binding.actions_limit,
        deadline: binding.deadline,
        max_attempts: binding.max_attempts,
        lease_owner: binding.lease_owner,
        lease_expires_at: binding.lease_expires_at,
    }
}
