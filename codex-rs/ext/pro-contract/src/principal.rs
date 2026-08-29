use crate::open_ledger;
use codex_pro_contract::Attestation;
use codex_pro_contract::Challenge;
use codex_pro_contract::ChallengeDisclosure;
use codex_pro_contract::Command;
use codex_pro_contract::Decision;
use codex_pro_contract::Ledger;
use codex_pro_contract::LedgerError;
use codex_pro_contract::QuietSnapshot;
use codex_pro_contract::RevisionDisposition;
use codex_pro_contract::State;
use codex_pro_contract::SubjectCoordinate;
use codex_pro_contract::SubjectStore;
use codex_pro_contract::Transition;
use codex_state::SqliteConfig;
use sha2::Digest;
use sha2::Sha256;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PrincipalChallenge {
    Executor {
        evidence_hash: String,
        summary: String,
    },
    Sealed {
        evidence_hash: String,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RevisionDecision {
    Accept,
    Reject,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrincipalRevisionDecision {
    pub revision: u64,
    pub spec_hash: String,
    pub decision: RevisionDecision,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrincipalContractCoordinate {
    pub revision: u64,
    pub spec_hash: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PrincipalAttestation {
    pub revision: u64,
    pub spec_hash: String,
    pub subject_hash: String,
    pub evidence_hash: String,
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
        Self::open_contract(sqlite, scope.clone(), format!("pct_{scope}")).await
    }

    pub async fn open_contract(
        sqlite: &SqliteConfig,
        scope: impl Into<String>,
        contract_id: impl Into<String>,
    ) -> Result<Self, PrincipalError> {
        let scope = scope.into();
        let ledger = open_ledger(sqlite).await?;
        Ok(Self {
            contract_id: contract_id.into(),
            ledger,
            subjects: SubjectStore::new(sqlite.home().join("pro-contract-subjects")),
            scope,
        })
    }

    pub async fn state(&self) -> Result<State, PrincipalError> {
        self.ledger.state(&self.scope).await.map_err(Into::into)
    }

    pub fn contract_id(&self) -> &str {
        &self.contract_id
    }

    pub async fn quiet(&self) -> Result<QuietSnapshot, PrincipalError> {
        self.ledger.quiet(&self.scope).await.map_err(Into::into)
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
        self.attest_exact(PrincipalAttestation {
            revision: contract.revision,
            spec_hash: contract.spec_hash.clone(),
            subject_hash: handoff.subject.hash.clone(),
            evidence_hash,
        })
        .await
    }

    pub async fn attest_exact(
        &self,
        attestation: PrincipalAttestation,
    ) -> Result<Transition, PrincipalError> {
        if attestation.evidence_hash.is_empty() {
            return Err(PrincipalError::EmptyEvidence);
        }
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Discharge {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    attestation: Attestation {
                        id: attestation_id(
                            &contract.id,
                            attestation.revision,
                            &attestation.spec_hash,
                            &attestation.subject_hash,
                            &attestation.evidence_hash,
                        ),
                        revision: attestation.revision,
                        spec_hash: attestation.spec_hash,
                        subject_hash: attestation.subject_hash,
                        evidence_hash: attestation.evidence_hash,
                        verifier_id: contract.issuer.clone(),
                    },
                },
            )
            .await?;
        require_accepted(transition)
    }

    pub async fn challenge(
        &self,
        challenge: PrincipalChallenge,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let handoff = contract
            .handoff
            .as_ref()
            .ok_or(PrincipalError::HandoffNotFound)?;
        self.challenge_exact(contract.revision, handoff.subject.hash.clone(), challenge)
            .await
    }

    pub async fn challenge_exact(
        &self,
        revision: u64,
        subject_hash: String,
        challenge: PrincipalChallenge,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let (evidence_hash, disclosure, summary) = match challenge {
            PrincipalChallenge::Executor {
                evidence_hash,
                summary,
            } => (evidence_hash, ChallengeDisclosure::Executor, Some(summary)),
            PrincipalChallenge::Sealed { evidence_hash } => {
                (evidence_hash, ChallengeDisclosure::Sealed, None)
            }
        };
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Challenge {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    challenge: Challenge {
                        revision,
                        subject_hash,
                        evidence_hash,
                        disclosure,
                        summary,
                        time: now_millis(),
                        attestation_id: None,
                    },
                },
            )
            .await?;
        require_accepted(transition)
    }

    pub async fn decide_revision(
        &self,
        decision: RevisionDecision,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let pending = contract.pending_revision.as_ref().ok_or_else(|| {
            PrincipalError::Rejected("no revision petition is pending".to_string())
        })?;
        self.decide_revision_exact(PrincipalRevisionDecision {
            revision: contract.revision,
            spec_hash: pending.spec_hash.clone(),
            decision,
        })
        .await
    }

    pub async fn decide_revision_exact(
        &self,
        decision: PrincipalRevisionDecision,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::DecideRevision {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    revision: decision.revision,
                    spec_hash: decision.spec_hash,
                    disposition: match decision.decision {
                        RevisionDecision::Accept => RevisionDisposition::Accept,
                        RevisionDecision::Reject => RevisionDisposition::Reject,
                    },
                },
            )
            .await?;
        require_accepted(transition)
    }

    pub async fn resume(&self) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        self.resume_exact(PrincipalContractCoordinate {
            revision: contract.revision,
            spec_hash: contract.spec_hash.clone(),
        })
        .await
    }

    pub async fn resume_exact(
        &self,
        coordinate: PrincipalContractCoordinate,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Resume {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    revision: coordinate.revision,
                    spec_hash: coordinate.spec_hash,
                },
            )
            .await?;
        require_accepted(transition)
    }

    pub async fn release(&self, reason: impl Into<String>) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        self.release_exact(
            PrincipalContractCoordinate {
                revision: contract.revision,
                spec_hash: contract.spec_hash.clone(),
            },
            reason,
        )
        .await
    }

    pub async fn release_exact(
        &self,
        coordinate: PrincipalContractCoordinate,
        reason: impl Into<String>,
    ) -> Result<Transition, PrincipalError> {
        let state = self.state().await?;
        let contract = state
            .contracts
            .get(&self.contract_id)
            .ok_or(PrincipalError::ContractNotFound)?;
        let transition = self
            .ledger
            .apply(
                &self.scope,
                Command::Release {
                    actor: contract.issuer.clone(),
                    contract_id: contract.id.clone(),
                    revision: coordinate.revision,
                    spec_hash: coordinate.spec_hash,
                    reason: reason.into(),
                },
            )
            .await?;
        require_accepted(transition)
    }
}

fn now_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_millis() as u64)
}

fn attestation_id(
    contract_id: &str,
    revision: u64,
    spec_hash: &str,
    subject_hash: &str,
    evidence_hash: &str,
) -> String {
    let mut digest = Sha256::new();
    let revision = revision.to_le_bytes();
    for value in [
        contract_id.as_bytes(),
        &revision,
        spec_hash.as_bytes(),
        subject_hash.as_bytes(),
        evidence_hash.as_bytes(),
    ] {
        digest.update(value.len().to_le_bytes());
        digest.update(value);
    }
    format!("pca_{:x}", digest.finalize())
}

fn require_accepted(transition: Transition) -> Result<Transition, PrincipalError> {
    match &transition.decision {
        Decision::Accepted => Ok(transition),
        Decision::Rejected { reason } => Err(PrincipalError::Rejected(reason.clone())),
    }
}
