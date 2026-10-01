use std::collections::BTreeMap;

use codex_pro_contract::Digest;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::ExperimentEvent;
use super::ExperimentKind;
use super::Identities;
use crate::Ledger;
use crate::LedgerError;

async fn ledger(dir: &std::path::Path) -> Ledger {
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(dir).expect("absolute tempdir"),
    );
    Ledger::open(&sqlite, dir).await.expect("open ledger")
}

fn identities() -> Identities {
    Identities {
        harness: Some("ab".repeat(32)),
        policies: BTreeMap::from([("reviewer".to_string(), Digest::of(b"reviewer"))]),
        model: Some("gpt-5.6-luna".to_string()),
        effort: Some("max".to_string()),
        evaluator_epoch: None,
    }
}

fn event(kind: ExperimentKind, body: serde_json::Value) -> ExperimentEvent {
    ExperimentEvent {
        kind,
        identities: identities(),
        body,
    }
}

async fn raw_pool(dir: &std::path::Path) -> sqlx::SqlitePool {
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(dir).expect("absolute tempdir"),
    );
    sqlite
        .open_read_write_pool(&dir.join(crate::LEDGER_FILE))
        .await
        .expect("raw pool")
}

#[tokio::test]
async fn events_append_in_order_and_chain() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;

    let first = ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({"run_id": "r1"})))
        .await
        .expect("append");
    let second = ledger
        .append_experiment(&event(ExperimentKind::Execution, json!({"run_id": "r1"})))
        .await
        .expect("append");

    assert_eq!((first.seq, second.prev_hash), (1, first.hash));
    assert_eq!(
        ledger.experiments().await.expect("list"),
        vec![first, second]
    );
    ledger
        .verify_experiment_chain()
        .await
        .expect("chain verifies");
}

#[tokio::test]
async fn events_cannot_be_updated_or_deleted() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({})))
        .await
        .expect("append");
    let pool = raw_pool(dir.path()).await;

    let update = sqlx::query("UPDATE experiment_events SET kind = 'label'")
        .execute(&pool)
        .await;
    let delete = sqlx::query("DELETE FROM experiment_events")
        .execute(&pool)
        .await;

    assert!(update.is_err() && delete.is_err(), "{update:?} {delete:?}");
}

#[tokio::test]
async fn a_label_needs_its_evaluator_epoch_and_verification_needs_policies() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    let mut no_policies = event(ExperimentKind::Verification, json!({}));
    no_policies.identities.policies.clear();

    let label = ledger
        .append_experiment(&event(ExperimentKind::Label, json!({})))
        .await;
    let verification = ledger.append_experiment(&no_policies).await;

    assert!(
        matches!(label, Err(LedgerError::InvalidEvent(_))),
        "{label:?}"
    );
    assert!(
        matches!(verification, Err(LedgerError::InvalidEvent(_))),
        "{verification:?}"
    );
}

#[tokio::test]
async fn body_key_order_does_not_change_the_hash() {
    let dir_a = tempfile::tempdir().expect("tempdir");
    let dir_b = tempfile::tempdir().expect("tempdir");
    let a: serde_json::Value =
        serde_json::from_str(r#"{"b": 1, "a": {"y": 2, "x": 3}}"#).expect("json");
    let b: serde_json::Value =
        serde_json::from_str(r#"{"a": {"x": 3, "y": 2}, "b": 1}"#).expect("json");

    let first = ledger(dir_a.path())
        .await
        .append_experiment(&event(ExperimentKind::Assignment, a))
        .await
        .expect("append");
    let second = ledger(dir_b.path())
        .await
        .append_experiment(&event(ExperimentKind::Assignment, b))
        .await
        .expect("append");

    assert_eq!(first.hash, second.hash);
}

#[tokio::test]
async fn a_forged_row_breaks_the_chain() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = ledger(dir.path()).await;
    let first = ledger
        .append_experiment(&event(ExperimentKind::Assignment, json!({})))
        .await
        .expect("append");
    let forged = serde_json::to_string(&event(ExperimentKind::Label, json!({}))).expect("json");
    let pool = raw_pool(dir.path()).await;
    sqlx::query(
        "INSERT INTO experiment_events (kind, event_json, prev_hash, hash) VALUES ('label', ?, ?, ?)",
    )
    .bind(forged)
    .bind(first.hash.to_string())
    .bind("11".repeat(32))
    .execute(&pool)
    .await
    .expect("raw insert");

    let verdict = ledger.verify_experiment_chain().await;

    assert!(
        matches!(&verdict, Err(LedgerError::Corrupt(message)) if message.contains("breaks the chain")),
        "{verdict:?}"
    );
}
