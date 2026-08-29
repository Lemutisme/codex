use serde::Serialize;
use sqlx::Row;
use sqlx::SqlitePool;
use thiserror::Error;

pub(crate) const MAX_EXECUTION_POLICY_BYTES: usize = 2_048;

#[derive(Clone, Debug)]
pub(crate) struct BindingStore {
    pool: SqlitePool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ExecutionBinding {
    pub(crate) contract_id: String,
    pub(crate) revision: u64,
    pub(crate) execution_policy: Option<String>,
}

#[derive(Debug, Error)]
pub(crate) enum BindingError {
    #[error("execution policy must not be empty")]
    EmptyPolicy,
    #[error("execution policy exceeds {MAX_EXECUTION_POLICY_BYTES} bytes")]
    PolicyTooLarge,
    #[error("execution binding already exists with different coordinates")]
    Conflict,
    #[error("execution binding operation failed")]
    Database(#[from] sqlx::Error),
}

impl BindingStore {
    pub(crate) async fn initialize(pool: SqlitePool) -> Result<Self, BindingError> {
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_binding (
                scope TEXT PRIMARY KEY NOT NULL,
                contract_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                execution_policy TEXT
            )",
        )
        .execute(&pool)
        .await?;
        Ok(Self { pool })
    }

    pub(crate) async fn bind_once(
        &self,
        scope: &str,
        contract_id: &str,
        revision: u64,
        execution_policy: Option<String>,
    ) -> Result<ExecutionBinding, BindingError> {
        if execution_policy
            .as_ref()
            .is_some_and(|policy| policy.trim().is_empty())
        {
            return Err(BindingError::EmptyPolicy);
        }
        if execution_policy
            .as_ref()
            .is_some_and(|policy| policy.len() > MAX_EXECUTION_POLICY_BYTES)
        {
            return Err(BindingError::PolicyTooLarge);
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        sqlx::query(
            "INSERT OR IGNORE INTO pro_contract_binding
             (scope, contract_id, revision, execution_policy) VALUES (?, ?, ?, ?)",
        )
        .bind(scope)
        .bind(contract_id)
        .bind(revision as i64)
        .bind(&execution_policy)
        .execute(&mut *transaction)
        .await?;
        let row = sqlx::query(
            "SELECT contract_id, revision, execution_policy
             FROM pro_contract_binding WHERE scope = ?",
        )
        .bind(scope)
        .fetch_one(&mut *transaction)
        .await?;
        let binding = ExecutionBinding {
            contract_id: row.try_get("contract_id")?,
            revision: row.try_get::<i64, _>("revision")? as u64,
            execution_policy: row.try_get("execution_policy")?,
        };
        if binding.contract_id != contract_id
            || binding.revision != revision
            || binding.execution_policy != execution_policy
        {
            return Err(BindingError::Conflict);
        }
        transaction.commit().await?;
        Ok(binding)
    }

    pub(crate) async fn get(&self, scope: &str) -> Result<Option<ExecutionBinding>, BindingError> {
        let row = sqlx::query(
            "SELECT contract_id, revision, execution_policy
             FROM pro_contract_binding WHERE scope = ?",
        )
        .bind(scope)
        .fetch_optional(&self.pool)
        .await?;
        row.map(|row| {
            Ok(ExecutionBinding {
                contract_id: row.try_get("contract_id")?,
                revision: row.try_get::<i64, _>("revision")? as u64,
                execution_policy: row.try_get("execution_policy")?,
            })
        })
        .transpose()
    }
}
