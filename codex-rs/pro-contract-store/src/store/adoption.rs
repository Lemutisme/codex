//! Fenced, atomic settlement and incumbent selection for the protected host.

use codex_pro_contract::AuthenticatedCommand;
use codex_pro_contract::Command;
use codex_pro_contract::Contract;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;

use super::experiments::ExperimentEvent;
use super::experiments::ExperimentKind;
use super::experiments::Identities;
use super::ledger::Ledger;
use super::ledger::LedgerError;
use super::ledger::storage;
use crate::digest_of;

/// An authenticated discharge fenced against the incumbent observed before confirmation.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AdoptionRequest {
    pub command: AuthenticatedCommand,
    /// Latest incumbent selection's sequence number, or `None` for initial adoption.
    pub expected_incumbent_seq: Option<i64>,
    pub identities: Identities,
}

impl Ledger {
    /// Commits discharge and selection together. Identical retries return their original state,
    /// even after another adoption; changed commands, identities or fences conflict.
    pub async fn adopt(
        &self,
        request: &AdoptionRequest,
        idempotency_key: &str,
    ) -> Result<Contract, LedgerError> {
        let command_hash = digest_of("adoption", request).to_string();
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(storage)?;
        if let Some(committed) =
            Self::committed_result(&mut tx, idempotency_key, &command_hash).await?
        {
            return Ok(committed);
        }
        let Command::Discharge { coordinate, .. } = &request.command.command else {
            return Err(LedgerError::InvalidEvent(
                "adoption requires a discharge".to_string(),
            ));
        };
        let actual = sqlx::query_scalar::<_, i64>(
            "SELECT seq FROM experiment_events WHERE kind = 'selection'
             AND json_extract(event_json, '$.body.role') = 'incumbent' ORDER BY seq DESC LIMIT 1",
        )
        .fetch_optional(&mut *tx)
        .await
        .map_err(storage)?;
        if actual != request.expected_incumbent_seq {
            return Err(LedgerError::IncumbentChanged {
                expected: request.expected_incumbent_seq,
                actual,
            });
        }
        let next =
            Self::apply_in_transaction(&mut tx, &request.command, idempotency_key, &command_hash)
                .await?;
        Self::append_experiment_in_transaction(
            &mut tx,
            &ExperimentEvent {
                kind: ExperimentKind::Selection,
                identities: request.identities.clone(),
                body: json!({
                    "role": "incumbent",
                    "version": coordinate.subject_hash.to_string(),
                    "adoption": request.command.contract_id,
                }),
            },
        )
        .await?;
        tx.commit().await.map_err(storage)?;
        Ok(next)
    }
}
