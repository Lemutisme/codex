use super::PROBE_TOOL_NAME;
use crate::tool_spec::function_tool;
use codex_extension_api::ToolSpec;
use codex_tools::JsonSchema;
use std::collections::BTreeMap;

pub(super) fn probe_spec() -> ToolSpec {
    let case = JsonSchema::object(
        BTreeMap::from([
            ("id".to_string(), JsonSchema::string(None)),
            (
                "args".to_string(),
                JsonSchema::array(JsonSchema::string(None), None),
            ),
        ]),
        Some(vec!["id".to_string(), "args".to_string()]),
        Some(false.into()),
    );
    function_tool(
        PROBE_TOOL_NAME,
        "Run 1-12 bounded stateless, non-interactive candidate/reference cases in one Contract action using normalized workspace-relative executable paths without './'. The trusted local executor applies identical argv, environment, sandbox, and limits to both sides, terminates every process, persists a content-addressed full bounded report, and returns only compact mismatches. case_timeout_ms is 100..60000; batch_timeout_ms is 1000..120000 and must cover 2 * cases * case_timeout_ms. This is observation evidence, not settlement or proof of coverage.",
        BTreeMap::from([
            ("reference".to_string(), JsonSchema::string(None)),
            ("candidate".to_string(), JsonSchema::string(None)),
            (
                "cases".to_string(),
                JsonSchema::array(case, Some("One to twelve cases.".to_string())),
            ),
            ("case_timeout_ms".to_string(), JsonSchema::integer(None)),
            ("batch_timeout_ms".to_string(), JsonSchema::integer(None)),
        ]),
        vec![
            "reference",
            "candidate",
            "cases",
            "case_timeout_ms",
            "batch_timeout_ms",
        ],
    )
}
