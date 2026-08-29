//! Executor-independent completion integrity for Codex.
//!
//! The crate deliberately owns only the normative state machine and immutable
//! delivery subjects. Codex lifecycle and persistence adapters live outside
//! this thin waist.

mod kernel;
mod ledger;
mod subject;

pub use kernel::Attestation;
pub use kernel::Command;
pub use kernel::Contract;
pub use kernel::ContractSpec;
pub use kernel::Decision;
pub use kernel::Draft;
pub use kernel::Handoff;
pub use kernel::INSTITUTION_ACTOR;
pub use kernel::Requirement;
pub use kernel::State;
pub use kernel::Status;
pub use kernel::Transition;
pub use kernel::hash_spec;
pub use kernel::quiet;
pub use kernel::transition;
pub use ledger::Ledger;
pub use ledger::LedgerError;
pub use ledger::LedgerEvent;
pub use subject::ArtifactPath;
pub use subject::ArtifactSpec;
pub use subject::CaptureLimits;
pub use subject::CapturedSubject;
pub use subject::SubjectCoordinate;
pub use subject::SubjectError;
pub use subject::SubjectStore;
