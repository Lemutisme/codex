//! Pure verification decisions and the text the executor sees (brief and residual).

use crate::CheckError;
use crate::CheckReceipts;
use crate::EvidencePolicy;
use crate::StepOutcome;
use crate::Terms;
use crate::WorkerError;
use crate::workers::bounded;
use crate::workers::reviewer::ReviewVerdict;

/// Cap on the brief and on a residual, about 512 tokens.
pub(crate) const EXECUTOR_TEXT_CAP: usize = 2000;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Verdict {
    Support,
    /// A frozen requirement failed; the residual is shown to the executor on repair.
    Defeat {
        residual: String,
    },
    /// No judgment could be formed; nothing is shown to the executor.
    NotVerified {
        reason: String,
    },
}

/// Combines check receipts and, when the checks passed, the review.
pub(crate) fn decide(
    checks: &Result<CheckReceipts, CheckError>,
    review: Option<&Result<ReviewVerdict, WorkerError>>,
    policy: &EvidencePolicy,
) -> Verdict {
    let not_verified = |reason: String| Verdict::NotVerified { reason };
    let receipts = match checks {
        Ok(receipts) => receipts,
        Err(error) => return not_verified(format!("checks could not run: {error}")),
    };
    let failures: Vec<_> = receipts
        .steps
        .iter()
        .filter(|step| step.outcome == StepOutcome::Fail)
        .collect();
    if !failures.is_empty() {
        let mut residual = String::from(
            "Independent verification of your handoff did not pass. Fix these unmet requirements, then end your turn:\n",
        );
        for failure in failures {
            let invocation = failure
                .step
                .strip_prefix("differential:")
                .and_then(|id| policy.differential.iter().find(|case| case.id == id))
                .map(|case| {
                    let stdin = case
                        .stdin
                        .as_deref()
                        .map(|stdin| format!(" with stdin {:?}", bounded(stdin, 200)))
                        .unwrap_or_default();
                    format!(" (program arguments {:?}{stdin}; stdout and exit status must match the reference)", case.args)
                })
                .unwrap_or_default();
            residual.push_str(&format!(
                "- {} failed{invocation}:\n{}\n",
                failure.step,
                bounded(failure.detail.trim_end(), 600)
            ));
        }
        return Verdict::Defeat {
            residual: bounded(&residual, EXECUTOR_TEXT_CAP),
        };
    }
    if !receipts.complete {
        return not_verified("the check pipeline did not report every step".to_string());
    }
    match review {
        None => not_verified("no review was obtained".to_string()),
        Some(Err(error)) => not_verified(format!("review failed: {error}")),
        Some(Ok(ReviewVerdict::Support { .. })) => Verdict::Support,
        Some(Ok(ReviewVerdict::Defeat { findings, residual })) => {
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
        Some(Ok(ReviewVerdict::CannotJudge { missing })) => {
            not_verified(format!("the reviewer could not judge: {missing}"))
        }
        Some(Ok(ReviewVerdict::TermsGap { gaps })) => not_verified(format!(
            "termsGap: the contract may have missed {}",
            gaps.iter()
                .map(|gap| gap.element.as_str())
                .collect::<Vec<_>>()
                .join("; ")
        )),
    }
}

fn brief_header(contract_id: &str, revision: u32) -> String {
    format!("ProContract {contract_id} revision {revision}")
}

/// The executor's brief: numbered requirements, identified by contract and revision.
pub(crate) fn brief_text(contract_id: &str, revision: u32, terms: &Terms) -> String {
    let mut text = format!(
        "{}\nThis task is under a contract. When you end your turn, the workspace is handed off to an independent verifier, which checks these requirements:\n",
        brief_header(contract_id, revision)
    );
    for requirement in &terms.requirements {
        text.push_str(&format!("{}: {}\n", requirement.id, requirement.text));
    }
    bounded(&text, EXECUTOR_TEXT_CAP)
}

/// Whether `text` is the brief for this exact contract and revision.
pub(crate) fn is_current_brief(text: &str, contract_id: &str, revision: u32) -> bool {
    let header = brief_header(contract_id, revision);
    text.lines().any(|line| line.trim() == header)
}

#[cfg(test)]
#[path = "decision_tests.rs"]
mod tests;
