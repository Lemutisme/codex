//! Pure settlement kernel for ProContract.
//!
//! Executors propose; evidence supports; authority settles; accepted defeat restores
//! responsibility. The kernel is a total, deterministic reducer over one contract: every
//! command is bound to one authority role, every recognizing command binds an exact
//! coordinate, outstanding duty ends only by discharge on current support or by release,
//! and an accepted defeat or withdrawal restores outstanding duty. Everything else
//! (verification, scheduling, persistence, authentication) belongs to its callers.

mod command;
mod digest;
mod model;
mod rejection;
mod transition;

pub use command::AuthenticatedCommand;
pub use command::Command;
pub use command::CommandKind;
pub use command::Provenance;
pub use command::Role;
pub use command::Target;
pub use digest::Digest;
pub use model::Bindings;
pub use model::Candidate;
pub use model::Contract;
pub use model::ContractId;
pub use model::Coordinate;
pub use model::DecisionProvenance;
pub use model::OwnerId;
pub use model::Reach;
pub use model::Settlement;
pub use model::Standing;
pub use model::Support;
pub use rejection::Axiom;
pub use rejection::CoordinateField;
pub use rejection::Rejection;
pub use transition::transition;

#[cfg(test)]
#[path = "transition_tests.rs"]
mod transition_tests;

#[cfg(test)]
#[path = "reference_model_tests.rs"]
mod reference_model_tests;

#[cfg(test)]
#[path = "manifest_tests.rs"]
mod manifest_tests;
