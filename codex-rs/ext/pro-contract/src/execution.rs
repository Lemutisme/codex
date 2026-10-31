//! A bounded host action with durable observations and an explicit effect/lifecycle receipt.
//! A started journal without an end receipt means unknown, never "did not execute". Callers
//! decide whether replay is authorized; this module never retries or renews a grant.

use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use codex_pro_contract::Digest;
use serde::Deserialize;
use serde::Serialize;
use tokio::io::AsyncRead;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::process::Command;

const STREAM_CAP: usize = 32 << 20;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExecutionState {
    Running,
    Completed,
    Failed,
    TimedOut,
    Cancelled,
    Unknown,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionReceipt {
    pub run_id: String,
    pub binding: Digest,
    pub state: ExecutionState,
    pub started_ms: u64,
    pub finished_ms: Option<u64>,
    pub exit_code: Option<i32>,
    pub shutdown_confirmed: bool,
    pub stdout_digest: Option<Digest>,
    pub stderr_digest: Option<Digest>,
    pub truncated: bool,
    pub detail: String,
}

impl ExecutionReceipt {
    pub fn completed(&self) -> bool {
        self.state == ExecutionState::Completed && self.shutdown_confirmed && !self.truncated
    }
}

pub(crate) struct Output {
    pub receipt: ExecutionReceipt,
    pub stdout: String,
    pub stderr: String,
}

impl std::ops::Deref for Output {
    type Target = str;
    fn deref(&self) -> &str {
        &self.stdout
    }
}

/// Host-authored cleanup, never supplied by the inspected program or model.
pub(crate) struct Cleanup {
    pub program: String,
    pub args: Vec<String>,
    armed: bool,
}

impl Cleanup {
    pub fn new(program: String, args: Vec<String>) -> Self {
        Self {
            program,
            args,
            armed: true,
        }
    }

    async fn finish(&mut self) -> bool {
        let done = cleanup(&self.program, &self.args).await;
        if done {
            self.armed = false;
        }
        done
    }
}

async fn cleanup(program: &str, args: &[String]) -> bool {
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        Command::new(program)
            .args(args)
            .stdin(std::process::Stdio::null())
            .kill_on_drop(true)
            .output(),
    )
    .await;
    result.is_ok_and(|result| {
        result.is_ok_and(|output| {
            output.status.success()
                || (args.len() == 3
                    && args[0] == "rm"
                    && args[1] == "-f"
                    && String::from_utf8_lossy(&output.stderr).trim()
                        == format!("Error response from daemon: No such container: {}", args[2]))
        })
    })
}

pub(crate) struct ProcessGroup(Option<u32>);
impl ProcessGroup {
    pub fn new(pid: Option<u32>) -> std::io::Result<Self> {
        Ok(Self(Some(pid.ok_or_else(|| {
            std::io::Error::other("missing process identity")
        })?)))
    }

    pub fn stop(&mut self) {
        let Some(pid) = self.0.take() else {
            return;
        };
        #[cfg(not(unix))]
        let _ = pid;
        #[cfg(unix)]
        // SAFETY: the child is created in a new process group whose ID is its PID.
        unsafe {
            libc::kill(-(pid as i32), libc::SIGKILL);
        }
    }
}
impl Drop for ProcessGroup {
    fn drop(&mut self) {
        self.stop();
    }
}

impl Drop for Cleanup {
    fn drop(&mut self) {
        if self.armed
            && let Ok(runtime) = tokio::runtime::Handle::try_current()
        {
            let program = self.program.clone();
            let args = self.args.clone();
            runtime.spawn(async move {
                cleanup(&program, &args).await;
            });
        }
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or_default()
}

async fn publish(path: &Path, receipt: &ExecutionReceipt) -> std::io::Result<()> {
    let temporary = path.with_extension("tmp");
    let mut file = tokio::fs::File::create(&temporary).await?;
    file.write_all(&serde_json::to_vec(receipt)?).await?;
    file.sync_all().await?;
    tokio::fs::rename(temporary, path).await
}

async fn capture(
    mut stream: impl AsyncRead + Unpin,
    path: PathBuf,
) -> std::io::Result<(Vec<u8>, bool)> {
    let mut file = tokio::fs::File::create(path).await?;
    let mut bytes = Vec::new();
    let mut buffer = [0; 8192];
    let mut truncated = false;
    loop {
        let count = stream.read(&mut buffer).await?;
        if count == 0 {
            break;
        }
        let keep = count.min(STREAM_CAP.saturating_sub(bytes.len()));
        truncated |= keep < count;
        if keep > 0 {
            file.write_all(&buffer[..keep]).await?;
            file.sync_data().await?;
            bytes.extend_from_slice(&buffer[..keep]);
        }
    }
    Ok((bytes, truncated))
}

/// Cancellation requests shutdown; the action owner retains the terminal observation even
/// when its caller is gone. Process loss can still leave unknown effects, never a replay grant.
pub(crate) async fn run(
    command: Command,
    directory: &Path,
    binding: Digest,
    timeout: Duration,
    cleanup: Option<Cleanup>,
) -> std::io::Result<Output> {
    let (cancel, cancelled) = tokio::sync::oneshot::channel();
    let directory = directory.to_path_buf();
    // Dropping the sender (including aborting this caller) wakes the owned action.
    // Its JoinHandle may be dropped, but finalization is not owned by that handle.
    let action = tokio::spawn(async move {
        run_owned(command, &directory, binding, timeout, cleanup, cancelled).await
    });
    let result = action.await.map_err(std::io::Error::other)?;
    drop(cancel);
    result
}

async fn run_owned(
    mut command: Command,
    directory: &Path,
    binding: Digest,
    timeout: Duration,
    mut cleanup: Option<Cleanup>,
    mut cancelled: tokio::sync::oneshot::Receiver<()>,
) -> std::io::Result<Output> {
    tokio::fs::create_dir(directory).await?;
    let path = directory.join("execution.json");
    let mut receipt = ExecutionReceipt {
        run_id: format!(
            "action-{}",
            crate::digest_of("action_identity", &(binding, directory, now_ms()))
        ),
        binding,
        state: ExecutionState::Running,
        started_ms: now_ms(),
        finished_ms: None,
        exit_code: None,
        shutdown_confirmed: false,
        stdout_digest: None,
        stderr_digest: None,
        truncated: false,
        detail: String::new(),
    };
    publish(&path, &receipt).await?;
    command
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true);
    #[cfg(unix)]
    command.process_group(0);
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            receipt.state = ExecutionState::Failed;
            receipt.detail = format!("action was not started: {error}");
            receipt.shutdown_confirmed = true;
            receipt.finished_ms = Some(now_ms());
            if let Some(cleanup) = &mut cleanup {
                cleanup.armed = false;
            }
            publish(&path, &receipt).await?;
            return Ok(Output {
                receipt,
                stdout: String::new(),
                stderr: error.to_string(),
            });
        }
    };
    let mut group = ProcessGroup::new(child.id())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| std::io::Error::other("missing stdout"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| std::io::Error::other("missing stderr"))?;
    let mut out = tokio::spawn(capture(stdout, directory.join("stdout")));
    let mut err = tokio::spawn(capture(stderr, directory.join("stderr")));
    let outcome = tokio::select! {
        result = tokio::time::timeout(timeout, child.wait()) => Some(result),
        _ = &mut cancelled => None,
    };
    match outcome {
        Some(Ok(Ok(status))) => {
            receipt.exit_code = status.code();
            receipt.state = if status.success() {
                ExecutionState::Completed
            } else {
                ExecutionState::Failed
            };
            receipt.shutdown_confirmed = true;
            if !status.success() {
                receipt.detail = format!("action exited {status}");
            }
            // Container --rm confirms its end before the CLI returns. Cleanup is needed only
            // for timeout/cancellation; removing an already removed container returns nonzero.
            if let Some(cleanup) = &mut cleanup {
                if status.success() {
                    cleanup.armed = false;
                } else {
                    receipt.shutdown_confirmed = cleanup.finish().await;
                    if !receipt.shutdown_confirmed {
                        receipt.state = ExecutionState::Unknown;
                    }
                }
            }
        }
        outcome => {
            receipt.state = if outcome.is_none() {
                ExecutionState::Cancelled
            } else if outcome.as_ref().is_some_and(Result::is_err) {
                ExecutionState::TimedOut
            } else {
                ExecutionState::Unknown
            };
            receipt.detail = if outcome.is_none() {
                "action caller cancelled; shutdown observed independently".into()
            } else if outcome.as_ref().is_some_and(Result::is_err) {
                "action deadline exceeded".into()
            } else {
                "action exit could not be observed".into()
            };
            receipt.shutdown_confirmed = match &mut cleanup {
                Some(cleanup) => cleanup.finish().await,
                None => true,
            };
            receipt.shutdown_confirmed &=
                child.kill().await.is_ok() || child.try_wait().is_ok_and(|s| s.is_some());
            if !receipt.shutdown_confirmed {
                receipt.state = ExecutionState::Unknown;
            }
        }
    }
    group.stop();
    let (captured_out, captured_err) = tokio::join!(
        tokio::time::timeout(Duration::from_secs(5), &mut out),
        tokio::time::timeout(Duration::from_secs(5), &mut err)
    );
    out.abort();
    err.abort();
    // A stream error must not skip the lifecycle receipt. Retained partial bytes
    // remain observations; they do not certify complete output.
    let mut collected = Vec::new();
    for (result, name) in [(captured_out, "stdout"), (captured_err, "stderr")] {
        let result = result
            .map_err(std::io::Error::other)
            .and_then(|r| r.map_err(std::io::Error::other))
            .and_then(|r| r);
        collected.push(match result {
            Ok(value) => value,
            Err(error) => {
                receipt
                    .detail
                    .push_str(&format!("; {name} capture incomplete: {error}"));
                (
                    tokio::fs::read(directory.join(name))
                        .await
                        .unwrap_or_default(),
                    true,
                )
            }
        });
    }
    let (stderr, err_truncated) = collected.pop().unwrap_or_default();
    let (stdout, out_truncated) = collected.pop().unwrap_or_default();
    receipt.stdout_digest = Some(Digest::of(&stdout));
    receipt.stderr_digest = Some(Digest::of(&stderr));
    receipt.truncated = out_truncated || err_truncated;
    receipt.finished_ms = Some(now_ms());
    publish(&path, &receipt).await?;
    Ok(Output {
        receipt,
        stdout: String::from_utf8_lossy(&stdout).into_owned(),
        stderr: String::from_utf8_lossy(&stderr).into_owned(),
    })
}

#[cfg(test)]
#[path = "execution_tests.rs"]
mod tests;
