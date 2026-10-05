//! The container check pipeline: one fresh, network-less container builds a private copy of the
//! candidate, runs its own tests when asked, then runs every case, public then sealed, through one
//! case runner and reports one result line per step.
//!
//! The case runner gives both programs the same world: the same working directory, rebuilt before
//! every run from the base workspace and the case's fixtures, the same program path, environment
//! and stdin. It runs the reference, the candidate, then the reference again; a channel (exit
//! status, stdout, stderr, the resulting files) counts only when the two reference runs agree on it.

use std::path::Path;
use std::path::PathBuf;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CheckEnvironment;
use crate::DifferentialCase;
use crate::EvidencePolicy;
use crate::digest_of;

/// Seconds each run of one case may take.
const CASE_TIMEOUT_SECS: u64 = 10;
/// Candidate timeouts after which the remaining cases fail without running the candidate.
const HANG_BREAKER: u32 = 5;
/// Bytes of log kept per step.
const STEP_DETAIL_CAP: usize = 4000;
/// Bytes of each stream kept per observation, head and tail, so a long `--help` keeps its option
/// list and its closing sections. Observations feed the prober only; comparisons use their own diff.
const OBSERVATION_STREAM_CAP: usize = 16384;
/// Where the pipeline copies the candidate before building it.
const WORK_DIR: &str = "/tmp/pc-work";
/// Where the base workspace is mounted, read-only.
const BASE_MOUNT: &str = "/pc-base";
/// Where the pipeline script and the case inputs are mounted, read-only.
const PIPELINE_MOUNT: &str = "/pc";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StepOutcome {
    Pass,
    Fail,
    /// The reference disagreed with itself on its exit status or timed out: no evidence.
    Unqualified,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct StepReceipt {
    /// `build`, `candidate_tests`, `public:<case id>` or `sealed:<case id>`.
    pub step: String,
    pub outcome: StepOutcome,
    pub detail: String,
    /// The channels on which the two reference runs agreed: `rc`, `out`, `err`, `files`.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub stable: Vec<String>,
    /// The reference's exit status on a case.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reference_exit: Option<i32>,
}

impl StepReceipt {
    pub fn new(step: impl Into<String>, outcome: StepOutcome, detail: impl Into<String>) -> Self {
        Self {
            step: step.into(),
            outcome,
            detail: detail.into(),
            stable: Vec::new(),
            reference_exit: None,
        }
    }
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

/// The reference's behavior on one case, run twice.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Observation {
    pub id: String,
    pub exit: Option<i32>,
    /// Whether the two runs agreed on every channel.
    pub stable: bool,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Debug, thiserror::Error)]
pub enum CheckError {
    #[error("check container failed to run: {0}")]
    Launch(String),
    #[error("check pipeline exceeded its timeout")]
    TimedOut,
}

/// The two partitions of an evidence policy's cases.
pub(crate) const PUBLIC: &str = "public";
pub(crate) const SEALED: &str = "sealed";

/// Quotes one shell word with single quotes.
pub(crate) fn shell_quote(word: &str) -> String {
    format!("'{}'", word.replace('\'', "'\\''"))
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

fn runs_cases(policy: &EvidencePolicy) -> bool {
    policy.reference_command.is_some() && policy.candidate_command.is_some()
}

/// Every case of `policy` with its step name, public before sealed.
pub(crate) fn cases(policy: &EvidencePolicy) -> Vec<(String, &DifferentialCase)> {
    let public = policy
        .differential
        .iter()
        .map(|case| (format!("{PUBLIC}:{}", case.id), case));
    let sealed = policy
        .sealed
        .iter()
        .map(|case| (format!("{SEALED}:{}", case.id), case));
    public.chain(sealed).collect()
}

/// Shell functions shared by every pipeline script.
pub(crate) const PRELUDE: &str = "set -u
emit() { printf '@@PC %s %s\\n' \"$1\" \"$2\"; }
log() { size=$(wc -c < \"$2\"); if [ \"$size\" -le 4000 ]; then cat \"$2\"; else head -c 2000 \"$2\"; printf '\\n[... %s bytes omitted ...]\\n' \"$((size - 4000))\"; tail -c 2000 \"$2\"; fi | awk -v prefix=\"@@LOG $1 \" '{ print prefix $0 }'; }
step() { log_file=$1; shift; timeout \"$STEP_TIMEOUT\" \"$@\" > \"$log_file\" 2>&1; rc=$?; if [ $rc -eq 124 ]; then { echo \"timed out after $STEP_TIMEOUT s\"; cat \"$log_file\"; } > \"$log_file.t\"; mv \"$log_file.t\" \"$log_file\"; fi; return $rc; }
for tool in 'rustc --version' 'cargo --version' 'uname -srm'; do printf '@@ENV %s\\n' \"$($tool 2>&1 | head -n 1)\"; done
export CARGO_NET_OFFLINE=true
";

/// The case runner. `run_side INPUT PROGRAM OUT ARGS...` rebuilds the case directory from the base
/// workspace and the case's fixtures, points the program path at PROGRAM and runs it with the
/// case's environment and stdin, recording exit status, stdout, stderr and the resulting files.
/// `run_case STEP INPUT RESULTS ARGS...` runs reference, candidate, reference and judges.
const CASE_RUNNER: &str = "mkdir -p /tmp/pc-bin /tmp/pc-diff
hangs=0
run_side() {
  input=$1; program=$2; out=$3; shift 3
  rm -rf /tmp/pc-case /tmp/pc-home && mkdir -p /tmp/pc-case /tmp/pc-home \"$out\" || return 90
  if [ -d /pc-base ]; then cp -R /pc-base/. /tmp/pc-case/ 2>/dev/null; fi
  if [ -d \"$input/fixture\" ]; then cp -R \"$input/fixture/.\" /tmp/pc-case/; fi
  ln -sfn \"$program\" /tmp/pc-bin/executable
  envs=(); if [ -s \"$input/env\" ]; then mapfile -t envs < \"$input/env\"; fi
  (cd /tmp/pc-case && env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 TZ=UTC HOME=/tmp/pc-home ${envs[@]+\"${envs[@]}\"} timeout -k 2 \"$CASE_TIMEOUT\" /tmp/pc-bin/executable \"$@\" < \"$input/stdin\" > \"$out/out\" 2> \"$out/err\"; echo $? > \"$out/rc\")
  (cd /tmp/pc-case && find . -type f -print0 | sort -z | xargs -0 -r sha256sum) > \"$out/files\" 2>/dev/null
}
judge() {
  d=$2; rrc=$(cat \"$d/r1/rc\")
  if [ \"$rrc\" = 124 ] || [ \"$rrc\" = 137 ] || ! cmp -s \"$d/r1/rc\" \"$d/r2/rc\"; then printf '@@PC %s unqualified - %s\\n' \"$1\" \"$rrc\"; return; fi
  stable=''; failed=''
  for ch in rc out err files; do
    if cmp -s \"$d/r1/$ch\" \"$d/r2/$ch\"; then
      stable=\"$stable${stable:+,}$ch\"
      cmp -s \"$d/r1/$ch\" \"$d/c/$ch\" || failed=\"$failed $ch\"
    fi
  done
  if [ -z \"$failed\" ]; then printf '@@PC %s pass %s %s\\n' \"$1\" \"$stable\" \"$rrc\"; return; fi
  {
    echo \"differing channels:$failed\"
    echo \"exit status: reference $rrc, candidate $(cat \"$d/c/rc\")\"
    for ch in $failed; do
      case $ch in
        out|err) echo \"--- $ch (< reference, > candidate)\"; diff \"$d/r1/$ch\" \"$d/c/$ch\" | head -c 1500; echo ;;
        files) echo '--- files (< reference, > candidate)'; diff \"$d/r1/files\" \"$d/c/files\" | head -c 1000; echo ;;
      esac
    done
  } > \"$d/report\"
  log \"$1\" \"$d/report\"
  printf '@@PC %s fail %s %s\\n' \"$1\" \"$stable\" \"$rrc\"
}
run_case() {
  step_name=$1; input=$2; d=$3; shift 3
  if [ \"$built\" != 1 ]; then emit \"$step_name\" fail; return; fi
  run_side \"$input\" \"$REFERENCE\" \"$d/r1\" \"$@\"
  if [ \"$hangs\" -ge \"$HANG_BREAKER\" ]; then
    mkdir -p \"$d/c\"; echo 124 > \"$d/c/rc\"; : > \"$d/c/out\"; : > \"$d/c/err\"; : > \"$d/c/files\"
  else
    run_side \"$input\" \"$CANDIDATE\" \"$d/c\" \"$@\"
    case $(cat \"$d/c/rc\") in 124|137) hangs=$((hangs + 1)) ;; esac
  fi
  run_side \"$input\" \"$REFERENCE\" \"$d/r2\" \"$@\"
  judge \"$step_name\" \"$d\"
}
obs() { size=$(wc -c < \"$2\"); if [ \"$size\" -le \"$OBSERVATION_CAP\" ]; then cat \"$2\"; else head -c \"$((OBSERVATION_CAP / 2))\" \"$2\"; printf '\\n[... %s bytes omitted ...]\\n' \"$((size - OBSERVATION_CAP))\"; tail -c \"$((OBSERVATION_CAP / 2))\" \"$2\"; fi | awk -v prefix=\"$1\" '{ print prefix $0 }'; }
observe_case() {
  id=$1; input=$2; d=$3; shift 3
  run_side \"$input\" \"$REFERENCE\" \"$d/r1\" \"$@\"
  run_side \"$input\" \"$REFERENCE\" \"$d/r2\" \"$@\"
  agree=stable; for ch in rc out err files; do cmp -s \"$d/r1/$ch\" \"$d/r2/$ch\" || agree=unstable; done
  obs \"@@OUT $id \" \"$d/r1/out\"
  obs \"@@ERR $id \" \"$d/r1/err\"
  printf '@@OBS %s %s %s\\n' \"$id\" \"$(cat \"$d/r1/rc\")\" \"$agree\"
}
";

/// The invocation of one case in the pipeline: `FUNCTION NAME INPUT RESULTS ARGS...`.
fn case_line(function: &str, name: &str, index: usize, case: &DifferentialCase) -> String {
    let args = case
        .args
        .iter()
        .map(|arg| shell_quote(arg))
        .collect::<Vec<_>>()
        .join(" ");
    format!(
        "{function} {} {PIPELINE_MOUNT}/cases/{index} /tmp/pc-diff/{index} {args}\n",
        shell_quote(name)
    )
}

fn runner_variables(reference: &str) -> String {
    format!(
        "CASE_TIMEOUT={CASE_TIMEOUT_SECS}\nHANG_BREAKER={HANG_BREAKER}\nOBSERVATION_CAP={OBSERVATION_STREAM_CAP}\nREFERENCE={}\n",
        shell_quote(reference)
    )
}

/// The ordered pipeline script for `policy`, run from `candidate_root` inside the container.
pub(crate) fn pipeline_script(
    policy: &EvidencePolicy,
    candidate_root: &str,
    step_timeout_secs: u64,
) -> String {
    let mut script = String::from(PRELUDE);
    script.push_str(&format!("STEP_TIMEOUT={step_timeout_secs}\nbuilt=1\n"));
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
            "if step /tmp/pc-build.log sh -c {}{built}; then emit build pass; else log build /tmp/pc-build.log; emit build fail; built=0; fi\n",
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
        script.push_str(CASE_RUNNER);
        script.push_str(&runner_variables(reference));
        script.push_str(&format!("CANDIDATE={}\n", shell_quote(&candidate)));
        for (index, (name, case)) in cases(policy).into_iter().enumerate() {
            script.push_str(&case_line("run_case", &name, index, case));
        }
    }
    script
}

/// The script that runs `cases` on the reference only, twice each.
pub(crate) fn observe_script(reference: &str, cases: &[DifferentialCase]) -> String {
    let mut script = String::from("set -u\n");
    script.push_str(CASE_RUNNER);
    script.push_str(&runner_variables(reference));
    for (index, case) in cases.iter().enumerate() {
        script.push_str(&case_line("observe_case", &case.id, index, case));
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
    if runs_cases(policy) {
        steps.extend(cases(policy).into_iter().map(|(name, _)| name));
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
            let mut fields = rest.split(' ');
            let step = fields.next().unwrap_or_default().to_string();
            let outcome = match fields.next() {
                Some("pass") => StepOutcome::Pass,
                Some("unqualified") => StepOutcome::Unqualified,
                _ => StepOutcome::Fail,
            };
            let stable = fields
                .next()
                .filter(|stable| *stable != "-")
                .map(|stable| stable.split(',').map(str::to_string).collect())
                .unwrap_or_default();
            let reference_exit = fields.next().and_then(|exit| exit.parse().ok());
            let detail = logs.remove(&step).unwrap_or_default();
            steps.push(StepReceipt {
                step,
                outcome,
                detail,
                stable,
                reference_exit,
            });
        }
    }
    let reported: Vec<String> = steps.iter().map(|step| step.step.clone()).collect();
    let complete = reported == expected_steps(policy);
    (steps, environment, complete)
}

/// Parses an observe script's stdout into one observation per reported case.
pub(crate) fn parse_observations(stdout: &str) -> Vec<Observation> {
    let mut streams: std::collections::HashMap<(String, bool), String> =
        std::collections::HashMap::new();
    let mut observations = Vec::new();
    for line in stdout.lines() {
        let (prefix, is_out) = if let Some(rest) = line.strip_prefix("@@OUT ") {
            (rest, true)
        } else if let Some(rest) = line.strip_prefix("@@ERR ") {
            (rest, false)
        } else if let Some(rest) = line.strip_prefix("@@OBS ") {
            let mut fields = rest.split(' ');
            let id = fields.next().unwrap_or_default().to_string();
            let exit = fields.next().and_then(|exit| exit.parse().ok());
            let stable = fields.next() == Some("stable");
            observations.push(Observation {
                stdout: streams.remove(&(id.clone(), true)).unwrap_or_default(),
                stderr: streams.remove(&(id.clone(), false)).unwrap_or_default(),
                id,
                exit,
                stable,
            });
            continue;
        } else {
            continue;
        };
        let (id, text) = prefix.split_once(' ').unwrap_or((prefix, ""));
        let stream = streams.entry((id.to_string(), is_out)).or_default();
        stream.push_str(text);
        stream.push('\n');
    }
    observations
}

/// A fixture path as a relative path that cannot leave the case directory.
pub(crate) fn safe_relative(path: &str) -> Option<&Path> {
    let candidate = Path::new(path);
    let plain = !path.is_empty()
        && candidate
            .components()
            .all(|component| matches!(component, std::path::Component::Normal(_)));
    plain.then_some(candidate)
}

/// Writes one case's stdin, environment and fixtures under `dir`.
fn write_case_inputs(dir: &Path, case: &DifferentialCase) -> std::io::Result<()> {
    let invalid = |path: &str| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            format!(
                "case {}: fixture path {path:?} leaves the case directory",
                case.id
            ),
        )
    };
    let fixture = dir.join("fixture");
    std::fs::create_dir_all(&fixture)?;
    std::fs::write(dir.join("stdin"), case.stdin.as_deref().unwrap_or(""))?;
    let env: String = case
        .env
        .iter()
        .map(|(key, value)| format!("{key}={value}\n"))
        .collect();
    std::fs::write(dir.join("env"), env)?;
    for path in &case.dirs {
        let relative = safe_relative(path).ok_or_else(|| invalid(path))?;
        std::fs::create_dir_all(fixture.join(relative))?;
    }
    for file in &case.files {
        let relative = safe_relative(&file.path).ok_or_else(|| invalid(&file.path))?;
        let target = fixture.join(relative);
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(target, file.content())?;
    }
    Ok(())
}

/// Writes the script and every case's inputs into a fresh pipeline directory.
async fn write_pipeline(
    pipeline_dir: &Path,
    script: &str,
    cases: Vec<DifferentialCase>,
) -> Result<(), CheckError> {
    let pipeline_dir = pipeline_dir.to_path_buf();
    let script = script.to_string();
    tokio::task::spawn_blocking(move || {
        let _ = std::fs::remove_dir_all(&pipeline_dir);
        std::fs::create_dir_all(&pipeline_dir)?;
        std::fs::write(pipeline_dir.join("pipeline.sh"), script)?;
        for (index, case) in cases.iter().enumerate() {
            write_case_inputs(&pipeline_dir.join("cases").join(index.to_string()), case)?;
        }
        Ok::<_, std::io::Error>(())
    })
    .await
    .map_err(|error| CheckError::Launch(error.to_string()))?
    .map_err(|error| CheckError::Launch(error.to_string()))
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

/// Runs `pipeline.sh` from `pipeline_dir` in a fresh, network-less container with each
/// `(host, container)` directory mounted read-only, and returns its stdout.
async fn run_container(
    env: &CheckEnvironment,
    pipeline_dir: &Path,
    mounts: &[(&Path, &str)],
    timeout: std::time::Duration,
) -> Result<String, CheckError> {
    let mut readable: Vec<String> = mounts
        .iter()
        .map(|(host, _)| host.display().to_string())
        .collect();
    readable.push(pipeline_dir.display().to_string());
    let mut chmod = vec!["-R", "a+rX"];
    chmod.extend(readable.iter().map(String::as_str));
    // The container user only needs to read the mounts; it works in its own copies.
    command_output("chmod", &chmod).await?;
    let name = unique_name();
    let mut args: Vec<String> = [
        "run",
        "--rm",
        "--name",
        &name,
        "--network",
        "none",
        "--user",
        &env.user,
    ]
    .iter()
    .map(ToString::to_string)
    .collect();
    let all_mounts = mounts
        .iter()
        .map(|(host, container)| (host.display().to_string(), container.to_string()))
        .chain(std::iter::once((
            pipeline_dir.display().to_string(),
            PIPELINE_MOUNT.to_string(),
        )));
    for (host, container) in all_mounts {
        args.push("-v".to_string());
        args.push(format!("{host}:{container}:ro"));
    }
    args.extend(
        [
            "--entrypoint",
            "bash",
            &env.image,
            &format!("{PIPELINE_MOUNT}/pipeline.sh"),
        ]
        .iter()
        .map(ToString::to_string),
    );
    let child = tokio::process::Command::new(&env.docker)
        .args(&args)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| CheckError::Launch(error.to_string()))?;
    match tokio::time::timeout(timeout, child.wait_with_output()).await {
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

/// Runs `cases` on the reference only, twice each, over the base workspace at `base_dir`; for
/// probing what the reference does before any candidate exists.
pub async fn observe(
    env: &CheckEnvironment,
    base_dir: &Path,
    reference: &str,
    cases: &[DifferentialCase],
) -> Result<Vec<Observation>, CheckError> {
    let pipeline_dir = scratch_dir(base_dir, "observe");
    write_pipeline(
        &pipeline_dir,
        &observe_script(reference, cases),
        cases.to_vec(),
    )
    .await?;
    let stdout = run_container(
        env,
        &pipeline_dir,
        &[(base_dir, BASE_MOUNT)],
        std::time::Duration::from_secs(env.timeout_secs),
    )
    .await;
    let _ = tokio::fs::remove_dir_all(&pipeline_dir).await;
    Ok(parse_observations(&stdout?))
}

/// A sibling directory of `dir` for one container run's script and case inputs.
fn scratch_dir(dir: &Path, purpose: &str) -> PathBuf {
    let name = dir
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    dir.with_file_name(format!("{name}.{purpose}-{}", unique_name()))
}

/// Build and candidate tests each get a sixth of the container budget, so a hanging step is the
/// candidate's failure while the container timeout stays an infrastructure backstop.
fn step_timeout_secs(env: &CheckEnvironment) -> u64 {
    (env.timeout_secs / 6).max(1)
}

/// Runs the pipeline over the materialized subject at `subject_dir`, with the base workspace at
/// `base_dir` under every case.
pub async fn run(
    env: &CheckEnvironment,
    subject_dir: &Path,
    base_dir: &Path,
    policy: &EvidencePolicy,
) -> Result<CheckReceipts, CheckError> {
    let script = pipeline_script(policy, &env.candidate_mount, step_timeout_secs(env));
    let evaluator_digest = digest_of("check_pipeline", &(&script, &env.image));
    let image_id = command_output(
        &env.docker,
        &["image", "inspect", "--format", "{{.Id}}", &env.image],
    )
    .await?;
    let pipeline_dir = subject_dir.with_extension("pipeline");
    let case_list = if runs_cases(policy) {
        cases(policy)
            .into_iter()
            .map(|(_, case)| case.clone())
            .collect()
    } else {
        Vec::new()
    };
    write_pipeline(&pipeline_dir, &script, case_list).await?;
    let stdout = run_container(
        env,
        &pipeline_dir,
        &[
            (subject_dir, env.candidate_mount.as_str()),
            (base_dir, BASE_MOUNT),
        ],
        std::time::Duration::from_secs(env.timeout_secs),
    )
    .await?;
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
