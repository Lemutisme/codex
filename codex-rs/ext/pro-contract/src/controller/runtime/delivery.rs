//! A completed executor can deliver an immutable artifact even when acceptance is unavailable.
//! Delivery attests only admission, provenance and captured bytes, never correctness or Support.

use codex_pro_contract_store::ExperimentKind;
use serde_json::json;

use super::ThreadRuntime;
use super::digest_of;

impl ThreadRuntime {
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
