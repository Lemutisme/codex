//! Durable, non-renewing authorization for one frozen review's computations.
//! Reservations follow input validation and survive dispatch failure and restart. Unknown action effects
//! must be reconciled before dispatch; a missing completion is never permission to retry.

use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_pro_contract::Digest;
use serde_json::Value;
use serde_json::json;

#[derive(Clone)]
pub(crate) struct InspectionGrant {
    pub environment: crate::CheckEnvironment,
    pub limits: crate::ReviewExecution,
    directory: PathBuf,
    binding: Digest,
    deadline_ms: u64,
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or_default()
}

fn read(path: &Path) -> Result<Value, String> {
    serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

impl InspectionGrant {
    pub fn open(
        environment: crate::CheckEnvironment,
        limits: crate::ReviewExecution,
        directory: PathBuf,
        subject: Digest,
        terms: &crate::Terms,
        lifetime: Duration,
    ) -> Result<Self, String> {
        if !(1..=64).contains(&limits.max_calls)
            || !(1..=900).contains(&limits.timeout_secs)
            || !(256..=1_048_576).contains(&limits.max_output_bytes)
        {
            return Err("invalid frozen-evidence computation grant".into());
        }
        std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        let binding = crate::digest_of(
            "inspection_grant_v1",
            &(subject, terms, &environment, &limits),
        );
        let path = directory.join("grant.json");
        if !path.exists() {
            let temporary = directory.join(format!(".{}", crate::checks::unique_name()));
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&temporary)
                .map_err(|e| e.to_string())?;
            let value = json!({"binding":binding,"deadline_ms":now_ms().saturating_add(lifetime.as_millis().min(u128::from(u64::MAX)) as u64)});
            file.write_all(value.to_string().as_bytes())
                .map_err(|e| e.to_string())?;
            file.sync_all().map_err(|e| e.to_string())?;
            // Publish without replacing a concurrently established original grant.
            match std::fs::hard_link(&temporary, &path) {
                Ok(()) => {}
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(e) => return Err(e.to_string()),
            }
            std::fs::remove_file(temporary).map_err(|e| e.to_string())?;
        }
        let saved = read(&path)?;
        if saved["binding"] != serde_json::to_value(binding).map_err(|e| e.to_string())? {
            return Err(
                "inspection grant has different subject, terms or capability; no implicit renewal"
                    .into(),
            );
        }
        let deadline_ms = saved["deadline_ms"]
            .as_u64()
            .ok_or("invalid saved inspection deadline")?;
        Ok(Self {
            environment,
            limits,
            directory,
            binding,
            deadline_ms,
        })
    }

    pub fn reserve(
        &self,
        request: &Value,
        remaining: Duration,
    ) -> Result<(PathBuf, Duration), String> {
        let remaining = remaining.min(Duration::from_millis(
            self.deadline_ms.saturating_sub(now_ms()),
        ));
        if remaining.is_zero() {
            return Err("original computation grant expired".into());
        }
        for slot in 0..self.limits.max_calls {
            let work = self.directory.join(format!("call-{slot}"));
            let action = work.join("action/execution.json");
            if action.exists() && read(&action)?["shutdown_confirmed"] != true {
                return Err(
                    "prior computation effects are unresolved; reconcile before another action"
                        .into(),
                );
            }
        }
        for slot in 0..self.limits.max_calls {
            let path = self.directory.join(format!("reservation-{slot}.json"));
            match std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
            {
                Ok(mut file) => {
                    file.write_all(
                        json!({"at_ms":now_ms(),"request":request})
                            .to_string()
                            .as_bytes(),
                    )
                    .map_err(|e| e.to_string())?;
                    file.sync_all().map_err(|e| e.to_string())?;
                    return Ok((self.directory.join(format!("call-{slot}")), remaining));
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(e) => return Err(e.to_string()),
            }
        }
        Err("computation grant exhausted".into())
    }

    pub fn retain(
        &self,
        directory: &Path,
        mut value: Value,
        store: &crate::BlobStore,
    ) -> Result<String, String> {
        value["grant_binding"] = serde_json::to_value(self.binding).map_err(|e| e.to_string())?;
        let document = value.to_string();
        store.put(document.as_bytes()).map_err(|e| e.to_string())?;
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join("result.json"))
            .map_err(|e| e.to_string())?;
        file.write_all(document.as_bytes())
            .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        Ok(document)
    }

    pub fn actions(&self) -> Result<Vec<crate::ExecutionReceipt>, String> {
        let mut actions = Vec::new();
        for slot in 0..self.limits.max_calls {
            let path = self
                .directory
                .join(format!("call-{slot}/action/execution.json"));
            if path.exists() {
                actions.push(
                    serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?)
                        .map_err(|e| e.to_string())?,
                );
            }
        }
        Ok(actions)
    }

    pub async fn wait_for_owned_actions(&self) {
        for slot in 0..self.limits.max_calls {
            crate::execution::wait_for_finalization(
                &self.directory.join(format!("call-{slot}/action")),
            )
            .await;
        }
    }

    pub fn history(&self, store: &crate::BlobStore) -> Result<Vec<String>, String> {
        let mut history = Vec::new();
        for slot in 0..self.limits.max_calls {
            let path = self.directory.join(format!("call-{slot}/result.json"));
            if !path.exists() {
                continue;
            }
            let document = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
            let value: Value = serde_json::from_str(&document).map_err(|e| e.to_string())?;
            if value["grant_binding"]
                != serde_json::to_value(self.binding).map_err(|e| e.to_string())?
                || store
                    .get(&Digest::of(document.as_bytes()))
                    .map_err(|e| e.to_string())?
                    != document.as_bytes()
            {
                return Err("recovered computation identity mismatch".into());
            }
            history.push(document);
        }
        Ok(history)
    }
}

#[cfg(test)]
#[path = "inspection_grant_tests.rs"]
mod tests;
