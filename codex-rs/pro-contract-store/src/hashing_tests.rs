use codex_pro_contract::Digest;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use serde::Serialize;

use super::digest_of;

#[derive(Serialize)]
struct Record {
    name: &'static str,
    size: u64,
}

#[test]
fn digest_is_deterministic_for_the_same_record() {
    let record = Record { name: "a", size: 1 };
    assert_eq!(digest_of("record", &record), digest_of("record", &record));
}

#[test]
fn domains_separate_otherwise_identical_records() {
    let record = Record { name: "a", size: 1 };
    assert_ne!(digest_of("terms", &record), digest_of("policy", &record));
}

#[test]
fn digest_covers_the_versioned_domain_prefix_and_json() {
    let record = Record { name: "a", size: 1 };
    let mut bytes = b"pro_contract/v1/record\0".to_vec();
    bytes.extend_from_slice(br#"{"name":"a","size":1}"#);
    assert_eq!(digest_of("record", &record), Digest::of(&bytes));
}

struct Unserializable;

impl Serialize for Unserializable {
    fn serialize<S: serde::Serializer>(&self, _serializer: S) -> Result<S::Ok, S::Error> {
        Err(serde::ser::Error::custom("refused"))
    }
}

#[test]
#[should_panic(expected = "canonical JSON for test failed: refused")]
fn a_value_that_cannot_be_serialized_fails_loudly() {
    digest_of("test", &Unserializable);
}
