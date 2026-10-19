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
use super::review_verdict;
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
        sealed_threshold_permille: Some(750),
        min_sealed_qualified: Some(4),
        min_success_permille: Some(500),
        preparation_failure: None,
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
        execution: None,
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

#[test]
fn undeclared_numeric_cutoffs_are_measurements_not_automatic_acceptance() {
    let policy = EvidencePolicy {
        min_sealed_qualified: None,
        min_success_permille: None,
        sealed_threshold_permille: None,
        ..policy()
    };
    let observations = with_sealed(&[StepOutcome::Unqualified; 4]);
    assert!(mechanical_verdict(&observations, &policy).is_none());
    assert!(matches!(
        decide(&observations, None, &policy),
        Verdict::NotVerified {
            class: NotVerifiedClass::ReviewerUnable,
            ..
        }
    ));
    assert!(review_summary(observations.as_ref().unwrap(), &policy).contains("unqualified"));
}

#[test]
fn reviewer_receives_actual_command_and_success_output_without_sealed_details() {
    let mut policy = policy();
    policy.build_command = Some("python3 -m unittest -v tests".into());
    let receipts = receipts(
        vec![
            step("build", StepOutcome::Pass, "Ran 10 tests; OK"),
            step("sealed:S0", StepOutcome::Pass, SEALED_SECRET),
        ],
        true,
    )
    .unwrap();
    let summary = review_summary(&receipts, &policy);
    assert!(summary.contains("python3 -m unittest -v tests"));
    assert!(summary.contains("Ran 10 tests; OK"));
    assert!(!summary.contains(SEALED_SECRET));
}

fn support() -> Result<Review, WorkerError> {
    Ok(Review {
        observations: vec![],
        execution_obligations: vec![],
        verdict: ReviewVerdict::Support {
            coverage: vec![Coverage {
                requirement_id: "R1".to_string(),
                evidence: "D1".to_string(),
            }],
        },
        terms_gap: vec![],
    })
}

#[test]
fn a_past_execution_violation_blocks_support_without_discarding_the_artifact() {
    let review = Review {
        observations: vec![],
        execution_obligations: vec!["process:0".into()],
        terms_gap: vec![],
        verdict: ReviewVerdict::Defeat {
            findings: vec![Finding {
                requirement_id: "process:0".into(),
                location: "execution".into(),
                counterexample: "initial publication occurred after modification".into(),
            }],
            residual: "rewrite the file".into(),
        },
    };
    assert!(matches!(
        review_verdict(Some(&Ok(review))),
        Verdict::NotVerified {
            class: NotVerifiedClass::ExecutionConstraint,
            ..
        }
    ));
}

#[test]
fn candidate_build_blockage_allows_repair_but_does_not_claim_qualified_evidence() {
    let mut checks = with_sealed(&[StepOutcome::Blocked; 4]);
    let receipts = checks.as_mut().unwrap();
    receipts.steps[0].outcome = StepOutcome::Fail;
    receipts.steps[1].outcome = StepOutcome::Blocked;
    for receipt in &mut receipts.steps {
        receipt.reference_exit = None;
    }
    let tally = super::sealed_tally(receipts, &policy());
    assert_eq!((tally.qualified, tally.blocked), (0, 4));
    assert!(matches!(
        decide(&checks, None, &policy()),
        Verdict::Defeat {
            blocker: Some(_),
            ..
        }
    ));

    // Repairing the build cannot recover observations already known to be independently
    // unqualified: even the optimistic candidate repair falls below this frozen minimum.
    checks.as_mut().unwrap().steps[2].outcome = StepOutcome::Unqualified;
    assert!(matches!(
        decide(&checks, None, &policy()),
        Verdict::Defeat {
            blocker: Some(_),
            ..
        }
    ));
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
fn an_interrupted_batch_keeps_its_completed_public_counterexample_actionable() {
    let checks = receipts(
        vec![step("public:D1", StepOutcome::Fail, "actual difference")],
        false,
    );
    assert!(matches!(
        decide(&checks, Some(&support()), &policy()),
        Verdict::Defeat {
            blocker: Some(_),
            ..
        }
    ));
    let checks = receipts(vec![step("public:D1", StepOutcome::Pass, "")], false);
    assert!(matches!(
        decide(&checks, Some(&support()), &policy()),
        Verdict::NotVerified { .. }
    ));
}

#[test]
fn legacy_failure_requires_the_original_complete_batch_before_authorizing_repair() {
    let legacy: StepReceipt = serde_json::from_value(serde_json::json!({
        "step":"public:D1", "outcome":"fail", "detail":"old receipt without individual completion"
    }))
    .unwrap();
    assert!(!legacy.complete);
    assert!(matches!(
        decide(&receipts(vec![legacy.clone()], false), None, &policy()),
        Verdict::NotVerified {
            class: NotVerifiedClass::Infrastructure,
            ..
        }
    ));
    assert!(matches!(
        decide(&receipts(vec![legacy], true), None, &policy()),
        Verdict::Defeat { .. }
    ));
}

#[test]
fn independent_review_gap_does_not_discard_an_actionable_finding() {
    let review = crate::workers::reviewer::Review {
        observations: vec![],
        execution_obligations: vec![],
        terms_gap: vec![],
        verdict: ReviewVerdict::Partial {
            coverage: vec![],
            findings: vec![crate::workers::reviewer::Finding {
                requirement_id: "R1".into(),
                location: "lemma".into(),
                counterexample: "d=2".into(),
            }],
            missing: vec![crate::workers::reviewer::MissingEvidence {
                requirement_id: "R2".into(),
                reason: "unread numeric attachment".into(),
            }],
            unscoped_missing: String::new(),
        },
    };
    let verdict = super::review_verdict(Some(&Ok(review)));
    assert!(matches!(
        verdict,
        Verdict::Defeat {
            blocker: Some(_),
            ..
        }
    ));
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
    let Verdict::Defeat { residual, .. } = decide(&checks, None, &policy()) else {
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
    let Verdict::Defeat { residual, .. } =
        decide(&receipts(steps, true), Some(&support()), &policy())
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
fn verbose_repeated_symptoms_do_not_hide_other_failed_modes() {
    let mut steps = (0..5)
        .map(|i| {
            step(
                &format!("public:format-{i}"),
                StepOutcome::Fail,
                &"same output diff ".repeat(50),
            )
        })
        .collect::<Vec<_>>();
    steps.push(step("public:parallel", StepOutcome::Fail, "empty output"));
    steps.push(step("public:stdin", StepOutcome::Fail, "wrong mode"));
    let Verdict::Defeat { residual, .. } = decide(&receipts(steps, true), None, &policy()) else {
        panic!("defeat");
    };
    assert!(residual.contains("public:parallel"), "{residual}");
    assert!(residual.contains("public:stdin"), "{residual}");
    assert!(residual.contains("not the whole repair scope"));
    assert!(residual.len() <= EXECUTOR_TEXT_CAP);
    assert!(!residual.contains(SEALED_SECRET));
}

#[test]
fn a_failed_build_defeats_without_a_sealed_line_even_if_the_review_would_support() {
    let mut steps = vec![step("build", StepOutcome::Fail, "error: no compile.sh")];
    steps.push(StepReceipt::new("public:D1", StepOutcome::Fail, ""));
    steps.extend(
        (0..4).map(|index| StepReceipt::new(format!("sealed:S{index}"), StepOutcome::Fail, "")),
    );
    let Verdict::Defeat { residual, .. } =
        decide(&receipts(steps, true), Some(&support()), &policy())
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
    let Verdict::Defeat { residual, .. } = verdict else {
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
        min_sealed_qualified: Some(3),
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
        observations: vec![],
        execution_obligations: vec![],
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
        observations: vec![],
        execution_obligations: vec![],
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
    let Verdict::Defeat { residual, .. } = decide(&passing(), Some(&defeat), &policy()) else {
        panic!("expected a defeat");
    };
    assert!(
        residual.contains("R2") && residual.contains("-p"),
        "{residual}"
    );
    let gap = Ok(Review {
        observations: vec![],
        execution_obligations: vec![],
        terms_gap: vec![TermsGap {
            affected_requirements: None,
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
fn a_scope_dispute_blocks_acceptance_without_blocking_an_unaffected_repair() {
    let review = Review {
        observations: vec![],
        execution_obligations: vec![],
        verdict: ReviewVerdict::Defeat {
            findings: vec![Finding {
                requirement_id: "R1".into(),
                location: "parser.py".into(),
                counterexample: "malformed JSON escapes the required error type".into(),
            }],
            residual: "invent unrequested scope".into(),
        },
        terms_gap: vec![TermsGap {
            element: "unrequested extra work".into(),
            reason: "widened".into(),
            affected_requirements: Some(vec!["R2".into()]),
        }],
    };
    let Verdict::Defeat {
        residual,
        blocker: Some(blocker),
    } = review_verdict(Some(&Ok(review.clone())))
    else {
        panic!("scoped repair");
    };
    assert_eq!(blocker.class, NotVerifiedClass::TermsGap);
    assert!(residual.contains("R1") && !residual.contains("invent unrequested"));
    let unscoped = Review {
        observations: vec![],
        execution_obligations: vec![],
        terms_gap: vec![TermsGap {
            affected_requirements: None,
            ..review.terms_gap[0].clone()
        }],
        ..review
    };
    assert!(matches!(
        review_verdict(Some(&Ok(unscoped))),
        Verdict::NotVerified {
            class: NotVerifiedClass::TermsGap,
            ..
        }
    ));
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
