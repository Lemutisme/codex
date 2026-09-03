use codex_core::config::Config;
use codex_protocol::intersect_effective_permission_profiles;
use codex_protocol::models::BaseInstructionsProvenance;
use codex_protocol::models::PermissionProfile;
use codex_protocol::models::PermissionProfileSnapshot;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_protocol::protocol::EnvironmentConfigState;
use codex_protocol::protocol::TurnEnvironmentSelection;
use codex_utils_absolute_path::AbsolutePathBuf;

pub(crate) const CONTRACT_EXECUTOR_INSTRUCTIONS: &str = "You are Codex, the bounded executor for one admitted ProContract. Work only on the supplied task and within the visible authority. Inspect the workspace, use tools to produce exact artifacts, and preserve useful evidence across edits. Create fresh uniquely named scratch paths instead of deleting existing paths. When the task permits observation, acquire bounded discriminating evidence before a costly implementation commitment; when visible, contract_probe_batch can observe a reference without a candidate. Choose implementation primitives faithful to required runtime semantics, then reuse observed request coordinates for candidate comparisons and preserve concrete residuals across edits. Use trusted frontier cost to avoid repeating unchanged candidate/request coordinates. Delay, request novelty, and byte equality are not semantic progress. Treat differences as coordinate-bound facts, not demands to erase legitimate identity or environment differences. The execution policy guides search but cannot settle the Contract. A runnable candidate or passing replay is not completion: use the Contract tools to report ready, blocked, or a needed revision; only the Principal can settle.";

pub(crate) struct IsolatedExecutor {
    pub(crate) config: Config,
    pub(crate) environments: Vec<TurnEnvironmentSelection>,
}

pub(crate) fn isolated(
    parent: &Config,
    parent_environments: &[TurnEnvironmentSelection],
    authority: &[String],
) -> Result<IsolatedExecutor, String> {
    let mut config = parent.clone();
    config.base_instructions = Some(CONTRACT_EXECUTOR_INSTRUCTIONS.to_string());
    config.base_instructions_provenance = Some(BaseInstructionsProvenance::Custom);
    config.personality = None;

    config.include_apps_instructions = false;
    config.include_collaboration_mode_instructions = false;
    config.include_skill_instructions = false;
    config.orchestrator_skills_enabled = false;
    config.orchestrator_mcp_enabled = false;
    config.agents_enabled = false;
    config.memories.use_memories = false;
    config.memories.dedicated_tools = false;

    let requested = requested_permissions(authority);
    let bounded = intersect_permissions(
        parent.permissions.effective_permission_profile(),
        requested.clone(),
        &parent.workspace_roots,
        &parent.cwd,
    )?;
    config
        .permissions
        .replace_permission_profile_from_session_snapshot(PermissionProfileSnapshot::legacy(
            bounded,
        ))
        .map_err(|error| format!("cannot restrict executor permissions: {error}"))?;
    if !authority.iter().any(|value| value == "network.access") {
        config.permissions.network = None;
    }

    let mut environments = parent_environments.to_vec();
    for selection in &mut environments {
        match &mut selection.config {
            EnvironmentConfigState::FromThread => {}
            EnvironmentConfigState::Ready(environment) => {
                let cwd = selection
                    .cwd
                    .to_abs_path()
                    .map_err(|error| format!("invalid executor cwd: {error}"))?;
                let roots = environment
                    .workspace_roots
                    .iter()
                    .map(codex_utils_path_uri::PathUri::to_abs_path)
                    .collect::<Result<Vec<_>, _>>()
                    .map_err(|error| format!("invalid executor workspace root: {error}"))?;
                let bounded = intersect_permissions(
                    environment.permission_profile.permission_profile().clone(),
                    requested.clone(),
                    &roots,
                    &cwd,
                )?;
                environment.permission_profile = PermissionProfileSnapshot::legacy(bounded);
                if !authority.iter().any(|value| value == "network.access") {
                    environment.network_policy = None;
                }
            }
            EnvironmentConfigState::Pending | EnvironmentConfigState::Failed(_) => {
                return Err(format!(
                    "executor environment `{}` has no resolved permissions",
                    selection.environment_id
                ));
            }
        }
    }
    Ok(IsolatedExecutor {
        config,
        environments,
    })
}

fn requested_permissions(authority: &[String]) -> PermissionProfile {
    let network = if authority.iter().any(|value| value == "network.access") {
        NetworkSandboxPolicy::Enabled
    } else {
        NetworkSandboxPolicy::Restricted
    };
    if authority.iter().any(|value| value == "filesystem.write") {
        PermissionProfile::workspace_write_with(
            &[],
            network,
            /*exclude_tmpdir_env_var*/ false,
            /*exclude_slash_tmp*/ false,
        )
    } else {
        PermissionProfile::from_runtime_permissions(&FileSystemSandboxPolicy::read_only(), network)
    }
}

fn intersect_permissions(
    authority: PermissionProfile,
    requested: PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    cwd: &AbsolutePathBuf,
) -> Result<PermissionProfile, String> {
    let authority = authority.materialize_project_roots_with_workspace_roots(workspace_roots);
    let requested = requested.materialize_project_roots_with_workspace_roots(workspace_roots);
    intersect_effective_permission_profiles(&authority, &requested, cwd.as_path())
        .map_err(|error| format!("cannot intersect executor permissions: {error}"))
}

#[cfg(test)]
#[path = "executor_config_tests.rs"]
mod tests;
