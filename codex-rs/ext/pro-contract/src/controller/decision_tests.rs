use codex_pro_contract::Digest;
use pretty_assertions::assert_eq;

use super::EXECUTOR_TEXT_CAP;
use super::NotVerifiedClass;
use super::Verdict;
use super::brief_text;
use super::decide;
use super::is_current_brief;
use super::mechanical_verdict;
use super::review_summary;
use crate::CheckError;
use crate::CheckReceipts;
use crate::DifferentialCase;
use crate::EvidenceClass;
use crate::EvidencePolicy;
use crate::FixtureFile;
use crate::ProcessConstraint;
use crate::Requirement;
use crate::StepOutcome;
use crate::StepReceipt;
use crate::Terms;
use crate::WorkerError;
use crate::workers::reviewer::Coverage;
use crate::workers::reviewer::Finding;
use crate::workers::reviewer::Review;
use crate::workers::reviewer::ReviewVerdict;
use crate::workers::reviewer::TermsGap;

const SEALED_SECRET: &str = "--sealed-secret-flag";

fn sealed_case(index: usize) -> DifferentialCase {
    DifferentialCase {
        id: format!("S{index}"),
        args: vec![SEALED_SECRET.to_string(), index.to_string()],
        family: if index.is_multiple_of(2) {
            "sizes"
        } else {
            "errors"
        }
        .to_string(),
        ..Default::default()
    }
}

/// Four sealed cases; support needs all four qualified and at least three passing.
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
            files: vec![FixtureFile {
                path: "data.csv".to_string(),
                text: "a;b\n".to_string(),
                repeat: 1,
            }],
            ..Default::default()
        }],
        reference_command: Some("/workspace/executable".to_string()),
        sealed: (0..4).map(sealed_case).collect(),
        sealed_threshold_permille: 750,
        min_sealed_qualified: 4,
        min_success_permille: 500,
    }
}

fn step(name: &str, outcome: StepOutcome, detail: &str) -> StepReceipt {
    StepReceipt {
        reference_exit: name.contains(':').then_some(0),
        ..StepReceipt::new(name, outcome, detail)
    }
}

fn receipts(steps: Vec<StepReceipt>, complete: bool) -> Result<CheckReceipts, CheckError> {
    Ok(CheckReceipts {
        steps,
        environment: vec![],
        complete,
        environment_digest: Digest::of(b"env"),
        evaluator_digest: Digest::of(b"eval"),
    })
}

/// Build and the public case pass; the sealed cases have the given outcomes.
fn with_sealed(outcomes: &[StepOutcome]) -> Result<CheckReceipts, CheckError> {
    let mut steps = vec![
        step("build", StepOutcome::Pass, ""),
        step("public:D1", StepOutcome::Pass, ""),
    ];
    steps.extend(
        outcomes
            .iter()
            .enumerate()
            .map(|(index, outcome)| step(&format!("sealed:S{index}"), *outcome, "")),
    );
    receipts(steps, true)
}

fn passing() -> Result<CheckReceipts, CheckError> {
    with_sealed(&[StepOutcome::Pass; 4])
}

fn support() -> Result<Review, WorkerError> {
    Ok(Review {
        verdict: ReviewVerdict::Support {
            coverage: vec![Coverage {
                requirement_id: "R1".to_string(),
                evidence: "D1".to_string(),
            }],
        },
        terms_gap: vec![],
    })
}

fn class(verdict: &Verdict) -> Option<NotVerifiedClass> {
    match verdict {
        Verdict::NotVerified { class, .. } => Some(*class),
        _ => None,
    }
}

#[test]
fn checks_that_could_not_run_or_stopped_early_are_infrastructure() {
    let verdict = decide(&Err(CheckError::TimedOut), Some(&support()), &policy());
    assert_eq!(class(&verdict), Some(NotVerifiedClass::Infrastructure));
    let verdict = decide(
        &receipts(vec![step("build", StepOutcome::Pass, "")], false),
        Some(&support()),
        &policy(),
    );
    assert_eq!(class(&verdict), Some(NotVerifiedClass::Infrastructure));
}

#[test]
fn a_failed_public_case_defeats_with_its_invocation_and_diff() {
    let checks = receipts(
        vec![
            step("build", StepOutcome::Pass, ""),
            step(
                "public:D1",
                StepOutcome::Fail,
                "differing channels: rc\nexit status: reference 0, candidate 1\n",
            ),
        ],
        true,
    );
    let Verdict::Defeat { residual } = decide(&checks, None, &policy()) else {
        panic!("expected a defeat");
    };
    assert!(residual.contains("--delimiter"), "{residual}");
    assert!(residual.contains("over fixtures data.csv"), "{residual}");
    assert!(
        residual.contains("exit status: reference 0, candidate 1"),
        "{residual}"
    );
    assert!(
        residual.len() <= EXECUTOR_TEXT_CAP + 64,
        "{}",
        residual.len()
    );
}

#[test]
fn long_public_failures_do_not_push_out_the_sealed_line() {
    let long = format!("{}\nlast line", "x".repeat(900));
    let mut steps = vec![step("build", StepOutcome::Pass, "")];
    steps.extend((0..6).map(|_| step("public:D1", StepOutcome::Fail, &long)));
    steps.extend(
        [
            StepOutcome::Pass,
            StepOutcome::Fail,
            StepOutcome::Fail,
            StepOutcome::Pass,
        ]
        .iter()
        .enumerate()
        .map(|(index, outcome)| step(&format!("sealed:S{index}"), *outcome, "")),
    );
    let Verdict::Defeat { residual } = decide(&receipts(steps, true), Some(&support()), &policy())
    else {
        panic!("expected a defeat");
    };
    let sealed_line = "- 2 of 4 independent sealed checks did not match the reference, in these behavior families: errors, sizes. Their invocations are not disclosed; re-check the documented behavior in these areas.\n";
    let header_end = residual.find('\n').unwrap() + 1;
    assert!(
        residual[header_end..].starts_with(sealed_line),
        "{residual}"
    );
    assert!(residual.contains("--delimiter"), "{residual}");
    assert!(
        residual.contains("more failed checks omitted"),
        "{residual}"
    );
    assert!(!residual.contains("bytes omitted ...]\n[..."), "{residual}");
    assert!(residual.len() <= EXECUTOR_TEXT_CAP, "{}", residual.len());
    assert!(!residual.contains(SEALED_SECRET), "{residual}");
}

#[test]
fn a_failed_build_defeats_without_a_sealed_line_even_if_the_review_would_support() {
    let mut steps = vec![step("build", StepOutcome::Fail, "error: no compile.sh")];
    steps.push(StepReceipt::new("public:D1", StepOutcome::Fail, ""));
    steps.extend(
        (0..4).map(|index| StepReceipt::new(format!("sealed:S{index}"), StepOutcome::Fail, "")),
    );
    let Verdict::Defeat { residual } = decide(&receipts(steps, true), Some(&support()), &policy())
    else {
        panic!("expected a defeat");
    };
    assert!(residual.contains("error: no compile.sh"), "{residual}");
    assert!(!residual.contains("sealed checks"), "{residual}");
}

#[test]
fn too_few_qualified_sealed_cases_are_insufficient_evidence() {
    let verdict = decide(
        &with_sealed(&[
            StepOutcome::Pass,
            StepOutcome::Pass,
            StepOutcome::Pass,
            StepOutcome::Unqualified,
        ]),
        Some(&support()),
        &policy(),
    );
    assert_eq!(
        class(&verdict),
        Some(NotVerifiedClass::InsufficientEvidence)
    );
    let empty = EvidencePolicy {
        sealed: vec![],
        ..policy()
    };
    let verdict = decide(&with_sealed(&[]), Some(&support()), &empty);
    assert_eq!(
        class(&verdict),
        Some(NotVerifiedClass::InsufficientEvidence)
    );
}

#[test]
fn sealed_cases_that_mostly_exercise_failures_are_insufficient_evidence() {
    let Ok(mut checks) = passing() else {
        unreachable!()
    };
    for step in checks
        .steps
        .iter_mut()
        .filter(|step| step.step.starts_with("sealed:"))
        .take(3)
    {
        step.reference_exit = Some(2);
    }
    let Verdict::NotVerified { class, reason } = decide(&Ok(checks), Some(&support()), &policy())
    else {
        panic!("expected not verified");
    };
    assert_eq!(class, NotVerifiedClass::InsufficientEvidence);
    assert!(
        reason.contains("1 with a successful reference run"),
        "{reason}"
    );
}

#[test]
fn a_sealed_pass_rate_below_threshold_defeats_with_aggregates_only() {
    let verdict = decide(
        &with_sealed(&[
            StepOutcome::Pass,
            StepOutcome::Fail,
            StepOutcome::Fail,
            StepOutcome::Pass,
        ]),
        Some(&support()),
        &policy(),
    );
    let Verdict::Defeat { residual } = verdict else {
        panic!("expected a defeat, got {verdict:?}");
    };
    assert!(
        residual.contains("2 of 4 independent sealed checks"),
        "{residual}"
    );
    assert!(residual.contains("errors, sizes"), "{residual}");
    assert!(!residual.contains(SEALED_SECRET), "{residual}");
}

#[test]
fn unqualified_sealed_cases_leave_the_denominator() {
    let policy = EvidencePolicy {
        min_sealed_qualified: 3,
        ..policy()
    };
    let checks = with_sealed(&[
        StepOutcome::Pass,
        StepOutcome::Pass,
        StepOutcome::Pass,
        StepOutcome::Unqualified,
    ]);
    assert_eq!(mechanical_verdict(&checks, &policy), None);
    assert_eq!(decide(&checks, Some(&support()), &policy), Verdict::Support);
}

#[test]
fn passing_checks_leave_the_decision_to_the_review() {
    assert_eq!(mechanical_verdict(&passing(), &policy()), None);
    assert_eq!(
        decide(&passing(), Some(&support()), &policy()),
        Verdict::Support
    );
    assert_eq!(
        class(&decide(&passing(), None, &policy())),
        Some(NotVerifiedClass::ReviewerUnable)
    );
    let failed = Err(WorkerError::TimedOut);
    assert_eq!(
        class(&decide(&passing(), Some(&failed), &policy())),
        Some(NotVerifiedClass::ReviewerUnable)
    );
    let cannot = Ok(Review {
        verdict: ReviewVerdict::CannotJudge {
            missing: "the output".to_string(),
        },
        terms_gap: vec![],
    });
    assert_eq!(
        class(&decide(&passing(), Some(&cannot), &policy())),
        Some(NotVerifiedClass::ReviewerUnable)
    );
}

#[test]
fn without_a_reference_the_sealed_rules_do_not_apply() {
    let policy = EvidencePolicy {
        reference_command: None,
        differential: vec![],
        sealed: vec![],
        ..policy()
    };
    let checks = receipts(vec![step("build", StepOutcome::Pass, "")], true);
    assert_eq!(decide(&checks, Some(&support()), &policy), Verdict::Support);
}

#[test]
fn a_review_defeat_carries_its_findings_and_a_terms_gap_overrides_support() {
    let defeat = Ok(Review {
        verdict: ReviewVerdict::Defeat {
            findings: vec![Finding {
                requirement_id: "R2".to_string(),
                location: "src/main.rs".to_string(),
                counterexample: "--help omits the -p option".to_string(),
            }],
            residual: "document -p in --help".to_string(),
        },
        terms_gap: vec![],
    });
    let Verdict::Defeat { residual } = decide(&passing(), Some(&defeat), &policy()) else {
        panic!("expected a defeat");
    };
    assert!(
        residual.contains("R2") && residual.contains("-p"),
        "{residual}"
    );
    let gap = Ok(Review {
        terms_gap: vec![TermsGap {
            element: "error messages".to_string(),
            reason: "not covered".to_string(),
        }],
        ..support().expect("support")
    });
    let Verdict::NotVerified { class, reason } = decide(&passing(), Some(&gap), &policy()) else {
        panic!("expected not verified");
    };
    assert_eq!(class, NotVerifiedClass::TermsGap);
    assert!(
        reason.contains("termsGap") && reason.contains("error messages"),
        "{reason}"
    );
}

#[test]
fn the_reviewer_sees_sealed_checks_only_in_aggregate() {
    let Ok(checks) = with_sealed(&[
        StepOutcome::Pass,
        StepOutcome::Pass,
        StepOutcome::Pass,
        StepOutcome::Unqualified,
    ]) else {
        unreachable!()
    };
    let summary = review_summary(&checks, &policy());
    assert!(summary.contains("public:D1: Pass"), "{summary}");
    assert!(
        summary.contains(
            "sealed: 3 of 3 qualified sealed checks agree with the reference (1 unqualified)"
        ),
        "{summary}"
    );
    assert!(!summary.contains("sealed:S0"), "{summary}");
    assert!(!summary.contains(SEALED_SECRET), "{summary}");
}

fn terms() -> Terms {
    Terms {
        intake_text: "Implement it. Do not read the reference.".to_string(),
        requirements: vec![Requirement {
            id: "R1".to_string(),
            text: "Behaves like the reference.".to_string(),
            source_quote: "Implement it.".to_string(),
            inferred: false,
        }],
        out_of_scope: vec![],
        process_constraints: vec![ProcessConstraint {
            text: "Do not read the reference program.".to_string(),
            source_quote: "Do not read the reference.".to_string(),
        }],
    }
}

#[test]
fn the_brief_lists_constraints_and_requirements_and_identifies_its_contract() {
    let brief = brief_text("c-1", 2, &terms(), &policy());
    assert!(brief.contains("R1: Behaves like the reference."), "{brief}");
    assert!(
        brief.contains("Work constraints:\n- Do not read the reference program."),
        "{brief}"
    );
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
    let brief = brief_text("c-1", 1, &terms, &policy());
    assert!(brief.len() <= EXECUTOR_TEXT_CAP + 64, "{}", brief.len());
    assert!(is_current_brief(&brief, "c-1", 1));
    // How the handoff is checked survives the bound; the requirement list is what gets cut.
    assert!(brief.contains("compared with the reference"), "{brief}");
}

#[test]
fn the_brief_states_the_evidence_class_and_how_the_handoff_is_checked() {
    let brief = brief_text("c-1", 2, &terms(), &policy());
    assert!(brief.contains("Evidence: checks and review"), "{brief}");
    assert!(brief.contains("`./compile.sh`"), "{brief}");
    assert!(brief.contains("compared with the reference"), "{brief}");
    assert!(
        brief.contains("sealed set whose contents are never shown"),
        "{brief}"
    );
    assert!(!brief.contains("cargo test"), "{brief}");
    // No case list, no budgets.
    assert!(!brief.contains("--delimiter"), "{brief}");
    assert!(!brief.contains(SEALED_SECRET), "{brief}");

    let own_tests_only = EvidencePolicy {
        candidate_tests: true,
        reference_command: None,
        differential: Vec::new(),
        sealed: Vec::new(),
        ..policy()
    };
    let brief = brief_text("c-1", 2, &terms(), &own_tests_only);
    assert!(brief.contains("cargo test"), "{brief}");
    assert!(!brief.contains("compared with the reference"), "{brief}");

    let nothing_mechanical = EvidencePolicy {
        build_command: None,
        candidate_tests: false,
        reference_command: None,
        ..policy()
    };
    let brief = brief_text("c-1", 2, &terms(), &nothing_mechanical);
    assert!(
        brief.contains(
            "Evidence: checks and review. An independent reviewer checks each requirement."
        ),
        "{brief}"
    );
}
