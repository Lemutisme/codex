use codex_pro_contract::Digest;
use pretty_assertions::assert_eq;

use super::BlobStore;

#[test]
fn put_then_get_round_trips_and_is_content_addressed() {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = BlobStore::open(dir.path()).expect("open");
    let digest = store.put(b"hello").expect("put");
    assert_eq!(digest, Digest::of(b"hello"));
    assert_eq!(store.get(&digest).expect("get"), b"hello".to_vec());
    assert_eq!(store.put(b"hello").expect("put again"), digest);
}

#[test]
fn a_tampered_blob_is_rejected_on_read() {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = BlobStore::open(dir.path()).expect("open");
    let digest = store.put(b"original").expect("put");
    let hex = digest.to_string();
    let path = dir.path().join(&hex[..2]).join(&hex);
    std::fs::write(&path, b"tampered").expect("tamper");
    let error = store
        .get(&digest)
        .expect_err("tampered blob must not be returned");
    assert_eq!(error.kind(), std::io::ErrorKind::InvalidData);
}

#[test]
fn a_missing_blob_is_not_found() {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = BlobStore::open(dir.path()).expect("open");
    let error = store.get(&Digest::of(b"absent")).expect_err("absent blob");
    assert_eq!(error.kind(), std::io::ErrorKind::NotFound);
}
