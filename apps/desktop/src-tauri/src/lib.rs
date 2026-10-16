//! Texora desktop shell entrypoint.
//!
//! This is the minimal Tauri v2 skeleton. The sidecar supervisor, secure IPC,
//! and typed engine client are added in task 1.4; for now this only builds the
//! default Tauri app and opens the Home window. Business logic stays out of
//! Rust by design — this layer is a secure client + process manager.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Texora desktop application");
}
