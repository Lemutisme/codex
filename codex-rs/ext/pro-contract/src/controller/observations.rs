//! Host observations have a precise boundary. Preparing bytes is not successful tool
//! completion; tool completion is not proof of model consumption or comprehension.
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use codex_pro_contract::Digest;
use codex_pro_contract_store::{ExperimentEvent, ExperimentKind, Identities};
use serde_json::{Value, json};

use super::archive::{EvidenceAccess, Query};

const ACCESS_BUDGET: &str = "evidence_access_budget_v1";
const MAX_ACCESS_RECEIPTS: u32 = 4096;

#[derive(Clone, Default)]
pub(super) struct AccessRecorder {
    pending: Arc<Mutex<BTreeMap<Digest, Digest>>>,
}

/// Adapter-neutral observation outcome. Transport-specific identities stay opaque.
#[derive(Clone, Copy, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum AccessOutcome {
    Completed,
    Unsuccessful,
    Blocked,
    Failed,
    Aborted,
}

impl EvidenceAccess {
    async fn observe(&self, body: Value) -> Result<Digest, String> {
        self.ledger
            .append_experiment(&ExperimentEvent {
                kind: ExperimentKind::Execution,
                identities: Identities {
                    harness: super::identity::harness_sha256(),
                    ..Default::default()
                },
                body,
            })
            .await
            .map(|r| r.hash)
            .map_err(|e| e.to_string())
    }

    async fn reserve_access(&self) -> Result<(), String> {
        for _ in 0..16 {
            let before: Option<u32> = self
                .ledger
                .record(ACCESS_BUDGET, &self.contract_id.0)
                .await
                .map_err(|e| e.to_string())?;
            let used = before.unwrap_or(0);
            if used >= MAX_ACCESS_RECEIPTS {
                return Err("task evidence-access receipt allowance exhausted; no renewal".into());
            }
            if self
                .ledger
                .compare_exchange_record(
                    ACCESS_BUDGET,
                    &self.contract_id.0,
                    before.as_ref(),
                    &(used + 1),
                )
                .await
                .map_err(|e| e.to_string())?
            {
                return Ok(());
            }
        }
        Err("evidence-access reservation is contended; no response attested".into())
    }

    pub(super) async fn read_observed(
        &self,
        query: Query,
        budget: usize,
        caller: Value,
    ) -> Result<Value, String> {
        if caller.to_string().len() > 4096 {
            return Err("native access identity exceeds receipt bound".into());
        }
        let value = self.read(query, budget).await?;
        let Some(text) = value.get("text").and_then(Value::as_str) else {
            return Ok(value);
        };
        self.reserve_access().await?;
        let key = crate::digest_of("evidence_access_call", &caller);
        {
            let mut pending = self
                .observations
                .pending
                .lock()
                .map_err(|e| e.to_string())?;
            if pending.contains_key(&key) {
                return Err("duplicate in-flight access identity".into());
            }
            pending.insert(key, Digest::ZERO);
        }
        let receipt = self.observe(json!({"phase":"evidence_response_prepared",
            "contract_id":self.contract_id.0,"caller":caller,"source_handle":value["handle"],
            "offset":value["offset"],"end":value["next_offset"],"total_bytes":value["total_bytes"],
            "returned_bytes_sha256":Digest::of(text.as_bytes()),
            "meaning":"Exact bytes prepared for this native invocation; completion requires its linked lifecycle receipt."})).await?;
        self.observations
            .pending
            .lock()
            .map_err(|e| e.to_string())?
            .insert(key, receipt);
        Ok(value)
    }

    pub(super) async fn finish_access(
        &self,
        caller: Value,
        outcome: AccessOutcome,
    ) -> Result<(), String> {
        let key = crate::digest_of("evidence_access_call", &caller);
        let receipt = self
            .observations
            .pending
            .lock()
            .map_err(|e| e.to_string())?
            .remove(&key);
        let Some(receipt) = receipt.filter(|r| *r != Digest::ZERO) else {
            return Ok(());
        };
        self.observe(json!({"phase":"evidence_response_finished", "contract_id":self.contract_id.0,
            "caller":caller,"prepared_receipt":receipt,"outcome":outcome,
            "meaning":"Native tool lifecycle outcome; no claim of model rendering, consumption or comprehension."})).await?;
        Ok(())
    }
}

pub(super) struct AssessmentScope<'a> {
    pub contract: &'a codex_pro_contract::Contract,
    pub terms: &'a crate::Terms,
    pub subject: &'a crate::Subject,
    pub baseline: &'a crate::Subject,
    pub owner_thread: &'a str,
    pub turn: &'a str,
    pub epoch: u64,
    pub formal: bool,
}

/// Freeze the observation prefix belonging to this handoff, not the latest mutable history.
pub(super) async fn snapshot(
    ledger: &crate::Ledger,
    store: &crate::BlobStore,
    scope: AssessmentScope<'_>,
) -> Result<Value, String> {
    ledger
        .verify_experiment_chain()
        .await
        .map_err(|e| e.to_string())?;
    let events = ledger.experiments().await.map_err(|e| e.to_string())?;
    let cutoff = events
        .iter()
        .rev()
        .find(|row| {
            let b = &row.event.body;
            b["turn_id"] == scope.turn
                && b["subject_hash"] == json!(scope.subject.subject_hash)
                && b["execution_epoch"] == scope.epoch
                && if scope.formal {
                    b["phase"] == "task_delivery" && b["thread_id"] == scope.owner_thread
                } else {
                    b["phase"] == "progress_snapshot" && b["contract_id"] == scope.contract.id.0
                }
        })
        .ok_or("assessment has no matching immutable capture boundary")?;
    let history: Vec<_> = events
        .iter()
        .filter(|r| r.seq <= cutoff.seq && r.event.body["contract_id"] == scope.contract.id.0)
        .collect();
    let publications: Vec<_> = history.iter().filter(|r| r.event.body["phase"] == "progress_snapshot")
        .map(|r| json!({"receipt":r.hash,"sequence":r.seq,"publication":r.event.body["publication"],
            "turn_id":r.event.body["turn_id"],"execution_epoch":r.event.body["execution_epoch"],
            "subject_hash":r.event.body["subject_hash"],
            "matches_task_baseline":r.event.body["subject_hash"] == json!(scope.baseline.subject_hash)})).collect();
    let mut accesses = Vec::new();
    for prepared in history
        .iter()
        .filter(|r| r.event.body["phase"] == "evidence_response_prepared")
    {
        let b = &prepared.event.body;
        let handle: Digest =
            serde_json::from_value(b["source_handle"].clone()).map_err(|e| e.to_string())?;
        let bytes = store.get(&handle).map_err(|e| e.to_string())?;
        let start = b["offset"].as_u64().ok_or("access offset unavailable")? as usize;
        let end = b["end"].as_u64().ok_or("access end unavailable")? as usize;
        if start > end
            || end > bytes.len()
            || b["total_bytes"] != bytes.len()
            || b["returned_bytes_sha256"] != json!(Digest::of(&bytes[start..end]))
        {
            return Err("access receipt differs from retained source bytes".into());
        }
        let finished = history.iter().find(|r| {
            r.seq > prepared.seq
                && r.event.body["phase"] == "evidence_response_finished"
                && r.event.body["prepared_receipt"] == json!(prepared.hash)
                && r.event.body["caller"] == b["caller"]
        });
        let source: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        accesses.push(json!({"prepared_receipt":prepared.hash,"sequence":prepared.seq,
            "caller":b["caller"],"source_handle":handle,"source_subject":source["subject_hash"],
            "source_revision":source["revision"],"offset":start,"end":end,"total_bytes":bytes.len(),
            "returned_bytes_sha256":b["returned_bytes_sha256"],
            "completion_receipt":finished.map(|r| r.hash),"completion_sequence":finished.map(|r| r.seq),
            "outcome":finished.map(|r| r.event.body["outcome"].clone()).unwrap_or(json!("unknown"))}));
    }
    let before: BTreeMap<_, _> = scope
        .baseline
        .manifest
        .entries
        .iter()
        .map(|e| (&e.path, e))
        .collect();
    let after: BTreeMap<_, _> = scope
        .subject
        .manifest
        .entries
        .iter()
        .map(|e| (&e.path, e))
        .collect();
    let paths: std::collections::BTreeSet<_> = before.keys().chain(after.keys()).copied().collect();
    let mut entries = Vec::new();
    let mut counts = BTreeMap::<&str, usize>::new();
    for path in paths {
        let state = match (before.get(path), after.get(path)) {
            (Some(a), Some(b)) if a == b => "identical",
            (Some(_), Some(_)) => "changed",
            (Some(_), None) => "removed",
            (None, Some(_)) => "added",
            (None, None) => unreachable!("path comes from a captured manifest"),
        };
        *counts.entry(state).or_default() += 1;
        if entries.len() < 1024 {
            entries.push(json!({"path":path,"state":state,
                "baseline":before.get(path).map(|entry| &entry.kind),
                "current":after.get(path).map(|entry| &entry.kind)}));
        }
    }
    let total: usize = counts.values().sum();
    Ok(
        json!({"kind":"host_observations_v1","contract_id":scope.contract.id.0,
        "revision":scope.contract.revision,"generation":scope.contract.generation,
        "terms_hash":crate::digest_of("terms", scope.terms),"subject_hash":scope.subject.subject_hash,
        "baseline_subject":scope.baseline.subject_hash,"turn_id":scope.turn,"execution_epoch":scope.epoch,
        "capture_receipt":cutoff.hash,"journal_through_sequence":cutoff.seq,
        "publications":publications,"feedback_access":accesses,
        "baseline_comparison":{"counts":counts,"entries":entries,"omitted_entries":total.saturating_sub(1024)},
        "limits":[
            "Only the recorded observation types through this immutable capture boundary are described; this is not a complete execution transcript.",
            "A prepared response alone is not completed access. Completed means the native tool returned successfully, not that the model rendered, consumed or understood its text.",
            "Byte/mode equality at capture boundaries does not prove there were no intervening edits. Omitted baseline entries establish no per-file fact.",
            "No claim about unobserved network, installation or arbitrary external effects is made. Absence of a receipt is unknown, not proof of absence.",
            "These observations create no new obligations and do not waive missing or failed steps."
        ]}),
    )
}
