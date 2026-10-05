use pretty_assertions::assert_eq;
use serde_json::json;

use super::append_command;
use super::apply_command;
use super::capture_command;
use super::contract_command;
use super::digest_command;
use super::events_command;
use super::materialize_command;

type TestResult = Result<(), Box<dyn std::error::Error + Send + Sync>>;

#[tokio::test]
async fn capture_then_materialize_round_trips_after_reopening() -> TestResult {
    let dir = tempfile::tempdir()?;
    let root = dir.path().join("ws");
    std::fs::create_dir_all(&root)?;
    std::fs::write(root.join("main.rs"), "fn main() {}\n")?;
    std::fs::write(root.join("executable"), "reference")?;
    let store = dir.path().join("store");

    let captured = capture_command(&store, &root, &["executable".to_string()]).await?;
    std::fs::write(root.join("main.rs"), "changed after capture\n")?;
    let dest = dir.path().join("out");
    materialize_command(&store, &captured.subject_hash, &dest).await?;

    assert_eq!(
        std::fs::read_to_string(dest.join("main.rs"))?,
        "fn main() {}\n"
    );
    assert!(!dest.join("executable").exists());
    Ok(())
}

#[tokio::test]
async fn materializing_an_unknown_subject_fails() -> TestResult {
    let dir = tempfile::tempdir()?;
    let unknown = codex_pro_contract::Digest::of(b"unknown").to_string();

    let result =
        materialize_command(&dir.path().join("store"), &unknown, &dir.path().join("out")).await;

    assert!(result.is_err());
    Ok(())
}

#[tokio::test]
async fn appended_events_are_listed() -> TestResult {
    let dir = tempfile::tempdir()?;
    let store = dir.path().join("store");
    let event = json!({
        "kind": "assignment",
        "identities": {"harness": null, "policies": {}, "model": null, "effort": null, "evaluator_epoch": null},
        "body": {"run_id": "r1"}
    });

    let appended = append_command(&store, &event.to_string()).await?;
    let listed = events_command(&store).await?;

    assert_eq!(appended.seq, 1);
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].event.body["run_id"], "r1");
    Ok(())
}

#[tokio::test]
async fn kernel_commands_apply_idempotently_and_rejections_carry_the_reason() -> TestResult {
    let dir = tempfile::tempdir()?;
    let store = dir.path().join("store");
    let digest = |text: &str| codex_pro_contract::Digest::of(text.as_bytes()).to_string();
    let issue = json!({
        "contract_id": "c1",
        "expected_version": 0,
        "role": "issuer",
        "provenance": "human",
        "command": {"type": "issue", "owner": "operator", "bindings": {
            "terms_hash": digest("terms"),
            "capture_policy_hash": digest("capture"),
            "evidence_policy_hash": digest("evidence"),
        }},
    })
    .to_string();

    let issued = apply_command(&store, "issue:c1", &issue).await?;
    let replayed = apply_command(&store, "issue:c1", &issue).await?;
    assert_eq!((issued.version, replayed.version), (1, 1));
    assert_eq!(contract_command(&store, "c1").await?, Some(issued));
    assert_eq!(contract_command(&store, "c2").await?, None);

    let propose_as_settler = json!({
        "contract_id": "c1",
        "expected_version": 1,
        "role": "settler",
        "provenance": "automation",
        "command": {"type": "propose", "subject_hash": digest("subject")},
    })
    .to_string();
    let rejected = apply_command(&store, "propose:c1", &propose_as_settler).await;
    assert!(
        rejected.is_err_and(|error| error.to_string().contains("requires role")),
        "a wrong role is rejected with the kernel's reason"
    );
    Ok(())
}

#[test]
fn digests_match_the_stores_own_hashing() -> TestResult {
    let value = json!({"b": 1, "a": [true, null]});
    assert_eq!(
        digest_command("version", &value.to_string())?,
        crate::digest_of("version", &value).to_string()
    );
    Ok(())
}
