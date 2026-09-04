use super::MAX_CAPTURE_BYTES;
use super::ProbeCase;
use super::encode_hex;
use super::model_error;
use super::process_error;
use codex_exec_server::ExecEnvPolicy;
use codex_exec_server::ExecMetadata;
use codex_exec_server::ExecOutputStream;
use codex_exec_server::ExecParams;
use codex_exec_server::ExecProcess;
use codex_exec_server::ProcessId;
use codex_extension_api::FunctionCallError;
use codex_protocol::config_types::ShellEnvironmentPolicyInherit;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

static NEXT_PROCESS_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct CaptureReport {
    pub(super) exit: Option<i32>,
    pub(super) duration_ms: u64,
    pub(super) timed_out: bool,
    pub(super) output_limit_exceeded: bool,
    pub(super) stdout_hex: String,
    pub(super) stderr_hex: String,
}

pub(super) async fn run_program(
    environment: &codex_exec_server::Environment,
    sandbox: &codex_file_system::FileSystemSandboxContext,
    executable: &AbsolutePathBuf,
    cwd: &AbsolutePathBuf,
    case: &ProbeCase,
    timeout: Duration,
    metadata: &ExecMetadata,
) -> Result<CaptureReport, FunctionCallError> {
    let mut argv = Vec::with_capacity(case.args.len() + 1);
    argv.push(executable.display().to_string());
    argv.extend(case.args.clone());
    let started_at = Instant::now();
    let started = environment
        .get_exec_backend()
        .start(ExecParams {
            process_id: ProcessId::from(format!(
                "pro-contract-probe-{}",
                NEXT_PROCESS_ID.fetch_add(1, Ordering::Relaxed)
            )),
            metadata: Some(metadata.clone()),
            argv,
            cwd: PathUri::from_abs_path(cwd),
            env_policy: Some(ExecEnvPolicy {
                inherit: ShellEnvironmentPolicyInherit::Core,
                ignore_default_excludes: false,
                exclude: Vec::new(),
                r#set: HashMap::new(),
                include_only: Vec::new(),
            }),
            shell_snapshot: None,
            env: HashMap::new(),
            tty: false,
            pipe_stdin: false,
            arg0: None,
            sandbox: Some(sandbox.clone()),
            enforce_managed_network: false,
            managed_network: None,
            network_proxy: None,
        })
        .await
        .map_err(|error| model_error(format!("probe process failed to start: {error}")))?;
    collect_process(started.process, timeout, started_at).await
}

async fn collect_process(
    process: Arc<dyn ExecProcess>,
    timeout: Duration,
    started_at: Instant,
) -> Result<CaptureReport, FunctionCallError> {
    let deadline = tokio::time::Instant::now() + timeout;
    let mut stdout = StreamCapture::default();
    let mut stderr = StreamCapture::default();
    let mut after_seq = None;
    let mut exit = None;
    let mut timed_out = false;
    let mut output_limit_exceeded = false;
    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        let captured = stdout.total.saturating_add(stderr.total);
        let max_bytes = MAX_CAPTURE_BYTES.saturating_sub(captured).saturating_add(1);
        let wait_ms = u64::try_from(remaining.as_millis()).unwrap_or(u64::MAX);
        let response = match tokio::time::timeout(
            remaining,
            process.read(
                after_seq,
                /*max_bytes*/ Some(max_bytes),
                /*wait_ms*/ Some(wait_ms),
            ),
        )
        .await
        {
            Ok(Ok(response)) => response,
            Ok(Err(error)) => {
                let _ = process.terminate().await;
                return Err(process_error(error));
            }
            Err(_) => {
                timed_out = true;
                process.terminate().await.map_err(process_error)?;
                break;
            }
        };
        if let Some(error) = response.failure {
            let _ = process.terminate().await;
            return Err(model_error(error));
        }
        for chunk in response.chunks {
            after_seq = Some(chunk.seq);
            let remaining = MAX_CAPTURE_BYTES
                .saturating_sub(stdout.bytes.len().saturating_add(stderr.bytes.len()));
            let stream = match chunk.stream {
                ExecOutputStream::Stdout | ExecOutputStream::Pty => &mut stdout,
                ExecOutputStream::Stderr => &mut stderr,
            };
            stream.push(&chunk.chunk.0, remaining);
        }
        if stdout.total.saturating_add(stderr.total) > MAX_CAPTURE_BYTES {
            output_limit_exceeded = true;
            process.terminate().await.map_err(process_error)?;
            break;
        }
        if response.exited {
            exit = response.exit_code;
        }
        if response.closed {
            break;
        }
        after_seq = response.next_seq.checked_sub(1).or(after_seq);
    }
    Ok(CaptureReport {
        exit,
        duration_ms: u64::try_from(started_at.elapsed().as_millis()).unwrap_or(u64::MAX),
        timed_out,
        output_limit_exceeded,
        stdout_hex: encode_hex(&stdout.bytes),
        stderr_hex: encode_hex(&stderr.bytes),
    })
}

#[derive(Default)]
struct StreamCapture {
    bytes: Vec<u8>,
    total: usize,
}

impl StreamCapture {
    fn push(&mut self, bytes: &[u8], remaining: usize) {
        self.total = self.total.saturating_add(bytes.len());
        self.bytes
            .extend_from_slice(&bytes[..bytes.len().min(remaining)]);
    }
}
