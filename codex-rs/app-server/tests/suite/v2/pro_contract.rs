use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use codex_features::Feature;
use core_test_support::responses;
use tempfile::TempDir;

#[tokio::test]
async fn enabled_pro_contract_registers_native_settlement_tools() -> Result<()> {
    let server = responses::start_mock_server().await;
    let call_id = "contract-propose";
    let response_mock = responses::mount_sse_sequence(
        &server,
        vec![
            responses::sse(vec![
                responses::ev_response_created("response-1"),
                responses::ev_function_call(
                    call_id,
                    "contract_propose",
                    &serde_json::json!({
                        "claim": "deliver",
                        "artifacts": ["compile.sh", "executable"],
                        "execution_policy": "Run one broad representative check, then repair concrete residuals."
                    })
                    .to_string(),
                ),
                responses::ev_completed("response-1"),
            ]),
            responses::sse(vec![
                responses::ev_response_created("response-2"),
                responses::ev_assistant_message("message", "done"),
                responses::ev_completed("response-2"),
            ]),
            responses::sse(vec![
                responses::ev_response_created("response-3"),
                responses::ev_assistant_message("message-2", "continued"),
                responses::ev_completed("response-3"),
            ]),
            responses::sse(vec![
                responses::ev_response_created("response-4"),
                responses::ev_assistant_message("message-3", "continued again"),
                responses::ev_completed("response-4"),
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

    app_server
        .start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread.id.clone(),
            input: vec![UserInput::Text {
                text: "perform the contracted task".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        })
        .await?;

    let requests = response_mock.requests();
    assert_eq!(requests.len(), 2);
    let body = requests[0].body_json();
    let tools = body["tools"].as_array().expect("tools array");
    for tool_name in [
        "contract_propose",
        "contract_status",
        "contract_report_ready",
    ] {
        assert!(
            tools
                .iter()
                .any(|tool| tool["name"].as_str() == Some(tool_name)),
            "app-server should expose {tool_name} to the model"
        );
    }
    let output: serde_json::Value = serde_json::from_str(
        &requests[1]
            .function_call_output_text(call_id)
            .expect("contract output"),
    )?;
    assert_eq!(
        output["executionBinding"]["execution_policy"],
        "Run one broad representative check, then repair concrete residuals."
    );
    assert!(output["contract"]["spec"].get("execution_policy").is_none());

    app_server
        .start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread.id.clone(),
            input: vec![UserInput::Text {
                text: "continue the admitted contract".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        })
        .await?;

    let requests = response_mock.requests();
    assert_eq!(requests.len(), 3);
    assert!(
        requests[2].body_contains_text("<pro_contract_execution_policy>"),
        "request did not contain the execution policy fragment"
    );

    app_server
        .start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: thread.id,
            input: vec![UserInput::Text {
                text: "continue once more".to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        })
        .await?;

    let requests = response_mock.requests();
    assert_eq!(requests.len(), 4);
    let marker = "<pro_contract_execution_policy>";
    assert_eq!(
        requests[2].body_json().to_string().matches(marker).count(),
        requests[3].body_json().to_string().matches(marker).count()
    );
    Ok(())
}
