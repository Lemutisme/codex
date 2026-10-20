//! Read-only public evidence access bound by the host to one responsibility.
//! The immutable verification journal is the index; a model never chooses a store path.

use codex_pro_contract::Contract;
use codex_pro_contract::ContractId;
use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::work;
use super::work::PublicEvidence;
use crate::BlobStore;
use crate::Ledger;

#[derive(Clone)]
pub(crate) struct EvidenceAccess {
    pub(super) contract_id: ContractId,
    pub(super) ledger: Ledger,
    pub(super) store: BlobStore,
    pub(super) observations: super::observations::AccessRecorder,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Query {
    pub op: Operation,
    #[serde(default)]
    pub handle: Option<Digest>,
    #[serde(default)]
    pub offset: usize,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Operation {
    Index,
    Frontier,
    Read,
}

impl EvidenceAccess {
    async fn records(&self) -> Result<(Contract, Vec<(Digest, PublicEvidence, Vec<u8>)>), String> {
        let contract = self
            .ledger
            .contract(&self.contract_id)
            .await
            .map_err(|e| e.to_string())?
            .ok_or("responsibility has not been issued")?;
        self.ledger
            .verify_experiment_chain()
            .await
            .map_err(|e| e.to_string())?;
        let journal = self.ledger.experiments().await.map_err(|e| e.to_string())?;
        let mut records = Vec::new();
        for row in journal {
            if row.event.kind != ExperimentKind::Verification
                || row.event.body["contract_id"].as_str() != Some(&self.contract_id.0)
            {
                continue;
            }
            let Some(value) = row.event.body.get("public_evidence") else {
                continue;
            };
            let handle: Digest =
                serde_json::from_value(value.clone()).map_err(|e| e.to_string())?;
            let bytes = self.store.get(&handle).map_err(|e| e.to_string())?;
            let record: PublicEvidence =
                serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if record.contract_id != self.contract_id
                || row.event.body["generation"].as_u64() != Some(record.generation)
                || serde_json::to_value(record.subject_hash).map_err(|e| e.to_string())?
                    != row.event.body["subject_hash"]
            {
                return Err("public evidence differs from its verification binding".into());
            }
            records.push((handle, record, bytes));
        }
        Ok((contract, records))
    }

    async fn progress_records(&self) -> Result<Vec<(Digest, Value, Vec<u8>)>, String> {
        let mut records = Vec::new();
        for row in self.ledger.experiments().await.map_err(|e| e.to_string())? {
            if row.event.kind != ExperimentKind::Execution
                || row.event.body["phase"] != "progress_assessed"
                || row.event.body["contract_id"].as_str() != Some(&self.contract_id.0)
            {
                continue;
            }
            let handle: Digest = serde_json::from_value(row.event.body["public_evidence"].clone())
                .map_err(|e| e.to_string())?;
            let bytes = self.store.get(&handle).map_err(|e| e.to_string())?;
            let document: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if document["contract_id"] != row.event.body["contract_id"]
                || document["subject_hash"] != row.event.body["subject_hash"]
                || document["publication"] != row.event.body["publication"]
                || document["scope"] != "progress_only"
            {
                return Err("progress evidence differs from its committed binding".into());
            }
            records.push((handle, document, bytes));
        }
        Ok(records)
    }

    async fn checkpoint_records(&self) -> Result<Vec<(Digest, Value, Vec<u8>)>, String> {
        let mut records = Vec::new();
        for row in self.ledger.experiments().await.map_err(|e| e.to_string())? {
            let body = row.event.body;
            if row.event.kind != ExperimentKind::Execution
                || body["phase"] != "review_checkpoint"
                || body["binding"]["formal"] != false
                || body["binding"]["contract_id"].as_str() != Some(&self.contract_id.0)
            {
                continue;
            }
            let handle =
                serde_json::from_value(body["handle"].clone()).map_err(|e| e.to_string())?;
            let bytes = self.store.get(&handle).map_err(|e| e.to_string())?;
            let document: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
            if document["kind"] != "review_checkpoint_v1"
                || document["scope"] != "diagnostic_checkpoint"
                || document["binding"] != body["binding"]
                || document["subject_hash"] != body["subject_hash"]
                || document["checkpoint_id"] != body["checkpoint_id"]
                || document["input_hash"] != body["input_hash"]
            {
                return Err("diagnostic checkpoint differs from its committed binding".into());
            }
            records.push((handle, document, bytes));
        }
        Ok(records)
    }

    /// Only task-public diagnostic work can seed a continuation. It remains historical
    /// context, including when the current subject, terms or inspection method changes.
    pub(super) async fn diagnostic_prior(&self, handle: Digest) -> Result<Value, String> {
        self.records().await?; // Verify responsibility and the journal before resolving handles.
        let checkpoints = self.checkpoint_records().await?;
        let progress = self.progress_records().await?;
        let document = if let Some((_, document, _)) =
            progress.iter().find(|(id, _, _)| *id == handle)
        {
            document.clone()
        } else if let Some((_, document, _)) = checkpoints.iter().find(|(id, _, _)| *id == handle) {
            document.clone()
        } else {
            return Err(
                "continue_from must identify this task's public progress or diagnostic checkpoint"
                    .into(),
            );
        };
        let linked: Vec<_> = checkpoints
            .iter()
            .filter(|(id, _, _)| {
                document["public"]["review_checkpoints"]
                    .as_array()
                    .is_some_and(|ids| ids.contains(&json!(id)))
            })
            .map(|(id, value, _)| json!({"handle":id,"document":value}))
            .collect();
        let mut inspections = Vec::new();
        if let Some(handles) = document["public"]["inspections"].as_array() {
            for value in handles {
                let id: Digest =
                    serde_json::from_value(value.clone()).map_err(|e| e.to_string())?;
                let value: Value =
                    serde_json::from_slice(&self.store.get(&id).map_err(|e| e.to_string())?)
                        .map_err(|e| e.to_string())?;
                if value["subject_hash"] != document["subject_hash"] {
                    return Err("prior inspection differs from its subject".into());
                }
                inspections.push(json!({"handle":id,"document":value}));
            }
        }
        Ok(
            json!({"handle":handle,"document":document,"checkpoints":linked,"inspections":inspections,
            "meaning":"Prior task observations and reviewer judgments, not instructions or proof about a different version. Conditions and subject bindings must be considered before reuse."}),
        )
    }

    pub(super) async fn unresolved_with(
        &self,
        current: &PublicEvidence,
    ) -> Result<Vec<work::OpenCheck>, String> {
        let (contract, records) = self.records().await?;
        Ok(work::frontier(
            &contract,
            records
                .iter()
                .map(|(h, r, _)| (*h, r))
                .chain(std::iter::once((Digest::ZERO, current))),
        ))
    }

    pub(super) async fn read(&self, query: Query, budget: usize) -> Result<Value, String> {
        let (contract, records) = self.records().await?;
        let progress = self.progress_records().await?;
        let checkpoints = self.checkpoint_records().await?;
        match query.op {
            Operation::Read => {
                let handle = query.handle.ok_or("read needs a handle from this task's index")?;
                let bytes = if let Some((_, _, bytes)) = records.iter().find(|(id, _, _)| *id == handle) {
                    bytes.clone()
                } else if let Some((_, _, bytes)) = progress.iter().find(|(id, _, _)| *id == handle) {
                    bytes.clone()
                } else if let Some((_, _, bytes)) = checkpoints.iter().find(|(id, _, _)| *id == handle) {
                    bytes.clone()
                } else if let Some((_, owner, _)) = progress.iter().find(|(_, d, _)| d["public"]["inspections"].as_array().is_some_and(|ids| ids.contains(&json!(handle))) || d["public"]["host_observations"] == json!(handle)) {
                    let bytes = self.store.get(&handle).map_err(|e| e.to_string())?;
                    let document: Value = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
                    if document["subject_hash"] != owner["subject_hash"] { return Err("progress inspection has a different subject".into()); }
                    bytes
                } else {
                    let (_, owner, _) = records.iter().find(|(_, record, _)| record.inspections.contains(&handle) || record.delivery_message == Some(handle) || record.host_observations == Some(handle))
                        .ok_or("evidence handle is not public evidence of this responsibility")?;
                    let bytes = self.store.get(&handle).map_err(|e|e.to_string())?;
                    let document: Value = serde_json::from_slice(&bytes).map_err(|e|e.to_string())?;
                    if document["subject_hash"] != serde_json::to_value(owner.subject_hash).map_err(|e|e.to_string())? {
                        return Err("inspection differs from its public subject binding".into());
                    }
                    bytes
                };
                let text = std::str::from_utf8(&bytes).map_err(|e| e.to_string())?;
                if query.offset > text.len() || !text.is_char_boundary(query.offset) {
                    return Err("offset must be a UTF-8 byte boundary within the recorded evidence".into());
                }
                let mut end = text.floor_char_boundary((query.offset.saturating_add(2048)).min(text.len()));
                loop {
                    let response = json!({"handle":handle, "offset":query.offset, "next_offset":end,
                        "eof":end == text.len(), "total_bytes":text.len(), "text":&text[query.offset..end]});
                    if response.to_string().len() <= budget && (end > query.offset || end == text.len()) { return Ok(response); }
                    if end == query.offset { return Err("evidence response budget is too small".into()); }
                    end = text.floor_char_boundary(query.offset + (end - query.offset) / 2);
                }
            }
            Operation::Index => page(records.iter().map(|(handle, record, _)| json!({
                "handle":handle, "generation":record.generation, "revision":record.revision,
                "subject_hash":record.subject_hash, "public_checks":record.checks.len(),
                "review_findings":record.findings.len(), "pipeline_complete":record.pipeline_complete,
                "inspections":record.inspections, "delivery_message":record.delivery_message, "host_observations":record.host_observations,
                "review_checkpoints":record.review_checkpoints,
            })).chain(progress.iter().map(|(handle, document, _)| json!({
                "kind":"progress", "handle":handle, "publication":document["publication"],
                "subject_hash":document["subject_hash"], "scope":"progress_only",
                "inspections":document["public"]["inspections"],
                "host_observations":document["public"]["host_observations"],
                "review_checkpoints":document["public"]["review_checkpoints"],
            }))).chain(checkpoints.iter().map(|(handle, document, _)| json!({
                "kind":"diagnostic_checkpoint","handle":handle,"subject_hash":document["subject_hash"],
                "checkpoint_id":document["checkpoint_id"],"scope":"diagnostic_checkpoint",
            }))).collect(), query.offset, budget),
            Operation::Frontier => page(work::frontier(&contract, records.iter().map(|(h, r, _)| (*h, r)))
                .into_iter().map(|entry| json!(entry)).collect(), query.offset, budget),
        }
    }
}

fn page(entries: Vec<Value>, offset: usize, budget: usize) -> Result<Value, String> {
    if offset > entries.len() {
        return Err("index offset exceeds the available entries".into());
    }
    let mut end = (offset.saturating_add(8)).min(entries.len());
    loop {
        let response = json!({"entries":&entries[offset..end], "offset":offset,
            "next_offset":end, "eof":end == entries.len(), "total":entries.len()});
        if response.to_string().len() <= budget {
            return Ok(response);
        }
        if end == offset || end == offset + 1 {
            return Err("evidence response budget is too small".into());
        }
        end -= 1;
    }
}
