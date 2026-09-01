//! Typed rejection vocabulary for the settlement kernel.
//!
//! Every guard in `transition` rejects with a `Rejection` variant. Each
//! variant maps to exactly one constitutional axiom, one well-formedness
//! class, or the fail-closed class, so the guard audit is a compiler fact
//! instead of a hand-maintained table. Reason strings are the settlement
//! wire format and must never drift; `Decision::Rejected { reason }` stays
//! the serialized form.

use std::fmt;

/// The four constitutional axioms of the settlement kernel.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Axiom {
    /// A1: recognized transitions are monopolized by typed authority roles.
    Monopoly,
    /// A2: recognizing commands bind exact coordinates; fencing is exactness
    /// through time.
    Exactness,
    /// A3: outstanding duty ends only through authorized, evidence-supported
    /// settlement or release.
    Conservation,
    /// A4: accepted defeaters withdraw support atomically and restore owned
    /// responsibility.
    Defeasance,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RejectionClass {
    Constitutional(Axiom),
    WellFormedness,
    FailClosed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Rejection {
    IssueRequiresIssuer,
    IssuerExecutorDistinct,
    SpecHashMismatch,
    EmptyIdentity,
    EmptyGoalOrClaim,
    NonPositiveBudget,
    InvalidAuthorityEntries,
    ReplayArtifactsMismatch,
    EmptyReplayPolicy,
    InvalidReplayChecks,
    EmptyProtectedHashes,
    ContractExists,
    SelfRequirement,
    RequirementNotFound,
    RequirementCoordinateMismatch,
    RequirementReleased,
    ContractNotFound,
    InstitutionActorRequired,
    ChallengeRequiresIssuer,
    ChallengeDuringRevision,
    NotAwaitingAdjudication,
    ChallengeCoordinateMismatch,
    InvalidChallengeEvidence,
    ExecutorChallengeNeedsSummary,
    SealedChallengeHasSummary,
    DependencyStateInconsistent,
    AlreadySettled,
    NotActiveAtRevision,
    HandoffDuringRevision,
    HandoffSpecMismatch,
    ReplayEvidenceRequired,
    ReplayNotConfigured,
    ReplayCoordinateMismatch,
    StateInconsistent,
    InvalidBlockedReport,
    PetitionRequiresExecutor,
    InvalidPetition,
    InvalidRevisionCoordinate,
    NoPendingRevision,
    RevisionDecisionMismatch,
    DecideRevisionRequiresIssuer,
    RequiredByOutstanding { dependent_id: String },
    NotDormantAtRevision,
    CannotActivate,
    TriggerNotReady,
    RequirementNotEvidenced,
    ResumeRequiresIssuer,
    ResumeCoordinateMismatch,
    PendingRevisionFence,
    InvalidEscalation,
    ReleaseRequiresIssuer,
    ReleaseCoordinateMismatch,
    NoHandoff,
    NotAwaitingVerification,
    AttestRequiresIssuer,
    AttestationCoordinateMismatch,
    AttestationExists,
    ReplayDoesNotSupportDischarge,
    ReplayCannotDoubleAsAttestation,
}

impl Rejection {
    pub const VARIANT_COUNT: usize = 59;

    pub fn class(&self) -> RejectionClass {
        use Axiom::Conservation;
        use Axiom::Defeasance;
        use Axiom::Exactness;
        use Axiom::Monopoly;
        use RejectionClass::Constitutional;
        match self {
            Self::IssueRequiresIssuer
            | Self::IssuerExecutorDistinct
            | Self::InstitutionActorRequired
            | Self::ChallengeRequiresIssuer
            | Self::PetitionRequiresExecutor
            | Self::ResumeRequiresIssuer
            | Self::ReleaseRequiresIssuer
            | Self::DecideRevisionRequiresIssuer
            | Self::AttestRequiresIssuer => Constitutional(Monopoly),
            Self::SpecHashMismatch
            | Self::ReplayArtifactsMismatch
            | Self::ContractExists
            | Self::SelfRequirement
            | Self::RequirementNotFound
            | Self::RequirementCoordinateMismatch
            | Self::RequirementReleased
            | Self::ContractNotFound
            | Self::ChallengeDuringRevision
            | Self::ChallengeCoordinateMismatch
            | Self::NotActiveAtRevision
            | Self::HandoffDuringRevision
            | Self::HandoffSpecMismatch
            | Self::ReplayCoordinateMismatch
            | Self::InvalidRevisionCoordinate
            | Self::NoPendingRevision
            | Self::RevisionDecisionMismatch
            | Self::NotDormantAtRevision
            | Self::CannotActivate
            | Self::TriggerNotReady
            | Self::ResumeCoordinateMismatch
            | Self::PendingRevisionFence
            | Self::ReleaseCoordinateMismatch
            | Self::NotAwaitingVerification
            | Self::AttestationCoordinateMismatch
            | Self::AttestationExists => Constitutional(Exactness),
            Self::AlreadySettled
            | Self::ReplayEvidenceRequired
            | Self::ReplayNotConfigured
            | Self::RequirementNotEvidenced
            | Self::RequiredByOutstanding { .. }
            | Self::NoHandoff
            | Self::ReplayDoesNotSupportDischarge
            | Self::ReplayCannotDoubleAsAttestation => Constitutional(Conservation),
            Self::NotAwaitingAdjudication
            | Self::InvalidChallengeEvidence
            | Self::ExecutorChallengeNeedsSummary
            | Self::SealedChallengeHasSummary => Constitutional(Defeasance),
            Self::EmptyIdentity
            | Self::EmptyGoalOrClaim
            | Self::NonPositiveBudget
            | Self::InvalidAuthorityEntries
            | Self::EmptyReplayPolicy
            | Self::InvalidReplayChecks
            | Self::EmptyProtectedHashes
            | Self::InvalidBlockedReport
            | Self::InvalidPetition
            | Self::InvalidEscalation => RejectionClass::WellFormedness,
            Self::DependencyStateInconsistent | Self::StateInconsistent => {
                RejectionClass::FailClosed
            }
        }
    }

    pub fn reason(&self) -> String {
        self.to_string()
    }
}

impl fmt::Display for Rejection {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let reason = match self {
            Self::IssueRequiresIssuer => "only the issuer may issue the contract",
            Self::IssuerExecutorDistinct => "issuer and executor must be distinct",
            Self::SpecHashMismatch => "specification hash does not match",
            Self::EmptyIdentity => "contract identity and scope must be non-empty",
            Self::EmptyGoalOrClaim => "contract goal and evidence claim must be non-empty",
            Self::NonPositiveBudget => "contract budget and attempt limits must be positive",
            Self::InvalidAuthorityEntries => {
                "contract authority entries must be unique and non-empty"
            }
            Self::ReplayArtifactsMismatch => "replay artifacts must match contract artifacts",
            Self::EmptyReplayPolicy => "replay policy must not be empty",
            Self::InvalidReplayChecks => "replay checks are invalid",
            Self::EmptyProtectedHashes => "protected replay hashes must be non-empty",
            Self::ContractExists => "contract already exists",
            Self::SelfRequirement => "contract cannot require itself",
            Self::RequirementNotFound => "required contract not found",
            Self::RequirementCoordinateMismatch => "required contract coordinate does not match",
            Self::RequirementReleased => "required contract was released",
            Self::ContractNotFound => "contract not found",
            Self::InstitutionActorRequired => "institution command requires institution actor",
            Self::ChallengeRequiresIssuer => "only the issuer may challenge verification",
            Self::ChallengeDuringRevision => {
                "verification cannot be challenged while a revision is pending"
            }
            Self::NotAwaitingAdjudication => "contract is not awaiting adjudication",
            Self::ChallengeCoordinateMismatch => "challenge coordinate does not match",
            Self::InvalidChallengeEvidence => "challenge evidence is invalid",
            Self::ExecutorChallengeNeedsSummary => {
                "executor-visible challenge requires a summary"
            }
            Self::SealedChallengeHasSummary => "sealed challenge cannot include a summary",
            Self::DependencyStateInconsistent => "contract dependency state is inconsistent",
            Self::AlreadySettled => "contract is already settled",
            Self::NotActiveAtRevision => "contract is not active at this revision",
            Self::HandoffDuringRevision => "handoff is blocked while a revision is pending",
            Self::HandoffSpecMismatch => "handoff does not match the contract specification",
            Self::ReplayEvidenceRequired => "replay evidence is required",
            Self::ReplayNotConfigured => "replay evidence is not configured",
            Self::ReplayCoordinateMismatch => "replay coordinate does not match",
            Self::StateInconsistent => "contract state is inconsistent",
            Self::InvalidBlockedReport => "blocked report is invalid",
            Self::PetitionRequiresExecutor => "only the executor may petition for revision",
            Self::InvalidPetition => "revision petition is invalid",
            Self::InvalidRevisionCoordinate => "proposed revision coordinate is invalid",
            Self::NoPendingRevision => "no revision petition is pending",
            Self::RevisionDecisionMismatch => "revision decision coordinate does not match",
            Self::DecideRevisionRequiresIssuer => "only the issuer may decide a revision",
            Self::RequiredByOutstanding { dependent_id } => {
                return write!(
                    formatter,
                    "contract is required by outstanding contract: {dependent_id}"
                );
            }
            Self::NotDormantAtRevision => "contract is not dormant at this revision",
            Self::CannotActivate => "contract cannot activate",
            Self::TriggerNotReady => "contract trigger is not ready",
            Self::RequirementNotEvidenced => "required contract is not evidenced",
            Self::ResumeRequiresIssuer => "only the issuer may resume an escalated contract",
            Self::ResumeCoordinateMismatch => "resume coordinate does not match",
            Self::PendingRevisionFence => "contract has a pending revision",
            Self::InvalidEscalation => "escalation coordinate is invalid",
            Self::ReleaseRequiresIssuer => "only the issuer may release with a reason",
            Self::ReleaseCoordinateMismatch => "release coordinate does not match",
            Self::NoHandoff => "contract has not been handed off",
            Self::NotAwaitingVerification => "contract is not awaiting verification",
            Self::AttestRequiresIssuer => "only the issuer may attest settlement",
            Self::AttestationCoordinateMismatch => "attestation coordinate does not match",
            Self::AttestationExists => "attestation already exists",
            Self::ReplayDoesNotSupportDischarge => "replay evidence does not support discharge",
            Self::ReplayCannotDoubleAsAttestation => {
                "replay evidence does not support independent discharge"
            }
        };
        formatter.write_str(reason)
    }
}

#[cfg(test)]
#[path = "rejection_tests.rs"]
mod tests;
