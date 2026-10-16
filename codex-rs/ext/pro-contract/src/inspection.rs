//! Host-granted computation over immutable evidence. Uses the existing isolated check runtime;
//! the worker supplies code and source IDs, never mounts, credentials or host executable paths.

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;

use codex_pro_contract::Digest;
use serde_json::json;

use crate::CheckEnvironment;
use crate::ReviewExecution;
use crate::digest_of;

pub(crate) struct Computation<'a> {
    pub subject: Digest,
    pub requirements: &'a [String],
    pub sources: &'a [(String, Vec<u8>)],
    pub python: &'a str,
    pub remaining: Duration,
}

async fn readonly(path: &Path) -> Result<(), String> {
    let mut permissions = tokio::fs::metadata(path)
        .await
        .map_err(|e| e.to_string())?
        .permissions();
    #[cfg(unix)]
    permissions.set_mode(0o444);
    #[cfg(not(unix))]
    permissions.set_readonly(true);
    tokio::fs::set_permissions(path, permissions)
        .await
        .map_err(|e| e.to_string())
}

pub(crate) async fn compute(
    env: &CheckEnvironment,
    grant: &ReviewExecution,
    directory: &Path,
    request: Computation<'_>,
) -> Result<serde_json::Value, String> {
    let Computation {
        subject,
        requirements,
        sources,
        python,
        remaining,
    } = request;
    let started = std::time::Instant::now();
    let source_dir = directory.join("sources");
    tokio::fs::create_dir(directory)
        .await
        .map_err(|e| e.to_string())?;
    tokio::fs::create_dir(&source_dir)
        .await
        .map_err(|e| e.to_string())?;
    let mut inputs = Vec::new();
    for (id, bytes) in sources {
        let name = id.replace(':', "-");
        let path = source_dir.join(&name);
        tokio::fs::write(&path, bytes)
            .await
            .map_err(|e| e.to_string())?;
        readonly(&path).await?;
        inputs.push(json!({"source_id":id,"path":format!("/evidence/{name}"),"sha256":Digest::of(bytes),"bytes":bytes.len()}));
    }
    let program = directory.join("inspection.py");
    tokio::fs::write(&program, python)
        .await
        .map_err(|e| e.to_string())?;
    readonly(&program).await?;
    // Resolve a local image before executing; the inspected program has no public network.
    let pinned = crate::checks::pin_environment(
        env,
        remaining
            .saturating_sub(started.elapsed())
            .min(Duration::from_secs(10)),
    )
    .await
    .map_err(|e| e.to_string())?;
    let image = pinned.image;
    let name = crate::checks::unique_name();
    let binding = digest_of(
        "frozen_computation_v1",
        &(
            &subject,
            requirements,
            &inputs,
            python,
            &image,
            &env.user,
            grant,
        ),
    );
    let mut command = tokio::process::Command::new(&env.docker);
    command
        .args([
            "run",
            "--rm",
            "--name",
            &name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--user",
            &env.user,
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=134217728,mode=1777",
            "-e",
            "HOME=/tmp",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-w",
            "/tmp",
            "-v",
        ])
        .arg(format!("{}:/evidence:ro", source_dir.display()))
        .arg("-v")
        .arg(format!("{}:/inspection.py:ro", program.display()))
        .args(["--entrypoint", "python3", &image, "-I", "/inspection.py"]);
    let available = remaining
        .saturating_sub(started.elapsed())
        .min(Duration::from_secs(grant.timeout_secs));
    if available.is_zero() {
        return Err("original worker deadline exhausted before computation".into());
    }
    let output = crate::execution::run(
        command,
        &directory.join("action"),
        binding,
        available,
        Some(crate::execution::Cleanup::new(
            env.docker.clone(),
            vec!["rm".into(), "-f".into(), name],
        )),
    )
    .await
    .map_err(|e| e.to_string())?;
    let out_cap = grant.max_output_bytes - output.stderr.len().min(grant.max_output_bytes / 2);
    let err_cap = grant.max_output_bytes - output.stdout.len().min(out_cap);
    let truncated = output.stdout.len() > out_cap || output.stderr.len() > err_cap;
    let stdout = crate::workers::bounded_head_tail(&output.stdout, out_cap);
    let stderr = crate::workers::bounded_head_tail(&output.stderr, err_cap);
    Ok(
        json!({"schema":1,"subject_hash":subject,"requirements":requirements,"inputs":inputs,
        "program_sha256":Digest::of(python.as_bytes()),"program":python,"image_id":image,
        "execution":output.receipt,"stdout":stdout,"stderr":stderr,"output_truncated":truncated,
        "interpretation":"An observed computation, not an automatic theorem proof or permission to settle."}),
    )
}
