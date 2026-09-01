use serde::Deserialize;
use serde::Serialize;
use std::path::Component;
use std::path::Path;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ArtifactPathError {
    #[error("artifact path is not a normalized relative path: {0}")]
    InvalidArtifactPath(String),
    #[error("artifact paths must be unique")]
    DuplicateArtifactPath,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ArtifactPath(String);

impl ArtifactPath {
    pub fn new(value: impl Into<String>) -> Result<Self, ArtifactPathError> {
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
            return Err(ArtifactPathError::InvalidArtifactPath(value));
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
    pub fn new(paths: impl IntoIterator<Item = ArtifactPath>) -> Result<Self, ArtifactPathError> {
        let mut paths = paths.into_iter().collect::<Vec<_>>();
        paths.sort();
        if paths.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(ArtifactPathError::DuplicateArtifactPath);
        }
        Ok(Self { paths })
    }

    pub fn paths(&self) -> &[ArtifactPath] {
        &self.paths
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SubjectCoordinate {
    pub hash: String,
    pub spec_hash: String,
    pub artifacts: Vec<ArtifactPath>,
    /// Identity of the capture policy that produced this subject. Subject
    /// exactness is only meaningful relative to its capture projection, so
    /// the projection's identity is part of the coordinate.
    pub capture_policy_hash: String,
}

#[cfg(test)]
#[path = "subject_tests.rs"]
mod tests;
