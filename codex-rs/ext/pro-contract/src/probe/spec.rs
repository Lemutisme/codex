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
        "Run 1-12 bounded stateless, non-interactive cases in one Contract action using normalized workspace-relative executable paths without './'. mode defaults to compare, which requires candidate and runs both reference and candidate with the same arguments, environment, sandbox, and limits. mode=observe forbids candidate and records reference behavior before an implementation exists. Every process is terminated, the full bounded report is content-addressed, and observed request hashes enter the same attempt frontier later comparisons use. Model output returns at most four compact case previews and reports the omitted count. Changed workspace state is not captured, and neither request novelty nor byte equality establishes semantic conformance, coverage, or settlement. case_timeout_ms is 100..60000; batch_timeout_ms is 1000..120000 and must cover cases * case_timeout_ms for observe or 2 * cases * case_timeout_ms for compare.",
        BTreeMap::from([
            ("mode".to_string(), JsonSchema::string(None)),
            ("reference".to_string(), JsonSchema::string(None)),
            ("candidate".to_string(), JsonSchema::string(None)),
            (
                "cases".to_string(),
                JsonSchema::array(case, Some("One to twelve cases.".to_string())),
            ),
            ("case_timeout_ms".to_string(), JsonSchema::integer(None)),
            ("batch_timeout_ms".to_string(), JsonSchema::integer(None)),
        ]),
        vec!["reference", "cases", "case_timeout_ms", "batch_timeout_ms"],
    )
}
