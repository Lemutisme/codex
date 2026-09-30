//! Whether a thread may receive contracts at all (spec §6.0, §13).

use crate::EvaluationProfile;
use crate::Settings;

/// The facts eligibility depends on, gathered at thread start.
pub(crate) struct EligibilityFacts<'a> {
    pub feature_enabled: bool,
    /// Internal workers and subagents never receive contracts.
    pub internal_or_subagent: bool,
    pub persistent: bool,
    pub settings: Option<&'a Settings>,
    /// Ids of the environments selected for the thread.
    pub environment_ids: Vec<&'a str>,
    pub mcp_server_count: usize,
    pub notify_configured: bool,
    pub hooks_enabled: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum Eligibility<'a> {
    Eligible(&'a EvaluationProfile),
    /// Contracts are possible in principle but not here; the reason is recorded.
    Abstain(String),
    /// The feature does not apply to this thread at all; nothing is recorded.
    Inactive,
}

pub(crate) fn eligibility<'a>(facts: &EligibilityFacts<'a>) -> Eligibility<'a> {
    if !facts.feature_enabled || facts.internal_or_subagent {
        return Eligibility::Inactive;
    }
    let abstain = |reason: &str| Eligibility::Abstain(reason.to_string());
    let Some(profile) = facts
        .settings
        .and_then(|settings| settings.evaluation.as_ref())
    else {
        return abstain("no pre-authorized evaluation principal is configured");
    };
    if !facts.persistent {
        return abstain("the thread has no persistent state");
    }
    if facts.environment_ids != [profile.environment_id.as_str()] {
        return abstain("the executor environment is not exactly the configured isolated container");
    }
    if facts.mcp_server_count > 0 {
        return abstain("MCP servers are reachable outside the isolated environment");
    }
    if facts.notify_configured {
        return abstain("a notify command runs outside the isolated environment");
    }
    if facts.hooks_enabled {
        return abstain("command hooks run outside the isolated environment");
    }
    Eligibility::Eligible(profile)
}

#[cfg(test)]
#[path = "eligibility_tests.rs"]
mod tests;
