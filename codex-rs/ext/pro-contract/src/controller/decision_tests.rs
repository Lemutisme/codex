use codex_pro_contract::Digest;
use pretty_assertions::assert_eq;

use super::EXECUTOR_TEXT_CAP;
use super::Verdict;
use super::brief_text;
use super::decide;
use super::is_current_brief;
use crate::CheckError;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::Requirement;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::Terms;
use crate::WorkerError;
use crate::workers::reviewer::Coverage;
use crate::workers::reviewer::Finding;
use crate::workers::reviewer::ReviewVerdict;
use crate::workers::reviewer::TermsGap;

fn policy() -> EvidencePolicy {
    EvidencePolicy {
        class: EvidenceClass::ChecksAndReview,
        build_command: Some("./compile.sh".to_string()),
        candidate_command: Some("./executable".to_string()),
        candidate_tests: false,
        differential: vec![DifferentialCase {
            id: "D1".to_string(),
            args: vec!["--delimiter".to_string(), ";".to_string()],
            stdin: Some("a;b\n".to_string()),
        }],
        reference_command: Some("/workspace/executable".to_string()),
    }
}

fn receipts(steps: Vec<(&str, StepOutcome, &str)>, complete: bool) -> Result<CheckReceipts, CheckError> {
    Ok(CheckReceipts {
        steps: steps
            .into_iter()
            .map(|(step, outcome, detail)| StepReceipt {
                step: step.to_string(),
                outcome,
                detail: detail.to_string(),
            })
            .collect(),
        environment: vec![],
        complete,
        environment_digest: Digest::of(b"env"),
        evaluator_digest: Digest::of(b"eval"),
    })
}

fn passing() -> Result<CheckReceipts, CheckError> {
    receipts(
        vec![
            ("build", StepOutcome::Pass, ""),
            ("differential:D1", StepOutcome::Pass, ""),
        ],
        true,
    )
}

#[test]
fn checks_that_could_not_run_are_not_verified() {
    let verdict = decide(&Err(CheckError::TimedOut), None, &policy());
    assert!(matches!(verdict, Verdict::NotVerified { .. }));
}

#[test]
fn an_incomplete_pipeline_is_not_verified() {
    let verdict = decide(
        &receipts(vec![("build", StepOutcome::Pass, "")], false),
        None,
        &policy(),
    );
    assert!(matches!(verdict, Verdict::NotVerified { .. }));
}

#[test]
fn a_failed_check_defeats_with_the_invocation_and_diff_in_the_residual() {
    let verdict = decide(
        &receipts(
            vec![
                ("build", StepOutcome::Pass, ""),
                (
                    "differential:D1",
                    StepOutcome::Fail,
                    "exit status: reference 0, candidate 1\n< a | b\n",
                ),
            ],
            true,
        ),
        None,
        &policy(),
    );
    let Verdict::Defeat { residual } = verdict else {
        panic!("expected a defeat, got {verdict:?}");
    };
    assert!(residual.contains("--delimiter"), "{residual}");
    assert!(residual.contains("exit status: reference 0, candidate 1"), "{residual}");
    assert!(residual.len() <= EXECUTOR_TEXT_CAP + 64, "{}", residual.len());
}

#[test]
fn a_failed_build_defeats_even_if_the_review_would_support() {
    let review = Ok(ReviewVerdict::Support { coverage: vec![] });
    let verdict = decide(
        &receipts(vec![("build", StepOutcome::Fail, "error: no compile.sh")], true),
        Some(&review),
        &policy(),
    );
    assert!(matches!(verdict, Verdict::Defeat { .. }));
}

#[test]
fn passing_checks_need_a_supporting_review() {
    let support = Ok(ReviewVerdict::Support {
        coverage: vec![Coverage {
            requirement_id: "R1".to_string(),
            evidence: "D1".to_string(),
        }],
    });
    assert_eq!(decide(&passing(), Some(&support), &policy()), Verdict::Support);
    assert!(matches!(
        decide(&passing(), None, &policy()),
        Verdict::NotVerified { .. }
    ));
    let failed = Err(WorkerError::TimedOut);
    assert!(matches!(
        decide(&passing(), Some(&failed), &policy()),
        Verdict::NotVerified { .. }
    ));
}

#[test]
fn a_review_defeat_carries_its_findings_and_a_terms_gap_is_not_verified() {
    let defeat = Ok(ReviewVerdict::Defeat {
        findings: vec![Finding {
            requirement_id: "R2".to_string(),
            location: "src/main.rs".to_string(),
            counterexample: "--help omits the -p option".to_string(),
        }],
        residual: "document -p in --help".to_string(),
    });
    let Verdict::Defeat { residual } = decide(&passing(), Some(&defeat), &policy()) else {
        panic!("expected a defeat");
    };
    assert!(residual.contains("R2") && residual.contains("-p"), "{residual}");
    let gap = Ok(ReviewVerdict::TermsGap {
        gaps: vec![TermsGap {
            element: "error messages".to_string(),
            reason: "not covered".to_string(),
        }],
    });
    let Verdict::NotVerified { reason } = decide(&passing(), Some(&gap), &policy()) else {
        panic!("expected not verified");
    };
    assert!(reason.contains("termsGap") && reason.contains("error messages"), "{reason}");
}

fn terms() -> Terms {
    Terms {
        intake_text: "Implement it.".to_string(),
        requirements: vec![Requirement {
            id: "R1".to_string(),
            text: "Behaves like the reference.".to_string(),
            source_quote: "Implement it.".to_string(),
            inferred: false,
        }],
        out_of_scope: vec![],
    }
}

#[test]
fn the_brief_lists_requirements_and_identifies_its_contract() {
    let brief = brief_text("c-1", 2, &terms());
    assert!(brief.contains("R1: Behaves like the reference."), "{brief}");
    assert!(is_current_brief(&brief, "c-1", 2));
    assert!(!is_current_brief(&brief, "c-1", 3));
    assert!(!is_current_brief(&brief, "c-2", 2));
}

#[test]
fn the_brief_is_bounded() {
    let mut terms = terms();
    terms.requirements = (0..200)
        .map(|index| Requirement {
            id: format!("R{index}"),
            text: "x".repeat(100),
            source_quote: "Implement it.".to_string(),
            inferred: false,
        })
        .collect();
    let brief = brief_text("c-1", 1, &terms);
    assert!(brief.len() <= EXECUTOR_TEXT_CAP + 64, "{}", brief.len());
    assert!(is_current_brief(&brief, "c-1", 1));
}
