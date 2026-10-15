use super::request;
use codex_context_fragments::AdditionalContextUserFragment;
use codex_context_fragments::ContextualUserFragment;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use pretty_assertions::assert_eq;

#[test]
fn packet_parts_are_bounded_ordered_and_preserve_unicode_bytes() {
    let input = "request 中文\n".repeat(1500);
    let request = request(&input).unwrap();
    let mut restored = String::new();
    for (key, value) in &request.additional_context {
        let item = ContextualUserFragment::into(AdditionalContextUserFragment::new(
            key.clone(),
            value.value.clone(),
        ));
        let ResponseItem::Message { content, .. } = item else {
            panic!("context message")
        };
        let [ContentItem::InputText { text }] = content.as_slice() else {
            panic!("text fragment")
        };
        let payload = text
            .strip_prefix(&format!("<external_{key}>"))
            .unwrap()
            .strip_suffix(&format!("</external_{key}>"))
            .unwrap();
        restored.push_str(payload);
    }
    assert_eq!(restored, input);
}

#[test]
fn oversized_packet_is_rejected_before_starting_inference() {
    assert!(request(&"x".repeat(96_001)).is_err());
}
