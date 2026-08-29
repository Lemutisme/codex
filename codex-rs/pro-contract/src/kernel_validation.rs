use crate::Contract;
use crate::ContractSpec;
use crate::State;
use crate::Status;
use crate::kernel::Command;
use std::collections::BTreeSet;

pub(crate) fn invalid_spec(spec: &ContractSpec) -> Option<&'static str> {
    if spec.goal.is_empty() || spec.evidence.claim.is_empty() {
        return Some("contract goal and evidence claim must be non-empty");
    }
    if spec.budget.turns == 0
        || spec.budget.actions == 0
        || spec.budget.deadline == 0
        || spec.resolution.max_attempts == 0
    {
        return Some("contract budget and attempt limits must be positive");
    }
    let authority = spec.authority.iter().collect::<BTreeSet<_>>();
    if authority.len() != spec.authority.len() || spec.authority.iter().any(String::is_empty) {
        return Some("contract authority entries must be unique and non-empty");
    }
    if let Some(replay) = &spec.evidence.replay {
        if replay.artifacts != spec.artifacts {
            return Some("replay artifacts must match contract artifacts");
        }
        if replay.checks.is_empty()
            && replay.protected.is_empty()
            && replay.artifacts.paths().is_empty()
        {
            return Some("replay policy must not be empty");
        }
        if replay.checks.iter().any(|check| {
            check.argv.is_empty()
                || check.argv.iter().any(String::is_empty)
                || !(1_000..=600_000).contains(&check.timeout_ms)
        }) {
            return Some("replay checks are invalid");
        }
        if replay
            .protected
            .iter()
            .any(|protected| protected.sha256.is_empty())
        {
            return Some("protected replay hashes must be non-empty");
        }
    }
    None
}

pub(crate) fn institution_command(command: &Command) -> bool {
    matches!(
        command,
        Command::Activate { .. }
            | Command::ReportReady { .. }
            | Command::ReportBlocked { .. }
            | Command::Escalate { .. }
    )
}

pub(crate) fn command_actor(command: &Command) -> &str {
    match command {
        Command::Issue { actor, .. }
        | Command::Activate { actor, .. }
        | Command::ReportReady { actor, .. }
        | Command::ReportBlocked { actor, .. }
        | Command::PetitionRevision { actor, .. }
        | Command::DecideRevision { actor, .. }
        | Command::Discharge { actor, .. }
        | Command::Challenge { actor, .. }
        | Command::Resume { actor, .. }
        | Command::Escalate { actor, .. }
        | Command::Release { actor, .. } => actor,
    }
}

pub(crate) fn outstanding_dependent<'a>(
    state: &'a State,
    contract_id: &str,
) -> Option<&'a Contract> {
    state.contracts.values().find(|candidate| {
        !matches!(candidate.status, Status::Discharged | Status::Released)
            && candidate
                .spec
                .requires
                .iter()
                .any(|requirement| requirement.contract_id == contract_id)
    })
}

pub(crate) fn dependent_closure(state: &State, contract_id: &str) -> BTreeSet<String> {
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
