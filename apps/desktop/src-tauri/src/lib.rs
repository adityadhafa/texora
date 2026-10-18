//! Texora desktop shell entrypoint.
//!
//! Tauri v2 shell for Texora. This layer is a secure client + process manager only —
//! business logic stays out of Rust by design. It registers the shell + global-shortcut
//! plugins, starts the engine sidecar supervisor, registers the snip hotkey, and exposes
//! the `engine_status` command plus thin authenticated proxy commands
//! (`recognize_snip`/`get_hardware`/`set_device`/`model_status`/`model_download`) that the
//! typed TS client (`src/engineClient.ts`) consumes. The engine port + bearer token stay in
//! Rust and never cross into the webview.

mod snip;
mod supervisor;

use serde_json::json;
use supervisor::{engine_request, EngineStatus, ProxyError, SupervisorState};
use tauri::{AppHandle, State};

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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(SupervisorState::default())
        .invoke_handler(tauri::generate_handler![
            engine_status,
            recognize_snip,
            get_hardware,
            set_device,
            model_status,
            model_download
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
