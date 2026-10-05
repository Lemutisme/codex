use crate::AuthenticatedCommand;
use crate::Bindings;
use crate::Candidate;
use crate::Command;
use crate::Contract;
use crate::Coordinate;
use crate::CoordinateField;
use crate::DecisionProvenance;
use crate::Digest;
use crate::OwnerId;
use crate::Provenance;
use crate::Reach;
use crate::Rejection;
use crate::Settlement;
use crate::Standing;
use crate::Support;
use crate::Target;

/// Applies one authenticated command to the current state of one contract.
///
/// Returns the next state, or the reason the command was rejected; rejection never changes
/// the contract.
pub fn transition(
    current: Option<&Contract>,
    command: &AuthenticatedCommand,
) -> Result<Contract, Rejection> {
    let kind = command.command.kind();
    let required = kind.required_role();
    if command.role != required {
        return Err(Rejection::WrongRole {
            command: kind,
            required,
            actual: command.role,
        });
    }
    let contract = match (&command.command, current) {
        (Command::Issue { owner, bindings }, None) => return issue(command, owner, bindings),
        (Command::Issue { .. }, Some(_)) => return Err(Rejection::ContractExists),
        (_, None) => return Err(Rejection::UnknownContract),
        (_, Some(contract)) => contract,
    };
    if contract.id != command.contract_id {
        return Err(Rejection::ContractMismatch);
    }
    if command.expected_version != contract.version {
        return Err(Rejection::StaleVersion {
            expected: command.expected_version,
            current: contract.version,
        });
    }
    if contract.standing == Standing::Released {
        return Err(Rejection::Released);
    }
    let mut next = contract.clone();
    match &command.command {
        Command::Issue { .. } => return Err(Rejection::ContractExists),
        Command::Propose { subject_hash } => propose(&mut next, *subject_hash)?,
        Command::Support {
            certificate,
            coordinate,
        } => support(&mut next, *certificate, coordinate)?,
        Command::Defeat { target, .. } | Command::Challenge { target, .. } => {
            defeat(&mut next, target)?
        }
        Command::Withdraw { target, .. } => withdraw(&mut next, target)?,
        Command::Discharge {
            attestation,
            coordinate,
            decision,
        } => discharge(&mut next, *attestation, coordinate, decision)?,
        Command::Release { .. } => {
            require_outstanding(&next)?;
            next.standing = Standing::Released;
        }
        Command::Revise { bindings } => revise(&mut next, command.provenance, *bindings)?,
    }
    next.version += 1;
    Ok(next)
}

fn issue(
    command: &AuthenticatedCommand,
    owner: &OwnerId,
    bindings: &Bindings,
) -> Result<Contract, Rejection> {
    if command.expected_version != 0 {
        return Err(Rejection::StaleVersion {
            expected: command.expected_version,
            current: 0,
        });
    }
    Ok(Contract {
        id: command.contract_id.clone(),
        owner: owner.clone(),
        revision: 1,
        bindings: *bindings,
        standing: Standing::Outstanding,
        generation: 0,
        candidate: None,
        support: None,
        settlement: None,
        version: 1,
    })
}

fn require_outstanding(contract: &Contract) -> Result<(), Rejection> {
    if contract.standing == Standing::Outstanding {
        Ok(())
    } else {
        Err(Rejection::NotOutstanding)
    }
}

fn propose(next: &mut Contract, subject_hash: Digest) -> Result<(), Rejection> {
    require_outstanding(next)?;
    next.generation += 1;
    next.candidate = Some(Candidate {
        generation: next.generation,
        subject_hash,
    });
    next.support = None;
    Ok(())
}

fn support(
    next: &mut Contract,
    certificate: Digest,
    coordinate: &Coordinate,
) -> Result<(), Rejection> {
    require_outstanding(next)?;
    let candidate = next.candidate.ok_or(Rejection::NoCandidate)?;
    if next.support.is_some() {
        return Err(Rejection::SupportPresent);
    }
    let checks = [
        (
            CoordinateField::ContractId,
            coordinate.contract_id == next.id,
        ),
        (
            CoordinateField::Revision,
            coordinate.revision == next.revision,
        ),
        (
            CoordinateField::TermsHash,
            coordinate.terms_hash == next.bindings.terms_hash,
        ),
        (
            CoordinateField::CapturePolicyHash,
            coordinate.capture_policy_hash == next.bindings.capture_policy_hash,
        ),
        (
            CoordinateField::EvidencePolicyHash,
            coordinate.evidence_policy_hash == next.bindings.evidence_policy_hash,
        ),
        (
            CoordinateField::Generation,
            coordinate.generation == candidate.generation,
        ),
        (
            CoordinateField::SubjectHash,
            coordinate.subject_hash == candidate.subject_hash,
        ),
    ];
    if let Some((field, _)) = checks.into_iter().find(|(_, matches)| !matches) {
        return Err(Rejection::CoordinateMismatch { field });
    }
    next.support = Some(Support {
        certificate,
        coordinate: coordinate.clone(),
    });
    Ok(())
}

/// Checks that `target` names the exact current candidate, support or settlement.
fn target_matches(contract: &Contract, target: &Target) -> bool {
    match (contract.standing, target) {
        (
            Standing::Outstanding,
            Target::Candidate {
                generation,
                subject_hash,
            },
        ) => {
            contract.candidate
                == Some(Candidate {
                    generation: *generation,
                    subject_hash: *subject_hash,
                })
        }
        (Standing::Outstanding, Target::Support { coordinate }) => contract
            .support
            .as_ref()
            .is_some_and(|support| &support.coordinate == coordinate),
        (Standing::Discharged, Target::Settlement { coordinate }) => contract
            .settlement
            .as_ref()
            .is_some_and(|settlement| &settlement.coordinate == coordinate),
        _ => false,
    }
}

/// Defeat and Challenge: the artifact is defeated and duty is restored.
fn defeat(next: &mut Contract, target: &Target) -> Result<(), Rejection> {
    if matches!(target, Target::Support { .. }) || !target_matches(next, target) {
        return Err(Rejection::TargetMismatch);
    }
    next.standing = Standing::Outstanding;
    next.candidate = None;
    next.support = None;
    next.settlement = None;
    next.generation += 1;
    Ok(())
}

/// Withdraw: the judgment is no longer trusted; the subject is kept under a new generation.
fn withdraw(next: &mut Contract, target: &Target) -> Result<(), Rejection> {
    if matches!(target, Target::Candidate { .. }) || !target_matches(next, target) {
        return Err(Rejection::TargetMismatch);
    }
    next.standing = Standing::Outstanding;
    next.support = None;
    next.settlement = None;
    next.generation += 1;
    let candidate = next.candidate.as_mut().ok_or(Rejection::NoCandidate)?;
    candidate.generation = next.generation;
    Ok(())
}

fn discharge(
    next: &mut Contract,
    attestation: Digest,
    coordinate: &Coordinate,
    decision: &DecisionProvenance,
) -> Result<(), Rejection> {
    require_outstanding(next)?;
    let support = next.support.as_ref().ok_or(Rejection::NoSupport)?;
    if &support.coordinate != coordinate {
        return Err(Rejection::CoordinateMismatch {
            field: CoordinateField::Support,
        });
    }
    // Only the holder of what lies beyond the claim's reach may settle on evidence from within it.
    if coordinate.reach == Reach::Within && decision != &DecisionProvenance::Explicit {
        return Err(Rejection::WithinReach);
    }
    next.standing = Standing::Discharged;
    next.settlement = Some(Settlement {
        attestation,
        coordinate: coordinate.clone(),
        decision: decision.clone(),
    });
    Ok(())
}

fn revise(
    next: &mut Contract,
    provenance: Provenance,
    bindings: Bindings,
) -> Result<(), Rejection> {
    if provenance != Provenance::Human {
        return Err(Rejection::RevisionRequiresHuman);
    }
    require_outstanding(next)?;
    next.revision += 1;
    next.bindings = bindings;
    next.candidate = None;
    next.support = None;
    next.generation += 1;
    Ok(())
}
