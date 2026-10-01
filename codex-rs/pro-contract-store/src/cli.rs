//! Logic behind the `pro-contract-store` operator CLI, which the Python runner uses to capture,
//! materialize and record against the same store the extension writes.

use std::path::Path;

use codex_pro_contract::Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Serialize;

use crate::BlobStore;
use crate::CapturePolicy;
use crate::ExperimentEvent;
use crate::ExperimentRecord;
use crate::Ledger;
use crate::SubjectBinding;
use crate::capture;
use crate::digest_of;
use crate::load_subject;
use crate::materialize;
use crate::persist_manifest;

/// Result type shared by every CLI command.
pub type CliResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// What `capture` prints: the subject digest plus the digests it was bound with.
#[derive(Debug, Serialize)]
pub struct Captured {
    /// Digest of the captured subject.
    pub subject_hash: String,
    /// Digest of the persisted manifest blob.
    pub manifest: String,
    /// Digest of the capture policy used.
    pub capture_policy: String,
}

/// What `append` prints: the position and hash of the new experiment record.
#[derive(Debug, Serialize)]
pub struct Appended {
    /// One-based sequence number in the experiment chain.
    pub seq: i64,
    /// Hash of the appended record.
    pub hash: String,
}

/// One entry of the `events` listing.
#[derive(Debug, Serialize)]
pub struct ListedEvent {
    /// One-based sequence number in the experiment chain.
    pub seq: i64,
    /// The recorded experiment event.
    pub event: ExperimentEvent,
    /// Hash of the previous record in the chain.
    pub prev_hash: String,
    /// Hash of this record.
    pub hash: String,
}

async fn open(store: &Path) -> CliResult<(Ledger, BlobStore)> {
    std::fs::create_dir_all(store)?;
    let absolute = AbsolutePathBuf::from_absolute_path(std::fs::canonicalize(store)?)?;
    let ledger = Ledger::open(&SqliteConfig::from_sqlite_home(absolute), store).await?;
    let blobs = BlobStore::open(&store.join("blobs"))?;
    Ok((ledger, blobs))
}

/// Captures `root` into the store under `CapturePolicy::standard(excluded)` and binds the subject.
pub async fn capture_command(
    store: &Path,
    root: &Path,
    excluded: &[String],
) -> CliResult<Captured> {
    let (ledger, blobs) = open(store).await?;
    let policy = CapturePolicy::standard(excluded.to_vec());
    let subject = capture(root, &policy, &blobs)?;
    let manifest = persist_manifest(&subject, &blobs)?;
    let capture_policy = digest_of("capture_policy", &policy);
    ledger
        .bind_subject(
            &subject.subject_hash,
            &SubjectBinding {
                manifest,
                capture_policy,
            },
        )
        .await?;
    Ok(Captured {
        subject_hash: subject.subject_hash.to_string(),
        manifest: manifest.to_string(),
        capture_policy: capture_policy.to_string(),
    })
}

/// Writes a previously captured subject into `dest`.
pub async fn materialize_command(store: &Path, subject: &str, dest: &Path) -> CliResult<()> {
    let subject_hash = Digest::parse_hex(subject).ok_or("subject is not a digest")?;
    let (ledger, blobs) = open(store).await?;
    let binding = ledger
        .subject_binding(&subject_hash)
        .await?
        .ok_or_else(|| format!("subject {subject} is not bound in this store"))?;
    let subject = load_subject(&blobs, &binding.manifest, &subject_hash)?;
    std::fs::create_dir_all(dest)?;
    materialize(&subject, &blobs, dest)?;
    Ok(())
}

/// Appends an `ExperimentEvent` given as JSON to the experiment chain.
pub async fn append_command(store: &Path, event_json: &str) -> CliResult<Appended> {
    let event: ExperimentEvent = serde_json::from_str(event_json)?;
    let (ledger, _) = open(store).await?;
    let record = ledger.append_experiment(&event).await?;
    Ok(Appended {
        seq: record.seq,
        hash: record.hash.to_string(),
    })
}

/// Lists every experiment record in chain order.
pub async fn events_command(store: &Path) -> CliResult<Vec<ListedEvent>> {
    let (ledger, _) = open(store).await?;
    Ok(ledger
        .experiments()
        .await?
        .into_iter()
        .map(|record: ExperimentRecord| ListedEvent {
            seq: record.seq,
            event: record.event,
            prev_hash: record.prev_hash.to_string(),
            hash: record.hash.to_string(),
        })
        .collect())
}

/// Verifies the experiment hash chain.
pub async fn verify_command(store: &Path) -> CliResult<()> {
    let (ledger, _) = open(store).await?;
    ledger.verify_experiment_chain().await?;
    Ok(())
}

#[cfg(test)]
#[path = "cli_tests.rs"]
mod tests;
