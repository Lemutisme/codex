//! Hidden, isolated, tool-less worker threads of the automatic Principal.

pub(crate) mod cases;
pub(crate) mod drafter;
pub(crate) mod prober;
pub(crate) mod reviewer;
pub(crate) mod runtime;

#[cfg(test)]
#[path = "mod_tests.rs"]
mod tests;

/// Hard cap on the evidence text placed in a worker prompt; the reviewer's candidate view has its
/// own cap (`reviewer::CANDIDATE_VIEW`).
pub(crate) const PROMPT_EVIDENCE_CAP: usize = 60_000;

#[derive(Debug, thiserror::Error)]
pub enum WorkerError {
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
    #[error("worker output is malformed: {0}")]
    Malformed(String),
}

/// Truncates `text` to at most `cap` bytes on a character boundary, marking the omission.
pub(crate) fn bounded(text: &str, cap: usize) -> String {
    if text.len() <= cap {
        return text.to_string();
    }
    let end = text.floor_char_boundary(cap);
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
