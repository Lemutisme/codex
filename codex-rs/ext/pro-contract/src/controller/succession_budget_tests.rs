use super::*;
use pretty_assertions::assert_eq;

#[test]
fn time_only_grant_does_not_invent_session_or_stagnation_limits() {
    let mut budget = Budget::new(
        SuccessionSettings {
            max_sessions: None,
            total_secs: 100,
        },
        1000,
    )
    .unwrap();
    let original_deadline = budget.deadline_ms;
    let lesson = Lesson {
        subject: Digest::of(b"same artifact"),
        residual: "New reasoning may still advance the task.".into(),
    };
    for i in 0..20 {
        budget = budget
            .reserve(format!("child-{i}"), lesson.clone(), 2000 + i * 1000, 1)
            .unwrap()
            .0;
        budget.pending = None;
        assert_eq!(budget.deadline_ms, original_deadline);
        let encoded = serde_json::to_string(&budget).unwrap();
        budget = serde_json::from_str(&encoded).unwrap();
    }
    assert!(
        budget
            .reserve("expired".into(), lesson, original_deadline, 0)
            .is_err()
    );
}

#[test]
fn a_session_changes_context_not_the_original_grant() {
    let initial = Budget::new(
        SuccessionSettings {
            max_sessions: Some(2),
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
