use super::ContextualUserFragment;
use codex_protocol::models::ContentItemKind;

/// Executor guidance bound outside the normative ProContract specification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProContractExecutionPolicy {
    policy: String,
}

impl ProContractExecutionPolicy {
    pub fn new(policy: impl Into<String>) -> Self {
        Self {
            policy: policy.into(),
        }
    }
}

impl ContextualUserFragment for ProContractExecutionPolicy {
    fn role(&self) -> &'static str {
        "developer"
    }

    fn content_kind(&self) -> ContentItemKind {
        ContentItemKind("pro_contract.execution_policy".to_string())
    }

    fn requires_separate_message(&self) -> bool {
        true
    }

    fn markers(&self) -> (&'static str, &'static str) {
        Self::type_markers()
    }

    fn type_markers() -> (&'static str, &'static str) {
        (
            "<pro_contract_execution_policy>\n",
            "\n</pro_contract_execution_policy>",
        )
    }

    fn body(&self) -> String {
        self.policy.clone()
    }
}
