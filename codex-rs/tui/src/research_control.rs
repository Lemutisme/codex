//! Thin user-command transport to a provisioner-owned research runtime.
//!
//! The endpoint supplies authority and execution capabilities. This client sends
//! the user's request; it does not select a research workflow or model action.

use serde::Serialize;
use serde_json::Value;
use std::path::Path;
use std::time::Duration;

pub(crate) const SOCKET_ENV: &str = "PROCONTRACT_RESEARCH_SOCKET";
pub(crate) const USAGE: &str =
    "Usage: /rsi <research goal> | /rsi status | /rsi resume | /rsi cancel | /rsi input <feedback>";

#[derive(Debug, Serialize, PartialEq, Eq)]
pub(crate) struct Request {
    pub(crate) schema: u8,
    pub(crate) request_id: String,
    pub(crate) operation: String,
    pub(crate) request: Option<String>,
    pub(crate) thread_id: Option<String>,
}

impl Request {
    pub(crate) fn parse(args: &str, thread_id: Option<String>) -> Result<Self, String> {
        let args = args.trim();
        let (head, tail) = args
            .split_once(char::is_whitespace)
            .map_or((args, ""), |(head, tail)| (head, tail.trim()));
        let (operation, request) = match head {
            "" => ("status", None),
            "status" | "resume" | "cancel" if tail.is_empty() => (head, None),
            "stop" if tail.is_empty() => ("cancel", None),
            "start" | "input" if !tail.is_empty() => (head, Some(tail.to_string())),
            "start" | "input" | "status" | "resume" | "cancel" | "stop" => {
                return Err(USAGE.to_string());
            }
            _ => ("start", Some(args.to_string())),
        };
        Ok(Self {
            schema: 1,
            request_id: uuid::Uuid::new_v4().to_string(),
            operation: operation.to_string(),
            request,
            thread_id,
        })
    }
}

pub(crate) fn configured_socket() -> Option<std::path::PathBuf> {
    std::env::var_os(SOCKET_ENV)
        .filter(|value| !value.is_empty())
        .map(Into::into)
}

pub(crate) async fn request(path: &Path, message: &Request) -> Result<String, String> {
    request_with_timeout(path, message, Duration::from_secs(10)).await
}

fn display_result(result: &Value) -> Result<String, serde_json::Error> {
    let Some(message) = result.get("message").and_then(Value::as_str) else {
        return serde_json::to_string_pretty(result);
    };
    let mut lines = vec![message.to_string()];
    if let Some(state) = result.get("state").and_then(Value::as_str) {
        let active = result
            .get("active_operations")
            .and_then(Value::as_array)
            .map_or(0, Vec::len);
        lines.push(format!("State: {state}; active operations: {active}"));
    }
    if let Some(goal) = result.get("goal").and_then(Value::as_str) {
        lines.push(format!("Goal: {goal}"));
    }
    if let Some(root) = result.get("root").and_then(Value::as_str) {
        lines.push(format!("Retained research: {root}"));
    }
    Ok(lines.join("\n"))
}

#[cfg(unix)]
async fn request_with_timeout(
    path: &Path,
    message: &Request,
    timeout: Duration,
) -> Result<String, String> {
    use tokio::io::AsyncBufReadExt;
    use tokio::io::AsyncReadExt;
    use tokio::io::AsyncWriteExt;
    use tokio::io::BufReader;

    let response = tokio::time::timeout(timeout, async {
        let mut stream = tokio::net::UnixStream::connect(path).await?;
        let mut payload = serde_json::to_vec(message)?;
        payload.push(b'\n');
        stream.write_all(&payload).await?;
        let mut line = String::new();
        BufReader::new(stream.take((1 << 20) + 1))
            .read_line(&mut line)
            .await?;
        if line.len() > 1 << 20 || !line.ends_with('\n') {
            anyhow::bail!("incomplete or oversized research control response");
        }
        let response: Value = serde_json::from_str(&line)?;
        if let Some(error) = response.get("error").and_then(Value::as_str) {
            anyhow::bail!("{error}");
        }
        let result = response
            .get("result")
            .ok_or_else(|| anyhow::anyhow!("missing control result"))?;
        Ok::<String, anyhow::Error>(display_result(result)?)
    })
    .await;
    match response {
        Ok(Ok(message)) => Ok(message),
        Ok(Err(error)) => Err(format!(
            "RSI control: {error}. Request {}. Use /rsi status to inspect retained state.",
            message.request_id
        )),
        Err(_) => Err(format!(
            "RSI control acknowledgement timed out. Request {} may already be admitted; use /rsi status. The request was not replayed.",
            message.request_id
        )),
    }
}

#[cfg(not(unix))]
async fn request_with_timeout(
    _path: &Path,
    _message: &Request,
    _timeout: Duration,
) -> Result<String, String> {
    Err("This local RSI control endpoint requires Unix sockets.".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn user_goal_is_data_and_controls_are_explicit() {
        let text = "inspect the project; $(do-not-execute) `literal`\nthen propose a change";
        let request = Request::parse(text, Some("thread".to_string())).unwrap();
        assert_eq!(request.operation, "start");
        assert_eq!(request.request.as_deref(), Some(text));
        assert_eq!(Request::parse("", None).unwrap().operation, "status");
        assert_eq!(Request::parse("stop", None).unwrap().operation, "cancel");
        assert_eq!(
            Request::parse("input new evidence", None)
                .unwrap()
                .request
                .as_deref(),
            Some("new evidence")
        );
        assert!(Request::parse("cancel another scope", None).is_err());
        let result = serde_json::json!({"message":"Retained work", "state":"waiting", "root":"/research", "active_operations":[]});
        assert_eq!(
            display_result(&result).unwrap(),
            "Retained work\nState: waiting; active operations: 0\nRetained research: /research"
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn socket_round_trip_preserves_the_selected_request() {
        use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("control.sock");
        let listener = tokio::net::UnixListener::bind(&path).unwrap();
        let message = Request::parse("retro this project", Some("thread-1".to_string())).unwrap();
        let expected = serde_json::to_value(&message).unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut stream = BufReader::new(stream);
            let mut line = String::new();
            stream.read_line(&mut line).await.unwrap();
            assert_eq!(serde_json::from_str::<Value>(&line).unwrap(), expected);
            stream
                .get_mut()
                .write_all(b"{\"result\":{\"message\":\"Research admitted\"}}\n")
                .await
                .unwrap();
        });
        assert_eq!(request(&path, &message).await.unwrap(), "Research admitted");
        server.await.unwrap();
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn lost_acknowledgement_does_not_replay_the_request() {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("control.sock");
        let listener = tokio::net::UnixListener::bind(&path).unwrap();
        let message = Request::parse("retro", None).unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut stream = BufReader::new(stream);
            let mut line = String::new();
            stream.read_line(&mut line).await.unwrap();
            tokio::time::sleep(Duration::from_millis(80)).await;
            assert!(
                tokio::time::timeout(Duration::from_millis(10), listener.accept())
                    .await
                    .is_err()
            );
        });
        let error = request_with_timeout(&path, &message, Duration::from_millis(30))
            .await
            .unwrap_err();
        assert!(error.contains(&message.request_id));
        assert!(error.contains("not replayed"));
        server.await.unwrap();
    }
}
