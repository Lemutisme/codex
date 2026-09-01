use crate::error_code::invalid_request;
use codex_app_server_protocol::ClientResponsePayload;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::ProContractAttestParams;
use codex_app_server_protocol::ProContractAttestResponse;
use codex_app_server_protocol::ProContractBlocked;
use codex_app_server_protocol::ProContractBudget as ApiBudget;
use codex_app_server_protocol::ProContractChallenge as ApiChallenge;
use codex_app_server_protocol::ProContractChallengeDisclosure as ApiChallengeDisclosure;
use codex_app_server_protocol::ProContractChallengeParams;
use codex_app_server_protocol::ProContractChallengeResponse;
use codex_app_server_protocol::ProContractEscalation as ApiEscalation;
use codex_app_server_protocol::ProContractEvidence as ApiEvidence;
use codex_app_server_protocol::ProContractExecutionInfo;
use codex_app_server_protocol::ProContractHandoff as ApiHandoff;
use codex_app_server_protocol::ProContractHandoffMaterializeParams;
use codex_app_server_protocol::ProContractHandoffMaterializeResponse;
use codex_app_server_protocol::ProContractInfo;
use codex_app_server_protocol::ProContractIssueParams;
use codex_app_server_protocol::ProContractIssueResponse;
use codex_app_server_protocol::ProContractPendingRevision as ApiPendingRevision;
use codex_app_server_protocol::ProContractProtectedFile as ApiProtectedFile;
use codex_app_server_protocol::ProContractQuiet as ApiQuiet;
use codex_app_server_protocol::ProContractQuietParams;
use codex_app_server_protocol::ProContractQuietResponse;
use codex_app_server_protocol::ProContractReadParams;
use codex_app_server_protocol::ProContractReadResponse;
use codex_app_server_protocol::ProContractReleaseParams;
use codex_app_server_protocol::ProContractReleaseResponse;
use codex_app_server_protocol::ProContractReplayCheck as ApiReplayCheck;
use codex_app_server_protocol::ProContractReplayPolicy as ApiReplayPolicy;
use codex_app_server_protocol::ProContractReplayResult as ApiReplayResult;
use codex_app_server_protocol::ProContractRequirement as ApiRequirement;
use codex_app_server_protocol::ProContractResolution as ApiResolution;
use codex_app_server_protocol::ProContractResumeParams;
use codex_app_server_protocol::ProContractResumeResponse;
use codex_app_server_protocol::ProContractRevisionDecideParams;
use codex_app_server_protocol::ProContractRevisionDecideResponse;
use codex_app_server_protocol::ProContractRevisionDecision;
use codex_app_server_protocol::ProContractSpec as ApiSpec;
use codex_app_server_protocol::ProContractStatus as ApiStatus;
use codex_app_server_protocol::ProContractSubject as ApiSubject;
use codex_app_server_protocol::ProContractTrigger as ApiTrigger;
use codex_core::config::Config;
use codex_features::Feature;
use codex_pro_contract::ArtifactPath;
use codex_pro_contract::ArtifactSpec;
use codex_pro_contract::Budget;
use codex_pro_contract::ChallengeDisclosure;
use codex_pro_contract::Contract;
use codex_pro_contract::ContractSpec;
use codex_pro_contract::Evidence;
use codex_pro_contract::ProtectedFile;
use codex_pro_contract::QuietSnapshot;
use codex_pro_contract::ReplayCheck;
use codex_pro_contract::ReplayPolicy;
use codex_pro_contract::Requirement;
use codex_pro_contract::Resolution;
use codex_pro_contract::Status;
use codex_pro_contract::Trigger;
use codex_pro_contract_extension::PrincipalAttestation;
use codex_pro_contract_extension::PrincipalChallenge;
use codex_pro_contract_extension::PrincipalContractCoordinate;
use codex_pro_contract_extension::PrincipalRevisionDecision;
use codex_pro_contract_extension::ProContractController;
use codex_pro_contract_extension::ProContractControllerError;
use codex_pro_contract_extension::ProContractIssue;
use codex_pro_contract_extension::RevisionDecision;
use codex_protocol::ThreadId;
use std::sync::Arc;

#[derive(Clone)]
pub(crate) struct ProContractRequestProcessor {
    controller: ProContractController,
    config: Arc<Config>,
}

impl ProContractRequestProcessor {
    pub(crate) fn new(controller: ProContractController, config: Arc<Config>) -> Self {
        Self { controller, config }
    }

    pub(crate) async fn issue(
        &self,
        params: ProContractIssueParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let thread_id = parse_thread_id(&params.thread_id)?;
        let result = self
            .controller
            .issue(ProContractIssue {
                thread_id,
                spec: contract_spec(params.spec)?,
                execution_policy: params.execution_policy,
                original_request: params.original_request,
            })
            .await
            .map_err(controller_error)?;
        let principal = self
            .controller
            .principal(thread_id, result.contract.id.clone())
            .map_err(controller_error)?;
        let quiet = principal.quiet().await.map_err(principal_error)?;
        Ok(Some(
            ProContractIssueResponse {
                contract: contract_info(result.contract),
                execution: ProContractExecutionInfo {
                    contract_id: result.execution.contract_id,
                    revision: result.execution.revision,
                    executor_thread_id: result
                        .execution
                        .executor_thread_id
                        .map(|thread_id| thread_id.to_string()),
                    execution_policy: result.execution.execution_policy,
                    execution_policy_hash: result.execution.execution_policy_hash,
                    dispatched: result.execution.dispatched,
                    awaiting_revision_decision: result.execution.awaiting_revision_decision,
                    attempts: result.execution.attempts,
                    turns_used: result.execution.turns_used,
                    actions_used: result.execution.actions_used,
                    next_action_at: millis_to_seconds(result.execution.next_action_at),
                    turns_limit: result.execution.turns_limit,
                    actions_limit: result.execution.actions_limit,
                    deadline_at: millis_to_seconds(result.execution.deadline),
                    max_attempts: result.execution.max_attempts,
                    lease_owner: result.execution.lease_owner,
                    lease_expires_at: millis_to_seconds(result.execution.lease_expires_at),
                },
                compiler_manifest_hash: result.compiler_manifest_hash,
                quiet: quiet_info(quiet),
            }
            .into(),
        ))
    }

    pub(crate) async fn read(
        &self,
        params: ProContractReadParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        let state = principal.state().await.map_err(principal_error)?;
        let contract = state
            .contracts
            .get(principal.contract_id())
            .cloned()
            .ok_or_else(|| invalid_request("contract not found"))?;
        let quiet = principal.quiet().await.map_err(principal_error)?;
        let execution = match self
            .controller
            .execution(parse_thread_id(&params.thread_id)?, principal.contract_id())
            .await
        {
            Ok(execution) => execution.map(execution_info),
            Err(ProContractControllerError::PrincipalUnavailable) => None,
            Err(error) => return Err(controller_error(error)),
        };
        Ok(Some(
            ProContractReadResponse {
                contract: contract_info(contract),
                execution,
                quiet: quiet_info(quiet),
            }
            .into(),
        ))
    }

    pub(crate) async fn quiet(
        &self,
        params: ProContractQuietParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let principal = self
            .principal(&params.thread_id, "pct_quiet".to_string())
            .await?;
        Ok(Some(
            ProContractQuietResponse {
                quiet: quiet_info(principal.quiet().await.map_err(principal_error)?),
            }
            .into(),
        ))
    }

    pub(crate) async fn attest(
        &self,
        params: ProContractAttestParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        principal
            .attest_exact(PrincipalAttestation {
                revision: params.revision,
                spec_hash: params.spec_hash,
                subject_hash: params.subject_hash,
                evidence_hash: params.evidence_hash,
            })
            .await
            .map_err(principal_error)?;
        let (contract, quiet) = mutation_state(&principal).await?;
        Ok(Some(ProContractAttestResponse { contract, quiet }.into()))
    }

    pub(crate) async fn materialize_handoff(
        &self,
        params: ProContractHandoffMaterializeParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let destination = params.destination.to_inferred_abs_path().ok_or_else(|| {
            invalid_request("handoff destination must be a host-local absolute path")
        })?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        let subject = principal
            .materialize_handoff(destination.as_path().to_path_buf())
            .await
            .map_err(principal_error)?;
        Ok(Some(
            ProContractHandoffMaterializeResponse {
                subject: ApiSubject {
                    hash: subject.hash,
                    spec_hash: subject.spec_hash,
                    artifacts: artifact_paths(subject.artifacts),
                },
                destination: params.destination,
            }
            .into(),
        ))
    }

    pub(crate) async fn challenge(
        &self,
        params: ProContractChallengeParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let thread_id = parse_thread_id(&params.thread_id)?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        let challenge = match params.disclosure {
            ApiChallengeDisclosure::Executor => PrincipalChallenge::Executor {
                evidence_hash: params.evidence_hash,
                summary: params
                    .summary
                    .ok_or_else(|| invalid_request("executor challenge requires a summary"))?,
            },
            ApiChallengeDisclosure::Sealed => {
                if params.summary.is_some() {
                    return Err(invalid_request("sealed challenge cannot include a summary"));
                }
                PrincipalChallenge::Sealed {
                    evidence_hash: params.evidence_hash,
                }
            }
        };
        principal
            .challenge_exact(params.revision, params.subject_hash, challenge)
            .await
            .map_err(principal_error)?;
        self.controller.reconcile_loaded(thread_id).await;
        let (contract, quiet) = mutation_state(&principal).await?;
        Ok(Some(
            ProContractChallengeResponse { contract, quiet }.into(),
        ))
    }

    pub(crate) async fn decide_revision(
        &self,
        params: ProContractRevisionDecideParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let thread_id = parse_thread_id(&params.thread_id)?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        principal
            .decide_revision_exact(PrincipalRevisionDecision {
                revision: params.revision,
                spec_hash: params.spec_hash,
                decision: match params.decision {
                    ProContractRevisionDecision::Accept => RevisionDecision::Accept,
                    ProContractRevisionDecision::Reject => RevisionDecision::Reject,
                },
            })
            .await
            .map_err(principal_error)?;
        self.controller.reconcile_loaded(thread_id).await;
        let (contract, quiet) = mutation_state(&principal).await?;
        Ok(Some(
            ProContractRevisionDecideResponse { contract, quiet }.into(),
        ))
    }

    pub(crate) async fn resume(
        &self,
        params: ProContractResumeParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let thread_id = parse_thread_id(&params.thread_id)?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        principal
            .resume_exact(PrincipalContractCoordinate {
                revision: params.revision,
                spec_hash: params.spec_hash,
            })
            .await
            .map_err(principal_error)?;
        self.controller.reconcile_loaded(thread_id).await;
        let (contract, quiet) = mutation_state(&principal).await?;
        Ok(Some(ProContractResumeResponse { contract, quiet }.into()))
    }

    pub(crate) async fn release(
        &self,
        params: ProContractReleaseParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_enabled()?;
        let principal = self
            .principal(&params.thread_id, params.contract_id)
            .await?;
        principal
            .release_exact(
                PrincipalContractCoordinate {
                    revision: params.revision,
                    spec_hash: params.spec_hash,
                },
                params.reason,
            )
            .await
            .map_err(principal_error)?;
        let (contract, quiet) = mutation_state(&principal).await?;
        Ok(Some(ProContractReleaseResponse { contract, quiet }.into()))
    }

    async fn principal(
        &self,
        thread_id: &str,
        contract_id: String,
    ) -> Result<codex_pro_contract_extension::ProContractPrincipal, JSONRPCErrorError> {
        let thread_id = parse_thread_id(thread_id)?;
        match self.controller.principal(thread_id, contract_id.clone()) {
            Ok(principal) => Ok(principal),
            Err(ProContractControllerError::PrincipalUnavailable) => {
                codex_pro_contract_extension::ProContractPrincipal::open_contract(
                    &self.config.sqlite,
                    thread_id.to_string(),
                    contract_id,
                )
                .await
                .map_err(principal_error)
            }
            Err(error) => Err(controller_error(error)),
        }
    }

    fn ensure_enabled(&self) -> Result<(), JSONRPCErrorError> {
        if self.config.features.enabled(Feature::ProContract) {
            Ok(())
        } else {
            Err(invalid_request("ProContract feature is disabled"))
        }
    }
}

async fn mutation_state(
    principal: &codex_pro_contract_extension::ProContractPrincipal,
) -> Result<(ProContractInfo, ApiQuiet), JSONRPCErrorError> {
    let state = principal.state().await.map_err(principal_error)?;
    let contract = state
        .contracts
        .get(principal.contract_id())
        .cloned()
        .ok_or_else(|| invalid_request("contract not found"))?;
    let quiet = principal.quiet().await.map_err(principal_error)?;
    Ok((contract_info(contract), quiet_info(quiet)))
}

fn parse_thread_id(thread_id: &str) -> Result<ThreadId, JSONRPCErrorError> {
    ThreadId::from_string(thread_id).map_err(|_| invalid_request("invalid thread id"))
}

fn contract_spec(spec: ApiSpec) -> Result<ContractSpec, JSONRPCErrorError> {
    let artifacts = artifact_spec(spec.artifacts)?;
    let replay = spec.evidence.replay.map(replay_policy).transpose()?;
    Ok(ContractSpec {
        trigger: match spec.trigger {
            ApiTrigger::Immediate => Trigger::Immediate,
            ApiTrigger::Time { trigger_at } => Trigger::Time {
                at: seconds_to_millis(trigger_at)?,
            },
        },
        goal: spec.goal,
        brief: spec.brief,
        artifacts,
        requires: spec
            .requires
            .into_iter()
            .map(|requirement| Requirement {
                contract_id: requirement.contract_id,
                revision: requirement.revision,
            })
            .collect(),
        authority: spec.authority,
        budget: Budget {
            turns: spec.budget.turns,
            actions: spec.budget.actions,
            deadline: seconds_to_millis(spec.budget.deadline_at)?,
        },
        evidence: Evidence {
            claim: spec.evidence.claim,
            replay,
        },
        resolution: Resolution {
            max_attempts: spec.resolution.max_attempts,
            retry_delay_ms: spec.resolution.retry_delay_ms,
        },
    })
}

fn replay_policy(policy: ApiReplayPolicy) -> Result<ReplayPolicy, JSONRPCErrorError> {
    Ok(ReplayPolicy {
        checks: policy
            .checks
            .into_iter()
            .map(|check| {
                Ok(ReplayCheck {
                    argv: check.argv,
                    cwd: check
                        .cwd
                        .map(ArtifactPath::new)
                        .transpose()
                        .map_err(path_error)?,
                    timeout_ms: check.timeout_ms,
                    exit: check.exit,
                })
            })
            .collect::<Result<Vec<_>, JSONRPCErrorError>>()?,
        protected: policy
            .protected
            .into_iter()
            .map(|file| {
                Ok(ProtectedFile {
                    path: ArtifactPath::new(file.path).map_err(path_error)?,
                    sha256: file.sha256,
                })
            })
            .collect::<Result<Vec<_>, JSONRPCErrorError>>()?,
        artifacts: artifact_spec(policy.artifacts)?,
    })
}

fn artifact_spec(paths: Vec<String>) -> Result<ArtifactSpec, JSONRPCErrorError> {
    ArtifactSpec::new(
        paths
            .into_iter()
            .map(ArtifactPath::new)
            .collect::<Result<Vec<_>, _>>()
            .map_err(path_error)?,
    )
    .map_err(path_error)
}

fn contract_info(contract: Contract) -> ProContractInfo {
    ProContractInfo {
        id: contract.id,
        scope: contract.scope,
        spec: spec_info(contract.spec),
        issuer: contract.issuer,
        executor: contract.executor,
        spec_hash: contract.spec_hash,
        revision: contract.revision,
        status: status_info(contract.status),
        blocked: contract.blocked.map(|blocked| ProContractBlocked {
            reason: blocked.reason,
            reported_at: millis_to_seconds(blocked.time),
        }),
        handoff: contract.handoff.map(|handoff| ApiHandoff {
            summary: handoff.summary,
            uncertainties: handoff.uncertainties,
            subject: ApiSubject {
                hash: handoff.subject.hash,
                spec_hash: handoff.subject.spec_hash,
                artifacts: artifact_paths(handoff.subject.artifacts),
            },
            replay: handoff.replay.map(replay_result_info),
            created_at: millis_to_seconds(handoff.time),
        }),
        challenge: contract.challenge.map(|challenge| ApiChallenge {
            revision: challenge.revision,
            subject_hash: challenge.subject_hash,
            evidence_hash: challenge.evidence_hash,
            disclosure: match challenge.disclosure {
                ChallengeDisclosure::Executor => ApiChallengeDisclosure::Executor,
                ChallengeDisclosure::Sealed => ApiChallengeDisclosure::Sealed,
            },
            summary: challenge.summary,
            created_at: millis_to_seconds(challenge.time),
            attestation_id: challenge.attestation_id,
        }),
        pending_revision: contract.pending_revision.map(|pending| ApiPendingRevision {
            spec: spec_info(pending.spec),
            spec_hash: pending.spec_hash,
            reason: pending.reason,
        }),
        attestation_id: contract.attestation_id,
        escalation: contract.escalation.map(|escalation| ApiEscalation {
            reason: escalation.reason,
            created_at: millis_to_seconds(escalation.time),
        }),
    }
}

fn spec_info(spec: ContractSpec) -> ApiSpec {
    ApiSpec {
        trigger: match spec.trigger {
            Trigger::Immediate => ApiTrigger::Immediate,
            Trigger::Time { at } => ApiTrigger::Time {
                trigger_at: millis_to_seconds(at),
            },
        },
        goal: spec.goal,
        brief: spec.brief,
        artifacts: artifact_paths(spec.artifacts.paths().to_vec()),
        requires: spec
            .requires
            .into_iter()
            .map(|requirement| ApiRequirement {
                contract_id: requirement.contract_id,
                revision: requirement.revision,
            })
            .collect(),
        authority: spec.authority,
        budget: ApiBudget {
            turns: spec.budget.turns,
            actions: spec.budget.actions,
            deadline_at: millis_to_seconds(spec.budget.deadline),
        },
        evidence: ApiEvidence {
            claim: spec.evidence.claim,
            replay: spec.evidence.replay.map(|replay| ApiReplayPolicy {
                checks: replay
                    .checks
                    .into_iter()
                    .map(|check| ApiReplayCheck {
                        argv: check.argv,
                        cwd: check.cwd.map(|path| path.as_str().to_string()),
                        timeout_ms: check.timeout_ms,
                        exit: check.exit,
                    })
                    .collect(),
                protected: replay
                    .protected
                    .into_iter()
                    .map(|file| ApiProtectedFile {
                        path: file.path.as_str().to_string(),
                        sha256: file.sha256,
                    })
                    .collect(),
                artifacts: artifact_paths(replay.artifacts.paths().to_vec()),
            }),
        },
        resolution: ApiResolution {
            max_attempts: spec.resolution.max_attempts,
            retry_delay_ms: spec.resolution.retry_delay_ms,
        },
    }
}

fn replay_result_info(replay: codex_pro_contract::ReplayResult) -> ApiReplayResult {
    ApiReplayResult {
        policy_hash: replay.policy_hash,
        subject_hash: replay.subject_hash,
        evidence_hash: replay.evidence_hash,
        passed: replay.passed,
        summary: replay.summary,
    }
}

fn status_info(status: Status) -> ApiStatus {
    match status {
        Status::Dormant => ApiStatus::Dormant,
        Status::Active => ApiStatus::Active,
        Status::Verification => ApiStatus::Verification,
        Status::Escalated => ApiStatus::Escalated,
        Status::Discharged => ApiStatus::Discharged,
        Status::Released => ApiStatus::Released,
    }
}

fn quiet_info(quiet: QuietSnapshot) -> ApiQuiet {
    ApiQuiet {
        scope: quiet.scope,
        quiet: quiet.quiet,
        frontier: quiet.frontier,
        ledger_hash: quiet.ledger_hash,
        state_hash: quiet.state_hash,
        outstanding: quiet.outstanding,
    }
}

fn execution_info(
    execution: codex_pro_contract_extension::ProContractExecution,
) -> ProContractExecutionInfo {
    ProContractExecutionInfo {
        contract_id: execution.contract_id,
        revision: execution.revision,
        executor_thread_id: execution
            .executor_thread_id
            .map(|thread_id| thread_id.to_string()),
        execution_policy: execution.execution_policy,
        execution_policy_hash: execution.execution_policy_hash,
        dispatched: execution.dispatched,
        awaiting_revision_decision: execution.awaiting_revision_decision,
        attempts: execution.attempts,
        turns_used: execution.turns_used,
        actions_used: execution.actions_used,
        next_action_at: millis_to_seconds(execution.next_action_at),
        turns_limit: execution.turns_limit,
        actions_limit: execution.actions_limit,
        deadline_at: millis_to_seconds(execution.deadline),
        max_attempts: execution.max_attempts,
        lease_owner: execution.lease_owner,
        lease_expires_at: millis_to_seconds(execution.lease_expires_at),
    }
}

fn artifact_paths(paths: Vec<ArtifactPath>) -> Vec<String> {
    paths
        .into_iter()
        .map(|path| path.as_str().to_string())
        .collect()
}

fn seconds_to_millis(seconds: i64) -> Result<u64, JSONRPCErrorError> {
    u64::try_from(seconds)
        .ok()
        .and_then(|seconds| seconds.checked_mul(1_000))
        .ok_or_else(|| invalid_request("contract timestamp is outside the supported range"))
}

fn millis_to_seconds(millis: u64) -> i64 {
    i64::try_from(millis / 1_000).unwrap_or(i64::MAX)
}

fn path_error(error: impl std::fmt::Display) -> JSONRPCErrorError {
    invalid_request(error.to_string())
}

fn controller_error(error: impl std::fmt::Display) -> JSONRPCErrorError {
    invalid_request(error.to_string())
}

fn principal_error(error: impl std::fmt::Display) -> JSONRPCErrorError {
    invalid_request(error.to_string())
}
