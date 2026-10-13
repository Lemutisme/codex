use super::*;
use pretty_assertions::assert_eq;

#[test]
fn a_session_changes_context_not_the_original_grant() {
    let initial = Budget::new(
        SuccessionSettings {
            max_sessions: 2,
            total_secs: 100,
        },
        /*now*/ 1000,
    )
    .unwrap();
    let lesson = Lesson {
        subject: Digest::of(b"failed"),
        residual: "test failed".into(),
    };
    let (pending, deadline_ms) = initial
        .reserve(
            "child-1".into(),
            lesson.clone(),
            /*now*/ 11000,
            /*verification_reserve_secs*/ 20,
        )
        .unwrap();
    assert_eq!(
        (deadline_ms, pending.deadline_ms, pending.launches),
        (81000, 101000, 1)
    );
    assert!(
        pending
            .reserve(
                "duplicate".into(),
                lesson.clone(),
                /*now*/ 12000,
                /*verification_reserve_secs*/ 20
            )
            .is_err()
    );
    let completed = Budget {
        pending: None,
        ..pending
    };
    let (second, deadline_ms) = completed
        .reserve(
            "child-2".into(),
            lesson.clone(),
            /*now*/ 61000,
            /*verification_reserve_secs*/ 20,
        )
        .unwrap();
    assert_eq!(
        (deadline_ms, second.deadline_ms, second.launches),
        (81000, 101000, 2)
    );
    let exhausted = Budget {
        pending: None,
        ..second
    };
    assert!(
        exhausted
            .reserve(
                "child-3".into(),
                lesson.clone(),
                /*now*/ 62000,
                /*verification_reserve_secs*/ 20
            )
            .is_err()
    );
    assert!(
        initial
            .reserve(
                "late".into(),
                lesson.clone(),
                /*now*/ 82000,
                /*verification_reserve_secs*/ 20
            )
            .is_err()
    );
    assert!(
        initial
            .reserve(
                "clock".into(),
                lesson,
                /*now*/ 999,
                /*verification_reserve_secs*/ 20
            )
            .is_err()
    );
}
