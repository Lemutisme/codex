use super::MAX_RETURNED_CASE_PREVIEWS;
use super::ProbeArgs;
use super::ProbeCase;
use super::ProbeTool;
use super::attempt_id;
use super::current_binding;
use super::digest;
use super::frontier;
use super::hash_optional_file;
use super::model_error;
use super::persist_report;
use super::prefix;
use super::process;
use super::request_hash;
use super::resolve_path;
use codex_exec_server::ExecMetadata;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_extension_api::FunctionCallError;
use codex_extension_api::JsonToolOutput;
use codex_extension_api::ToolCall;
use codex_extension_api::ToolOutput;
use codex_pro_contract::ArtifactPath;
use serde::Serialize;
use serde_json::json;
use std::time::Duration;
use std::time::Instant;

pub(super) async fn run(
    tool: &ProbeTool,
    invocation: ToolCall<'_>,
    args: ProbeArgs,
) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
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
    let environment = tool
        .runtime
        .environment_manager
        .try_local_environment()
        .ok_or_else(|| model_error("local environment is unavailable"))?;
    let binding = current_binding(&tool.runtime).await?;
    let attempt_id = attempt_id(&binding)?;
    let reference_name = ArtifactPath::new(&args.reference)
        .map_err(|error| model_error(format!("invalid reference path: {error}")))?;
    let reference_path = resolve_path(&tool_environment.cwd, &reference_name)?;
    let reference_hash = tokio::task::spawn_blocking({
        let reference_path = reference_path.clone();
        move || hash_optional_file(&reference_path)
    })
    .await
    .map_err(|error| model_error(format!("probe executable hashing failed: {error}")))?
    .map_err(model_error)?;

    let metadata = ExecMetadata {
        thread_id: Some(tool.runtime.thread_id),
        tool_call_id: Some(invocation.call_id.clone()),
    };
    let batch_started = Instant::now();
    let mut cases = Vec::with_capacity(args.cases.len());
    for case in args.cases {
        let request_hash = request_hash(
            &tool_environment.environment_id,
            reference_name.as_str(),
            reference_hash.as_deref(),
            &case.args,
        )?;
        let remaining =
            Duration::from_millis(args.batch_timeout_ms).saturating_sub(batch_started.elapsed());
        if remaining.is_zero() {
            return Err(model_error("probe batch timeout exhausted"));
        }
        let reference = process::run_program(
            &environment,
            &tool_environment.file_system_sandbox_context,
            &reference_path,
            &tool_environment.cwd,
            &case,
            Duration::from_millis(args.case_timeout_ms).min(remaining),
            &metadata,
        )
        .await?;
        cases.push(ReferenceCaseReport {
            request: case,
            request_hash,
            reference,
        });
    }

    let final_reference_hash = tokio::task::spawn_blocking({
        let reference_path = reference_path.clone();
        move || hash_optional_file(&reference_path)
    })
    .await
    .map_err(|error| model_error(format!("probe executable hashing failed: {error}")))?
    .map_err(model_error)?;
    if reference_hash != final_reference_hash {
        return Err(model_error(
            "probe reference changed while the batch was running",
        ));
    }
    let current = current_binding(&tool.runtime).await?;
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

    let report = ReferenceObservationReport {
        version: 1,
        mode: "observe",
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
        reference_hash,
        case_timeout_ms: args.case_timeout_ms,
        batch_timeout_ms: args.batch_timeout_ms,
        wall_duration_ms: u64::try_from(batch_started.elapsed().as_millis()).unwrap_or(u64::MAX),
        cases,
    };
    let encoded = serde_json::to_vec(&report)
        .map_err(|error| model_error(format!("probe report encoding failed: {error}")))?;
    let report_hash = digest(b"codex.procontract.probe.observation.v1\0", &encoded);
    persist_report(&tool.runtime, &report_hash, &encoded)?;
    let frontier = tool
        .runtime
        .probe_frontiers
        .record_reference_observation(frontier::ReferenceObservationRecord {
            report_hash: report_hash.clone(),
            attempt_id,
            request_hashes: report
                .cases
                .iter()
                .map(|case| case.request_hash.clone())
                .collect(),
            wall_duration_ms: report.wall_duration_ms,
        })
        .await
        .map_err(|error| model_error(format!("probe frontier update failed: {error}")))?;
    let observations = report
        .cases
        .iter()
        .take(MAX_RETURNED_CASE_PREVIEWS)
        .map(|case| {
            json!({
                "id": case.request.id,
                "requestHash": case.request_hash,
                "referenceExit": case.reference.exit,
                "referenceTimedOut": case.reference.timed_out,
                "referenceOutputLimitExceeded": case.reference.output_limit_exceeded,
                "referenceStdoutHex": prefix(&case.reference.stdout_hex),
                "referenceStderrHex": prefix(&case.reference.stderr_hex),
            })
        })
        .collect::<Vec<_>>();
    Ok(Box::new(
        JsonToolOutput::new(json!({
            "mode": "observe",
            "reportHash": report_hash,
            "referenceHash": &report.reference_hash,
            "caseCount": report.cases.len(),
            "executionCount": report.cases.len(),
            "observationCount": report.cases.len(),
            "returnedObservationCount": observations.len(),
            "omittedObservationCount": report.cases.len().saturating_sub(observations.len()),
            "wallDurationMs": report.wall_duration_ms,
            "observations": observations,
            "frontier": frontier,
        }))
        .with_external_context(),
    ))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ReferenceCaseReport {
    request: ProbeCase,
    request_hash: String,
    reference: process::CaptureReport,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ReferenceObservationReport {
    version: u32,
    mode: &'static str,
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
    case_timeout_ms: u64,
    batch_timeout_ms: u64,
    wall_duration_ms: u64,
    cases: Vec<ReferenceCaseReport>,
}
