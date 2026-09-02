use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ProContractBudget;
use codex_app_server_protocol::ProContractEvidence;
use codex_app_server_protocol::ProContractIssueParams;
use codex_app_server_protocol::ProContractIssueResponse;
use codex_app_server_protocol::ProContractResolution;
use codex_app_server_protocol::ProContractSpec;
use codex_app_server_protocol::ProContractTrigger;
use codex_app_server_protocol::SandboxMode;
use codex_app_server_protocol::ThreadStartParams;
use codex_features::Feature;
use core_test_support::responses;
use serde_json::json;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

#[tokio::test]
async fn native_probe_batch_compares_cases_in_one_model_action() -> Result<()> {
    let reference = format!("reference{}", std::env::consts::EXE_SUFFIX);
    let candidate = format!("candidate{}", std::env::consts::EXE_SUFFIX);
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_response_created("probe-response"),
                responses::ev_function_call(
                    "probe-call",
                    "contract_probe_batch",
                    &json!({
                        "reference": reference,
                        "candidate": candidate,
                        "case_timeout_ms": 5_000,
                        "batch_timeout_ms": 10_000,
                        "cases": [{
                            "id": "write",
                            "args": ["result.json", "same-payload"],
                        }]
                    })
                    .to_string(),
                ),
                responses::ev_completed("probe-response"),
            ]),
            responses::sse(vec![responses::ev_completed("done")]),
        ],
    )
    .await;
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .enable_feature(Feature::ProContract)
        .write(codex_home.path())?;
    let mut app_server = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized()
        .await?;
    let workspace = app_server.auto_env()?.cwd().to_path_buf();
    let executable = codex_utils_cargo_bin::cargo_bin("codex-app-server-test-notify-capture")?;
    std::fs::copy(&executable, workspace.join(&reference))?;
    std::fs::copy(&executable, workspace.join(&candidate))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            workspace.join(&reference),
            std::fs::Permissions::from_mode(0o111),
        )?;
    }
    let thread = app_server
        .start_thread(ThreadStartParams {
            sandbox: Some(SandboxMode::DangerFullAccess),
            ..Default::default()
        })
        .await?
        .thread;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
    let _: ProContractIssueResponse = app_server
        .request(|request_id| ClientRequest::ProContractIssue {
            request_id,
            params: ProContractIssueParams {
                thread_id: thread.id,
                spec: ProContractSpec {
                    trigger: ProContractTrigger::Immediate,
                    goal: "compare the exact candidate".to_string(),
                    brief: "Use the native differential probe.".to_string(),
                    artifacts: Vec::new(),
                    requires: Vec::new(),
                    authority: [
                        "filesystem.read",
                        "filesystem.write",
                        "process.execute",
                        "tool:contract_probe_batch",
                    ]
                    .map(str::to_string)
                    .to_vec(),
                    budget: ProContractBudget {
                        turns: 2,
                        actions: 4,
                        deadline_at: now + 60,
                    },
                    evidence: ProContractEvidence {
                        claim: "the compared scenarios match".to_string(),
                        replay: None,
                    },
                    resolution: ProContractResolution {
                        max_attempts: 1,
                        retry_delay_ms: 0,
                    },
                },
                execution_policy: None,
                original_request: None,
            },
        })
        .await?;
    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        while response_mock.requests().len() < 2 {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;

    let requests = response_mock.requests();
    let output = requests[1].function_call_output("probe-call");
    assert!(
        output["output"]
            .as_str()
            .is_some_and(|output| output.contains("\"matchedCount\":1"))
    );
    Ok(())
}
