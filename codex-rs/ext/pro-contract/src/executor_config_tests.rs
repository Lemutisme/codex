use super::*;
use codex_core::config::ConfigBuilder;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn contract_authority_narrows_disabled_parent_permissions() -> anyhow::Result<()> {
    let home = tempfile::tempdir()?;
    let mut parent = ConfigBuilder::default()
        .codex_home(home.path().to_path_buf())
        .fallback_cwd(Some(home.path().to_path_buf()))
        .build()
        .await?;
    parent
        .permissions
        .replace_permission_profile_from_session_snapshot(PermissionProfileSnapshot::legacy(
            PermissionProfile::Disabled,
        ))?;

    let bounded = isolated(
        &parent,
        &[],
        &[
            "filesystem.write".to_string(),
            "process.execute".to_string(),
        ],
    )
    .map_err(anyhow::Error::msg)?;
    assert_eq!(
        bounded.config.permissions.network_sandbox_policy(),
        NetworkSandboxPolicy::Restricted
    );
    assert!(matches!(
        bounded.config.permissions.permission_profile(),
        PermissionProfile::Managed { .. }
    ));

    let networked = isolated(
        &parent,
        &[],
        &[
            "filesystem.write".to_string(),
            "process.execute".to_string(),
            "network.access".to_string(),
        ],
    )
    .map_err(anyhow::Error::msg)?;
    assert_eq!(
        networked.config.permissions.network_sandbox_policy(),
        NetworkSandboxPolicy::Enabled
    );
    Ok(())
}
