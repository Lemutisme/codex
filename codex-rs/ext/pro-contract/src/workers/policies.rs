//! The judgment workers' instructions: the part of each worker a version may change. Their output
//! schemas and the case format stay fixed: they are the protocol the lane depends on.

use std::path::Path;

use super::drafter;
use super::prober;
use super::reviewer;

/// Replaceable context for the executor and its judgment workers.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Policies {
    pub work_method: String,
    pub drafter: String,
    pub prober: String,
    pub reviewer: String,
}

impl Default for Policies {
    fn default() -> Self {
        Self {
            work_method: DEFAULT_WORK_METHOD.to_string(),
            drafter: drafter::DEFAULT_INSTRUCTIONS.to_string(),
            prober: prober::DEFAULT_INSTRUCTIONS.to_string(),
            reviewer: reviewer::DEFAULT_INSTRUCTIONS.to_string(),
        }
    }
}

impl Policies {
    /// Reads `work_method.md`, `drafter.md`, `prober.md` and `reviewer.md`; a missing file
    /// keeps the built-in text, an unreadable one is an error.
    pub(crate) fn load(dir: &Path) -> std::io::Result<Self> {
        let read = |name: &str, default: &str| match std::fs::read_to_string(dir.join(name)) {
            Ok(text) => Ok(text),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(default.to_string()),
            Err(error) => Err(error),
        };
        Ok(Self {
            work_method: read("work_method.md", DEFAULT_WORK_METHOD)?,
            drafter: read("drafter.md", drafter::DEFAULT_INSTRUCTIONS)?,
            prober: read("prober.md", prober::DEFAULT_INSTRUCTIONS)?,
            reviewer: read("reviewer.md", reviewer::DEFAULT_INSTRUCTIONS)?,
        })
    }
}

pub(crate) const DEFAULT_WORK_METHOD: &str = include_str!("../../policies/work_method.md");

#[cfg(test)]
#[path = "policies_tests.rs"]
mod tests;
