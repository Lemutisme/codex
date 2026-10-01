use pretty_assertions::assert_eq;

use super::bounded_head_tail;

#[test]
fn head_and_tail_survive_and_the_omission_is_stated() {
    let text = format!("HEAD{}TAIL", "x".repeat(1000));

    let bounded = bounded_head_tail(&text, 40);

    assert!(bounded.starts_with("HEAD"), "{bounded}");
    assert!(bounded.ends_with("TAIL"), "{bounded}");
    assert!(bounded.contains("bytes omitted"), "{bounded}");
}

#[test]
fn short_text_is_unchanged() {
    assert_eq!(bounded_head_tail("short", 40), "short");
}
