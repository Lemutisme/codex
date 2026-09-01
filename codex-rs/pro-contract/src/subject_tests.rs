use super::*;

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
