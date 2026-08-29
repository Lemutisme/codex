use super::*;
use crate::tool::PROPOSE_TOOL_NAME;
use crate::tool::REPORT_READY_TOOL_NAME;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_exec_server::LOCAL_FS;
use codex_extension_api::ConversationHistory;
use codex_extension_api::NoopTurnItemEmitter;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolEnvironment;
use codex_extension_api::ToolName;
use codex_file_system::FileSystemSandboxContext;
use codex_pro_contract::Status;
use codex_protocol::models::PermissionProfile;
use codex_tools::ToolPayload;
use codex_utils_output_truncation::TruncationPolicy;
use pretty_assertions::assert_eq;
use serde_json::json;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::path::Path;
use std::str::FromStr;

#[tokio::test]
async fn native_tools_freeze_artifacts_without_self_settling() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    std::fs::write(workspace.join(".gitignore"), "executable\n")?;
    std::fs::write(
        workspace.join("executable"),
        vec![7_u8; 2 * 1024 * 1024 + 1],
    )?;
    let options = SqliteConnectOptions::from_str(
        directory
            .path()
            .join("ledger.sqlite")
            .to_string_lossy()
            .as_ref(),
    )?
    .create_if_missing(true);
    #[expect(
        clippy::disallowed_methods,
        reason = "focused extension test does not own a Codex host SQLiteConfig"
    )]
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(options)
        .await?;
    let runtime = Arc::new(Runtime {
        ledger: Ledger::initialize(pool.clone()).await?,
        bindings: BindingStore::initialize(pool).await?,
        subjects: SubjectStore::new(directory.path().join("subjects")),
        scope: "thread".to_string(),
        contract_id: "pct_thread".to_string(),
        issuer: "principal:thread".to_string(),
        executor: "codex:thread".to_string(),
        policy_projected: Arc::new(std::sync::atomic::AtomicBool::new(false)),
    });
    let propose = ContractTool::new(ToolKind::Propose, Arc::clone(&runtime));
    let report = ContractTool::new(ToolKind::ReportReady, Arc::clone(&runtime));

    let proposal_payload = ToolPayload::Function {
        arguments: json!({
            "claim": "deliver",
            "artifacts": ["executable"],
            "execution_policy": "Run one broad representative check, then repair concrete residuals."
        })
        .to_string(),
    };
    let proposal = propose
        .handle(tool_call_with_payload(
            PROPOSE_TOOL_NAME,
            proposal_payload.clone(),
            &workspace,
        )?)
        .await?
        .code_mode_result(&proposal_payload);
    assert_eq!(proposal["contract"]["spec"]["claim"], "deliver");
    assert!(
        proposal["contract"]["spec"]
            .get("execution_policy")
            .is_none()
    );
    assert_eq!(
        proposal["executionBinding"]["execution_policy"],
        "Run one broad representative check, then repair concrete residuals."
    );
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new("thread");
    thread_store.insert(runtime.as_ref().clone());
    let extension = Extension::<()> {
        config: Arc::new(|_| unreachable!()),
    };
    let fragments = extension
        .contribute_thread_context(&session_store, &thread_store)
        .await;
    assert_eq!(fragments.len(), 1);
    assert!(
        fragments[0]
            .text()
            .contains("Run one broad representative check")
    );
    let payload = ToolPayload::Function {
        arguments: json!({"summary": "ready"}).to_string(),
    };
    let output = report
        .handle(tool_call_with_payload(
            REPORT_READY_TOOL_NAME,
            payload.clone(),
            &workspace,
        )?)
        .await?;
    let response = output.code_mode_result(&payload);

    assert_eq!(response["contract"]["status"], "verification");
    assert_eq!(response["subject"]["bytes"], 2 * 1024 * 1024 + 12);
    assert_eq!(response["quiet"], false);
    assert!(
        runtime
            .ledger
            .state("thread")
            .await?
            .attestations
            .is_empty()
    );
    let principal = ProContractPrincipal {
        ledger: runtime.ledger.clone(),
        subjects: runtime.subjects.clone(),
        scope: runtime.scope.clone(),
        contract_id: runtime.contract_id.clone(),
    };
    std::fs::write(workspace.join("executable"), b"mutated after handoff")?;
    let materialized = directory.path().join("materialized");
    let coordinate = principal.materialize_handoff(&materialized).await?;
    assert_eq!(coordinate.hash, response["subject"]["coordinate"]["hash"]);
    assert_eq!(
        std::fs::read(materialized.join("executable"))?,
        vec![7_u8; 2 * 1024 * 1024 + 1]
    );
    let settled = principal.attest("independent-evidence").await?;
    assert_eq!(
        settled.state.contracts["pct_thread"].status,
        Status::Discharged
    );
    assert!(codex_pro_contract::quiet(&settled.state, "thread"));
    Ok(())
}

fn tool_call_with_payload(
    name: &str,
    payload: ToolPayload,
    workspace: &Path,
) -> anyhow::Result<ToolCall> {
    let cwd = workspace.try_into()?;
    Ok(ToolCall {
        turn_id: "turn".to_string(),
        call_id: format!("call-{name}"),
        tool_name: ToolName::plain(name),
        model: "gpt-test".to_string(),
        codex_turn_metadata: None,
        truncation_policy: TruncationPolicy::Bytes(4096),
        source: ToolCallSource::Direct,
        conversation_history: ConversationHistory::default(),
        turn_item_emitter: Arc::new(NoopTurnItemEmitter),
        environments: vec![ToolEnvironment {
            environment_id: LOCAL_ENVIRONMENT_ID.to_string(),
            cwd,
            file_system: Arc::clone(&LOCAL_FS),
            file_system_sandbox_context: FileSystemSandboxContext::from_permission_profile(
                PermissionProfile::Disabled,
            ),
        }],
        payload,
    })
}
