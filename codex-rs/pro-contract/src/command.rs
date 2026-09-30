use serde::Deserialize;
use serde::Serialize;

use crate::Bindings;
use crate::ContractId;
use crate::Coordinate;
use crate::DecisionProvenance;
use crate::Digest;
use crate::OwnerId;

/// Authority roles. Each command kind is bound to exactly one role (A1).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Issuer,
    Executor,
    Verifier,
    Settler,
}

/// Who actually exercised a role. Provenance is an attribute, not an additional role.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Provenance {
    Human,
    Delegate,
    Automation,
}

/// The exact object a defeat, challenge or withdrawal answers.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Target {
    Candidate {
        generation: u64,
        subject_hash: Digest,
    },
    Support {
        coordinate: Coordinate,
    },
    Settlement {
        coordinate: Coordinate,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Command {
    Issue {
        owner: OwnerId,
        bindings: Bindings,
    },
    Propose {
        subject_hash: Digest,
    },
    Support {
        certificate: Digest,
        coordinate: Coordinate,
    },
    /// A verdict against the artifact: the candidate is gone.
    Defeat {
        target: Target,
        defeater: Digest,
    },
    /// The judgment is no longer trusted; the artifact is kept for re-verification.
    Withdraw {
        target: Target,
        cause: Digest,
    },
    Challenge {
        target: Target,
        defeater: Digest,
    },
    Discharge {
        attestation: Digest,
        coordinate: Coordinate,
        decision: DecisionProvenance,
    },
    Release {
        attestation: Digest,
    },
    Revise {
        bindings: Bindings,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CommandKind {
    Issue,
    Propose,
    Support,
    Defeat,
    Withdraw,
    Challenge,
    Discharge,
    Release,
    Revise,
}

impl Command {
    pub fn kind(&self) -> CommandKind {
        match self {
            Command::Issue { .. } => CommandKind::Issue,
            Command::Propose { .. } => CommandKind::Propose,
            Command::Support { .. } => CommandKind::Support,
            Command::Defeat { .. } => CommandKind::Defeat,
            Command::Withdraw { .. } => CommandKind::Withdraw,
            Command::Challenge { .. } => CommandKind::Challenge,
            Command::Discharge { .. } => CommandKind::Discharge,
            Command::Release { .. } => CommandKind::Release,
            Command::Revise { .. } => CommandKind::Revise,
        }
    }
}

impl CommandKind {
    /// The single role bound to this command kind.
    pub fn required_role(self) -> Role {
        match self {
            CommandKind::Issue | CommandKind::Revise => Role::Issuer,
            CommandKind::Propose => Role::Executor,
            CommandKind::Support | CommandKind::Defeat | CommandKind::Withdraw => Role::Verifier,
            CommandKind::Challenge | CommandKind::Discharge | CommandKind::Release => Role::Settler,
        }
    }
}

/// A command whose actor the host has authenticated. The kernel checks role binding and
/// exactness; it cannot authenticate transport.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct AuthenticatedCommand {
    pub contract_id: ContractId,
    /// The contract version the caller observed; 0 for Issue.
    pub expected_version: u64,
    pub role: Role,
    pub provenance: Provenance,
    pub command: Command,
}
