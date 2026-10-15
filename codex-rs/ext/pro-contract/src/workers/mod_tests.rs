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

#[test]
fn truncation_marker_and_unicode_fit_inside_the_requested_budget() {
    let text = "中文🦀".repeat(500);
    for cap in 0..=text.len() + 1 {
        let result = super::bounded(&text, cap);
        assert!(result.len() <= cap);
        if cap >= text.len() {
            assert_eq!(result, text);
        }
    }
}
