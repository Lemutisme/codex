use super::*;
use pretty_assertions::assert_eq;

#[test]
fn captures_ignored_artifact_larger_than_normal_snapshot_limit() -> anyhow::Result<()> {
    let workspace = tempfile::tempdir()?;
    let store = tempfile::tempdir()?;
    let artifact = vec![7_u8; 2 * 1024 * 1024 + 1];
    fs::write(workspace.path().join(".gitignore"), "executable\n")?;
    fs::write(workspace.path().join("executable"), &artifact)?;
    let artifacts = ArtifactSpec::new([ArtifactPath::new("executable")?])?;

    let captured =
        SubjectStore::new(store.path()).capture(workspace.path(), "spec-hash", &artifacts)?;
    let materialized = store.path().join("materialized");
    SubjectStore::new(store.path()).materialize(&captured.coordinate, &materialized)?;

    assert_eq!(
        captured,
        CapturedSubject {
            coordinate: captured.coordinate.clone(),
            entries: 2,
            bytes: artifact.len() as u64 + 11,
        }
    );
    assert_eq!(fs::read(materialized.join("executable"))?, artifact);
    Ok(())
}

#[test]
fn combines_normal_snapshot_with_forced_delivery_artifacts() -> anyhow::Result<()> {
    let workspace = tempfile::tempdir()?;
    let store = tempfile::tempdir()?;
    fs::write(
        workspace.path().join(".gitignore"),
        "executable\nignored.c\n",
    )?;
    fs::write(
        workspace.path().join("compile.sh"),
        "cc source.c -o executable\n",
    )?;
    fs::write(
        workspace.path().join("source.c"),
        "int main(void) { return 0; }\n",
    )?;
    fs::write(workspace.path().join("ignored.c"), "not delivery source\n")?;
    fs::write(workspace.path().join("executable"), "binary")?;
    let artifacts = ArtifactSpec::new([
        ArtifactPath::new("compile.sh")?,
        ArtifactPath::new("executable")?,
    ])?;

    let captured = SubjectStore::new(store.path()).capture(workspace.path(), "spec", &artifacts)?;
    let materialized = store.path().join("copy");
    SubjectStore::new(store.path()).materialize(&captured.coordinate, &materialized)?;

    assert_eq!(captured.entries, 4);
    assert_eq!(captured.bytes, 82);
    assert_eq!(
        fs::read_to_string(materialized.join("source.c"))?,
        "int main(void) { return 0; }\n"
    );
    assert_eq!(fs::read(materialized.join("executable"))?, b"binary");
    assert!(!materialized.join("ignored.c").exists());
    Ok(())
}

#[test]
fn captures_declared_directory_as_complete_subject() -> anyhow::Result<()> {
    let workspace = tempfile::tempdir()?;
    let store = tempfile::tempdir()?;
    fs::create_dir(workspace.path().join("dist"))?;
    fs::write(workspace.path().join("dist/visible"), "one")?;
    fs::write(workspace.path().join("dist/.hidden"), "two")?;
    let artifacts = ArtifactSpec::new([ArtifactPath::new("dist")?])?;

    let captured = SubjectStore::new(store.path()).capture(workspace.path(), "spec", &artifacts)?;
    let materialized = store.path().join("copy");
    SubjectStore::new(store.path()).materialize(&captured.coordinate, &materialized)?;

    assert_eq!(captured.entries, 3);
    assert_eq!(
        fs::read_to_string(materialized.join("dist/visible"))?,
        "one"
    );
    assert_eq!(
        fs::read_to_string(materialized.join("dist/.hidden"))?,
        "two"
    );
    Ok(())
}

#[test]
fn rejects_non_relative_or_non_normalized_artifact_paths() {
    for path in [
        "",
        ".",
        "../escape",
        "a/../escape",
        "a/./file",
        "a//file",
        "/absolute",
        "C:/drive",
    ] {
        assert!(ArtifactPath::new(path).is_err(), "accepted {path:?}");
    }
}
