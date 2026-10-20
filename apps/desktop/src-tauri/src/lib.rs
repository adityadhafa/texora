//! Texora desktop shell entrypoint.
//!
//! Tauri v2 shell for Texora. This layer is a secure client + process manager only —
//! business logic stays out of Rust by design. It registers the shell + global-shortcut
//! plugins, starts the engine sidecar supervisor, registers the snip hotkey, and exposes
//! the `engine_status` command plus thin authenticated proxy commands
//! (`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`, plus the
//! PDF→Markdown job commands `job_create`/`job_get`/`job_cancel`/`job_export` and the local
//! `save_text` write) that the typed TS client (`src/engineClient.ts`) consumes. The engine
//! port + bearer token stay in Rust and never cross into the webview.

mod snip;
mod supervisor;

use serde_json::json;
use supervisor::{engine_request, EngineStatus, ProxyError, SupervisorState};
use tauri::{AppHandle, State};

/// URL-encode the handful of characters that could break a query string. Job ids and the
/// export format are engine-controlled, but encoding keeps the thin client defensive.
fn encode_component(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for b in value.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Return the current engine status snapshot for the UI.
#[tauri::command]
fn engine_status(state: State<'_, SupervisorState>) -> EngineStatus {
    state.snapshot()
}

/// Proxy `POST /recognize/snip` with the bearer token (kept in Rust).
#[tauri::command]
fn recognize_snip(
    state: State<'_, SupervisorState>,
    image_base64: String,
    is_display: bool,
) -> Result<String, ProxyError> {
    let body = json!({ "image_base64": image_base64, "is_display": is_display }).to_string();
    engine_request(&state, "POST", "/recognize/snip", Some(&body))
}

/// Proxy `GET /hardware`.
#[tauri::command]
fn get_hardware(state: State<'_, SupervisorState>) -> Result<String, ProxyError> {
    engine_request(&state, "GET", "/hardware", None)
}

/// Proxy `POST /hardware/device`.
#[tauri::command]
fn set_device(state: State<'_, SupervisorState>, device: String) -> Result<String, ProxyError> {
    let body = json!({ "device": device }).to_string();
    engine_request(&state, "POST", "/hardware/device", Some(&body))
}

/// Proxy `GET /models/{id}`.
#[tauri::command]
fn model_status(state: State<'_, SupervisorState>, id: String) -> Result<String, ProxyError> {
    engine_request(&state, "GET", &format!("/models/{id}"), None)
}

/// Trigger `POST /models/{id}/download` (returns immediately) and start the progress poller.
#[tauri::command]
fn model_download(
    app: AppHandle,
    state: State<'_, SupervisorState>,
    id: String,
) -> Result<String, ProxyError> {
    let initial = engine_request(&state, "POST", &format!("/models/{id}/download"), None)?;
    supervisor::start_model_poll(app, id);
    Ok(initial)
}

/// Proxy `POST /jobs` (create a PDF→Markdown conversion job) and start the progress poller.
///
/// `options_json` is the serialized engine `JobOptions` object (e.g. `{"formats":["md"]}`),
/// built in the typed TS client so Rust stays free of business logic. The new job id is parsed
/// out of the returned `JobView` to kick off the `engine://job-progress` poll.
#[tauri::command]
fn job_create(
    app: AppHandle,
    state: State<'_, SupervisorState>,
    path: String,
    options_json: String,
    priority: i64,
) -> Result<String, ProxyError> {
    let options: serde_json::Value = serde_json::from_str(&options_json)
        .map_err(|e| ProxyError::from_message("badRequest", format!("invalid options: {e}")))?;
    let body = json!({ "path": path, "options": options, "priority": priority }).to_string();
    let created = engine_request(&state, "POST", "/jobs", Some(&body))?;
    if let Ok(serde_json::Value::Object(obj)) = serde_json::from_str::<serde_json::Value>(&created)
    {
        if let Some(serde_json::Value::String(id)) = obj.get("id") {
            supervisor::start_job_poll(app, id.clone());
        }
    }
    Ok(created)
}

/// Proxy `GET /jobs/{id}`.
#[tauri::command]
fn job_get(state: State<'_, SupervisorState>, id: String) -> Result<String, ProxyError> {
    engine_request(
        &state,
        "GET",
        &format!("/jobs/{}", encode_component(&id)),
        None,
    )
}

/// Proxy `POST /jobs/{id}:cancel`.
#[tauri::command]
fn job_cancel(state: State<'_, SupervisorState>, id: String) -> Result<String, ProxyError> {
    engine_request(
        &state,
        "POST",
        &format!("/jobs/{}:cancel", encode_component(&id)),
        Some("{}"),
    )
}

/// Proxy `GET /jobs/{id}/export?format={format}` (returns the raw export body).
#[tauri::command]
fn job_export(
    state: State<'_, SupervisorState>,
    id: String,
    format: String,
) -> Result<String, ProxyError> {
    engine_request(
        &state,
        "GET",
        &format!(
            "/jobs/{}/export?format={}",
            encode_component(&id),
            encode_component(&format)
        ),
        None,
    )
}

/// Write a UTF-8 text file to disk (used to save exported Markdown to a user-chosen path).
///
/// This is a thin local filesystem write — no engine involvement — so the Save-.md dialog can
/// persist the exported Markdown without adding a second Tauri plugin.
#[tauri::command]
fn save_text(path: String, contents: String) -> Result<(), ProxyError> {
    std::fs::write(&path, contents)
        .map_err(|e| ProxyError::from_message("ioError", format!("could not save file: {e}")))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(SupervisorState::default())
        .invoke_handler(tauri::generate_handler![
            engine_status,
            recognize_snip,
            get_hardware,
            set_device,
            model_status,
            model_download,
            job_create,
            job_get,
            job_cancel,
            job_export,
            save_text
        ])
        .setup(|app| {
            supervisor::start(app.handle().clone());
            if let Err(err) = snip::register_shortcut(app.handle()) {
                // A failed hotkey registration must not prevent the app from starting.
                eprintln!("snip shortcut registration failed: {err}");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Texora desktop application");
}
