use super::*;

impl BindingStore {
    pub(crate) async fn initialize(
        pool: SqlitePool,
        owner: impl Into<String>,
    ) -> Result<Self, BindingError> {
        let mut transaction = pool.begin_with("BEGIN IMMEDIATE").await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_binding (
                scope TEXT PRIMARY KEY NOT NULL,
                ledger_scope TEXT NOT NULL DEFAULT '',
                contract_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                execution_policy TEXT,
                execution_policy_hash TEXT,
                dispatched INTEGER NOT NULL DEFAULT 0,
                resume_same_attempt INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                turns_used INTEGER NOT NULL DEFAULT 0,
                actions_used INTEGER NOT NULL DEFAULT 0,
                next_action_at INTEGER NOT NULL DEFAULT 0,
                attempt_key TEXT NOT NULL DEFAULT '',
                turns_limit INTEGER NOT NULL DEFAULT 1,
                actions_limit INTEGER NOT NULL DEFAULT 1,
                deadline INTEGER NOT NULL DEFAULT 1,
                max_attempts INTEGER NOT NULL DEFAULT 1,
                lease_owner TEXT,
                lease_expires_at INTEGER NOT NULL DEFAULT 0
            )",
        )
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS pro_contract_binding_session (
                scope TEXT PRIMARY KEY NOT NULL,
                contract_id TEXT NOT NULL,
                ledger_scope TEXT NOT NULL
            )",
        )
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            "CREATE UNIQUE INDEX IF NOT EXISTS pro_contract_binding_contract_idx
             ON pro_contract_binding(contract_id)",
        )
        .execute(&mut *transaction)
        .await?;
        for (name, statement) in [
            (
                "ledger_scope",
                "ALTER TABLE pro_contract_binding ADD COLUMN ledger_scope TEXT NOT NULL DEFAULT ''",
            ),
            (
                "execution_policy_hash",
                "ALTER TABLE pro_contract_binding ADD COLUMN execution_policy_hash TEXT",
            ),
            (
                "dispatched",
                "ALTER TABLE pro_contract_binding ADD COLUMN dispatched INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "resume_same_attempt",
                "ALTER TABLE pro_contract_binding ADD COLUMN resume_same_attempt INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "attempts",
                "ALTER TABLE pro_contract_binding ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "turns_used",
                "ALTER TABLE pro_contract_binding ADD COLUMN turns_used INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "actions_used",
                "ALTER TABLE pro_contract_binding ADD COLUMN actions_used INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "next_action_at",
                "ALTER TABLE pro_contract_binding ADD COLUMN next_action_at INTEGER NOT NULL DEFAULT 0",
            ),
            (
                "attempt_key",
                "ALTER TABLE pro_contract_binding ADD COLUMN attempt_key TEXT NOT NULL DEFAULT ''",
            ),
            (
                "turns_limit",
                "ALTER TABLE pro_contract_binding ADD COLUMN turns_limit INTEGER NOT NULL DEFAULT 1",
            ),
            (
                "actions_limit",
                "ALTER TABLE pro_contract_binding ADD COLUMN actions_limit INTEGER NOT NULL DEFAULT 1",
            ),
            (
                "deadline",
                "ALTER TABLE pro_contract_binding ADD COLUMN deadline INTEGER NOT NULL DEFAULT 1",
            ),
            (
                "max_attempts",
                "ALTER TABLE pro_contract_binding ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 1",
            ),
            (
                "lease_owner",
                "ALTER TABLE pro_contract_binding ADD COLUMN lease_owner TEXT",
            ),
            (
                "lease_expires_at",
                "ALTER TABLE pro_contract_binding ADD COLUMN lease_expires_at INTEGER NOT NULL DEFAULT 0",
            ),
        ] {
            ensure_column(&mut transaction, name, statement).await?;
        }
        let ledger_initialized = sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM sqlite_master
             WHERE type = 'table' AND name = 'pro_contract_projection'",
        )
        .fetch_one(&mut *transaction)
        .await?
            != 0;
        if ledger_initialized {
            sqlx::query(
                "UPDATE pro_contract_binding
                 SET ledger_scope = COALESCE(
                     (SELECT projection.scope
                      FROM pro_contract_projection AS projection,
                           json_each(projection.state_json, '$.contracts') AS contract
                      WHERE json_extract(contract.value, '$.id') = pro_contract_binding.contract_id
                      LIMIT 1),
                     scope)
                 WHERE ledger_scope = ''",
            )
            .execute(&mut *transaction)
            .await?;
        }
        sqlx::query(
            "INSERT OR IGNORE INTO pro_contract_binding_session (scope, contract_id, ledger_scope)
             SELECT scope, contract_id, ledger_scope FROM pro_contract_binding",
        )
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(Self {
            pool,
            owner: owner.into(),
        })
    }
}

async fn ensure_column(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    name: &str,
    statement: &'static str,
) -> Result<(), BindingError> {
    let columns = sqlx::query("PRAGMA table_info(pro_contract_binding)")
        .fetch_all(&mut **transaction)
        .await?;
    if columns
        .iter()
        .any(|column| column.try_get::<String, _>("name").ok().as_deref() == Some(name))
    {
        return Ok(());
    }
    sqlx::query(statement).execute(&mut **transaction).await?;
    Ok(())
}
