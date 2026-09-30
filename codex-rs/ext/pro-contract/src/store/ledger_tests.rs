use codex_pro_contract::AuthenticatedCommand;
use codex_pro_contract::Bindings;
use codex_pro_contract::Command;
use codex_pro_contract::Contract;
use codex_pro_contract::ContractId;
use codex_pro_contract::Coordinate;
use codex_pro_contract::DecisionProvenance;
use codex_pro_contract::Digest;
use codex_pro_contract::OwnerId;
use codex_pro_contract::Provenance;
use codex_pro_contract::Rejection;
use codex_pro_contract::Role;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use super::Ledger;
use super::LedgerError;

async fn open(dir: &std::path::Path) -> Ledger {
    let sqlite = SqliteConfig::new_for_testing(
        AbsolutePathBuf::from_absolute_path(dir).expect("absolute tempdir"),
    );
    Ledger::open(&sqlite, dir).await.expect("open ledger")
}

fn id() -> ContractId {
    ContractId("c-1".to_string())
}

fn command(expected_version: u64, role: Role, command: Command) -> AuthenticatedCommand {
    AuthenticatedCommand {
        contract_id: id(),
        expected_version,
        role,
        provenance: Provenance::Human,
        command,
    }
}

fn issue() -> AuthenticatedCommand {
    command(
        0,
        Role::Issuer,
        Command::Issue {
            owner: OwnerId("owner".to_string()),
            bindings: Bindings {
                terms_hash: Digest::of(b"terms"),
                capture_policy_hash: Digest::of(b"capture"),
                evidence_policy_hash: Digest::of(b"evidence"),
            },
        },
    )
}

fn coordinate(contract: &Contract) -> Coordinate {
    let candidate = contract.candidate.expect("candidate");
    Coordinate {
        contract_id: contract.id.clone(),
        revision: contract.revision,
        terms_hash: contract.bindings.terms_hash,
        generation: candidate.generation,
        subject_hash: candidate.subject_hash,
        capture_policy_hash: contract.bindings.capture_policy_hash,
        evidence_policy_hash: contract.bindings.evidence_policy_hash,
        environment_digest: Digest::of(b"env"),
        evaluator_digest: Digest::of(b"evaluator"),
        evidence_hash: Digest::of(b"evidence"),
    }
}

#[tokio::test]
async fn an_accepted_sequence_persists_and_reloads_identically() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let issued = ledger.apply(&issue(), "k-issue").await.expect("issue");
    let proposed = ledger
        .apply(
            &command(
                issued.version,
                Role::Executor,
                Command::Propose {
                    subject_hash: Digest::of(b"subject"),
                },
            ),
            "k-propose",
        )
        .await
        .expect("propose");
    let supported = ledger
        .apply(
            &command(
                proposed.version,
                Role::Verifier,
                Command::Support {
                    certificate: Digest::of(b"certificate"),
                    coordinate: coordinate(&proposed),
                },
            ),
            "k-support",
        )
        .await
        .expect("support");
    let discharged = ledger
        .apply(
            &command(
                supported.version,
                Role::Settler,
                Command::Discharge {
                    attestation: Digest::of(b"accept"),
                    coordinate: coordinate(&proposed),
                    decision: DecisionProvenance::Explicit,
                },
            ),
            "k-discharge",
        )
        .await
        .expect("discharge");
    drop(ledger);
    let reopened = open(dir.path()).await;
    assert_eq!(
        reopened.contract(&id()).await.expect("read"),
        Some(discharged)
    );
    assert_eq!(reopened.events().await.expect("events").len(), 4);
}

#[tokio::test]
async fn a_rejected_command_changes_nothing() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let issued = ledger.apply(&issue(), "k-issue").await.expect("issue");
    let result = ledger
        .apply(
            &command(
                issued.version,
                Role::Executor,
                Command::Release {
                    attestation: Digest::of(b"self release"),
                },
            ),
            "k-bad",
        )
        .await;
    assert!(matches!(
        result,
        Err(LedgerError::Rejected(Rejection::WrongRole { .. }))
    ));
    assert_eq!(ledger.contract(&id()).await.expect("read"), Some(issued));
    assert_eq!(ledger.events().await.expect("events").len(), 1);
}

#[tokio::test]
async fn an_identical_retry_returns_the_committed_result_without_a_new_event() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let first = ledger.apply(&issue(), "k-issue").await.expect("issue");
    let retry = ledger.apply(&issue(), "k-issue").await.expect("retry");
    assert_eq!(retry, first);
    assert_eq!(ledger.events().await.expect("events").len(), 1);
}

#[tokio::test]
async fn a_conflicting_retry_under_the_same_key_is_rejected() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let issued = ledger.apply(&issue(), "k-1").await.expect("issue");
    let other = command(
        issued.version,
        Role::Executor,
        Command::Propose {
            subject_hash: Digest::of(b"s"),
        },
    );
    assert!(matches!(
        ledger.apply(&other, "k-1").await,
        Err(LedgerError::IdempotencyConflict)
    ));
}

#[tokio::test]
async fn events_form_a_hash_chain() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let issued = ledger.apply(&issue(), "k-issue").await.expect("issue");
    ledger
        .apply(
            &command(
                issued.version,
                Role::Executor,
                Command::Propose {
                    subject_hash: Digest::of(b"s"),
                },
            ),
            "k-propose",
        )
        .await
        .expect("propose");
    let events = ledger.events().await.expect("events");
    assert_eq!(events[0].prev_hash, Digest::from_bytes([0; 32]));
    assert_eq!(events[1].prev_hash, events[0].hash);
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct Status {
    phase: String,
}

#[tokio::test]
async fn records_upsert_and_read_back() {
    let dir = tempfile::tempdir().expect("tempdir");
    let ledger = open(dir.path()).await;
    let first = Status {
        phase: "checking".to_string(),
    };
    let second = Status {
        phase: "supported".to_string(),
    };
    ledger
        .put_record("status", "thread-1", &first)
        .await
        .expect("put");
    ledger
        .put_record("status", "thread-1", &second)
        .await
        .expect("put again");
    assert_eq!(
        ledger
            .record::<Status>("status", "thread-1")
            .await
            .expect("read"),
        Some(second)
    );
    assert_eq!(
        ledger
            .record::<Status>("status", "missing")
            .await
            .expect("read"),
        None
    );
}
