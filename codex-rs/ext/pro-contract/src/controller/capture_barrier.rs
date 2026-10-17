//! A provisioner-owned container freeze, separate from artifact hashing.
//! The caller reserves a durable publication before acquiring this barrier.

use std::time::Duration;
use tokio::process::Command;

use crate::EvaluationProfile;

pub(crate) struct CaptureBarrier {
    docker: String,
    ids: Vec<String>,
}

async fn docker(program: &str, args: &[&str]) -> Result<String, String> {
    let output = tokio::time::timeout(
        Duration::from_secs(10),
        Command::new(program).args(args).kill_on_drop(true).output(),
    )
    .await
    .map_err(|_| "capture barrier command timed out")?
    .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(format!(
            "capture barrier command failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    String::from_utf8(output.stdout).map_err(|e| e.to_string())
}

impl CaptureBarrier {
    pub(crate) async fn acquire(profile: &EvaluationProfile, label: &str) -> Result<Self, String> {
        if !label.starts_with("procontract.task=")
            || label.len() > 128
            || !label
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b".=_-".contains(&b))
        {
            return Err("invalid provisioner capture label".into());
        }
        let ids: Vec<String> = docker(
            &profile.check.docker,
            &[
                "ps",
                "--no-trunc",
                "--filter",
                &format!("label={label}"),
                "--format",
                "{{.ID}}",
            ],
        )
        .await?
        .lines()
        .map(str::to_string)
        .collect();
        // The initial adapter requires one exclusively owned workspace executor.
        // It never guesses which of several live writers is safe to freeze.
        if ids.len() != 1
            || ids
                .iter()
                .any(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
        {
            return Err("capture requires exactly one provisioned workspace executor".into());
        }
        let metadata: serde_json::Value =
            serde_json::from_str(&docker(&profile.check.docker, &["inspect", &ids[0]]).await?)
                .map_err(|e| e.to_string())?;
        let container = &metadata[0];
        let mounted = container["Mounts"].as_array().is_some_and(|mounts| {
            mounts.iter().any(|mount| {
                mount["Source"].as_str() == profile.workspace_host_root.to_str()
                    && mount["Destination"] == profile.workspace_container_root
                    && mount["RW"] == true
            })
        });
        if !mounted
            || container["State"]["Running"] != true
            || container["State"]["Paused"] != false
        {
            return Err(
                "capture executor identity, mount or lifecycle does not match the grant".into(),
            );
        }
        let barrier = Self {
            docker: profile.check.docker.clone(),
            ids,
        };
        // Arm cleanup before dispatch: cancellation cannot leave a known container frozen.
        docker(&barrier.docker, &["pause", &barrier.ids[0]]).await?;
        let paused = docker(
            &barrier.docker,
            &["inspect", "--format", "{{.State.Paused}}", &barrier.ids[0]],
        )
        .await?;
        if paused.trim() != "true" {
            return Err("executor freeze was not confirmed".into());
        }
        Ok(barrier)
    }

    pub(crate) fn identities(&self) -> &[String] {
        &self.ids
    }

    pub(crate) async fn resume(mut self) -> Result<(), String> {
        for id in &self.ids {
            docker(&self.docker, &["unpause", id]).await?;
            if docker(
                &self.docker,
                &["inspect", "--format", "{{.State.Paused}}", id],
            )
            .await?
            .trim()
                != "false"
            {
                return Err("executor unfreeze was not confirmed".into());
            }
        }
        self.ids.clear();
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn test_only() -> Self {
        Self {
            docker: String::new(),
            ids: Vec::new(),
        }
    }
}

impl Drop for CaptureBarrier {
    fn drop(&mut self) {
        if !self.ids.is_empty()
            && let Ok(runtime) = tokio::runtime::Handle::try_current()
        {
            let program = self.docker.clone();
            let ids = std::mem::take(&mut self.ids);
            runtime.spawn(async move {
                for id in ids {
                    let _ = docker(&program, &["unpause", &id]).await;
                }
            });
        }
    }
}
