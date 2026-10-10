use pretty_assertions::assert_eq;

use super::RequestSources;

#[test]
fn references_resolve_to_exact_request_bytes_not_workspace_content() {
    let request = "实现工具。\nDo not install dependencies.";
    let sources = RequestSources::new(request);
    assert_eq!(sources.resolve("request:0").unwrap(), "实现工具。\n");
    assert_eq!(
        sources.resolve("request:1").unwrap(),
        "Do not install dependencies."
    );
    for id in ["workspace:0", "request:2", "request:01", "request:-1"] {
        assert!(sources.resolve(id).is_err());
    }
}

#[test]
fn long_unicode_requests_are_chunked_without_changing_content() {
    let text = "说明".repeat(300);
    let sources = RequestSources::new(&text);
    let restored: String = (0..sources.spans.len())
        .map(|index| sources.resolve(&format!("request:{index}")).unwrap())
        .collect();
    assert_eq!(restored, text);
}

#[test]
fn incomplete_catalog_never_authorizes_partial_request_terms() {
    for text in ["a".repeat(20_000), "line\n".repeat(4_000)] {
        let sources = RequestSources::new(&text);
        assert!(sources.render().len() < 12_000);
        assert!(sources.resolve("request:0").is_err());
    }
}

#[test]
fn short_allowlist_lines_do_not_hide_the_task_requirements() {
    let request = format!(
        "Permitted tools:\n{}Implement from scratch in Rust; never reuse the reference.\n",
        "- tool: build and runtime only.\n".repeat(100)
    );
    let sources = RequestSources::new(&request);
    let restored: String = (0..sources.spans.len())
        .map(|index| sources.resolve(&format!("request:{index}")).unwrap())
        .collect();
    assert_eq!(restored, request);
}
