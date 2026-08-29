use crate::Command;
use crate::Decision;
use crate::State;
use crate::Transition;
use crate::transition;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use thiserror::Error;

const EMPTY_LEDGER_HEAD: &str = "";

#[derive(Clone, Debug)]
pub struct Ledger {
    pool: SqlitePool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct LedgerEvent {
    pub sequence: u64,
    pub previous_hash: String,
    pub hash: String,
    pub command: Command,
    pub decision: Decision,
}

#[derive(Debug, Error)]
pub enum LedgerError {
    #[error("contract command targets a different scope")]
    ScopeMismatch,
    #[error("contract state is corrupt")]
    CorruptState(#[from] serde_json::Error),
    #[error("contract ledger operation failed")]
    Database(#[from] sqlx::Error),
}

impl Ledger {
    /// Initializes a contract ledger on a host-configured SQLite pool.
    ///
    /// The host owns connection policy; this crate owns only its tables and
    /// transaction semantics.
    pub async fn initialize(pool: SqlitePool) -> Result<Self, LedgerError> {
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_projection (
                scope TEXT PRIMARY KEY NOT NULL,
                state_json TEXT NOT NULL,
                ledger_head TEXT NOT NULL,
                next_sequence INTEGER NOT NULL
            )",
        )
        .execute(&pool)
        .await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_event (
                scope TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                command_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                PRIMARY KEY (scope, sequence)
            )",
        )
        .execute(&pool)
        .await?;
        Ok(Self { pool })
    }

    pub async fn apply(&self, scope: &str, command: Command) -> Result<Transition, LedgerError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let row = sqlx::query(
            "SELECT state_json, ledger_head, next_sequence
             FROM pro_contract_projection WHERE scope = ?",
        )
        .bind(scope)
        .fetch_optional(&mut *transaction)
        .await?;
        let (state, previous_hash, sequence) = if let Some(row) = row {
            (
                serde_json::from_str(row.try_get("state_json")?)?,
                row.try_get("ledger_head")?,
                row.try_get::<i64, _>("next_sequence")? as u64,
            )
        } else {
            (State::default(), EMPTY_LEDGER_HEAD.to_string(), 0)
        };
        if !command_matches_scope(&state, scope, &command) {
            return Err(LedgerError::ScopeMismatch);
        }

        let transition = transition(&state, command);
        let command_json = serde_json::to_string(&transition.command)?;
        let decision_json = serde_json::to_string(&transition.decision)?;
        let event_hash = event_hash(&previous_hash, sequence, &command_json, &decision_json)?;
        sqlx::query(
            "INSERT INTO pro_contract_event
             (scope, sequence, previous_hash, event_hash, command_json, decision_json)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(scope)
        .bind(sequence as i64)
        .bind(&previous_hash)
        .bind(&event_hash)
        .bind(command_json)
        .bind(decision_json)
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            "INSERT INTO pro_contract_projection
             (scope, state_json, ledger_head, next_sequence) VALUES (?, ?, ?, ?)
             ON CONFLICT(scope) DO UPDATE SET
               state_json = excluded.state_json,
               ledger_head = excluded.ledger_head,
               next_sequence = excluded.next_sequence",
        )
        .bind(scope)
        .bind(serde_json::to_string(&transition.state)?)
        .bind(event_hash)
        .bind(sequence.saturating_add(1) as i64)
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(transition)
    }

    pub async fn state(&self, scope: &str) -> Result<State, LedgerError> {
        let state = sqlx::query_scalar::<_, String>(
            "SELECT state_json FROM pro_contract_projection WHERE scope = ?",
        )
        .bind(scope)
        .fetch_optional(&self.pool)
        .await?;
        state
            .map(|state| serde_json::from_str(&state))
            .transpose()
            .map(Option::unwrap_or_default)
            .map_err(Into::into)
    }

    pub async fn events(&self, scope: &str) -> Result<Vec<LedgerEvent>, LedgerError> {
        let rows = sqlx::query(
            "SELECT sequence, previous_hash, event_hash, command_json, decision_json
             FROM pro_contract_event WHERE scope = ? ORDER BY sequence",
        )
        .bind(scope)
        .fetch_all(&self.pool)
        .await?;
        rows.into_iter()
            .map(|row| {
                Ok(LedgerEvent {
                    sequence: row.try_get::<i64, _>("sequence")? as u64,
                    previous_hash: row.try_get("previous_hash")?,
                    hash: row.try_get("event_hash")?,
                    command: serde_json::from_str(row.try_get("command_json")?)?,
                    decision: serde_json::from_str(row.try_get("decision_json")?)?,
                })
            })
            .collect()
    }
}

fn command_matches_scope(state: &State, scope: &str, command: &Command) -> bool {
    match command {
        Command::Issue { draft, .. } => draft.scope == scope,
        Command::Activate { contract_id, .. }
        | Command::ReportReady { contract_id, .. }
        | Command::Discharge { contract_id, .. }
        | Command::Challenge { contract_id, .. }
        | Command::Resume { contract_id, .. }
        | Command::Release { contract_id, .. } => state
            .contracts
            .get(contract_id)
            .is_none_or(|contract| contract.scope == scope),
    }
}

fn event_hash(
    previous_hash: &str,
    sequence: u64,
    command_json: &str,
    decision_json: &str,
) -> Result<String, serde_json::Error> {
    let encoded = serde_json::to_vec(&(previous_hash, sequence, command_json, decision_json))?;
    Ok(format!("{:x}", Sha256::digest(encoded)))
}

#[cfg(test)]
#[path = "ledger_tests.rs"]
mod tests;
