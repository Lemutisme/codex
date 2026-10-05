//! The case format the drafter's public cases and the prober's sealed cases share: its strict
//! output schema, its validation, and how reference observations are shown to a worker.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

use super::WorkerError;
use super::bounded;
use super::strict_object;
use crate::DifferentialCase;
use crate::FixtureFile;
use crate::Observation;
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

/// The instructions every case-writing worker shares.
pub(crate) const CASE_RULES: &str = "Each case runs in a fresh copy of the base workspace (so relative paths to its \
documentation and assets resolve), with the case's own files and empty directories added on top, a fixed environment \
plus the case's env, and the case's stdin. Both programs run at the same path with the same arguments; their exit \
status, standard output, standard error and the files left in the case directory are compared. Give each case a plain \
id (letters, digits, '-', '_', '.'), a short family tag naming the behavior it exercises, args (the argument vector \
after the program name), stdin (text up to 64 KiB, or null), files (path relative to the case directory, text, and \
repeat: the content is text repeated that many times; at most 256 KiB per case), dirs (empty directories), and env \
(name/value pairs). Never use the reference program itself as an input.";

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

fn is_env_name(name: &str) -> bool {
    let mut chars = name.chars();
    chars
        .next()
        .is_some_and(|first| first.is_ascii_uppercase() || first == '_')
        && chars.all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
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
        cases.push(DifferentialCase {
            id,
            args: case.args,
            stdin: case.stdin,
            files: case.files,
            dirs: case.dirs,
            env,
            family: case.family,
        });
    }
    Ok(cases)
}

/// Observations of the reference, one block per case, bounded to `cap` bytes; each stream gets an
/// equal share so one long output cannot crowd out the rest.
pub(crate) fn render_observations(
    cases: &[DifferentialCase],
    observations: &[Observation],
    cap: usize,
) -> String {
    let per_stream = (cap / (2 * observations.len().max(1))).max(400);
    let mut text = String::new();
    for observation in observations {
        let Some(case) = cases.iter().find(|case| case.id == observation.id) else {
            continue;
        };
        text.push_str(&format!("$ executable {}", shell_words(&case.args)));
        if case.stdin.is_some() {
            text.push_str(" < stdin");
        }
        text.push('\n');
        let fixtures: Vec<&str> = case
            .files
            .iter()
            .map(|file| file.path.as_str())
            .chain(case.dirs.iter().map(String::as_str))
            .collect();
        if !fixtures.is_empty() {
            text.push_str(&format!("[fixtures: {}]\n", fixtures.join(", ")));
        }
        text.push_str(&bounded(&observation.stdout, per_stream));
        if !observation.stderr.is_empty() {
            text.push_str("[stderr]\n");
            text.push_str(&bounded(&observation.stderr, per_stream));
        }
        let exit = observation
            .exit
            .map_or_else(|| "unknown".to_string(), |exit| exit.to_string());
        let stability = if observation.stable {
            ""
        } else {
            ", differs between two runs"
        };
        text.push_str(&format!("[exit status {exit}{stability}]\n\n"));
    }
    bounded(&text, cap)
}

fn shell_words(args: &[String]) -> String {
    args.iter()
        .map(|arg| {
            if !arg.is_empty()
                && arg
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || "-_./=:,+@%".contains(c))
            {
                arg.clone()
            } else {
                crate::checks::shell_quote(arg)
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
#[path = "cases_tests.rs"]
mod tests;
