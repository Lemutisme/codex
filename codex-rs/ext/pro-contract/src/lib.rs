//! ProContract settlement extension.
//!
//! Hosts the institution (a SQLite ledger over the pure `codex-pro-contract` kernel and a
//! SHA-256 artifact store) and the automatic Principal's automation lane: intake, drafting,
//! Issue, a candidate frozen at the turn-end boundary, container checks plus an isolated
//! review, Support or Defeat, and a bounded repair. Settlement stays with the human; under
//! the evaluation profile nothing is settled at all.

mod checks;
mod controller;
mod settings;
mod workers;

pub use checks::CheckError;
pub use checks::CheckReceipts;
pub use checks::StepOutcome;
pub use checks::StepReceipt;
pub use codex_pro_contract_store::BlobStore;
pub use codex_pro_contract_store::CaptureError;
pub use codex_pro_contract_store::CapturePolicy;
pub use codex_pro_contract_store::DifferentialCase;
pub use codex_pro_contract_store::Entry;
pub use codex_pro_contract_store::EntryKind;
pub use codex_pro_contract_store::EventRecord;
pub use codex_pro_contract_store::EvidenceClass;
pub use codex_pro_contract_store::EvidencePolicy;
pub use codex_pro_contract_store::Ledger;
pub use codex_pro_contract_store::LedgerError;
pub use codex_pro_contract_store::Manifest;
pub use codex_pro_contract_store::OutOfScope;
pub use codex_pro_contract_store::Requirement;
pub use codex_pro_contract_store::Subject;
pub use codex_pro_contract_store::Terms;
pub use codex_pro_contract_store::capture;
pub use codex_pro_contract_store::digest_of;
pub use codex_pro_contract_store::materialize;
pub use controller::runtime::StatusRecord;
pub use settings::CheckEnvironment;
pub use settings::EvaluationProfile;
pub use settings::Settings;
pub use settings::SettingsError;
pub use settings::WorkerSettings;
pub use workers::WorkerError;

/// Installs the ProContract automation lane. `enabled` decides per thread configuration whether
/// the lane is active at all; eligibility then decides whether contracts are possible.
pub fn install(
    registry: &mut codex_extension_api::ExtensionRegistryBuilder<codex_core::config::Config>,
    thread_manager: std::sync::Weak<codex_core::ThreadManager>,
    enabled: impl Fn(&codex_core::config::Config) -> bool + Send + Sync + 'static,
) {
    let extension = std::sync::Arc::new(controller::ProContractExtension::new(
        thread_manager,
        Box::new(enabled),
    ));
    registry.thread_lifecycle_contributor(extension.clone());
    registry.turn_lifecycle_contributor(extension.clone());
    registry.turn_input_contributor(extension.clone());
    registry.prompt_contributor(extension);
}
