//! SoulForge desktop shell.
//!
//! Two windows over the same studio page (served by `studio/server.py`):
//! * `main`    — the full companion app at /live
//! * `overlay` — /live?transparent=1&hud=0: transparent, undecorated,
//!               always-on-top, draggable; the character floats on the desktop.
//!
//! The four things a transparent overlay needs (learned from aikeya):
//! 1. window `transparent: true`, `decorations: false`, `shadow: false`
//! 2. `app.macOSPrivateApi: true` (macOS refuses transparent webviews otherwise)
//! 3. the page paints nothing behind the canvas (live.js `host.transparent`)
//! 4. no post-processing composer in transparent mode (it swallows alpha)

use tauri::Manager;

#[tauri::command]
fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("overlay") {
        w.show().map_err(|e| e.to_string())?;
        w.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("overlay") {
        w.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn toggle_overlay(app: tauri::AppHandle) -> Result<bool, String> {
    let Some(w) = app.get_webview_window("overlay") else {
        return Err("overlay window not found".into());
    };
    let visible = w.is_visible().map_err(|e| e.to_string())?;
    if visible {
        w.hide().map_err(|e| e.to_string())?;
        Ok(false)
    } else {
        w.show().map_err(|e| e.to_string())?;
        w.set_focus().map_err(|e| e.to_string())?;
        Ok(true)
    }
}

/// Window drag from the page (the overlay has no title bar).
#[tauri::command]
fn start_drag(window: tauri::WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            show_overlay,
            hide_overlay,
            toggle_overlay,
            start_drag
        ])
        .setup(|app| {
            // Ctrl/Cmd+Shift+U toggles the floating companion from anywhere.
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};
            let handle = app.handle().clone();
            let shortcut: Shortcut = "CmdOrCtrl+Shift+U".parse()?;
            app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, event| {
                if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                    let _ = toggle_overlay(handle.clone());
                }
            })?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running SoulForge desktop");
}
