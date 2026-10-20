use super::*;
use pretty_assertions::assert_eq;

#[test]
fn an_open_ended_task_keeps_identity_and_accounting_without_a_clock_bound() {
    let mut budget = Budget::new(
        SuccessionSettings {
            max_sessions: None,
            total_secs: None,
        },
        1000,
    )
    .unwrap();
    let lesson = Lesson {
        subject: Digest::of(b"work"),
        residual: "a concrete observation".into(),
    };
    for (i, now) in [1001, 20 * 365 * 24 * 3600 * 1000, 999]
        .into_iter()
        .enumerate()
    {
        let (next, deadline) = budget
            .reserve(format!("session-{i}"), lesson.clone(), now)
            .unwrap();
        assert_eq!(deadline, None);
        budget = next;
        budget.pending = None;
        let encoded = serde_json::to_value(&budget).unwrap();
        assert!(encoded["deadline_ms"].is_null());
        assert!(encoded["grant"]["total_secs"].is_null());
        budget = serde_json::from_value(encoded).unwrap();
        assert_eq!(budget.started_ms, 1000);
        assert_eq!(budget.launches, i as u32 + 1);
    }
}

#[test]
fn legacy_finite_records_remain_finite_and_missing_or_inconsistent_deadlines_are_rejected() {
    let budget = Budget::new(
        SuccessionSettings {
            max_sessions: Some(2),
            total_secs: Some(60),
        },
        1000,
    )
    .unwrap();
    let record = serde_json::to_value(&budget).unwrap();
    assert_eq!(record["deadline_ms"], 61000);
    assert_eq!(record["grant"]["total_secs"], 60);
    assert_eq!(
        serde_json::from_value::<Budget>(record.clone()).unwrap(),
        budget
    );
    for deadline in [serde_json::Value::Null, serde_json::json!(62000)] {
        let mut invalid = record.clone();
        invalid["deadline_ms"] = deadline;
        assert!(serde_json::from_value::<Budget>(invalid).is_err());
    }
    let mut missing = record;
    missing.as_object_mut().unwrap().remove("deadline_ms");
    assert!(serde_json::from_value::<Budget>(missing).is_err());
    assert!(
        Budget::new(
            SuccessionSettings {
                max_sessions: None,
                total_secs: Some(0)
            },
            1000
        )
        .is_err()
    );
}

#[test]
fn a_count_only_grant_still_enforces_pending_ownership_and_the_declared_count() {
    let budget = Budget::new(
        SuccessionSettings {
            max_sessions: Some(1),
            total_secs: None,
        },
        1000,
    )
    .unwrap();
    let lesson = Lesson {
        subject: Digest::of(b"work"),
        residual: "repair".into(),
    };
    let (mut pending, _) = budget.reserve("one".into(), lesson.clone(), 2000).unwrap();
    assert!(
        pending
            .reserve("duplicate".into(), lesson.clone(), 3000)
            .is_err()
    );
    pending.pending = None;
    assert!(pending.reserve("two".into(), lesson, 4000).is_err());
}

#[test]
fn remaining_time_is_not_rounded_away_or_reserved_for_hypothetical_verification() {
    let budget = Budget::new(
        SuccessionSettings {
            max_sessions: None,
            total_secs: Some(1),
        },
        1000,
    )
    .unwrap();
    let (reserved, deadline) = budget
        .reserve(
            "last-millisecond".into(),
            Lesson {
                subject: Digest::of(b"work"),
                residual: "continue within the actual grant".into(),
            },
            1999,
        )
        .unwrap();
    assert_eq!(deadline, Some(2000));
    assert_eq!(
        (reserved.started_ms, reserved.deadline_ms),
        (1000, Some(2000))
    );
}

#[test]
fn time_only_grant_does_not_invent_session_or_stagnation_limits() {
    let mut budget = Budget::new(
        SuccessionSettings {
            max_sessions: None,
            total_secs: Some(100),
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
            .reserve(format!("child-{i}"), lesson.clone(), 2000 + i * 1000)
            .unwrap()
            .0;
        budget.pending = None;
        assert_eq!(budget.deadline_ms, original_deadline);
        let encoded = serde_json::to_string(&budget).unwrap();
        budget = serde_json::from_str(&encoded).unwrap();
    }
    assert!(
        budget
            .reserve("expired".into(), lesson, original_deadline.unwrap())
            .is_err()
    );
}

#[test]
fn a_session_changes_context_not_the_original_grant() {
    let initial = Budget::new(
        SuccessionSettings {
            max_sessions: Some(2),
            total_secs: Some(100),
        },
        /*now*/ 1000,
    )
    .unwrap();
    let lesson = Lesson {
        subject: Digest::of(b"failed"),
        residual: "test failed".into(),
    };
    let (pending, deadline_ms) = initial
        .reserve("child-1".into(), lesson.clone(), /*now*/ 11000)
        .unwrap();
    assert_eq!(
        (deadline_ms, pending.deadline_ms, pending.launches),
        (Some(101000), Some(101000), 1)
    );
    assert!(
        pending
            .reserve("duplicate".into(), lesson.clone(), /*now*/ 12000,)
            .is_err()
    );
    let completed = Budget {
        pending: None,
        ..pending
    };
    let (second, deadline_ms) = completed
        .reserve("child-2".into(), lesson.clone(), /*now*/ 61000)
        .unwrap();
    assert_eq!(
        (deadline_ms, second.deadline_ms, second.launches),
        (Some(101000), Some(101000), 2)
    );
    let exhausted = Budget {
        pending: None,
        ..second
    };
    assert!(
        exhausted
            .reserve("child-3".into(), lesson.clone(), /*now*/ 62000,)
            .is_err()
    );
    assert!(
        initial
            .reserve("late".into(), lesson.clone(), /*now*/ 101000,)
            .is_err()
    );
    assert!(
        initial
            .reserve("clock".into(), lesson, /*now*/ 999,)
            .is_err()
    );
}
