use super::*;
use Axiom::Conservation;
use Axiom::Defeasance;
use Axiom::Exactness;
use Axiom::Monopoly;
use RejectionClass::Constitutional;
use RejectionClass::FailClosed;
use RejectionClass::WellFormedness;

#[test]
fn every_rejection_keeps_its_audited_reason_and_maps_to_one_class() {
    let golden: Vec<(Rejection, &str, RejectionClass)> = vec![
        (
            Rejection::IssueRequiresIssuer,
            "only the issuer may issue the contract",
            Constitutional(Monopoly),
        ),
        (
            Rejection::IssuerExecutorDistinct,
            "issuer and executor must be distinct",
            Constitutional(Monopoly),
        ),
        (
            Rejection::SpecHashMismatch,
            "specification hash does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::EmptyIdentity,
            "contract identity and scope must be non-empty",
            WellFormedness,
        ),
        (
            Rejection::EmptyGoalOrClaim,
            "contract goal and evidence claim must be non-empty",
            WellFormedness,
        ),
        (
            Rejection::NonPositiveBudget,
            "contract budget and attempt limits must be positive",
            WellFormedness,
        ),
        (
            Rejection::InvalidAuthorityEntries,
            "contract authority entries must be unique and non-empty",
            WellFormedness,
        ),
        (
            Rejection::ReplayArtifactsMismatch,
            "replay artifacts must match contract artifacts",
            Constitutional(Exactness),
        ),
        (
            Rejection::EmptyReplayPolicy,
            "replay policy must not be empty",
            WellFormedness,
        ),
        (
            Rejection::InvalidReplayChecks,
            "replay checks are invalid",
            WellFormedness,
        ),
        (
            Rejection::EmptyProtectedHashes,
            "protected replay hashes must be non-empty",
            WellFormedness,
        ),
        (
            Rejection::ContractExists,
            "contract already exists",
            Constitutional(Exactness),
        ),
        (
            Rejection::SelfRequirement,
            "contract cannot require itself",
            Constitutional(Exactness),
        ),
        (
            Rejection::RequirementNotFound,
            "required contract not found",
            Constitutional(Exactness),
        ),
        (
            Rejection::RequirementCoordinateMismatch,
            "required contract coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::RequirementReleased,
            "required contract was released",
            Constitutional(Exactness),
        ),
        (
            Rejection::ContractNotFound,
            "contract not found",
            Constitutional(Exactness),
        ),
        (
            Rejection::InstitutionActorRequired,
            "institution command requires institution actor",
            Constitutional(Monopoly),
        ),
        (
            Rejection::ChallengeRequiresIssuer,
            "only the issuer may challenge verification",
            Constitutional(Monopoly),
        ),
        (
            Rejection::ChallengeDuringRevision,
            "verification cannot be challenged while a revision is pending",
            Constitutional(Exactness),
        ),
        (
            Rejection::NotAwaitingAdjudication,
            "contract is not awaiting adjudication",
            Constitutional(Defeasance),
        ),
        (
            Rejection::ChallengeCoordinateMismatch,
            "challenge coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::InvalidChallengeEvidence,
            "challenge evidence is invalid",
            Constitutional(Defeasance),
        ),
        (
            Rejection::ExecutorChallengeNeedsSummary,
            "executor-visible challenge requires a summary",
            Constitutional(Defeasance),
        ),
        (
            Rejection::SealedChallengeHasSummary,
            "sealed challenge cannot include a summary",
            Constitutional(Defeasance),
        ),
        (
            Rejection::DependencyStateInconsistent,
            "contract dependency state is inconsistent",
            FailClosed,
        ),
        (
            Rejection::AlreadySettled,
            "contract is already settled",
            Constitutional(Conservation),
        ),
        (
            Rejection::NotActiveAtRevision,
            "contract is not active at this revision",
            Constitutional(Exactness),
        ),
        (
            Rejection::HandoffDuringRevision,
            "handoff is blocked while a revision is pending",
            Constitutional(Exactness),
        ),
        (
            Rejection::HandoffSpecMismatch,
            "handoff does not match the contract specification",
            Constitutional(Exactness),
        ),
        (
            Rejection::ReplayEvidenceRequired,
            "replay evidence is required",
            Constitutional(Conservation),
        ),
        (
            Rejection::ReplayNotConfigured,
            "replay evidence is not configured",
            Constitutional(Conservation),
        ),
        (
            Rejection::ReplayCoordinateMismatch,
            "replay coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::StateInconsistent,
            "contract state is inconsistent",
            FailClosed,
        ),
        (
            Rejection::InvalidBlockedReport,
            "blocked report is invalid",
            WellFormedness,
        ),
        (
            Rejection::PetitionRequiresExecutor,
            "only the executor may petition for revision",
            Constitutional(Monopoly),
        ),
        (
            Rejection::InvalidPetition,
            "revision petition is invalid",
            WellFormedness,
        ),
        (
            Rejection::InvalidRevisionCoordinate,
            "proposed revision coordinate is invalid",
            Constitutional(Exactness),
        ),
        (
            Rejection::NoPendingRevision,
            "no revision petition is pending",
            Constitutional(Exactness),
        ),
        (
            Rejection::RevisionDecisionMismatch,
            "revision decision coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::DecideRevisionRequiresIssuer,
            "only the issuer may decide a revision",
            Constitutional(Monopoly),
        ),
        (
            Rejection::RequiredByOutstanding {
                dependent_id: "dependent".to_string(),
            },
            "contract is required by outstanding contract: dependent",
            Constitutional(Conservation),
        ),
        (
            Rejection::NotDormantAtRevision,
            "contract is not dormant at this revision",
            Constitutional(Exactness),
        ),
        (
            Rejection::CannotActivate,
            "contract cannot activate",
            Constitutional(Exactness),
        ),
        (
            Rejection::TriggerNotReady,
            "contract trigger is not ready",
            Constitutional(Exactness),
        ),
        (
            Rejection::RequirementNotEvidenced,
            "required contract is not evidenced",
            Constitutional(Conservation),
        ),
        (
            Rejection::ResumeRequiresIssuer,
            "only the issuer may resume an escalated contract",
            Constitutional(Monopoly),
        ),
        (
            Rejection::ResumeCoordinateMismatch,
            "resume coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::PendingRevisionFence,
            "contract has a pending revision",
            Constitutional(Exactness),
        ),
        (
            Rejection::InvalidEscalation,
            "escalation coordinate is invalid",
            WellFormedness,
        ),
        (
            Rejection::ReleaseRequiresIssuer,
            "only the issuer may release with a reason",
            Constitutional(Monopoly),
        ),
        (
            Rejection::ReleaseCoordinateMismatch,
            "release coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::NoHandoff,
            "contract has not been handed off",
            Constitutional(Conservation),
        ),
        (
            Rejection::NotAwaitingVerification,
            "contract is not awaiting verification",
            Constitutional(Exactness),
        ),
        (
            Rejection::AttestRequiresIssuer,
            "only the issuer may attest settlement",
            Constitutional(Monopoly),
        ),
        (
            Rejection::AttestationCoordinateMismatch,
            "attestation coordinate does not match",
            Constitutional(Exactness),
        ),
        (
            Rejection::AttestationExists,
            "attestation already exists",
            Constitutional(Exactness),
        ),
        (
            Rejection::ReplayDoesNotSupportDischarge,
            "replay evidence does not support discharge",
            Constitutional(Conservation),
        ),
        (
            Rejection::ReplayCannotDoubleAsAttestation,
            "replay evidence does not support independent discharge",
            Constitutional(Conservation),
        ),
    ];
    assert_eq!(golden.len(), Rejection::VARIANT_COUNT);
    let mut seen = std::collections::BTreeSet::new();
    for (rejection, reason, class) in golden {
        assert_eq!(rejection.reason(), reason, "reason drift for {rejection:?}");
        assert_eq!(rejection.class(), class, "class drift for {rejection:?}");
        assert!(seen.insert(reason), "duplicate audited reason: {reason}");
    }
}
