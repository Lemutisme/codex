use std::sync::Arc;

use anyhow::Result;
use codex_core::config::Config;
use codex_extension_api::ExecutionAdmission;
use codex_extension_api::ExecutionAdmissionContributor;
use codex_extension_api::ExecutionPermit;
use codex_extension_api::ExecutionReminder;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::SamplingAdmissionInput;
use codex_protocol::models::ContentItemKind;
use core_test_support::responses;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::test_codex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct DenySampling;

struct BoundSampling;

impl ExecutionAdmissionContributor for BoundSampling {
    fn admit_sampling<'a>(
        &'a self,
        _input: SamplingAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |duration| duration.as_millis() as u64);
        Box::pin(std::future::ready(ExecutionAdmission::Permit(
            ExecutionPermit {
                valid_until: Some(now.saturating_add(2_000)),
                reminders: ExecutionReminder::new(
                    "settle before the boundary",
                    ContentItemKind("test.execution_boundary".to_string()),
                )
                .into_iter()
                .collect(),
            },
        )))
    }
}

impl ExecutionAdmissionContributor for DenySampling {
    fn admit_sampling<'a>(
        &'a self,
        _input: SamplingAdmissionInput<'a>,
    ) -> ExtensionFuture<'a, ExecutionAdmission> {
        Box::pin(std::future::ready(ExecutionAdmission::Deny {
            reason: "provider-turn budget exhausted".to_string(),
        }))
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn sampling_denial_prevents_a_provider_request() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = responses::start_mock_server().await;
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.execution_admission_contributor(Arc::new(DenySampling));
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .build_with_auto_env(&server)
        .await?;

    test.submit_text_turn("this turn must be denied before sampling")
        .await?;

    let requests = server.received_requests().await.unwrap_or_default();
    assert!(
        requests
            .iter()
            .all(|request| !request.url.path().ends_with("/responses"))
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn sampling_permit_injects_reminder_and_bounds_the_provider() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let server = responses::start_mock_server().await;
    let response = responses::sse(vec![
        responses::ev_response_created("response-1"),
        responses::ev_completed("response-1"),
    ]);
    let response_mock = responses::mount_response_once(
        &server,
        responses::sse_response(response).set_delay(Duration::from_secs(5)),
    )
    .await;
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.execution_admission_contributor(Arc::new(BoundSampling));
    let test = test_codex()
        .with_extensions(Arc::new(extensions.build()))
        .build_with_auto_env(&server)
        .await?;

    let started = Instant::now();
    test.submit_text_turn("this provider must be bounded")
        .await?;
    assert!(started.elapsed() < Duration::from_secs(4));
    let request = response_mock.single_request();
    assert!(request.body_contains_text("<execution_boundary_reminder>"));
    assert!(request.body_contains_text("settle before the boundary"));
    Ok(())
}
