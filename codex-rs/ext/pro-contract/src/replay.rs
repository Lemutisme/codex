use codex_exec_server::EnvironmentManager;
use codex_exec_server::ExecEnvPolicy;
use codex_exec_server::ExecOutputStream;
use codex_exec_server::ExecParams;
use codex_exec_server::ExecProcessEvent;
use codex_exec_server::ProcessId;
use codex_file_system::FileSystemSandboxContext;
use codex_pro_contract::CapturedSubject;
use codex_pro_contract::ProtectedFile;
use codex_pro_contract::ReplayCheck;
use codex_pro_contract::ReplayPolicy;
use codex_pro_contract::ReplayResult;
use codex_pro_contract::SubjectStore;
use codex_pro_contract::hash_replay;
use codex_protocol::config_types::ShellEnvironmentPolicyInherit;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tempfile::NamedTempFile;
use thiserror::Error;

const MAX_OUTPUT_BYTES: usize = 1024 * 1024;
static NEXT_PROCESS_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
pub(crate) struct ReplayVerifier {
    subjects: SubjectStore,
    environments: Arc<EnvironmentManager>,
    reports: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct CheckReport {
    argv: Vec<String>,
    cwd: String,
    expected_exit: i32,
    exit: i32,
    stdout_hash: String,
    stderr_hash: String,
    stdout_truncated: bool,
    stderr_truncated: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct FileReport {
    path: String,
    exists: bool,
    hash: Option<String>,
    expected_hash: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct Report {
    version: u32,
    contract_id: String,
    policy_hash: String,
    subject_hash: String,
    passed: bool,
    checks: Vec<CheckReport>,
    protected: Vec<FileReport>,
    artifacts: Vec<FileReport>,
}

#[derive(Debug, Error)]
pub(crate) enum ReplayError {
    #[error("replay is only available in the local execution environment")]
    NonLocal,
    #[error("local replay environment is unavailable")]
    EnvironmentUnavailable,
    #[error("replay path is invalid: {0}")]
    Path(String),
    #[error("subject materialization failed: {0}")]
    Subject(String),
    #[error("replay process failed: {0}")]
    Process(String),
    #[error("replay check timed out after {0} milliseconds")]
    Timeout(u64),
    #[error("replay report could not be persisted: {0}")]
    Report(String),
}

impl ReplayVerifier {
    pub(crate) fn new(
        subjects: SubjectStore,
        environments: Arc<EnvironmentManager>,
        reports: PathBuf,
    ) -> Self {
        Self {
            subjects,
            environments,
            reports,
        }
    }

    pub(crate) async fn verify(
        &self,
        contract_id: &str,
        policy: &ReplayPolicy,
        subject: &CapturedSubject,
        environment_id: &str,
        original_sandbox: &FileSystemSandboxContext,
    ) -> Result<ReplayResult, ReplayError> {
        if environment_id != codex_exec_server::LOCAL_ENVIRONMENT_ID {
            return Err(ReplayError::NonLocal);
        }
        let environment = self
            .environments
            .try_local_environment()
            .ok_or(ReplayError::EnvironmentUnavailable)?;
        fs::create_dir_all(&self.reports).map_err(report_error)?;
        let run = tempfile::Builder::new()
            .prefix("run-")
            .tempdir_in(&self.reports)
            .map_err(report_error)?;
        let root = run.path().join("project");
        self.subjects
            .materialize(&subject.coordinate, &root)
            .map_err(|error| ReplayError::Subject(error.to_string()))?;
        let root = AbsolutePathBuf::from_absolute_path_checked(&root)
            .map_err(|error| ReplayError::Path(error.to_string()))?;
        let sandbox = replay_sandbox(original_sandbox, &root)?;

        let mut checks = Vec::with_capacity(policy.checks.len());
        for check in &policy.checks {
            checks.push(run_check(&environment, &root, &sandbox, check).await?);
        }
        let protected = policy
            .protected
            .iter()
            .map(|item| inspect(&root, &item.path, Some(item)))
            .collect::<Result<Vec<_>, _>>()?;
        let artifacts = policy
            .artifacts
            .paths()
            .iter()
            .map(|path| inspect(&root, path, None))
            .collect::<Result<Vec<_>, _>>()?;
        let passed = checks.iter().all(|check| check.exit == check.expected_exit)
            && protected
                .iter()
                .all(|file| file.exists && file.hash == file.expected_hash)
            && artifacts.iter().all(|file| file.exists);
        let policy_hash =
            hash_replay(policy).map_err(|error| ReplayError::Report(error.to_string()))?;
        let report = Report {
            version: 1,
            contract_id: contract_id.to_string(),
            policy_hash: policy_hash.clone(),
            subject_hash: subject.coordinate.hash.clone(),
            passed,
            checks,
            protected,
            artifacts,
        };
        let encoded =
            serde_json::to_vec(&report).map_err(|error| ReplayError::Report(error.to_string()))?;
        let evidence_hash = hex_digest(&encoded);
        let destination = self.reports.join(format!("{evidence_hash}.json"));
        if !destination.exists() {
            let mut temporary = NamedTempFile::new_in(&self.reports).map_err(report_error)?;
            std::io::Write::write_all(&mut temporary, &encoded).map_err(report_error)?;
            match temporary.persist_noclobber(&destination) {
                Ok(_) => {}
                Err(error) if error.error.kind() == std::io::ErrorKind::AlreadyExists => {}
                Err(error) => return Err(report_error(error.error)),
            }
        }
        Ok(ReplayResult {
            policy_hash,
            subject_hash: subject.coordinate.hash.clone(),
            evidence_hash,
            passed,
            summary: if passed {
                "replay verification passed".to_string()
            } else {
                failure_summary(&report)
            },
        })
    }
}

async fn run_check(
    environment: &codex_exec_server::Environment,
    root: &AbsolutePathBuf,
    sandbox: &Option<FileSystemSandboxContext>,
    check: &ReplayCheck,
) -> Result<CheckReport, ReplayError> {
    let cwd = match &check.cwd {
        Some(relative) => AbsolutePathBuf::from_absolute_path_checked(root.join(relative.as_str()))
            .map_err(|error| ReplayError::Path(error.to_string())),
        None => Ok(root.clone()),
    }?;
    if !cwd.as_path().starts_with(root.as_path()) {
        return Err(ReplayError::Path(cwd.display().to_string()));
    }
    let started = environment
        .get_exec_backend()
        .start(ExecParams {
            process_id: ProcessId::from(format!(
                "pro-contract-replay-{}",
                NEXT_PROCESS_ID.fetch_add(1, Ordering::Relaxed)
            )),
            argv: check.argv.clone(),
            cwd: PathUri::from_abs_path(&cwd),
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
            sandbox: sandbox.clone(),
            enforce_managed_network: false,
            managed_network: None,
            network_proxy: None,
        })
        .await
        .map_err(|error| ReplayError::Process(error.to_string()))?;
    let process = started.process;
    let mut events = process.subscribe_events();
    let output = tokio::time::timeout(Duration::from_millis(check.timeout_ms), async {
        let mut stdout = BoundedOutput::default();
        let mut stderr = BoundedOutput::default();
        let mut exit = None;
        loop {
            match events
                .recv()
                .await
                .map_err(|error| ReplayError::Process(error.to_string()))?
            {
                ExecProcessEvent::Output(chunk) => match chunk.stream {
                    ExecOutputStream::Stdout | ExecOutputStream::Pty => {
                        push_bounded(&mut stdout, &chunk.chunk.0)
                    }
                    ExecOutputStream::Stderr => push_bounded(&mut stderr, &chunk.chunk.0),
                },
                ExecProcessEvent::Exited { exit_code, .. } => exit = Some(exit_code),
                ExecProcessEvent::Closed { .. } => break,
                ExecProcessEvent::Failed(error) => return Err(ReplayError::Process(error)),
            }
        }
        Ok::<_, ReplayError>((stdout, stderr, exit.unwrap_or(-1)))
    })
    .await;
    let (stdout, stderr, exit) = match output {
        Ok(result) => result?,
        Err(_) => {
            let _ = process.terminate().await;
            return Err(ReplayError::Timeout(check.timeout_ms));
        }
    };
    Ok(CheckReport {
        argv: check.argv.clone(),
        cwd: check
            .cwd
            .as_ref()
            .map_or_else(|| ".".to_string(), |cwd| cwd.as_str().to_string()),
        expected_exit: check.exit,
        exit,
        stdout_hash: hex_digest(&stdout.bytes),
        stderr_hash: hex_digest(&stderr.bytes),
        stdout_truncated: stdout.truncated,
        stderr_truncated: stderr.truncated,
    })
}

#[derive(Default)]
struct BoundedOutput {
    bytes: Vec<u8>,
    truncated: bool,
}

fn push_bounded(output: &mut BoundedOutput, bytes: &[u8]) {
    let remaining = MAX_OUTPUT_BYTES.saturating_sub(output.bytes.len());
    output
        .bytes
        .extend_from_slice(&bytes[..bytes.len().min(remaining)]);
    output.truncated |= bytes.len() > remaining;
}

fn replay_sandbox(
    original: &FileSystemSandboxContext,
    root: &AbsolutePathBuf,
) -> Result<Option<FileSystemSandboxContext>, ReplayError> {
    let permissions = PermissionProfile::try_from(original.permissions.clone())
        .map_err(|error| ReplayError::Path(error.to_string()))?;
    let permissions = match permissions {
        PermissionProfile::Managed { .. } => Some(
            PermissionProfile::workspace_write()
                .materialize_project_roots_with_workspace_roots(std::slice::from_ref(root)),
        ),
        PermissionProfile::Disabled => None,
        PermissionProfile::External { .. } => {
            return Err(ReplayError::Process(
                "external sandbox cannot protect a host-materialized replay".to_string(),
            ));
        }
    };
    Ok(permissions.map(|permissions| {
        FileSystemSandboxContext::from_permission_profile_with_cwd(
            permissions,
            PathUri::from_abs_path(root),
        )
    }))
}

fn inspect(
    root: &AbsolutePathBuf,
    relative: &codex_pro_contract::ArtifactPath,
    protected: Option<&ProtectedFile>,
) -> Result<FileReport, ReplayError> {
    let target = root.join(relative.as_str());
    if !target.exists() {
        return Ok(FileReport {
            path: relative.as_str().to_string(),
            exists: false,
            hash: None,
            expected_hash: protected.map(|item| item.sha256.clone()),
        });
    }
    let canonical =
        fs::canonicalize(&target).map_err(|error| ReplayError::Path(error.to_string()))?;
    if !canonical.starts_with(root.as_path()) {
        return Ok(FileReport {
            path: relative.as_str().to_string(),
            exists: false,
            hash: None,
            expected_hash: protected.map(|item| item.sha256.clone()),
        });
    }
    let hash = canonical
        .is_file()
        .then(|| fs::read(&canonical))
        .transpose()
        .map_err(|error| ReplayError::Path(error.to_string()))?
        .map(|bytes| hex_digest(&bytes));
    Ok(FileReport {
        path: relative.as_str().to_string(),
        exists: true,
        hash,
        expected_hash: protected.map(|item| item.sha256.clone()),
    })
}

fn failure_summary(report: &Report) -> String {
    if let Some(check) = report
        .checks
        .iter()
        .find(|check| check.exit != check.expected_exit)
    {
        return format!(
            "replay check {} exited {}; expected {}",
            check.argv.join(" "),
            check.exit,
            check.expected_exit
        );
    }
    if let Some(file) = report
        .protected
        .iter()
        .find(|file| !file.exists || file.hash != file.expected_hash)
    {
        return format!("protected file changed or missing: {}", file.path);
    }
    if let Some(file) = report.artifacts.iter().find(|file| !file.exists) {
        return format!("required artifact missing: {}", file.path);
    }
    "unknown replay failure".to_string()
}

fn hex_digest(value: &[u8]) -> String {
    format!("{:x}", Sha256::digest(value))
}

fn report_error(error: std::io::Error) -> ReplayError {
    ReplayError::Report(error.to_string())
}
