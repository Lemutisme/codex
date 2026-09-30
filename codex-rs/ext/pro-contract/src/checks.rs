//! The container check pipeline: one fresh, network-less container runs an explicitly ordered
//! pipeline over a materialized copy of the subject — build, the candidate's own tests, then
//! every frozen differential case against the reference — and reports one result line per step.

use std::path::Path;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CheckEnvironment;
use crate::EvidencePolicy;
use crate::digest_of;

/// Seconds each side of one differential case may run.
const CASE_TIMEOUT_SECS: u64 = 20;
/// Bytes of log kept per step.
const STEP_DETAIL_CAP: usize = 4000;
/// Where the pipeline copies the candidate before building it.
const WORK_DIR: &str = "/tmp/pc-work";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StepOutcome {
    Pass,
    Fail,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StepReceipt {
    /// `build`, `candidate_tests`, or `differential:<case id>`.
    pub step: String,
    pub outcome: StepOutcome,
    pub detail: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckReceipts {
    pub steps: Vec<StepReceipt>,
    /// Toolchain lines reported inside the container.
    pub environment: Vec<String>,
    /// Whether every expected step reported an outcome.
    pub complete: bool,
    pub environment_digest: Digest,
    pub evaluator_digest: Digest,
}

#[derive(Debug, thiserror::Error)]
pub enum CheckError {
    #[error("check container failed to run: {0}")]
    Launch(String),
    #[error("check pipeline exceeded its timeout")]
    TimedOut,
}

/// Quotes one shell word with single quotes.
pub(crate) fn shell_quote(word: &str) -> String {
    format!("'{}'", word.replace('\'', "'\\''"))
}

fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let triple = [
            chunk[0],
            chunk.get(1).copied().unwrap_or(0),
            chunk.get(2).copied().unwrap_or(0),
        ];
        let value =
            (u32::from(triple[0]) << 16) | (u32::from(triple[1]) << 8) | u32::from(triple[2]);
        for index in 0..4 {
            if index <= chunk.len() {
                let sextet = (value >> (18 - 6 * index)) & 0x3f;
                out.push(char::from(ALPHABET[sextet as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// The candidate program as an absolute path inside the container.
fn candidate_path(policy: &EvidencePolicy, candidate_root: &str) -> Option<String> {
    let command = policy.candidate_command.as_deref()?;
    Some(if command.starts_with('/') {
        command.to_string()
    } else {
        format!(
            "{}/{}",
            candidate_root.trim_end_matches('/'),
            command.trim_start_matches("./")
        )
    })
}

fn runs_differential(policy: &EvidencePolicy) -> bool {
    policy.reference_command.is_some() && policy.candidate_command.is_some()
}

/// The ordered pipeline script for `policy`, run from `candidate_root` inside the container.
pub(crate) fn pipeline_script(
    policy: &EvidencePolicy,
    candidate_root: &str,
    step_timeout_secs: u64,
) -> String {
    let mut script = String::from(
        "set -u\n\
emit() { printf '@@PC %s %s\\n' \"$1\" \"$2\"; }\n\
log() { head -c 4000 \"$2\" | awk -v prefix=\"@@LOG $1 \" '{ print prefix $0 }'; }\n\
step() { log_file=$1; shift; timeout \"$STEP_TIMEOUT\" \"$@\" > \"$log_file\" 2>&1; rc=$?; if [ $rc -eq 124 ]; then { echo \"timed out after $STEP_TIMEOUT s\"; cat \"$log_file\"; } > \"$log_file.t\"; mv \"$log_file.t\" \"$log_file\"; fi; return $rc; }\n\
for tool in 'rustc --version' 'cargo --version' 'uname -srm'; do printf '@@ENV %s\\n' \"$($tool 2>&1 | head -n 1)\"; done\n\
export CARGO_NET_OFFLINE=true\n",
    );
    script.push_str(&format!("STEP_TIMEOUT={step_timeout_secs}\n"));
    // Build in a private copy owned by the container user, as the evaluator builds in a
    // workspace it owns; the mounted subject stays untouched.
    script.push_str(&format!(
        "rm -rf {WORK_DIR} && mkdir -p {WORK_DIR} && cp -R {}/. {WORK_DIR}/ || exit 90\ncd {WORK_DIR} || exit 90\n",
        shell_quote(candidate_root)
    ));
    if let Some(build) = &policy.build_command {
        let built = policy
            .candidate_command
            .as_deref()
            .map(|command| format!(" && [ -x {} ]", shell_quote(command)))
            .unwrap_or_default();
        script.push_str(&format!(
            "if step /tmp/pc-build.log sh -c {}{built}; then emit build pass; else log build /tmp/pc-build.log; emit build fail; fi\n",
            shell_quote(build)
        ));
    }
    if policy.candidate_tests {
        script.push_str(
            "if [ -f Cargo.toml ]; then if step /tmp/pc-test.log cargo test --offline --quiet; then emit candidate_tests pass; else log candidate_tests /tmp/pc-test.log; emit candidate_tests fail; fi; else echo 'no Cargo.toml in the candidate' > /tmp/pc-test.log; log candidate_tests /tmp/pc-test.log; emit candidate_tests fail; fi\n",
        );
    }
    if let (Some(reference), Some(candidate)) = (
        policy.reference_command.as_deref(),
        candidate_path(policy, WORK_DIR),
    ) {
        let reference = shell_quote(reference);
        let candidate = shell_quote(&candidate);
        for case in &policy.differential {
            let id = &case.id;
            let dir = format!("/tmp/pc-diff/{id}");
            let args = case
                .args
                .iter()
                .map(|arg| shell_quote(arg))
                .collect::<Vec<_>>()
                .join(" ");
            script.push_str(&format!("mkdir -p {dir}/c {dir}/r\n"));
            match &case.stdin {
                Some(stdin) => script.push_str(&format!(
                    "printf %s {} | base64 -d > {dir}/in\n",
                    shell_quote(&base64(stdin.as_bytes()))
                )),
                None => script.push_str(&format!(": > {dir}/in\n")),
            }
            for (side, program) in [("c", &candidate), ("r", &reference)] {
                script.push_str(&format!(
                    "(cd {dir}/{side} && timeout {CASE_TIMEOUT_SECS} {program} {args} < {dir}/in > out 2> err; echo $? > rc)\n"
                ));
            }
            script.push_str(&format!(
                "if cmp -s {dir}/c/out {dir}/r/out && cmp -s {dir}/c/rc {dir}/r/rc; then emit differential:{id} pass; else {{ echo \"exit status: reference $(cat {dir}/r/rc), candidate $(cat {dir}/c/rc)\"; diff {dir}/r/out {dir}/c/out | head -c 3000; }} > {dir}/report; log differential:{id} {dir}/report; emit differential:{id} fail; fi\n"
            ));
        }
    }
    script
}

/// The steps a complete run of `policy` reports, in order.
pub(crate) fn expected_steps(policy: &EvidencePolicy) -> Vec<String> {
    let mut steps = Vec::new();
    if policy.build_command.is_some() {
        steps.push("build".to_string());
    }
    if policy.candidate_tests {
        steps.push("candidate_tests".to_string());
    }
    if runs_differential(policy) {
        steps.extend(
            policy
                .differential
                .iter()
                .map(|case| format!("differential:{}", case.id)),
        );
    }
    steps
}

/// Parses the pipeline's stdout into receipts, environment lines, and completeness.
pub(crate) fn parse_output(
    stdout: &str,
    policy: &EvidencePolicy,
) -> (Vec<StepReceipt>, Vec<String>, bool) {
    let mut steps = Vec::new();
    let mut environment = Vec::new();
    let mut logs: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    for line in stdout.lines() {
        if let Some(rest) = line.strip_prefix("@@ENV ") {
            environment.push(rest.to_string());
        } else if let Some(rest) = line.strip_prefix("@@LOG ") {
            let (step, text) = rest.split_once(' ').unwrap_or((rest, ""));
            let log = logs.entry(step.to_string()).or_default();
            if log.len() < STEP_DETAIL_CAP {
                log.push_str(text);
                log.push('\n');
            }
        } else if let Some(rest) = line.strip_prefix("@@PC ") {
            let (step, outcome) = rest.split_once(' ').unwrap_or((rest, ""));
            let outcome = match outcome {
                "pass" => StepOutcome::Pass,
                _ => StepOutcome::Fail,
            };
            steps.push(StepReceipt {
                step: step.to_string(),
                outcome,
                detail: logs.remove(step).unwrap_or_default(),
            });
        }
    }
    let reported: Vec<String> = steps.iter().map(|step| step.step.clone()).collect();
    let complete = reported == expected_steps(policy);
    (steps, environment, complete)
}

fn unique_name() -> String {
    static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let count = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.subsec_nanos())
        .unwrap_or_default();
    format!("pro-contract-check-{}-{count}-{nanos}", std::process::id())
}

async fn command_output(program: &str, args: &[&str]) -> Result<String, CheckError> {
    let output = tokio::process::Command::new(program)
        .args(args)
        .output()
        .await
        .map_err(|error| CheckError::Launch(format!("{program}: {error}")))?;
    if !output.status.success() {
        return Err(CheckError::Launch(format!(
            "{program} {}: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr).trim()
        )));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// Runs the reference program once, black-box, in a fresh network-less container and returns
/// its bounded combined output and exit status — observations the drafter may use.
pub async fn probe_reference(
    env: &CheckEnvironment,
    reference: &str,
    args: &[String],
) -> Result<String, CheckError> {
    let invocation = std::iter::once(shell_quote(reference))
        .chain(args.iter().map(|arg| shell_quote(arg)))
        .collect::<Vec<_>>()
        .join(" ");
    let script = format!(
        "cd /tmp && timeout {CASE_TIMEOUT_SECS} {invocation} < /dev/null > /tmp/pc-probe.out 2>&1; status=$?; head -c 8000 /tmp/pc-probe.out; printf '\\n[exit status %s]\\n' \"$status\""
    );
    let name = unique_name();
    let child = tokio::process::Command::new(&env.docker)
        .args([
            "run",
            "--rm",
            "--name",
            &name,
            "--network",
            "none",
            "--user",
            &env.user,
            "--entrypoint",
            "bash",
            &env.image,
            "-c",
            &script,
        ])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| CheckError::Launch(error.to_string()))?;
    match tokio::time::timeout(
        std::time::Duration::from_secs(CASE_TIMEOUT_SECS * 3),
        child.wait_with_output(),
    )
    .await
    {
        Ok(output) => {
            let output = output.map_err(|error| CheckError::Launch(error.to_string()))?;
            Ok(String::from_utf8_lossy(&output.stdout).into_owned())
        }
        Err(_) => {
            let _ = command_output(&env.docker, &["rm", "-f", &name]).await;
            Err(CheckError::TimedOut)
        }
    }
}

/// Build and candidate tests each get a sixth of the container budget, so a hanging step is the
/// candidate's failure while the container timeout stays an infrastructure backstop.
fn step_timeout_secs(env: &CheckEnvironment) -> u64 {
    (env.timeout_secs / 6).max(1)
}

/// Runs the pipeline over the materialized subject at `subject_dir`.
pub async fn run(
    env: &CheckEnvironment,
    subject_dir: &Path,
    policy: &EvidencePolicy,
) -> Result<CheckReceipts, CheckError> {
    let launch = |error: std::io::Error| CheckError::Launch(error.to_string());
    let script = pipeline_script(policy, &env.candidate_mount, step_timeout_secs(env));
    let evaluator_digest = digest_of("check_pipeline", &(&script, &env.image));
    let image_id = command_output(
        &env.docker,
        &["image", "inspect", "--format", "{{.Id}}", &env.image],
    )
    .await?;
    let script_dir = subject_dir.with_extension("pipeline");
    tokio::fs::create_dir_all(&script_dir)
        .await
        .map_err(launch)?;
    tokio::fs::write(script_dir.join("pipeline.sh"), &script)
        .await
        .map_err(launch)?;
    let subject = subject_dir.display().to_string();
    let scripts = script_dir.display().to_string();
    // The container user only needs to read the subject; it builds in its own copy.
    command_output("chmod", &["-R", "a+rX", &subject, &scripts]).await?;
    let name = unique_name();
    let mount = format!("{subject}:{}:ro", env.candidate_mount);
    let script_mount = format!("{scripts}:/pc:ro");
    let child = tokio::process::Command::new(&env.docker)
        .args([
            "run",
            "--rm",
            "--name",
            &name,
            "--network",
            "none",
            "--user",
            &env.user,
            "-v",
            &mount,
            "-v",
            &script_mount,
            "--entrypoint",
            "bash",
            &env.image,
            "/pc/pipeline.sh",
        ])
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(launch)?;
    let output = match tokio::time::timeout(
        std::time::Duration::from_secs(env.timeout_secs),
        child.wait_with_output(),
    )
    .await
    {
        Ok(output) => output.map_err(launch)?,
        Err(_) => {
            let _ = command_output(&env.docker, &["rm", "-f", &name]).await;
            return Err(CheckError::TimedOut);
        }
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    let (steps, environment, complete) = parse_output(&stdout, policy);
    let environment_digest = digest_of("check_environment", &(&image_id, &environment));
    Ok(CheckReceipts {
        steps,
        environment,
        complete,
        environment_digest,
        evaluator_digest,
    })
}

#[cfg(test)]
#[path = "checks_tests.rs"]
mod tests;
