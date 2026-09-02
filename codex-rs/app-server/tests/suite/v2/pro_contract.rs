use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ProContractAttestParams;
use codex_app_server_protocol::ProContractAttestResponse;
use codex_app_server_protocol::ProContractBudget;
use codex_app_server_protocol::ProContractChallengeDisclosure;
use codex_app_server_protocol::ProContractChallengeParams;
use codex_app_server_protocol::ProContractChallengeResponse;
use codex_app_server_protocol::ProContractEvidence;
use codex_app_server_protocol::ProContractHandoffMaterializeParams;
use codex_app_server_protocol::ProContractHandoffMaterializeResponse;
use codex_app_server_protocol::ProContractIssueParams;
use codex_app_server_protocol::ProContractIssueResponse;
use codex_app_server_protocol::ProContractReadParams;
use codex_app_server_protocol::ProContractReadResponse;
use codex_app_server_protocol::ProContractResolution;
use codex_app_server_protocol::ProContractRevisionDecideParams;
use codex_app_server_protocol::ProContractRevisionDecideResponse;
use codex_app_server_protocol::ProContractRevisionDecision;
use codex_app_server_protocol::ProContractSpec;
use codex_app_server_protocol::ProContractStatus;
use codex_app_server_protocol::ProContractTrigger;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadStartParams;
use codex_features::Feature;
use codex_utils_path_uri::LegacyAppPathString;
use core_test_support::responses;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tempfile::TempDir;

#[tokio::test]
async fn principal_rpc_runs_isolated_semantic_attempts_with_one_policy_projection() -> Result<()> {
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_sequence(
        &server,
        (1..=3)
            .map(|attempt| {
                responses::sse(vec![
                    responses::ev_response_created(&format!("response-{attempt}")),
                    responses::ev_assistant_message(
                        &format!("message-{attempt}"),
                        &format!("attempt {attempt} ended"),
                    ),
                    responses::ev_completed(&format!("response-{attempt}")),
                ])
            })
            .collect(),
    )
    .await;
    let codex_home = TempDir::new()?;
    let workspace = TempDir::new()?;
    MockResponsesConfig::new(&server.uri())
        .enable_feature(Feature::ProContract)
        .write(codex_home.path())?;
    let mut app_server = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized()
        .await?;
    let thread = app_server
        .start_thread(ThreadStartParams {
            cwd: Some(workspace.path().display().to_string()),
            ..Default::default()
        })
        .await?
        .thread;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
    let issued: ProContractIssueResponse = app_server
        .request(|request_id| ClientRequest::ProContractIssue {
            request_id,
            params: ProContractIssueParams {
                thread_id: thread.id.clone(),
                spec: ProContractSpec {
                    trigger: ProContractTrigger::Immediate,
                    goal: "perform the contracted task".to_string(),
                    brief: "Use the isolated executor.".to_string(),
                    artifacts: Vec::new(),
                    requires: Vec::new(),
                    authority: vec![
                        "filesystem.read".to_string(),
                        "filesystem.write".to_string(),
                        "process.execute".to_string(),
                    ],
                    budget: ProContractBudget {
                        turns: 10,
                        actions: 20,
                        deadline_at: now + 60,
                    },
                    evidence: ProContractEvidence {
                        claim: "deliver".to_string(),
                        replay: None,
                    },
                    resolution: ProContractResolution {
                        max_attempts: 3,
                        retry_delay_ms: 0,
                    },
                },
                execution_policy: Some(
                    "Run one broad representative check, then repair concrete residuals."
                        .to_string(),
                ),
                original_request: Some("perform the contracted task".to_string()),
            },
        })
        .await?;
    assert_eq!(issued.contract.status, ProContractStatus::Active);
    assert_ne!(
        issued.execution.executor_thread_id.as_deref(),
        Some(thread.id.as_str())
    );
    assert_eq!(issued.execution.attempts, 1);
    assert!(issued.execution.dispatched);
    assert!(issued.contract.spec.brief.contains("Original request:"));

    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        while response_mock.requests().len() < 3 {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let requests = response_mock.requests();
    assert_eq!(requests.len(), 3);
    let marker = "<pro_contract_execution_policy>";
    for request in &requests {
        let body = request.body_json();
        let instructions = body["instructions"].as_str().expect("instructions");
        assert!(instructions.contains("bounded executor for one admitted ProContract"));
        assert!(instructions.contains("fresh uniquely named scratch paths"));
        assert!(!instructions.contains("# Personality"));
        assert_eq!(body.to_string().matches(marker).count(), 1);
        assert!(request.body_contains_text("Original request:"));
        assert!(request.body_contains_text("perform the contracted task"));
        let tool_names = body["tools"]
            .as_array()
            .expect("tools")
            .iter()
            .filter_map(|tool| tool["name"].as_str())
            .collect::<Vec<_>>();
        assert!(
            tool_names.contains(&"contract_report_ready"),
            "{tool_names:?}"
        );
        assert!(tool_names.contains(&"exec_command"), "{tool_names:?}");
        assert!(!tool_names.contains(&"contract_probe_batch"));
        assert!(!tool_names.contains(&"contract_propose"), "{tool_names:?}");
        assert!(
            !tool_names.contains(&"request_user_input"),
            "{tool_names:?}"
        );
        assert!(!tool_names.contains(&"web_search"), "{tool_names:?}");
        assert!(!tool_names.contains(&"multi_agent_v1"), "{tool_names:?}");
    }
    let escalated = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: issued.contract.id.clone(),
                    },
                })
                .await
                .expect("read contract");
            if response.contract.status == ProContractStatus::Escalated {
                break response;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert!(
        escalated
            .contract
            .escalation
            .is_some_and(|escalation| escalation.reason.contains("attempt budget"))
    );
    assert!(!escalated.quiet.quiet);
    Ok(())
}

#[tokio::test]
async fn executor_challenge_starts_a_residual_attempt_without_losing_policy() -> Result<()> {
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_sequence(
        &server,
        (1..=2)
            .map(|attempt| {
                responses::sse(vec![
                    responses::ev_response_created(&format!("response-{attempt}")),
                    responses::ev_function_call(
                        &format!("ready-{attempt}"),
                        "contract_report_ready",
                        &serde_json::json!({
                            "summary": format!("candidate {attempt}"),
                            "uncertainties": []
                        })
                        .to_string(),
                    ),
                    responses::ev_completed(&format!("response-{attempt}")),
                ])
            })
            .collect(),
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
    let thread = app_server
        .start_thread(ThreadStartParams::default())
        .await?
        .thread;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
    let issued: ProContractIssueResponse = app_server
        .request(|request_id| ClientRequest::ProContractIssue {
            request_id,
            params: ProContractIssueParams {
                thread_id: thread.id.clone(),
                spec: ProContractSpec {
                    trigger: ProContractTrigger::Immediate,
                    goal: "repair verifier residuals".to_string(),
                    brief: "Hand off an exact candidate.".to_string(),
                    artifacts: Vec::new(),
                    requires: Vec::new(),
                    authority: vec!["filesystem.read".to_string()],
                    budget: ProContractBudget {
                        turns: 4,
                        actions: 4,
                        deadline_at: now + 60,
                    },
                    evidence: ProContractEvidence {
                        claim: "the exact candidate satisfies the request".to_string(),
                        replay: None,
                    },
                    resolution: ProContractResolution {
                        max_attempts: 2,
                        retry_delay_ms: 0,
                    },
                },
                execution_policy: Some(
                    "Run one broad check, then preserve concrete verifier residuals.".to_string(),
                ),
                original_request: Some("repair verifier residuals".to_string()),
            },
        })
        .await?;
    let policy_hash = issued
        .execution
        .execution_policy_hash
        .clone()
        .expect("execution policy hash");
    assert_eq!(policy_hash.len(), 64);
    let first_executor = issued.execution.executor_thread_id.clone();
    let first = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: issued.contract.id.clone(),
                    },
                })
                .await
                .expect("read first handoff");
            if response.contract.status == ProContractStatus::Verification {
                break response;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let first_subject = first
        .contract
        .handoff
        .as_ref()
        .expect("first handoff")
        .subject
        .hash
        .clone();
    let challenged: ProContractChallengeResponse = app_server
        .request(|request_id| ClientRequest::ProContractChallenge {
            request_id,
            params: ProContractChallengeParams {
                thread_id: thread.id.clone(),
                contract_id: issued.contract.id.clone(),
                revision: first.contract.revision,
                subject_hash: first_subject,
                evidence_hash: "verifier-residual-1".to_string(),
                disclosure: ProContractChallengeDisclosure::Executor,
                summary: Some("case 17 still differs".to_string()),
            },
        })
        .await?;
    assert!(!challenged.quiet.quiet);

    let second = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: issued.contract.id.clone(),
                    },
                })
                .await
                .expect("read residual handoff");
            if response.contract.status == ProContractStatus::Verification
                && response
                    .execution
                    .as_ref()
                    .is_some_and(|execution| execution.attempts == 2)
            {
                break response;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert_ne!(
        second
            .execution
            .as_ref()
            .and_then(|execution| execution.executor_thread_id.as_ref()),
        first_executor.as_ref()
    );
    assert_eq!(
        second
            .execution
            .as_ref()
            .and_then(|execution| execution.execution_policy_hash.as_ref()),
        Some(&policy_hash)
    );
    let requests = response_mock.requests();
    assert_eq!(requests.len(), 2);
    assert!(requests[1].body_contains_text("case 17 still differs"));
    assert!(requests.iter().all(|request| {
        request
            .body_json()
            .to_string()
            .matches("<pro_contract_execution_policy>")
            .count()
            == 1
    }));
    Ok(())
}

#[tokio::test]
async fn principal_rpc_issues_and_settles_without_a_model_authored_proposal() -> Result<()> {
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_once(
        &server,
        responses::sse(vec![
            responses::ev_response_created("executor-response"),
            responses::ev_function_call(
                "report-ready",
                "contract_report_ready",
                &serde_json::json!({
                    "summary": "frozen candidate ready",
                    "uncertainties": []
                })
                .to_string(),
            ),
            responses::ev_completed("executor-response"),
        ]),
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
    std::fs::write(app_server.auto_env()?.cwd().join("result"), "candidate")?;
    let thread = app_server
        .start_thread(ThreadStartParams::default())
        .await?
        .thread;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
    let issue_params = ProContractIssueParams {
        thread_id: thread.id.clone(),
        spec: ProContractSpec {
            trigger: ProContractTrigger::Immediate,
            goal: "deliver the exact result".to_string(),
            brief: "Return the already prepared result for independent verification.".to_string(),
            artifacts: vec!["result".to_string()],
            requires: Vec::new(),
            authority: vec!["filesystem.read".to_string()],
            budget: ProContractBudget {
                turns: 4,
                actions: 8,
                deadline_at: now + 60,
            },
            evidence: ProContractEvidence {
                claim: "the frozen result is the requested delivery".to_string(),
                replay: None,
            },
            resolution: ProContractResolution {
                max_attempts: 2,
                retry_delay_ms: 0,
            },
        },
        execution_policy: Some("Inspect once, then hand off the exact subject.".to_string()),
        original_request: Some("Deliver result for independent verification.".to_string()),
    };
    let issued: ProContractIssueResponse = app_server
        .request(|request_id| ClientRequest::ProContractIssue {
            request_id,
            params: issue_params,
        })
        .await?;
    assert_eq!(issued.contract.status, ProContractStatus::Active);
    assert!(issued.execution.dispatched);
    assert_eq!(issued.execution.attempts, 1);
    assert!(!issued.quiet.quiet);
    assert_eq!(issued.compiler_manifest_hash.len(), 64);

    tokio::time::timeout(std::time::Duration::from_secs(10), async {
        while response_mock.requests().is_empty() {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let contract_id = issued.contract.id;
    let handed_off = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: contract_id.clone(),
                    },
                })
                .await
                .expect("read contract");
            if response.contract.status == ProContractStatus::Verification {
                break response;
            }
            assert_ne!(
                response.contract.status,
                ProContractStatus::Escalated,
                "handoff unexpectedly escalated: {:?}",
                response.contract.escalation
            );
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert!(handed_off.contract.handoff.is_some());
    assert!(!handed_off.quiet.quiet);
    let revision = handed_off.contract.revision;
    let spec_hash = handed_off.contract.spec_hash.clone();
    let subject_hash = handed_off
        .contract
        .handoff
        .as_ref()
        .expect("handoff")
        .subject
        .hash
        .clone();
    std::fs::write(app_server.auto_env()?.cwd().join("result"), "mutated")?;
    let export_root = TempDir::new()?;
    let export = export_root.path().join("frozen");
    let materialized: ProContractHandoffMaterializeResponse = app_server
        .request(|request_id| ClientRequest::ProContractHandoffMaterialize {
            request_id,
            params: ProContractHandoffMaterializeParams {
                thread_id: thread.id.clone(),
                contract_id: contract_id.clone(),
                destination: LegacyAppPathString::from_path(&export),
            },
        })
        .await?;
    assert_eq!(materialized.subject.hash, subject_hash);
    assert_eq!(std::fs::read_to_string(export.join("result"))?, "candidate");
    let stale_request = app_server
        .send_raw_request(
            "proContract/attest",
            Some(serde_json::to_value(ProContractAttestParams {
                thread_id: thread.id.clone(),
                contract_id: contract_id.clone(),
                revision,
                spec_hash: spec_hash.clone(),
                subject_hash: "stale-subject".to_string(),
                evidence_hash: "stale-evaluator-report".to_string(),
            })?),
        )
        .await;
    let stale_error = app_server
        .read_stream_until_error_message(RequestId::Integer(stale_request?))
        .await?;
    assert!(
        stale_error
            .error
            .message
            .contains("coordinate does not match")
    );
    app_server.shutdown_gracefully().await?;
    let mut app_server = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized()
        .await?;

    let settled: ProContractAttestResponse = app_server
        .request(|request_id| ClientRequest::ProContractAttest {
            request_id,
            params: ProContractAttestParams {
                thread_id: thread.id,
                contract_id,
                revision,
                spec_hash,
                subject_hash,
                evidence_hash: "independent-evaluator-report".to_string(),
            },
        })
        .await?;
    assert_eq!(settled.contract.status, ProContractStatus::Discharged);
    assert!(settled.quiet.quiet);
    assert!(settled.quiet.outstanding.is_empty());
    Ok(())
}

#[tokio::test]
async fn rejected_revision_resumes_the_same_semantic_attempt() -> Result<()> {
    let server = responses::start_mock_server().await;
    let response_mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_response_created("revision-request"),
                responses::ev_function_call(
                    "propose-revision",
                    "contract_propose_revision",
                    &serde_json::json!({
                        "goal": "replacement goal",
                        "reason": "request different terms"
                    })
                    .to_string(),
                ),
                responses::ev_completed("revision-request"),
            ]),
            responses::sse(vec![
                responses::ev_response_created("ready-after-rejection"),
                responses::ev_function_call(
                    "report-ready",
                    "contract_report_ready",
                    &serde_json::json!({"summary": "original terms ready"}).to_string(),
                ),
                responses::ev_completed("ready-after-rejection"),
            ]),
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
    let thread = app_server
        .start_thread(ThreadStartParams::default())
        .await?
        .thread;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs() as i64;
    let issued: ProContractIssueResponse = app_server
        .request(|request_id| ClientRequest::ProContractIssue {
            request_id,
            params: ProContractIssueParams {
                thread_id: thread.id.clone(),
                spec: ProContractSpec {
                    trigger: ProContractTrigger::Immediate,
                    goal: "original goal".to_string(),
                    brief: "Complete the original goal.".to_string(),
                    artifacts: Vec::new(),
                    requires: Vec::new(),
                    authority: vec!["filesystem.read".to_string()],
                    budget: ProContractBudget {
                        turns: 4,
                        actions: 4,
                        deadline_at: now + 60,
                    },
                    evidence: ProContractEvidence {
                        claim: "original claim".to_string(),
                        replay: None,
                    },
                    resolution: ProContractResolution {
                        max_attempts: 1,
                        retry_delay_ms: 0,
                    },
                },
                execution_policy: None,
                original_request: Some("Complete the original goal.".to_string()),
            },
        })
        .await?;
    let contract_id = issued.contract.id;
    tokio::time::timeout(std::time::Duration::from_secs(30), async {
        while response_mock.requests().is_empty() {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let pending = tokio::time::timeout(std::time::Duration::from_secs(30), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: contract_id.clone(),
                    },
                })
                .await
                .expect("read pending revision");
            if response.contract.pending_revision.is_some() {
                break response;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert_eq!(
        pending
            .execution
            .as_ref()
            .map(|execution| execution.attempts),
        Some(1)
    );
    assert!(
        pending
            .execution
            .as_ref()
            .is_some_and(|execution| execution.awaiting_revision_decision)
    );
    let pending_spec_hash = pending
        .contract
        .pending_revision
        .as_ref()
        .expect("pending revision")
        .spec_hash
        .clone();
    let _: ProContractRevisionDecideResponse = app_server
        .request(|request_id| ClientRequest::ProContractRevisionDecide {
            request_id,
            params: ProContractRevisionDecideParams {
                thread_id: thread.id.clone(),
                contract_id: contract_id.clone(),
                revision: pending.contract.revision,
                spec_hash: pending_spec_hash,
                decision: ProContractRevisionDecision::Reject,
            },
        })
        .await?;
    tokio::time::timeout(std::time::Duration::from_secs(30), async {
        while response_mock.requests().len() < 2 {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    let ready = tokio::time::timeout(std::time::Duration::from_secs(30), async {
        loop {
            let response: ProContractReadResponse = app_server
                .request(|request_id| ClientRequest::ProContractRead {
                    request_id,
                    params: ProContractReadParams {
                        thread_id: thread.id.clone(),
                        contract_id: contract_id.clone(),
                    },
                })
                .await
                .expect("read resumed contract");
            if response.contract.status == ProContractStatus::Verification {
                break response;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await?;
    assert_eq!(ready.contract.revision, 1);
    assert_eq!(ready.contract.spec.goal, "original goal");
    assert_eq!(
        ready.execution.as_ref().map(|execution| execution.attempts),
        Some(1)
    );
    assert_eq!(
        ready
            .execution
            .as_ref()
            .map(|execution| execution.turns_used),
        Some(2)
    );
    Ok(())
}
