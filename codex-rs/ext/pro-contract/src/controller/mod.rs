//! The ProContract automation lane, installed as host-side thread and turn contributors.

pub(crate) mod decision;
pub(crate) mod eligibility;
pub(crate) mod ports;
pub(crate) mod runtime;
pub(crate) mod views;

use std::sync::Arc;
use std::sync::Weak;

use codex_core::ThreadManager;
use codex_core::config::Config;
use codex_extension_api::ContextContributor;
use codex_extension_api::ContextualUserFragment;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionMetrics;
use codex_extension_api::PreviousWorldStateSection;
use codex_extension_api::RenderedWorldStateFragment;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ThreadStopInput;
use codex_extension_api::TurnInputContext;
use codex_extension_api::TurnInputContributor;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartInput;
use codex_extension_api::TurnStopInput;
use codex_extension_api::WorldStateContributionInput;
use codex_extension_api::WorldStateSectionContribution;
use codex_features::Feature;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_protocol::user_input::UserInput;
use serde_json::json;

use self::decision::is_current_brief;
use self::eligibility::Eligibility;
use self::eligibility::EligibilityFacts;
use self::eligibility::eligibility;
use self::runtime::ThreadRuntime;
use crate::BlobStore;
use crate::Ledger;
use crate::Settings;

const SECTION_ID: &str = "pro_contract";
const OPEN_MARKER: &str = "<pro_contract>";
const CLOSE_MARKER: &str = "</pro_contract>";

type EnabledFn = dyn Fn(&Config) -> bool + Send + Sync;

pub(crate) struct ProContractExtension {
    thread_manager: Weak<ThreadManager>,
    enabled: Box<EnabledFn>,
}

impl ProContractExtension {
    pub(crate) fn new(thread_manager: Weak<ThreadManager>, enabled: Box<EnabledFn>) -> Self {
        Self {
            thread_manager,
            enabled,
        }
    }

    async fn start(&self, input: &ThreadStartInput<'_, Config>) {
        let config = input.config;
        if !(self.enabled)(config) {
            return;
        }
        let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) else {
            tracing::warn!("pro_contract: thread store has no thread id");
            return;
        };
        let settings = Settings::load(config.codex_home.as_path());
        let loaded = settings.as_ref().ok().and_then(Option::as_ref);
        let facts = EligibilityFacts {
            feature_enabled: true,
            internal_or_subagent: matches!(
                input.session_source,
                SessionSource::Internal(_) | SessionSource::SubAgent(_)
            ),
            persistent: input.persistent_thread_state_available,
            settings: loaded,
            environment_ids: input
                .environments
                .iter()
                .map(|environment| environment.environment_id.as_str())
                .collect(),
            mcp_server_count: config.mcp_servers.get().len(),
            notify_configured: config.notify.is_some(),
            hooks_enabled: config.features.enabled(Feature::CodexHooks),
        };
        let decision = match (&settings, eligibility(&facts)) {
            (_, Eligibility::Inactive) => return,
            (Err(error), _) => Err(format!("settings are invalid: {error}")),
            (Ok(_), Eligibility::Abstain(reason)) => Err(reason),
            (Ok(_), Eligibility::Eligible(profile)) => Ok(profile.clone()),
        };
        let dir = config.codex_home.as_path().join("pro_contract");
        let ledger = match Ledger::open(config.sqlite_config(), &dir).await {
            Ok(ledger) => ledger,
            Err(error) => {
                tracing::warn!("pro_contract: cannot open the ledger: {error}");
                return;
            }
        };
        let profile = match decision {
            Ok(profile) => profile,
            Err(reason) => {
                record_abstention(&ledger, thread_id, &reason).await;
                return;
            }
        };
        let store = match BlobStore::open(&dir.join("blobs")) {
            Ok(store) => store,
            Err(error) => {
                let reason = format!("cannot open the blob store: {error}");
                record_abstention(&ledger, thread_id, &reason).await;
                return;
            }
        };
        let Some(settings) = settings.ok().flatten() else {
            return;
        };
        let ports = Arc::new(ports::CodexPorts {
            thread_id,
            manager: Weak::clone(&self.thread_manager),
            config: config.clone(),
            worker: settings.worker.clone(),
        });
        let runtime = ThreadRuntime::new(
            thread_id,
            settings,
            profile,
            runtime::Stores { dir, ledger, store },
            ports,
        );
        input.thread_store.insert(runtime);
        if let Some(runtime) = runtime_of(input.thread_store) {
            runtime.record_status("idle", "", /*resting*/ false).await;
        }
    }
}

async fn record_abstention(ledger: &Ledger, thread_id: ThreadId, reason: &str) {
    let status = runtime::StatusRecord {
        thread_id: thread_id.to_string(),
        contract_id: None,
        phase: "abstained".to_string(),
        detail: reason.to_string(),
        resting: true,
        repairs_used: 0,
    };
    if let Err(error) = ledger
        .put_record(runtime::STATUS_KIND, &thread_id.to_string(), &status)
        .await
    {
        tracing::warn!("pro_contract could not record status: {error}");
    }
}

fn runtime_of(thread_store: &ExtensionData) -> Option<Arc<ThreadRuntime>> {
    thread_store.get::<ThreadRuntime>()
}

impl ThreadLifecycleContributor<Config> for ProContractExtension {
    fn on_thread_start<'a>(
        &'a self,
        input: ThreadStartInput<'a, Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move { self.start(&input).await })
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(runtime) = runtime_of(input.thread_store) {
                runtime.thread_idle(input.cause).await;
            }
        })
    }

    fn on_thread_stop<'a>(&'a self, input: ThreadStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(runtime) = runtime_of(input.thread_store) {
                runtime.stop().await;
            }
        })
    }
}

impl TurnLifecycleContributor for ProContractExtension {
    fn on_turn_start<'a>(&'a self, input: TurnStartInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(runtime) = runtime_of(input.thread_store) {
                runtime.turn_started().await;
            }
        })
    }

    fn on_turn_stop<'a>(&'a self, input: TurnStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(runtime) = runtime_of(input.thread_store) {
                runtime
                    .turn_stopped(input.turn_store.level_id().to_string())
                    .await;
            }
        })
    }
}

impl TurnInputContributor for ProContractExtension {
    fn contribute<'a>(
        &'a self,
        input: TurnInputContext<'a>,
        _extension_metrics: Option<Arc<dyn ExtensionMetrics>>,
        _session_store: &'a ExtensionData,
        thread_store: &'a ExtensionData,
        _turn_store: &'a ExtensionData,
    ) -> ExtensionFuture<'a, Vec<Box<dyn ContextualUserFragment + Send>>> {
        Box::pin(async move {
            let text = input
                .user_input
                .iter()
                .filter_map(|item| match item {
                    UserInput::Text { text, .. } => Some(text.as_str()),
                    _ => None,
                })
                .collect::<Vec<_>>()
                .join("\n");
            if let Some(runtime) = runtime_of(thread_store)
                && !text.trim().is_empty()
            {
                runtime.intake(text).await;
            }
            Vec::new()
        })
    }
}

impl ContextContributor for ProContractExtension {
    fn contribute_world_state<'a>(
        &'a self,
        input: WorldStateContributionInput<'a>,
    ) -> ExtensionFuture<'a, Vec<WorldStateSectionContribution>> {
        Box::pin(async move {
            let Some(runtime) = runtime_of(input.thread_store) else {
                return Vec::new();
            };
            let Some(brief) = runtime.brief().await else {
                return Vec::new();
            };
            vec![brief_section(brief)]
        })
    }
}

/// The executor's brief, rendered once per contract revision and kept across compaction.
fn brief_section(brief: runtime::BriefView) -> WorldStateSectionContribution {
    let snapshot = json!({ "contract": brief.contract_id, "revision": brief.revision });
    let current = snapshot.clone();
    let runtime::BriefView {
        contract_id,
        revision,
        text,
    } = brief;
    WorldStateSectionContribution::new(SECTION_ID, snapshot, move |previous| match previous {
        PreviousWorldStateSection::Known(value) if *value == current => None,
        PreviousWorldStateSection::Unknown => None,
        PreviousWorldStateSection::Absent | PreviousWorldStateSection::Known(_) => Some(
            RenderedWorldStateFragment::new("developer", (OPEN_MARKER, CLOSE_MARKER), text.clone()),
        ),
    })
    .with_retained_fragment_matcher(move |role, text| {
        role == "developer" && is_current_brief(text, &contract_id, revision)
    })
}

#[cfg(test)]
#[path = "brief_section_tests.rs"]
mod tests;
