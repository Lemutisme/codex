//! Context-level work selection. It grants no authority and changes no verdict.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::WorkerError;

pub(crate) const DEFAULT_INSTRUCTIONS: &str = include_str!("../../policies/continuation.md");

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Action {
    Resume,
    Successor,
    Rest,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Choice {
    pub action: Action,
    pub requirements: Vec<String>,
    pub next_step: String,
}

pub(crate) fn schema(actions: &[Action], requirements: &[String]) -> Value {
    super::strict_object(json!({
        "action":{"type":"string","enum":actions},
        "requirements":{"type":"array","items":{"type":"string","enum":requirements}},
        "next_step":{"type":"string","description":"A concrete next investigation/repair, or why no useful authorized action can currently be selected. This is a plan, not evidence of completion."},
    }))
}

pub(crate) fn parse(
    message: &str,
    actions: &[Action],
    requirements: &[String],
) -> Result<Choice, WorkerError> {
    if message.len() > 64 << 10 {
        return Err(WorkerError::InputBudget(
            "continuation response exceeds 64 KiB".into(),
        ));
    }
    let choice: Choice =
        serde_json::from_str(message).map_err(|e| WorkerError::Malformed(e.to_string()))?;
    let mut seen = std::collections::BTreeSet::new();
    if !actions.contains(&choice.action)
        || choice.next_step.trim().is_empty()
        || choice
            .requirements
            .iter()
            .any(|id| !requirements.contains(id) || !seen.insert(id))
        || (choice.action == Action::Rest) != choice.requirements.is_empty()
    {
        return Err(WorkerError::Malformed("continuation must select an offered action and undisputed obligations; rest has no work targets".into()));
    }
    Ok(choice)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strategy_choice_cannot_add_scope_or_execution_authority() {
        let actions = [Action::Resume, Action::Rest];
        let allowed = ["R1".to_string()];
        let choice = |action, ids| {
            json!({"action":action,"requirements":ids,"next_step":"Inspect the retained case."})
                .to_string()
        };
        assert!(parse(&choice("resume", json!(["R1"])), &actions, &allowed).is_ok());
        assert!(parse(&choice("rest", json!([])), &actions, &allowed).is_ok());
        for (action, ids) in [
            ("successor", json!(["R1"])),
            ("resume", json!(["R2"])),
            ("resume", json!([])),
            ("rest", json!(["R1"])),
            ("resume", json!(["R1", "R1"])),
        ] {
            assert!(parse(&choice(action, ids), &actions, &allowed).is_err());
        }
    }
}
