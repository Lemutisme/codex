//! Bounded text views of a captured subject for worker prompts.

use crate::BlobStore;
use crate::EntryKind;
use crate::Subject;
use crate::workers::bounded;

/// A listing of every entry followed by the contents of text files, documentation first, then
/// build files and sources, within `cap` bytes. Binary files are listed but never included.
pub(crate) fn workspace_view(subject: &Subject, store: &BlobStore, cap: usize) -> String {
    let mut listing = String::from("Files:\n");
    for entry in &subject.manifest.entries {
        match &entry.kind {
            EntryKind::File { len, .. } => listing.push_str(&format!("{} ({len} bytes)\n", entry.path)),
            EntryKind::Symlink { target } => {
                listing.push_str(&format!("{} -> {target}\n", entry.path));
            }
        }
    }
    let mut view = bounded(&listing, cap / 4);
    let mut files: Vec<_> = subject
        .manifest
        .entries
        .iter()
        .filter_map(|entry| match &entry.kind {
            EntryKind::File { digest, .. } => Some((priority(&entry.path), entry.path.as_str(), digest)),
            EntryKind::Symlink { .. } => None,
        })
        .collect();
    files.sort();
    let mut omitted = Vec::new();
    for (_, path, digest) in files {
        let Ok(bytes) = store.get(digest) else {
            omitted.push(path);
            continue;
        };
        let Ok(text) = String::from_utf8(bytes) else {
            continue;
        };
        let section = format!("\n=== {path} ===\n{text}\n");
        if view.len() + section.len() > cap {
            omitted.push(path);
            continue;
        }
        view.push_str(&section);
    }
    if !omitted.is_empty() {
        let note = format!("\n[contents omitted for size: {}]\n", omitted.join(", "));
        view.push_str(&bounded(&note, cap.saturating_sub(view.len()).max(64)));
    }
    view
}

/// Documentation first, then build files, then sources, then everything else.
fn priority(path: &str) -> u8 {
    let name = path.rsplit('/').next().unwrap_or(path).to_ascii_lowercase();
    if name.starts_with("readme") || path.starts_with("doc") || name.ends_with(".md") {
        0
    } else if matches!(name.as_str(), "cargo.toml" | "compile.sh" | "build.rs") {
        1
    } else if name.ends_with(".rs") {
        2
    } else {
        3
    }
}

#[cfg(test)]
#[path = "views_tests.rs"]
mod tests;
