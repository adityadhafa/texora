//! Snip tool: global hotkey + screen-region capture (shell/OS concern, Rust side).
//!
//! The capture itself is an OS concern and correctly lives in Rust; recognition stays in
//! the engine. The flow is: Ctrl+Shift+M (global shortcut) -> capture the primary monitor
//! via `xcap` -> PNG-encode -> base64 -> emit `engine://snip-captured`. The frontend picks
//! that up through the typed `engineClient` and calls `recognizeSnip`, which proxies to the
//! engine `POST /recognize/snip`. The token/port never reach the webview.
//!
//! Live hotkey firing + on-screen region selection are host/interactive and are confirmed
//! manually (documented pending in docs/m2-verification.md). The pure PNG-encode helper and
//! the shortcut registration are unit-tested.

use base64::Engine as _;
use tauri::{AppHandle, Emitter, Runtime};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut};
use xcap::image::{ImageFormat, RgbaImage};

/// Event name carrying the base64 PNG of a captured snip.
pub const SNIP_CAPTURED_EVENT: &str = "engine://snip-captured";

/// Default snip hotkey: Ctrl+Shift+M.
pub fn default_snip_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM)
}

/// PNG-encode an RGBA buffer and base64 it. Pure + unit-testable (no OS capture).
pub fn encode_rgba_to_png_base64(image: &RgbaImage) -> Result<String, String> {
    let mut buf: Vec<u8> = Vec::new();
    {
        let mut cursor = std::io::Cursor::new(&mut buf);
        image
            .write_to(&mut cursor, ImageFormat::Png)
            .map_err(|e| format!("png encode failed: {e}"))?;
    }
    Ok(base64::engine::general_purpose::STANDARD.encode(&buf))
}

/// Capture the primary monitor, PNG-encode it, and return the base64 string.
///
/// M2 captures the whole primary monitor; the on-screen region selection overlay is a
/// host/interactive follow-up. This keeps the capture path real (no mock) while the
/// region-select UX is confirmed manually.
pub fn capture_primary_png_base64() -> Result<String, String> {
    let monitors = xcap::Monitor::all().map_err(|e| format!("monitor enumeration failed: {e}"))?;
    let monitor = monitors
        .into_iter()
        .next()
        .ok_or_else(|| "no monitors available".to_string())?;
    let image = monitor
        .capture_image()
        .map_err(|e| format!("capture failed: {e}"))?;
    encode_rgba_to_png_base64(&image)
}

/// Register the global snip shortcut. On trigger it captures + emits `engine://snip-captured`.
pub fn register_shortcut<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;

    let shortcut = default_snip_shortcut();
    let handle = app.clone();
    app.global_shortcut()
        .on_shortcut(shortcut, move |_app, _sc, event| {
            // Only act on key press (not release) to avoid double-firing.
            if event.state() != tauri_plugin_global_shortcut::ShortcutState::Pressed {
                return;
            }
            match capture_primary_png_base64() {
                Ok(b64) => {
                    let _ = handle.emit(SNIP_CAPTURED_EVENT, b64);
                }
                Err(err) => {
                    let _ = handle.emit(SNIP_CAPTURED_EVENT, format!("ERROR:{err}"));
                }
            }
        })
        .map_err(|e| format!("failed to register snip shortcut: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_shortcut_is_ctrl_shift_m() {
        let sc = default_snip_shortcut();
        assert_eq!(sc.key, Code::KeyM);
        let mods = sc.mods;
        assert!(mods.contains(Modifiers::CONTROL));
        assert!(mods.contains(Modifiers::SHIFT));
    }

    #[test]
    fn encodes_known_buffer_to_png_base64() {
        // A tiny 2x2 RGBA image encodes to a non-empty base64 PNG whose decoded bytes carry
        // the PNG magic signature.
        let mut img = RgbaImage::new(2, 2);
        for p in img.pixels_mut() {
            *p = xcap::image::Rgba([10, 20, 30, 255]);
        }
        let b64 = encode_rgba_to_png_base64(&img).expect("encode");
        assert!(!b64.is_empty());
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(b64)
            .expect("valid base64");
        // PNG signature: 89 50 4E 47 0D 0A 1A 0A
        assert_eq!(
            &bytes[..8],
            &[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]
        );
    }
}
