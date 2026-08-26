fn main() {
    // App commands only get ACL permissions (allow-<command>) when declared here;
    // pages served from the remote studio origin need them listed in a capability.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&[
            "show_overlay",
            "hide_overlay",
            "toggle_overlay",
            "start_drag",
            "start_native_mic",
            "stop_native_mic",
        ])),
    )
    .expect("failed to run tauri-build");
}
