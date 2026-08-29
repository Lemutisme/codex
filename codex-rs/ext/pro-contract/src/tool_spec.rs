use crate::tool::PROPOSE_REVISION_TOOL_NAME;
use crate::tool::PROPOSE_TOOL_NAME;
use crate::tool::REPORT_BLOCKED_TOOL_NAME;
use crate::tool::REPORT_READY_TOOL_NAME;
use crate::tool::STATUS_TOOL_NAME;
use codex_tools::JsonSchema;
use codex_tools::ResponsesApiTool;
use codex_tools::ToolSpec;
use std::collections::BTreeMap;

pub(crate) fn propose_spec() -> ToolSpec {
    let trigger = JsonSchema::object(
        BTreeMap::from([
            (
                "type".to_string(),
                JsonSchema::string(Some("immediate or time".to_string())),
            ),
            (
                "at".to_string(),
                JsonSchema::integer(Some(
                    "Absolute Unix time in milliseconds; required for a time trigger.".to_string(),
                )),
            ),
        ]),
        Some(vec!["type".to_string()]),
        Some(false.into()),
    );
    let requirement = JsonSchema::object(
        BTreeMap::from([
            ("contract_id".to_string(), JsonSchema::string(None)),
            ("revision".to_string(), JsonSchema::integer(None)),
        ]),
        Some(vec!["contract_id".to_string(), "revision".to_string()]),
        Some(false.into()),
    );
    let budget = JsonSchema::object(
        BTreeMap::from([
            ("turns".to_string(), JsonSchema::integer(None)),
            ("actions".to_string(), JsonSchema::integer(None)),
            (
                "deadline".to_string(),
                JsonSchema::integer(Some("Absolute Unix time in milliseconds.".to_string())),
            ),
        ]),
        Some(vec![
            "turns".to_string(),
            "actions".to_string(),
            "deadline".to_string(),
        ]),
        Some(false.into()),
    );
    let resolution = JsonSchema::object(
        BTreeMap::from([
            ("max_attempts".to_string(), JsonSchema::integer(None)),
            ("retry_delay_ms".to_string(), JsonSchema::integer(None)),
        ]),
        Some(vec![
            "max_attempts".to_string(),
            "retry_delay_ms".to_string(),
        ]),
        Some(false.into()),
    );
    let properties = BTreeMap::from([
        ("trigger".to_string(), trigger),
        (
            "goal".to_string(),
            JsonSchema::string(Some(
                "Executor objective; defaults to the settlement claim.".to_string(),
            )),
        ),
        ("claim".to_string(), JsonSchema::string(None)),
        (
            "brief".to_string(),
            JsonSchema::string(Some("Self-contained executor task.".to_string())),
        ),
        (
            "artifacts".to_string(),
            JsonSchema::array(
                JsonSchema::string(None),
                Some("Complete relative delivery paths to freeze at handoff.".to_string()),
            ),
        ),
        (
            "execution_policy".to_string(),
            JsonSchema::string(Some(
                "Optional executor guidance selected outside the Contract. It does not alter Contract identity, revision, evidence, or settlement. Do not invent it."
                    .to_string(),
            )),
        ),
        ("replay".to_string(), replay_schema()),
        (
            "completion".to_string(),
            JsonSchema::string(Some(
                "Use terminal to keep a one-shot host alive until verification or escalation; defaults to admission."
                    .to_string(),
            )),
        ),
        ("budget".to_string(), budget),
        ("resolution".to_string(), resolution),
        (
            "requires".to_string(),
            JsonSchema::array(
                requirement,
                Some("Exact discharged prerequisite revisions.".to_string()),
            ),
        ),
        (
            "authority".to_string(),
            JsonSchema::array(
                JsonSchema::string(None),
                Some("Delegated capability identifiers for the executor.".to_string()),
            ),
        ),
    ]);
    function_tool(
        PROPOSE_TOOL_NAME,
        "Propose one durable completion contract and bind optional independently selected execution guidance. The trusted compiler preserves the current user request, rejects invented artifact paths and adapter-unknown authority, then runs the Contract in a dedicated executor session. Policy remains outside Contract identity and cannot settle responsibility.",
        properties,
        vec!["claim", "artifacts"],
    )
}

pub(crate) fn status_spec() -> ToolSpec {
    function_tool(
        STATUS_TOOL_NAME,
        "Read the current durable contract, execution binding, and quiet status.",
        BTreeMap::from([(
            "contract_id".to_string(),
            JsonSchema::string(Some(
                "Contract returned by contract_propose; omit inside its executor thread."
                    .to_string(),
            )),
        )]),
        Vec::new(),
    )
}

pub(crate) fn report_ready_spec() -> ToolSpec {
    function_tool(
        REPORT_READY_TOOL_NAME,
        "Freeze the exact subject, run its configured replay, and petition independent verification. This never discharges the Contract.",
        BTreeMap::from([
            ("summary".to_string(), JsonSchema::string(None)),
            (
                "uncertainties".to_string(),
                JsonSchema::array(JsonSchema::string(None), None),
            ),
            (
                "environment_id".to_string(),
                JsonSchema::string(Some(
                    "Required only when more than one execution environment is active.".to_string(),
                )),
            ),
        ]),
        vec!["summary"],
    )
}

pub(crate) fn report_blocked_spec() -> ToolSpec {
    function_tool(
        REPORT_BLOCKED_TOOL_NAME,
        "Record a concrete blocker without settling or discarding the Contract.",
        BTreeMap::from([("reason".to_string(), JsonSchema::string(None))]),
        vec!["reason"],
    )
}

pub(crate) fn propose_revision_spec() -> ToolSpec {
    function_tool(
        PROPOSE_REVISION_TOOL_NAME,
        "Petition the Principal for a new Contract revision. Execution policy is not revisable here.",
        BTreeMap::from([
            ("reason".to_string(), JsonSchema::string(None)),
            ("goal".to_string(), JsonSchema::string(None)),
            ("brief".to_string(), JsonSchema::string(None)),
            (
                "artifacts".to_string(),
                JsonSchema::array(JsonSchema::string(None), None),
            ),
            ("replay".to_string(), replay_schema()),
        ]),
        vec!["reason"],
    )
}

fn replay_schema() -> JsonSchema {
    let replay_check = JsonSchema::object(
        BTreeMap::from([
            (
                "argv".to_string(),
                JsonSchema::array(JsonSchema::string(None), None),
            ),
            ("cwd".to_string(), JsonSchema::string(None)),
            (
                "timeout_ms".to_string(),
                JsonSchema::integer(Some(
                    "Timeout from 1000 to 600000 milliseconds.".to_string(),
                )),
            ),
            ("exit".to_string(), JsonSchema::integer(None)),
        ]),
        Some(vec![
            "argv".to_string(),
            "timeout_ms".to_string(),
            "exit".to_string(),
        ]),
        Some(false.into()),
    );
    let protected_file = JsonSchema::object(
        BTreeMap::from([
            ("path".to_string(), JsonSchema::string(None)),
            ("sha256".to_string(), JsonSchema::string(None)),
        ]),
        Some(vec!["path".to_string(), "sha256".to_string()]),
        Some(false.into()),
    );
    JsonSchema::object(
        BTreeMap::from([
            ("checks".to_string(), JsonSchema::array(replay_check, None)),
            (
                "protected".to_string(),
                JsonSchema::array(protected_file, None),
            ),
        ]),
        Some(vec!["checks".to_string()]),
        Some(false.into()),
    )
}

fn function_tool(
    name: &str,
    description: &str,
    properties: BTreeMap<String, JsonSchema>,
    required: Vec<&str>,
) -> ToolSpec {
    ToolSpec::Function(ResponsesApiTool {
        name: name.to_string(),
        description: description.to_string(),
        strict: false,
        defer_loading: None,
        parameters: JsonSchema::object(
            properties,
            Some(required.into_iter().map(str::to_string).collect()),
            Some(false.into()),
        ),
        output_schema: None,
    })
}
