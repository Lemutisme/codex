//! ProContract settlement extension.
//!
//! Hosts the institution (a SQLite ledger over the pure `codex-pro-contract` kernel and a
//! SHA-256 artifact store) and the automatic Principal's automation lane: intake, drafting,
//! Issue, a candidate frozen at the turn-end boundary, container checks plus an isolated
//! review, Support or Defeat, and a bounded repair. Settlement stays with the human; under
//! the evaluation profile nothing is settled at all.

mod capture;
mod hashing;
mod settings;
mod store;
mod terms;
mod workers;

pub use capture::CaptureError;
pub use capture::Entry;
pub use capture::EntryKind;
pub use capture::Manifest;
pub use capture::Subject;
pub use capture::capture;
pub use capture::materialize;
pub use hashing::digest_of;
pub use settings::CheckEnvironment;
pub use settings::EvaluationProfile;
pub use settings::Settings;
pub use settings::SettingsError;
pub use settings::WorkerSettings;
pub use store::blobs::BlobStore;
pub use store::ledger::EventRecord;
pub use store::ledger::Ledger;
pub use store::ledger::LedgerError;
pub use terms::CapturePolicy;
pub use terms::DifferentialCase;
pub use terms::EvidenceClass;
pub use terms::EvidencePolicy;
pub use terms::OutOfScope;
pub use terms::Requirement;
pub use terms::Terms;
pub use workers::WorkerError;
