use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ExecutionLimits {
    pub(crate) turns: u64,
    pub(crate) actions: u64,
    pub(crate) deadline: u64,
    pub(crate) max_attempts: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ExecutionBinding {
    pub(crate) scope: String,
    pub(crate) ledger_scope: String,
    pub(crate) contract_id: String,
    pub(crate) revision: u64,
    pub(crate) execution_policy: Option<String>,
    pub(crate) execution_policy_hash: Option<String>,
    pub(crate) dispatched: bool,
    pub(crate) resume_same_attempt: bool,
    pub(crate) attempts: u64,
    pub(crate) turns_used: u64,
    pub(crate) actions_used: u64,
    pub(crate) next_action_at: u64,
    pub(crate) attempt_key: String,
    pub(crate) turns_limit: u64,
    pub(crate) actions_limit: u64,
    pub(crate) deadline: u64,
    pub(crate) max_attempts: u64,
    pub(crate) lease_owner: Option<String>,
    pub(crate) lease_expires_at: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct BoundSession {
    pub(crate) ledger_scope: String,
    pub(crate) contract_id: String,
    pub(crate) current: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RecoveryClaim {
    pub(crate) binding: ExecutionBinding,
    pub(crate) interrupted: bool,
    pub(crate) context_changed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum Reservation {
    Reserved(Box<ExecutionBinding>),
    Denied { reason: ReservationDenial },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ReservationDenial {
    Deadline,
    LeaseHeld,
    AttemptBudget,
    AttemptInactive,
    ProviderTurnBudget,
    ActionBudget,
    NotDue,
    ContractInactive,
}

impl ReservationDenial {
    pub(crate) fn message(self) -> &'static str {
        match self {
            Self::Deadline => "contract deadline exhausted",
            Self::LeaseHeld => "contract execution lease is held by another owner",
            Self::AttemptBudget => "contract attempt budget exhausted",
            Self::AttemptInactive => "contract execution attempt is not active",
            Self::ProviderTurnBudget => "contract provider-turn budget exhausted",
            Self::ActionBudget => "contract action budget exhausted",
            Self::NotDue => "contract retry is not due",
            Self::ContractInactive => "contract is not active at the bound revision",
        }
    }

    pub(crate) fn exhausts_contract(self) -> bool {
        matches!(
            self,
            Self::Deadline | Self::AttemptBudget | Self::ProviderTurnBudget | Self::ActionBudget
        )
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AttemptSchedule {
    Immediate,
    At(u64),
    AwaitRevision,
}

impl AttemptSchedule {
    pub(super) fn next_action_at(self) -> u64 {
        match self {
            Self::Immediate | Self::AwaitRevision => 0,
            Self::At(next_action_at) => next_action_at,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ReservationKind {
    Turn,
    Action,
}

impl ReservationKind {
    pub(super) fn used(self, binding: &ExecutionBinding) -> u64 {
        match self {
            Self::Turn => binding.turns_used,
            Self::Action => binding.actions_used,
        }
    }

    pub(super) fn limit(self, binding: &ExecutionBinding) -> u64 {
        match self {
            Self::Turn => binding.turns_limit,
            Self::Action => binding.actions_limit,
        }
    }

    pub(super) fn denial(self) -> ReservationDenial {
        match self {
            Self::Turn => ReservationDenial::ProviderTurnBudget,
            Self::Action => ReservationDenial::ActionBudget,
        }
    }

    pub(super) fn increment_sql(self) -> &'static str {
        match self {
            Self::Turn => {
                "UPDATE pro_contract_binding SET turns_used = turns_used + 1,
                 lease_owner = ?, lease_expires_at = ? WHERE scope = ?"
            }
            Self::Action => {
                "UPDATE pro_contract_binding SET actions_used = actions_used + 1,
                 lease_owner = ?, lease_expires_at = ? WHERE scope = ?"
            }
        }
    }
}
