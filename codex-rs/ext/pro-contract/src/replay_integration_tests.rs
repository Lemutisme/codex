use super::*;
use crate::binding::ExecutionLimits;
use crate::tool::REPORT_READY_TOOL_NAME;
use codex_exec_server::LOCAL_ENVIRONMENT_ID;
use codex_exec_server::LOCAL_FS;
use codex_extension_api::ConversationHistory;
use codex_extension_api::NoopTurnItemEmitter;
use codex_extension_api::ToolCallSource;
use codex_extension_api::ToolEnvironment;
use codex_extension_api::ToolName;
use codex_file_system::FileSystemSandboxContext;
use codex_pro_contract::ArtifactPath;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Draft;
use codex_pro_contract::Evidence;
use codex_pro_contract::ReplayCheck;
use codex_pro_contract::ReplayPolicy;
use codex_pro_contract::Resolution;
use codex_pro_contract::Trigger;
use codex_pro_contract::hash_spec;
use codex_protocol::models::PermissionProfile;
use codex_tools::ToolPayload;
use codex_utils_output_truncation::TruncationPolicy;
use pretty_assertions::assert_eq;
use serde_json::json;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqlitePoolOptions;
use std::marker::PhantomData;
use std::path::Path;
use std::str::FromStr;

#[tokio::test]
async fn failed_native_replay_reopens_the_exact_contract() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    std::fs::write(workspace.join("result"), "candidate")?;
    let artifacts = ArtifactSpec::new([ArtifactPath::new("result")?])?;
    let replay = ReplayPolicy {
        checks: vec![ReplayCheck {
            argv: vec![
                "/bin/sh".to_string(),
                "-c".to_string(),
                "test -n \"$PATH\"; exit 7".to_string(),
            ],
            cwd: None,
            timeout_ms: 1_000,
            exit: 0,
        }],
        protected: Vec::new(),
        artifacts: artifacts.clone(),
    };
    let runtime = runtime(&directory, artifacts, Some(replay)).await?;
    let report = ContractTool::new(ToolKind::ReportReady, Arc::clone(&runtime));
    let payload = ToolPayload::Function {
        arguments: json!({"summary": "candidate ready"}).to_string(),
    };
    let output = report
        .handle(tool_call(
            &workspace,
            LOCAL_ENVIRONMENT_ID,
            payload.clone(),
        )?)
        .await?;
    let response = output.code_mode_result(&payload);

    assert_eq!(response["contract"]["status"], "dormant");
    assert_eq!(response["replay"]["passed"], false);
    assert!(
        response["replay"]["summary"]
            .as_str()
            .is_some_and(|summary| summary.contains("exited 7; expected 0"))
    );
    let state = runtime.ledger.state("thread").await?;
    assert_eq!(state.contracts["pct_thread"].status, Status::Dormant);
    assert!(state.contracts["pct_thread"].challenge.is_some());
    assert_eq!(
        runtime
            .bindings
            .get("thread")
            .await?
            .expect("binding")
            .dispatched,
        false
    );
    Ok(())
}

#[tokio::test]
async fn timed_out_native_replay_is_negative_evidence() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    std::fs::write(workspace.join("result"), "candidate")?;
    let artifacts = ArtifactSpec::new([ArtifactPath::new("result")?])?;
    let replay = ReplayPolicy {
        checks: vec![ReplayCheck {
            argv: vec![
                "/bin/sh".to_string(),
                "-c".to_string(),
                "sleep 30".to_string(),
            ],
            cwd: None,
            timeout_ms: 1_000,
            exit: 0,
        }],
        protected: Vec::new(),
        artifacts: artifacts.clone(),
    };
    let runtime = runtime(&directory, artifacts, Some(replay)).await?;
    let report = ContractTool::new(ToolKind::ReportReady, Arc::clone(&runtime));
    let payload = ToolPayload::Function {
        arguments: json!({"summary": "candidate ready"}).to_string(),
    };
    let output = report
        .handle(tool_call(
            &workspace,
            LOCAL_ENVIRONMENT_ID,
            payload.clone(),
        )?)
        .await?;
    let response = output.code_mode_result(&payload);

    assert_eq!(response["contract"]["status"], "dormant");
    assert_eq!(response["replay"]["passed"], false);
    assert!(
        response["replay"]["summary"]
            .as_str()
            .is_some_and(|summary| summary.contains("timed out after 1000 milliseconds"))
    );
    let evidence_hash = response["replay"]["evidence_hash"]
        .as_str()
        .expect("evidence hash");
    let persisted: serde_json::Value = serde_json::from_slice(&std::fs::read(
        runtime.replay_reports.join(format!("{evidence_hash}.json")),
    )?)?;
    assert_eq!(persisted["version"], 2);
    assert_eq!(persisted["checks"][0]["timed_out"], true);
    assert!(persisted["checks"][0]["exit"].is_null());
    assert!(
        persisted["checks"][0]["duration_ms"]
            .as_u64()
            .is_some_and(|duration| duration >= 1_000)
    );
    let state = runtime.ledger.state("thread").await?;
    assert_eq!(state.contracts["pct_thread"].status, Status::Dormant);
    assert!(state.contracts["pct_thread"].challenge.is_some());
    assert!(state.contracts["pct_thread"].escalation.is_none());
    Ok(())
}

#[tokio::test]
async fn unavailable_subject_capture_escalates_instead_of_fabricating_evidence()
-> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    std::fs::write(workspace.join("result"), "candidate")?;
    let artifacts = ArtifactSpec::new([ArtifactPath::new("result")?])?;
    let runtime = runtime(&directory, artifacts, None).await?;
    let report = ContractTool::new(ToolKind::ReportReady, Arc::clone(&runtime));
    let payload = ToolPayload::Function {
        arguments: json!({"summary": "candidate ready"}).to_string(),
    };
    let result = report
        .handle(tool_call(&workspace, "remote", payload)?)
        .await;
    assert!(result.is_err());

    let state = runtime.ledger.state("thread").await?;
    assert_eq!(state.contracts["pct_thread"].status, Status::Escalated);
    assert_eq!(
        state.contracts["pct_thread"]
            .escalation
            .as_ref()
            .map(|escalation| escalation.reason.as_str()),
        Some("contract subject capture requires the local execution environment")
    );
    assert!(state.contracts["pct_thread"].handoff.is_none());
    Ok(())
}

async fn runtime(
    directory: &tempfile::TempDir,
    artifacts: ArtifactSpec,
    replay: Option<ReplayPolicy>,
) -> anyhow::Result<Arc<Runtime>> {
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
    let ledger = Ledger::initialize(pool.clone()).await?;
    let bindings = BindingStore::initialize(pool.clone(), "owner").await?;
    let probe_frontiers = probe::ProbeFrontierStore::initialize(pool).await?;
    let spec = ContractSpec {
        trigger: Trigger::Immediate,
        goal: "deliver".to_string(),
        brief: "deliver".to_string(),
        artifacts,
        requires: Vec::new(),
        authority: vec!["filesystem.read".to_string()],
        budget: Budget {
            turns: 10,
            actions: 20,
            deadline: u64::MAX,
        },
        evidence: Evidence {
            claim: "deliver".to_string(),
            replay,
        },
        resolution: Resolution {
            max_attempts: 3,
            retry_delay_ms: 0,
        },
    };
    ledger
        .apply(
            "thread",
            Command::Issue {
                actor: "principal:thread".to_string(),
                draft: Draft {
                    id: "pct_thread".to_string(),
                    scope: "thread".to_string(),
                    spec_hash: hash_spec(&spec)?,
                    spec: spec.clone(),
                    issuer: "principal:thread".to_string(),
                    executor: "codex:thread".to_string(),
                },
            },
        )
        .await?;
    ledger
        .apply(
            "thread",
            Command::Activate {
                actor: INSTITUTION_ACTOR.to_string(),
                contract_id: "pct_thread".to_string(),
                revision: 1,
                time: 1,
            },
        )
        .await?;
    bindings
        .bind_once(
            "thread",
            "thread",
            "pct_thread",
            1,
            None,
            ExecutionLimits {
                turns: spec.budget.turns,
                actions: spec.budget.actions,
                deadline: spec.budget.deadline,
                max_attempts: spec.resolution.max_attempts,
            },
        )
        .await?;
    bindings.begin_attempt("thread", 1).await?;
    Ok(Arc::new(Runtime {
        ledger,
        bindings,
        subjects: SubjectStore::new(directory.path().join("subjects")),
        environment_manager: Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
        replay_reports: directory.path().join("replay"),
        probe_frontiers,
        executor_config: None,
        environments: Vec::new(),
        executor_spawner: None,
        thread_id: ThreadId::new(),
        ledger_scope: "thread".to_string(),
        thread_scope: "thread".to_string(),
        contract_id: "pct_thread".to_string(),
        issuer: "principal:thread".to_string(),
        role: RuntimeRole::Executor,
        policy_projected: Arc::new(AtomicBool::new(false)),
        recovery_started: Arc::new(AtomicBool::new(false)),
        settlement_reminder_projected: Arc::new(AtomicBool::new(false)),
        proposal_mode: ProContractProposalMode::HostApprovedModelTool,
        authority: vec!["filesystem.read".to_string()],
    }))
}

fn tool_call(
    workspace: &Path,
    environment_id: &str,
    payload: ToolPayload,
) -> anyhow::Result<ToolCall<'static>> {
    Ok(ToolCall {
        turn_id: "turn".to_string(),
        call_id: "call-ready".to_string(),
        tool_name: ToolName::plain(REPORT_READY_TOOL_NAME),
        model: "gpt-test".to_string(),
        codex_turn_metadata: None,
        truncation_policy: TruncationPolicy::Bytes(4096),
        source: ToolCallSource::Direct,
        conversation_history: ConversationHistory::default(),
        turn_item_emitter: Arc::new(NoopTurnItemEmitter),
        environments: vec![ToolEnvironment {
            _lifetime: PhantomData,
            environment_id: environment_id.to_string(),
            cwd: workspace.try_into()?,
            file_system: Arc::clone(&LOCAL_FS),
            file_system_sandbox_context: FileSystemSandboxContext::from_permission_profile(
                PermissionProfile::Disabled,
            ),
        }],
        payload,
    })
}
