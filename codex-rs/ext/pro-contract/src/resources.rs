//! Optional allocator observations. Absence or unavailable data never invents a limit.
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Deserialize, Serialize)]
pub(crate) struct Snapshot {
    schema: String,
    allocation_id: String,
    observed_at: f64,
    model_requests: Requests,
    time: Time,
}
#[derive(Deserialize, Serialize)]
struct Requests {
    limit: Option<u64>,
    reserved: u64,
    remaining: Option<u64>,
}
#[derive(Deserialize, Serialize)]
struct Time {
    deadline: Option<f64>,
}

pub(crate) fn read(path: Option<&Path>) -> Result<Option<Snapshot>, String> {
    let Some(path) = path else {
        return Ok(None);
    };
    let raw = std::fs::read(path).map_err(|e| e.to_string())?;
    let snapshot: Snapshot = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    if snapshot.schema != "task_resources/v1"
        || snapshot.allocation_id.is_empty()
        || snapshot.model_requests.remaining
            != snapshot
                .model_requests
                .limit
                .map(|n| n.saturating_sub(snapshot.model_requests.reserved))
    {
        return Err("inconsistent allocator resource view".into());
    }
    Ok(Some(snapshot))
}

impl Snapshot {
    pub(crate) fn exhaustion(&self) -> Option<&'static str> {
        if self.model_requests.remaining == Some(0) {
            return Some(
                "shared model-request allocation exhausted; the current artifact and observations remain retained",
            );
        }
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()?
            .as_secs_f64();
        self.time
            .deadline
            .filter(|end| now >= *end)
            .map(|_| "shared allocator deadline exhausted")
    }
}

pub(crate) fn require_model_capacity(path: Option<&Path>) -> Result<(), crate::WorkerError> {
    if let Ok(Some(snapshot)) = read(path)
        && let Some(reason) = snapshot.exhaustion()
    {
        return Err(crate::WorkerError::ResourceExhausted(reason.into()));
    }
    // The authoritative allocator still admits each actual request. Unknown views
    // do not authorize spending, and are exposed as unavailable in planning context.
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn absent_unlimited_exhausted_and_inconsistent_views_remain_distinct() {
        assert!(read(None).unwrap().is_none());
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("resources.json");
        let write = |limit, remaining| {
            std::fs::write(&path,serde_json::json!({
            "schema":"task_resources/v1","allocation_id":"task","observed_at":1.0,
            "model_requests":{"limit":limit,"reserved":3,"remaining":remaining},"time":{"deadline":null}
        }).to_string()).unwrap()
        };
        write(None::<u64>, None::<u64>);
        assert!(read(Some(&path)).unwrap().unwrap().exhaustion().is_none());
        write(Some(3), Some(0));
        assert!(require_model_capacity(Some(&path)).is_err());
        write(Some(10), Some(0));
        assert!(read(Some(&path)).is_err());
        assert!(require_model_capacity(Some(&path)).is_ok());
    }
}
