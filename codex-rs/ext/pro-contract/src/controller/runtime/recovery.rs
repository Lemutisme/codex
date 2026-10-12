//! Rehydrate an existing responsibility, never replay an interrupted paid action.
//!
//! The immutable intake/Issue journal is also the migration source for pre-recovery sessions.
//! Missing or inconsistent evidence blocks automation without erasing the contract identity.

use codex_pro_contract::Command;
use codex_pro_contract::Contract;
use codex_pro_contract::Digest;
use codex_pro_contract::transition;
use codex_pro_contract_store::ExperimentKind;
use codex_pro_contract_store::load_subject;
use serde::Deserialize;

use super::ActiveContract;
use super::Base;
use super::EvidencePolicy;
use super::Phase;
use super::STATUS_KIND;
use super::StatusRecord;
use super::Terms;
use super::ThreadRuntime;
use super::brief_text;
use super::digest_of;

#[derive(Deserialize)]
struct Issued {
    terms: Terms,
    evidence_policy: EvidencePolicy,
    capture_policy: Digest,
}

impl ThreadRuntime {
    pub(crate) async fn restore(&self) {
        self.state.lock().await.phase = Phase::RecoveryBlocked;
        if let Err(error) = self.restore_state().await {
            self.state.lock().await.phase = Phase::RecoveryBlocked;
            self.write_status(
                "not_verified",
                "infrastructure",
                &format!("responsibility recovery blocked: {error}; no action replayed"),
                /*resting*/ true,
            )
            .await;
        }
    }

    async fn restore_state(&self) -> Result<(), String> {
        let id = self.contract_id();
        let contract = self.ledger.contract(&id).await.map_err(|e| e.to_string())?;
        {
            let mut state = self.state.lock().await;
            state.recovered_contract_id = contract.as_ref().map(|_| id.clone());
            // Unknown accounting is not a fresh repair allowance.
            state.repairs_used = self.settings.repair_attempts;
        }
        let previous: Option<StatusRecord> = self
            .ledger
            .record(STATUS_KIND, &self.thread_id.to_string())
            .await
            .map_err(|e| e.to_string())?;
        if let Some(status) = &previous {
            self.state.lock().await.repairs_used = status.repairs_used;
            if status.thread_id != self.thread_id.to_string()
                || status
                    .contract_id
                    .as_ref()
                    .is_some_and(|value| value != &id.0)
            {
                return Err("status belongs to a different responsibility".to_string());
            }
            if status.contract_id.is_some() {
                self.state.lock().await.recovered_contract_id = Some(id.clone());
            }
        }
        let Some(contract) = contract else {
            match previous {
                None => {
                    {
                        let mut state = self.state.lock().await;
                        state.phase = Phase::Idle;
                        state.repairs_used = 0;
                    }
                    self.record_status("idle", "", /*resting*/ false).await;
                }
                Some(status) if status.contract_id.is_none() && status.phase == "idle" => {
                    self.state.lock().await.phase = Phase::Idle;
                }
                Some(status) if status.contract_id.is_none() && status.resting => {
                    self.state.lock().await.phase = Phase::Resting;
                }
                Some(_) => {
                    return Err("intake was interrupted or its contract is missing".to_string());
                }
            }
            return Ok(());
        };
        let mut replayed: Option<Contract> = None;
        let mut previous_hash = Digest::ZERO;
        let mut defeats = 0_u32;
        for event in self.ledger.events().await.map_err(|e| e.to_string())? {
            if event.prev_hash != previous_hash
                || event.hash
                    != digest_of("event", &(previous_hash, &event.command, event.state_hash))
                || event.contract_id != event.command.contract_id
            {
                return Err("contract event chain is inconsistent".to_string());
            }
            previous_hash = event.hash;
            if event.contract_id == id {
                defeats = defeats.saturating_add(u32::from(matches!(
                    event.command.command,
                    Command::Defeat { .. }
                )));
                let next =
                    transition(replayed.as_ref(), &event.command).map_err(|e| e.to_string())?;
                if event.state_hash != digest_of("contract_state", &next) {
                    return Err("contract event state differs".to_string());
                }
                replayed = Some(next);
            }
        }
        if replayed.as_ref() != Some(&contract) {
            return Err("contract differs from its accepted history".to_string());
        }
        {
            let mut state = self.state.lock().await;
            state.repairs_used = state
                .repairs_used
                .max(defeats.min(self.settings.repair_attempts));
        }
        self.ledger
            .verify_experiment_chain()
            .await
            .map_err(|e| e.to_string())?;
        let journal = self.ledger.experiments().await.map_err(|e| e.to_string())?;
        let issue = journal
            .iter()
            .rev()
            .find(|r| {
                r.event.kind == ExperimentKind::Issue
                    && r.event.body["contract_id"].as_str() == Some(&id.0)
            })
            .ok_or("missing issued terms")?;
        let issued: Issued =
            serde_json::from_value(issue.event.body.clone()).map_err(|e| e.to_string())?;
        if digest_of("terms", &issued.terms) != contract.bindings.terms_hash
            || digest_of("evidence_policy", &issued.evidence_policy)
                != contract.bindings.evidence_policy_hash
            || issued.capture_policy != contract.bindings.capture_policy_hash
            || issued.capture_policy != digest_of("capture_policy", &self.capture_policy)
        {
            return Err("issued bindings changed; explicit reconciliation required".to_string());
        }
        let base_hash: Digest = serde_json::from_value(
            journal
                .iter()
                .rev()
                .find(|r| {
                    r.seq < issue.seq
                        && r.event.kind == ExperimentKind::Intake
                        && r.event.body["thread_id"].as_str() == Some(&self.thread_id.to_string())
                })
                .ok_or("missing original intake")?
                .event
                .body["base_subject"]
                .clone(),
        )
        .map_err(|e| e.to_string())?;
        let binding = self
            .ledger
            .subject_binding(&base_hash)
            .await
            .map_err(|e| e.to_string())?
            .ok_or("missing original workspace binding")?;
        if binding.capture_policy != issued.capture_policy {
            return Err("original workspace capture policy differs".to_string());
        }
        let base =
            load_subject(&self.store, &binding.manifest, &base_hash).map_err(|e| e.to_string())?;
        let dir = self.work_dir().join("base");
        self.materialize(&base, &dir).await?;
        {
            let mut state = self.state.lock().await;
            state.contract = Some(ActiveContract {
                brief: brief_text(
                    &id.0,
                    contract.revision,
                    &issued.terms,
                    &issued.evidence_policy,
                ),
                contract,
                terms: issued.terms,
                policy: issued.evidence_policy,
                base: Base {
                    dir,
                    subject: base_hash,
                },
            });
            state.phase = Phase::Resting;
            state.repair_note = previous
                .as_ref()
                .filter(|s| matches!(s.phase.as_str(), "repairing" | "did_not_pass"))
                .map(|s| crate::workers::bounded(&s.detail, /*cap*/ 800));
        }
        if let Some(status) = previous.filter(|s| {
            s.resting
                && s.contract_id.as_deref() == Some(&id.0)
                && (s.phase != "supported"
                    || replayed.as_ref().is_some_and(|c| c.support.is_some()))
        }) {
            self.write_status(
                &status.phase,
                &status.class,
                &status.detail,
                /*resting*/ true,
            )
            .await;
        } else {
            self.write_status("not_verified", "no_handoff", "previous execution was interrupted; responsibility restored, no action replayed; continue in a new turn", /*resting*/ true).await;
        }
        Ok(())
    }
}
