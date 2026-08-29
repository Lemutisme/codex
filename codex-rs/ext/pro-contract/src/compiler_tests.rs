use super::*;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::Evidence;
use codex_pro_contract::Resolution;
use codex_pro_contract::Trigger;
use pretty_assertions::assert_eq;

fn spec(authority: Vec<String>, artifacts: Vec<&str>) -> anyhow::Result<ContractSpec> {
    let artifacts = ArtifactSpec::new(
        artifacts
            .into_iter()
            .map(ArtifactPath::new)
            .collect::<Result<Vec<_>, _>>()?,
    )?;
    Ok(ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver".to_string(),
        brief: "preserve behavior".to_string(),
        artifacts,
        requires: Vec::new(),
        authority,
        budget: Budget {
            turns: 2,
            actions: 4,
            deadline: 10,
        },
        evidence: Evidence {
            claim: "candidate is ready".to_string(),
            replay: None,
        },
        resolution: Resolution {
            max_attempts: 2,
            retry_delay_ms: 0,
        },
    })
}

#[test]
fn preserves_original_request_without_putting_policy_in_the_spec() -> anyhow::Result<()> {
    let compiled = compile_spec(
        spec(vec!["filesystem.write".to_string()], vec!["result.bin"])?,
        Some("Build ./result.bin exactly."),
    )?;
    assert_eq!(
        compiled.spec.brief,
        "preserve behavior\n\nOriginal request:\nBuild ./result.bin exactly."
    );
    assert_eq!(compiled.manifest_hash.len(), 64);
    Ok(())
}

#[test]
fn rejects_adapter_unknown_authority_and_invented_artifacts() -> anyhow::Result<()> {
    assert_eq!(
        compile_spec(spec(vec!["root".to_string()], Vec::new())?, None)
            .expect_err("unknown authority should fail")
            .to_string(),
        "Codex cannot execute delegated authority: root"
    );
    assert_eq!(
        compile_spec(
            spec(Vec::new(), vec!["invented.bin"])?,
            Some("Build the requested result."),
        )
        .expect_err("invented artifact should fail")
        .to_string(),
        "declared artifacts must be exact paths named by the user: invented.bin"
    );
    Ok(())
}
