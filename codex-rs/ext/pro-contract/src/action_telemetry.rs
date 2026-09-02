use crate::binding::ExecutionBinding;
use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolName;
use codex_extension_api::ToolPayload;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use thiserror::Error;

const LONG_ACTION_MS: u64 = 60_000;
const MAX_ACTIONS_PER_ATTEMPT: u64 = 100_000;

#[derive(Clone)]
pub(crate) struct ActionTelemetryStore {
    pool: SqlitePool,
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) struct ActionReminder {
    pub(crate) sequence: u64,
    pub(crate) text: String,
}

#[derive(Debug, Error)]
pub(crate) enum ActionTelemetryError {
    #[error("action telemetry conflicts with an existing call")]
    Conflict,
    #[error("action telemetry exceeds its bounded attempt limit")]
    Limit,
    #[error("action telemetry database is corrupt")]
    Corrupt,
    #[error(transparent)]
    Database(#[from] sqlx::Error),
}

impl ActionTelemetryStore {
    pub(crate) async fn initialize(pool: SqlitePool) -> Result<Self, sqlx::Error> {
        let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_action_telemetry (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                call_key TEXT UNIQUE NOT NULL,
                attempt_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                outcome TEXT,
                repeat_ordinal INTEGER NOT NULL
            )",
        )
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            "CREATE INDEX IF NOT EXISTS pro_contract_action_attempt_idx
             ON pro_contract_action_telemetry(attempt_id, sequence)",
        )
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(Self { pool })
    }

    pub(crate) async fn admit(
        &self,
        binding: &ExecutionBinding,
        call_id: &str,
        tool_name: &ToolName,
        payload: &ToolPayload,
        now: u64,
    ) -> Result<(), ActionTelemetryError> {
        let attempt_id = attempt_id(binding);
        let call_key = call_key(&binding.contract_id, call_id);
        let fingerprint = fingerprint(tool_name, payload);
        let tool_name = tool_name.to_string();
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        if let Some(row) = sqlx::query(
            "SELECT attempt_id, fingerprint, tool_name
             FROM pro_contract_action_telemetry WHERE call_key = ?",
        )
        .bind(&call_key)
        .fetch_optional(&mut *transaction)
        .await?
        {
            if row.try_get::<String, _>("attempt_id")? != attempt_id
                || row.try_get::<String, _>("fingerprint")? != fingerprint
                || row.try_get::<String, _>("tool_name")? != tool_name
            {
                return Err(ActionTelemetryError::Conflict);
            }
            return Ok(());
        }
        let action_count = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM pro_contract_action_telemetry WHERE attempt_id = ?",
        )
        .bind(&attempt_id)
        .fetch_one(&mut *transaction)
        .await?;
        if unsigned(action_count)? >= MAX_ACTIONS_PER_ATTEMPT {
            return Err(ActionTelemetryError::Limit);
        }
        let prior_repeats = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM pro_contract_action_telemetry
             WHERE attempt_id = ? AND fingerprint = ?",
        )
        .bind(&attempt_id)
        .bind(&fingerprint)
        .fetch_one(&mut *transaction)
        .await?;
        sqlx::query(
            "INSERT INTO pro_contract_action_telemetry
             (call_key, attempt_id, fingerprint, tool_name, started_at, repeat_ordinal)
             VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(call_key)
        .bind(attempt_id)
        .bind(fingerprint)
        .bind(tool_name)
        .bind(integer(now))
        .bind(prior_repeats.saturating_add(1))
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(())
    }

    pub(crate) async fn finish(
        &self,
        contract_id: &str,
        call_id: &str,
        outcome: ToolCallOutcome,
        now: u64,
    ) -> Result<(), ActionTelemetryError> {
        let result = sqlx::query(
            "UPDATE pro_contract_action_telemetry
             SET finished_at = ?, outcome = ?
             WHERE call_key = ? AND finished_at IS NULL",
        )
        .bind(integer(now))
        .bind(outcome_name(outcome))
        .bind(call_key(contract_id, call_id))
        .execute(&self.pool)
        .await?;
        if result.rows_affected() > 1 {
            return Err(ActionTelemetryError::Corrupt);
        }
        Ok(())
    }

    pub(crate) async fn reminder(
        &self,
        binding: &ExecutionBinding,
        after_sequence: u64,
    ) -> Result<Option<ActionReminder>, ActionTelemetryError> {
        let row = sqlx::query(
            "SELECT sequence, tool_name, started_at, finished_at, repeat_ordinal
             FROM pro_contract_action_telemetry
             WHERE attempt_id = ? AND sequence > ? AND finished_at IS NOT NULL
               AND (repeat_ordinal > 1 OR finished_at - started_at >= ?)
             ORDER BY sequence DESC LIMIT 1",
        )
        .bind(attempt_id(binding))
        .bind(integer(after_sequence))
        .bind(integer(LONG_ACTION_MS))
        .fetch_optional(&self.pool)
        .await?;
        row.map(|row| {
            let sequence = unsigned(row.try_get("sequence")?)?;
            let tool_name = row.try_get::<String, _>("tool_name")?;
            let started_at = unsigned(row.try_get("started_at")?)?;
            let finished_at = unsigned(row.try_get("finished_at")?)?;
            let repeat_ordinal = unsigned(row.try_get("repeat_ordinal")?)?;
            let duration_ms = finished_at.saturating_sub(started_at);
            let text = if repeat_ordinal > 1 {
                format!(
                    "Host action telemetry: exact `{tool_name}` request occurrence {repeat_ordinal} in this semantic attempt; the last call took {duration_ms} ms. Repetition is cost, not evidence of progress. Continue only for changed external state or a live hypothesis; otherwise change action or preserve the uncertainty."
                )
            } else {
                format!(
                    "Host action telemetry: the last `{tool_name}` action took {duration_ms} ms. Long execution is cost, not evidence of progress. Continue it only while it can discriminate a live hypothesis; otherwise use a bounded targeted action or preserve the uncertainty."
                )
            };
            Ok(ActionReminder { sequence, text })
        })
        .transpose()
    }
}

fn attempt_id(binding: &ExecutionBinding) -> String {
    digest(&[
        b"codex.procontract.action.attempt.v1",
        binding.contract_id.as_bytes(),
        &binding.revision.to_le_bytes(),
        &binding.attempts.to_le_bytes(),
        binding.attempt_key.as_bytes(),
    ])
}

fn call_key(contract_id: &str, call_id: &str) -> String {
    digest(&[
        b"codex.procontract.action.call.v1",
        contract_id.as_bytes(),
        call_id.as_bytes(),
    ])
}

fn fingerprint(tool_name: &ToolName, payload: &ToolPayload) -> String {
    let tool_name = tool_name.to_string();
    match payload {
        ToolPayload::Function { arguments } => digest(&[
            b"codex.procontract.action.fingerprint.v1",
            tool_name.as_bytes(),
            b"function",
            arguments.as_bytes(),
        ]),
        ToolPayload::ToolSearch { arguments } => {
            let limit = arguments
                .limit
                .map(|limit| limit.to_string())
                .unwrap_or_default();
            digest(&[
                b"codex.procontract.action.fingerprint.v1",
                tool_name.as_bytes(),
                b"tool_search",
                arguments.query.as_bytes(),
                limit.as_bytes(),
            ])
        }
        ToolPayload::Custom { input } => digest(&[
            b"codex.procontract.action.fingerprint.v1",
            tool_name.as_bytes(),
            b"custom",
            input.as_bytes(),
        ]),
    }
}

fn outcome_name(outcome: ToolCallOutcome) -> &'static str {
    match outcome {
        ToolCallOutcome::Completed { success: true } => "success",
        ToolCallOutcome::Completed { success: false } => "completed_error",
        ToolCallOutcome::Blocked => "blocked",
        ToolCallOutcome::Failed {
            handler_executed: true,
        } => "handler_failed",
        ToolCallOutcome::Failed {
            handler_executed: false,
        } => "dispatch_failed",
        ToolCallOutcome::Aborted => "aborted",
    }
}

fn digest(parts: &[&[u8]]) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        hasher.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_le_bytes());
        hasher.update(part);
    }
    format!("{:x}", hasher.finalize())
}

fn unsigned(value: i64) -> Result<u64, ActionTelemetryError> {
    u64::try_from(value).map_err(|_| ActionTelemetryError::Corrupt)
}

fn integer(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

#[cfg(test)]
#[path = "action_telemetry_tests.rs"]
mod tests;
