use pretty_assertions::assert_eq;

use super::Policies;

#[test]
fn a_bundle_overrides_what_it_names_and_keeps_the_rest() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    std::fs::write(dir.path().join("reviewer.md"), "Review strictly.")?;

    let loaded = Policies::load(dir.path())?;

    assert_eq!(
        loaded,
        Policies {
            reviewer: "Review strictly.".to_string(),
            ..Policies::default()
        }
    );
    Ok(())
}

#[test]
fn the_built_in_texts_are_the_shipped_bundle_files() {
    let defaults = Policies::default();
    assert!(defaults.drafter.starts_with("You are the drafting worker"));
    assert!(defaults.prober.starts_with("You are the probing worker"));
    assert!(defaults.reviewer.starts_with("Independently assess"));
}

#[test]
fn strategy_changes_context_without_changing_worker_protocols() -> std::io::Result<()> {
    let dir = tempfile::tempdir()?;
    std::fs::write(
        dir.path().join("work_method.md"),
        "Keep a proof dependency graph.",
    )?;
    let loaded = Policies::load(dir.path())?;
    assert_eq!(loaded.work_method, "Keep a proof dependency graph.");
    assert_eq!(loaded.drafter, Policies::default().drafter);
    assert_eq!(loaded.reviewer, Policies::default().reviewer);
    Ok(())
}
