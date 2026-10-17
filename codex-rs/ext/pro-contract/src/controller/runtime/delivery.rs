//! A completed executor can deliver an immutable artifact even when acceptance is unavailable.
//! Delivery attests only admission, provenance and captured bytes, never correctness or Support.

use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::ThreadRuntime;
use codex_pro_contract::Digest;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub(super) enum ResponseCapture {
    #[default]
    Absent,
    Available {
        handle: Digest,
    },
    Unavailable {
        reason: String,
    },
}
impl ResponseCapture {
    pub(super) fn handle(&self) -> Option<Digest> {
        match self {
            Self::Available { handle } => Some(*handle),
            _ => None,
        }
    }
}

use super::digest_of;

fn response_document(subject: Digest, turn: &str, message: &str) -> serde_json::Value {
    let text = if message.len() <= 65536 {
        message.to_string()
    } else {
        // The omission marker is part of the retained byte allowance.
        crate::workers::bounded_head_tail(message, 65536 - 64)
    };
    json!({"kind":"native_final_response", "subject_hash":subject,
        "turn_id":turn, "complete":message.len() <= 65536,
        "original_bytes":message.len(), "original_sha256":Digest::of(message.as_bytes()),
        "text":text,
        "meaning":"The actual delivered response is an artifact to assess, not proof of the executor's claims."})
}

impl ThreadRuntime {
    pub(super) fn capture_response(
        &self,
        subject: &crate::Subject,
        turn: &str,
        message: Option<&str>,
    ) -> ResponseCapture {
        let Some(message) = message else {
            return ResponseCapture::Absent;
        };
        let document = response_document(subject.subject_hash, turn, message);
        match serde_json::to_vec(&document)
            .map_err(|e| e.to_string())
            .and_then(|bytes| self.store.put(&bytes).map_err(|e| e.to_string()))
        {
            Ok(handle) => ResponseCapture::Available { handle },
            Err(reason) => ResponseCapture::Unavailable { reason },
        }
    }

    pub(super) async fn commit_delivery(&self) -> Result<(), String> {
        // Reserve the turn before I/O. The epoch travels with the immutable artifact, so a
        // delayed old append cannot become the latest delivery after a newer owner turn.
        let (intake, frozen, epoch) = {
            let mut state = self.state.lock().await;
            let (Some(intake), Some(frozen)) = (state.admission, state.frozen.clone()) else {
                return Ok(());
            };
            if !state.delivered_turns.insert(frozen.turn_id.clone()) {
                return Ok(());
            }
            (intake, frozen, state.epoch)
        };
        let result = self
            .append_event(
                ExperimentKind::Capture,
                None,
                json!({
                    "phase": "task_delivery", "thread_id": self.thread_id.to_string(),
                    "intake": intake, "turn_id": frozen.turn_id,
                    "execution_epoch": epoch,
                    "subject_hash": frozen.subject.subject_hash,
                    "response": frozen.response,
                    "capture_policy": digest_of("capture_policy", &self.capture_policy),
                }),
            )
            .await;
        if result.is_err() {
            self.state
                .lock()
                .await
                .delivered_turns
                .remove(&frozen.turn_id);
        }
        result.map(|_| ())
    }

    /// Restore admission without replaying a model action or creating a new budget.
    pub(super) async fn restore_admission(&self) -> Result<(), String> {
        self.ledger
            .verify_experiment_chain()
            .await
            .map_err(|e| e.to_string())?;
        let journal = self.ledger.experiments().await.map_err(|e| e.to_string())?;
        let thread = self.thread_id.to_string();
        let intakes: Vec<_> = journal
            .iter()
            .filter(|r| {
                r.event.kind == ExperimentKind::Intake && r.event.body["thread_id"] == thread
            })
            .collect();
        if intakes.len() > 1 {
            return Err("more than one original task admission".into());
        }
        let Some(intake) = intakes.first() else {
            return Ok(());
        };
        if intake.event.body["capture_policy"]
            != json!(digest_of("capture_policy", &self.capture_policy))
        {
            return Err("admitted capture policy changed".into());
        }
        if intake
            .event
            .body
            .get("progress")
            .is_some_and(|value| !value.is_null())
            && intake.event.body["progress"] != json!(self.settings.progress)
        {
            return Err("admitted progress capability changed; no grant renewed".into());
        }
        let mut state = self.state.lock().await;
        state.admission = Some(intake.hash);
        state.delivered_turns.clear();
        for event in journal.iter().filter(|r| {
            r.event.kind == ExperimentKind::Capture
                && r.event.body["thread_id"] == thread
                && r.event.body["phase"] == "task_delivery"
        }) {
            if event.seq <= intake.seq || event.event.body["intake"] != json!(intake.hash) {
                return Err("delivery belongs to a different admission".into());
            }
            let turn = event.event.body["turn_id"]
                .as_str()
                .ok_or("delivery has no turn")?;
            let epoch = event.event.body["execution_epoch"]
                .as_u64()
                .ok_or("delivery has no execution epoch")?;
            state.epoch = state
                .epoch
                .max(epoch.checked_add(1).ok_or("delivery epoch exhausted")?);
            if !state.delivered_turns.insert(turn.to_string()) {
                return Err("duplicate delivered turn".into());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn response_retains_actual_bytes_or_explicitly_marks_utf8_truncation() {
        let subject = Digest::of(b"frozen workspace");
        for message in [
            "完整答复".repeat(200),
            format!("HEAD{}TAIL", "中".repeat(30000)),
        ] {
            let document = response_document(subject, "actual-turn", &message);
            assert_eq!(document["subject_hash"], json!(subject));
            assert_eq!(document["turn_id"], "actual-turn");
            assert_eq!(document["original_bytes"], message.len());
            assert_eq!(
                document["original_sha256"],
                json!(Digest::of(message.as_bytes()))
            );
            let text = document["text"].as_str().unwrap();
            assert!(text.len() <= 65536);
            if message.len() <= 65536 {
                assert_eq!(document["complete"], true);
                assert_eq!(text, message);
            } else {
                assert_eq!(document["complete"], false);
                assert!(text.starts_with("HEAD") && text.ends_with("TAIL"));
            }
        }
    }
}
