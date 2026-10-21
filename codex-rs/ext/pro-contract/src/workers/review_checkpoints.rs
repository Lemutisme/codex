//! Explicit reviewer outputs retained before its final response. No authority transitions.

use codex_pro_contract::Digest;
use codex_pro_contract_store::{ExperimentEvent, ExperimentKind};
use codex_protocol::dynamic_tools::{
    DynamicToolCallOutputContentItem, DynamicToolFunctionSpec, DynamicToolResponse, DynamicToolSpec,
};
use serde::Deserialize;
use serde_json::{Value, json};

use super::ReviewEvidence;
use crate::workers::{WorkerError, reviewer};

pub(crate) const TOOL: &str = "record_review";

impl ReviewEvidence {
    pub(crate) fn can_checkpoint(&self) -> bool {
        self.protocol_log
            .as_ref()
            .is_some_and(|(_, _, binding)| binding["formal"] == false)
    }

    pub(crate) fn checkpoint_tool(&self) -> DynamicToolSpec {
        DynamicToolSpec::Function(DynamicToolFunctionSpec {
            name: TOOL.into(),
            description: "Save a diagnostic review checkpoint before the final response. Submit completed local observations, findings and judgments using the existing obligation IDs and issued citations. You may omit unassessed obligations. A checkpoint survives timeout; it does not grant Support or settle the task. Repeating an identical checkpoint_id reopens its receipt; use a new ID for revised work. Earlier judgments remain historical, not automatically current truth.".into(),
            input_schema: crate::workers::strict_object(json!({
                "checkpoint_id":{"type":"string","minLength":1,"maxLength":128},
                "review":reviewer::schema_for(&self.terms),
            })),
            defer_loading: false,
        })
    }

    pub(crate) async fn record_checkpoint(&self, arguments: Value) -> DynamicToolResponse {
        let result = self.commit_checkpoint(arguments).await;
        let (text, success) = match result {
            Ok(value) => (value.to_string(), true),
            Err(error) => (
                format!(
                    "Refused: {}",
                    crate::workers::bounded(&error.to_string(), 1000)
                ),
                false,
            ),
        };
        DynamicToolResponse {
            structured_content: None,
            content_items: vec![DynamicToolCallOutputContentItem::InputText { text }],
            success,
        }
    }

    async fn commit_checkpoint(&self, arguments: Value) -> Result<Value, WorkerError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Request {
            checkpoint_id: String,
            review: Value,
        }
        let malformed = |reason: String| WorkerError::Malformed(reason);
        if !self.can_checkpoint() {
            return Err(malformed("no diagnostic checkpoint capability".into()));
        }
        if arguments.to_string().len() > 65_536 {
            return Err(WorkerError::InputBudget(
                "review checkpoint exceeds 64 KiB".into(),
            ));
        }
        let request: Request =
            serde_json::from_value(arguments).map_err(|e| malformed(e.to_string()))?;
        if request.checkpoint_id.is_empty() || request.checkpoint_id.len() > 128 {
            return Err(malformed("checkpoint_id must contain 1..128 bytes".into()));
        }
        let (ledger, identities, binding) = self
            .protocol_log
            .as_ref()
            .ok_or_else(|| malformed("checkpoint journal unavailable".into()))?;
        let message = request.review.to_string();
        let input_hash = Digest::of(message.as_bytes());
        let receipt = |handle: Digest, reused: bool, rejected: Value| {
            json!({
                "handle":handle,"reused":reused,"subject_hash":self.subject.subject_hash,
                "scope":"diagnostic_checkpoint","completion_certified":false,
                "rejected_support":rejected,
            })
        };
        // This isolated worker serializes its tool calls. The durable journal also makes
        // repeated delivery idempotent without relying on its in-memory conversation.
        for row in ledger
            .experiments()
            .await
            .map_err(|e| WorkerError::Failed(e.to_string()))?
        {
            let body = row.event.body;
            if body["phase"] == "review_checkpoint"
                && body["binding"] == *binding
                && body["checkpoint_id"] == request.checkpoint_id
            {
                if body["input_hash"] != json!(input_hash) {
                    return Err(malformed(
                        "checkpoint_id already identifies different work".into(),
                    ));
                }
                let handle = serde_json::from_value(body["handle"].clone())
                    .map_err(|e| malformed(e.to_string()))?;
                return Ok(receipt(handle, true, body["rejected_support"].clone()));
            }
        }
        let resolved = self.resolve_review(&message)?;
        let review = reviewer::parse(&resolved.message, &self.terms)?;
        let document = json!({
            "kind":"review_checkpoint_v1","scope":"diagnostic_checkpoint",
            "subject_hash":self.subject.subject_hash,"terms_hash":crate::digest_of("terms",&self.terms),
            "binding":binding,"checkpoint_id":request.checkpoint_id,"input_hash":input_hash,
            "review":review,"completion_certified":false,
            "rejected_support":resolved.rejected,
            "meaning":"Explicit reviewer judgments with validated identities/citations, not host proof or final acceptance. Unassessed obligations remain unassessed; later work may revise these judgments.",
        });
        let handle = self
            .store
            .put(document.to_string().as_bytes())
            .map_err(|e| WorkerError::Failed(e.to_string()))?;
        ledger
            .append_experiment(&ExperimentEvent {
                kind: ExperimentKind::Execution,
                identities: identities.clone(),
                body: json!({"phase":"review_checkpoint","binding":binding,
                "subject_hash":self.subject.subject_hash,"checkpoint_id":request.checkpoint_id,
                "input_hash":input_hash,"handle":handle,"rejected_support":resolved.rejected}),
            })
            .await
            .map_err(|e| WorkerError::Failed(e.to_string()))?;
        Ok(receipt(handle, false, json!(resolved.rejected)))
    }
}
