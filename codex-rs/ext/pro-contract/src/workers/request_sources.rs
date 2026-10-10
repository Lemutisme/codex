//! Host-owned references to the human request. Workspace text never acquires request authority.

use super::WorkerError;

const MAX_BYTES: usize = 10_000;
const MAX_SOURCES: usize = 64;
const CHUNK_BYTES: usize = 512;

pub(super) struct RequestSources<'a> {
    spans: Vec<&'a str>,
    complete: bool,
}

impl<'a> RequestSources<'a> {
    pub(super) fn new(request: &'a str) -> Self {
        let mut spans = Vec::new();
        let mut consumed = 0;
        let mut rest = request;
        while !rest.is_empty() && consumed < MAX_BYTES && spans.len() < MAX_SOURCES {
            let end = rest.floor_char_boundary(CHUNK_BYTES.min(MAX_BYTES - consumed));
            // Source slots bound chunks, not lines: a short allowlist must not
            // consume every slot before the actual task requirements arrive.
            let count = rest[..end].rfind('\n').map_or(end, |index| index + 1);
            if count == 0 {
                return Self {
                    spans,
                    complete: false,
                };
            }
            spans.push(&rest[..count]);
            consumed += count;
            rest = &rest[count..];
        }
        Self {
            spans,
            complete: consumed == request.len(),
        }
    }

    pub(super) fn render(&self) -> String {
        let mut output = String::new();
        for (index, text) in self.spans.iter().enumerate() {
            output.push_str(&format!("[request:{index}]\n{text}\n"));
        }
        if !self.complete {
            output.push_str("[request exceeds source budget; decline the draft rather than omit requirements]\n");
        }
        output
    }

    pub(super) fn resolve(&self, id: &str) -> Result<String, WorkerError> {
        let index = id
            .strip_prefix("request:")
            .and_then(|index| index.parse::<usize>().ok());
        match index.filter(|index| id == format!("request:{index}")) {
            Some(index)
                if self.complete
                    && index < self.spans.len()
                    && self.spans[index].chars().any(char::is_alphanumeric) =>
            {
                Ok(self.spans[index].to_string())
            }
            _ => Err(WorkerError::Malformed(
                "unknown or incomplete human-request source".to_string(),
            )),
        }
    }
}

#[cfg(test)]
#[path = "request_sources_tests.rs"]
mod tests;
