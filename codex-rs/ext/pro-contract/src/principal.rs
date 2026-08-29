use crate::open_ledger;
use codex_pro_contract::Attestation;
use codex_pro_contract::Command;
use codex_pro_contract::Decision;
use codex_pro_contract::Ledger;
use codex_pro_contract::LedgerError;
use codex_pro_contract::State;
use codex_pro_contract::SubjectCoordinate;
use codex_pro_contract::SubjectStore;
use codex_pro_contract::Transition;
use codex_state::SqliteConfig;
use std::path::PathBuf;
use thiserror::Error;

/// Model-invisible authority for independent settlement and challenge.
///
/// Hosts give this handle only to the Principal/evaluator. Executor tools do
/// not expose either operation.
#[derive(Clone, Debug)]
pub struct ProContractPrincipal {
    pub(crate) ledger: Ledger,
    pub(crate) subjects: SubjectStore,
    pub(crate) scope: String,
    pub(crate) contract_id: String,
}

#[derive(Debug, Error)]
pub enum PrincipalError {
    #[error("contract not found")]
    ContractNotFound,
    #[error("contract has no frozen handoff")]
    HandoffNotFound,
    #[error("principal evidence must be non-empty")]
    EmptyEvidence,
    #[error("settlement command was rejected: {0}")]
    Rejected(String),
    #[error(transparent)]
    Ledger(#[from] LedgerError),
    #[error("failed to open the contract ledger")]
    Database(#[from] sqlx::Error),
    #[error("failed to open the execution binding: {0}")]
    Binding(String),
    #[error("failed to materialize the frozen contract subject: {0}")]
    Materialize(String),
}

impl ProContractPrincipal {
    pub async fn open(
        sqlite: &SqliteConfig,
        scope: impl Into<String>,
    ) -> Result<Self, PrincipalError> {
        let scope = scope.into();
        let ledger = open_ledger(sqlite).await?;
        Ok(Self {
            contract_id: format!("pct_{scope}"),
            ledger,
            subjects: SubjectStore::new(sqlite.home().join("pro-contract-subjects")),
            scope,
        })
    }

    pub async fn state(&self) -> Result<State, PrincipalError> {
        self.ledger.state(&self.scope).await.map_err(Into::into)
    }

    /// Materializes the exact immutable subject currently awaiting verification.
    ///
    /// Independent evaluators use this copy instead of the executor's mutable
    /// workspace. Existing destinations are rejected by the subject store.
    pub async fn materialize_handoff(
        &self,
        destination: impl Into<PathBuf>,
    ) -> Result<SubjectCoordinate, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let coordinate = contract
            .handoff
            .as_ref()
            .ok_or(PrincipalError::HandoffNotFound)?
            .subject
            .clone();
        let subjects = self.subjects.clone();
        let destination = destination.into();
        let materialized = coordinate.clone();
        tokio::task::spawn_blocking(move || subjects.materialize(&materialized, &destination))
            .await
            .map_err(|error| PrincipalError::Materialize(error.to_string()))?
            .map_err(|error| PrincipalError::Materialize(error.to_string()))?;
        Ok(coordinate)
    }

    pub async fn attest(
        &self,
        evidence_hash: impl Into<String>,
    ) -> Result<Transition, PrincipalError> {
        let evidence_hash = evidence_hash.into();
        if evidence_hash.is_empty() {
            return Err(PrincipalError::EmptyEvidence);
        }
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let handoff = contract
            .handoff
            .as_ref()
            .ok_or(PrincipalError::HandoffNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Discharge {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    attestation: Attestation {
                        id: format!("pca_{}_{}", contract.revision, evidence_hash),
                        revision: contract.revision,
                        spec_hash: contract.spec_hash.clone(),
                        subject_hash: handoff.subject.hash.clone(),
                        evidence_hash,
                        verifier_id: contract.issuer.clone(),
                    },
                },
            )
            .await?;
        require_accepted(transition)
    }

    pub async fn challenge(&self, reason: impl Into<String>) -> Result<Transition, PrincipalError> {
        let reason = reason.into();
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let handoff = contract
            .handoff
            .as_ref()
            .ok_or(PrincipalError::HandoffNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Challenge {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    revision: contract.revision,
                    subject_hash: handoff.subject.hash.clone(),
                    reason,
                },
            )
            .await?;
        require_accepted(transition)
    }
}

fn require_accepted(transition: Transition) -> Result<Transition, PrincipalError> {
    match &transition.decision {
        Decision::Accepted => Ok(transition),
        Decision::Rejected { reason } => Err(PrincipalError::Rejected(reason.clone())),
    }
}
