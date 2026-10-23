//! Hidden isolated workers; only reviewers receive a frozen read-only evidence capability.

pub(crate) mod cases;
pub(crate) mod continuation;
pub(crate) mod drafter;
mod packet;
pub(crate) mod policies;
pub(crate) mod prober;
mod request_sources;
pub(crate) mod review_evidence;
pub(crate) mod reviewer;
pub(crate) mod runtime;

#[cfg(test)]
#[path = "mod_tests.rs"]
mod tests;

/// Evidence cap for drafting/probing. Worker packets are split into bounded context items;
/// reviewers obtain candidate evidence through the separate read-only catalog.
pub(crate) const PROMPT_EVIDENCE_CAP: usize = 60_000;
pub(crate) const WORKER_PACKET_CAP: usize = 96_000;
/// AdditionalContext truncates values at 1,000 approximate tokens (4KB).
/// Keep margin, and exercise its actual renderer in packet_tests.
pub(crate) const WORKER_PACKET_PART_CAP: usize = 3_500;

#[derive(Debug, thiserror::Error)]
pub enum WorkerError {
    #[error("worker input exceeds its byte budget: {0}")]
    InputBudget(String),
    #[error("worker thread could not start: {0}")]
    Start(String),
    #[error("worker turn did not start: {0}")]
    NotStarted(String),
    #[error("worker turn timed out")]
    TimedOut,
    #[error("worker turn was aborted")]
    Aborted,
    #[error("worker turn failed: {0}")]
    Failed(String),
    /// Native execution ended with an error instead of an assessment. The
    /// responsibility and original grant remain available to an authorized caller.
    #[error("worker execution interrupted: {0}")]
    Interrupted(String),
    #[error("worker resources exhausted: {0}")]
    ResourceExhausted(String),
    #[error("worker output is malformed: {0}")]
    Malformed(String),
}

/// Truncates `text` to at most `cap` bytes on a character boundary, marking the omission.
pub(crate) fn bounded(text: &str, cap: usize) -> String {
    if text.len() <= cap {
        return text.to_string();
    }
    // Reserve the marker before slicing; the marker itself consumes packet bytes.
    let marker = format!("\n[... {} bytes omitted ...]", text.len());
    if cap < marker.len() {
        return "[omitted]"[..cap.min(9)].to_string();
    }
    let end = text.floor_char_boundary(cap - marker.len());
    format!(
        "{}\n[... {} bytes omitted ...]",
        &text[..end],
        text.len() - end
    )
}

/// Keeps the first and last `cap / 2` bytes; errors usually sit at the end of a log.
pub(crate) fn bounded_head_tail(text: &str, cap: usize) -> String {
    if text.len() <= cap {
        return text.to_string();
    }
    let head = text.floor_char_boundary(cap / 2);
    let tail = text.ceil_char_boundary(text.len() - cap / 2);
    format!(
        "{}\n[... {} bytes omitted ...]\n{}",
        &text[..head],
        tail - head,
        &text[tail..]
    )
}

/// A strict structured-output object: every property required, nothing else allowed.
pub(crate) fn strict_object(properties: serde_json::Value) -> serde_json::Value {
    let required: Vec<serde_json::Value> = properties
        .as_object()
        .map(|object| object.keys().map(|key| serde_json::json!(key)).collect())
        .unwrap_or_default();
    serde_json::json!({
        "type": "object",
        "additionalProperties": false,
        "required": required,
        "properties": properties,
    })
}
