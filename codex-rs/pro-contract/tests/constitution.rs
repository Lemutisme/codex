//! Constitutional meta-test: the settlement kernel crate must stay pure.
//!
//! Dependency whitelist plus banned-token scan, in the spirit of the OpenCode
//! implementation's pro-contract-constitution.test.ts. The kernel's purity is
//! a correctness property; this test makes drift a build failure instead of a
//! review finding.

use std::fs;
use std::path::Path;

const ALLOWED_DEPENDENCIES: [&str; 4] = ["serde", "serde_json", "sha2", "thiserror"];

const BANNED_TOKENS: [&str; 14] = [
    "std::fs",
    "std::io",
    "std::net",
    "std::process",
    "std::thread",
    "std::time",
    "std::env",
    "SystemTime",
    "Instant",
    "tokio",
    "sqlx",
    "tempfile",
    "rand",
    "ignore::",
];

#[test]
fn kernel_dependencies_are_exactly_the_whitelist() {
    let manifest = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"))
        .expect("read Cargo.toml");
    let deps_section = manifest
        .split("[dependencies]")
        .nth(1)
        .expect("dependencies section")
        .split("[dev-dependencies]")
        .next()
        .expect("dependencies body");
    let declared: Vec<&str> = deps_section
        .lines()
        .filter_map(|line| {
            let name = line.split('=').next()?.trim();
            (!name.is_empty() && !name.starts_with('[') && !name.starts_with('#')).then_some(name)
        })
        .collect();
    assert_eq!(declared, ALLOWED_DEPENDENCIES, "kernel dependency drift");
}

#[test]
fn rejection_sites_match_the_audited_count() {
    let kernel = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/src/kernel.rs"))
        .expect("read kernel.rs");
    let sites = kernel.matches("reject(").count();
    assert_eq!(
        sites, 68,
        "rejection site drift: re-audit rejection.rs mapping before updating this count"
    );
}

#[test]
fn kernel_sources_contain_no_banned_tokens() {
    let src = Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/src"));
    let mut checked = 0;
    for entry in fs::read_dir(src).expect("read src") {
        let path = entry.expect("entry").path();
        if path.extension().is_none_or(|extension| extension != "rs") {
            continue;
        }
        let source = fs::read_to_string(&path).expect("read source");
        for token in BANNED_TOKENS {
            assert!(
                !source.contains(token),
                "banned token `{token}` in {}",
                path.display()
            );
        }
        checked += 1;
    }
    assert!(checked >= 5, "expected kernel sources, found {checked}");
}
