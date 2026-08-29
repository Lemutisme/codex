use super::*;
use crate::tool::REPORT_READY_TOOL_NAME;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_exec_server::LOCAL_FS;
use codex_extension_api::ConversationHistory;
use codex_extension_api::NoopTurnItemEmitter;
use codex_extension_api::SamplingAdmissionInput;
use codex_extension_api::ToolAdmissionInput;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolEnvironment;
use codex_extension_api::ToolName;
use codex_file_system::FileSystemSandboxContext;
use codex_pro_contract::ArtifactPath;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::Command;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Draft;
use codex_pro_contract::Evidence;
use codex_pro_contract::ReplayCheck;
use codex_pro_contract::ReplayPolicy;
use codex_pro_contract::Resolution;
use codex_pro_contract::Status;
use codex_pro_contract::Trigger;
use codex_pro_contract::hash_spec;
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
        bindings: BindingStore::initialize(pool.clone(), "owner").await?,
        subjects: SubjectStore::new(directory.path().join("subjects")),
        environment_manager: Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
        replay_reports: directory.path().join("replay"),
        executor_config: None,
        environments: Vec::new(),
        executor_spawner: None,
        thread_id: codex_protocol::ThreadId::new(),
        ledger_scope: "thread".to_string(),
        thread_scope: "thread".to_string(),
        contract_id: "pct_thread".to_string(),
        issuer: "principal:thread".to_string(),
        role: RuntimeRole::Executor,
        policy_projected: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        recovery_started: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        settlement_reminder_projected: Arc::new(std::sync::atomic::AtomicBool::new(false)),
        proposal_mode: ProContractProposalMode::HostApprovedModelTool,
        authority: vec!["filesystem.read".to_string()],
    });
    let report = ContractTool::new(ToolKind::ReportReady, Arc::clone(&runtime));
    let artifacts = ArtifactSpec::new([ArtifactPath::new("executable")?])?;
    let spec = ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver".to_string(),
        brief: "deliver".to_string(),
        artifacts: artifacts.clone(),
        requires: Vec::new(),
        authority: vec!["filesystem.read".to_string()],
        budget: Budget {
            turns: 10,
            actions: 20,
            deadline: u64::MAX,
        },
        evidence: Evidence {
            claim: "deliver".to_string(),
            replay: Some(ReplayPolicy {
                checks: vec![ReplayCheck {
                    argv: vec![
                        "/bin/sh".to_string(),
                        "-c".to_string(),
                        "test -n \"$PATH\" && test -s executable".to_string(),
                    ],
                    cwd: None,
                    timeout_ms: 10_000,
                    exit: 0,
                }],
                protected: Vec::new(),
                artifacts: artifacts.clone(),
            }),
        },
        resolution: Resolution {
            max_attempts: 3,
            retry_delay_ms: 0,
        },
    };
    runtime
        .ledger
        .apply(
            "thread",
            Command::Issue {
                actor: runtime.issuer.clone(),
                draft: Draft {
                    id: runtime.contract_id.clone(),
                    scope: "thread".to_string(),
                    spec_hash: hash_spec(&spec)?,
                    spec,
                    issuer: runtime.issuer.clone(),
                    executor: "codex:thread".to_string(),
                },
            },
        )
        .await?;
    runtime
        .ledger
        .apply(
            "thread",
            Command::Activate {
                actor: codex_pro_contract::INSTITUTION_ACTOR.to_string(),
                contract_id: runtime.contract_id.clone(),
                revision: 1,
                time: 1,
            },
        )
        .await?;
    runtime
        .bindings
        .bind_once(
            "thread",
            "thread",
            &runtime.contract_id,
            1,
            Some("Run one broad representative check, then repair concrete residuals.".to_string()),
            crate::binding::ExecutionLimits {
                turns: 10,
                actions: 20,
                deadline: u64::MAX,
                max_attempts: 3,
            },
        )
        .await?;
    runtime.bindings.begin_attempt("thread", 1).await?;
    let session_store = ExtensionData::new("session");
    let thread_store = ExtensionData::new("thread");
    thread_store.insert(runtime.as_ref().clone());
    let extension = Extension::<()> {
        config: Arc::new(|_| unreachable!()),
        executor_spawner: Arc::new(
            |_parent_thread_id: codex_protocol::ThreadId,
             _options: codex_core::StartThreadOptions|
             -> codex_extension_api::InternalSessionSpawnFuture<
                'static,
                codex_core::NewThread,
                codex_protocol::error::CodexErr,
            > {
                Box::pin(async {
                    Err(codex_protocol::error::CodexErr::UnsupportedOperation(
                        "not used by this test".to_string(),
                    ))
                })
            },
        ),
        owner: "owner".to_string(),
        controller: ProContractController::new(),
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
    let turn_store = ExtensionData::new("turn");
    let first_sampling = extension
        .admit_sampling(SamplingAdmissionInput {
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            turn_id: "turn",
        })
        .await;
    assert!(matches!(
        first_sampling,
        ExecutionAdmission::Permit(ExecutionPermit {
            valid_until: Some(_),
            ref reminders,
        }) if reminders.len() == 1
    ));
    assert!(matches!(
        extension
            .admit_sampling(SamplingAdmissionInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
                turn_id: "turn",
            })
            .await,
        ExecutionAdmission::Permit(ExecutionPermit {
            valid_until: Some(_),
            ref reminders,
        }) if reminders.is_empty()
    ));
    let apply_patch = ToolName::plain("apply_patch");
    let settlement = ToolName::plain(REPORT_READY_TOOL_NAME);
    assert_eq!(
        extension
            .admit_tool(ToolAdmissionInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
                turn_id: "turn",
                call_id: "call-apply",
                tool_name: &apply_patch,
                payload: &ToolPayload::Function {
                    arguments: "{}".to_string(),
                },
            })
            .await,
        ExecutionAdmission::Deny {
            reason: "contract authority does not permit this tool".to_string(),
        }
    );
    assert_eq!(
        extension
            .admit_tool(ToolAdmissionInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
                turn_id: "turn",
                call_id: "call-ready",
                tool_name: &settlement,
                payload: &ToolPayload::Function {
                    arguments: "{}".to_string(),
                },
            })
            .await,
        ExecutionAdmission::Permit(ExecutionPermit::default())
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
    assert_eq!(response["replay"]["passed"], true);
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
        scope: runtime.ledger_scope.clone(),
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
    assert_eq!(
        extension
            .admit_sampling(SamplingAdmissionInput {
                session_store: &session_store,
                thread_store: &thread_store,
                turn_store: &turn_store,
                turn_id: "retired-turn",
            })
            .await,
        ExecutionAdmission::Deny {
            reason: "contract is not active at the bound revision".to_string(),
        }
    );
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
