use super::request;
use pretty_assertions::assert_eq;

#[test]
fn packet_parts_are_bounded_ordered_and_preserve_unicode_bytes() {
    let input = "request 中文\n".repeat(1500);
    let request = request(&input).unwrap();
    let mut restored = String::new();
    for value in request.additional_context.values() {
        assert!(value.value.len() <= 7000);
        restored.push_str(&value.value);
    }
    assert_eq!(restored, input);
}

#[test]
fn oversized_packet_is_rejected_before_starting_inference() {
    assert!(request(&"x".repeat(96_001)).is_err());
}
