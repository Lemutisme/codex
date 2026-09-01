//! Executor-independent completion integrity for Codex.
//!
//! The crate deliberately owns only the normative state machine and the pure
//! subject/spec vocabulary. Impure institution adapters (the SQLite ledger and
//! the filesystem subject store) live in `codex-pro-contract-institution`;
//! Codex lifecycle adapters live outside this thin waist entirely.

mod kernel;
mod kernel_validation;
mod rejection;
mod spec;
mod subject;

pub use kernel::Attestation;
pub use kernel::Blocked;
pub use kernel::Challenge;
pub use kernel::ChallengeDisclosure;
pub use kernel::Command;
pub use kernel::Contract;
pub use kernel::Decision;
pub use kernel::Draft;
pub use kernel::Escalation;
pub use kernel::Handoff;
pub use kernel::INSTITUTION_ACTOR;
pub use kernel::PendingRevision;
pub use kernel::ReplayResult;
pub use kernel::RevisionDisposition;
pub use kernel::State;
pub use kernel::Status;
pub use kernel::Transition;
pub use kernel::hash_replay;
pub use kernel::hash_spec;
pub use kernel::quiet;
pub use kernel::transition;
pub use rejection::Axiom;
pub use rejection::Rejection;
pub use rejection::RejectionClass;
pub use spec::Budget;
pub use spec::ContractSpec;
pub use spec::Evidence;
pub use spec::ProtectedFile;
pub use spec::ReplayCheck;
pub use spec::ReplayPolicy;
pub use spec::Requirement;
pub use spec::Resolution;
pub use spec::Trigger;
pub use subject::ArtifactPath;
pub use subject::ArtifactPathError;
pub use subject::ArtifactSpec;
pub use subject::SubjectCoordinate;
