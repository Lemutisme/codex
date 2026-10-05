use pretty_assertions::assert_eq;

use crate::AuthenticatedCommand;
use crate::Axiom;
use crate::Bindings;
use crate::Candidate;
use crate::Command;
use crate::CommandKind;
use crate::Contract;
use crate::ContractId;
use crate::Coordinate;
use crate::CoordinateField;
use crate::DecisionProvenance;
use crate::Digest;
use crate::OwnerId;
use crate::Provenance;
use crate::Reach;
use crate::Rejection;
use crate::Role;
use crate::Settlement;
use crate::Standing;
use crate::Support;
use crate::Target;
use crate::transition;

fn digest(label: &str) -> Digest {
    Digest::of(label.as_bytes())
}

fn id() -> ContractId {
    ContractId("c-1".to_string())
}

fn bindings(label: &str) -> Bindings {
    Bindings {
        terms_hash: digest(&format!("{label}-terms")),
        capture_policy_hash: digest(&format!("{label}-capture")),
        evidence_policy_hash: digest(&format!("{label}-evidence")),
    }
}

fn cmd(contract: Option<&Contract>, role: Role, command: Command) -> AuthenticatedCommand {
    AuthenticatedCommand {
        contract_id: id(),
        expected_version: contract.map_or(0, |contract| contract.version),
        role,
        provenance: Provenance::Human,
        command,
    }
}

fn apply(contract: Option<&Contract>, role: Role, command: Command) -> Result<Contract, Rejection> {
    transition(contract, &cmd(contract, role, command))
}

fn issued() -> Contract {
    apply(
        None,
        Role::Issuer,
        Command::Issue {
            owner: OwnerId("owner".to_string()),
            bindings: bindings("v1"),
        },
    )
    .expect("issue")
}

fn proposed(contract: &Contract, subject: &str) -> Contract {
    apply(
        Some(contract),
        Role::Executor,
        Command::Propose {
            subject_hash: digest(subject),
        },
    )
    .expect("propose")
}

/// The coordinate a verifier would bind for the contract's current candidate.
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
        environment_digest: digest("env"),
        evaluator_digest: digest("evaluator"),
        evidence_hash: digest("evidence"),
        basis: digest("basis"),
        reach: Reach::Within,
    }
}

fn supported(contract: &Contract) -> Contract {
    apply(
        Some(contract),
        Role::Verifier,
        Command::Support {
            certificate: digest("certificate"),
            coordinate: coordinate(contract),
        },
    )
    .expect("support")
}

fn discharged(contract: &Contract) -> Contract {
    let coordinate = contract.support.clone().expect("support").coordinate;
    apply(
        Some(contract),
        Role::Settler,
        Command::Discharge {
            attestation: digest("accept"),
            coordinate,
            decision: DecisionProvenance::Explicit,
        },
    )
    .expect("discharge")
}

fn settlement_coordinate(contract: &Contract) -> Coordinate {
    contract.settlement.clone().expect("settlement").coordinate
}

#[test]
fn issue_creates_an_outstanding_contract() {
    assert_eq!(
        issued(),
        Contract {
            id: id(),
            owner: OwnerId("owner".to_string()),
            revision: 1,
            bindings: bindings("v1"),
            standing: Standing::Outstanding,
            generation: 0,
            candidate: None,
            support: None,
            settlement: None,
            version: 1,
        }
    );
}

#[test]
fn issuing_an_existing_contract_is_rejected() {
    let contract = issued();
    let result = transition(
        Some(&contract),
        &AuthenticatedCommand {
            expected_version: 0,
            ..cmd(
                Some(&contract),
                Role::Issuer,
                Command::Issue {
                    owner: OwnerId("owner".to_string()),
                    bindings: bindings("v1"),
                },
            )
        },
    );
    assert_eq!(result, Err(Rejection::ContractExists));
}

#[test]
fn commands_on_unknown_contracts_are_rejected() {
    let result = apply(
        None,
        Role::Executor,
        Command::Propose {
            subject_hash: digest("s"),
        },
    );
    assert_eq!(result, Err(Rejection::UnknownContract));
}

#[test]
fn a_stale_version_is_rejected() {
    let contract = issued();
    let mut command = cmd(
        Some(&contract),
        Role::Executor,
        Command::Propose {
            subject_hash: digest("s"),
        },
    );
    command.expected_version = contract.version + 1;
    assert_eq!(
        transition(Some(&contract), &command),
        Err(Rejection::StaleVersion {
            expected: contract.version + 1,
            current: contract.version,
        })
    );
}

#[test]
fn a_command_for_another_contract_is_rejected() {
    let contract = issued();
    let mut command = cmd(
        Some(&contract),
        Role::Executor,
        Command::Propose {
            subject_hash: digest("s"),
        },
    );
    command.contract_id = ContractId("other".to_string());
    assert_eq!(
        transition(Some(&contract), &command),
        Err(Rejection::ContractMismatch)
    );
}

/// Counterexample for A1: the executor certifying its own completion.
#[test]
fn the_executor_cannot_discharge_its_own_work() {
    let contract = supported(&proposed(&issued(), "s"));
    let coordinate = contract.support.clone().expect("support").coordinate;
    let result = apply(
        Some(&contract),
        Role::Executor,
        Command::Discharge {
            attestation: digest("self"),
            coordinate,
            decision: DecisionProvenance::Explicit,
        },
    );
    assert_eq!(
        result,
        Err(Rejection::WrongRole {
            command: CommandKind::Discharge,
            required: Role::Settler,
            actual: Role::Executor,
        })
    );
}

#[test]
fn the_executor_cannot_support_its_own_candidate() {
    let contract = proposed(&issued(), "s");
    let result = apply(
        Some(&contract),
        Role::Executor,
        Command::Support {
            certificate: digest("self"),
            coordinate: coordinate(&contract),
        },
    );
    assert_eq!(
        result,
        Err(Rejection::WrongRole {
            command: CommandKind::Support,
            required: Role::Verifier,
            actual: Role::Executor,
        })
    );
}

#[test]
fn every_command_kind_is_bound_to_exactly_one_role() {
    let bound = [
        (CommandKind::Issue, Role::Issuer),
        (CommandKind::Revise, Role::Issuer),
        (CommandKind::Propose, Role::Executor),
        (CommandKind::Support, Role::Verifier),
        (CommandKind::Defeat, Role::Verifier),
        (CommandKind::Withdraw, Role::Verifier),
        (CommandKind::Challenge, Role::Settler),
        (CommandKind::Discharge, Role::Settler),
        (CommandKind::Release, Role::Settler),
    ];
    let actual: Vec<_> = bound
        .iter()
        .map(|(kind, _)| (*kind, kind.required_role()))
        .collect();
    assert_eq!(actual, bound.to_vec());
}

#[test]
fn propose_sets_the_candidate_at_a_new_generation() {
    let contract = proposed(&issued(), "s");
    assert_eq!(
        (contract.generation, contract.candidate, contract.version),
        (
            1,
            Some(Candidate {
                generation: 1,
                subject_hash: digest("s"),
            }),
            2
        )
    );
}

/// Counterexample for Propose: settling a subject that was never handed off.
#[test]
fn support_requires_a_candidate() {
    let contract = issued();
    let result = apply(
        Some(&contract),
        Role::Verifier,
        Command::Support {
            certificate: digest("certificate"),
            coordinate: Coordinate {
                contract_id: id(),
                revision: 1,
                terms_hash: contract.bindings.terms_hash,
                generation: 0,
                subject_hash: digest("never proposed"),
                capture_policy_hash: contract.bindings.capture_policy_hash,
                evidence_policy_hash: contract.bindings.evidence_policy_hash,
                environment_digest: digest("env"),
                evaluator_digest: digest("evaluator"),
                evidence_hash: digest("evidence"),
                basis: digest("basis"),
                reach: Reach::Within,
            },
        },
    );
    assert_eq!(result, Err(Rejection::NoCandidate));
}

#[test]
fn support_rejects_each_mismatched_coordinate_field() {
    let contract = proposed(&issued(), "s");
    let good = coordinate(&contract);
    let cases: Vec<(CoordinateField, Coordinate)> = vec![
        (
            CoordinateField::ContractId,
            Coordinate {
                contract_id: ContractId("other".to_string()),
                ..good.clone()
            },
        ),
        (
            CoordinateField::Revision,
            Coordinate {
                revision: 2,
                ..good.clone()
            },
        ),
        (
            CoordinateField::TermsHash,
            Coordinate {
                terms_hash: digest("other"),
                ..good.clone()
            },
        ),
        (
            CoordinateField::CapturePolicyHash,
            Coordinate {
                capture_policy_hash: digest("other"),
                ..good.clone()
            },
        ),
        (
            CoordinateField::EvidencePolicyHash,
            Coordinate {
                evidence_policy_hash: digest("other"),
                ..good.clone()
            },
        ),
        (
            CoordinateField::Generation,
            Coordinate {
                generation: 7,
                ..good.clone()
            },
        ),
        (
            CoordinateField::SubjectHash,
            Coordinate {
                subject_hash: digest("substituted"),
                ..good
            },
        ),
    ];
    for (field, coordinate) in cases {
        let result = apply(
            Some(&contract),
            Role::Verifier,
            Command::Support {
                certificate: digest("certificate"),
                coordinate,
            },
        );
        assert_eq!(result, Err(Rejection::CoordinateMismatch { field }));
    }
}

#[test]
fn support_is_immutable_once_set() {
    let contract = supported(&proposed(&issued(), "s"));
    let result = apply(
        Some(&contract),
        Role::Verifier,
        Command::Support {
            certificate: digest("another"),
            coordinate: coordinate(&contract),
        },
    );
    assert_eq!(result, Err(Rejection::SupportPresent));
}

/// Counterexample for Defeat's fence: a late support crossing a defeat.
#[test]
fn stale_support_cannot_cross_a_defeat() {
    let contract = proposed(&issued(), "s");
    let stale = coordinate(&contract);
    let defeated = apply(
        Some(&contract),
        Role::Verifier,
        Command::Defeat {
            target: Target::Candidate {
                generation: stale.generation,
                subject_hash: stale.subject_hash,
            },
            defeater: digest("failing check"),
        },
    )
    .expect("defeat");
    let reproposed = proposed(&defeated, "s");
    let result = apply(
        Some(&reproposed),
        Role::Verifier,
        Command::Support {
            certificate: digest("late"),
            coordinate: stale,
        },
    );
    assert_eq!(
        result,
        Err(Rejection::CoordinateMismatch {
            field: CoordinateField::Generation,
        })
    );
}

#[test]
fn defeat_requires_the_exact_current_candidate() {
    let contract = proposed(&issued(), "s");
    let result = apply(
        Some(&contract),
        Role::Verifier,
        Command::Defeat {
            target: Target::Candidate {
                generation: contract.generation,
                subject_hash: digest("other"),
            },
            defeater: digest("d"),
        },
    );
    assert_eq!(result, Err(Rejection::TargetMismatch));
}

#[test]
fn defeat_clears_the_candidate_and_advances_the_generation() {
    let contract = supported(&proposed(&issued(), "s"));
    let candidate = contract.candidate.expect("candidate");
    let defeated = apply(
        Some(&contract),
        Role::Verifier,
        Command::Defeat {
            target: Target::Candidate {
                generation: candidate.generation,
                subject_hash: candidate.subject_hash,
            },
            defeater: digest("d"),
        },
    )
    .expect("defeat");
    assert_eq!(
        (
            defeated.standing,
            defeated.generation,
            defeated.candidate,
            defeated.support
        ),
        (Standing::Outstanding, contract.generation + 1, None, None)
    );
}

/// Counterexample for A3: settling without current support.
#[test]
fn discharge_requires_current_support() {
    let contract = proposed(&issued(), "s");
    let result = apply(
        Some(&contract),
        Role::Settler,
        Command::Discharge {
            attestation: digest("accept"),
            coordinate: coordinate(&contract),
            decision: DecisionProvenance::Explicit,
        },
    );
    assert_eq!(result, Err(Rejection::NoSupport));
}

/// Counterexample for A2: accepting a support that was never the one presented.
#[test]
fn discharge_rejects_a_receipt_for_different_support() {
    let contract = supported(&proposed(&issued(), "s"));
    let presented = Coordinate {
        evidence_hash: digest("something else"),
        basis: digest("basis"),
        reach: Reach::Within,
        ..contract.support.clone().expect("support").coordinate
    };
    let result = apply(
        Some(&contract),
        Role::Settler,
        Command::Discharge {
            attestation: digest("accept"),
            coordinate: presented,
            decision: DecisionProvenance::Explicit,
        },
    );
    assert_eq!(
        result,
        Err(Rejection::CoordinateMismatch {
            field: CoordinateField::Support,
        })
    );
}

#[test]
fn discharge_records_the_settlement_and_its_provenance() {
    let contract = supported(&proposed(&issued(), "s"));
    let settled = discharged(&contract);
    assert_eq!(
        (settled.standing, settled.settlement),
        (
            Standing::Discharged,
            Some(Settlement {
                attestation: digest("accept"),
                coordinate: contract.support.expect("support").coordinate,
                decision: DecisionProvenance::Explicit,
            })
        )
    );
}

/// Counterexample for A4: a wrong settlement that cannot restore responsibility.
#[test]
fn a_challenge_reopens_a_discharged_contract() {
    let settled = discharged(&supported(&proposed(&issued(), "s")));
    let reopened = apply(
        Some(&settled),
        Role::Settler,
        Command::Challenge {
            target: Target::Settlement {
                coordinate: settlement_coordinate(&settled),
            },
            defeater: digest("still broken"),
        },
    )
    .expect("challenge");
    assert_eq!(
        (
            reopened.standing,
            reopened.candidate,
            reopened.support,
            reopened.settlement,
            reopened.generation
        ),
        (
            Standing::Outstanding,
            None,
            None,
            None,
            settled.generation + 1
        )
    );
}

/// Counterexample for Defeat on a discharge: a defeated discharge left standing.
#[test]
fn a_verifier_defeat_reopens_a_discharged_contract() {
    let settled = discharged(&supported(&proposed(&issued(), "s")));
    let reopened = apply(
        Some(&settled),
        Role::Verifier,
        Command::Defeat {
            target: Target::Settlement {
                coordinate: settlement_coordinate(&settled),
            },
            defeater: digest("regression"),
        },
    )
    .expect("defeat");
    assert_eq!(reopened.standing, Standing::Outstanding);
}

#[test]
fn a_challenge_must_name_the_exact_settlement() {
    let settled = discharged(&supported(&proposed(&issued(), "s")));
    let result = apply(
        Some(&settled),
        Role::Settler,
        Command::Challenge {
            target: Target::Settlement {
                coordinate: Coordinate {
                    evidence_hash: digest("other"),
                    basis: digest("basis"),
                    reach: Reach::Within,
                    ..settlement_coordinate(&settled)
                },
            },
            defeater: digest("d"),
        },
    );
    assert_eq!(result, Err(Rejection::TargetMismatch));
}

/// Counterexample for Withdraw: an untrusted judgment removable only by destroying the artifact.
#[test]
fn withdraw_keeps_the_subject_and_advances_the_generation() {
    let contract = supported(&proposed(&issued(), "s"));
    let withdrawn = apply(
        Some(&contract),
        Role::Verifier,
        Command::Withdraw {
            target: Target::Support {
                coordinate: coordinate(&contract),
            },
            cause: digest("custody break"),
        },
    )
    .expect("withdraw");
    assert_eq!(
        (
            withdrawn.standing,
            withdrawn.support,
            withdrawn.generation,
            withdrawn.candidate
        ),
        (
            Standing::Outstanding,
            None,
            contract.generation + 1,
            Some(Candidate {
                generation: contract.generation + 1,
                subject_hash: digest("s"),
            })
        )
    );
}

/// Counterexample for Withdraw's fence: a pre-withdrawal certificate re-attaching.
#[test]
fn a_withdrawn_certificate_cannot_reattach() {
    let contract = supported(&proposed(&issued(), "s"));
    let old = coordinate(&contract);
    let withdrawn = apply(
        Some(&contract),
        Role::Verifier,
        Command::Withdraw {
            target: Target::Support {
                coordinate: old.clone(),
            },
            cause: digest("custody break"),
        },
    )
    .expect("withdraw");
    let result = apply(
        Some(&withdrawn),
        Role::Verifier,
        Command::Support {
            certificate: digest("certificate"),
            coordinate: old,
        },
    );
    assert_eq!(
        result,
        Err(Rejection::CoordinateMismatch {
            field: CoordinateField::Generation,
        })
    );
}

#[test]
fn withdrawing_a_settlement_requires_a_new_acceptance() {
    let settled = discharged(&supported(&proposed(&issued(), "s")));
    let old_settlement = settlement_coordinate(&settled);
    let withdrawn = apply(
        Some(&settled),
        Role::Verifier,
        Command::Withdraw {
            target: Target::Settlement {
                coordinate: old_settlement.clone(),
            },
            cause: digest("custody break"),
        },
    )
    .expect("withdraw");
    assert_eq!(
        (withdrawn.standing, withdrawn.settlement.clone()),
        (Standing::Outstanding, None)
    );
    let reverified = supported(&withdrawn);
    let result = apply(
        Some(&reverified),
        Role::Settler,
        Command::Discharge {
            attestation: digest("old accept"),
            coordinate: old_settlement,
            decision: DecisionProvenance::Explicit,
        },
    );
    assert_eq!(
        result,
        Err(Rejection::CoordinateMismatch {
            field: CoordinateField::Support,
        })
    );
}

#[test]
fn withdraw_must_name_the_exact_current_support() {
    let contract = supported(&proposed(&issued(), "s"));
    let result = apply(
        Some(&contract),
        Role::Verifier,
        Command::Withdraw {
            target: Target::Support {
                coordinate: Coordinate {
                    evidence_hash: digest("other"),
                    basis: digest("basis"),
                    reach: Reach::Within,
                    ..coordinate(&contract)
                },
            },
            cause: digest("c"),
        },
    );
    assert_eq!(result, Err(Rejection::TargetMismatch));
}

/// Counterexample for A3: duty silently erased — release is terminal and explicit.
#[test]
fn release_is_terminal() {
    let released = apply(
        Some(&issued()),
        Role::Settler,
        Command::Release {
            attestation: digest("abandon"),
        },
    )
    .expect("release");
    assert_eq!(released.standing, Standing::Released);
    let result = apply(
        Some(&released),
        Role::Executor,
        Command::Propose {
            subject_hash: digest("s"),
        },
    );
    assert_eq!(result, Err(Rejection::Released));
}

#[test]
fn a_discharged_contract_accepts_no_new_proposal() {
    let settled = discharged(&supported(&proposed(&issued(), "s")));
    let result = apply(
        Some(&settled),
        Role::Executor,
        Command::Propose {
            subject_hash: digest("improved"),
        },
    );
    assert_eq!(result, Err(Rejection::NotOutstanding));
}

/// Counterexample for Revise: terms silently weakened by automation.
#[test]
fn revise_requires_human_provenance() {
    let contract = issued();
    let mut command = cmd(
        Some(&contract),
        Role::Issuer,
        Command::Revise {
            bindings: bindings("v2"),
        },
    );
    command.provenance = Provenance::Delegate;
    assert_eq!(
        transition(Some(&contract), &command),
        Err(Rejection::RevisionRequiresHuman)
    );
}

#[test]
fn revise_replaces_bindings_and_clears_candidate_and_support() {
    let contract = supported(&proposed(&issued(), "s"));
    let revised = apply(
        Some(&contract),
        Role::Issuer,
        Command::Revise {
            bindings: bindings("v2"),
        },
    )
    .expect("revise");
    assert_eq!(
        (
            revised.revision,
            revised.bindings,
            revised.candidate,
            revised.support,
            revised.generation
        ),
        (2, bindings("v2"), None, None, contract.generation + 1)
    );
}

#[test]
fn every_rejection_protects_an_axiom_or_well_formedness() {
    let cases = [
        (
            Rejection::WrongRole {
                command: CommandKind::Discharge,
                required: Role::Settler,
                actual: Role::Executor,
            },
            Axiom::Monopoly,
        ),
        (Rejection::RevisionRequiresHuman, Axiom::Monopoly),
        (Rejection::WithinReach, Axiom::Monopoly),
        (Rejection::NoCandidate, Axiom::Exactness),
        (Rejection::SupportPresent, Axiom::Exactness),
        (
            Rejection::CoordinateMismatch {
                field: CoordinateField::Generation,
            },
            Axiom::Exactness,
        ),
        (Rejection::TargetMismatch, Axiom::Exactness),
        (Rejection::Released, Axiom::Conservation),
        (Rejection::NotOutstanding, Axiom::Conservation),
        (Rejection::NoSupport, Axiom::Conservation),
        (Rejection::ContractExists, Axiom::WellFormed),
        (Rejection::UnknownContract, Axiom::WellFormed),
        (Rejection::ContractMismatch, Axiom::WellFormed),
        (
            Rejection::StaleVersion {
                expected: 1,
                current: 2,
            },
            Axiom::WellFormed,
        ),
    ];
    for (rejection, axiom) in cases {
        assert_eq!(rejection.axiom(), axiom, "{rejection:?}");
    }
}

#[test]
fn digests_round_trip_through_json_as_hex() {
    let value = digest("x");
    let json = serde_json::to_string(&value).expect("serialize");
    assert_eq!(json, format!("\"{value}\""));
    assert_eq!(
        serde_json::from_str::<Digest>(&json).expect("deserialize"),
        value
    );
}

#[test]
fn support_records_the_certificate_and_coordinate() {
    let contract = proposed(&issued(), "s");
    let supported = supported(&contract);
    assert_eq!(
        supported.support,
        Some(Support {
            certificate: digest("certificate"),
            coordinate: coordinate(&contract),
        })
    );
}

/// A contract supported by evidence of the given reach.
fn supported_with(reach: Reach) -> Contract {
    let contract = proposed(&issued(), "s");
    apply(
        Some(&contract),
        Role::Verifier,
        Command::Support {
            certificate: digest("certificate"),
            coordinate: Coordinate {
                reach,
                ..coordinate(&contract)
            },
        },
    )
    .expect("support")
}

fn settle(contract: &Contract, decision: DecisionProvenance) -> Result<Contract, Rejection> {
    apply(
        Some(contract),
        Role::Settler,
        Command::Discharge {
            attestation: digest("accept"),
            coordinate: contract.support.clone().expect("support").coordinate,
            decision,
        },
    )
}

#[test]
fn only_an_explicit_human_act_settles_on_evidence_from_within_reach() {
    let within = supported_with(Reach::Within);
    let presumed = DecisionProvenance::Presumed {
        convention: digest("convention"),
        classifier: digest("classifier"),
    };
    let interpreted = DecisionProvenance::Interpreted {
        classifier: digest("classifier"),
    };
    assert_eq!(
        settle(&within, presumed.clone()),
        Err(Rejection::WithinReach)
    );
    assert_eq!(settle(&within, interpreted), Err(Rejection::WithinReach));
    let explicit = settle(&within, DecisionProvenance::Explicit).expect("explicit settles");
    assert_eq!(explicit.standing, Standing::Discharged);

    let beyond = supported_with(Reach::Beyond);
    let presumed = settle(&beyond, presumed).expect("beyond settles by convention");
    assert_eq!(presumed.standing, Standing::Discharged);
}

#[test]
fn a_coordinate_recorded_before_reach_existed_reads_as_within_reach() {
    let mut value = serde_json::to_value(coordinate(&proposed(&issued(), "s"))).expect("json");
    let object = value.as_object_mut().expect("object");
    object.remove("basis");
    object.remove("reach");
    let old: Coordinate = serde_json::from_value(value).expect("old coordinate");
    assert_eq!((old.basis, old.reach), (Digest::ZERO, Reach::Within));
}
