//! The ProContract institution's storage primitives: domain-separated hashing, contract terms,
//! workspace capture, the content-addressed blob store, and the SQLite ledger. Free of
//! `codex-core`, so that operator tools and a protected institution service can link it directly.

mod capture;
mod hashing;
mod store;
mod terms;

pub use capture::CaptureError;
pub use capture::Entry;
pub use capture::EntryKind;
pub use capture::Manifest;
pub use capture::Subject;
pub use capture::capture;
pub use capture::materialize;
pub use hashing::digest_of;
pub use store::blobs::BlobStore;
pub use store::ledger::EventRecord;
pub use store::ledger::LEDGER_FILE;
pub use store::ledger::Ledger;
pub use store::ledger::LedgerError;
pub use terms::CapturePolicy;
pub use terms::DifferentialCase;
pub use terms::EvidenceClass;
pub use terms::EvidencePolicy;
pub use terms::OutOfScope;
pub use terms::Requirement;
pub use terms::Terms;
