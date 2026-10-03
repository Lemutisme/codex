//! Bounded text views of a captured subject for worker prompts.

use serde::Serialize;

use crate::BlobStore;
use crate::EntryKind;
use crate::Subject;
use crate::workers::bounded;

/// Which file contents a view spends its cap on first.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ViewOrder {
    /// Documentation, then build files, then sources: what describes the task.
    DocumentationFirst,
    /// Build files, then sources, then documentation: what implements the candidate.
    SourcesFirst,
}

/// How much of a subject a view shows and in what order; part of a worker's judgment identity.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub(crate) struct ViewPolicy {
    pub cap: usize,
    pub order: ViewOrder,
}

/// A listing of every entry followed by the contents of text files in the policy's order,
/// within its cap. A file is shown whole or named as omitted; binary files are only listed.
pub(crate) fn workspace_view(subject: &Subject, store: &BlobStore, policy: ViewPolicy) -> String {
    let ViewPolicy { cap, order } = policy;
    let mut listing = String::from("Files:\n");
    for entry in &subject.manifest.entries {
        match &entry.kind {
            EntryKind::File { len, .. } => {
                listing.push_str(&format!("{} ({len} bytes)\n", entry.path))
            }
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
            EntryKind::File { digest, .. } => {
                Some((priority(&entry.path, order), entry.path.as_str(), digest))
            }
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

#[derive(Clone, Copy)]
enum FileKind {
    Documentation,
    Build,
    Source,
    Other,
}

fn file_kind(path: &str) -> FileKind {
    let name = path.rsplit('/').next().unwrap_or(path).to_ascii_lowercase();
    if name.starts_with("readme") || path.starts_with("doc") || name.ends_with(".md") {
        FileKind::Documentation
    } else if matches!(name.as_str(), "cargo.toml" | "compile.sh" | "build.rs") {
        FileKind::Build
    } else if name.ends_with(".rs") {
        FileKind::Source
    } else {
        FileKind::Other
    }
}

/// Lower comes first; everything else always comes last.
fn priority(path: &str, order: ViewOrder) -> u8 {
    match (order, file_kind(path)) {
        (ViewOrder::DocumentationFirst, FileKind::Documentation) => 0,
        (ViewOrder::DocumentationFirst, FileKind::Build) => 1,
        (ViewOrder::DocumentationFirst, FileKind::Source) => 2,
        (ViewOrder::SourcesFirst, FileKind::Build) => 0,
        (ViewOrder::SourcesFirst, FileKind::Source) => 1,
        (ViewOrder::SourcesFirst, FileKind::Documentation) => 2,
        (_, FileKind::Other) => 3,
    }
}

#[cfg(test)]
#[path = "views_tests.rs"]
mod tests;
