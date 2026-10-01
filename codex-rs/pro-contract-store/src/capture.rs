use std::io;
use std::path::Path;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::BlobStore;
use crate::CapturePolicy;
use crate::digest_of;

/// Format version of [`Manifest`].
const MANIFEST_VERSION: u32 = 1;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum EntryKind {
    File {
        executable: bool,
        len: u64,
        digest: Digest,
    },
    /// The link target as content; links are never followed.
    Symlink { target: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Entry {
    /// Path relative to the workspace root, `/`-separated.
    pub path: String,
    pub kind: EntryKind,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Manifest {
    pub version: u32,
    /// Sorted by path.
    pub entries: Vec<Entry>,
}

/// A constructed, immutable artifact. Support is a statement about this artifact.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Subject {
    pub manifest: Manifest,
    pub subject_hash: Digest,
}

#[derive(Debug, thiserror::Error)]
pub enum CaptureError {
    #[error("subject record is corrupt: {0}")]
    Corrupt(String),
    #[error("capture i/o error at {path}: {source}")]
    Io { path: String, source: io::Error },
    #[error("{path} is {len} bytes, over the per-file cap")]
    TooLarge { path: String, len: u64 },
    #[error("the workspace exceeds the total size cap")]
    TotalTooLarge,
    #[error("{path} changed while it was being captured")]
    Unstable { path: String },
    #[error("{path} is not valid UTF-8")]
    NonUtf8Path { path: String },
    #[error("symlink {path} points outside the workspace")]
    SymlinkEscapes { path: String },
}

/// Captures the workspace under `root` into `store`, then re-reads it to confirm that the
/// constructed artifact still matches the workspace.
pub fn capture(
    root: &Path,
    policy: &CapturePolicy,
    store: &BlobStore,
) -> Result<Subject, CaptureError> {
    let stored = scan(root, policy, Some(store))?;
    let verified = scan(root, policy, /*store*/ None)?;
    if stored != verified {
        let path = stored
            .iter()
            .zip(verified.iter())
            .find(|(left, right)| left != right)
            .map(|(left, _)| left.path.clone())
            .or_else(|| stored.last().map(|entry| entry.path.clone()))
            .unwrap_or_default();
        return Err(CaptureError::Unstable { path });
    }
    let manifest = Manifest {
        version: MANIFEST_VERSION,
        entries: stored,
    };
    let subject_hash = digest_of("subject_manifest", &manifest);
    Ok(Subject {
        manifest,
        subject_hash,
    })
}

/// Stores the subject's canonical manifest as a blob, so that the subject can later be resolved
/// from its hash alone.
pub fn persist_manifest(subject: &Subject, store: &BlobStore) -> Result<Digest, CaptureError> {
    let bytes = serde_json::to_vec(&subject.manifest)
        .map_err(|error| CaptureError::Corrupt(error.to_string()))?;
    store.put(&bytes).map_err(io_error("manifest"))
}

/// Reads a persisted manifest back and checks that it is exactly the claimed subject.
pub fn load_subject(
    store: &BlobStore,
    manifest: &Digest,
    subject_hash: &Digest,
) -> Result<Subject, CaptureError> {
    let bytes = store.get(manifest).map_err(io_error("manifest"))?;
    let manifest: Manifest =
        serde_json::from_slice(&bytes).map_err(|error| CaptureError::Corrupt(error.to_string()))?;
    let actual = digest_of("subject_manifest", &manifest);
    if actual != *subject_hash {
        return Err(CaptureError::Corrupt(format!(
            "manifest describes subject {actual}, not {subject_hash}"
        )));
    }
    Ok(Subject {
        manifest,
        subject_hash: *subject_hash,
    })
}

fn io_error(path: &str) -> impl FnOnce(io::Error) -> CaptureError + '_ {
    move |source| CaptureError::Io {
        path: path.to_string(),
        source,
    }
}

fn excluded(policy: &CapturePolicy, path: &str) -> bool {
    policy.excluded_paths.iter().any(|excluded| {
        path == excluded
            || path
                .strip_prefix(excluded.as_str())
                .is_some_and(|rest| rest.starts_with('/'))
    })
}

/// Whether a relative link target resolves outside the workspace root.
fn escapes(link_path: &str, target: &str) -> bool {
    if target.starts_with('/') {
        return true;
    }
    let mut depth = link_path.matches('/').count() as i64;
    for component in target.split('/') {
        match component {
            "" | "." => {}
            ".." => {
                depth -= 1;
                if depth < 0 {
                    return true;
                }
            }
            _ => depth += 1,
        }
    }
    false
}

/// Walks the workspace in sorted order. With a store, file contents are stored; without one,
/// they are only hashed (the verification pass).
fn scan(
    root: &Path,
    policy: &CapturePolicy,
    store: Option<&BlobStore>,
) -> Result<Vec<Entry>, CaptureError> {
    let mut entries = Vec::new();
    let mut total = 0u64;
    let mut pending = vec![String::new()];
    while let Some(dir) = pending.pop() {
        let dir_path = if dir.is_empty() {
            root.to_path_buf()
        } else {
            root.join(&dir)
        };
        let mut children = std::fs::read_dir(&dir_path)
            .and_then(std::iter::Iterator::collect::<Result<Vec<_>, _>>)
            .map_err(io_error(&dir))?;
        children.sort_by_key(std::fs::DirEntry::file_name);
        for child in children {
            let name =
                child
                    .file_name()
                    .into_string()
                    .map_err(|name| CaptureError::NonUtf8Path {
                        path: name.to_string_lossy().into_owned(),
                    })?;
            let path = if dir.is_empty() {
                name
            } else {
                format!("{dir}/{name}")
            };
            if excluded(policy, &path) {
                continue;
            }
            let metadata = std::fs::symlink_metadata(child.path()).map_err(io_error(&path))?;
            let file_type = metadata.file_type();
            if file_type.is_symlink() {
                let target = std::fs::read_link(child.path())
                    .map_err(io_error(&path))?
                    .into_os_string()
                    .into_string()
                    .map_err(|_| CaptureError::NonUtf8Path { path: path.clone() })?;
                if escapes(&path, &target) {
                    return Err(CaptureError::SymlinkEscapes { path });
                }
                entries.push(Entry {
                    path,
                    kind: EntryKind::Symlink { target },
                });
            } else if file_type.is_dir() {
                pending.push(path);
            } else if file_type.is_file() {
                let len = metadata.len();
                if len > policy.max_file_bytes {
                    return Err(CaptureError::TooLarge { path, len });
                }
                total += len;
                if total > policy.max_total_bytes {
                    return Err(CaptureError::TotalTooLarge);
                }
                let bytes = std::fs::read(child.path()).map_err(io_error(&path))?;
                if bytes.len() as u64 != len {
                    return Err(CaptureError::Unstable { path });
                }
                let digest = match store {
                    Some(store) => store.put(&bytes).map_err(io_error(&path))?,
                    None => Digest::of(&bytes),
                };
                entries.push(Entry {
                    path,
                    kind: EntryKind::File {
                        executable: is_executable(&metadata),
                        len,
                        digest,
                    },
                });
            }
            // Sockets, FIFOs and devices hold no source content and are not captured.
        }
    }
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(entries)
}

#[cfg(unix)]
fn is_executable(metadata: &std::fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_executable(_metadata: &std::fs::Metadata) -> bool {
    false
}

/// Writes the subject's entries under `dest`, which must be empty.
pub fn materialize(subject: &Subject, store: &BlobStore, dest: &Path) -> Result<(), CaptureError> {
    for entry in &subject.manifest.entries {
        let path = dest.join(&entry.path);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(io_error(&entry.path))?;
        }
        match &entry.kind {
            EntryKind::File {
                executable, digest, ..
            } => {
                let bytes = store.get(digest).map_err(io_error(&entry.path))?;
                std::fs::write(&path, bytes).map_err(io_error(&entry.path))?;
                set_executable(&path, *executable).map_err(io_error(&entry.path))?;
            }
            EntryKind::Symlink { target } => {
                make_symlink(target, &path).map_err(io_error(&entry.path))?;
            }
        }
    }
    Ok(())
}

#[cfg(unix)]
fn set_executable(path: &Path, executable: bool) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mode = if executable { 0o755 } else { 0o644 };
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode))
}

#[cfg(not(unix))]
fn set_executable(_path: &Path, _executable: bool) -> io::Result<()> {
    Ok(())
}

#[cfg(unix)]
fn make_symlink(target: &str, path: &Path) -> io::Result<()> {
    std::os::unix::fs::symlink(target, path)
}

#[cfg(not(unix))]
fn make_symlink(_target: &str, _path: &Path) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "symlink materialization requires unix",
    ))
}

#[cfg(all(test, unix))]
#[path = "capture_tests.rs"]
mod tests;
