use serde::Serialize;
use sqlx::Row;
use sqlx::SqlitePool;
use std::collections::BTreeSet;
use thiserror::Error;

const MAX_REPORTS_PER_ATTEMPT: u64 = 4_096;
const MAX_REQUESTS_PER_ATTEMPT: u64 = 4_096;

#[derive(Clone)]
pub(crate) struct ProbeFrontierStore {
    pool: SqlitePool,
}

pub(super) struct ObservationRecord {
    pub(super) report_hash: String,
    pub(super) attempt_id: String,
    pub(super) candidate_coordinate_hash: String,
    pub(super) request_hashes: Vec<String>,
    pub(super) byte_equal_count: u64,
    pub(super) wall_duration_ms: u64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct FrontierSummary {
    candidate_coordinate_changed: bool,
    new_attempt_request_count: u64,
    new_candidate_request_count: u64,
    repeated_candidate_request_count: u64,
    attempt_unique_request_count: u64,
    candidate_unique_request_count: u64,
    attempt_report_count: u64,
    attempt_execution_count: u64,
    attempt_wall_duration_ms: u64,
}

#[derive(Debug, Error)]
pub(super) enum FrontierError {
    #[error("probe frontier conflicts with an existing report")]
    Conflict,
    #[error("probe frontier exceeds its bounded attempt limit")]
    Limit,
    #[error("probe frontier database is corrupt")]
    Corrupt,
    #[error(transparent)]
    Database(#[from] sqlx::Error),
}

impl ProbeFrontierStore {
    pub(crate) async fn initialize(pool: SqlitePool) -> Result<Self, sqlx::Error> {
        let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
        for statement in [
            "CREATE TABLE IF NOT EXISTS pro_contract_probe_report (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                report_hash TEXT UNIQUE NOT NULL,
                attempt_id TEXT NOT NULL,
                candidate_coordinate_hash TEXT NOT NULL,
                case_count INTEGER NOT NULL,
                byte_equal_count INTEGER NOT NULL,
                wall_duration_ms INTEGER NOT NULL,
                candidate_coordinate_changed INTEGER NOT NULL,
                new_attempt_requests INTEGER NOT NULL,
                new_candidate_requests INTEGER NOT NULL,
                repeated_candidate_requests INTEGER NOT NULL,
                attempt_unique_requests INTEGER NOT NULL,
                candidate_unique_requests INTEGER NOT NULL,
                attempt_report_count INTEGER NOT NULL,
                attempt_execution_count INTEGER NOT NULL,
                attempt_wall_duration_ms INTEGER NOT NULL
            )",
            "CREATE INDEX IF NOT EXISTS pro_contract_probe_report_attempt_idx
             ON pro_contract_probe_report(attempt_id, sequence)",
            "CREATE TABLE IF NOT EXISTS pro_contract_probe_attempt_request (
                attempt_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                PRIMARY KEY (attempt_id, request_hash)
            )",
            "CREATE TABLE IF NOT EXISTS pro_contract_probe_candidate_request (
                attempt_id TEXT NOT NULL,
                candidate_coordinate_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                PRIMARY KEY (attempt_id, candidate_coordinate_hash, request_hash)
            )",
        ] {
            sqlx::query(statement).execute(&mut *transaction).await?;
        }
        transaction.commit().await?;
        Ok(Self { pool })
    }

    pub(super) async fn record(
        &self,
        record: ObservationRecord,
    ) -> Result<FrontierSummary, FrontierError> {
        let case_count =
            u64::try_from(record.request_hashes.len()).map_err(|_| FrontierError::Limit)?;
        if record.byte_equal_count > case_count
            || record.report_hash.is_empty()
            || record.attempt_id.is_empty()
            || record.candidate_coordinate_hash.is_empty()
            || record.request_hashes.iter().any(String::is_empty)
        {
            return Err(FrontierError::Conflict);
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        if let Some(row) = sqlx::query(
            "SELECT attempt_id, candidate_coordinate_hash, case_count, byte_equal_count,
                    wall_duration_ms, candidate_coordinate_changed, new_attempt_requests,
                    new_candidate_requests, repeated_candidate_requests,
                    attempt_unique_requests, candidate_unique_requests,
                    attempt_report_count, attempt_execution_count,
                    attempt_wall_duration_ms
             FROM pro_contract_probe_report WHERE report_hash = ?",
        )
        .bind(&record.report_hash)
        .fetch_optional(&mut *transaction)
        .await?
        {
            if row.try_get::<String, _>("attempt_id")? != record.attempt_id
                || row.try_get::<String, _>("candidate_coordinate_hash")?
                    != record.candidate_coordinate_hash
                || unsigned(&row, "case_count")? != case_count
                || unsigned(&row, "byte_equal_count")? != record.byte_equal_count
                || unsigned(&row, "wall_duration_ms")? != record.wall_duration_ms
            {
                return Err(FrontierError::Conflict);
            }
            return summary(&row);
        }

        let totals = sqlx::query(
            "SELECT COUNT(*) AS report_count,
                    COALESCE(SUM(case_count), 0) AS case_count,
                    COALESCE(SUM(wall_duration_ms), 0) AS wall_duration_ms
             FROM pro_contract_probe_report WHERE attempt_id = ?",
        )
        .bind(&record.attempt_id)
        .fetch_one(&mut *transaction)
        .await?;
        let prior_reports = unsigned(&totals, "report_count")?;
        if prior_reports >= MAX_REPORTS_PER_ATTEMPT {
            return Err(FrontierError::Limit);
        }
        let previous_candidate = sqlx::query_scalar::<_, String>(
            "SELECT candidate_coordinate_hash FROM pro_contract_probe_report
             WHERE attempt_id = ? ORDER BY sequence DESC LIMIT 1",
        )
        .bind(&record.attempt_id)
        .fetch_optional(&mut *transaction)
        .await?;
        let candidate_coordinate_changed = previous_candidate
            .as_deref()
            .is_some_and(|previous| previous != record.candidate_coordinate_hash);

        let unique_requests = record.request_hashes.iter().collect::<BTreeSet<_>>();
        let mut new_attempt_requests = 0_u64;
        let mut new_candidate_requests = 0_u64;
        for request_hash in unique_requests {
            new_attempt_requests += sqlx::query(
                "INSERT OR IGNORE INTO pro_contract_probe_attempt_request
                 (attempt_id, request_hash) VALUES (?, ?)",
            )
            .bind(&record.attempt_id)
            .bind(request_hash)
            .execute(&mut *transaction)
            .await?
            .rows_affected();
            new_candidate_requests += sqlx::query(
                "INSERT OR IGNORE INTO pro_contract_probe_candidate_request
                 (attempt_id, candidate_coordinate_hash, request_hash) VALUES (?, ?, ?)",
            )
            .bind(&record.attempt_id)
            .bind(&record.candidate_coordinate_hash)
            .bind(request_hash)
            .execute(&mut *transaction)
            .await?
            .rows_affected();
        }
        let attempt_unique_requests =
            count_attempt_requests(&mut transaction, &record.attempt_id).await?;
        if attempt_unique_requests > MAX_REQUESTS_PER_ATTEMPT {
            return Err(FrontierError::Limit);
        }
        let candidate_unique_requests = count_candidate_requests(
            &mut transaction,
            &record.attempt_id,
            &record.candidate_coordinate_hash,
        )
        .await?;
        let frontier = FrontierSummary {
            candidate_coordinate_changed,
            new_attempt_request_count: new_attempt_requests,
            new_candidate_request_count: new_candidate_requests,
            repeated_candidate_request_count: case_count.saturating_sub(new_candidate_requests),
            attempt_unique_request_count: attempt_unique_requests,
            candidate_unique_request_count: candidate_unique_requests,
            attempt_report_count: prior_reports + 1,
            attempt_execution_count: unsigned(&totals, "case_count")?
                .saturating_add(case_count)
                .saturating_mul(2),
            attempt_wall_duration_ms: unsigned(&totals, "wall_duration_ms")?
                .saturating_add(record.wall_duration_ms),
        };
        sqlx::query(
            "INSERT INTO pro_contract_probe_report
             (report_hash, attempt_id, candidate_coordinate_hash, case_count,
              byte_equal_count, wall_duration_ms, candidate_coordinate_changed,
              new_attempt_requests, new_candidate_requests, repeated_candidate_requests,
              attempt_unique_requests, candidate_unique_requests,
              attempt_report_count, attempt_execution_count, attempt_wall_duration_ms)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&record.report_hash)
        .bind(&record.attempt_id)
        .bind(&record.candidate_coordinate_hash)
        .bind(integer(case_count))
        .bind(integer(record.byte_equal_count))
        .bind(integer(record.wall_duration_ms))
        .bind(frontier.candidate_coordinate_changed)
        .bind(integer(frontier.new_attempt_request_count))
        .bind(integer(frontier.new_candidate_request_count))
        .bind(integer(frontier.repeated_candidate_request_count))
        .bind(integer(frontier.attempt_unique_request_count))
        .bind(integer(frontier.candidate_unique_request_count))
        .bind(integer(frontier.attempt_report_count))
        .bind(integer(frontier.attempt_execution_count))
        .bind(integer(frontier.attempt_wall_duration_ms))
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(frontier)
    }
}

async fn count_attempt_requests(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    attempt_id: &str,
) -> Result<u64, FrontierError> {
    let count = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM pro_contract_probe_attempt_request WHERE attempt_id = ?",
    )
    .bind(attempt_id)
    .fetch_one(&mut **transaction)
    .await?;
    u64::try_from(count).map_err(|_| FrontierError::Corrupt)
}

async fn count_candidate_requests(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    attempt_id: &str,
    candidate_coordinate_hash: &str,
) -> Result<u64, FrontierError> {
    let count = sqlx::query_scalar::<_, i64>(
        "SELECT COUNT(*) FROM pro_contract_probe_candidate_request
         WHERE attempt_id = ? AND candidate_coordinate_hash = ?",
    )
    .bind(attempt_id)
    .bind(candidate_coordinate_hash)
    .fetch_one(&mut **transaction)
    .await?;
    u64::try_from(count).map_err(|_| FrontierError::Corrupt)
}

fn summary(row: &sqlx::sqlite::SqliteRow) -> Result<FrontierSummary, FrontierError> {
    Ok(FrontierSummary {
        candidate_coordinate_changed: row.try_get("candidate_coordinate_changed")?,
        new_attempt_request_count: unsigned(row, "new_attempt_requests")?,
        new_candidate_request_count: unsigned(row, "new_candidate_requests")?,
        repeated_candidate_request_count: unsigned(row, "repeated_candidate_requests")?,
        attempt_unique_request_count: unsigned(row, "attempt_unique_requests")?,
        candidate_unique_request_count: unsigned(row, "candidate_unique_requests")?,
        attempt_report_count: unsigned(row, "attempt_report_count")?,
        attempt_execution_count: unsigned(row, "attempt_execution_count")?,
        attempt_wall_duration_ms: unsigned(row, "attempt_wall_duration_ms")?,
    })
}

fn unsigned(row: &sqlx::sqlite::SqliteRow, name: &str) -> Result<u64, FrontierError> {
    u64::try_from(row.try_get::<i64, _>(name)?).map_err(|_| FrontierError::Corrupt)
}

fn integer(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}
