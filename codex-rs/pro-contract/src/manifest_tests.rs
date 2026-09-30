use pretty_assertions::assert_eq;

/// The kernel stays pure: its only runtime dependencies are serde, sha2 and thiserror.
#[test]
fn kernel_dependencies_are_exactly_serde_sha2_and_thiserror() {
    let manifest = include_str!("../Cargo.toml");
    let mut in_dependencies = false;
    let mut dependencies = Vec::new();
    for line in manifest.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_dependencies = line == "[dependencies]";
            continue;
        }
        if in_dependencies && let Some((name, _)) = line.split_once('=') {
            dependencies.push(name.trim().to_string());
        }
    }
    assert_eq!(dependencies, vec!["serde", "sha2", "thiserror"]);
}
