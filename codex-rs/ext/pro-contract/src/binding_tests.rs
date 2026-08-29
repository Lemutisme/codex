use super::*;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::Command;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Draft;
use codex_pro_contract::Evidence;
use codex_pro_contract::Ledger;
use codex_pro_contract::Resolution;
use codex_pro_contract::Trigger;
use codex_pro_contract::hash_spec;
use pretty_assertions::assert_eq;
use sqlx::SqlitePool;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::str::FromStr;

#[tokio::test]
async fn shares_exact_turn_action_and_attempt_ceilings() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let options = SqliteConnectOptions::from_str(
        directory
            .path()
            .join("binding.sqlite")
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
    let ledger = activate_contract(&pool).await?;
    let store = BindingStore::initialize(pool.clone(), "owner-a").await?;
    let other = BindingStore::initialize(pool, "owner-b").await?;
    let limits = ExecutionLimits {
        turns: 2,
        actions: 1,
        deadline: 100_000,
        max_attempts: 2,
    };
    let initial = store
        .bind_once(
            "thread",
            "ledger",
            "contract",
            1,
            Some("policy".to_string()),
            limits,
        )
        .await?;
    assert_eq!(
        initial,
        ExecutionBinding {
            scope: "thread".to_string(),
            ledger_scope: "ledger".to_string(),
            contract_id: "contract".to_string(),
            revision: 1,
            execution_policy: Some("policy".to_string()),
            dispatched: false,
            resume_same_attempt: false,
            attempts: 0,
            turns_used: 0,
            actions_used: 0,
            next_action_at: 0,
            attempt_key: "1:".to_string(),
            turns_limit: 2,
            actions_limit: 1,
            deadline: 100_000,
            max_attempts: 2,
            lease_owner: None,
            lease_expires_at: 0,
        }
    );
    assert_eq!(
        store.reserve_turn("thread", 1).await?,
        Reservation::Denied {
            reason: ReservationDenial::AttemptInactive,
        }
    );
    assert!(matches!(
        store.begin_attempt("thread", 1).await?,
        Reservation::Reserved(_)
    ));
    assert_eq!(
        other.begin_attempt("thread", 2).await?,
        Reservation::Denied {
            reason: ReservationDenial::LeaseHeld,
        }
    );
    assert!(matches!(
        store.reserve_turn("thread", 2).await?,
        Reservation::Reserved(_)
    ));
    assert!(matches!(
        store.reserve_turn("thread", 3).await?,
        Reservation::Reserved(_)
    ));
    assert_eq!(
        store.reserve_turn("thread", 4).await?,
        Reservation::Denied {
            reason: ReservationDenial::ProviderTurnBudget,
        }
    );
    assert!(matches!(
        store.reserve_action("thread", 5).await?,
        Reservation::Reserved(_)
    ));
    assert_eq!(
        store.reserve_action("thread", 6).await?,
        Reservation::Denied {
            reason: ReservationDenial::ActionBudget,
        }
    );
    assert!(matches!(
        store.begin_attempt("thread", 7).await?,
        Reservation::Reserved(_)
    ));
    assert_eq!(
        store.begin_attempt("thread", 8).await?,
        Reservation::Denied {
            reason: ReservationDenial::AttemptBudget,
        }
    );
    assert!(store.heartbeat("thread", 20_000).await?);
    assert_eq!(
        other.claim_recovery("contract", "thread-b", 30_008).await?,
        None
    );
    store.record_interruption("contract").await?;
    let recovered = other
        .claim_recovery("contract", "thread-b", 30_009)
        .await?
        .expect("recorded transport interruption should be recoverable");
    assert!(recovered.interrupted);
    assert_eq!(recovered.binding.scope, "thread-b");
    assert_eq!(recovered.binding.ledger_scope, "ledger");
    assert_eq!(recovered.binding.attempts, 2);
    assert!(!recovered.binding.dispatched);
    assert_eq!(recovered.binding.lease_owner.as_deref(), Some("owner-b"));
    let reclaimed = other
        .claim_recovery("contract", "thread-c", 60_010)
        .await?
        .expect("the same owner should recover an expired interrupted claim");
    assert!(!reclaimed.interrupted);
    assert_eq!(reclaimed.binding.scope, "thread-c");
    ledger
        .apply(
            "ledger",
            Command::Escalate {
                actor: codex_pro_contract::INSTITUTION_ACTOR.to_string(),
                contract_id: "contract".to_string(),
                revision: 1,
                reason: "principal transition won the race".to_string(),
                time: 60_011,
            },
        )
        .await?;
    assert_eq!(
        other.reserve_action("thread-c", 60_012).await?,
        Reservation::Denied {
            reason: ReservationDenial::ContractInactive,
        }
    );
    assert_eq!(store.get("thread").await?, None);
    assert_eq!(
        store.for_session("thread").await?,
        Some(BoundSession {
            ledger_scope: "ledger".to_string(),
            contract_id: "contract".to_string(),
            current: false,
        })
    );
    assert_eq!(
        store.for_session("thread-b").await?,
        Some(BoundSession {
            ledger_scope: "ledger".to_string(),
            contract_id: "contract".to_string(),
            current: false,
        })
    );
    assert_eq!(
        store.for_session("thread-c").await?,
        Some(BoundSession {
            ledger_scope: "ledger".to_string(),
            contract_id: "contract".to_string(),
            current: true,
        })
    );
    assert_eq!(
        other.reserve_action("thread-c", 100_000).await?,
        Reservation::Denied {
            reason: ReservationDenial::Deadline,
        }
    );
    Ok(())
}

#[tokio::test]
async fn revision_preserves_spent_shared_limits() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let options = SqliteConnectOptions::from_str(
        directory
            .path()
            .join("binding.sqlite")
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
    let _ledger = activate_contract(&pool).await?;
    let store = BindingStore::initialize(pool, "owner").await?;
    let limits = ExecutionLimits {
        turns: 4,
        actions: 4,
        deadline: 100_000,
        max_attempts: 4,
    };
    store
        .bind_once("thread", "ledger", "contract", 1, None, limits)
        .await?;
    assert!(matches!(
        store.begin_attempt("thread", 1).await?,
        Reservation::Reserved(_)
    ));
    assert!(matches!(
        store.reserve_turn("thread", 2).await?,
        Reservation::Reserved(_)
    ));
    assert!(matches!(
        store.reserve_action("thread", 3).await?,
        Reservation::Reserved(_)
    ));

    store
        .suspend_attempt("thread", AttemptSchedule::At(10))
        .await?;
    assert_eq!(
        store.reserve_turn("thread", 5).await?,
        Reservation::Denied {
            reason: ReservationDenial::NotDue,
        }
    );
    assert!(matches!(
        store.begin_new_attempt("contract", "thread-2", 10).await?,
        Reservation::Reserved(binding)
            if binding.attempts == 2 && binding.scope == "thread-2"
    ));
    assert_eq!(
        store.for_session("thread").await?,
        Some(BoundSession {
            ledger_scope: "ledger".to_string(),
            contract_id: "contract".to_string(),
            current: false,
        })
    );
    store
        .suspend_attempt("thread-2", AttemptSchedule::AwaitRevision)
        .await?;
    let awaiting = store.get("thread-2").await?.expect("binding");
    assert!(awaiting.resume_same_attempt);
    assert_eq!(awaiting.attempts, 2);
    let resumed = store.resume_attempt("thread-2", 11).await?;
    assert!(!resumed.resume_same_attempt);
    assert_eq!(resumed.attempts, 2);

    let revised = store
        .revise_contract(
            "contract",
            2,
            ExecutionLimits {
                turns: 6,
                actions: 7,
                deadline: 200_000,
                max_attempts: 5,
            },
        )
        .await?;

    assert_eq!(revised.revision, 2);
    assert!(!revised.dispatched);
    assert_eq!(revised.attempts, 2);
    assert_eq!(revised.turns_used, 1);
    assert_eq!(revised.actions_used, 1);
    assert_eq!(revised.turns_limit, 6);
    assert_eq!(revised.actions_limit, 7);
    Ok(())
}

async fn activate_contract(pool: &SqlitePool) -> anyhow::Result<Ledger> {
    let ledger = Ledger::initialize(pool.clone()).await?;
    let spec = ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver".to_string(),
        brief: String::new(),
        artifacts: ArtifactSpec::new(Vec::new())?,
        requires: Vec::new(),
        authority: vec!["filesystem.read".to_string()],
        budget: Budget {
            turns: 10,
            actions: 10,
            deadline: 100_000,
        },
        evidence: Evidence {
            claim: "deliver".to_string(),
            replay: None,
        },
        resolution: Resolution {
            max_attempts: 10,
            retry_delay_ms: 0,
        },
    };
    ledger
        .apply(
            "ledger",
            Command::Issue {
                actor: "principal".to_string(),
                draft: Draft {
                    id: "contract".to_string(),
                    scope: "ledger".to_string(),
                    spec_hash: hash_spec(&spec)?,
                    spec,
                    issuer: "principal".to_string(),
                    executor: "worker".to_string(),
                },
            },
        )
        .await?;
    ledger
        .apply(
            "ledger",
            Command::Activate {
                actor: codex_pro_contract::INSTITUTION_ACTOR.to_string(),
                contract_id: "contract".to_string(),
                revision: 1,
                time: 0,
            },
        )
        .await?;
    Ok(ledger)
}
