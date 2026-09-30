use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::CaptureError;
use super::EntryKind;
use super::capture;
use super::materialize;
use crate::BlobStore;
use crate::CapturePolicy;

fn policy() -> CapturePolicy {
    CapturePolicy {
        version: 1,
        excluded_paths: vec![
            ".git".to_string(),
            "target".to_string(),
            "executable".to_string(),
        ],
        max_file_bytes: 1024,
        max_total_bytes: 64 * 1024,
    }
}

fn write(root: &Path, path: &str, bytes: &[u8]) {
    let path = root.join(path);
    std::fs::create_dir_all(path.parent().expect("parent")).expect("mkdir");
    std::fs::write(path, bytes).expect("write");
}

fn paths(root: &Path, store: &BlobStore) -> Vec<String> {
    capture(root, &policy(), store)
        .expect("capture")
        .manifest
        .entries
        .into_iter()
        .map(|entry| entry.path)
        .collect()
}

#[test]
fn excluded_paths_are_never_captured() {
    let ws = tempfile::tempdir().expect("ws");
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    write(ws.path(), "src/main.rs", b"fn main() {}");
    write(ws.path(), ".git/HEAD", b"ref");
    write(ws.path(), "target/debug/app", b"bin");
    write(ws.path(), "executable", b"reference");
    write(ws.path(), "targets.txt", b"not the target dir");
    assert_eq!(
        paths(ws.path(), &store),
        vec!["src/main.rs".to_string(), "targets.txt".to_string()]
    );
}

#[test]
fn gitignore_does_not_hide_files() {
    let ws = tempfile::tempdir().expect("ws");
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    write(ws.path(), ".gitignore", b"secret.rs\n");
    write(ws.path(), "secret.rs", b"hidden?");
    assert_eq!(
        paths(ws.path(), &store),
        vec![".gitignore".to_string(), "secret.rs".to_string()]
    );
}

#[test]
fn symlinks_are_recorded_not_followed() {
    let ws = tempfile::tempdir().expect("ws");
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    write(ws.path(), "real.txt", b"data");
    std::os::unix::fs::symlink("real.txt", ws.path().join("link.txt")).expect("symlink");
    let subject = capture(ws.path(), &policy(), &store).expect("capture");
    let link = subject
        .manifest
        .entries
        .iter()
        .find(|entry| entry.path == "link.txt")
        .expect("link entry");
    assert_eq!(
        link.kind,
        EntryKind::Symlink {
            target: "real.txt".to_string()
        }
    );
}

#[test]
fn a_symlink_escaping_the_workspace_rejects_the_capture() {
    let ws = tempfile::tempdir().expect("ws");
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    std::os::unix::fs::symlink("../../etc/passwd", ws.path().join("escape")).expect("symlink");
    assert!(matches!(
        capture(ws.path(), &policy(), &store),
        Err(CaptureError::SymlinkEscapes { .. })
    ));
}

#[test]
fn an_oversized_file_rejects_the_capture() {
    let ws = tempfile::tempdir().expect("ws");
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    write(ws.path(), "big.bin", &[0u8; 2048]);
    assert!(matches!(
        capture(ws.path(), &policy(), &store),
        Err(CaptureError::TooLarge { .. })
    ));
}

#[test]
fn identical_trees_hash_identically_and_one_byte_changes_the_subject() {
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    let a = tempfile::tempdir().expect("a");
    let b = tempfile::tempdir().expect("b");
    for root in [a.path(), b.path()] {
        write(root, "src/lib.rs", b"pub fn f() {}");
        write(root, "README.md", b"doc");
    }
    let first = capture(a.path(), &policy(), &store).expect("capture a");
    assert_eq!(
        first.subject_hash,
        capture(b.path(), &policy(), &store)
            .expect("capture b")
            .subject_hash
    );
    write(b.path(), "README.md", b"doc!");
    assert_ne!(
        first.subject_hash,
        capture(b.path(), &policy(), &store)
            .expect("capture b again")
            .subject_hash
    );
}

#[test]
fn materialize_round_trips_bytes_modes_and_links() {
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    let ws = tempfile::tempdir().expect("ws");
    write(ws.path(), "compile.sh", b"#!/bin/sh\necho build\n");
    std::fs::set_permissions(
        ws.path().join("compile.sh"),
        std::fs::Permissions::from_mode(0o755),
    )
    .expect("chmod");
    write(ws.path(), "src/main.rs", b"fn main() {}");
    std::os::unix::fs::symlink("src/main.rs", ws.path().join("main.rs")).expect("symlink");
    let subject = capture(ws.path(), &policy(), &store).expect("capture");
    let out = tempfile::tempdir().expect("out");
    materialize(&subject, &store, out.path()).expect("materialize");
    assert_eq!(
        capture(out.path(), &policy(), &store).expect("recapture"),
        subject
    );
    let mode = std::fs::metadata(out.path().join("compile.sh"))
        .expect("metadata")
        .permissions()
        .mode();
    assert_eq!(mode & 0o111, 0o111);
}
