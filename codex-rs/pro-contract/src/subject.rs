use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use tempfile::NamedTempFile;
use thiserror::Error;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ArtifactPath(String);

impl ArtifactPath {
    pub fn new(value: impl Into<String>) -> Result<Self, SubjectError> {
        let value = value.into().replace('\\', "/");
        let path = Path::new(&value);
        let has_drive_prefix = value
            .as_bytes()
            .get(1)
            .is_some_and(|separator| *separator == b':');
        let segments_are_normal = value
            .split('/')
            .all(|segment| !segment.is_empty() && segment != "." && segment != "..");
        if value.is_empty()
            || has_drive_prefix
            || path.is_absolute()
            || !segments_are_normal
            || path
                .components()
                .any(|component| !matches!(component, Component::Normal(_)))
        {
            return Err(SubjectError::InvalidArtifactPath(value));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ArtifactSpec {
    paths: Vec<ArtifactPath>,
}

impl ArtifactSpec {
    pub fn new(paths: impl IntoIterator<Item = ArtifactPath>) -> Result<Self, SubjectError> {
        let mut paths = paths.into_iter().collect::<Vec<_>>();
        paths.sort();
        if paths.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(SubjectError::DuplicateArtifactPath);
        }
        Ok(Self { paths })
    }

    pub fn paths(&self) -> &[ArtifactPath] {
        &self.paths
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CaptureLimits {
    pub max_entries: usize,
    pub max_normal_file_bytes: u64,
    pub max_total_bytes: u64,
}

impl Default for CaptureLimits {
    fn default() -> Self {
        Self {
            max_entries: 50_000,
            max_normal_file_bytes: 2 * 1024 * 1024,
            max_total_bytes: 2 * 1024 * 1024 * 1024,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SubjectCoordinate {
    pub hash: String,
    pub spec_hash: String,
    pub artifacts: Vec<ArtifactPath>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CapturedSubject {
    pub coordinate: SubjectCoordinate,
    pub entries: usize,
    pub bytes: u64,
}

#[derive(Clone, Debug)]
pub struct SubjectStore {
    root: PathBuf,
    limits: CaptureLimits,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
struct Manifest {
    version: u32,
    spec_hash: String,
    artifacts: Vec<ArtifactPath>,
    entries: Vec<ManifestEntry>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
struct ManifestEntry {
    path: String,
    kind: EntryKind,
    bytes: u64,
    sha256: Option<String>,
    executable: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum EntryKind {
    Directory,
    File,
}

#[derive(Debug, Error)]
pub enum SubjectError {
    #[error("artifact path is not a normalized relative path: {0}")]
    InvalidArtifactPath(String),
    #[error("artifact paths must be unique")]
    DuplicateArtifactPath,
    #[error("declared artifact is missing: {0}")]
    MissingArtifact(String),
    #[error("symbolic links are not supported in contract subjects: {0}")]
    SymbolicLink(String),
    #[error("artifact path is not valid Unicode: {0}")]
    NonUnicodePath(PathBuf),
    #[error("subject has more than {0} entries")]
    EntryLimit(usize),
    #[error("subject is larger than {0} bytes")]
    ByteLimit(u64),
    #[error("subject manifest hash does not match its coordinate")]
    ManifestHashMismatch,
    #[error("subject destination already exists: {0}")]
    DestinationExists(PathBuf),
    #[error("subject object is corrupt: {0}")]
    CorruptObject(String),
    #[error("workspace snapshot failed: {0}")]
    Walk(String),
    #[error("failed to encode subject manifest")]
    Manifest(#[from] serde_json::Error),
    #[error("subject I/O failed")]
    Io(#[from] std::io::Error),
}

impl SubjectStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self {
            root: root.into(),
            limits: CaptureLimits::default(),
        }
    }

    pub fn with_limits(root: impl Into<PathBuf>, limits: CaptureLimits) -> Self {
        Self {
            root: root.into(),
            limits,
        }
    }

    pub fn capture(
        &self,
        workspace: &Path,
        spec_hash: impl Into<String>,
        artifacts: &ArtifactSpec,
    ) -> Result<CapturedSubject, SubjectError> {
        let mut pending = Vec::new();
        let mut walk = ignore::WalkBuilder::new(workspace);
        walk.hidden(false)
            .parents(false)
            .git_global(false)
            .require_git(false)
            .filter_entry(|entry| entry.file_name() != ".git");
        for entry in walk.build() {
            let entry = entry.map_err(|error| SubjectError::Walk(error.to_string()))?;
            let path = entry.path();
            if path == workspace {
                continue;
            }
            let relative = relative_path(workspace, path)?;
            let metadata = fs::symlink_metadata(path)?;
            if metadata.file_type().is_symlink()
                || (metadata.is_file() && metadata.len() > self.limits.max_normal_file_bytes)
            {
                continue;
            }
            pending.push((relative, path.to_path_buf(), false));
        }
        pending.extend(
            artifacts
                .paths()
                .iter()
                .map(|path| (path.0.clone(), workspace.join(path.as_str()), true)),
        );
        let mut entries = BTreeMap::new();
        let mut total_bytes = 0_u64;
        fs::create_dir_all(self.objects_dir())?;
        fs::create_dir_all(self.subjects_dir())?;

        while let Some((relative, path, forced)) = pending.pop() {
            if entries.contains_key(&relative) {
                continue;
            }
            let metadata = match fs::symlink_metadata(&path) {
                Ok(metadata) => metadata,
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
                    return Err(SubjectError::MissingArtifact(relative));
                }
                Err(err) => return Err(err.into()),
            };
            if metadata.file_type().is_symlink() {
                if forced {
                    return Err(SubjectError::SymbolicLink(relative));
                }
                continue;
            }
            let entry = if metadata.is_dir() {
                if forced {
                    let mut children = fs::read_dir(&path)?.collect::<Result<Vec<_>, _>>()?;
                    children.sort_by_key(fs::DirEntry::file_name);
                    for child in children.into_iter().rev() {
                        let child_path = child.path();
                        let name = child
                            .file_name()
                            .into_string()
                            .map_err(|_| SubjectError::NonUnicodePath(child_path.clone()))?;
                        pending.push((format!("{relative}/{name}"), child_path, true));
                    }
                }
                ManifestEntry {
                    path: relative.clone(),
                    kind: EntryKind::Directory,
                    bytes: 0,
                    sha256: None,
                    executable: false,
                }
            } else if metadata.is_file() {
                let (sha256, bytes) = self.capture_file(&path)?;
                total_bytes = total_bytes
                    .checked_add(bytes)
                    .ok_or(SubjectError::ByteLimit(self.limits.max_total_bytes))?;
                if total_bytes > self.limits.max_total_bytes {
                    return Err(SubjectError::ByteLimit(self.limits.max_total_bytes));
                }
                ManifestEntry {
                    path: relative.clone(),
                    kind: EntryKind::File,
                    bytes,
                    sha256: Some(sha256),
                    executable: executable(&metadata),
                }
            } else {
                return Err(SubjectError::MissingArtifact(relative));
            };
            entries.insert(relative, entry);
            if entries.len() > self.limits.max_entries {
                return Err(SubjectError::EntryLimit(self.limits.max_entries));
            }
        }

        let manifest = Manifest {
            version: 1,
            spec_hash: spec_hash.into(),
            artifacts: artifacts.paths.clone(),
            entries: entries.into_values().collect(),
        };
        let encoded = serde_json::to_vec(&manifest)?;
        let hash = hex_digest(&encoded);
        let manifest_path = self.subjects_dir().join(format!("{hash}.json"));
        if !manifest_path.exists() {
            let mut temporary = NamedTempFile::new_in(self.subjects_dir())?;
            temporary.write_all(&encoded)?;
            temporary.as_file().sync_all()?;
            match temporary.persist_noclobber(&manifest_path) {
                Ok(_) => {}
                Err(err) if err.error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(err) => return Err(err.error.into()),
            }
        }
        Ok(CapturedSubject {
            coordinate: SubjectCoordinate {
                hash,
                spec_hash: manifest.spec_hash,
                artifacts: manifest.artifacts,
            },
            entries: manifest.entries.len(),
            bytes: total_bytes,
        })
    }

    pub fn materialize(
        &self,
        coordinate: &SubjectCoordinate,
        destination: &Path,
    ) -> Result<(), SubjectError> {
        if destination.exists() {
            return Err(SubjectError::DestinationExists(destination.to_path_buf()));
        }
        let encoded = fs::read(
            self.subjects_dir()
                .join(format!("{}.json", coordinate.hash)),
        )?;
        if hex_digest(&encoded) != coordinate.hash {
            return Err(SubjectError::ManifestHashMismatch);
        }
        let manifest: Manifest = serde_json::from_slice(&encoded)?;
        if manifest.spec_hash != coordinate.spec_hash || manifest.artifacts != coordinate.artifacts
        {
            return Err(SubjectError::ManifestHashMismatch);
        }
        fs::create_dir_all(destination)?;
        for entry in manifest.entries {
            let path = destination.join(&entry.path);
            match entry.kind {
                EntryKind::Directory => fs::create_dir_all(path)?,
                EntryKind::File => {
                    let hash = entry.sha256.ok_or(SubjectError::ManifestHashMismatch)?;
                    let object = self.objects_dir().join(&hash);
                    if digest_file(&object)? != hash {
                        return Err(SubjectError::CorruptObject(hash));
                    }
                    if let Some(parent) = path.parent() {
                        fs::create_dir_all(parent)?;
                    }
                    fs::copy(object, &path)?;
                    set_executable(&path, entry.executable)?;
                }
            }
        }
        Ok(())
    }

    fn capture_file(&self, path: &Path) -> Result<(String, u64), SubjectError> {
        let mut source = File::open(path)?;
        let mut temporary = NamedTempFile::new_in(self.objects_dir())?;
        let mut hasher = Sha256::new();
        let mut bytes = 0_u64;
        let mut buffer = [0_u8; 64 * 1024];
        loop {
            let read = source.read(&mut buffer)?;
            if read == 0 {
                break;
            }
            hasher.update(&buffer[..read]);
            temporary.write_all(&buffer[..read])?;
            bytes += read as u64;
        }
        temporary.as_file().sync_all()?;
        let hash = format!("{:x}", hasher.finalize());
        let object = self.objects_dir().join(&hash);
        match temporary.persist_noclobber(object) {
            Ok(_) => {}
            Err(err) if err.error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(err) => return Err(err.error.into()),
        }
        Ok((hash, bytes))
    }

    fn objects_dir(&self) -> PathBuf {
        self.root.join("objects")
    }

    fn subjects_dir(&self) -> PathBuf {
        self.root.join("subjects")
    }
}

fn hex_digest(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

fn relative_path(root: &Path, path: &Path) -> Result<String, SubjectError> {
    let relative = path
        .strip_prefix(root)
        .map_err(|error| SubjectError::Walk(error.to_string()))?;
    relative
        .to_str()
        .map(|path| path.replace('\\', "/"))
        .ok_or_else(|| SubjectError::NonUnicodePath(path.to_path_buf()))
}

fn digest_file(path: &Path) -> std::io::Result<String> {
    let mut source = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = source.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(unix)]
fn executable(metadata: &fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;
    metadata.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn executable(_metadata: &fs::Metadata) -> bool {
    false
}

#[cfg(unix)]
fn set_executable(path: &Path, executable: bool) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path)?.permissions();
    let mode = permissions.mode();
    permissions.set_mode(if executable {
        mode | 0o111
    } else {
        mode & !0o111
    });
    fs::set_permissions(path, permissions)
}

#[cfg(not(unix))]
fn set_executable(_path: &Path, _executable: bool) -> std::io::Result<()> {
    Ok(())
}

#[cfg(test)]
#[path = "subject_tests.rs"]
mod tests;
