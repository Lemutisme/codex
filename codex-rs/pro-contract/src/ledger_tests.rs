use super::*;
use crate::ArtifactPath;
use crate::ArtifactSpec;
use crate::Budget;
use crate::ContractSpec;
use crate::Decision;
use crate::Draft;
use crate::Evidence;
use crate::Resolution;
use crate::Trigger;
use crate::hash_spec;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
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
    let artifacts = ArtifactSpec::new([ArtifactPath::new("executable")?])?;
    let spec = ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver".to_string(),
        brief: String::new(),
        artifacts,
        requires: Vec::new(),
        authority: vec!["filesystem.read".to_string()],
        budget: Budget {
            turns: 4,
            actions: 32,
            deadline: 10_000,
        },
        evidence: Evidence {
            claim: "deliver".to_string(),
            replay: None,
        },
        resolution: Resolution {
            max_attempts: 3,
            retry_delay_ms: 0,
        },
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
                time: 1,
            },
        )
        .await?;

    assert!(matches!(rejected.decision, Decision::Rejected { .. }));
    assert_eq!(rejected.state, persisted);
    let events = ledger.events("thread").await?;
    assert_eq!(events.len(), 2);
    assert_eq!(events[1].previous_hash, events[0].hash);
    let encoded = serde_json::to_string(&persisted)?;
    assert_eq!(
        ledger.quiet("thread").await?,
        QuietSnapshot {
            scope: "thread".to_string(),
            quiet: false,
            frontier: 2,
            ledger_hash: events[1].hash.clone(),
            state_hash: format!("{:x}", Sha256::digest(encoded.as_bytes())),
            outstanding: vec!["delivery".to_string()],
        }
    );
    Ok(())
}
