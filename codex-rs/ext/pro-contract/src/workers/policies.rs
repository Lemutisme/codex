//! The judgment workers' instructions: the part of each worker a version may change. Their output
//! schemas and the case format stay fixed: they are the protocol the lane depends on.

use std::path::Path;

use super::drafter;
use super::prober;
use super::reviewer;

/// One instruction text per worker, read from a version's policy bundle.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Policies {
    pub drafter: String,
    pub prober: String,
    pub reviewer: String,
}

impl Default for Policies {
    fn default() -> Self {
        Self {
            drafter: drafter::DEFAULT_INSTRUCTIONS.to_string(),
            prober: prober::DEFAULT_INSTRUCTIONS.to_string(),
            reviewer: reviewer::DEFAULT_INSTRUCTIONS.to_string(),
        }
    }
}

impl Policies {
    /// Reads `drafter.md`, `prober.md` and `reviewer.md` from a bundle directory; a missing file
    /// keeps the built-in text, an unreadable one is an error.
    pub(crate) fn load(dir: &Path) -> std::io::Result<Self> {
        let read = |name: &str, default: &str| match std::fs::read_to_string(dir.join(name)) {
            Ok(text) => Ok(text),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(default.to_string()),
            Err(error) => Err(error),
        };
        Ok(Self {
            drafter: read("drafter.md", drafter::DEFAULT_INSTRUCTIONS)?,
            prober: read("prober.md", prober::DEFAULT_INSTRUCTIONS)?,
            reviewer: read("reviewer.md", reviewer::DEFAULT_INSTRUCTIONS)?,
        })
    }
}

#[cfg(test)]
#[path = "policies_tests.rs"]
mod tests;
