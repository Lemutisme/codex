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
use pretty_assertions::assert_eq;
use serde_json::json;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

#[tokio::test]
async fn native_probe_batch_compares_cases_in_one_model_action() -> Result<()> {
    let reference = format!("reference{}", std::env::consts::EXE_SUFFIX);
    let candidate = format!("candidate{}", std::env::consts::EXE_SUFFIX);
    let alternate = format!("candidate-alternate{}", std::env::consts::EXE_SUFFIX);
    let probe_arguments = |candidate: &str| {
        json!({
            "reference": reference,
            "candidate": candidate,
            "case_timeout_ms": 5_000,
            "batch_timeout_ms": 10_000,
            "cases": [{
                "id": "write",
                "args": ["result.json", "same-payload"],
            }]
        })
        .to_string()
    };
    let first_arguments = probe_arguments(&candidate);
    let alternate_arguments = probe_arguments(&alternate);
    let probe_response = |response_id, call_id, arguments: &str| {
        responses::sse(vec![
            responses::ev_response_created(response_id),
            responses::ev_function_call(call_id, "contract_probe_batch", arguments),
            responses::ev_completed(response_id),
        ])
    };
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_sequence(
        &server,
        vec![
            probe_response("probe-response-1", "probe-call-1", &first_arguments),
            probe_response("probe-response-2", "probe-call-2", &first_arguments),
            probe_response("probe-response-3", "probe-call-3", &alternate_arguments),
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
    std::fs::copy(&executable, workspace.join(&alternate))?;
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
                        turns: 4,
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
        while response_mock.requests().len() < 4 {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;

    let requests = response_mock.requests();
    assert!(!requests[1].body_contains_text("Host action telemetry:"));
    assert!(requests[2].body_contains_text(
        "exact `contract_probe_batch` request occurrence 2 in this semantic attempt"
    ));
    let first = requests[1].function_call_output("probe-call-1");
    let first: serde_json::Value = serde_json::from_str(
        first["output"]
            .as_str()
            .expect("first probe should return JSON"),
    )?;
    let second = requests[2].function_call_output("probe-call-2");
    let second: serde_json::Value = serde_json::from_str(
        second["output"]
            .as_str()
            .expect("second probe should return JSON"),
    )?;
    let third = requests[3].function_call_output("probe-call-3");
    let third: serde_json::Value = serde_json::from_str(
        third["output"]
            .as_str()
            .expect("third probe should return JSON"),
    )?;
    assert_eq!(
        json!({
            "caseCount": first["caseCount"],
            "executionCount": first["executionCount"],
            "byteEqualCount": first["byteEqualCount"],
            "frontier": first["frontier"],
        }),
        json!({
            "caseCount": 1,
            "executionCount": 2,
            "byteEqualCount": 1,
            "frontier": {
                "candidateCoordinateChanged": false,
                "newAttemptRequestCount": 1,
                "newCandidateRequestCount": 1,
                "repeatedCandidateRequestCount": 0,
                "attemptUniqueRequestCount": 1,
                "candidateUniqueRequestCount": 1,
                "attemptReportCount": 1,
                "attemptExecutionCount": 2,
                "attemptWallDurationMs": first["wallDurationMs"],
            },
        })
    );
    assert_eq!(
        json!({
            "candidateHash": second["candidateHash"],
            "candidateCoordinateHash": second["candidateCoordinateHash"],
            "frontier": second["frontier"],
        }),
        json!({
            "candidateHash": first["candidateHash"],
            "candidateCoordinateHash": first["candidateCoordinateHash"],
            "frontier": {
                "candidateCoordinateChanged": false,
                "newAttemptRequestCount": 0,
                "newCandidateRequestCount": 0,
                "repeatedCandidateRequestCount": 1,
                "attemptUniqueRequestCount": 1,
                "candidateUniqueRequestCount": 1,
                "attemptReportCount": 2,
                "attemptExecutionCount": 4,
                "attemptWallDurationMs": first["wallDurationMs"].as_u64().unwrap()
                    + second["wallDurationMs"].as_u64().unwrap(),
            },
        })
    );
    assert_eq!(
        json!({
            "sameContent": third["candidateHash"] == first["candidateHash"],
            "differentCoordinate": third["candidateCoordinateHash"]
                != first["candidateCoordinateHash"],
            "frontier": third["frontier"],
        }),
        json!({
            "sameContent": true,
            "differentCoordinate": true,
            "frontier": {
                "candidateCoordinateChanged": true,
                "newAttemptRequestCount": 0,
                "newCandidateRequestCount": 1,
                "repeatedCandidateRequestCount": 0,
                "attemptUniqueRequestCount": 1,
                "candidateUniqueRequestCount": 1,
                "attemptReportCount": 3,
                "attemptExecutionCount": 6,
                "attemptWallDurationMs": first["wallDurationMs"].as_u64().unwrap()
                    + second["wallDurationMs"].as_u64().unwrap()
                    + third["wallDurationMs"].as_u64().unwrap(),
            },
        })
    );
    Ok(())
}
