//! Context-level work selection. It grants no authority and changes no verdict.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::WorkerError;

pub(crate) const DEFAULT_INSTRUCTIONS: &str = include_str!("../../policies/continuation.md");

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Action {
    Check,
    Diagnose,
    Verify,
    Resume,
    Successor,
    Rest,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Choice {
    Check {
        reason: String,
    },
    Diagnose {
        question: String,
    },
    Verify {
        reason: String,
    },
    Resume {
        requirements: Vec<String>,
        next_step: String,
    },
    Successor {
        requirements: Vec<String>,
        next_step: String,
    },
    Rest {
        reason: String,
    },
}

impl Choice {
    pub(crate) fn action(&self) -> Action {
        match self {
            Self::Check { .. } => Action::Check,
            Self::Diagnose { .. } => Action::Diagnose,
            Self::Verify { .. } => Action::Verify,
            Self::Resume { .. } => Action::Resume,
            Self::Successor { .. } => Action::Successor,
            Self::Rest { .. } => Action::Rest,
        }
    }
}

pub(crate) fn schema(actions: &[Action], requirements: &[String]) -> Value {
    // A nested union is supported by structured-output providers. Rest has no
    // work targets; the schema cannot request a combination the parser rejects.
    let variants: Vec<_> = actions.iter().map(|action| {
        if matches!(action, Action::Rest | Action::Check | Action::Verify) {
            super::strict_object(json!({
                "action":{"type":"string","enum":[action]},
                "reason":{"type":"string","minLength":1,"description":"Why this offered operation is useful, or why work should rest. Selecting an operation is not acceptance."},
            }))
        } else if *action == Action::Diagnose {
            super::strict_object(json!({
                "action":{"type":"string","enum":[action]},
                "question":{"type":"string","minLength":1,"description":"The concrete uncertainty to investigate on the frozen artifact. This requests scoped diagnosis, not whole-task acceptance."},
            }))
        } else {
            super::strict_object(json!({
                "action":{"type":"string","enum":[action]},
                "requirements":{"type":"array","minItems":1,"items":{"type":"string","enum":requirements}},
                "next_step":{"type":"string","minLength":1,"description":"Concrete work for the executor using its offered capabilities. A plan, not evidence of completion."},
            }))
        }
    }).collect();
    super::strict_object(json!({"choice":{"anyOf":variants}}))
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
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Response {
        choice: Choice,
    }
    let Response { mut choice } =
        serde_json::from_str(message).map_err(|e| WorkerError::Malformed(e.to_string()))?;
    if !actions.contains(&choice.action()) {
        return Err(WorkerError::Malformed(
            "continuation action was not offered".into(),
        ));
    }
    match &mut choice {
        Choice::Rest { reason } | Choice::Check { reason } | Choice::Verify { reason }
            if !reason.trim().is_empty() => {}
        Choice::Diagnose { question } if !question.trim().is_empty() => {}
        Choice::Resume {
            requirements: ids,
            next_step,
        }
        | Choice::Successor {
            requirements: ids,
            next_step,
        } if !ids.is_empty()
            && !next_step.trim().is_empty()
            && ids.iter().all(|id| requirements.contains(id)) =>
        {
            // Repeating the same scope adds no authority and is not a failure.
            let mut seen = std::collections::BTreeSet::new();
            ids.retain(|id| seen.insert(id.clone()));
        }
        _ => {
            return Err(WorkerError::Malformed(
                "continuation requires nonempty reasoning and offered work scopes".into(),
            ));
        }
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
            json!({"choice":{"action":action,"requirements":ids,"next_step":"Inspect the retained case."}}).to_string()
        };
        assert!(parse(&choice("resume", json!(["R1"])), &actions, &allowed).is_ok());
        assert!(
            parse(
                r#"{"choice":{"action":"rest","reason":"No useful work available."}}"#,
                &actions,
                &allowed
            )
            .is_ok()
        );
        for (action, ids) in [
            ("successor", json!(["R1"])),
            ("resume", json!(["R2"])),
            ("resume", json!([])),
            ("rest", json!(["R1"])),
        ] {
            assert!(parse(&choice(action, ids), &actions, &allowed).is_err());
        }
        let duplicate = parse(&choice("resume", json!(["R1", "R1"])), &actions, &allowed).unwrap();
        assert!(matches!(duplicate, Choice::Resume { requirements, .. } if requirements == ["R1"]));
    }
}
