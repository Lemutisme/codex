use std::path::Path;

use codex_pro_contract::AuthenticatedCommand;
use codex_pro_contract::Contract;
use codex_pro_contract::ContractId;
use codex_pro_contract::Digest;
use codex_pro_contract::Rejection;
use codex_pro_contract::transition;
use codex_state::SqliteConfig;
use serde::Serialize;
use serde::de::DeserializeOwned;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::digest_of;

/// Ledger file under `CODEX_HOME/pro_contract/`.
pub const LEDGER_FILE: &str = "ledger_1.sqlite";

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS contracts (
    id TEXT PRIMARY KEY NOT NULL,
    version INTEGER NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id TEXT NOT NULL,
    command_json TEXT NOT NULL,
    state_hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY NOT NULL,
    command_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS subjects (
    subject_hash TEXT PRIMARY KEY NOT NULL,
    manifest TEXT NOT NULL,
    capture_policy TEXT NOT NULL
);
";

#[derive(Debug, thiserror::Error)]
pub enum LedgerError {
    #[error("ledger storage error: {0}")]
    Storage(String),
    #[error("command rejected: {0}")]
    Rejected(Rejection),
    #[error("idempotency key reused with a different command")]
    IdempotencyConflict,
    #[error("ledger record is corrupt: {0}")]
    Corrupt(String),
    #[error("experiment event is invalid: {0}")]
    InvalidEvent(String),
}

/// One accepted command in the hash-chained event log.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EventRecord {
    pub seq: i64,
    pub contract_id: ContractId,
    pub command: AuthenticatedCommand,
    pub state_hash: Digest,
    pub prev_hash: Digest,
    pub hash: Digest,
}

/// The institution's store: the kernel's accepted transitions, their hash-chained events, the
/// idempotency index, and extension records (intakes, artifacts, verdicts, status).
#[derive(Clone, Debug)]
pub struct Ledger {
    pub(super) pool: SqlitePool,
}

impl Ledger {
    /// Opens (creating if needed) `dir/ledger_1.sqlite`.
    pub async fn open(sqlite: &SqliteConfig, dir: &Path) -> Result<Ledger, LedgerError> {
        tokio::fs::create_dir_all(dir).await.map_err(storage)?;
        let pool = sqlite
            .open_read_write_pool(&dir.join(LEDGER_FILE))
            .await
            .map_err(storage)?;
        sqlx::raw_sql(SCHEMA)
            .execute(&pool)
            .await
            .map_err(storage)?;
        sqlx::raw_sql(super::experiments::SCHEMA)
            .execute(&pool)
            .await
            .map_err(storage)?;
        Ok(Ledger { pool })
    }

    /// Applies one command through the kernel in a single `BEGIN IMMEDIATE` transaction.
    ///
    /// Retries never reach the reducer: an identical retry under the same key returns the
    /// originally committed state; a different command under the same key is rejected.
    pub async fn apply(
        &self,
        command: &AuthenticatedCommand,
        idempotency_key: &str,
    ) -> Result<Contract, LedgerError> {
        let command_hash = digest_of("command", command).to_string();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)?;
        let committed =
            sqlx::query("SELECT command_hash, result_json FROM idempotency WHERE key = ?")
                .bind(idempotency_key)
                .fetch_optional(&mut *tx)
                .await
                .map_err(storage)?;
        if let Some(row) = committed {
            let stored_hash: String = row.try_get("command_hash").map_err(storage)?;
            if stored_hash != command_hash {
                return Err(LedgerError::IdempotencyConflict);
            }
            let json: String = row.try_get("result_json").map_err(storage)?;
            return decode(&json);
        }
        let current: Option<Contract> =
            sqlx::query_scalar::<_, String>("SELECT state_json FROM contracts WHERE id = ?")
                .bind(&command.contract_id.0)
                .fetch_optional(&mut *tx)
                .await
                .map_err(storage)?
                .map(|json| decode(&json))
                .transpose()?;
        let next = transition(current.as_ref(), command).map_err(LedgerError::Rejected)?;
        let prev_hash =
            sqlx::query_scalar::<_, String>("SELECT hash FROM events ORDER BY seq DESC LIMIT 1")
                .fetch_optional(&mut *tx)
                .await
                .map_err(storage)?
                .map(|hex| parse_digest(&hex))
                .transpose()?
                .unwrap_or(Digest::from_bytes([0; 32]));
        let state_hash = digest_of("contract_state", &next);
        let hash = digest_of("event", &(prev_hash, command, state_hash));
        let command_json = encode(command)?;
        let state_json = encode(&next)?;
        sqlx::query(
            "INSERT INTO events (contract_id, command_json, state_hash, prev_hash, hash)
             VALUES (?, ?, ?, ?, ?)",
        )
        .bind(&next.id.0)
        .bind(&command_json)
        .bind(state_hash.to_string())
        .bind(prev_hash.to_string())
        .bind(hash.to_string())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query(
            "INSERT INTO contracts (id, version, state_json) VALUES (?, ?, ?)
             ON CONFLICT(id) DO UPDATE SET version = excluded.version, state_json = excluded.state_json",
        )
        .bind(&next.id.0)
        .bind(next.version as i64)
        .bind(&state_json)
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        sqlx::query("INSERT INTO idempotency (key, command_hash, result_json) VALUES (?, ?, ?)")
            .bind(idempotency_key)
            .bind(&command_hash)
            .bind(&state_json)
            .execute(&mut *tx)
            .await
            .map_err(storage)?;
        tx.commit().await.map_err(storage)?;
        Ok(next)
    }

    pub async fn contract(&self, id: &ContractId) -> Result<Option<Contract>, LedgerError> {
        sqlx::query_scalar::<_, String>("SELECT state_json FROM contracts WHERE id = ?")
            .bind(&id.0)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(|json| decode(&json))
            .transpose()
    }

    pub async fn events(&self) -> Result<Vec<EventRecord>, LedgerError> {
        let rows = sqlx::query(
            "SELECT seq, contract_id, command_json, state_hash, prev_hash, hash
             FROM events ORDER BY seq",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter()
            .map(|row| {
                let command_json: String = row.try_get("command_json").map_err(storage)?;
                let state_hash: String = row.try_get("state_hash").map_err(storage)?;
                let prev_hash: String = row.try_get("prev_hash").map_err(storage)?;
                let hash: String = row.try_get("hash").map_err(storage)?;
                Ok(EventRecord {
                    seq: row.try_get("seq").map_err(storage)?,
                    contract_id: ContractId(row.try_get("contract_id").map_err(storage)?),
                    command: decode(&command_json)?,
                    state_hash: parse_digest(&state_hash)?,
                    prev_hash: parse_digest(&prev_hash)?,
                    hash: parse_digest(&hash)?,
                })
            })
            .collect()
    }

    /// Upserts an extension record.
    pub async fn put_record<T: Serialize + Sync>(
        &self,
        kind: &str,
        key: &str,
        value: &T,
    ) -> Result<(), LedgerError> {
        sqlx::query(
            "INSERT INTO records (kind, key, json) VALUES (?, ?, ?)
             ON CONFLICT(kind, key) DO UPDATE SET json = excluded.json",
        )
        .bind(kind)
        .bind(key)
        .bind(encode(value)?)
        .execute(&self.pool)
        .await
        .map_err(storage)?;
        Ok(())
    }

    pub async fn record<T: DeserializeOwned>(
        &self,
        kind: &str,
        key: &str,
    ) -> Result<Option<T>, LedgerError> {
        sqlx::query_scalar::<_, String>("SELECT json FROM records WHERE kind = ? AND key = ?")
            .bind(kind)
            .bind(key)
            .fetch_optional(&self.pool)
            .await
            .map_err(storage)?
            .map(|json| decode(&json))
            .transpose()
    }
}

/// Where a captured subject's manifest is stored and under which capture policy it was taken.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SubjectBinding {
    pub manifest: Digest,
    pub capture_policy: Digest,
}

impl Ledger {
    /// Binds a subject hash to its persisted manifest. Rebinding identically is a no-op;
    /// rebinding differently is corruption.
    pub async fn bind_subject(
        &self,
        subject_hash: &Digest,
        binding: &SubjectBinding,
    ) -> Result<(), LedgerError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)?;
        if let Some(found) = read_binding(&mut tx, subject_hash).await? {
            return if found == *binding {
                Ok(())
            } else {
                Err(LedgerError::Corrupt(format!(
                    "subject {subject_hash} is already bound to another manifest"
                )))
            };
        }
        sqlx::query(
            "INSERT INTO subjects (subject_hash, manifest, capture_policy) VALUES (?, ?, ?)",
        )
        .bind(subject_hash.to_string())
        .bind(binding.manifest.to_string())
        .bind(binding.capture_policy.to_string())
        .execute(&mut *tx)
        .await
        .map_err(storage)?;
        tx.commit().await.map_err(storage)
    }

    pub async fn subject_binding(
        &self,
        subject_hash: &Digest,
    ) -> Result<Option<SubjectBinding>, LedgerError> {
        let mut connection = self.pool.acquire().await.map_err(storage)?;
        read_binding(&mut connection, subject_hash).await
    }
}

async fn read_binding(
    connection: &mut sqlx::SqliteConnection,
    subject_hash: &Digest,
) -> Result<Option<SubjectBinding>, LedgerError> {
    let row = sqlx::query("SELECT manifest, capture_policy FROM subjects WHERE subject_hash = ?")
        .bind(subject_hash.to_string())
        .fetch_optional(connection)
        .await
        .map_err(storage)?;
    row.map(|row| {
        let manifest: String = row.try_get("manifest").map_err(storage)?;
        let capture_policy: String = row.try_get("capture_policy").map_err(storage)?;
        Ok(SubjectBinding {
            manifest: parse_digest(&manifest)?,
            capture_policy: parse_digest(&capture_policy)?,
        })
    })
    .transpose()
}

pub(super) fn storage(error: impl std::fmt::Display) -> LedgerError {
    LedgerError::Storage(error.to_string())
}

fn encode<T: Serialize + ?Sized>(value: &T) -> Result<String, LedgerError> {
    serde_json::to_string(value).map_err(|error| LedgerError::Corrupt(error.to_string()))
}

fn decode<T: DeserializeOwned>(json: &str) -> Result<T, LedgerError> {
    serde_json::from_str(json).map_err(|error| LedgerError::Corrupt(error.to_string()))
}

pub(super) fn parse_digest(hex: &str) -> Result<Digest, LedgerError> {
    Digest::parse_hex(hex).ok_or_else(|| LedgerError::Corrupt(format!("invalid digest {hex}")))
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;
