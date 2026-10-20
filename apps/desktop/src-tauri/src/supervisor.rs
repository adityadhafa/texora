//! Engine sidecar supervisor.
//!
//! This module is a thin, secure *process manager* for the Python engine
//! sidecar. It contains NO OCR / business logic — that all lives in the engine.
//! The supervisor's responsibilities are:
//!
//! 1. Generate a per-session 256-bit bearer token.
//! 2. Pick a free loopback (`127.0.0.1`) ephemeral port.
//! 3. Spawn the engine (dev: `python -m texora_engine`; prod: the frozen
//!    `externalBin` sidecar) with the token supplied via the
//!    `TEXORA_ENGINE_TOKEN` environment variable to avoid argv leakage.
//! 4. Health-check `GET /healthz` until the engine answers `200`.
//! 5. Restart with exponential backoff on crash or failed health check.
//! 6. Broadcast state changes as `engine://status` events and answer the
//!    `engine_status` command with the current status.
//!
//! The pure helpers (`free_loopback_port`, `generate_token`, `BackoffSchedule`)
//! are unit-tested without spawning a real engine.

use std::net::{Ipv4Addr, SocketAddrV4, TcpListener};
use std::sync::Mutex;
use std::time::Duration;

use rand::RngCore;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Event name used for every engine status broadcast.
pub const STATUS_EVENT: &str = "engine://status";

/// Sidecar base name (resolved by Tauri with the `-$TARGET_TRIPLE` suffix).
const SIDECAR_NAME: &str = "texora-engine";

/// How long a single `/healthz` request may take.
const HEALTH_TIMEOUT: Duration = Duration::from_millis(1500);

/// Delay between `/healthz` polls while waiting for the engine to come up.
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(250);

/// Maximum number of `/healthz` polls before a freshly spawned engine is
/// considered unhealthy (≈ 20s at the poll interval above).
const HEALTH_MAX_POLLS: u32 = 80;

/// Lifecycle state of the engine, surfaced to the UI.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum EngineState {
    /// The engine is being spawned / waiting for its first healthy response.
    Starting,
    /// `/healthz` answered `200`.
    Healthy,
    /// The engine process is alive but `/healthz` is not answering `200`.
    Unhealthy,
    /// A crash/failure was detected and a backoff restart is scheduled.
    Restarting,
    /// The supervisor has stopped the engine and will not restart it.
    Stopped,
}

/// Typed status payload shared with the UI via the command and events.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineStatus {
    pub state: EngineState,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

impl EngineStatus {
    fn new(state: EngineState, port: Option<u16>, detail: Option<String>) -> Self {
        Self {
            state,
            port,
            detail,
        }
    }
}

impl Default for EngineStatus {
    fn default() -> Self {
        Self::new(EngineState::Starting, None, None)
    }
}

/// Managed Tauri state holding the latest known engine status plus the live loopback
/// `port` and session `token`. The token/port stay in Rust and are NEVER handed to the
/// webview — JS reaches the engine only through the authenticated proxy commands.
pub struct SupervisorState {
    status: Mutex<EngineStatus>,
    /// Live loopback port of the currently-healthy engine (None until healthy).
    port: Mutex<Option<u16>>,
    /// Per-session bearer token minted once by `start`.
    token: Mutex<String>,
    /// Set of model ids with an in-flight download poll (so duplicate polls are avoided).
    downloads: Mutex<std::collections::HashSet<String>>,
}

impl Default for SupervisorState {
    fn default() -> Self {
        Self {
            status: Mutex::new(EngineStatus::default()),
            port: Mutex::new(None),
            token: Mutex::new(String::new()),
            downloads: Mutex::new(std::collections::HashSet::new()),
        }
    }
}

impl SupervisorState {
    /// Snapshot the current status for the `engine_status` command.
    pub fn snapshot(&self) -> EngineStatus {
        self.status
            .lock()
            .expect("supervisor status mutex poisoned")
            .clone()
    }

    fn set(&self, status: EngineStatus) {
        let mut guard = self
            .status
            .lock()
            .expect("supervisor status mutex poisoned");
        *guard = status;
    }

    /// Store the session token (called once at startup).
    pub fn set_token(&self, token: &str) {
        *self.token.lock().expect("token mutex poisoned") = token.to_string();
    }

    /// Record the live port when the engine becomes healthy (or clear it when not).
    pub fn set_port(&self, port: Option<u16>) {
        *self.port.lock().expect("port mutex poisoned") = port;
    }

    /// Current live port, if the engine is healthy.
    pub fn port(&self) -> Option<u16> {
        *self.port.lock().expect("port mutex poisoned")
    }

    /// Current session token.
    pub fn token(&self) -> String {
        self.token.lock().expect("token mutex poisoned").clone()
    }

    /// Register an in-flight download; returns false if already registered.
    pub fn begin_download(&self, id: &str) -> bool {
        self.downloads
            .lock()
            .expect("downloads mutex poisoned")
            .insert(id.to_string())
    }

    /// Remove a download from the in-flight set (on a terminal state).
    pub fn end_download(&self, id: &str) {
        self.downloads
            .lock()
            .expect("downloads mutex poisoned")
            .remove(id);
    }
}

/// Error from the authenticated engine proxy.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProxyError {
    pub kind: String,
    pub message: String,
}

impl ProxyError {
    fn not_ready() -> Self {
        Self {
            kind: "engineNotReady".to_string(),
            message: "engine is not healthy yet".to_string(),
        }
    }

    fn http(status: u16, message: String) -> Self {
        Self {
            kind: format!("http{status}"),
            message,
        }
    }

    fn transport(message: String) -> Self {
        Self {
            kind: "transport".to_string(),
            message,
        }
    }

    /// Build a proxy error with an explicit kind + message (used by command wrappers for
    /// local validation/IO failures that never reach the engine).
    pub fn from_message(kind: &str, message: String) -> Self {
        Self {
            kind: kind.to_string(),
            message,
        }
    }
}

/// Build the base URL for the live engine port, or an error if not ready.
fn engine_base_url(port: Option<u16>) -> Result<String, ProxyError> {
    match port {
        Some(p) => Ok(format!("http://127.0.0.1:{p}")),
        None => Err(ProxyError::not_ready()),
    }
}

/// Make an authenticated request to the engine and return the response body bytes.
///
/// The bearer token + port are read from `SupervisorState` and never cross into JS. A `GET`
/// is issued when `body` is `None`; otherwise a `POST` with a JSON body.
pub fn engine_request(
    state: &SupervisorState,
    method: &str,
    path: &str,
    body: Option<&str>,
) -> Result<String, ProxyError> {
    let base = engine_base_url(state.port())?;
    let token = state.token();
    if token.is_empty() {
        return Err(ProxyError::not_ready());
    }
    let url = format!("{base}{path}");
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(120))
        .build();
    let auth = format!("Bearer {token}");

    let result = if method.eq_ignore_ascii_case("post") {
        let req = agent.post(&url).set("Authorization", &auth);
        match body {
            Some(b) => req.set("Content-Type", "application/json").send_string(b),
            None => req.call(),
        }
    } else {
        agent.get(&url).set("Authorization", &auth).call()
    };

    match result {
        Ok(resp) => resp
            .into_string()
            .map_err(|e| ProxyError::transport(e.to_string())),
        Err(ureq::Error::Status(code, resp)) => {
            let detail = resp.into_string().unwrap_or_default();
            Err(ProxyError::http(code, detail))
        }
        Err(e) => Err(ProxyError::transport(e.to_string())),
    }
}

/// Bind `127.0.0.1:0`, read the OS-assigned ephemeral port, then release the
/// listener so the engine can bind it. There is an inherent TOCTOU window, but
/// it is acceptable for a single-user loopback app and keeps port selection out
/// of the engine.
pub fn free_loopback_port() -> std::io::Result<u16> {
    let addr = SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0);
    let listener = TcpListener::bind(addr)?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

/// Generate a 256-bit (32-byte) session token, hex-encoded to 64 lowercase
/// characters. Each call draws fresh randomness from the OS RNG.
pub fn generate_token() -> String {
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// Exponential backoff schedule with a cap. Pure and unit-testable; the restart
/// loop advances it on each failed attempt and resets it after a healthy run.
#[derive(Debug, Clone)]
pub struct BackoffSchedule {
    base: Duration,
    cap: Duration,
    factor: u32,
    attempt: u32,
}

impl BackoffSchedule {
    /// Create a schedule starting at `base`, multiplying by `factor` each step,
    /// clamped to `cap`.
    pub fn new(base: Duration, cap: Duration, factor: u32) -> Self {
        Self {
            base,
            cap,
            factor: factor.max(1),
            attempt: 0,
        }
    }

    /// The delay for the current attempt without advancing the schedule.
    pub fn current_delay(&self) -> Duration {
        let mult = (self.factor as u64).saturating_pow(self.attempt);
        let scaled = self.base.saturating_mul(mult.min(u32::MAX as u64) as u32);
        scaled.min(self.cap)
    }

    /// Return the current delay, then advance to the next attempt.
    pub fn next_delay(&mut self) -> Duration {
        let delay = self.current_delay();
        self.attempt = self.attempt.saturating_add(1);
        delay
    }

    /// Reset the schedule to its initial attempt (call after a healthy run).
    pub fn reset(&mut self) {
        self.attempt = 0;
    }
}

impl Default for BackoffSchedule {
    fn default() -> Self {
        // 500ms → 1s → 2s → … capped at 30s.
        Self::new(Duration::from_millis(500), Duration::from_secs(30), 2)
    }
}

/// Resolve the dev-mode Python interpreter used to run `python -m texora_engine`.
///
/// Honors `TEXORA_ENGINE_PYTHON` when set; otherwise falls back to the engine
/// virtualenv next to the crate (`<repo>/engine/.venv/Scripts/python(.exe)`),
/// and finally to `python` on `PATH`.
fn dev_python_path() -> String {
    if let Ok(explicit) = std::env::var("TEXORA_ENGINE_PYTHON") {
        if !explicit.is_empty() {
            return explicit;
        }
    }

    // CARGO_MANIFEST_DIR = <repo>/apps/desktop/src-tauri
    let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo_root) = manifest_dir.ancestors().nth(3) {
        let venv = repo_root.join("engine").join(".venv");
        let candidate = if cfg!(windows) {
            venv.join("Scripts").join("python.exe")
        } else {
            venv.join("bin").join("python")
        };
        if candidate.exists() {
            return candidate.to_string_lossy().into_owned();
        }
    }

    "python".to_string()
}

/// Publish a status update to managed state and broadcast it to the UI.
fn publish<R: Runtime>(app: &AppHandle<R>, status: EngineStatus) {
    if let Some(state) = app.try_state::<SupervisorState>() {
        state.set(status.clone());
    }
    // A failed emit must never crash the supervisor loop.
    let _ = app.emit(STATUS_EVENT, status);
}

/// Blocking `/healthz` probe. Returns `true` only on a `200` response.
fn probe_health(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/healthz");
    let agent = ureq::AgentBuilder::new().timeout(HEALTH_TIMEOUT).build();
    matches!(agent.get(&url).call(), Ok(resp) if resp.status() == 200)
}

/// Spawn the engine process (dev vs prod) with the token in the environment and
/// loopback host/port on argv. Returns the receiver + child handle.
fn spawn_engine<R: Runtime>(
    app: &AppHandle<R>,
    port: u16,
    token: &str,
) -> Result<(tauri::async_runtime::Receiver<CommandEvent>, CommandChild), String> {
    let port_str = port.to_string();
    let args = ["--host", "127.0.0.1", "--port", &port_str, "--token", token];

    let command = if tauri::is_dev() {
        let python = dev_python_path();
        app.shell()
            .command(python)
            .args(["-m", "texora_engine"])
            .args(args)
    } else {
        app.shell()
            .sidecar(SIDECAR_NAME)
            .map_err(|e| format!("failed to resolve sidecar {SIDECAR_NAME}: {e}"))?
            .args(args)
    };

    command
        // Token is also passed via env so it does not show up in process listings
        // on platforms that expose argv.
        .env("TEXORA_ENGINE_TOKEN", token)
        .spawn()
        .map_err(|e| format!("failed to spawn engine: {e}"))
}

/// Start the supervisor on a background task: spawn → health-check → restart
/// with exponential backoff, broadcasting status on every transition. The token
/// is minted once per session; a fresh free port is picked for each spawn.
pub fn start<R: Runtime>(app: AppHandle<R>) {
    let token = generate_token();
    if let Some(state) = app.try_state::<SupervisorState>() {
        state.set_token(&token);
    }

    tauri::async_runtime::spawn(async move {
        let mut backoff = BackoffSchedule::default();

        loop {
            let port = match free_loopback_port() {
                Ok(p) => p,
                Err(e) => {
                    publish(
                        &app,
                        EngineStatus::new(
                            EngineState::Restarting,
                            None,
                            Some(format!("could not reserve a loopback port: {e}")),
                        ),
                    );
                    tauri::async_runtime::spawn_blocking({
                        let delay = backoff.next_delay();
                        move || std::thread::sleep(delay)
                    })
                    .await
                    .ok();
                    continue;
                }
            };

            publish(
                &app,
                EngineStatus::new(EngineState::Starting, Some(port), None),
            );

            let (mut rx, child) = match spawn_engine(&app, port, &token) {
                Ok(pair) => pair,
                Err(detail) => {
                    publish(
                        &app,
                        EngineStatus::new(EngineState::Restarting, Some(port), Some(detail)),
                    );
                    let delay = backoff.next_delay();
                    tauri::async_runtime::spawn_blocking(move || std::thread::sleep(delay))
                        .await
                        .ok();
                    continue;
                }
            };

            // Drain the process event stream in the background so the OS pipe
            // never fills; a channel close signals the process exited.
            let (exit_tx, mut exit_rx) = tauri::async_runtime::channel::<()>(1);
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Terminated(_) = event {
                        break;
                    }
                }
                let _ = exit_tx.send(()).await;
            });

            // Poll /healthz until the engine answers 200 or we give up.
            let mut healthy = false;
            for _ in 0..HEALTH_MAX_POLLS {
                if exit_rx.try_recv().is_ok() {
                    break;
                }
                if tauri::async_runtime::spawn_blocking(move || probe_health(port))
                    .await
                    .unwrap_or(false)
                {
                    healthy = true;
                    break;
                }
                tokio::time::sleep(HEALTH_POLL_INTERVAL).await;
            }

            if healthy {
                backoff.reset();
                if let Some(state) = app.try_state::<SupervisorState>() {
                    state.set_port(Some(port));
                }
                publish(
                    &app,
                    EngineStatus::new(EngineState::Healthy, Some(port), None),
                );
                // Stay healthy until the process exits; re-probe periodically so
                // a silent hang is surfaced as `Unhealthy`.
                loop {
                    tokio::select! {
                        _ = exit_rx.recv() => { break; }
                        _ = tokio::time::sleep(Duration::from_secs(5)) => {
                            let ok = tauri::async_runtime::spawn_blocking(move || probe_health(port))
                                .await
                                .unwrap_or(false);
                            if !ok {
                                publish(
                                    &app,
                                    EngineStatus::new(
                                        EngineState::Unhealthy,
                                        Some(port),
                                        Some("/healthz stopped responding".to_string()),
                                    ),
                                );
                            }
                        }
                    }
                }
            } else {
                // Never became healthy; make sure the child is gone.
                let _ = child.kill();
            }

            // The engine exited or never came up: clear the live port and schedule a
            // backoff restart so the proxy reports "engine not ready" until it recovers.
            if let Some(state) = app.try_state::<SupervisorState>() {
                state.set_port(None);
            }
            publish(
                &app,
                EngineStatus::new(
                    EngineState::Restarting,
                    Some(port),
                    Some("engine exited; restarting with backoff".to_string()),
                ),
            );
            let delay = backoff.next_delay();
            tauri::async_runtime::spawn_blocking(move || std::thread::sleep(delay))
                .await
                .ok();
        }
    });
}

/// Event name for model-download progress updates.
pub const MODEL_PROGRESS_EVENT: &str = "engine://model-progress";

/// Interval between `GET /models/{id}` polls while a download is in flight.
const MODEL_POLL_INTERVAL: Duration = Duration::from_millis(500);

/// Terminal model-download states that stop the poller.
fn is_terminal_model_state(json: &str) -> bool {
    // Cheap substring check on the serialized state; the engine controls the vocabulary.
    json.contains("\"state\":\"ready\"")
        || json.contains("\"state\":\"corrupt\"")
        || json.contains("\"state\":\"error\"")
}

/// Start polling `GET /models/{id}` every 500 ms, emitting `engine://model-progress` with
/// the raw `ModelProgress` JSON, until a terminal state is observed (ready/corrupt/error)
/// or the engine becomes unreachable (surfaced as a synthetic error payload).
pub fn start_model_poll<R: Runtime>(app: AppHandle<R>, id: String) {
    let Some(state) = app.try_state::<SupervisorState>() else {
        return;
    };
    if !state.begin_download(&id) {
        return; // already polling this id
    }

    tauri::async_runtime::spawn(async move {
        loop {
            let poll = {
                let st = app.state::<SupervisorState>();
                engine_request(&st, "GET", &format!("/models/{id}"), None)
            };
            match poll {
                Ok(body) => {
                    let _ = app.emit(MODEL_PROGRESS_EVENT, body.clone());
                    if is_terminal_model_state(&body) {
                        break;
                    }
                }
                Err(err) => {
                    // Engine unreachable mid-download: surface an error payload and stop so
                    // the UI never hangs on a dead download.
                    let payload = format!(
                        "{{\"id\":\"{id}\",\"state\":\"error\",\"bytesReceived\":0,\
                         \"bytesTotal\":0,\"files\":[],\"detail\":\"{}\"}}",
                        err.message.replace('"', "'")
                    );
                    let _ = app.emit(MODEL_PROGRESS_EVENT, payload);
                    break;
                }
            }
            tokio::time::sleep(MODEL_POLL_INTERVAL).await;
        }
        let st = app.state::<SupervisorState>();
        st.end_download(&id);
    });
}

/// Event name for job-progress updates (PDF → Markdown convert screen).
pub const JOB_PROGRESS_EVENT: &str = "engine://job-progress";

/// Interval between `GET /jobs/{id}` polls while a job is active.
const JOB_POLL_INTERVAL: Duration = Duration::from_millis(500);

/// Terminal job statuses that stop the poller. Mirrors
/// `jobs_dao.TERMINAL_JOB_STATUSES = ("done", "failed", "canceled")`.
fn is_terminal_job_status(json: &str) -> bool {
    // Cheap substring check on the serialized status; the engine owns the vocabulary.
    json.contains("\"status\":\"done\"")
        || json.contains("\"status\":\"failed\"")
        || json.contains("\"status\":\"canceled\"")
}

/// Start polling `GET /jobs/{id}` every 500 ms, emitting `engine://job-progress` with the raw
/// `JobView` JSON, until a terminal status is observed (done/failed/canceled) or the engine
/// becomes unreachable (surfaced as a synthetic `failed` payload so the UI never hangs).
pub fn start_job_poll<R: Runtime>(app: AppHandle<R>, job_id: String) {
    tauri::async_runtime::spawn(async move {
        loop {
            let poll = {
                let st = app.state::<SupervisorState>();
                engine_request(&st, "GET", &format!("/jobs/{job_id}"), None)
            };
            match poll {
                Ok(body) => {
                    let _ = app.emit(JOB_PROGRESS_EVENT, body.clone());
                    if is_terminal_job_status(&body) {
                        break;
                    }
                }
                Err(err) => {
                    // Engine unreachable mid-job: surface a failed payload and stop so the UI
                    // never hangs on a dead poll. Build with serde_json so the error message is
                    // always escaped into valid JSON (backslashes, control chars, quotes).
                    let payload = serde_json::json!({
                        "id": job_id,
                        "status": "failed",
                        "error": err.message,
                    })
                    .to_string();
                    let _ = app.emit(JOB_PROGRESS_EVENT, payload);
                    break;
                }
            }
            tokio::time::sleep(JOB_POLL_INTERVAL).await;
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;
    use std::net::TcpStream;

    #[test]
    fn free_loopback_port_returns_a_usable_port() {
        let port = free_loopback_port().expect("should reserve a port");
        assert_ne!(port, 0, "port must be non-zero");

        // The port is released, so we can bind it again right away.
        let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port))
            .expect("released port should be bindable");
        let local = listener.local_addr().expect("addr");
        assert_eq!(local.port(), port);

        // And it is reachable on loopback while bound.
        let connect = TcpStream::connect(local);
        assert!(connect.is_ok(), "loopback port should accept connections");
    }

    #[test]
    fn free_loopback_port_varies() {
        // Not guaranteed unique, but the OS should hand out distinct ports for
        // simultaneously-held listeners.
        let a = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0)).unwrap();
        let b = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0)).unwrap();
        assert_ne!(
            a.local_addr().unwrap().port(),
            b.local_addr().unwrap().port()
        );
    }

    #[test]
    fn token_is_256_bit_hex() {
        let token = generate_token();
        // 32 bytes => 64 hex chars.
        assert_eq!(token.len(), 64, "token must be 64 hex chars (256 bits)");
        assert!(
            token
                .chars()
                .all(|c| c.is_ascii_hexdigit() && !c.is_uppercase()),
            "token must be lowercase hex"
        );
    }

    #[test]
    fn token_is_unique_across_calls() {
        let mut seen = HashSet::new();
        for _ in 0..1000 {
            assert!(seen.insert(generate_token()), "tokens must be unique");
        }
    }

    #[test]
    fn backoff_increases_and_caps() {
        let mut backoff =
            BackoffSchedule::new(Duration::from_millis(100), Duration::from_millis(800), 2);
        let delays: Vec<Duration> = (0..6).map(|_| backoff.next_delay()).collect();

        assert_eq!(delays[0], Duration::from_millis(100));
        assert_eq!(delays[1], Duration::from_millis(200));
        assert_eq!(delays[2], Duration::from_millis(400));
        // Capped at 800ms thereafter.
        assert_eq!(delays[3], Duration::from_millis(800));
        assert_eq!(delays[4], Duration::from_millis(800));
        assert_eq!(delays[5], Duration::from_millis(800));

        // Each step is non-decreasing.
        for pair in delays.windows(2) {
            assert!(pair[1] >= pair[0], "backoff must be non-decreasing");
        }
    }

    #[test]
    fn backoff_resets() {
        let mut backoff =
            BackoffSchedule::new(Duration::from_millis(100), Duration::from_secs(10), 2);
        let _ = backoff.next_delay();
        let _ = backoff.next_delay();
        backoff.reset();
        assert_eq!(backoff.current_delay(), Duration::from_millis(100));
    }

    #[test]
    fn engine_status_serializes_camel_case() {
        let status = EngineStatus::new(EngineState::Healthy, Some(1234), None);
        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"state\":\"healthy\""));
        assert!(json.contains("\"port\":1234"));
        // `detail: None` is skipped.
        assert!(!json.contains("detail"));
    }

    #[test]
    fn engine_request_not_ready_without_port() {
        let state = SupervisorState::default();
        state.set_token("deadbeef");
        // No port set -> not ready.
        let err = engine_request(&state, "GET", "/hardware", None).unwrap_err();
        assert_eq!(err.kind, "engineNotReady");
    }

    #[test]
    fn engine_request_not_ready_without_token() {
        let state = SupervisorState::default();
        state.set_port(Some(12345));
        // Port but no token -> still not ready (token must be present).
        let err = engine_request(&state, "GET", "/hardware", None).unwrap_err();
        assert_eq!(err.kind, "engineNotReady");
    }

    #[test]
    fn engine_request_reaches_stub_with_bearer() {
        use std::io::{Read, Write};
        use std::net::TcpListener;

        // A one-shot stub server that records the request line + Authorization header.
        let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let handle = std::thread::spawn(move || {
            let (mut sock, _) = listener.accept().unwrap();
            let mut buf = [0u8; 2048];
            let n = sock.read(&mut buf).unwrap();
            let req = String::from_utf8_lossy(&buf[..n]).to_string();
            let body = "{\"ok\":true}";
            let resp = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: application/json\r\n\r\n{}",
                body.len(),
                body
            );
            sock.write_all(resp.as_bytes()).unwrap();
            req
        });

        let state = SupervisorState::default();
        state.set_token("secret-token");
        state.set_port(Some(port));
        let out = engine_request(&state, "GET", "/hardware", None).unwrap();
        assert!(out.contains("\"ok\":true"));

        let req = handle.join().unwrap();
        assert!(req.starts_with("GET /hardware "));
        assert!(req.contains("Authorization: Bearer secret-token"));
    }

    #[test]
    fn terminal_model_state_detection() {
        assert!(is_terminal_model_state("{\"state\":\"ready\"}"));
        assert!(is_terminal_model_state("{\"state\":\"corrupt\"}"));
        assert!(is_terminal_model_state("{\"state\":\"error\"}"));
        assert!(!is_terminal_model_state("{\"state\":\"downloading\"}"));
        assert!(!is_terminal_model_state("{\"state\":\"verifying\"}"));
    }

    #[test]
    fn terminal_job_status_detection() {
        assert!(is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"done\"}"
        ));
        assert!(is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"failed\"}"
        ));
        assert!(is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"canceled\"}"
        ));
        assert!(!is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"queued\"}"
        ));
        assert!(!is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"running\"}"
        ));
        assert!(!is_terminal_job_status(
            "{\"id\":\"j1\",\"status\":\"paused\"}"
        ));
    }

    #[test]
    fn download_registry_dedupes() {
        let state = SupervisorState::default();
        assert!(state.begin_download("pix2tex"));
        assert!(!state.begin_download("pix2tex"));
        state.end_download("pix2tex");
        assert!(state.begin_download("pix2tex"));
    }
}
