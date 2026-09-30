use codex_pro_contract::Digest;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;

/// Versioned, domain-separated digest of a typed record.
///
/// The digest covers `pro_contract/v1/{domain}\0` followed by the record's JSON encoding.
/// Records are Rust structs, so their field order — and therefore the encoding — is fixed by
/// their definition.
pub fn digest_of<T: Serialize>(domain: &str, value: &T) -> Digest {
    let mut hasher = Sha256::new();
    hasher.update(b"pro_contract/v1/");
    hasher.update(domain.as_bytes());
    hasher.update([0u8]);
    // Serializing a plain struct of strings, numbers, digests and vectors cannot fail.
    let json = serde_json::to_vec(value).unwrap_or_default();
    hasher.update(&json);
    Digest::from_bytes(hasher.finalize().into())
}

#[cfg(test)]
#[path = "hashing_tests.rs"]
mod tests;
