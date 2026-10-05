//! Runs the ProContract check pipeline over a materialized subject outside any thread, for
//! offline replay and controls. It calls the same `run_checks` the lane uses and prints the
//! receipts as JSON.
//!
//! `pro-contract-check --settings FILE --policy FILE --subject DIR --base DIR
//! [--candidate-is-reference]` reads the check environment from the settings file's evaluation
//! profile and the evidence policy from its own JSON file. With `--candidate-is-reference` the
//! reference is judged against itself: the negative control.

use std::path::PathBuf;
use std::process::ExitCode;

use codex_pro_contract_extension::EvidencePolicy;
use codex_pro_contract_extension::Settings;
use codex_pro_contract_extension::run_checks;

const USAGE: &str = "usage: pro-contract-check --settings FILE --policy FILE --subject DIR --base DIR [--candidate-is-reference]";

struct Args {
    settings: PathBuf,
    policy: PathBuf,
    subject: PathBuf,
    base: PathBuf,
    candidate_is_reference: bool,
}

fn parse_args() -> Result<Args, String> {
    let (mut settings, mut policy, mut subject, mut base) = (None, None, None, None);
    let mut candidate_is_reference = false;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        let slot = match flag.as_str() {
            "--settings" => &mut settings,
            "--policy" => &mut policy,
            "--subject" => &mut subject,
            "--base" => &mut base,
            "--candidate-is-reference" => {
                candidate_is_reference = true;
                continue;
            }
            other => return Err(format!("unknown argument {other}\n{USAGE}")),
        };
        *slot = Some(PathBuf::from(
            args.next()
                .ok_or_else(|| format!("{flag} needs a value\n{USAGE}"))?,
        ));
    }
    let required = |value: Option<PathBuf>, flag: &str| {
        value.ok_or_else(|| format!("{flag} is required\n{USAGE}"))
    };
    Ok(Args {
        settings: required(settings, "--settings")?,
        policy: required(policy, "--policy")?,
        subject: required(subject, "--subject")?,
        base: required(base, "--base")?,
        candidate_is_reference,
    })
}

fn read_json<T: serde::de::DeserializeOwned>(path: &PathBuf) -> Result<T, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    serde_json::from_str(&text).map_err(|error| format!("invalid {}: {error}", path.display()))
}

async fn run() -> Result<String, String> {
    let args = parse_args()?;
    let settings: Settings = read_json(&args.settings)?;
    let env = settings
        .evaluation
        .ok_or("the settings have no evaluation profile")?
        .check;
    let mut policy: EvidencePolicy = read_json(&args.policy)?;
    if args.candidate_is_reference {
        policy.build_command = None;
        policy.candidate_tests = false;
        policy.candidate_command = policy.reference_command.clone();
    }
    let receipts = run_checks(&env, &args.subject, &args.base, &policy)
        .await
        .map_err(|error| error.to_string())?;
    serde_json::to_string_pretty(&receipts).map_err(|error| error.to_string())
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> ExitCode {
    match run().await {
        Ok(receipts) => {
            println!("{receipts}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("pro-contract-check: {error}");
            ExitCode::from(2)
        }
    }
}
