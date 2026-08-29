use super::*;
use crate::ArtifactPath;
use pretty_assertions::assert_eq;

fn spec(requires: Vec<Requirement>) -> ContractSpec {
    ContractSpec {
        claim: "deliver exact executable".to_string(),
        artifacts: ArtifactSpec::new([ArtifactPath::new("executable").unwrap()]).unwrap(),
        requires,
    }
}

fn issue(state: &State, id: &str, requires: Vec<Requirement>) -> State {
    let spec = spec(requires);
    transition(
        state,
        Command::Issue {
            actor: "principal".to_string(),
            draft: Draft {
                id: id.to_string(),
                scope: "workspace".to_string(),
                spec_hash: hash_spec(&spec).unwrap(),
                spec,
                issuer: "principal".to_string(),
                executor: "worker".to_string(),
            },
        },
    )
    .state
}

fn coordinate(spec_hash: &str, hash: &str) -> SubjectCoordinate {
    SubjectCoordinate {
        hash: hash.to_string(),
        spec_hash: spec_hash.to_string(),
        artifacts: vec![ArtifactPath::new("executable").unwrap()],
    }
}

fn activate_and_handoff(state: &State, id: &str, subject_hash: &str) -> State {
    let state = transition(
        state,
        Command::Activate {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: id.to_string(),
            revision: 1,
        },
    )
    .state;
    let spec_hash = state.contracts[id].spec_hash.clone();
    transition(
        &state,
        Command::ReportReady {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: id.to_string(),
            revision: 1,
            summary: "ready".to_string(),
            uncertainties: Vec::new(),
            subject: coordinate(&spec_hash, subject_hash),
        },
    )
    .state
}

fn discharge(state: &State, id: &str, subject_hash: &str) -> State {
    let contract = &state.contracts[id];
    transition(
        state,
        Command::Discharge {
            actor: "principal".to_string(),
            contract_id: id.to_string(),
            attestation: Attestation {
                id: format!("attestation-{id}"),
                revision: contract.revision,
                spec_hash: contract.spec_hash.clone(),
                subject_hash: subject_hash.to_string(),
                evidence_hash: format!("evidence-{id}"),
                verifier_id: "principal".to_string(),
            },
        },
    )
    .state
}

#[test]
fn executor_cannot_settle_and_attestation_is_subject_bound() {
    let state = issue(&State::default(), "delivery", Vec::new());
    let state = activate_and_handoff(&state, "delivery", "subject-a");
    let contract = &state.contracts["delivery"];
    let wrong_subject = transition(
        &state,
        Command::Discharge {
            actor: "principal".to_string(),
            contract_id: "delivery".to_string(),
            attestation: Attestation {
                id: "attestation".to_string(),
                revision: 1,
                spec_hash: contract.spec_hash.clone(),
                subject_hash: "subject-b".to_string(),
                evidence_hash: "evidence".to_string(),
                verifier_id: "principal".to_string(),
            },
        },
    );
    let self_settlement = transition(
        &state,
        Command::Discharge {
            actor: "worker".to_string(),
            contract_id: "delivery".to_string(),
            attestation: Attestation {
                id: "attestation".to_string(),
                revision: 1,
                spec_hash: contract.spec_hash.clone(),
                subject_hash: "subject-a".to_string(),
                evidence_hash: "evidence".to_string(),
                verifier_id: "worker".to_string(),
            },
        },
    );

    assert_eq!(wrong_subject.state, state);
    assert_eq!(self_settlement.state, state);
    assert!(!quiet(&state, "workspace"));
}

#[test]
fn challenge_restores_transitive_responsibility() {
    let state = issue(&State::default(), "foundation", Vec::new());
    let state = activate_and_handoff(&state, "foundation", "subject-foundation");
    let state = discharge(&state, "foundation", "subject-foundation");
    let state = issue(
        &state,
        "delivery",
        vec![Requirement {
            contract_id: "foundation".to_string(),
            revision: 1,
        }],
    );
    let state = activate_and_handoff(&state, "delivery", "subject-delivery");
    let state = discharge(&state, "delivery", "subject-delivery");
    assert!(quiet(&state, "workspace"));

    let challenged = transition(
        &state,
        Command::Challenge {
            actor: "principal".to_string(),
            contract_id: "foundation".to_string(),
            revision: 1,
            subject_hash: "subject-foundation".to_string(),
            reason: "counterexample".to_string(),
        },
    );

    assert_eq!(challenged.decision, Decision::Accepted);
    assert_eq!(
        challenged.state.contracts["foundation"].status,
        Status::Dormant
    );
    assert_eq!(
        challenged.state.contracts["delivery"].status,
        Status::Escalated
    );
    assert!(!quiet(&challenged.state, "workspace"));
}
