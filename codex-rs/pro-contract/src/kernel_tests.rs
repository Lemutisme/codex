use super::*;
use crate::ArtifactPath;
use crate::ArtifactSpec;
use crate::Budget;
use crate::Evidence;
use crate::ReplayCheck;
use crate::ReplayPolicy;
use crate::Requirement;
use crate::Resolution;
use crate::Trigger;
use pretty_assertions::assert_eq;

fn spec(requires: Vec<Requirement>) -> ContractSpec {
    let artifacts = ArtifactSpec::new([ArtifactPath::new("executable").unwrap()]).unwrap();
    ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver exact executable".to_string(),
        brief: String::new(),
        artifacts,
        requires,
        authority: vec!["filesystem.read".to_string()],
        budget: Budget {
            turns: 100,
            actions: 1_000,
            deadline: 10_000,
        },
        evidence: Evidence {
            claim: "the exact executable is accepted".to_string(),
            replay: None,
        },
        resolution: Resolution {
            max_attempts: 3,
            retry_delay_ms: 0,
        },
    }
}

fn issue(state: &State, id: &str, requires: Vec<Requirement>) -> State {
    let spec = spec(requires);
    issue_with_spec(state, id, spec)
}

fn issue_with_spec(state: &State, id: &str, spec: ContractSpec) -> State {
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
            time: 1,
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
            replay: None,
            time: 2,
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
            challenge: Challenge {
                revision: 1,
                subject_hash: "subject-foundation".to_string(),
                evidence_hash: "counterexample-evidence".to_string(),
                disclosure: ChallengeDisclosure::Executor,
                summary: Some("counterexample".to_string()),
                time: 3,
                attestation_id: None,
            },
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

#[test]
fn failed_replay_reopens_responsibility_with_exact_evidence() {
    let mut replay_spec = spec(Vec::new());
    replay_spec.evidence.replay = Some(ReplayPolicy {
        checks: vec![ReplayCheck {
            argv: vec!["./compile.sh".to_string()],
            cwd: None,
            timeout_ms: 1_000,
            exit: 0,
        }],
        protected: Vec::new(),
        artifacts: replay_spec.artifacts.clone(),
    });
    let state = issue_with_spec(&State::default(), "delivery", replay_spec);
    let state = transition(
        &state,
        Command::Activate {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            time: 1,
        },
    )
    .state;
    let contract = &state.contracts["delivery"];
    let policy_hash = hash_replay(contract.spec.evidence.replay.as_ref().unwrap()).unwrap();
    let failed = transition(
        &state,
        Command::ReportReady {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            summary: "ready".to_string(),
            uncertainties: Vec::new(),
            subject: coordinate(&contract.spec_hash, "subject"),
            replay: Some(ReplayResult {
                policy_hash,
                subject_hash: "subject".to_string(),
                evidence_hash: "replay-evidence".to_string(),
                passed: false,
                summary: "compile failed".to_string(),
            }),
            time: 2,
        },
    );

    assert_eq!(failed.decision, Decision::Accepted);
    assert_eq!(failed.state.contracts["delivery"].status, Status::Dormant);
    assert_eq!(
        failed.state.contracts["delivery"].challenge,
        Some(Challenge {
            revision: 1,
            subject_hash: "subject".to_string(),
            evidence_hash: "replay-evidence".to_string(),
            disclosure: ChallengeDisclosure::Executor,
            summary: Some("compile failed".to_string()),
            time: 2,
            attestation_id: None,
        })
    );
}

#[test]
fn replay_evidence_cannot_double_as_principal_attestation() {
    let mut replay_spec = spec(Vec::new());
    replay_spec.evidence.replay = Some(ReplayPolicy {
        checks: vec![ReplayCheck {
            argv: vec!["./validate.sh".to_string()],
            cwd: None,
            timeout_ms: 1_000,
            exit: 0,
        }],
        protected: Vec::new(),
        artifacts: replay_spec.artifacts.clone(),
    });
    let state = issue_with_spec(&State::default(), "delivery", replay_spec);
    let state = transition(
        &state,
        Command::Activate {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            time: 1,
        },
    )
    .state;
    let contract = &state.contracts["delivery"];
    let state = transition(
        &state,
        Command::ReportReady {
            actor: INSTITUTION_ACTOR.to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            summary: "ready".to_string(),
            uncertainties: Vec::new(),
            subject: coordinate(&contract.spec_hash, "subject"),
            replay: Some(ReplayResult {
                policy_hash: hash_replay(contract.spec.evidence.replay.as_ref().unwrap()).unwrap(),
                subject_hash: "subject".to_string(),
                evidence_hash: "same-evidence".to_string(),
                passed: true,
                summary: "replay verification passed".to_string(),
            }),
            time: 2,
        },
    )
    .state;
    let contract = &state.contracts["delivery"];
    let rejected = transition(
        &state,
        Command::Discharge {
            actor: "principal".to_string(),
            contract_id: "delivery".to_string(),
            attestation: Attestation {
                id: "attestation".to_string(),
                revision: 1,
                spec_hash: contract.spec_hash.clone(),
                subject_hash: "subject".to_string(),
                evidence_hash: "same-evidence".to_string(),
                verifier_id: "principal".to_string(),
            },
        },
    );

    assert!(matches!(rejected.decision, Decision::Rejected { .. }));
    assert_eq!(rejected.state, state);
}

#[test]
fn revision_decision_is_bound_to_the_pending_coordinate() {
    let state = issue(&State::default(), "delivery", Vec::new());
    let original = state.contracts["delivery"].spec.clone();
    let mut proposed = original.clone();
    proposed.goal = "revised goal".to_string();
    let proposed_hash = hash_spec(&proposed).unwrap();
    let pending = transition(
        &state,
        Command::PetitionRevision {
            actor: "worker".to_string(),
            contract_id: "delivery".to_string(),
            spec: proposed,
            spec_hash: proposed_hash.clone(),
            reason: "new information".to_string(),
        },
    )
    .state;
    let stale = transition(
        &pending,
        Command::DecideRevision {
            actor: "principal".to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            spec_hash: "stale-spec".to_string(),
            disposition: RevisionDisposition::Accept,
        },
    );
    assert!(matches!(stale.decision, Decision::Rejected { .. }));
    assert_eq!(stale.state, pending);

    let rejected = transition(
        &pending,
        Command::DecideRevision {
            actor: "principal".to_string(),
            contract_id: "delivery".to_string(),
            revision: 1,
            spec_hash: proposed_hash,
            disposition: RevisionDisposition::Reject,
        },
    );
    assert_eq!(rejected.decision, Decision::Accepted);
    assert_eq!(rejected.state.contracts["delivery"].spec, original);
    assert!(
        rejected.state.contracts["delivery"]
            .pending_revision
            .is_none()
    );
}
