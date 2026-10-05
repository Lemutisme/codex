use serde::Deserialize;
use serde::Serialize;

use crate::CommandKind;
use crate::Role;

/// The invariant a rejection protects.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Axiom {
    /// A1: each command kind is bound to one role; the executor has no settlement verb.
    Monopoly,
    /// A2: recognizing commands bind a complete coordinate; fencing is exactness over time.
    Exactness,
    /// A3: outstanding duty ends only by discharge on current support or by release.
    Conservation,
    /// A4: an accepted defeat restores outstanding duty.
    Defeasance,
    /// The command cannot be interpreted as one operation on this contract.
    WellFormed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CoordinateField {
    ContractId,
    Revision,
    TermsHash,
    CapturePolicyHash,
    EvidencePolicyHash,
    Generation,
    SubjectHash,
    Support,
}

/// Why a command was rejected. A rejected command leaves the contract unchanged.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Rejection {
    #[error("{command:?} requires role {required:?}, got {actual:?}")]
    WrongRole {
        command: CommandKind,
        required: Role,
        actual: Role,
    },
    #[error("revision requires human provenance")]
    RevisionRequiresHuman,
    #[error("contract already exists")]
    ContractExists,
    #[error("unknown contract")]
    UnknownContract,
    #[error("command addresses a different contract")]
    ContractMismatch,
    #[error("stale version: expected {expected}, current {current}")]
    StaleVersion { expected: u64, current: u64 },
    #[error("contract is released")]
    Released,
    #[error("contract is not outstanding")]
    NotOutstanding,
    #[error("contract has no candidate")]
    NoCandidate,
    #[error("contract already has support")]
    SupportPresent,
    #[error("contract has no current support")]
    NoSupport,
    #[error("coordinate mismatch in {field:?}")]
    CoordinateMismatch { field: CoordinateField },
    #[error("target does not match the contract's current state")]
    TargetMismatch,
    #[error("only an explicit human act may settle on evidence from within the claim's reach")]
    WithinReach,
}

impl Rejection {
    pub fn axiom(&self) -> Axiom {
        match self {
            Rejection::WrongRole { .. }
            | Rejection::RevisionRequiresHuman
            | Rejection::WithinReach => Axiom::Monopoly,
            Rejection::NoCandidate
            | Rejection::SupportPresent
            | Rejection::CoordinateMismatch { .. }
            | Rejection::TargetMismatch => Axiom::Exactness,
            Rejection::Released | Rejection::NotOutstanding | Rejection::NoSupport => {
                Axiom::Conservation
            }
            Rejection::ContractExists
            | Rejection::UnknownContract
            | Rejection::ContractMismatch
            | Rejection::StaleVersion { .. } => Axiom::WellFormed,
        }
    }
}
