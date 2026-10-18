//! The case format the drafter's public cases and the prober's sealed cases share: its strict
//! output schema, its validation, and how reference observations are shown to a worker.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::WorkerError;
use super::bounded;
use super::bounded_head_tail;
use super::strict_object;
use crate::DifferentialCase;
use crate::FixtureFile;
use crate::Observation;
use crate::Terminal;
use crate::checks::safe_relative;

/// Largest stdin a case may carry.
pub(crate) const MAX_STDIN_BYTES: usize = 64 << 10;
/// Largest total size of a case's fixture files, after repetition.
pub(crate) const MAX_FIXTURE_BYTES: usize = 256 << 10;
const MAX_FIXTURE_ENTRIES: usize = 32;
const MAX_ARGS: usize = 64;
const MAX_ENV: usize = 16;
const MAX_ENV_VALUE_BYTES: usize = 1024;
const MAX_FAMILY_BYTES: usize = 64;
pub(crate) const OBSERVATION_FORMAT: &str = "paired-normalized-invocation-and-reference-output-v2";

/// The instructions every case-writing worker shares.
pub(crate) const CASE_RULES: &str = "Each case runs in a fresh copy of the base workspace (so relative paths to its \
documentation and assets resolve), with the case's own files and empty directories added on top, a fixed environment \
plus the case's env, and the case's stdin. Both programs run at the same path with the same arguments; their exit \
status, standard output, standard error and the files left in the case directory are compared. Give each case a plain \
id (letters, digits, '-', '_', '.'), a short family tag naming the behavior it exercises, args (the argument vector \
after the program name), stdin (text up to 64 KiB, or null), files (path relative to the case directory, text, and \
repeat: the content is text repeated that many times; at most 256 KiB per case), dirs (empty directories), and env \
(name/value pairs). Set terminal to null for ordinary pipe execution, or to {rows, cols, input, dialogue} \
for a controlling PTY with stdout and stderr merged into terminal output. With a PTY, null stdin attaches \
stdin to the terminal; text stdin supplies that text separately while terminal.input feeds /dev/tty. \
Choose TERM and dimensions from the documented interface. input is sent once at startup. dialogue is an \
ordered array of {expect, send}: wait for the literal expect bytes in terminal output, then send the reply. \
Each trigger is consumed once; all declared exchanges must complete for the invocation to qualify. \
Use an empty array when no dialogue is needed. At most 64 exchanges and 64 KiB total input. \
Calibrate a representative successful invocation before expanding variants. Never use the reference program itself as an input.";

pub(crate) fn case_schema() -> Value {
    strict_object(json!({
        "id": {"type": "string"},
        "family": {"type": "string"},
        "args": {"type": "array", "items": {"type": "string"}},
        "stdin": {"type": ["string", "null"]},
        "files": {"type": "array", "items": strict_object(json!({
            "path": {"type": "string"},
            "text": {"type": "string"},
            "repeat": {"type": "integer"},
        }))},
        "dirs": {"type": "array", "items": {"type": "string"}},
        "env": {"type": "array", "items": strict_object(json!({
            "name": {"type": "string"},
            "value": {"type": "string"},
        }))},
        "terminal": {"anyOf": [{"type": "null"}, strict_object(json!({
            "rows": {"type": "integer", "minimum": 1, "maximum": 500},
            "cols": {"type": "integer", "minimum": 1, "maximum": 1000},
            "input": {"type": "string"},
            "dialogue": {"type": "array", "maxItems":64, "items": strict_object(json!({
                "expect": {"type":"string", "minLength":1, "maxLength":1024},
                "send": {"type":"string"},
            }))},
        }))]},
    }))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RawCase {
    id: String,
    #[serde(default)]
    family: String,
    args: Vec<String>,
    #[serde(default)]
    stdin: Option<String>,
    #[serde(default)]
    files: Vec<FixtureFile>,
    #[serde(default)]
    dirs: Vec<String>,
    #[serde(default)]
    env: Vec<RawEnv>,
    #[serde(default)]
    terminal: Option<Terminal>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawEnv {
    name: String,
    value: String,
}

fn is_plain_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 40
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

/// A portable environment variable name; lowercase names such as `http_proxy` are common.
fn is_env_name(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|first| first.is_ascii_alphabetic() || first == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// Validates at most `max` raw cases into differential cases.
pub(crate) fn validate_cases(
    raw: Vec<RawCase>,
    max: usize,
) -> Result<Vec<DifferentialCase>, WorkerError> {
    let malformed = |message: String| Err(WorkerError::Malformed(message));
    if raw.len() > max {
        return malformed(format!("{} cases exceed the limit of {max}", raw.len()));
    }
    let mut ids = BTreeSet::new();
    let mut cases = Vec::with_capacity(raw.len());
    for case in raw {
        let id = case.id;
        if !is_plain_id(&id) {
            return malformed(format!("case id {id:?} is not a plain token"));
        }
        if !ids.insert(id.clone()) {
            return malformed(format!("duplicate case id {id}"));
        }
        if case.args.len() > MAX_ARGS || case.args.iter().any(|arg| arg.contains('\0')) {
            return malformed(format!("case {id} has too many or invalid arguments"));
        }
        if case
            .stdin
            .as_ref()
            .is_some_and(|stdin| stdin.len() > MAX_STDIN_BYTES)
        {
            return malformed(format!("case {id} stdin is too large"));
        }
        if case.files.len() > MAX_FIXTURE_ENTRIES || case.dirs.len() > MAX_FIXTURE_ENTRIES {
            return malformed(format!("case {id} has too many fixtures"));
        }
        let paths = case
            .files
            .iter()
            .map(|file| file.path.as_str())
            .chain(case.dirs.iter().map(String::as_str));
        if let Some(path) = paths.into_iter().find(|path| safe_relative(path).is_none()) {
            return malformed(format!(
                "case {id} fixture path {path:?} leaves the case directory"
            ));
        }
        let fixture_bytes = case
            .files
            .iter()
            .fold(0usize, |total, file| total.saturating_add(file.len()));
        if fixture_bytes > MAX_FIXTURE_BYTES {
            return malformed(format!("case {id} fixtures are too large"));
        }
        if case.env.len() > MAX_ENV {
            return malformed(format!("case {id} sets too many environment variables"));
        }
        let mut env = BTreeMap::new();
        for RawEnv { name, value } in case.env {
            let valid_value = value.len() <= MAX_ENV_VALUE_BYTES
                && !value.contains('\n')
                && !value.contains('\0');
            if !is_env_name(&name) || !valid_value {
                return malformed(format!("case {id} has an invalid environment variable"));
            }
            if env.insert(name.clone(), value).is_some() {
                return malformed(format!("case {id} sets {name} twice"));
            }
        }
        if case.family.len() > MAX_FAMILY_BYTES || case.family.contains('\n') {
            return malformed(format!("case {id} family is not a short tag"));
        }
        if let Some(terminal) = &case.terminal
            && (!(1..=500).contains(&terminal.rows)
                || !(1..=1000).contains(&terminal.cols)
                || terminal.dialogue.len() > 64
                || terminal
                    .dialogue
                    .iter()
                    .any(|e| e.expect.is_empty() || e.expect.len() > 1024)
                || terminal
                    .dialogue
                    .iter()
                    .fold(terminal.input.len(), |n, e| n.saturating_add(e.send.len()))
                    > MAX_STDIN_BYTES)
        {
            return malformed(format!(
                "case {id} has invalid terminal dimensions or input"
            ));
        }
        cases.push(DifferentialCase {
            id,
            args: case.args,
            stdin: case.stdin,
            files: case.files,
            dirs: case.dirs,
            env,
            family: case.family,
            terminal: case.terminal,
        });
    }
    Ok(cases)
}

/// Pair every observation with its normalized invocation. The writer is a fresh worker: it
/// cannot recover stdin, fixture contents, environment or terminal input from an argv summary.
/// Each case has its own byte allowance, so a large early example cannot hide later cases.
pub(crate) fn render_observations(
    cases: &[DifferentialCase],
    observations: &[Observation],
    cap: usize,
) -> String {
    let per_case = cap / observations.len().max(1);
    let mut text = String::new();
    for observation in observations {
        let Some(case) = cases.iter().find(|case| case.id == observation.id) else {
            continue;
        };
        let exit = observation
            .exit
            .map_or_else(|| "unknown".to_string(), |exit| exit.to_string());
        let stability = if observation.stable {
            ", all channels stable".to_string()
        } else if observation.stable_channels.is_empty() {
            ", stable channels unavailable".to_string()
        } else {
            format!(
                ", stable channels: {}; other channels may vary",
                observation.stable_channels.join(",")
            )
        };
        let heading = format!(
            "Case {}\nInvocation JSON (omission markers mean unknown input, not defaults):\n",
            case.id
        );
        let ending = format!("\n[exit status {exit}{stability}]\n\n");
        let overhead = heading.len() + ending.len() + "\n[stdout]\n\n[stderr]\n".len();
        let Some(available) = per_case.checked_sub(overhead) else {
            return bounded(
                "[Reference observations omitted: insufficient budget for paired input/output framing]",
                cap,
            );
        };
        let input_cap = available
            - observation.stdout.len().min(available / 4)
            - observation.stderr.len().min(available / 4);
        let invocation = observation_fragment(&json!(case).to_string(), input_cap);
        let remaining = available - invocation.len();
        let out_cap = remaining - observation.stderr.len().min(remaining / 2);
        let stdout = observation_fragment(&observation.stdout, out_cap);
        let stderr = observation_fragment(&observation.stderr, remaining - stdout.len());
        text.push_str(&format!(
            "{heading}{invocation}\n[stdout]\n{stdout}\n[stderr]\n{stderr}{ending}"
        ));
    }
    bounded(&text, cap)
}

fn observation_fragment(value: &str, cap: usize) -> String {
    if value.len() <= cap {
        value.to_string()
    } else if cap < 64 {
        bounded(value, cap)
    } else {
        // The existing head/tail helper's marker is additional to its data allowance.
        // Reserve more than its maximum usize-length marker before allocating data bytes.
        bounded_head_tail(value, cap - 64)
    }
}

#[cfg(test)]
#[path = "cases_tests.rs"]
mod tests;
