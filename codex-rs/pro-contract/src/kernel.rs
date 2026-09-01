use crate::ContractSpec;
use crate::ReplayPolicy;
use crate::SubjectCoordinate;
use crate::kernel_validation::command_actor;
use crate::kernel_validation::dependent_closure;
use crate::kernel_validation::institution_command;
use crate::kernel_validation::invalid_spec;
use crate::kernel_validation::outstanding_dependent;
use crate::rejection::Rejection;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;

pub const INSTITUTION_ACTOR: &str = "institution";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Draft {
    pub id: String,
    pub scope: String,
    pub spec: ContractSpec,
    pub issuer: String,
    pub executor: String,
    pub spec_hash: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Dormant,
    Active,
    Verification,
    Escalated,
    Discharged,
    Released,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Handoff {
    pub summary: String,
    pub uncertainties: Vec<String>,
    pub subject: SubjectCoordinate,
    pub replay: Option<ReplayResult>,
    pub time: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ReplayResult {
    pub policy_hash: String,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub passed: bool,
    pub summary: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChallengeDisclosure {
    Executor,
    Sealed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Challenge {
    pub revision: u64,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub disclosure: ChallengeDisclosure,
    pub summary: Option<String>,
    pub time: u64,
    pub attestation_id: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Blocked {
    pub reason: String,
    pub time: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Escalation {
    pub reason: String,
    pub time: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct PendingRevision {
    pub spec: ContractSpec,
    pub spec_hash: String,
    pub reason: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Attestation {
    pub id: String,
    pub revision: u64,
    pub spec_hash: String,
    pub subject_hash: String,
    pub evidence_hash: String,
    pub verifier_id: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RevisionDisposition {
    Accept,
    Reject,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Contract {
    pub id: String,
    pub scope: String,
    pub spec: ContractSpec,
    pub issuer: String,
    pub executor: String,
    pub spec_hash: String,
    pub revision: u64,
    pub status: Status,
    pub blocked: Option<Blocked>,
    pub handoff: Option<Handoff>,
    pub challenge: Option<Challenge>,
    pub pending_revision: Option<PendingRevision>,
    pub attestation_id: Option<String>,
    pub escalation: Option<Escalation>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct State {
    pub contracts: BTreeMap<String, Contract>,
    pub attestations: BTreeMap<String, Attestation>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Command {
    Issue {
        actor: String,
        draft: Draft,
    },
    Activate {
        actor: String,
        contract_id: String,
        revision: u64,
        time: u64,
    },
    ReportReady {
        actor: String,
        contract_id: String,
        revision: u64,
        summary: String,
        uncertainties: Vec<String>,
        subject: SubjectCoordinate,
        replay: Option<ReplayResult>,
        time: u64,
    },
    ReportBlocked {
        actor: String,
        contract_id: String,
        revision: u64,
        reason: String,
        time: u64,
    },
    PetitionRevision {
        actor: String,
        contract_id: String,
        spec: ContractSpec,
        spec_hash: String,
        reason: String,
    },
    DecideRevision {
        actor: String,
        contract_id: String,
        revision: u64,
        spec_hash: String,
        disposition: RevisionDisposition,
    },
    Discharge {
        actor: String,
        contract_id: String,
        attestation: Attestation,
    },
    Challenge {
        actor: String,
        contract_id: String,
        challenge: Challenge,
    },
    Resume {
        actor: String,
        contract_id: String,
        revision: u64,
        spec_hash: String,
    },
    Escalate {
        actor: String,
        contract_id: String,
        revision: u64,
        reason: String,
        time: u64,
    },
    Release {
        actor: String,
        contract_id: String,
        revision: u64,
        spec_hash: String,
        reason: String,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Decision {
    Accepted,
    Rejected { reason: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Transition {
    pub state: State,
    pub decision: Decision,
    pub command: Command,
}

pub fn hash_spec(spec: &ContractSpec) -> Result<String, serde_json::Error> {
    serde_json::to_vec(spec).map(|encoded| format!("{:x}", Sha256::digest(encoded)))
}

pub fn hash_replay(policy: &ReplayPolicy) -> Result<String, serde_json::Error> {
    serde_json::to_vec(policy).map(|encoded| format!("{:x}", Sha256::digest(encoded)))
}

pub fn transition(state: &State, command: Command) -> Transition {
    let reject = |rejection: Rejection| Transition {
        state: state.clone(),
        decision: Decision::Rejected {
            reason: rejection.reason(),
        },
        command: command.clone(),
    };

    if let Command::Issue { actor, draft } = &command {
        if actor != &draft.issuer {
            return reject(Rejection::IssueRequiresIssuer);
        }
        if draft.issuer == draft.executor {
            return reject(Rejection::IssuerExecutorDistinct);
        }
        if !matches!(hash_spec(&draft.spec), Ok(spec_hash) if draft.spec_hash == spec_hash) {
            return reject(Rejection::SpecHashMismatch);
        }
        if draft.id.is_empty() || draft.scope.is_empty() {
            return reject(Rejection::EmptyIdentity);
        }
        if let Some(rejection) = invalid_spec(&draft.spec) {
            return reject(rejection);
        }
        if let Some(existing) = state.contracts.get(&draft.id) {
            if existing.spec_hash == draft.spec_hash
                && existing.issuer == draft.issuer
                && existing.executor == draft.executor
                && existing.scope == draft.scope
            {
                return accept(state.clone(), command);
            }
            return reject(Rejection::ContractExists);
        }
        for requirement in &draft.spec.requires {
            if requirement.contract_id == draft.id {
                return reject(Rejection::SelfRequirement);
            }
            let Some(dependency) = state.contracts.get(&requirement.contract_id) else {
                return reject(Rejection::RequirementNotFound);
            };
            if dependency.issuer != draft.issuer || dependency.revision != requirement.revision {
                return reject(Rejection::RequirementCoordinateMismatch);
            }
            if dependency.status == Status::Released {
                return reject(Rejection::RequirementReleased);
            }
        }
        let mut next = state.clone();
        next.contracts.insert(
            draft.id.clone(),
            Contract {
                id: draft.id.clone(),
                scope: draft.scope.clone(),
                spec: draft.spec.clone(),
                issuer: draft.issuer.clone(),
                executor: draft.executor.clone(),
                spec_hash: draft.spec_hash.clone(),
                revision: 1,
                status: Status::Dormant,
                blocked: None,
                handoff: None,
                challenge: None,
                pending_revision: None,
                attestation_id: None,
                escalation: None,
            },
        );
        return accept(next, command);
    }

    let contract_id = command_contract_id(&command);
    let Some(contract) = state.contracts.get(contract_id) else {
        return reject(Rejection::ContractNotFound);
    };
    if institution_command(&command) && command_actor(&command) != INSTITUTION_ACTOR {
        return reject(Rejection::InstitutionActorRequired);
    }

    if let Command::Challenge {
        actor, challenge, ..
    } = &command
    {
        if actor != &contract.issuer {
            return reject(Rejection::ChallengeRequiresIssuer);
        }
        if contract.pending_revision.is_some() {
            return reject(Rejection::ChallengeDuringRevision);
        }
        if !matches!(contract.status, Status::Verification | Status::Discharged) {
            return reject(Rejection::NotAwaitingAdjudication);
        }
        if challenge.revision != contract.revision
            || contract
                .handoff
                .as_ref()
                .is_none_or(|handoff| handoff.subject.hash != challenge.subject_hash)
        {
            return reject(Rejection::ChallengeCoordinateMismatch);
        }
        if challenge.evidence_hash.is_empty() || challenge.attestation_id.is_some() {
            return reject(Rejection::InvalidChallengeEvidence);
        }
        match challenge.disclosure {
            ChallengeDisclosure::Executor
                if challenge.summary.as_deref().is_none_or(str::is_empty) =>
            {
                return reject(Rejection::ExecutorChallengeNeedsSummary);
            }
            ChallengeDisclosure::Sealed if challenge.summary.is_some() => {
                return reject(Rejection::SealedChallengeHasSummary);
            }
            ChallengeDisclosure::Executor | ChallengeDisclosure::Sealed => {}
        }
        let affected = dependent_closure(state, contract_id);
        let mut next = state.clone();
        for affected_id in affected {
            let Some(affected_contract) = next.contracts.get_mut(&affected_id) else {
                return reject(Rejection::DependencyStateInconsistent);
            };
            if affected_contract.status == Status::Released {
                continue;
            }
            if affected_id == contract_id {
                affected_contract.status = match challenge.disclosure {
                    ChallengeDisclosure::Executor => Status::Dormant,
                    ChallengeDisclosure::Sealed => Status::Escalated,
                };
                affected_contract.challenge = Some(Challenge {
                    attestation_id: affected_contract.attestation_id.clone(),
                    ..challenge.clone()
                });
                affected_contract.escalation =
                    (challenge.disclosure == ChallengeDisclosure::Sealed).then(|| Escalation {
                        reason: "verification challenged; evidence is sealed".to_string(),
                        time: challenge.time,
                    });
            } else if affected_contract.status != Status::Dormant {
                affected_contract.status = Status::Escalated;
                affected_contract.escalation = Some(Escalation {
                    reason: format!("dependency support lost: {contract_id}"),
                    time: challenge.time,
                });
            }
            affected_contract.blocked = None;
            affected_contract.handoff = None;
            affected_contract.attestation_id = None;
        }
        return accept(next, command);
    }

    if matches!(contract.status, Status::Discharged | Status::Released) {
        return reject(Rejection::AlreadySettled);
    }
    let dependent = outstanding_dependent(state, contract_id);

    match &command {
        Command::Issue { .. } | Command::Challenge { .. } => unreachable!("handled above"),
        Command::ReportReady {
            revision,
            summary,
            uncertainties,
            subject,
            replay,
            time,
            ..
        } => {
            if contract.status != Status::Active || revision != &contract.revision {
                return reject(Rejection::NotActiveAtRevision);
            }
            if contract.pending_revision.is_some() {
                return reject(Rejection::HandoffDuringRevision);
            }
            if summary.is_empty()
                || subject.spec_hash != contract.spec_hash
                || subject.artifacts != contract.spec.artifacts.paths()
            {
                return reject(Rejection::HandoffSpecMismatch);
            }
            let configured_replay = contract.spec.evidence.replay.as_ref();
            match (configured_replay, replay) {
                (Some(_), None) => return reject(Rejection::ReplayEvidenceRequired),
                (None, Some(_)) => return reject(Rejection::ReplayNotConfigured),
                (Some(policy), Some(result)) => {
                    if !matches!(
                        hash_replay(policy),
                        Ok(policy_hash) if result.policy_hash == policy_hash
                    ) || result.subject_hash != subject.hash
                    {
                        return reject(Rejection::ReplayCoordinateMismatch);
                    }
                }
                (None, None) => {}
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            if let Some(failed) = replay.as_ref().filter(|result| !result.passed) {
                next_contract.status = Status::Dormant;
                next_contract.challenge = Some(Challenge {
                    revision: contract.revision,
                    subject_hash: subject.hash.clone(),
                    evidence_hash: failed.evidence_hash.clone(),
                    disclosure: ChallengeDisclosure::Executor,
                    summary: Some(failed.summary.clone()),
                    time: *time,
                    attestation_id: None,
                });
                next_contract.blocked = None;
                next_contract.handoff = None;
            } else {
                next_contract.status = Status::Verification;
                next_contract.blocked = None;
                next_contract.challenge = None;
                next_contract.handoff = Some(Handoff {
                    summary: summary.clone(),
                    uncertainties: uncertainties.clone(),
                    subject: subject.clone(),
                    replay: replay.clone(),
                    time: *time,
                });
            }
            next_contract.attestation_id = None;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::ReportBlocked {
            revision,
            reason,
            time,
            ..
        } => {
            if contract.status != Status::Active || revision != &contract.revision {
                return reject(Rejection::NotActiveAtRevision);
            }
            if contract.pending_revision.is_some() || reason.is_empty() {
                return reject(Rejection::InvalidBlockedReport);
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.blocked = Some(Blocked {
                reason: reason.clone(),
                time: *time,
            });
            accept(next, command)
        }
        Command::PetitionRevision {
            actor,
            spec,
            spec_hash,
            reason,
            ..
        } => {
            if actor != &contract.executor {
                return reject(Rejection::PetitionRequiresExecutor);
            }
            if contract.pending_revision.is_some() || reason.is_empty() {
                return reject(Rejection::InvalidPetition);
            }
            if spec_hash == &contract.spec_hash
                || !matches!(hash_spec(spec), Ok(hash) if &hash == spec_hash)
                || spec.requires != contract.spec.requires
            {
                return reject(Rejection::InvalidRevisionCoordinate);
            }
            if let Some(rejection) = invalid_spec(spec) {
                return reject(rejection);
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.pending_revision = Some(PendingRevision {
                spec: spec.clone(),
                spec_hash: spec_hash.clone(),
                reason: reason.clone(),
            });
            accept(next, command)
        }
        Command::DecideRevision {
            actor,
            revision,
            spec_hash,
            disposition,
            ..
        } => {
            if actor != &contract.issuer {
                return reject(Rejection::DecideRevisionRequiresIssuer);
            }
            let Some(pending) = &contract.pending_revision else {
                return reject(Rejection::NoPendingRevision);
            };
            if revision != &contract.revision || spec_hash != &pending.spec_hash {
                return reject(Rejection::RevisionDecisionMismatch);
            }
            if *disposition == RevisionDisposition::Accept
                && let Some(dependent) = dependent
            {
                return reject(Rejection::RequiredByOutstanding {
                    dependent_id: dependent.id.clone(),
                });
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            if *disposition == RevisionDisposition::Accept {
                next_contract.spec = pending.spec.clone();
                next_contract.spec_hash = pending.spec_hash.clone();
                next_contract.revision += 1;
                next_contract.status = Status::Dormant;
                next_contract.blocked = None;
                next_contract.handoff = None;
                next_contract.challenge = None;
                next_contract.attestation_id = None;
                next_contract.escalation = None;
            }
            next_contract.pending_revision = None;
            accept(next, command)
        }
        Command::Activate { revision, time, .. } => {
            if contract.status != Status::Dormant || revision != &contract.revision {
                return reject(Rejection::NotDormantAtRevision);
            }
            if contract.pending_revision.is_some() || *time >= contract.spec.budget.deadline {
                return reject(Rejection::CannotActivate);
            }
            if matches!(contract.spec.trigger, crate::Trigger::Time { at } if at > *time) {
                return reject(Rejection::TriggerNotReady);
            }
            if contract.spec.requires.iter().any(|requirement| {
                state
                    .contracts
                    .get(&requirement.contract_id)
                    .is_none_or(|dependency| {
                        dependency.revision != requirement.revision
                            || dependency.status != Status::Discharged
                            || dependency.attestation_id.is_none()
                    })
            }) {
                return reject(Rejection::RequirementNotEvidenced);
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.status = Status::Active;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::Resume {
            actor,
            revision,
            spec_hash,
            ..
        } => {
            if actor != &contract.issuer || contract.status != Status::Escalated {
                return reject(Rejection::ResumeRequiresIssuer);
            }
            if revision != &contract.revision || spec_hash != &contract.spec_hash {
                return reject(Rejection::ResumeCoordinateMismatch);
            }
            if contract.pending_revision.is_some() {
                return reject(Rejection::PendingRevisionFence);
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.status = Status::Dormant;
            next_contract.blocked = next_contract.blocked.clone().or_else(|| {
                next_contract.escalation.as_ref().map(|escalation| Blocked {
                    reason: escalation.reason.clone(),
                    time: escalation.time,
                })
            });
            next_contract.handoff = None;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::Escalate {
            revision,
            reason,
            time,
            ..
        } => {
            if revision != &contract.revision || reason.is_empty() {
                return reject(Rejection::InvalidEscalation);
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.status = Status::Escalated;
            next_contract.escalation = Some(Escalation {
                reason: reason.clone(),
                time: *time,
            });
            accept(next, command)
        }
        Command::Release {
            actor,
            revision,
            spec_hash,
            reason,
            ..
        } => {
            if actor != &contract.issuer || reason.is_empty() {
                return reject(Rejection::ReleaseRequiresIssuer);
            }
            if revision != &contract.revision || spec_hash != &contract.spec_hash {
                return reject(Rejection::ReleaseCoordinateMismatch);
            }
            if let Some(dependent) = dependent {
                return reject(Rejection::RequiredByOutstanding {
                    dependent_id: dependent.id.clone(),
                });
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.status = Status::Released;
            next_contract.blocked = None;
            next_contract.handoff = None;
            next_contract.challenge = None;
            next_contract.pending_revision = None;
            next_contract.attestation_id = None;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::Discharge {
            actor, attestation, ..
        } => {
            let Some(handoff) = &contract.handoff else {
                return reject(Rejection::NoHandoff);
            };
            if contract.status != Status::Verification || contract.pending_revision.is_some() {
                return reject(Rejection::NotAwaitingVerification);
            }
            if actor != &contract.issuer || attestation.verifier_id != contract.issuer {
                return reject(Rejection::AttestRequiresIssuer);
            }
            if attestation.revision != contract.revision
                || attestation.spec_hash != contract.spec_hash
                || attestation.subject_hash != handoff.subject.hash
                || attestation.id.is_empty()
                || attestation.evidence_hash.is_empty()
            {
                return reject(Rejection::AttestationCoordinateMismatch);
            }
            if state.attestations.contains_key(&attestation.id) {
                return reject(Rejection::AttestationExists);
            }
            if let Some(policy) = &contract.spec.evidence.replay {
                let Some(replay) = &handoff.replay else {
                    return reject(Rejection::ReplayDoesNotSupportDischarge);
                };
                if !replay.passed
                    || !matches!(
                        hash_replay(policy),
                        Ok(hash) if replay.policy_hash == hash
                    )
                    || replay.subject_hash != handoff.subject.hash
                    || replay.evidence_hash == attestation.evidence_hash
                {
                    return reject(Rejection::ReplayCannotDoubleAsAttestation);
                }
            }
            let mut next = state.clone();
            next.attestations
                .insert(attestation.id.clone(), attestation.clone());
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject(Rejection::StateInconsistent);
            };
            next_contract.status = Status::Discharged;
            next_contract.blocked = None;
            next_contract.challenge = None;
            next_contract.pending_revision = None;
            next_contract.attestation_id = Some(attestation.id.clone());
            next_contract.escalation = None;
            accept(next, command)
        }
    }
}

pub fn quiet(state: &State, scope: &str) -> bool {
    state.contracts.values().all(|contract| {
        contract.scope != scope || matches!(contract.status, Status::Discharged | Status::Released)
    })
}

fn accept(state: State, command: Command) -> Transition {
    Transition {
        state,
        decision: Decision::Accepted,
        command,
    }
}

fn command_contract_id(command: &Command) -> &str {
    match command {
        Command::Issue { draft, .. } => &draft.id,
        Command::Activate { contract_id, .. }
        | Command::ReportReady { contract_id, .. }
        | Command::ReportBlocked { contract_id, .. }
        | Command::PetitionRevision { contract_id, .. }
        | Command::DecideRevision { contract_id, .. }
        | Command::Discharge { contract_id, .. }
        | Command::Challenge { contract_id, .. }
        | Command::Resume { contract_id, .. }
        | Command::Escalate { contract_id, .. }
        | Command::Release { contract_id, .. } => contract_id,
    }
}

#[cfg(test)]
#[path = "kernel_tests.rs"]
mod tests;
