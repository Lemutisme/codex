//! Same-turn publication. Working observations never issue kernel commands.
use codex_pro_contract::Digest;
use codex_pro_contract_store::ExperimentKind;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use super::{Phase, ThreadRuntime, WorkSnapshot};
use crate::controller::succession_budget::{Budget, KIND, earliest, now_ms};

const PROGRESS: &str = "progress_grant_v1";
const CLEANUP_SECONDS: u64 = 10;

/// Caller-selected work, not a new task grant or a change to the frozen obligations.
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(crate) struct ProgressAssessment {
    #[serde(default)]
    pub review: bool,
    #[serde(default)]
    pub question: Option<String>,
    #[serde(default)]
    pub continue_from: Option<Digest>,
    #[serde(default)]
    pub assessment_secs: Option<u64>,
}

impl ProgressAssessment {
    fn validate(&self) -> Result<(), String> {
        if !self.review && (self.question.is_some() || self.continue_from.is_some()) {
            return Err("question and continue_from require review=true".into());
        }
        if self.question.as_ref().is_some_and(|q| q.len() > 8192) {
            return Err("diagnostic question exceeds 8 KiB".into());
        }
        if self.assessment_secs == Some(0) {
            return Err("assessment_secs must be positive".into());
        }
        Ok(())
    }
}

#[derive(Clone, Serialize, Deserialize, PartialEq)]
struct Grant {
    binding: Digest,
    used: u32,
    pending: Option<String>,
    completed: Vec<(String, Digest)>,
}

impl ThreadRuntime {
    pub(super) async fn arm_deadline(self: &std::sync::Arc<Self>) {
        {
            let mut state = self.state.lock().await;
            if state.admission.is_none() || state.deadline_watch {
                return;
            }
            state.deadline_watch = true;
        }
        let budget = self
            .ledger
            .record::<Budget>(KIND, &self.thread_id.to_string())
            .await;
        let Ok(Some(budget)) = budget else {
            return;
        };
        let Some(deadline_ms) = budget.deadline_ms else {
            return;
        };
        let runtime = std::sync::Arc::clone(self);
        self.spawn(async move {
            let remaining = deadline_ms.saturating_sub(now_ms().unwrap_or(deadline_ms));
            tokio::time::sleep(std::time::Duration::from_millis(remaining)).await;
            // Shutdown invokes stop(), which joins this actor's tasks. Its bounded
            // observer must outlive that JoinSet to commit the actual shutdown result.
            tokio::spawn(runtime.expire_original_grant(deadline_ms));
        });
    }

    async fn expire_original_grant(self: std::sync::Arc<Self>, deadline_ms: u64) {
        use crate::controller::decision::NotVerifiedClass;
        let was_active = !matches!(
            self.state.lock().await.phase,
            Phase::Resting | Phase::RecoveryBlocked
        );
        self.cancel_successor().await;
        let interrupted = self.ports.interrupt_executor().await;
        if was_active {
            let (class, reason) = match &interrupted {
                Ok(()) => (NotVerifiedClass::BudgetExhausted,
                    "original task grant expired; executor shutdown confirmed; retained progress is not completed acceptance".to_string()),
                Err(reason) => (NotVerifiedClass::Infrastructure,
                    format!("original task grant expired; executor shutdown unresolved: {reason}")),
            };
            self.not_verified(class, &reason).await;
        }
        self.record_event(ExperimentKind::Execution, None, json!({
            "phase":"original_grant_expired", "thread_id":self.thread_id.to_string(),
            "deadline_ms":deadline_ms, "interrupt_and_executor_shutdown_confirmed":interrupted.is_ok(),
            "error":interrupted.err(), "completion_certified":false,
        })).await;
    }

    pub(crate) fn progress_enabled(&self) -> bool {
        self.settings.progress.is_some()
    }

    pub(crate) async fn remaining_task_budget(&self) -> Result<Value, String> {
        let budget: Budget = self
            .ledger
            .record(KIND, &self.thread_id.to_string())
            .await
            .map_err(|e| e.to_string())?
            .ok_or("original task grant unavailable")?;
        let now = now_ms()?;
        let progress = if self.settings.progress.is_some() {
            Some(self.progress_grant().await?)
        } else {
            None
        };
        Ok(json!({"deadline_ms":budget.deadline_ms,
            "remaining_ms":budget.deadline_ms.map(|end| end.saturating_sub(now)),
            "started_ms":budget.started_ms,"elapsed_ms":now.checked_sub(budget.started_ms),
            "sessions_used":budget.launches,"session_limit":budget.grant.max_sessions,
            "publications_used":progress.map(|grant| grant.used),
            "publication_limit":self.settings.progress.as_ref().and_then(|grant| grant.max_publications)}))
    }

    pub(super) async fn action_seconds(
        &self,
        deadline: Option<u64>,
        maximum: u64,
    ) -> Result<u64, String> {
        let budget: Option<Budget> = self
            .ledger
            .record(KIND, &self.thread_id.to_string())
            .await
            .map_err(|e| e.to_string())?;
        if budget.is_none()
            && (self.settings.succession.is_some() || self.settings.progress.is_some())
        {
            return Err("original task grant is unavailable".into());
        }
        let now = now_ms()?;
        let task_deadline = budget.as_ref().and_then(|b| b.deadline_ms);
        if task_deadline.is_some() && budget.as_ref().is_some_and(|b| now < b.started_ms) {
            return Err("host clock moved backwards".into());
        }
        let seconds = earliest(deadline, task_deadline).map_or(maximum, |end| {
            maximum.min(
                end.saturating_sub(CLEANUP_SECONDS * 1000)
                    .saturating_sub(now)
                    / 1000,
            )
        });
        if seconds == 0 {
            return Err("original task or action budget exhausted".into());
        }
        if seconds
            .checked_add(CLEANUP_SECONDS)
            .and_then(|n| n.checked_mul(1000))
            .and_then(|ms| now.checked_add(ms))
            .is_none()
        {
            return Err("action allocation is not representable".into());
        }
        Ok(seconds)
    }

    pub(super) async fn initialize_progress(&self) -> Result<(), String> {
        let Some(settings) = &self.settings.progress else {
            return Ok(());
        };
        if settings.assessment_secs == 0
            || settings
                .executor_slice_secs
                .is_some_and(|seconds| seconds == 0 || seconds > u64::MAX / 1000)
        {
            return Err(
                "progress requires a positive action allocation and valid optional executor limits"
                    .into(),
            );
        }
        self.action_seconds(None, settings.assessment_secs).await?;
        let intake = self
            .state
            .lock()
            .await
            .admission
            .ok_or("task intake unavailable")?;
        let grant = Grant {
            binding: super::digest_of("progress_grant", &(intake, settings)),
            used: 0,
            pending: None,
            completed: Vec::new(),
        };
        if !self
            .ledger
            .compare_exchange_record(
                PROGRESS,
                &self.thread_id.to_string(),
                None::<&Grant>,
                &grant,
            )
            .await
            .map_err(|e| e.to_string())?
        {
            return Err("original progress grant already exists; no renewal".into());
        }
        Ok(())
    }

    async fn progress_grant(&self) -> Result<Grant, String> {
        let settings = self
            .settings
            .progress
            .as_ref()
            .ok_or("progress publication is not authorized")?;
        let grant: Grant = self
            .ledger
            .record(PROGRESS, &self.thread_id.to_string())
            .await
            .map_err(|e| e.to_string())?
            .ok_or("original progress grant is missing; resume cannot create it")?;
        let intake = self
            .state
            .lock()
            .await
            .admission
            .ok_or("task intake unavailable")?;
        if grant.binding != super::digest_of("progress_grant", &(intake, settings)) {
            return Err("original progress grant binding changed".into());
        }
        Ok(grant)
    }

    pub(super) async fn progress_ready(&self) -> Result<(), String> {
        if self.settings.progress.is_none() {
            return Ok(());
        }
        let grant = self.progress_grant().await?;
        let Some(request) = &grant.pending else {
            return Ok(());
        };
        self.ledger
            .verify_experiment_chain()
            .await
            .map_err(|e| e.to_string())?;
        for row in self.ledger.experiments().await.map_err(|e| e.to_string())? {
            if row.event.kind != ExperimentKind::Execution
                || row.event.body["phase"] != "progress_assessed"
                || row.event.body["contract_id"] != json!(self.contract_id().0)
                || row.event.body["publication"] != json!(grant.used)
            {
                continue;
            }
            let handle: Digest = serde_json::from_value(row.event.body["public_evidence"].clone())
                .map_err(|e| e.to_string())?;
            let document: Value =
                serde_json::from_slice(&self.store.get(&handle).map_err(|e| e.to_string())?)
                    .map_err(|e| e.to_string())?;
            if document["request_id"] == json!(request)
                && document["effects_resolved"] == true
                && document["contract_id"] == row.event.body["contract_id"]
                && document["subject_hash"] == row.event.body["subject_hash"]
                && document["publication"] == json!(grant.used)
                && document["scope"] == "progress_only"
            {
                let mut completed = grant.clone();
                completed.pending = None;
                completed.completed.push((request.clone(), handle));
                if self
                    .ledger
                    .compare_exchange_record(
                        PROGRESS,
                        &self.thread_id.to_string(),
                        Some(&grant),
                        &completed,
                    )
                    .await
                    .map_err(|e| e.to_string())?
                {
                    return Ok(());
                }
                return Err("publication recovery lost ownership; no action replayed".into());
            }
        }
        Err(
            "a prior publication has unresolved effects; reconcile before acceptance or more work"
                .into(),
        )
    }

    #[cfg(test)]
    pub(crate) async fn publish_progress(
        &self,
        request: String,
        turn: String,
    ) -> Result<Value, String> {
        self.publish_progress_for(request, turn, None).await
    }

    #[cfg(test)]
    pub(crate) async fn publish_progress_for(
        &self,
        request: String,
        turn: String,
        owner: Option<(u64, Option<u64>)>,
    ) -> Result<Value, String> {
        self.publish_progress_with_review(request, turn, owner, false)
            .await
    }

    #[cfg(test)]
    pub(crate) async fn publish_progress_with_review(
        &self,
        request: String,
        turn: String,
        owner: Option<(u64, Option<u64>)>,
        diagnostic_review: bool,
    ) -> Result<Value, String> {
        self.publish_assessment(
            request,
            turn,
            owner,
            ProgressAssessment {
                review: diagnostic_review,
                ..Default::default()
            },
        )
        .await
    }

    pub(crate) async fn publish_assessment(
        &self,
        request: String,
        turn: String,
        owner: Option<(u64, Option<u64>)>,
        options: ProgressAssessment,
    ) -> Result<Value, String> {
        options.validate()?;
        let diagnostic_review = options.review;
        if request.is_empty() || request.len() > 128 {
            return Err("publication request_id must contain 1..128 bytes".into());
        }
        let settings = self
            .settings
            .progress
            .as_ref()
            .ok_or("progress publication is not authorized")?;
        self.progress_ready().await?;
        let previous = self.progress_grant().await?;
        if let Some((_, handle)) = previous.completed.iter().find(|(id, _)| id == &request) {
            let stored: Value =
                serde_json::from_slice(&self.store.get(handle).map_err(|e| e.to_string())?)
                    .map_err(|e| e.to_string())?;
            let original = if let Some(value) = stored.get("assessment_request") {
                serde_json::from_value(value.clone()).map_err(|e| e.to_string())?
            } else {
                ProgressAssessment {
                    review: stored["diagnostic_review"].as_bool().unwrap_or(false),
                    ..Default::default()
                }
            };
            if original != options {
                return Err(
                    "request_id belongs to a different assessment; use a new ID for new work"
                        .into(),
                );
            }
            return Ok(
                json!({"handle":handle,"reused":true,"scope":"progress_only","read_with":"contract_read_evidence"}),
            );
        }
        if previous.pending.is_some() {
            return Err("prior publication is still running or unresolved; no replay".into());
        }
        if settings
            .max_publications
            .is_some_and(|limit| previous.used >= limit)
        {
            return Err("original publication allowance exhausted".into());
        }
        let seconds = self
            .action_seconds(
                owner.and_then(|(_, end)| end),
                options.assessment_secs.unwrap_or(settings.assessment_secs),
            )
            .await?;
        let deadline = now_ms()?.saturating_add((seconds + CLEANUP_SECONDS) * 1000);
        // Preparation is concurrent with this turn. One state subscription and one
        // deadline cover both waiting and assessment; no polling or renewed slice.
        let mut changed = self.state_changed.subscribe();
        let wait_deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(seconds);
        while self.state.lock().await.phase == Phase::Drafting {
            tokio::time::timeout_at(wait_deadline, changed.changed())
                .await
                .map_err(|_| "progress preparation did not finish within the original allowance")?
                .map_err(|_| "progress preparation state is unavailable")?;
        }
        self.action_seconds(Some(deadline), 1).await?;
        let (epoch, contract, mut policy, terms, base) = {
            let state = self.state.lock().await;
            let active_owner = match owner {
                None => state.phase == Phase::Working,
                Some((epoch, _)) => state.phase == Phase::Succeeding && state.epoch == epoch,
            };
            if !active_owner {
                return Err("publication requires the current executor and issued terms".into());
            }
            let active = state
                .contract
                .as_ref()
                .ok_or("acceptance terms are not ready; continue ordinary work")?;
            (
                state.epoch,
                active.contract.clone(),
                active.policy.clone(),
                active.terms.clone(),
                active.base.clone(),
            )
        };
        let prior = match options.continue_from {
            Some(handle) => Some(self.evidence_access().diagnostic_prior(handle).await?),
            None => None,
        };
        let mut reserved = previous.clone();
        reserved.used = reserved
            .used
            .checked_add(1)
            .ok_or("publication counter overflow")?;
        reserved.pending = Some(request.clone());
        if !self
            .ledger
            .compare_exchange_record(
                PROGRESS,
                &self.thread_id.to_string(),
                Some(&previous),
                &reserved,
            )
            .await
            .map_err(|e| e.to_string())?
        {
            return Err("publication ownership changed".into());
        }

        // A failure after reservation stays unresolved. Never infer that pause/dispatch did not happen.
        self.append_event(
            ExperimentKind::Execution,
            None,
            json!({"phase":"progress_reserved",
            "contract_id":contract.id.0,"publication":reserved.used,"request_id":request,
            "execution_epoch":epoch,"turn_id":turn,"deadline_ms":deadline}),
        )
        .await?;
        let capture_seconds = self.action_seconds(Some(deadline), 60).await?;
        let barrier = tokio::time::timeout(
            std::time::Duration::from_secs(capture_seconds),
            self.ports
                .capture_barrier(&self.profile, &settings.executor_label),
        )
        .await
        .map_err(|_| "executor capture barrier exceeded its original allocation")??;
        let executor_ids = barrier.identities().to_vec();
        let capture_seconds = self.action_seconds(Some(deadline), 60).await?;
        let captured = tokio::time::timeout(
            std::time::Duration::from_secs(capture_seconds),
            self.capture_workspace(),
        )
        .await
        .map_err(|_| "progress capture exceeded its original allocation".to_string())
        .and_then(|result| result);
        barrier.resume().await?;
        let subject = captured?;
        if self.state.lock().await.epoch != epoch {
            return Err("publication owner was superseded".into());
        }
        self.append_event(ExperimentKind::Capture, None, json!({"phase":"progress_snapshot",
            "contract_id":contract.id.0,"publication":reserved.used,"request_id":request,
            "execution_epoch":epoch,"turn_id":turn,"subject_hash":subject.subject_hash,
            "executor_ids":executor_ids,
            "capture_boundary":"confirmed pause of the exclusively provisioned workspace executor; confirmed resume"})).await?;
        // Adaptive feedback never queries withheld acceptance cases.
        policy = super::selection::public_checks_policy(&policy);
        let checks_policy_hash = super::digest_of(
            "progress_checks_v1",
            &(
                &policy,
                &self.profile.check,
                super::identity::harness_sha256(),
            ),
        );
        let policy_hash = super::digest_of(
            "progress_assessment_v2",
            &(
                &policy,
                &self.profile.check,
                super::identity::harness_sha256(),
                diagnostic_review.then_some(&self.policies.reviewer),
            ),
        );
        // Artifact-only checks may be reused; diagnosis also depends on the evolving
        // execution observations. A new diagnosis request gets a new frozen basis.
        let includes_review = diagnostic_review;
        for (_, handle) in previous.completed.iter().filter(|_| !includes_review) {
            let old: Value =
                serde_json::from_slice(&self.store.get(handle).map_err(|e| e.to_string())?)
                    .map_err(|e| e.to_string())?;
            if old["subject_hash"] == json!(subject.subject_hash)
                && old["assessment_policy_hash"] == json!(policy_hash)
                && old
                    .get("assessment_request")
                    .map_or(options == ProgressAssessment::default(), |value| {
                        *value == json!(options)
                    })
            {
                let mut completed = reserved.clone();
                completed.pending = None;
                completed.completed.push((request, *handle));
                if !self
                    .ledger
                    .compare_exchange_record(
                        PROGRESS,
                        &self.thread_id.to_string(),
                        Some(&reserved),
                        &completed,
                    )
                    .await
                    .map_err(|e| e.to_string())?
                {
                    return Err("publication completion lost ownership".into());
                }
                return Ok(
                    json!({"handle":handle,"reused":true,"scope":"progress_only","read_with":"contract_read_evidence"}),
                );
            }
        }
        let work = self
            .work_dir()
            .join("progress")
            .join(reserved.used.to_string())
            .join("candidate");
        self.materialize(&subject, &work).await?;
        let handoff = WorkSnapshot {
            capture: super::super::observations::CaptureKind::Progress,
            response: super::delivery::ResponseCapture::Absent,
            epoch,
            contract,
            subject,
            turn_id: turn,
            policy,
            terms,
            base,
        };
        let mut diagnosis = super::verification::Diagnosis {
            question: options.question.clone(),
            prior,
            checks: None,
        };
        if let Some(prior) = &diagnosis.prior {
            let old = &prior["document"];
            if old["scope"] == "progress_only"
                && old["effects_resolved"] == true
                && old["subject_hash"] == json!(handoff.subject.subject_hash)
                && old["revision"] == json!(handoff.contract.revision)
                && old["checks_policy_hash"] == json!(checks_policy_hash)
                && old["check_receipts"]["complete"] == true
            {
                diagnosis.checks = Some(
                    serde_json::from_value(old["check_receipts"].clone())
                        .map_err(|e| e.to_string())?,
                );
            }
        }
        let checks_reused = diagnosis.checks.is_some();
        let assessment = self
            .assess_snapshot(
                &handoff,
                &work,
                Some(deadline),
                false,
                diagnostic_review,
                Some(&diagnosis),
            )
            .await;
        let safe = assessment.effects_resolved;
        let review_available = assessment.public.review.is_some();
        let checkpoint_count = assessment.public.review_checkpoints.len();
        let mut feedback = match &assessment.verdict {
            crate::controller::decision::Verdict::Support => "Local assessment supports this frozen snapshot; full acceptance has not been performed.".to_string(),
            crate::controller::decision::Verdict::Defeat { residual, .. } => residual.clone(),
            crate::controller::decision::Verdict::NotVerified { reason, .. } => reason.clone(),
        };
        if checkpoint_count > 0 {
            feedback.push_str(&format!("\n{checkpoint_count} diagnostic checkpoint(s) retained independently of the final review. Read them through contract_read_evidence; their judgments remain bound to the recorded subject."));
        }
        let document = json!({"schema_version":1,"scope":"progress_only","contract_id":handoff.contract.id.0,
            "revision":handoff.contract.revision,"publication":reserved.used,"request_id":request,
            "subject_hash":handoff.subject.subject_hash,"assessment_policy_hash":policy_hash,
            "diagnostic_review":diagnostic_review,
            "assessment_request":options,"checks_policy_hash":checks_policy_hash,
            "check_receipts":assessment.checks.as_ref().ok(),"checks_reused":checks_reused,
            "feedback":feedback,"public":assessment.public,"effects_resolved":safe});
        let handle = self
            .store
            .put(&serde_json::to_vec(&document).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        self.append_event(
            ExperimentKind::Execution,
            None,
            json!({"phase":"progress_assessed",
            "contract_id":handoff.contract.id.0,"publication":reserved.used,
            "subject_hash":handoff.subject.subject_hash,"public_evidence":handle}),
        )
        .await?;
        if safe {
            let mut completed = reserved.clone();
            completed.pending = None;
            completed.completed.push((request, handle));
            if !self
                .ledger
                .compare_exchange_record(
                    PROGRESS,
                    &self.thread_id.to_string(),
                    Some(&reserved),
                    &completed,
                )
                .await
                .map_err(|e| e.to_string())?
            {
                return Err("publication completion lost ownership".into());
            }
        }
        Ok(
            json!({"handle":handle,"subject_hash":handoff.subject.subject_hash,"publication":reserved.used,
            "scope":"progress_only","feedback":crate::workers::bounded(&feedback, 2000),
            "diagnostic_review_requested":diagnostic_review,"review_available":review_available,
            "review_checkpoints":document["public"]["review_checkpoints"],"checks_reused":checks_reused,
            "review_error":document["public"]["review_error"],
            "effects_resolved":safe,"read_with":"contract_read_evidence","completion_certified":false}),
        )
    }
}
