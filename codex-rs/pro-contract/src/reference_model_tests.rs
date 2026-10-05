//! Differential test against an independently expressed reference model.
//!
//! The model uses a phase machine instead of the kernel's optional fields, so a bug that
//! both share would have to be written twice in different shapes. Random command sequences
//! mix valid and invalid roles, versions, coordinates and targets; the kernel and the model
//! must agree on every accept/reject decision and on the resulting state.

use pretty_assertions::assert_eq;

use crate::AuthenticatedCommand;
use crate::Bindings;
use crate::Candidate;
use crate::Command;
use crate::Contract;
use crate::ContractId;
use crate::Coordinate;
use crate::DecisionProvenance;
use crate::Digest;
use crate::OwnerId;
use crate::Provenance;
use crate::Reach;
use crate::Role;
use crate::Standing;
use crate::Target;
use crate::transition;

#[derive(Clone, Debug, PartialEq)]
enum Phase {
    Open,
    Proposed(Candidate),
    Supported(Candidate, Coordinate),
    Settled(Candidate, Coordinate),
    Released,
}

#[derive(Clone, Debug, PartialEq)]
struct Model {
    id: ContractId,
    revision: u32,
    bindings: Bindings,
    generation: u64,
    version: u64,
    phase: Phase,
}

fn required_role(command: &Command) -> Role {
    match command {
        Command::Issue { .. } | Command::Revise { .. } => Role::Issuer,
        Command::Propose { .. } => Role::Executor,
        Command::Support { .. } | Command::Defeat { .. } | Command::Withdraw { .. } => {
            Role::Verifier
        }
        Command::Challenge { .. } | Command::Discharge { .. } | Command::Release { .. } => {
            Role::Settler
        }
    }
}

fn matches(model: &Model, candidate: &Candidate, coordinate: &Coordinate) -> bool {
    coordinate.contract_id == model.id
        && coordinate.revision == model.revision
        && coordinate.terms_hash == model.bindings.terms_hash
        && coordinate.capture_policy_hash == model.bindings.capture_policy_hash
        && coordinate.evidence_policy_hash == model.bindings.evidence_policy_hash
        && coordinate.generation == candidate.generation
        && coordinate.subject_hash == candidate.subject_hash
}

/// Applies a command to the model; `None` means the model rejects it.
fn model_step(model: Option<&Model>, command: &AuthenticatedCommand) -> Option<Model> {
    if command.role != required_role(&command.command) {
        return None;
    }
    let Some(model) = model else {
        return match &command.command {
            Command::Issue { bindings, .. } if command.expected_version == 0 => Some(Model {
                id: command.contract_id.clone(),
                revision: 1,
                bindings: *bindings,
                generation: 0,
                version: 1,
                phase: Phase::Open,
            }),
            _ => None,
        };
    };
    if matches!(command.command, Command::Issue { .. }) {
        return None;
    }
    if command.contract_id != model.id
        || command.expected_version != model.version
        || model.phase == Phase::Released
    {
        return None;
    }
    let outstanding = matches!(
        model.phase,
        Phase::Open | Phase::Proposed(_) | Phase::Supported(_, _)
    );
    let mut next = model.clone();
    next.version += 1;
    match &command.command {
        Command::Issue { .. } => return None,
        Command::Propose { subject_hash } => {
            if !outstanding {
                return None;
            }
            next.generation += 1;
            next.phase = Phase::Proposed(Candidate {
                generation: next.generation,
                subject_hash: *subject_hash,
            });
        }
        Command::Support { coordinate, .. } => match &model.phase {
            Phase::Proposed(candidate) if matches(model, candidate, coordinate) => {
                next.phase = Phase::Supported(*candidate, coordinate.clone());
            }
            _ => return None,
        },
        Command::Defeat { target, .. } | Command::Challenge { target, .. } => {
            let hit = match (&model.phase, target) {
                (
                    Phase::Proposed(candidate) | Phase::Supported(candidate, _),
                    Target::Candidate {
                        generation,
                        subject_hash,
                    },
                ) => candidate.generation == *generation && candidate.subject_hash == *subject_hash,
                (Phase::Settled(_, settled), Target::Settlement { coordinate }) => {
                    settled == coordinate
                }
                _ => false,
            };
            if !hit {
                return None;
            }
            next.generation += 1;
            next.phase = Phase::Open;
        }
        Command::Withdraw { target, .. } => {
            let kept = match (&model.phase, target) {
                (Phase::Supported(candidate, support), Target::Support { coordinate })
                    if support == coordinate =>
                {
                    *candidate
                }
                (Phase::Settled(candidate, settled), Target::Settlement { coordinate })
                    if settled == coordinate =>
                {
                    *candidate
                }
                _ => return None,
            };
            next.generation += 1;
            next.phase = Phase::Proposed(Candidate {
                generation: next.generation,
                subject_hash: kept.subject_hash,
            });
        }
        Command::Discharge {
            coordinate,
            decision,
            ..
        } => match &model.phase {
            Phase::Supported(candidate, support)
                if support == coordinate
                    && (coordinate.reach == Reach::Beyond
                        || decision == &DecisionProvenance::Explicit) =>
            {
                next.phase = Phase::Settled(*candidate, coordinate.clone());
            }
            _ => return None,
        },
        Command::Release { .. } => {
            if !outstanding {
                return None;
            }
            next.phase = Phase::Released;
        }
        Command::Revise { bindings } => {
            if command.provenance != Provenance::Human || !outstanding {
                return None;
            }
            next.revision += 1;
            next.bindings = *bindings;
            next.generation += 1;
            next.phase = Phase::Open;
        }
    }
    Some(next)
}

/// Projects a kernel contract onto the model's shape.
fn project(contract: &Contract) -> Model {
    let phase = match contract.standing {
        Standing::Released => Phase::Released,
        Standing::Discharged => Phase::Settled(
            contract
                .candidate
                .expect("discharged contract keeps its candidate"),
            contract
                .settlement
                .clone()
                .expect("discharged contract has a settlement")
                .coordinate,
        ),
        Standing::Outstanding => match (&contract.candidate, &contract.support) {
            (None, None) => Phase::Open,
            (Some(candidate), None) => Phase::Proposed(*candidate),
            (Some(candidate), Some(support)) => {
                Phase::Supported(*candidate, support.coordinate.clone())
            }
            (None, Some(_)) => panic!("support without a candidate: {contract:?}"),
        },
    };
    Model {
        id: contract.id.clone(),
        revision: contract.revision,
        bindings: contract.bindings,
        generation: contract.generation,
        version: contract.version,
        phase,
    }
}

fn assert_invariants(contract: &Contract) {
    if let Some(candidate) = contract.candidate {
        assert_eq!(candidate.generation, contract.generation, "{contract:?}");
    }
    if let Some(support) = &contract.support {
        let candidate = contract.candidate.expect("support implies a candidate");
        assert_eq!(support.coordinate.generation, candidate.generation);
        assert_eq!(support.coordinate.subject_hash, candidate.subject_hash);
    }
    assert_eq!(
        contract.standing == Standing::Discharged,
        contract.settlement.is_some(),
        "{contract:?}"
    );
}

struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }

    fn below(&mut self, bound: u64) -> u64 {
        self.next() % bound
    }

    fn chance(&mut self, percent: u64) -> bool {
        self.below(100) < percent
    }
}

fn contract_id() -> ContractId {
    ContractId("c".to_string())
}

fn digest(rng: &mut Rng) -> Digest {
    Digest::of(&rng.below(4).to_le_bytes())
}

fn bindings(rng: &mut Rng) -> Bindings {
    Bindings {
        terms_hash: digest(rng),
        capture_policy_hash: digest(rng),
        evidence_policy_hash: digest(rng),
    }
}

/// A coordinate that is usually right for the current candidate and sometimes perturbed.
fn coordinate(rng: &mut Rng, contract: Option<&Contract>) -> Coordinate {
    let mut coordinate = match contract {
        Some(contract) => {
            let candidate = contract.candidate.unwrap_or(Candidate {
                generation: contract.generation,
                subject_hash: Digest::of(b"none"),
            });
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
                basis: Digest::of(b"basis"),
                reach: Reach::Within,
            }
        }
        None => Coordinate {
            contract_id: contract_id(),
            revision: 1,
            terms_hash: digest(rng),
            generation: 0,
            subject_hash: digest(rng),
            capture_policy_hash: digest(rng),
            evidence_policy_hash: digest(rng),
            environment_digest: digest(rng),
            evaluator_digest: digest(rng),
            evidence_hash: digest(rng),
            basis: Digest::of(b"basis"),
            reach: Reach::Within,
        },
    };
    coordinate.reach = if rng.chance(50) {
        Reach::Within
    } else {
        Reach::Beyond
    };
    if rng.chance(25) {
        match rng.below(5) {
            0 => coordinate.generation += 1,
            1 => coordinate.subject_hash = digest(rng),
            2 => coordinate.revision += 1,
            3 => coordinate.evidence_hash = digest(rng),
            _ => coordinate.terms_hash = digest(rng),
        }
    }
    coordinate
}

/// The coordinate that the current support or settlement actually carries, when present.
fn recorded(rng: &mut Rng, contract: Option<&Contract>) -> Coordinate {
    let recorded = contract.and_then(|contract| {
        contract
            .settlement
            .as_ref()
            .map(|settlement| settlement.coordinate.clone())
            .or_else(|| {
                contract
                    .support
                    .as_ref()
                    .map(|support| support.coordinate.clone())
            })
    });
    match recorded {
        Some(coordinate) if rng.chance(80) => coordinate,
        _ => self::coordinate(rng, contract),
    }
}

fn target(rng: &mut Rng, contract: Option<&Contract>) -> Target {
    match rng.below(3) {
        0 => {
            let candidate = contract.and_then(|contract| contract.candidate);
            match candidate {
                Some(candidate) if rng.chance(80) => Target::Candidate {
                    generation: candidate.generation,
                    subject_hash: candidate.subject_hash,
                },
                _ => Target::Candidate {
                    generation: rng.below(4),
                    subject_hash: digest(rng),
                },
            }
        }
        1 => Target::Support {
            coordinate: recorded(rng, contract),
        },
        _ => Target::Settlement {
            coordinate: recorded(rng, contract),
        },
    }
}

/// Picks a command kind, weighted so that sequences usually live long enough to exercise
/// every standing: Issue mostly when nothing exists yet, Release rarely.
fn command_kind(rng: &mut Rng, contract: Option<&Contract>) -> u64 {
    match contract {
        None => {
            if rng.chance(90) {
                0
            } else {
                1 + rng.below(8)
            }
        }
        Some(_) => {
            let roll = rng.below(100);
            match roll {
                0..=1 => 0,
                2..=21 => 1,
                22..=41 => 2,
                42..=51 => 3,
                52..=61 => 4,
                62..=71 => 5,
                72..=91 => 6,
                92..=93 => 7,
                _ => 8,
            }
        }
    }
}

fn random_command(rng: &mut Rng, contract: Option<&Contract>) -> AuthenticatedCommand {
    let command = match command_kind(rng, contract) {
        0 => Command::Issue {
            owner: OwnerId("owner".to_string()),
            bindings: bindings(rng),
        },
        1 => Command::Propose {
            subject_hash: digest(rng),
        },
        2 => Command::Support {
            certificate: digest(rng),
            coordinate: coordinate(rng, contract),
        },
        3 => Command::Defeat {
            target: target(rng, contract),
            defeater: digest(rng),
        },
        4 => Command::Withdraw {
            target: target(rng, contract),
            cause: digest(rng),
        },
        5 => Command::Challenge {
            target: target(rng, contract),
            defeater: digest(rng),
        },
        6 => Command::Discharge {
            attestation: digest(rng),
            coordinate: recorded(rng, contract),
            decision: if rng.chance(50) {
                DecisionProvenance::Explicit
            } else {
                DecisionProvenance::Presumed {
                    convention: digest(rng),
                    classifier: digest(rng),
                }
            },
        },
        7 => Command::Release {
            attestation: digest(rng),
        },
        _ => Command::Revise {
            bindings: bindings(rng),
        },
    };
    let roles = [Role::Issuer, Role::Executor, Role::Verifier, Role::Settler];
    let role = if rng.chance(85) {
        required_role(&command)
    } else {
        roles[rng.below(4) as usize]
    };
    let current_version = contract.map_or(0, |contract| contract.version);
    AuthenticatedCommand {
        contract_id: if rng.chance(97) {
            contract_id()
        } else {
            ContractId("other".to_string())
        },
        expected_version: if rng.chance(92) {
            current_version
        } else {
            current_version + 1 + rng.below(2)
        },
        role,
        provenance: if rng.chance(85) {
            Provenance::Human
        } else {
            Provenance::Delegate
        },
        command,
    }
}

#[test]
fn kernel_agrees_with_the_reference_model_on_random_sequences() {
    let mut rng = Rng(0x9e37_79b9_7f4a_7c15);
    let mut accepted = 0u64;
    let mut rejected = 0u64;
    for _sequence in 0..2_000 {
        let mut contract: Option<Contract> = None;
        let mut model: Option<Model> = None;
        for _step in 0..40 {
            let command = random_command(&mut rng, contract.as_ref());
            let kernel = transition(contract.as_ref(), &command);
            let expected = model_step(model.as_ref(), &command);
            match (kernel, expected) {
                (Ok(next), Some(next_model)) => {
                    assert_invariants(&next);
                    assert_eq!(project(&next), next_model, "{command:?}");
                    contract = Some(next);
                    model = Some(next_model);
                    accepted += 1;
                }
                (Err(_), None) => rejected += 1,
                (kernel, expected) => {
                    panic!("disagreement on {command:?}: kernel {kernel:?}, model {expected:?}")
                }
            }
        }
    }
    assert!(
        accepted > 10_000 && rejected > 10_000,
        "weak coverage: {accepted} accepted, {rejected} rejected"
    );
}
