use codex_extension_api::PreviousWorldStateSection;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::brief_section;
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

    let rendered = section
        .render_diff(PreviousWorldStateSection::Absent)
        .expect("first render");
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
        None
    );
    assert!(
        section
            .render_diff(PreviousWorldStateSection::Known(&older))
            .is_some()
    );
}

/// The text core records in history: the body wrapped in the section's markers.
fn in_history(revision: u32) -> String {
    let rendered = brief_section(brief(revision))
        .render_diff(PreviousWorldStateSection::Absent)
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
