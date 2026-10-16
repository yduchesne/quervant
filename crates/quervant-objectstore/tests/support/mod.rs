//! Test-only deterministic HTTP/1.1 fault proxy in front of real RustFS.
//!
//! This module is compiled only into integration-test binaries. It tunnels the
//! exact request bytes (including the `Host` header) to the real RustFS endpoint
//! so AWS SigV4 signing remains valid, and injects faults on a per-rule,
//! per-matching-request basis. It never fabricates a successful conditional PUT:
//! `ForwardThenDrop` forwards the whole request, observes the real upstream
//! response, and only then closes the client connection without delivering it.
//!
//! It records sanitized method/key/status counts only; credentials, signatures
//! and document bytes are never logged.

#![allow(dead_code)]

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Notify;

/// A deterministic response/transport fault.
#[derive(Clone)]
pub enum Fault {
    /// Send the response head and the first `n` body bytes, then close (an
    /// interrupted transfer).
    TruncateBodyAfter(usize),
    /// Rewrite a `206` status line to `200` and strip `Content-Range`.
    ReplaceStatus200,
    /// Replace the `Content-Range` header value (or add it if absent).
    SetContentRange(String),
    /// Block before forwarding until the notifier is released.
    DelayUntil(Arc<Notify>),
    /// Answer `503 Service Unavailable` without forwarding.
    Return503,
    /// Answer an arbitrary status without forwarding.
    ReturnStatus(u16),
    /// Forward fully, read the real response, then close without delivering it.
    ForwardThenDrop,
    /// Forward the request fully, record the named checkpoint, then block.
    ForwardThenCheckpoint(String),
    /// Record the named checkpoint, block, and never forward.
    BlockBeforeCheckpoint(String),
}

/// A fault keyed by method, a path substring, and the 1-based matching request.
#[derive(Clone)]
pub struct Rule {
    /// HTTP method (`"PUT"`, `"GET"`, …).
    pub method: String,
    /// Substring that must appear in the request path.
    pub key_contains: String,
    /// Apply on the `nth` matching request (1-based); `0` means every match.
    pub nth: usize,
    /// The fault to apply.
    pub fault: Fault,
}

#[derive(Default)]
struct State {
    rules: Vec<Rule>,
    seen: Vec<usize>,
    observed: HashMap<String, usize>,
    checkpoints: HashMap<String, usize>,
}

/// A running fault proxy.
pub struct Proxy {
    /// Base endpoint to hand to `S3Config` (for example `http://127.0.0.1:1234`).
    pub endpoint: String,
    state: Arc<Mutex<State>>,
    shutdown: Arc<Notify>,
    handle: tokio::task::JoinHandle<()>,
}

impl Proxy {
    /// Start a proxy forwarding to `upstream_host:upstream_port`.
    pub async fn start(upstream_host: &str, upstream_port: u16) -> Self {
        let listener = TcpListener::bind(("127.0.0.1", 0))
            .await
            .expect("bind proxy");
        let port = listener.local_addr().expect("proxy addr").port();
        let endpoint = format!("http://127.0.0.1:{port}");
        let state = Arc::new(Mutex::new(State::default()));
        let shutdown = Arc::new(Notify::new());
        let upstream = (upstream_host.to_owned(), upstream_port);
        let handle = {
            let state = Arc::clone(&state);
            let shutdown = Arc::clone(&shutdown);
            tokio::spawn(async move {
                loop {
                    let accept = tokio::select! {
                        accept = listener.accept() => accept,
                        () = shutdown.notified() => return,
                    };
                    let Ok((client, _)) = accept else {
                        return;
                    };
                    let upstream = upstream.clone();
                    let state = Arc::clone(&state);
                    tokio::spawn(async move {
                        let _ = handle_connection(client, &upstream, &state).await;
                    });
                }
            })
        };
        Self {
            endpoint,
            state,
            shutdown,
            handle,
        }
    }

    /// Install a rule. Rules are matched in insertion order.
    pub fn add_rule(&self, rule: Rule) {
        let mut state = self.state.lock().expect("proxy state");
        state.rules.push(rule);
        state.seen.push(0);
    }

    /// Number of requests whose method and path matched `method`/`key`.
    pub fn observed(&self, method: &str, key: &str) -> usize {
        let state = self.state.lock().expect("proxy state");
        let mut total = 0;
        for (name, count) in &state.observed {
            if let Some((m, k)) = name.split_once(' ') {
                if m.eq_ignore_ascii_case(method) && k.contains(key) {
                    total += count;
                }
            }
        }
        total
    }

    /// Whether the named crash checkpoint has been reached.
    pub fn checkpoint_hit(&self, name: &str) -> bool {
        self.state
            .lock()
            .expect("proxy state")
            .checkpoints
            .get(name)
            .is_some_and(|count| *count > 0)
    }

    /// All observed `method path` counts, for diagnostics.
    pub fn observed_all(&self) -> Vec<(String, usize)> {
        let state = self.state.lock().expect("proxy state");
        state
            .observed
            .iter()
            .map(|(name, count)| (name.clone(), *count))
            .collect()
    }

    /// Signal and await shutdown, then abort the accept loop.
    pub async fn stop(self) {
        self.shutdown.notify_waiters();
        self.handle.abort();
        let _ = tokio::time::timeout(Duration::from_secs(2), self.handle).await;
    }
}

struct Message {
    raw_head: Vec<u8>,
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
}

impl Message {
    fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(n, _)| n.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.as_str())
    }
}

async fn handle_connection(
    mut client: TcpStream,
    upstream: &(String, u16),
    state: &Arc<Mutex<State>>,
) -> std::io::Result<()> {
    let mut buf: Vec<u8> = Vec::new();
    loop {
        let Some(head_len) = read_head(&mut client, &mut buf).await? else {
            return Ok(());
        };
        let request = parse_message(&buf[..head_len], false, &buf[head_len..]);
        let content_length = request
            .header("content-length")
            .and_then(|v| v.parse::<usize>().ok());
        if let Some(n) = content_length {
            while buf.len() < head_len + n {
                let mut chunk = [0u8; 64 * 1024];
                let read = client.read(&mut chunk).await?;
                if read == 0 {
                    break;
                }
                buf.extend_from_slice(&chunk[..read]);
            }
        }
        let request = parse_message(&buf[..head_len], false, &buf[head_len..]);
        let body_len = content_length.unwrap_or(0).min(buf.len() - head_len);
        let raw_request = buf[..head_len + body_len].to_vec();
        buf.drain(..head_len + body_len);

        record_observed(state, &request.method, &request.path);
        let fault = match_fault(state, &request.method, &request.path);

        match fault {
            Some(Fault::Return503) => {
                send_all(
                    &mut client,
                    b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .await?;
                return Ok(());
            }
            Some(Fault::ReturnStatus(status)) => {
                let response = format!(
                    "HTTP/1.1 {status} Fault\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                );
                send_all(&mut client, response.as_bytes()).await?;
                return Ok(());
            }
            Some(Fault::BlockBeforeCheckpoint(name)) => {
                mark_checkpoint(state, &name);
                // Never forward: the request must not reach RustFS.
                std::future::pending::<()>().await;
                return Ok(());
            }
            Some(Fault::DelayUntil(ref release)) => {
                release.notified().await;
            }
            _ => {}
        }

        // Forward the exact request bytes to the real upstream.
        let mut server = TcpStream::connect((upstream.0.as_str(), upstream.1)).await?;
        server.write_all(&raw_request).await?;
        server.flush().await?;

        let response = match read_full_response(
            &mut server,
            request.method.eq_ignore_ascii_case("HEAD"),
        )
        .await
        {
            Ok(response) => response,
            Err(_) => {
                return Ok(());
            }
        };

        match fault {
            Some(Fault::ForwardThenDrop) => {
                // The upstream applied the request; drop the client connection
                // without delivering the response.
                return Ok(());
            }
            Some(Fault::ForwardThenCheckpoint(name)) => {
                mark_checkpoint(state, &name);
                std::future::pending::<()>().await;
                return Ok(());
            }
            Some(Fault::TruncateBodyAfter(n)) => {
                client.write_all(&response.raw_head).await?;
                let body = response.body;
                let take = n.min(body.len());
                client.write_all(&body[..take]).await?;
                client.flush().await?;
                return Ok(());
            }
            Some(Fault::ReplaceStatus200) => {
                let head = response.rebuild_head(
                    Some("HTTP/1.1 200 OK"),
                    &["Content-Range", "Transfer-Encoding"],
                    &[("Content-Length", response.body.len().to_string())],
                );
                send_all(&mut client, &head).await?;
                send_all(&mut client, &response.body).await?;
                continue;
            }
            Some(Fault::SetContentRange(value)) => {
                let head =
                    response.rebuild_head(None, &["Content-Range"], &[("Content-Range", value)]);
                send_all(&mut client, &head).await?;
                send_all(&mut client, &response.body).await?;
                continue;
            }
            _ => {
                client.write_all(&response.raw_head).await?;
                client.write_all(&response.body).await?;
                client.flush().await?;
                if response.close_after {
                    return Ok(());
                }
                continue;
            }
        }
    }
}

fn mark_checkpoint(state: &Arc<Mutex<State>>, name: &str) {
    let mut state = state.lock().expect("proxy state");
    *state.checkpoints.entry(name.to_owned()).or_insert(0) += 1;
}

fn record_observed(state: &Arc<Mutex<State>>, method: &str, path: &str) {
    let mut state = state.lock().expect("proxy state");
    *state
        .observed
        .entry(format!("{method} {path}"))
        .or_insert(0) += 1;
}

fn match_fault(state: &Arc<Mutex<State>>, method: &str, path: &str) -> Option<Fault> {
    let mut state = state.lock().expect("proxy state");
    let count = state.rules.len();
    for index in 0..count {
        let (rule_method, rule_key, rule_nth, fault) = {
            let rule = &state.rules[index];
            (
                rule.method.clone(),
                rule.key_contains.clone(),
                rule.nth,
                rule.fault.clone(),
            )
        };
        if !rule_method.eq_ignore_ascii_case(method) || !path.contains(&rule_key) {
            continue;
        }
        state.seen[index] += 1;
        let seen = state.seen[index];
        let apply = if rule_nth == 0 {
            true
        } else {
            seen == rule_nth
        };
        if apply {
            return Some(fault);
        }
    }
    None
}

struct Response {
    raw_head: Vec<u8>,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    close_after: bool,
}

async fn read_full_response(server: &mut TcpStream, is_head: bool) -> std::io::Result<Response> {
    let mut buf = Vec::new();
    let Some(head_len) = read_head(server, &mut buf).await? else {
        return Err(std::io::Error::other("no response head"));
    };
    let parsed = parse_message(&buf[..head_len], true, &[]);
    // A HEAD response carries headers (including Content-Length) but no body.
    let content_length = if is_head {
        None
    } else {
        parsed
            .header("content-length")
            .and_then(|v| v.parse::<usize>().ok())
    };
    let chunked = !is_head
        && parsed
            .header("transfer-encoding")
            .is_some_and(|v| v.to_ascii_lowercase().contains("chunked"));
    let close_after = parsed
        .header("connection")
        .is_some_and(|v| v.to_ascii_lowercase().contains("close"));
    if is_head {
        // No body to read.
    } else if let Some(n) = content_length {
        while buf.len() < head_len + n {
            let mut chunk = [0u8; 64 * 1024];
            let read = server.read(&mut chunk).await?;
            if read == 0 {
                break;
            }
            buf.extend_from_slice(&chunk[..read]);
        }
    } else if chunked {
        loop {
            if try_parse_chunked(&buf, head_len).is_some() {
                break;
            }
            let mut chunk = [0u8; 64 * 1024];
            let read = server.read(&mut chunk).await?;
            if read == 0 {
                break;
            }
            buf.extend_from_slice(&chunk[..read]);
        }
    } else {
        loop {
            let mut chunk = [0u8; 64 * 1024];
            let read = server.read(&mut chunk).await?;
            if read == 0 {
                break;
            }
            buf.extend_from_slice(&chunk[..read]);
        }
    }
    let body = buf[head_len..].to_vec();
    Ok(Response {
        raw_head: buf[..head_len].to_vec(),
        headers: parsed.headers,
        body,
        close_after,
    })
}

impl Response {
    fn rebuild_head(
        &self,
        status_line: Option<&str>,
        strip: &[&str],
        set: &[(&str, String)],
    ) -> Vec<u8> {
        let base = status_line.unwrap_or_else(|| {
            std::str::from_utf8(&self.raw_head)
                .ok()
                .and_then(|text| text.lines().next())
                .unwrap_or("HTTP/1.1 200 OK")
        });
        let mut emitted: Vec<String> = Vec::new();
        for (name, value) in &self.headers {
            if strip.iter().any(|s| name.eq_ignore_ascii_case(s)) {
                continue;
            }
            if set.iter().any(|(s, _)| name.eq_ignore_ascii_case(s)) {
                continue;
            }
            emitted.push(format!("{name}: {value}"));
        }
        for (name, value) in set {
            emitted.push(format!("{name}: {value}"));
        }
        let mut head = Vec::new();
        head.extend_from_slice(base.as_bytes());
        head.extend_from_slice(b"\r\n");
        for line in emitted {
            head.extend_from_slice(line.as_bytes());
            head.extend_from_slice(b"\r\n");
        }
        head.extend_from_slice(b"\r\n");
        head
    }
}

async fn send_all(stream: &mut TcpStream, bytes: &[u8]) -> std::io::Result<()> {
    stream.write_all(bytes).await?;
    stream.flush().await
}

async fn read_head(stream: &mut TcpStream, buf: &mut Vec<u8>) -> std::io::Result<Option<usize>> {
    loop {
        if let Some(pos) = find(&buf[..], b"\r\n\r\n") {
            return Ok(Some(pos + 4));
        }
        if buf.len() > 32 * 1024 * 1024 {
            return Err(std::io::Error::other("proxy head too large"));
        }
        let mut chunk = [0u8; 16 * 1024];
        let read = stream.read(&mut chunk).await?;
        if read == 0 {
            return Ok(None);
        }
        buf.extend_from_slice(&chunk[..read]);
    }
}

fn parse_message(head: &[u8], _is_response: bool, existing_body: &[u8]) -> Message {
    let text = String::from_utf8_lossy(head);
    let mut lines = text.split("\r\n");
    let first = lines.next().unwrap_or_default().to_owned();
    let mut parts = first.split(' ');
    let method = parts.next().unwrap_or_default().to_owned();
    let path = parts.next().unwrap_or_default().to_owned();
    let mut headers = Vec::new();
    for line in lines {
        if line.is_empty() {
            continue;
        }
        if let Some((name, value)) = line.split_once(':') {
            headers.push((name.trim().to_owned(), value.trim().to_owned()));
        }
    }
    Message {
        raw_head: head.to_vec(),
        method,
        path,
        headers,
        body: existing_body.to_vec(),
    }
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

fn try_parse_chunked(buf: &[u8], start: usize) -> Option<usize> {
    let mut pos = start;
    loop {
        let line_end = find(&buf[pos..], b"\r\n")? + pos;
        let size_text = std::str::from_utf8(&buf[pos..line_end]).ok()?;
        let size = usize::from_str_radix(size_text.split(';').next()?.trim(), 16).ok()?;
        pos = line_end + 2;
        if size == 0 {
            let end = find(&buf[pos..], b"\r\n")? + pos + 2;
            return Some(end - start);
        }
        pos = pos.checked_add(size)?;
        if pos + 2 > buf.len() {
            return None;
        }
        pos += 2;
    }
}
