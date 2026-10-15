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
        match query.op {
            Operation::Read => {
                let handle = query.handle.ok_or("read needs a handle from this task's index")?;
                let (_, _, bytes) = records.iter().find(|(id, _, _)| *id == handle)
                    .ok_or("evidence handle is not public evidence of this responsibility")?;
                let text = std::str::from_utf8(bytes).map_err(|e| e.to_string())?;
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
            })).collect(), query.offset, budget),
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
