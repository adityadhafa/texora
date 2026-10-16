//! Texora desktop shell entrypoint.
//!
//! Tauri v2 shell for Texora. This layer is a secure client + process manager
//! only — business logic stays out of Rust by design. It registers the shell
//! plugin, starts the engine sidecar supervisor, and exposes a single
//! `engine_status` command plus `engine://status` events that the typed TS
//! client (`src/engineClient.ts`) consumes.

mod supervisor;

use supervisor::{EngineStatus, SupervisorState};

/// Return the current engine status snapshot for the UI.
#[tauri::command]
fn engine_status(state: tauri::State<'_, SupervisorState>) -> EngineStatus {
    state.snapshot()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SupervisorState::default())
        .invoke_handler(tauri::generate_handler![engine_status])
        .setup(|app| {
            supervisor::start(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Texora desktop application");
}
