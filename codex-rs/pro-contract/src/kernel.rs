use crate::ArtifactSpec;
use crate::SubjectCoordinate;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub const INSTITUTION_ACTOR: &str = "institution";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ContractSpec {
    pub claim: String,
    pub artifacts: ArtifactSpec,
    pub requires: Vec<Requirement>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Requirement {
    pub contract_id: String,
    pub revision: u64,
}

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
    pub handoff: Option<Handoff>,
    pub attestation_id: Option<String>,
    pub escalation: Option<String>,
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
    },
    ReportReady {
        actor: String,
        contract_id: String,
        revision: u64,
        summary: String,
        uncertainties: Vec<String>,
        subject: SubjectCoordinate,
    },
    Discharge {
        actor: String,
        contract_id: String,
        attestation: Attestation,
    },
    Challenge {
        actor: String,
        contract_id: String,
        revision: u64,
        subject_hash: String,
        reason: String,
    },
    Resume {
        actor: String,
        contract_id: String,
    },
    Release {
        actor: String,
        contract_id: String,
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

pub fn transition(state: &State, command: Command) -> Transition {
    let reject = |reason: &str| Transition {
        state: state.clone(),
        decision: Decision::Rejected {
            reason: reason.to_string(),
        },
        command: command.clone(),
    };

    if let Command::Issue { actor, draft } = &command {
        if actor != &draft.issuer {
            return reject("only the issuer may issue the contract");
        }
        if draft.issuer == draft.executor {
            return reject("issuer and executor must be distinct");
        }
        if match hash_spec(&draft.spec) {
            Ok(spec_hash) => draft.spec_hash != spec_hash,
            Err(_) => true,
        } {
            return reject("specification hash does not match");
        }
        if draft.id.is_empty() || draft.scope.is_empty() || draft.spec.claim.is_empty() {
            return reject("contract identity, scope, and claim must be non-empty");
        }
        if let Some(existing) = state.contracts.get(&draft.id) {
            if existing.spec_hash == draft.spec_hash
                && existing.issuer == draft.issuer
                && existing.executor == draft.executor
                && existing.scope == draft.scope
            {
                return accept(state.clone(), command);
            }
            return reject("contract already exists");
        }
        for requirement in &draft.spec.requires {
            if requirement.contract_id == draft.id {
                return reject("contract cannot require itself");
            }
            let Some(dependency) = state.contracts.get(&requirement.contract_id) else {
                return reject("required contract not found");
            };
            if dependency.issuer != draft.issuer || dependency.revision != requirement.revision {
                return reject("required contract coordinate does not match");
            }
            if dependency.status == Status::Released {
                return reject("required contract was released");
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
                handoff: None,
                attestation_id: None,
                escalation: None,
            },
        );
        return accept(next, command);
    }

    let contract_id = command_contract_id(&command);
    let Some(contract) = state.contracts.get(contract_id) else {
        return reject("contract not found");
    };

    match &command {
        Command::Issue { .. } => unreachable!("issue handled above"),
        Command::Activate {
            actor, revision, ..
        } => {
            if actor != INSTITUTION_ACTOR {
                return reject("activation requires the institution actor");
            }
            if contract.status != Status::Dormant || revision != &contract.revision {
                return reject("contract is not dormant at this revision");
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
                return reject("required contract is not evidenced");
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject("contract state is inconsistent");
            };
            next_contract.status = Status::Active;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::ReportReady {
            actor,
            revision,
            summary,
            uncertainties,
            subject,
            ..
        } => {
            if actor != INSTITUTION_ACTOR {
                return reject("handoff requires the institution actor");
            }
            if contract.status != Status::Active || revision != &contract.revision {
                return reject("contract is not active at this revision");
            }
            if summary.is_empty() {
                return reject("handoff summary must be non-empty");
            }
            if subject.spec_hash != contract.spec_hash
                || subject.artifacts != contract.spec.artifacts.paths()
            {
                return reject("subject does not match the contract specification");
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject("contract state is inconsistent");
            };
            next_contract.status = Status::Verification;
            next_contract.handoff = Some(Handoff {
                summary: summary.clone(),
                uncertainties: uncertainties.clone(),
                subject: subject.clone(),
            });
            next_contract.attestation_id = None;
            accept(next, command)
        }
        Command::Discharge {
            actor, attestation, ..
        } => {
            let Some(handoff) = &contract.handoff else {
                return reject("contract has not been handed off");
            };
            if contract.status != Status::Verification {
                return reject("contract is not awaiting verification");
            }
            if actor != &contract.issuer || attestation.verifier_id != contract.issuer {
                return reject("only the issuer may attest settlement");
            }
            if attestation.revision != contract.revision
                || attestation.spec_hash != contract.spec_hash
                || attestation.subject_hash != handoff.subject.hash
            {
                return reject("attestation coordinate does not match");
            }
            if attestation.id.is_empty() || attestation.evidence_hash.is_empty() {
                return reject("attestation identity and evidence must be non-empty");
            }
            if state.attestations.contains_key(&attestation.id) {
                return reject("attestation already exists");
            }
            let mut next = state.clone();
            next.attestations
                .insert(attestation.id.clone(), attestation.clone());
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject("contract state is inconsistent");
            };
            next_contract.status = Status::Discharged;
            next_contract.attestation_id = Some(attestation.id.clone());
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::Challenge {
            actor,
            revision,
            subject_hash,
            reason,
            ..
        } => {
            if actor != &contract.issuer {
                return reject("only the issuer may challenge settlement");
            }
            if !matches!(contract.status, Status::Verification | Status::Discharged) {
                return reject("contract is not awaiting or holding settlement");
            }
            if revision != &contract.revision
                || contract
                    .handoff
                    .as_ref()
                    .is_none_or(|handoff| &handoff.subject.hash != subject_hash)
            {
                return reject("challenge coordinate does not match");
            }
            if reason.is_empty() {
                return reject("challenge reason must be non-empty");
            }
            let affected = dependent_closure(state, contract_id);
            let mut next = state.clone();
            for affected_id in affected {
                let Some(affected_contract) = next.contracts.get_mut(&affected_id) else {
                    return reject("contract dependency state is inconsistent");
                };
                if affected_contract.status != Status::Released {
                    affected_contract.status = if affected_id == contract_id {
                        Status::Dormant
                    } else {
                        Status::Escalated
                    };
                    affected_contract.handoff = None;
                    affected_contract.attestation_id = None;
                    affected_contract.escalation = Some(reason.clone());
                }
            }
            accept(next, command)
        }
        Command::Resume { actor, .. } => {
            if actor != &contract.issuer {
                return reject("only the issuer may resume the contract");
            }
            if contract.status != Status::Escalated {
                return reject("contract is not escalated");
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject("contract state is inconsistent");
            };
            next_contract.status = Status::Dormant;
            next_contract.escalation = None;
            accept(next, command)
        }
        Command::Release { actor, reason, .. } => {
            if actor != &contract.issuer {
                return reject("only the issuer may release the contract");
            }
            if reason.is_empty() {
                return reject("release reason must be non-empty");
            }
            if matches!(contract.status, Status::Discharged | Status::Released) {
                return reject("contract is already settled");
            }
            if state.contracts.values().any(|candidate| {
                !matches!(candidate.status, Status::Discharged | Status::Released)
                    && candidate
                        .spec
                        .requires
                        .iter()
                        .any(|requirement| requirement.contract_id == contract.id)
            }) {
                return reject("contract is required by an outstanding contract");
            }
            let mut next = state.clone();
            let Some(next_contract) = next.contracts.get_mut(contract_id) else {
                return reject("contract state is inconsistent");
            };
            next_contract.status = Status::Released;
            next_contract.handoff = None;
            next_contract.attestation_id = None;
            next_contract.escalation = Some(reason.clone());
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
        | Command::Discharge { contract_id, .. }
        | Command::Challenge { contract_id, .. }
        | Command::Resume { contract_id, .. }
        | Command::Release { contract_id, .. } => contract_id,
    }
}

fn dependent_closure(state: &State, contract_id: &str) -> BTreeSet<String> {
    let mut affected = BTreeSet::from([contract_id.to_string()]);
    let mut pending = vec![contract_id.to_string()];
    while let Some(dependency_id) = pending.pop() {
        for candidate in state.contracts.values() {
            if !affected.contains(&candidate.id)
                && candidate
                    .spec
                    .requires
                    .iter()
                    .any(|requirement| requirement.contract_id == dependency_id)
            {
                affected.insert(candidate.id.clone());
                pending.push(candidate.id.clone());
            }
        }
    }
    affected
}

#[cfg(test)]
#[path = "kernel_tests.rs"]
mod tests;
