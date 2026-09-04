use crate::Runtime;
use crate::binding::ExecutionBinding;
use codex_exec_server::ExecMetadata;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_extension_api::FunctionCallError;
use codex_extension_api::JsonToolOutput;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolExecutor;
use codex_extension_api::ToolName;
use codex_extension_api::ToolOutput;
use codex_extension_api::ToolSpec;
use codex_pro_contract::ArtifactPath;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::collections::HashSet;
use std::io::Write;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use tempfile::NamedTempFile;

pub(crate) const PROBE_TOOL_NAME: &str = "contract_probe_batch";

const MAX_CASES: usize = 12;
const MAX_ARGS: usize = 64;
const MAX_ARGUMENT_BYTES: usize = 16 * 1024;
const MAX_CAPTURE_BYTES: usize = 32 * 1024;
const MAX_EXECUTABLE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_CASE_TIMEOUT_MS: u64 = 60_000;
const MAX_BATCH_TIMEOUT_MS: u64 = 120_000;
const PREVIEW_BYTES: usize = 48;

#[path = "probe/frontier.rs"]
mod frontier;
#[path = "probe/observation.rs"]
mod observation;
#[path = "probe/process.rs"]
mod process;
#[path = "probe/spec.rs"]
mod spec;

pub(crate) use frontier::ProbeFrontierStore;

#[derive(Clone)]
pub(crate) struct ProbeTool {
    runtime: Arc<Runtime>,
}

impl ProbeTool {
    pub(crate) fn new(runtime: Arc<Runtime>) -> Self {
        Self { runtime }
    }
    async fn run(
        &self,
        invocation: ToolCall<'_>,
    ) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
        let args: ProbeArgs = serde_json::from_str(invocation.function_arguments()?)
            .map_err(|error| model_error(format!("invalid arguments: {error}")))?;
        validate_limits(&args)?;
        if args.mode == ProbeMode::Observe {
            return observation::run(self, invocation, args).await;
        }
        if invocation.environments.len() != 1 {
            return Err(model_error(
                "contract_probe_batch requires exactly one environment",
            ));
        }
        let tool_environment = &invocation.environments[0];
        if tool_environment.environment_id != LOCAL_ENVIRONMENT_ID {
            return Err(model_error(
                "contract_probe_batch currently requires the local environment",
            ));
        }
        let environment = self
            .runtime
            .environment_manager
            .try_local_environment()
            .ok_or_else(|| model_error("local environment is unavailable"))?;
        let binding = current_binding(&self.runtime).await?;
        let attempt_id = attempt_id(&binding)?;
        let reference_name = ArtifactPath::new(&args.reference)
            .map_err(|error| model_error(format!("invalid reference path: {error}")))?;
        let candidate = args
            .candidate
            .as_deref()
            .ok_or_else(|| model_error("compare mode requires candidate"))?;
        let candidate_name = ArtifactPath::new(candidate)
            .map_err(|error| model_error(format!("invalid candidate path: {error}")))?;
        let reference_path = resolve_path(&tool_environment.cwd, &reference_name)?;
        let candidate_path = resolve_path(&tool_environment.cwd, &candidate_name)?;
        let hashes = tokio::task::spawn_blocking({
            let reference_path = reference_path.clone();
            let candidate_path = candidate_path.clone();
            move || {
                Ok::<_, String>((
                    hash_optional_file(&reference_path)?,
                    hash_required_file(&candidate_path)?,
                ))
            }
        })
        .await
        .map_err(|error| model_error(format!("probe executable hashing failed: {error}")))?
        .map_err(model_error)?;
        let candidate_coordinate_hash = coordinate_digest(
            b"codex.procontract.probe.candidate.v1\0",
            &(candidate_name.as_str(), &hashes.1),
        )?;
        let metadata = ExecMetadata {
            thread_id: Some(self.runtime.thread_id.clone()),
            tool_call_id: Some(invocation.call_id.clone()),
        };
        let batch_started = Instant::now();
        let mut cases = Vec::with_capacity(args.cases.len());
        for case in args.cases {
            let request_hash = request_hash(
                &tool_environment.environment_id,
                reference_name.as_str(),
                hashes.0.as_deref(),
                &case.args,
            )?;
            let remaining = Duration::from_millis(args.batch_timeout_ms)
                .saturating_sub(batch_started.elapsed());
            if remaining.is_zero() {
                return Err(model_error("probe batch timeout exhausted"));
            }
            let timeout = Duration::from_millis(args.case_timeout_ms).min(remaining);
            let reference = process::run_program(
                &environment,
                &tool_environment.file_system_sandbox_context,
                &reference_path,
                &tool_environment.cwd,
                &case,
                timeout,
                &metadata,
            )
            .await?;
            let remaining = Duration::from_millis(args.batch_timeout_ms)
                .saturating_sub(batch_started.elapsed());
            if remaining.is_zero() {
                return Err(model_error("probe batch timeout exhausted"));
            }
            let candidate = process::run_program(
                &environment,
                &tool_environment.file_system_sandbox_context,
                &candidate_path,
                &tool_environment.cwd,
                &case,
                Duration::from_millis(args.case_timeout_ms).min(remaining),
                &metadata,
            )
            .await?;
            cases.push(CaseReport {
                byte_equal: captures_are_byte_equal(&reference, &candidate),
                request_hash,
                request: case,
                reference,
                candidate,
            });
        }
        let final_hashes = tokio::task::spawn_blocking({
            let reference_path = reference_path.clone();
            let candidate_path = candidate_path.clone();
            move || {
                Ok::<_, String>((
                    hash_optional_file(&reference_path)?,
                    hash_required_file(&candidate_path)?,
                ))
            }
        })
        .await
        .map_err(|error| model_error(format!("probe executable hashing failed: {error}")))?
        .map_err(model_error)?;
        if hashes != final_hashes {
            return Err(model_error(
                "probe executable changed while the batch was running",
            ));
        }
        let current = current_binding(&self.runtime).await?;
        if binding.contract_id != current.contract_id
            || binding.revision != current.revision
            || binding.attempts != current.attempts
            || binding.attempt_key != current.attempt_key
            || binding.execution_policy_hash != current.execution_policy_hash
        {
            return Err(model_error(
                "probe execution binding changed while the batch was running",
            ));
        }
        let report = ProbeReport {
            version: 3,
            turn_id: invocation.turn_id.clone(),
            call_id: invocation.call_id.clone(),
            model: invocation.model.clone(),
            contract_id: binding.contract_id,
            revision: binding.revision,
            attempt: binding.attempts,
            attempt_key: binding.attempt_key,
            environment_id: tool_environment.environment_id.clone(),
            execution_policy_hash: binding.execution_policy_hash,
            reference: reference_name.as_str().to_string(),
            reference_hash: hashes.0,
            candidate: candidate_name.as_str().to_string(),
            candidate_hash: hashes.1,
            candidate_coordinate_hash,
            case_timeout_ms: args.case_timeout_ms,
            batch_timeout_ms: args.batch_timeout_ms,
            wall_duration_ms: u64::try_from(batch_started.elapsed().as_millis())
                .unwrap_or(u64::MAX),
            cases,
        };
        let encoded = serde_json::to_vec(&report)
            .map_err(|error| model_error(format!("probe report encoding failed: {error}")))?;
        let report_hash = digest(b"codex.procontract.probe.v3\0", &encoded);
        persist_report(&self.runtime, &report_hash, &encoded)?;
        let byte_equal = report.cases.iter().filter(|case| case.byte_equal).count();
        let frontier = self
            .runtime
            .probe_frontiers
            .record(frontier::ObservationRecord {
                report_hash: report_hash.clone(),
                attempt_id,
                candidate_coordinate_hash: report.candidate_coordinate_hash.clone(),
                request_hashes: report
                    .cases
                    .iter()
                    .map(|case| case.request_hash.clone())
                    .collect(),
                byte_equal_count: byte_equal as u64,
                wall_duration_ms: report.wall_duration_ms,
            })
            .await
            .map_err(|error| model_error(format!("probe frontier update failed: {error}")))?;
        let differences = report
            .cases
            .iter()
            .filter(|case| !case.byte_equal)
            .map(|case| {
                json!({
                    "id": case.request.id,
                    "requestHash": case.request_hash,
                    "referenceExit": case.reference.exit,
                    "candidateExit": case.candidate.exit,
                    "referenceTimedOut": case.reference.timed_out,
                    "candidateTimedOut": case.candidate.timed_out,
                    "referenceOutputLimitExceeded": case.reference.output_limit_exceeded,
                    "candidateOutputLimitExceeded": case.candidate.output_limit_exceeded,
                    "referenceStdoutHex": prefix(&case.reference.stdout_hex),
                    "candidateStdoutHex": prefix(&case.candidate.stdout_hex),
                    "referenceStderrHex": prefix(&case.reference.stderr_hex),
                    "candidateStderrHex": prefix(&case.candidate.stderr_hex),
                })
            })
            .collect::<Vec<_>>();
        Ok(Box::new(
            JsonToolOutput::new(json!({
                "reportHash": report_hash,
                "candidateHash": &report.candidate_hash,
                "candidateCoordinateHash": &report.candidate_coordinate_hash,
                "caseCount": report.cases.len(),
                "executionCount": report.cases.len() * 2,
                "byteEqualCount": byte_equal,
                "differenceCount": report.cases.len() - byte_equal,
                "wallDurationMs": report.wall_duration_ms,
                "differences": differences,
                "frontier": frontier,
            }))
            .with_external_context(),
        ))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProbeArgs {
    #[serde(default)]
    mode: ProbeMode,
    reference: String,
    candidate: Option<String>,
    cases: Vec<ProbeCase>,
    case_timeout_ms: u64,
    batch_timeout_ms: u64,
}

#[derive(Clone, Copy, Default, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum ProbeMode {
    #[default]
    Compare,
    Observe,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ProbeCase {
    id: String,
    args: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CaseReport {
    request: ProbeCase,
    request_hash: String,
    byte_equal: bool,
    reference: process::CaptureReport,
    candidate: process::CaptureReport,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ProbeReport {
    version: u32,
    turn_id: String,
    call_id: String,
    model: String,
    contract_id: String,
    revision: u64,
    attempt: u64,
    attempt_key: String,
    environment_id: String,
    execution_policy_hash: Option<String>,
    reference: String,
    reference_hash: Option<String>,
    candidate: String,
    candidate_hash: String,
    candidate_coordinate_hash: String,
    case_timeout_ms: u64,
    batch_timeout_ms: u64,
    wall_duration_ms: u64,
    cases: Vec<CaseReport>,
}

impl<'call> ToolExecutor<ToolCall<'call>> for ProbeTool {
    fn tool_name(&self) -> ToolName {
        ToolName::plain(PROBE_TOOL_NAME)
    }

    fn spec(&self) -> ToolSpec {
        spec::probe_spec()
    }

    fn handle<'a>(
        &'a self,
        invocation: ToolCall<'call>,
    ) -> codex_extension_api::ToolExecutorFuture<'a>
    where
        'call: 'a,
    {
        Box::pin(async move { self.run(invocation).await })
    }
}

fn validate_limits(args: &ProbeArgs) -> Result<(), FunctionCallError> {
    match (args.mode, args.candidate.as_deref()) {
        (ProbeMode::Compare, Some(_)) | (ProbeMode::Observe, None) => {}
        (ProbeMode::Compare, None) => {
            return Err(model_error("compare mode requires candidate"));
        }
        (ProbeMode::Observe, Some(_)) => {
            return Err(model_error("observe mode does not accept candidate"));
        }
    }
    if args.cases.is_empty() || args.cases.len() > MAX_CASES {
        return Err(model_error(format!(
            "cases must contain 1..={MAX_CASES} items"
        )));
    }
    if !(100..=MAX_CASE_TIMEOUT_MS).contains(&args.case_timeout_ms) {
        return Err(model_error(format!(
            "case_timeout_ms must be 100..={MAX_CASE_TIMEOUT_MS}"
        )));
    }
    let mut ids = HashSet::new();
    for case in &args.cases {
        validate_case(case)?;
        if !ids.insert(case.id.as_str()) {
            return Err(model_error("case ids must be unique"));
        }
    }
    let executions_per_case = match args.mode {
        ProbeMode::Compare => 2,
        ProbeMode::Observe => 1,
    };
    if !(1_000..=MAX_BATCH_TIMEOUT_MS).contains(&args.batch_timeout_ms)
        || args
            .case_timeout_ms
            .saturating_mul(executions_per_case)
            .saturating_mul(args.cases.len() as u64)
            > args.batch_timeout_ms
    {
        return Err(model_error(format!(
            "batch_timeout_ms must be 1000..={MAX_BATCH_TIMEOUT_MS} and cover every requested execution"
        )));
    }
    Ok(())
}

fn validate_case(case: &ProbeCase) -> Result<(), FunctionCallError> {
    if case.id.is_empty()
        || case.id.len() > 80
        || !case
            .id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err(model_error("case id is invalid"));
    }
    if case.args.len() > MAX_ARGS
        || case.args.iter().map(String::len).sum::<usize>() > MAX_ARGUMENT_BYTES
    {
        return Err(model_error("case arguments exceed the bounded limit"));
    }
    Ok(())
}

fn resolve_path(
    root: &AbsolutePathBuf,
    relative: &ArtifactPath,
) -> Result<AbsolutePathBuf, FunctionCallError> {
    let root = root
        .canonicalize()
        .map_err(|error| model_error(format!("workspace path is unavailable: {error}")))?;
    let path = root
        .join(relative.as_str())
        .canonicalize()
        .map_err(|error| model_error(format!("probe executable is unavailable: {error}")))?;
    if !path.as_path().starts_with(root.as_path()) {
        return Err(model_error("probe path escapes the workspace"));
    }
    Ok(path)
}

fn captures_are_byte_equal(left: &process::CaptureReport, right: &process::CaptureReport) -> bool {
    !left.timed_out
        && !right.timed_out
        && !left.output_limit_exceeded
        && !right.output_limit_exceeded
        && left.exit == right.exit
        && left.stdout_hex == right.stdout_hex
        && left.stderr_hex == right.stderr_hex
}

fn attempt_id(binding: &ExecutionBinding) -> Result<String, FunctionCallError> {
    coordinate_digest(
        b"codex.procontract.probe.attempt.v1\0",
        &(
            &binding.contract_id,
            binding.revision,
            binding.attempts,
            &binding.attempt_key,
        ),
    )
}

fn request_hash(
    environment_id: &str,
    reference: &str,
    reference_hash: Option<&str>,
    args: &[String],
) -> Result<String, FunctionCallError> {
    coordinate_digest(
        b"codex.procontract.probe.request.v1\0",
        &(environment_id, reference, reference_hash, args),
    )
}

fn coordinate_digest(domain: &[u8], value: &impl Serialize) -> Result<String, FunctionCallError> {
    let encoded = serde_json::to_vec(value)
        .map_err(|error| model_error(format!("probe coordinate encoding failed: {error}")))?;
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(encoded);
    Ok(encode_hex(&hasher.finalize()))
}

fn prefix(value: &str) -> &str {
    &value[..value.len().min(PREVIEW_BYTES * 2)]
}

fn hash_optional_file(path: &AbsolutePathBuf) -> Result<Option<String>, String> {
    let metadata = std::fs::metadata(path.as_path()).map_err(|error| error.to_string())?;
    if !metadata.is_file() || metadata.len() > MAX_EXECUTABLE_BYTES {
        return Err("probe executable is not a bounded regular file".to_string());
    }
    match std::fs::read(path.as_path()) {
        Ok(bytes) => Ok(Some(encode_hex(&Sha256::digest(bytes)))),
        Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

fn hash_required_file(path: &AbsolutePathBuf) -> Result<String, String> {
    hash_optional_file(path)?.ok_or_else(|| "candidate executable is not readable".to_string())
}

fn persist_report(
    runtime: &Runtime,
    report_hash: &str,
    encoded: &[u8],
) -> Result<(), FunctionCallError> {
    let reports = runtime.replay_reports.with_file_name("pro-contract-probes");
    std::fs::create_dir_all(&reports)
        .map_err(|error| model_error(format!("probe report directory failed: {error}")))?;
    let destination = reports.join(format!("{report_hash}.json"));
    let mut temporary = NamedTempFile::new_in(&reports)
        .map_err(|error| model_error(format!("probe report staging failed: {error}")))?;
    temporary
        .write_all(encoded)
        .map_err(|error| model_error(format!("probe report write failed: {error}")))?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|error| model_error(format!("probe report sync failed: {error}")))?;
    match temporary.persist_noclobber(&destination) {
        Ok(_) => Ok(()),
        Err(error) if error.error.kind() == std::io::ErrorKind::AlreadyExists => {
            (std::fs::read(destination).map_err(|error| {
                model_error(format!("existing probe report read failed: {error}"))
            })? == encoded)
                .then_some(())
                .ok_or_else(|| model_error("existing probe report hash mismatch"))
        }
        Err(error) => Err(model_error(format!(
            "probe report persist failed: {}",
            error.error
        ))),
    }
}

async fn current_binding(runtime: &Runtime) -> Result<ExecutionBinding, FunctionCallError> {
    runtime
        .bindings
        .get(&runtime.thread_scope)
        .await
        .map_err(|error| model_error(format!("execution binding unavailable: {error}")))?
        .ok_or_else(|| model_error("execution binding is missing"))
}

fn process_error(error: impl std::fmt::Display) -> FunctionCallError {
    model_error(format!("probe process failed: {error}"))
}

fn model_error(message: impl Into<String>) -> FunctionCallError {
    FunctionCallError::RespondToModel(message.into())
}

fn digest(domain: &[u8], bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(bytes);
    encode_hex(&hasher.finalize())
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    encoded
}
