use super::packet;
use pretty_assertions::assert_eq;

#[test]
fn fresh_context_is_bounded_and_preserves_the_complete_task_and_lessons() {
    let text = "原始任务与失败证据\n".repeat(/*n*/ 500);
    let request = packet(&text).unwrap();
    assert!(
        request
            .additional_context
            .values()
            .all(|part| part.value.len() <= 768)
    );
    assert_eq!(
        request
            .additional_context
            .values()
            .map(|p| p.value.as_str())
            .collect::<String>(),
        text
    );
    assert!(packet(&"x".repeat(/*n*/ 64001)).is_err());
}
