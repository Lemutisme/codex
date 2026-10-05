//! Pure verification decisions and the text the executor and the reviewer see (brief, residual,
//! receipt summary).

use std::collections::BTreeSet;

use serde::Serialize;

use crate::CheckError;
use crate::CheckReceipts;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::Terms;
use crate::WorkerError;
use crate::checks::PUBLIC;
use crate::checks::SEALED;
use crate::workers::bounded;
use crate::workers::bounded_head_tail;
use crate::workers::reviewer::Review;
use crate::workers::reviewer::ReviewVerdict;

/// Cap on the brief and on a residual, about 512 tokens.
pub(crate) const EXECUTOR_TEXT_CAP: usize = 2000;
/// Bytes of one public failure's detail in a residual.
const FAILURE_DETAIL_CAP: usize = 600;
/// Room kept in a residual for the line that counts omitted failures.
const OMITTED_LINE_RESERVE: usize = 60;
/// Failing sealed families named in a residual.
const RESIDUAL_FAMILIES: usize = 12;

/// Why no judgment could be formed.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum NotVerifiedClass {
    /// The checks or the lane's own machinery failed.
    Infrastructure,
    /// Too few qualified sealed cases, or too few exercising success paths.
    InsufficientEvidence,
    /// The reviewer failed or could not judge.
    ReviewerUnable,
    /// The reviewer found the terms unfaithful to the request.
    TermsGap,
    /// The executor's turn ended without handing off a candidate.
    NoHandoff,
}

impl NotVerifiedClass {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            NotVerifiedClass::Infrastructure => "infrastructure",
            NotVerifiedClass::InsufficientEvidence => "insufficient_evidence",
            NotVerifiedClass::ReviewerUnable => "reviewer_unable",
            NotVerifiedClass::TermsGap => "terms_gap",
            NotVerifiedClass::NoHandoff => "no_handoff",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Verdict {
    Support,
    /// A frozen requirement failed; the residual is shown to the executor on repair.
    Defeat {
        residual: String,
    },
    /// No judgment could be formed; nothing is shown to the executor.
    NotVerified {
        class: NotVerifiedClass,
        reason: String,
    },
}

fn not_verified(class: NotVerifiedClass, reason: impl Into<String>) -> Verdict {
    Verdict::NotVerified {
        class,
        reason: reason.into(),
    }
}

/// The sealed partition's evidence in one verification.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub(crate) struct SealedTally {
    pub qualified: u32,
    pub passed: u32,
    pub unqualified: u32,
    /// Qualified cases on which the reference exited zero.
    pub succeeded: u32,
    pub failing_families: BTreeSet<String>,
}

impl SealedTally {
    fn of(receipts: &CheckReceipts, policy: &EvidencePolicy) -> Self {
        let mut tally = Self::default();
        for step in sealed_steps(receipts) {
            let id = step.step.trim_start_matches(SEALED).trim_start_matches(':');
            match step.outcome {
                StepOutcome::Unqualified => tally.unqualified += 1,
                StepOutcome::Pass | StepOutcome::Fail => {
                    tally.qualified += 1;
                    if step.reference_exit == Some(0) {
                        tally.succeeded += 1;
                    }
                    if step.outcome == StepOutcome::Pass {
                        tally.passed += 1;
                    } else {
                        let family = policy
                            .sealed
                            .iter()
                            .find(|case| case.id == id)
                            .map(|case| case.family.clone())
                            .filter(|family| !family.is_empty())
                            .unwrap_or_else(|| "untagged".to_string());
                        tally.failing_families.insert(family);
                    }
                }
            }
        }
        tally
    }

    fn line(&self) -> String {
        format!(
            "{} of {} qualified sealed checks agree with the reference ({} unqualified)",
            self.passed, self.qualified, self.unqualified
        )
    }
}

fn sealed_steps(receipts: &CheckReceipts) -> impl Iterator<Item = &StepReceipt> {
    receipts
        .steps
        .iter()
        .filter(|step| step.step.starts_with(&format!("{SEALED}:")))
}

/// Whether the policy's sealed evidence applies: only differential evidence can be sealed.
fn sealed_applies(policy: &EvidencePolicy) -> bool {
    policy.reference_command.is_some() && policy.candidate_command.is_some()
}

/// Decides from the mechanical checks alone, or returns `None` when they pass and the review
/// decides.
pub(crate) fn mechanical_verdict(
    checks: &Result<CheckReceipts, CheckError>,
    policy: &EvidencePolicy,
) -> Option<Verdict> {
    let receipts = match checks {
        Ok(receipts) => receipts,
        Err(error) => {
            return Some(not_verified(
                NotVerifiedClass::Infrastructure,
                format!("checks could not run: {error}"),
            ));
        }
    };
    if !receipts.complete {
        return Some(not_verified(
            NotVerifiedClass::Infrastructure,
            "the check pipeline did not report every step",
        ));
    }
    let failures: Vec<&StepReceipt> = receipts
        .steps
        .iter()
        .filter(|step| step.outcome == StepOutcome::Fail && !step.step.starts_with(SEALED))
        .collect();
    let tally = SealedTally::of(receipts, policy);
    let sealed_defeat =
        sealed_applies(policy) && sufficient(&tally, policy) && below_threshold(&tally, policy);
    if !failures.is_empty() || sealed_defeat {
        return Some(Verdict::Defeat {
            residual: residual(&failures, sealed_defeat.then_some(&tally), policy),
        });
    }
    if sealed_applies(policy) && !sufficient(&tally, policy) {
        return Some(not_verified(
            NotVerifiedClass::InsufficientEvidence,
            format!(
                "insufficient evidence: {}, {} with a successful reference run; support needs at least {} qualified and {}‰ successful",
                tally.line(),
                tally.succeeded,
                policy.min_sealed_qualified,
                policy.min_success_permille
            ),
        ));
    }
    None
}

fn sufficient(tally: &SealedTally, policy: &EvidencePolicy) -> bool {
    tally.qualified >= policy.min_sealed_qualified
        && u64::from(tally.succeeded) * 1000
            >= u64::from(policy.min_success_permille) * u64::from(tally.qualified)
}

fn below_threshold(tally: &SealedTally, policy: &EvidencePolicy) -> bool {
    u64::from(tally.passed) * 1000
        < u64::from(policy.sealed_threshold_permille) * u64::from(tally.qualified)
}

/// The residual of a mechanical defeat: the sealed line first (it alone measures breadth), then
/// public failures in full while they fit, sealed failures only in aggregate.
fn residual(
    failures: &[&StepReceipt],
    sealed: Option<&SealedTally>,
    policy: &EvidencePolicy,
) -> String {
    let mut residual = String::from(
        "Independent verification of your handoff did not pass. Fix these unmet requirements, then end your turn:\n",
    );
    if let Some(tally) = sealed {
        let families: Vec<&str> = tally
            .failing_families
            .iter()
            .take(RESIDUAL_FAMILIES)
            .map(String::as_str)
            .collect();
        residual.push_str(&format!(
            "- {} of {} independent sealed checks did not match the reference, in these behavior families: {}. Their invocations are not disclosed; re-check the documented behavior in these areas.\n",
            tally.qualified - tally.passed,
            tally.qualified,
            families.join(", ")
        ));
    }
    let mut shown = 0;
    for failure in failures {
        let entry = failure_entry(failure, policy, FAILURE_DETAIL_CAP);
        if residual.len() + entry.len() + OMITTED_LINE_RESERVE > EXECUTOR_TEXT_CAP {
            if shown == 0 {
                // Never leave the executor without a single public failure: shrink the first.
                let room = EXECUTOR_TEXT_CAP.saturating_sub(residual.len() + OMITTED_LINE_RESERVE);
                let overhead = entry.len().saturating_sub(FAILURE_DETAIL_CAP);
                let shrunk = failure_entry(failure, policy, room.saturating_sub(overhead).max(80));
                residual.push_str(&shrunk);
                shown = 1;
            }
            break;
        }
        residual.push_str(&entry);
        shown += 1;
    }
    if shown < failures.len() {
        residual.push_str(&format!(
            "[... {} more failed checks omitted ...]\n",
            failures.len() - shown
        ));
    }
    bounded(&residual, EXECUTOR_TEXT_CAP)
}

/// One public failure of a residual, its detail kept at head and tail within `detail_cap`.
fn failure_entry(failure: &StepReceipt, policy: &EvidencePolicy, detail_cap: usize) -> String {
    let invocation = failure
        .step
        .strip_prefix(&format!("{PUBLIC}:"))
        .and_then(|id| policy.differential.iter().find(|case| case.id == id))
        .map(|case| {
            let stdin = case
                .stdin
                .as_deref()
                .map(|stdin| format!(" with stdin {:?}", bounded(stdin, 200)))
                .unwrap_or_default();
            let fixtures: Vec<&str> = case
                .files
                .iter()
                .map(|file| file.path.as_str())
                .chain(case.dirs.iter().map(String::as_str))
                .collect();
            let fixtures = if fixtures.is_empty() {
                String::new()
            } else {
                format!(" over fixtures {}", fixtures.join(", "))
            };
            format!(
                " (program arguments {:?}{stdin}{fixtures}, run in a copy of the workspace; behavior must match the reference)",
                case.args
            )
        })
        .unwrap_or_default();
    format!(
        "- {} failed{invocation}:\n{}\n",
        failure.step,
        bounded_head_tail(failure.detail.trim_end(), detail_cap)
    )
}

/// Decides from the review once the mechanical checks pass.
pub(crate) fn review_verdict(review: Option<&Result<Review, WorkerError>>) -> Verdict {
    let review = match review {
        None => {
            return not_verified(NotVerifiedClass::ReviewerUnable, "no review was obtained");
        }
        Some(Err(error)) => {
            return not_verified(
                NotVerifiedClass::ReviewerUnable,
                format!("review failed: {error}"),
            );
        }
        Some(Ok(review)) => review,
    };
    if !review.terms_gap.is_empty() {
        return not_verified(
            NotVerifiedClass::TermsGap,
            format!(
                "termsGap: the contract may have missed {}",
                review
                    .terms_gap
                    .iter()
                    .map(|gap| gap.element.as_str())
                    .collect::<Vec<_>>()
                    .join("; ")
            ),
        );
    }
    match &review.verdict {
        ReviewVerdict::Support { .. } => Verdict::Support,
        ReviewVerdict::Defeat { findings, residual } => {
            let mut text = String::from(
                "Independent review of your handoff found unmet requirements. Fix them, then end your turn:\n",
            );
            for finding in findings {
                text.push_str(&format!(
                    "- {} at {}: {}\n",
                    finding.requirement_id, finding.location, finding.counterexample
                ));
            }
            if !residual.trim().is_empty() {
                text.push_str(residual.trim());
                text.push('\n');
            }
            Verdict::Defeat {
                residual: bounded(&text, EXECUTOR_TEXT_CAP),
            }
        }
        ReviewVerdict::CannotJudge { missing } => not_verified(
            NotVerifiedClass::ReviewerUnable,
            format!("the reviewer could not judge: {missing}"),
        ),
    }
}

/// Combines the check receipts and, when they pass, the review.
pub(crate) fn decide(
    checks: &Result<CheckReceipts, CheckError>,
    review: Option<&Result<Review, WorkerError>>,
    policy: &EvidencePolicy,
) -> Verdict {
    mechanical_verdict(checks, policy).unwrap_or_else(|| review_verdict(review))
}

/// The receipts as the reviewer sees them: every non-sealed step, sealed steps only in aggregate.
pub(crate) fn review_summary(receipts: &CheckReceipts, policy: &EvidencePolicy) -> String {
    let mut text = format!("environment: {}\n", receipts.environment.join(" | "));
    for step in &receipts.steps {
        if step.step.starts_with(&format!("{SEALED}:")) {
            continue;
        }
        text.push_str(&format!("{}: {:?}\n", step.step, step.outcome));
        if !step.detail.is_empty() {
            text.push_str(&bounded(&step.detail, 800));
            text.push('\n');
        }
    }
    if sealed_applies(policy) {
        text.push_str(&format!(
            "sealed: {}\n",
            SealedTally::of(receipts, policy).line()
        ));
    }
    text
}

/// The sealed evidence of a verification, for the experiment record.
pub(crate) fn sealed_tally(receipts: &CheckReceipts, policy: &EvidencePolicy) -> SealedTally {
    SealedTally::of(receipts, policy)
}

fn brief_header(contract_id: &str, revision: u32) -> String {
    format!("ProContract {contract_id} revision {revision}")
}

/// The executor's brief: how the handoff is checked, the work constraints, then the requirements,
/// identified by contract and revision. Bounding cuts requirements first.
pub(crate) fn brief_text(
    contract_id: &str,
    revision: u32,
    terms: &Terms,
    policy: &EvidencePolicy,
) -> String {
    let mut text = format!(
        "{}\nThis task is under a contract. When you end your turn, the workspace is handed off to an independent verifier.\n{}\n",
        brief_header(contract_id, revision),
        evidence_line(policy)
    );
    if !terms.process_constraints.is_empty() {
        text.push_str("Work constraints:\n");
        for constraint in &terms.process_constraints {
            text.push_str(&format!("- {}\n", constraint.text));
        }
    }
    text.push_str("Requirements:\n");
    for requirement in &terms.requirements {
        text.push_str(&format!("{}: {}\n", requirement.id, requirement.text));
    }
    bounded(&text, EXECUTOR_TEXT_CAP)
}

/// The evidence class and the checks it implies, without cases or budgets.
fn evidence_line(policy: &EvidencePolicy) -> String {
    match policy.class {
        EvidenceClass::ReviewOnly => {
            "Evidence: review only. An independent reviewer checks each requirement.".to_string()
        }
        EvidenceClass::ChecksAndReview => {
            let mut checks = Vec::new();
            if let Some(build) = &policy.build_command {
                checks.push(format!("a clean copy is built with `{build}`"));
            }
            if policy.candidate_tests {
                checks.push("your own tests must pass under `cargo test --offline`".to_string());
            }
            if sealed_applies(policy) {
                checks.push(
                    "exit status, standard output, standard error and resulting files are compared with the reference program on fixed invocations run in a copy of the workspace, including a larger sealed set whose contents are never shown"
                        .to_string(),
                );
            }
            if checks.is_empty() {
                return "Evidence: checks and review. An independent reviewer checks each requirement."
                    .to_string();
            }
            format!(
                "Evidence: checks and review. {}; then an independent reviewer checks each requirement.",
                checks.join("; ")
            )
        }
    }
}

/// Whether `text` is the brief for this exact contract and revision.
pub(crate) fn is_current_brief(text: &str, contract_id: &str, revision: u32) -> bool {
    let header = brief_header(contract_id, revision);
    text.lines().any(|line| line.trim() == header)
}

#[cfg(test)]
#[path = "decision_tests.rs"]
mod tests;
