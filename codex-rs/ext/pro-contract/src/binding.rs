use codex_pro_contract::ChallengeDisclosure;
use codex_pro_contract::Contract;
use codex_pro_contract::State;
use codex_pro_contract::Status;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteRow;
use thiserror::Error;

mod schema;
mod types;

pub(crate) use types::*;

pub(crate) const MAX_EXECUTION_POLICY_BYTES: usize = 2_048;

#[derive(Clone, Debug)]
pub(crate) struct BindingStore {
    pool: SqlitePool,
    owner: String,
}

#[derive(Debug, Error)]
pub(crate) enum BindingError {
    #[error("execution policy must not be empty")]
    EmptyPolicy,
    #[error("execution policy exceeds {MAX_EXECUTION_POLICY_BYTES} bytes")]
    PolicyTooLarge,
    #[error("stored execution policy hash does not match its instructions")]
    PolicyHashMismatch,
    #[error("execution limits must be positive")]
    InvalidLimits,
    #[error("execution binding already exists with different coordinates")]
    Conflict,
    #[error("execution binding not found")]
    NotFound,
    #[error("execution binding operation failed")]
    Database(#[from] sqlx::Error),
    #[error("contract projection is corrupt")]
    CorruptState(#[from] serde_json::Error),
}

impl BindingStore {
    pub(crate) async fn bind_once(
        &self,
        scope: &str,
        ledger_scope: &str,
        contract_id: &str,
        revision: u64,
        execution_policy: Option<String>,
        limits: ExecutionLimits,
    ) -> Result<ExecutionBinding, BindingError> {
        validate_policy(execution_policy.as_deref())?;
        let execution_policy_hash = execution_policy.as_deref().map(hash_execution_policy);
        if limits.turns == 0
            || limits.actions == 0
            || limits.deadline == 0
            || limits.max_attempts == 0
        {
            return Err(BindingError::InvalidLimits);
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        sqlx::query(
            "INSERT OR IGNORE INTO pro_contract_binding
             (scope, ledger_scope, contract_id, revision, execution_policy, execution_policy_hash,
              dispatched, attempt_key,
              turns_limit, actions_limit,
              deadline, max_attempts)
             VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)",
        )
        .bind(scope)
        .bind(ledger_scope)
        .bind(contract_id)
        .bind(revision as i64)
        .bind(&execution_policy)
        .bind(&execution_policy_hash)
        .bind(format!("{revision}:"))
        .bind(limits.turns as i64)
        .bind(limits.actions as i64)
        .bind(limits.deadline as i64)
        .bind(limits.max_attempts as i64)
        .execute(&mut *transaction)
        .await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        if binding.ledger_scope != ledger_scope
            || binding.contract_id != contract_id
            || binding.revision != revision
            || binding.execution_policy != execution_policy
            || binding.execution_policy_hash != execution_policy_hash
            || binding.attempt_key != format!("{revision}:")
            || binding.turns_limit != limits.turns
            || binding.actions_limit != limits.actions
            || binding.deadline != limits.deadline
            || binding.max_attempts != limits.max_attempts
        {
            return Err(BindingError::Conflict);
        }
        sqlx::query(
            "INSERT OR IGNORE INTO pro_contract_binding_session (scope, contract_id, ledger_scope)
             VALUES (?, ?, ?)",
        )
        .bind(scope)
        .bind(contract_id)
        .bind(ledger_scope)
        .execute(&mut *transaction)
        .await?;
        transaction.commit().await?;
        Ok(binding)
    }

    pub(crate) async fn begin_attempt(
        &self,
        scope: &str,
        now: u64,
    ) -> Result<Reservation, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        let contract = contract_at_active_revision(&mut transaction, &binding).await?;
        if now >= binding.deadline {
            transaction.commit().await?;
            return Ok(Reservation::Denied {
                reason: ReservationDenial::Deadline,
            });
        }
        let Some(contract) = contract.filter(|contract| contract.pending_revision.is_none()) else {
            transaction.commit().await?;
            return Ok(Reservation::Denied {
                reason: ReservationDenial::ContractInactive,
            });
        };
        let reservation = if now < binding.next_action_at {
            Reservation::Denied {
                reason: ReservationDenial::NotDue,
            }
        } else if binding
            .lease_owner
            .as_deref()
            .is_some_and(|owner| owner != self.owner)
            && binding.lease_expires_at > now
        {
            Reservation::Denied {
                reason: ReservationDenial::LeaseHeld,
            }
        } else if binding.attempts >= binding.max_attempts {
            Reservation::Denied {
                reason: ReservationDenial::AttemptBudget,
            }
        } else {
            sqlx::query(
                "UPDATE pro_contract_binding SET attempts = attempts + 1,
                 dispatched = 1, resume_same_attempt = 0, next_action_at = 0,
                 attempt_key = ?, lease_owner = ?, lease_expires_at = ? WHERE scope = ?",
            )
            .bind(contract_attempt_key(&contract))
            .bind(&self.owner)
            .bind(lease_expiry(now, binding.deadline) as i64)
            .bind(scope)
            .execute(&mut *transaction)
            .await?;
            Reservation::Reserved(Box::new(fetch_binding(&mut transaction, scope).await?))
        };
        transaction.commit().await?;
        Ok(reservation)
    }

    pub(crate) async fn begin_new_attempt(
        &self,
        contract_id: &str,
        new_scope: &str,
        now: u64,
    ) -> Result<Reservation, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let row = sqlx::query(BINDING_BY_CONTRACT_SELECT)
            .bind(contract_id)
            .fetch_optional(&mut *transaction)
            .await?;
        let Some(binding) = row.map(binding_from_row).transpose()? else {
            transaction.commit().await?;
            return Err(BindingError::NotFound);
        };
        let contract = contract_at_active_revision(&mut transaction, &binding).await?;
        if now >= binding.deadline {
            transaction.commit().await?;
            return Ok(Reservation::Denied {
                reason: ReservationDenial::Deadline,
            });
        }
        let Some(contract) = contract.filter(|contract| contract.pending_revision.is_none()) else {
            transaction.commit().await?;
            return Ok(Reservation::Denied {
                reason: ReservationDenial::ContractInactive,
            });
        };
        let reservation = if now < binding.next_action_at {
            Reservation::Denied {
                reason: ReservationDenial::NotDue,
            }
        } else if binding.lease_owner.as_deref() != Some(self.owner.as_str())
            && binding.lease_expires_at > now
        {
            Reservation::Denied {
                reason: ReservationDenial::LeaseHeld,
            }
        } else if binding.attempts >= binding.max_attempts {
            Reservation::Denied {
                reason: ReservationDenial::AttemptBudget,
            }
        } else {
            sqlx::query(
                "UPDATE pro_contract_binding SET scope = ?, attempts = attempts + 1,
                 dispatched = 1, resume_same_attempt = 0, next_action_at = 0,
                 attempt_key = ?, lease_owner = ?, lease_expires_at = ? WHERE contract_id = ?",
            )
            .bind(new_scope)
            .bind(contract_attempt_key(&contract))
            .bind(&self.owner)
            .bind(lease_expiry(now, binding.deadline) as i64)
            .bind(contract_id)
            .execute(&mut *transaction)
            .await?;
            sqlx::query(
                "INSERT OR IGNORE INTO pro_contract_binding_session
                 (scope, contract_id, ledger_scope) VALUES (?, ?, ?)",
            )
            .bind(new_scope)
            .bind(contract_id)
            .bind(&binding.ledger_scope)
            .execute(&mut *transaction)
            .await?;
            Reservation::Reserved(Box::new(fetch_binding(&mut transaction, new_scope).await?))
        };
        transaction.commit().await?;
        Ok(reservation)
    }

    pub(crate) async fn revise_contract(
        &self,
        contract_id: &str,
        revision: u64,
        limits: ExecutionLimits,
    ) -> Result<ExecutionBinding, BindingError> {
        if limits.turns == 0
            || limits.actions == 0
            || limits.deadline == 0
            || limits.max_attempts == 0
        {
            return Err(BindingError::InvalidLimits);
        }
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let result = sqlx::query(
            "UPDATE pro_contract_binding SET revision = ?, dispatched = 0,
             resume_same_attempt = 0, next_action_at = 0,
             turns_limit = ?, actions_limit = ?,
             deadline = ?, max_attempts = ?, lease_owner = NULL, lease_expires_at = 0
             WHERE contract_id = ?",
        )
        .bind(revision as i64)
        .bind(limits.turns as i64)
        .bind(limits.actions as i64)
        .bind(limits.deadline as i64)
        .bind(limits.max_attempts as i64)
        .bind(contract_id)
        .execute(&mut *transaction)
        .await?;
        if result.rows_affected() != 1 {
            return Err(BindingError::NotFound);
        }
        let row = sqlx::query(
            "SELECT scope, ledger_scope, contract_id, revision, execution_policy,
                    execution_policy_hash, dispatched,
                    resume_same_attempt,
                    attempts, turns_used, actions_used, next_action_at, attempt_key,
                    turns_limit, actions_limit, deadline, max_attempts,
                    lease_owner, lease_expires_at
             FROM pro_contract_binding WHERE contract_id = ?",
        )
        .bind(contract_id)
        .fetch_one(&mut *transaction)
        .await?;
        let binding = binding_from_row(row)?;
        transaction.commit().await?;
        Ok(binding)
    }

    pub(crate) async fn claim_recovery(
        &self,
        contract_id: &str,
        new_scope: &str,
        now: u64,
    ) -> Result<Option<RecoveryClaim>, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let row = sqlx::query(BINDING_BY_CONTRACT_SELECT)
            .bind(contract_id)
            .fetch_optional(&mut *transaction)
            .await?;
        let Some(binding) = row.map(binding_from_row).transpose()? else {
            transaction.commit().await?;
            return Ok(None);
        };
        let contract = active_contract(&mut transaction, &binding).await?;
        if binding.lease_expires_at > now || binding.next_action_at > now || now >= binding.deadline
        {
            transaction.commit().await?;
            return Ok(None);
        }
        let Some(contract) = contract.filter(|contract| contract.pending_revision.is_none()) else {
            transaction.commit().await?;
            return Ok(None);
        };
        sqlx::query(
            "UPDATE pro_contract_binding SET scope = ?, dispatched = 0,
             lease_owner = ?, lease_expires_at = ?
             WHERE contract_id = ?",
        )
        .bind(new_scope)
        .bind(&self.owner)
        .bind(lease_expiry(now, binding.deadline) as i64)
        .bind(contract_id)
        .execute(&mut *transaction)
        .await?;
        sqlx::query(
            "INSERT OR IGNORE INTO pro_contract_binding_session (scope, contract_id, ledger_scope)
             VALUES (?, ?, ?)",
        )
        .bind(new_scope)
        .bind(contract_id)
        .bind(&binding.ledger_scope)
        .execute(&mut *transaction)
        .await?;
        let row = sqlx::query(BINDING_BY_CONTRACT_SELECT)
            .bind(contract_id)
            .fetch_one(&mut *transaction)
            .await?;
        let recovered = binding_from_row(row)?;
        transaction.commit().await?;
        Ok(Some(RecoveryClaim {
            binding: recovered,
            interrupted: binding.dispatched,
            context_changed: binding.attempt_key != contract_attempt_key(&contract),
        }))
    }

    pub(crate) async fn heartbeat(&self, scope: &str, now: u64) -> Result<bool, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        let owns_attempt = binding.dispatched || binding.resume_same_attempt;
        let renewed = owns_attempt
            && binding.lease_owner.as_deref() == Some(self.owner.as_str())
            && now < binding.deadline
            && contract_has_active_revision(&mut transaction, &binding).await?;
        if renewed {
            sqlx::query("UPDATE pro_contract_binding SET lease_expires_at = ? WHERE scope = ?")
                .bind(lease_expiry(now, binding.deadline) as i64)
                .bind(scope)
                .execute(&mut *transaction)
                .await?;
        }
        transaction.commit().await?;
        Ok(renewed)
    }

    pub(crate) async fn abandon_claim(&self, contract_id: &str) -> Result<(), BindingError> {
        sqlx::query(
            "UPDATE pro_contract_binding SET dispatched = 0,
             lease_owner = NULL, lease_expires_at = 0
             WHERE contract_id = ? AND lease_owner = ?",
        )
        .bind(contract_id)
        .bind(&self.owner)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub(crate) async fn record_interruption(&self, contract_id: &str) -> Result<(), BindingError> {
        sqlx::query(
            "UPDATE pro_contract_binding SET dispatched = 1,
             next_action_at = 0, lease_owner = NULL, lease_expires_at = 0
             WHERE contract_id = ? AND lease_owner = ?",
        )
        .bind(contract_id)
        .bind(&self.owner)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub(crate) async fn suspend_attempt(
        &self,
        scope: &str,
        schedule: AttemptSchedule,
    ) -> Result<(), BindingError> {
        match schedule {
            AttemptSchedule::AwaitRevision => {
                sqlx::query(
                    "UPDATE pro_contract_binding SET dispatched = 0,
                     resume_same_attempt = 1, next_action_at = 0
                     WHERE scope = ? AND lease_owner = ?",
                )
                .bind(scope)
                .bind(&self.owner)
                .execute(&self.pool)
                .await?;
            }
            AttemptSchedule::Immediate | AttemptSchedule::At(_) => {
                sqlx::query(
                    "UPDATE pro_contract_binding SET dispatched = 0,
                     resume_same_attempt = 0, next_action_at = ?,
                     lease_owner = NULL, lease_expires_at = 0
                     WHERE scope = ? AND lease_owner = ?",
                )
                .bind(schedule.next_action_at() as i64)
                .bind(scope)
                .bind(&self.owner)
                .execute(&self.pool)
                .await?;
            }
        }
        Ok(())
    }

    pub(crate) async fn resume_attempt(
        &self,
        scope: &str,
        now: u64,
    ) -> Result<ExecutionBinding, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        if now >= binding.deadline {
            return Err(BindingError::InvalidLimits);
        }
        sqlx::query(
            "UPDATE pro_contract_binding SET dispatched = 1,
             resume_same_attempt = 0, next_action_at = 0,
             lease_owner = ?, lease_expires_at = ? WHERE scope = ?",
        )
        .bind(&self.owner)
        .bind(lease_expiry(now, binding.deadline) as i64)
        .bind(scope)
        .execute(&mut *transaction)
        .await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        transaction.commit().await?;
        Ok(binding)
    }

    pub(crate) async fn reserve_turn(
        &self,
        scope: &str,
        now: u64,
    ) -> Result<Reservation, BindingError> {
        self.reserve(scope, now, ReservationKind::Turn).await
    }

    pub(crate) async fn reserve_action(
        &self,
        scope: &str,
        now: u64,
    ) -> Result<Reservation, BindingError> {
        self.reserve(scope, now, ReservationKind::Action).await
    }

    async fn reserve(
        &self,
        scope: &str,
        now: u64,
        kind: ReservationKind,
    ) -> Result<Reservation, BindingError> {
        let mut transaction = self.pool.begin_with("BEGIN IMMEDIATE").await?;
        let binding = fetch_binding(&mut transaction, scope).await?;
        let reservation = if now >= binding.deadline {
            Reservation::Denied {
                reason: ReservationDenial::Deadline,
            }
        } else if !contract_is_active(&mut transaction, &binding).await? {
            Reservation::Denied {
                reason: ReservationDenial::ContractInactive,
            }
        } else if now < binding.next_action_at {
            Reservation::Denied {
                reason: ReservationDenial::NotDue,
            }
        } else if !binding.dispatched || binding.attempts == 0 {
            Reservation::Denied {
                reason: ReservationDenial::AttemptInactive,
            }
        } else if binding.lease_owner.as_deref() != Some(self.owner.as_str())
            && binding.lease_expires_at > now
        {
            Reservation::Denied {
                reason: ReservationDenial::LeaseHeld,
            }
        } else if kind.used(&binding) >= kind.limit(&binding) {
            Reservation::Denied {
                reason: kind.denial(),
            }
        } else {
            sqlx::query(kind.increment_sql())
                .bind(&self.owner)
                .bind(lease_expiry(now, binding.deadline) as i64)
                .bind(scope)
                .execute(&mut *transaction)
                .await?;
            Reservation::Reserved(Box::new(fetch_binding(&mut transaction, scope).await?))
        };
        transaction.commit().await?;
        Ok(reservation)
    }

    pub(crate) async fn get(&self, scope: &str) -> Result<Option<ExecutionBinding>, BindingError> {
        sqlx::query(BINDING_SELECT)
            .bind(scope)
            .fetch_optional(&self.pool)
            .await?
            .map(binding_from_row)
            .transpose()
    }

    pub(crate) async fn get_by_contract(
        &self,
        contract_id: &str,
    ) -> Result<Option<ExecutionBinding>, BindingError> {
        sqlx::query(BINDING_BY_CONTRACT_SELECT)
            .bind(contract_id)
            .fetch_optional(&self.pool)
            .await?
            .map(binding_from_row)
            .transpose()
    }

    pub(crate) async fn for_session(
        &self,
        scope: &str,
    ) -> Result<Option<BoundSession>, BindingError> {
        let row = sqlx::query(
            "SELECT session.ledger_scope, session.contract_id,
                    binding.scope = session.scope AS current
             FROM pro_contract_binding_session AS session
             LEFT JOIN pro_contract_binding AS binding
               ON binding.contract_id = session.contract_id
             WHERE session.scope = ?",
        )
        .bind(scope)
        .fetch_optional(&self.pool)
        .await?;
        row.map(|row| {
            Ok(BoundSession {
                ledger_scope: row.try_get("ledger_scope")?,
                contract_id: row.try_get("contract_id")?,
                current: row.try_get::<i64, _>("current")? != 0,
            })
        })
        .transpose()
    }
}

const BINDING_SELECT: &str = "SELECT scope, ledger_scope, contract_id, revision, execution_policy,
            execution_policy_hash, dispatched,
            resume_same_attempt,
            attempts, turns_used, actions_used, next_action_at, attempt_key,
            turns_limit, actions_limit, deadline, max_attempts,
            lease_owner, lease_expires_at
     FROM pro_contract_binding WHERE scope = ?";

const BINDING_BY_CONTRACT_SELECT: &str =
    "SELECT scope, ledger_scope, contract_id, revision, execution_policy,
            execution_policy_hash, dispatched,
            resume_same_attempt,
            attempts, turns_used, actions_used, next_action_at, attempt_key,
            turns_limit, actions_limit, deadline, max_attempts,
            lease_owner, lease_expires_at
     FROM pro_contract_binding WHERE contract_id = ?";

async fn fetch_binding(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    scope: &str,
) -> Result<ExecutionBinding, BindingError> {
    let row = sqlx::query(BINDING_SELECT)
        .bind(scope)
        .fetch_optional(&mut **transaction)
        .await?
        .ok_or(BindingError::NotFound)?;
    binding_from_row(row)
}

async fn contract_is_active(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    binding: &ExecutionBinding,
) -> Result<bool, BindingError> {
    Ok(contract_at_active_revision(transaction, binding)
        .await?
        .is_some_and(|contract| contract.pending_revision.is_none()))
}

async fn contract_at_active_revision(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    binding: &ExecutionBinding,
) -> Result<Option<Contract>, BindingError> {
    Ok(active_contract(transaction, binding)
        .await?
        .filter(|contract| contract.revision == binding.revision))
}

async fn active_contract(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    binding: &ExecutionBinding,
) -> Result<Option<Contract>, BindingError> {
    let encoded = sqlx::query_scalar::<_, String>(
        "SELECT state_json FROM pro_contract_projection WHERE scope = ?",
    )
    .bind(&binding.ledger_scope)
    .fetch_optional(&mut **transaction)
    .await?;
    let Some(encoded) = encoded else {
        return Ok(None);
    };
    let state: State = serde_json::from_str(&encoded)?;
    Ok(state
        .contracts
        .get(&binding.contract_id)
        .filter(|contract| contract.status == Status::Active)
        .cloned())
}

async fn contract_has_active_revision(
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    binding: &ExecutionBinding,
) -> Result<bool, BindingError> {
    contract_at_active_revision(transaction, binding)
        .await
        .map(|contract| contract.is_some())
}

fn contract_attempt_key(contract: &Contract) -> String {
    let context = contract
        .challenge
        .as_ref()
        .filter(|challenge| challenge.disclosure == ChallengeDisclosure::Executor)
        .map(|challenge| format!("{}:{}", challenge.time, challenge.evidence_hash))
        .or_else(|| {
            contract
                .blocked
                .as_ref()
                .map(|blocked| format!("{}:{}", blocked.time, blocked.reason))
        })
        .unwrap_or_default();
    format!("{}:{context}", contract.revision)
}

fn binding_from_row(row: SqliteRow) -> Result<ExecutionBinding, BindingError> {
    let execution_policy: Option<String> = row.try_get("execution_policy")?;
    let expected_policy_hash = execution_policy.as_deref().map(hash_execution_policy);
    let stored_policy_hash: Option<String> = row.try_get("execution_policy_hash")?;
    if stored_policy_hash
        .as_ref()
        .is_some_and(|stored| Some(stored) != expected_policy_hash.as_ref())
    {
        return Err(BindingError::PolicyHashMismatch);
    }
    Ok(ExecutionBinding {
        scope: row.try_get("scope")?,
        ledger_scope: row.try_get("ledger_scope")?,
        contract_id: row.try_get("contract_id")?,
        revision: row.try_get::<i64, _>("revision")? as u64,
        execution_policy,
        execution_policy_hash: stored_policy_hash.or(expected_policy_hash),
        dispatched: row.try_get::<i64, _>("dispatched")? != 0,
        resume_same_attempt: row.try_get::<i64, _>("resume_same_attempt")? != 0,
        attempts: row.try_get::<i64, _>("attempts")? as u64,
        turns_used: row.try_get::<i64, _>("turns_used")? as u64,
        actions_used: row.try_get::<i64, _>("actions_used")? as u64,
        next_action_at: row.try_get::<i64, _>("next_action_at")? as u64,
        attempt_key: row.try_get("attempt_key")?,
        turns_limit: row.try_get::<i64, _>("turns_limit")? as u64,
        actions_limit: row.try_get::<i64, _>("actions_limit")? as u64,
        deadline: row.try_get::<i64, _>("deadline")? as u64,
        max_attempts: row.try_get::<i64, _>("max_attempts")? as u64,
        lease_owner: row.try_get("lease_owner")?,
        lease_expires_at: row.try_get::<i64, _>("lease_expires_at")? as u64,
    })
}

fn lease_expiry(now: u64, deadline: u64) -> u64 {
    now.saturating_add(30_000).min(deadline)
}

fn validate_policy(policy: Option<&str>) -> Result<(), BindingError> {
    if policy.is_some_and(|policy| policy.trim().is_empty()) {
        return Err(BindingError::EmptyPolicy);
    }
    if policy.is_some_and(|policy| policy.len() > MAX_EXECUTION_POLICY_BYTES) {
        return Err(BindingError::PolicyTooLarge);
    }
    Ok(())
}

fn hash_execution_policy(policy: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"codex.pro_contract.execution_policy.v1\0");
    hasher.update(policy.as_bytes());
    format!("{:x}", hasher.finalize())
}

#[cfg(test)]
#[path = "binding_tests.rs"]
mod tests;
