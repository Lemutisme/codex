//! Append-only, hash-chained research events (RSI spec §3.5). Unlike `records`, these are never
//! updated or deleted: SQLite triggers reject both, and the chain detects forged rows.

use std::collections::BTreeMap;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use sqlx::Row;

use super::ledger::Ledger;
use super::ledger::LedgerError;
use super::ledger::parse_digest;
use super::ledger::storage;
use crate::digest_of;

pub(crate) const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS experiment_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    event_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS experiment_events_no_update
BEFORE UPDATE ON experiment_events
BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS experiment_events_no_delete
BEFORE DELETE ON experiment_events
BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END;
";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExperimentKind {
    Assignment,
    Intake,
    Draft,
    /// The prober's raw output and the reference observations it explored.
    Probe,
    Issue,
    Verification,
    Capture,
    Execution,
    Label,
    Correction,
    /// A version registered for succession: its manifest and lineage.
    Version,
    /// A choice that carries no authority by itself: a research parent, a candidate put forward,
    /// an incumbent recorded after its adoption was settled.
    Selection,
    /// Sources made readable to a view; exposure only accumulates.
    Exposure,
}

/// What produced an event. Every event carries one.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Identities {
    /// SHA-256 of the harness executable, when a harness produced the event.
    pub harness: Option<String>,
    /// Judgment policy digests by name (`drafter`, `reviewer`, `check_pipeline`).
    pub policies: BTreeMap<String, Digest>,
    pub model: Option<String>,
    pub effort: Option<String>,
    /// Required on labels.
    pub evaluator_epoch: Option<Digest>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentEvent {
    pub kind: ExperimentKind,
    pub identities: Identities,
    /// Kind-specific content, owned by its writer (the extension or the runner).
    pub body: Value,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExperimentRecord {
    pub seq: i64,
    pub event: ExperimentEvent,
    pub prev_hash: Digest,
    pub hash: Digest,
}

/// Rebuilds objects with sorted keys, so the encoding does not depend on serde_json features.
fn canonical(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let sorted: BTreeMap<&String, Value> = map
                .iter()
                .map(|(key, value)| (key, canonical(value)))
                .collect();
            Value::Object(
                sorted
                    .into_iter()
                    .map(|(key, value)| (key.clone(), value))
                    .collect(),
            )
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical).collect()),
        other => other.clone(),
    }
}

fn validate(event: &ExperimentEvent) -> Result<(), LedgerError> {
    let invalid = |message: &str| Err(LedgerError::InvalidEvent(message.to_string()));
    match event.kind {
        ExperimentKind::Label | ExperimentKind::Correction
            if event.identities.evaluator_epoch.is_none() =>
        {
            invalid("a label or correction must carry its evaluator epoch")
        }
        ExperimentKind::Verification
            if event.identities.policies.is_empty() || event.identities.model.is_none() =>
        {
            invalid("a verification must carry its policy digests and model")
        }
        ExperimentKind::Assignment
        | ExperimentKind::Intake
        | ExperimentKind::Draft
        | ExperimentKind::Probe
        | ExperimentKind::Issue
        | ExperimentKind::Verification
        | ExperimentKind::Capture
        | ExperimentKind::Execution
        | ExperimentKind::Label
        | ExperimentKind::Correction
        | ExperimentKind::Version
        | ExperimentKind::Selection
        | ExperimentKind::Exposure => Ok(()),
    }
}

fn chain_hash(prev_hash: &Digest, event: &ExperimentEvent) -> Digest {
    digest_of("experiment_event", &(prev_hash, event))
}

impl Ledger {
    pub async fn append_experiment(
        &self,
        event: &ExperimentEvent,
    ) -> Result<ExperimentRecord, LedgerError> {
        validate(event)?;
        let event = ExperimentEvent {
            body: canonical(&event.body),
            ..event.clone()
        };
        let encoded = serde_json::to_string(&event)
            .map_err(|error| LedgerError::Corrupt(error.to_string()))?;
        let kind = serde_json::to_value(event.kind)
            .ok()
            .and_then(|kind| kind.as_str().map(str::to_string))
            .unwrap_or_default();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)?;
        let prev_hash = sqlx::query_scalar::<_, String>(
            "SELECT hash FROM experiment_events ORDER BY seq DESC LIMIT 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?
        .map(|hex| parse_digest(&hex))
        .transpose()?
        .unwrap_or(Digest::from_bytes([0; 32]));
        let hash = chain_hash(&prev_hash, &event);
        let seq = sqlx::query(
            "INSERT INTO experiment_events (kind, event_json, prev_hash, hash) VALUES (?, ?, ?, ?)",
        )
        .bind(&kind)
        .bind(&encoded)
        .bind(prev_hash.to_string())
        .bind(hash.to_string())
        .execute(&mut *tx)
        .await
        .map_err(storage)?
        .last_insert_rowid();
        tx.commit().await.map_err(storage)?;
        Ok(ExperimentRecord {
            seq,
            event,
            prev_hash,
            hash,
        })
    }

    pub async fn experiments(&self) -> Result<Vec<ExperimentRecord>, LedgerError> {
        let rows = sqlx::query(
            "SELECT seq, event_json, prev_hash, hash FROM experiment_events ORDER BY seq",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(storage)?;
        rows.into_iter()
            .map(|row| {
                let event_json: String = row.try_get("event_json").map_err(storage)?;
                let prev_hash: String = row.try_get("prev_hash").map_err(storage)?;
                let hash: String = row.try_get("hash").map_err(storage)?;
                Ok(ExperimentRecord {
                    seq: row.try_get("seq").map_err(storage)?,
                    event: serde_json::from_str(&event_json)
                        .map_err(|error| LedgerError::Corrupt(error.to_string()))?,
                    prev_hash: parse_digest(&prev_hash)?,
                    hash: parse_digest(&hash)?,
                })
            })
            .collect()
    }

    /// Recomputes the chain; any forged, reordered or edited row is corruption.
    pub async fn verify_experiment_chain(&self) -> Result<(), LedgerError> {
        let mut expected_prev = Digest::from_bytes([0; 32]);
        for record in self.experiments().await? {
            if record.prev_hash != expected_prev
                || record.hash != chain_hash(&record.prev_hash, &record.event)
            {
                return Err(LedgerError::Corrupt(format!(
                    "experiment event {} breaks the chain",
                    record.seq
                )));
            }
            expected_prev = record.hash;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "experiments_tests.rs"]
mod tests;
