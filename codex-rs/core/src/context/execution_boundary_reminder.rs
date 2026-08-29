use super::ContextualUserFragment;
use codex_protocol::models::ContentItemKind;

pub(crate) struct ExecutionBoundaryReminder {
    text: String,
    content_kind: ContentItemKind,
}

impl ExecutionBoundaryReminder {
    pub(crate) fn new(text: String, content_kind: ContentItemKind) -> Self {
        Self { text, content_kind }
    }
}

impl ContextualUserFragment for ExecutionBoundaryReminder {
    fn role(&self) -> &'static str {
        "developer"
    }

    fn content_kind(&self) -> ContentItemKind {
        self.content_kind.clone()
    }

    fn markers(&self) -> (&'static str, &'static str) {
        Self::type_markers()
    }

    fn type_markers() -> (&'static str, &'static str) {
        (
            "<execution_boundary_reminder>\n",
            "\n</execution_boundary_reminder>",
        )
    }

    fn body(&self) -> String {
        self.text.clone()
    }
}
