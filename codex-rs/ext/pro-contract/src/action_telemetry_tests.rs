use super::*;
use crate::binding::ExecutionBinding;
use codex_extension_api::ToolCallOutcome;
use codex_extension_api::ToolName;
use codex_extension_api::ToolPayload;
use pretty_assertions::assert_eq;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::str::FromStr;

#[tokio::test]
async fn reports_only_new_repeat_or_long_action_anomalies() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let options = SqliteConnectOptions::from_str(
        directory
            .path()
            .join("telemetry.sqlite")
            .to_string_lossy()
            .as_ref(),
    )?
    .create_if_missing(true);
    #[expect(
        clippy::disallowed_methods,
        reason = "focused store test does not own a Codex host SQLiteConfig"
    )]
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await?;
    let store = ActionTelemetryStore::initialize(pool).await?;
    let binding = binding();
    let tool_name = ToolName::plain("write_stdin");
    let payload = ToolPayload::Function {
        arguments: r#"{"session_id":7,"chars":""}"#.to_string(),
    };

    store
        .admit(&binding, "call-1", &tool_name, &payload, 100)
        .await?;
    store
        .finish(
            &binding.contract_id,
            "call-1",
            ToolCallOutcome::Completed { success: true },
            1_000,
        )
        .await?;
    assert_eq!(store.reminder(&binding, 0).await?, None);

    store
        .admit(&binding, "call-2", &tool_name, &payload, 2_000)
        .await?;
    store
        .finish(
            &binding.contract_id,
            "call-2",
            ToolCallOutcome::Completed { success: true },
            62_500,
        )
        .await?;
    assert_eq!(
        store.reminder(&binding, 0).await?,
        Some(ActionReminder {
            sequence: 2,
            text: "Host action telemetry: exact `write_stdin` request occurrence 2 in this semantic attempt; the last call took 60500 ms. Repetition is cost, not evidence of progress. Continue only for changed external state or a live hypothesis; otherwise change action or preserve the uncertainty."
                .to_string(),
        })
    );
    assert_eq!(store.reminder(&binding, 2).await?, None);
    Ok(())
}

fn binding() -> ExecutionBinding {
    ExecutionBinding {
        scope: "thread".to_string(),
        ledger_scope: "ledger".to_string(),
        contract_id: "contract".to_string(),
        revision: 1,
        execution_policy: None,
        execution_policy_hash: None,
        dispatched: true,
        resume_same_attempt: false,
        attempts: 1,
        turns_used: 1,
        actions_used: 1,
        next_action_at: 0,
        attempt_key: "1:".to_string(),
        turns_limit: 10,
        actions_limit: 10,
        deadline: 100_000,
        max_attempts: 1,
        lease_owner: Some("owner".to_string()),
        lease_expires_at: 10_000,
    }
}
