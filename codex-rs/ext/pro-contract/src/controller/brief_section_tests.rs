use codex_extension_api::PreviousWorldStateSection;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::brief_section;
use super::repair_fragment;
use super::runtime::BriefView;

fn brief(revision: u32) -> BriefView {
    BriefView {
        contract_id: "thread.1".to_string(),
        revision,
        text: format!("ProContract thread.1 revision {revision}\nR1: answer.txt says done\n"),
    }
}

#[test]
fn the_brief_renders_once_per_contract_revision() {
    let section = brief_section(brief(1));
    let same = json!({ "contract": "thread.1", "revision": 1 });
    let older = json!({ "contract": "thread.1", "revision": 0 });

    let (snapshot, rendered) = section.render_diff(PreviousWorldStateSection::Absent);
    let rendered = rendered.expect("first render");
    assert_eq!(snapshot, Some(same.clone()));
    assert_eq!(
        (rendered.role(), rendered.markers(), rendered.body()),
        (
            "developer",
            ("<pro_contract>", "</pro_contract>"),
            brief(1).text.as_str()
        )
    );
    assert_eq!(
        section.render_diff(PreviousWorldStateSection::Known(&same)),
        (Some(same.clone()), None)
    );
    assert_eq!(
        section.render_diff(PreviousWorldStateSection::Unknown),
        (Some(same.clone()), None)
    );
    let (snapshot, rendered) = section.render_diff(PreviousWorldStateSection::Known(&older));
    assert_eq!(snapshot, Some(same));
    assert!(rendered.is_some());
}

/// The text core records in history: the body wrapped in the section's markers.
fn in_history(revision: u32) -> String {
    let rendered = brief_section(brief(revision))
        .render_diff(PreviousWorldStateSection::Absent)
        .1
        .expect("render");
    let (open, close) = rendered.markers();
    format!("{open}{}{close}", rendered.body())
}

#[test]
fn only_the_current_revision_in_history_is_retained() {
    let section = brief_section(brief(2));

    assert!(section.matches_retained_fragment("developer", &in_history(2)));
    assert!(!section.matches_retained_fragment("developer", &in_history(1)));
    assert!(!section.matches_retained_fragment("user", &in_history(2)));
    assert!(!section.matches_retained_fragment("developer", &brief(2).text));
}

#[test]
fn the_outstanding_repair_note_is_stated_again_as_developer_context() {
    let fragment = repair_fragment("Fix these:\n- public:D1 failed\n");

    assert_eq!(
        fragment.text(),
        "<pro_contract_repair>\nFix these:\n- public:D1 failed\n</pro_contract_repair>"
    );
    assert_eq!(fragment.content_kind().0, "pro_contract.repair_note");
}
