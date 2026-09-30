use serde::Deserialize;
use serde::Serialize;

use crate::Digest;

#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ContractId(pub String);

/// The stable responsibility owner of a contract (the human), never a worker.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct OwnerId(pub String);

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Standing {
    Outstanding,
    Discharged,
    Released,
}

/// Policy identities bound at Issue and replaced only by Revise.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Bindings {
    pub terms_hash: Digest,
    pub capture_policy_hash: Digest,
    pub evidence_policy_hash: Digest,
}

/// The artifact currently proposed, fenced by the contract generation it was proposed at.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Candidate {
    pub generation: u64,
    pub subject_hash: Digest,
}

/// The complete world coordinate a recognizing command binds.
///
/// The first seven fields must equal the contract's bindings and current candidate. The last
/// three are assertions of the authenticated verifier, recorded verbatim.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Coordinate {
    pub contract_id: ContractId,
    pub revision: u32,
    pub terms_hash: Digest,
    pub generation: u64,
    pub subject_hash: Digest,
    pub capture_policy_hash: Digest,
    pub evidence_policy_hash: Digest,
    pub environment_digest: Digest,
    pub evaluator_digest: Digest,
    pub evidence_hash: Digest,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Support {
    pub certificate: Digest,
    pub coordinate: Coordinate,
}

/// How a settling human act was obtained; recorded, never collapsed.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DecisionProvenance {
    /// The human pressed accept, reopen or release.
    Explicit,
    /// Acceptance presumed under a convention the human chose.
    Presumed {
        convention: Digest,
        classifier: Digest,
    },
    /// Any other act read from natural language.
    Interpreted { classifier: Digest },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Settlement {
    pub attestation: Digest,
    pub coordinate: Coordinate,
    pub decision: DecisionProvenance,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Contract {
    pub id: ContractId,
    pub owner: OwnerId,
    pub revision: u32,
    pub bindings: Bindings,
    pub standing: Standing,
    /// Monotonic fence; never reset.
    pub generation: u64,
    pub candidate: Option<Candidate>,
    pub support: Option<Support>,
    pub settlement: Option<Settlement>,
    /// Incremented by every accepted command.
    pub version: u64,
}
