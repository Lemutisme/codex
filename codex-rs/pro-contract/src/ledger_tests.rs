use super::*;
use crate::ArtifactPath;
use crate::ArtifactSpec;
use crate::ContractSpec;
use crate::Decision;
use crate::Draft;
use crate::hash_spec;
use pretty_assertions::assert_eq;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::str::FromStr;

#[tokio::test]
async fn persists_projection_and_rejected_events_atomically() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let options = SqliteConnectOptions::from_str(
        directory
            .path()
            .join("contracts.sqlite")
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
    let ledger = Ledger::initialize(pool).await?;
    let spec = ContractSpec {
        claim: "deliver".to_string(),
        artifacts: ArtifactSpec::new([ArtifactPath::new("executable")?])?,
        requires: Vec::new(),
    };
    let issue = Command::Issue {
        actor: "principal".to_string(),
        draft: Draft {
            id: "delivery".to_string(),
            scope: "thread".to_string(),
            spec_hash: hash_spec(&spec)?,
            spec,
            issuer: "principal".to_string(),
            executor: "worker".to_string(),
        },
    };
    assert_eq!(
        ledger.apply("thread", issue).await?.decision,
        Decision::Accepted
    );
    let persisted = ledger.state("thread").await?;
    let rejected = ledger
        .apply(
            "thread",
            Command::Activate {
                actor: "worker".to_string(),
                contract_id: "delivery".to_string(),
                revision: 1,
            },
        )
        .await?;

    assert!(matches!(rejected.decision, Decision::Rejected { .. }));
    assert_eq!(rejected.state, persisted);
    let events = ledger.events("thread").await?;
    assert_eq!(events.len(), 2);
    assert_eq!(events[1].previous_hash, events[0].hash);
    Ok(())
}
