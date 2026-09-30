use pretty_assertions::assert_eq;

use super::workspace_view;
use crate::BlobStore;
use crate::CapturePolicy;
use crate::capture;

fn capture_tree(files: &[(&str, &[u8])]) -> (tempfile::TempDir, BlobStore, crate::Subject) {
    let ws = tempfile::tempdir().expect("ws");
    for (path, bytes) in files {
        let path = ws.path().join(path);
        std::fs::create_dir_all(path.parent().expect("parent")).expect("mkdir");
        std::fs::write(path, bytes).expect("write");
    }
    let blobs = tempfile::tempdir().expect("blobs");
    let store = BlobStore::open(blobs.path()).expect("store");
    let policy = CapturePolicy {
        version: 1,
        excluded_paths: vec![],
        max_file_bytes: 1 << 20,
        max_total_bytes: 1 << 24,
    };
    let subject = capture(ws.path(), &policy, &store).expect("capture");
    // Keep the blob directory alive with the store.
    std::mem::forget(blobs);
    (ws, store, subject)
}

#[test]
fn the_view_lists_everything_and_shows_documentation_before_sources() {
    let (_ws, store, subject) = capture_tree(&[
        ("src/main.rs", b"fn main() {}"),
        ("README.md", b"# Tool\nusage"),
        ("logo.bin", &[0, 159, 146, 150]),
    ]);
    let view = workspace_view(&subject, &store, 10_000);
    let readme = view.find("=== README.md ===").expect("readme section");
    let main = view.find("=== src/main.rs ===").expect("main section");
    assert!(readme < main, "{view}");
    assert!(view.contains("logo.bin (4 bytes)"), "{view}");
    assert!(
        !view.contains("=== logo.bin ==="),
        "binary content must not be included"
    );
}

#[test]
fn the_view_respects_its_cap_and_says_what_it_omitted() {
    let big = "line\n".repeat(10_000);
    let (_ws, store, subject) =
        capture_tree(&[("README.md", b"short"), ("src/big.rs", big.as_bytes())]);
    let view = workspace_view(&subject, &store, 2_000);
    assert!(view.len() <= 2_200, "{}", view.len());
    assert!(view.contains("omitted"), "{view}");
    assert_eq!(view.matches("=== README.md ===").count(), 1);
}
