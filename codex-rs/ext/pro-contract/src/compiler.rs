use codex_pro_contract::ArtifactPath;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::hash_spec;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

const MAX_BRIEF_BYTES: usize = 32 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct CompiledSpec {
    pub(crate) spec: ContractSpec,
    pub(crate) manifest_hash: String,
}

#[derive(Debug, Error)]
pub(crate) enum CompilerError {
    #[error("contract brief exceeds {MAX_BRIEF_BYTES} bytes after preserving the original request")]
    BriefTooLarge,
    #[error("Codex cannot execute delegated authority: {0}")]
    UnknownAuthority(String),
    #[error("declared artifacts must be exact paths named by the user: {0}")]
    UnnamedArtifacts(String),
    #[error("contract compiler failed: {0}")]
    Encode(String),
}

#[derive(Serialize)]
struct CompilerManifest<'a> {
    version: u32,
    adapter: &'static str,
    spec_hash: String,
    request_hash: Option<String>,
    authority: &'a [String],
    artifacts: &'a [ArtifactPath],
}

pub(crate) fn latest_user_request(items: &[ResponseItem]) -> Option<String> {
    items.iter().rev().find_map(|item| {
        let ResponseItem::Message { role, content, .. } = item else {
            return None;
        };
        if role != "user" {
            return None;
        }
        let text = content
            .iter()
            .filter_map(|item| match item {
                ContentItem::InputText { text } => Some(text.as_str()),
                ContentItem::OutputText { .. }
                | ContentItem::InputImage { .. }
                | ContentItem::InputAudio { .. } => None,
            })
            .collect::<Vec<_>>()
            .join("\n");
        (!text.is_empty()).then_some(text)
    })
}

pub(crate) fn compile_spec(
    mut spec: ContractSpec,
    request: Option<&str>,
) -> Result<CompiledSpec, CompilerError> {
    let unknown = spec
        .authority
        .iter()
        .filter(|capability| !known_authority(capability))
        .cloned()
        .collect::<Vec<_>>();
    if !unknown.is_empty() {
        return Err(CompilerError::UnknownAuthority(unknown.join(", ")));
    }
    if let Some(request) = request {
        let unnamed = spec
            .artifacts
            .paths()
            .iter()
            .filter(|artifact| !request_names_artifact(request, artifact))
            .map(codex_pro_contract::ArtifactPath::as_str)
            .collect::<Vec<_>>();
        if !unnamed.is_empty() {
            return Err(CompilerError::UnnamedArtifacts(unnamed.join(", ")));
        }
        let original = format!("Original request:\n{request}");
        if !spec.brief.contains(&original) {
            spec.brief = if spec.brief.is_empty() {
                original
            } else {
                format!("{}\n\n{original}", spec.brief)
            };
        }
    }
    if spec.brief.len() > MAX_BRIEF_BYTES {
        return Err(CompilerError::BriefTooLarge);
    }
    let spec_hash = hash_spec(&spec).map_err(|error| CompilerError::Encode(error.to_string()))?;
    let manifest = CompilerManifest {
        version: 1,
        adapter: "codex",
        spec_hash,
        request_hash: request.map(hash),
        authority: &spec.authority,
        artifacts: spec.artifacts.paths(),
    };
    let encoded =
        serde_json::to_vec(&manifest).map_err(|error| CompilerError::Encode(error.to_string()))?;
    Ok(CompiledSpec {
        spec,
        manifest_hash: hash(&encoded),
    })
}

fn known_authority(capability: &str) -> bool {
    matches!(
        capability,
        "filesystem.read" | "filesystem.write" | "process.execute" | "network.access"
    ) || capability
        .strip_prefix("tool:")
        .is_some_and(|name| !name.is_empty())
}

fn request_names_artifact(request: &str, artifact: &ArtifactPath) -> bool {
    request.contains(artifact.as_str()) || request.contains(&format!("./{}", artifact.as_str()))
}

fn hash(value: impl AsRef<[u8]>) -> String {
    format!("{:x}", Sha256::digest(value.as_ref()))
}

#[cfg(test)]
#[path = "compiler_tests.rs"]
mod tests;
