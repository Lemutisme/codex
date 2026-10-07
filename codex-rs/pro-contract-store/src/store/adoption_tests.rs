use super::command;
use super::coordinate;
use super::id;
use super::issue;
use super::open;
use codex_pro_contract::Command;
use codex_pro_contract::Contract;
use codex_pro_contract::DecisionProvenance;
use codex_pro_contract::Digest;
use codex_pro_contract::Role;
use codex_pro_contract::transition;
use pretty_assertions::assert_eq;
use serde_json::json;

use crate::AdoptionRequest;
use crate::ExperimentEvent;
use crate::ExperimentKind;
use crate::Identities;
use crate::Ledger;
use crate::LedgerError;
use crate::digest_of;

async fn supported_adoption(ledger: &Ledger) -> (Contract, AdoptionRequest) {
    let issued = ledger.apply(&issue(), "issue").await.unwrap();
    let proposed = ledger
        .apply(
            &command(
                issued.version,
                Role::Executor,
                Command::Propose {
                    subject_hash: Digest::of(b"candidate"),
                },
            ),
            "propose",
        )
        .await
        .unwrap();
    let coordinate = coordinate(&proposed);
    let supported = ledger
        .apply(
            &command(
                proposed.version,
                Role::Verifier,
                Command::Support {
                    certificate: Digest::of(b"certificate"),
                    coordinate: coordinate.clone(),
                },
            ),
            "support",
        )
        .await
        .unwrap();
    let request = AdoptionRequest {
        command: command(
            supported.version,
            Role::Settler,
            Command::Discharge {
                attestation: Digest::of(b"accept"),
                coordinate,
                decision: DecisionProvenance::Explicit,
            },
        ),
        expected_incumbent_seq: None,
        identities: Identities::default(),
    };
    (supported, request)
}

#[tokio::test]
async fn adoption_and_retries_bind_the_entire_request_and_preserve_both_chains() {
    let dir = tempfile::tempdir().unwrap();
    let ledger = open(dir.path()).await;
    let (_, request) = supported_adoption(&ledger).await;
    let adopted = ledger.adopt(&request, "adopt").await.unwrap();
    let experiments = ledger.experiments().await.unwrap();
    assert_eq!(
        experiments
            .iter()
            .map(|record| &record.event)
            .collect::<Vec<_>>(),
        vec![&ExperimentEvent {
            kind: ExperimentKind::Selection,
            identities: request.identities.clone(),
            body: json!({"role": "incumbent", "version": Digest::of(b"candidate").to_string(), "adoption": id()}),
        }]
    );
    let events = ledger.events().await.unwrap();
    let retried = crate::cli::adopt_command(
        dir.path(),
        "adopt",
        &serde_json::to_string(&request).unwrap(),
    )
    .await
    .unwrap();
    assert_eq!(retried, adopted);
    let mut changes = [request.clone(), request.clone(), request.clone()];
    changes[0].expected_incumbent_seq = Some(experiments[0].seq);
    changes[1].identities.model = Some("different".to_string());
    changes[2].command.provenance = codex_pro_contract::Provenance::Automation;
    for changed in changes {
        assert!(matches!(
            ledger.adopt(&changed, "adopt").await,
            Err(LedgerError::IdempotencyConflict)
        ));
    }
    assert_eq!(ledger.experiments().await.unwrap(), experiments);
    assert_eq!(ledger.events().await.unwrap(), events);
    ledger.verify_experiment_chain().await.unwrap();
    let mut state = None;
    let mut previous = Digest::from_bytes([0; 32]);
    for event in events {
        state = Some(transition(state.as_ref(), &event.command).unwrap());
        let state_hash = digest_of("contract_state", state.as_ref().unwrap());
        assert_eq!(
            (event.prev_hash, event.state_hash, event.hash),
            (
                previous,
                state_hash,
                digest_of("event", &(previous, &event.command, state_hash))
            )
        );
        previous = event.hash;
    }
    assert_eq!(state, Some(adopted));
}

#[tokio::test]
async fn a_stale_incumbent_fence_changes_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let ledger = open(dir.path()).await;
    let (supported, mut request) = supported_adoption(&ledger).await;
    let incumbent = ledger
        .append_experiment(&ExperimentEvent {
            kind: ExperimentKind::Selection,
            identities: Identities::default(),
            body: json!({"role": "incumbent", "version": "previous"}),
        })
        .await
        .unwrap();
    ledger
        .append_experiment(&ExperimentEvent {
            kind: ExperimentKind::Selection,
            identities: Identities::default(),
            body: json!({"role": "research_parent", "version": "other"}),
        })
        .await
        .unwrap();
    let events = ledger.events().await.unwrap();
    let experiments = ledger.experiments().await.unwrap();
    assert!(matches!(ledger.adopt(&request, "adopt").await,
        Err(LedgerError::IncumbentChanged { expected: None, actual: Some(seq) }) if seq == incumbent.seq));
    assert_eq!(ledger.contract(&id()).await.unwrap(), Some(supported));
    assert_eq!(ledger.events().await.unwrap(), events);
    assert_eq!(ledger.experiments().await.unwrap(), experiments);
    request.expected_incumbent_seq = Some(incumbent.seq);
    ledger.adopt(&request, "adopt").await.unwrap();
    ledger.verify_experiment_chain().await.unwrap();
}

#[tokio::test]
async fn selection_failure_rolls_back_discharge_and_idempotency() {
    let dir = tempfile::tempdir().unwrap();
    let ledger = open(dir.path()).await;
    let (supported, request) = supported_adoption(&ledger).await;
    let events = ledger.events().await.unwrap();
    let mut invalid = request.clone();
    invalid.command.command = Command::Release {
        attestation: Digest::of(b"release"),
    };
    assert!(matches!(
        ledger.adopt(&invalid, "adopt").await,
        Err(LedgerError::InvalidEvent(_))
    ));
    invalid = request.clone();
    invalid.command.role = Role::Executor;
    assert!(matches!(
        ledger.adopt(&invalid, "adopt").await,
        Err(LedgerError::Rejected(_))
    ));
    sqlx::query(
        "CREATE TRIGGER reject_selection BEFORE INSERT ON experiment_events
        BEGIN SELECT RAISE(ABORT, 'simulated failure'); END",
    )
    .execute(&ledger.pool)
    .await
    .unwrap();
    assert!(matches!(
        ledger.adopt(&request, "adopt").await,
        Err(LedgerError::Storage(_))
    ));
    assert_eq!(ledger.contract(&id()).await.unwrap(), Some(supported));
    assert_eq!(ledger.events().await.unwrap(), events);
    assert_eq!(ledger.experiments().await.unwrap(), vec![]);
    sqlx::query("DROP TRIGGER reject_selection")
        .execute(&ledger.pool)
        .await
        .unwrap();
    ledger.adopt(&request, "adopt").await.unwrap();
}
