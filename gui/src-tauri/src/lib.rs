use std::path::{Path, PathBuf};

use tauri::{AppHandle, Runtime};
use tauri_plugin_fs::FsExt;

/// Directory whose contents the app needs in order to act on `path`.
///
/// A rename touches three things in one folder: the source file, its rename
/// target, and the sibling `.autorename-log.json`. Granting the containing
/// directory covers all three; granting the file alone would not.
fn access_root(path: &Path) -> Option<PathBuf> {
    if path.is_dir() {
        Some(path.to_path_buf())
    } else {
        path.parent().map(Path::to_path_buf)
    }
}

/// Grant the fs plugin access to paths the user explicitly selected.
///
/// The static `fs:scope` is empty, so this is the only way a path becomes
/// readable or writable — every caller is a dialog pick or a drag-drop.
/// Directories are granted non-recursively, matching `expandFolder`, which
/// does not descend either.
#[tauri::command]
fn grant_path_access<R: Runtime>(app: AppHandle<R>, paths: Vec<String>) -> Result<(), String> {
    let scope = app.fs_scope();
    for raw in paths {
        let path = PathBuf::from(&raw);
        let root = access_root(&path)
            .ok_or_else(|| format!("cannot resolve a parent directory for {raw}"))?;
        scope
            .allow_directory(&root, false)
            .map_err(|e| format!("failed to grant access to {}: {e}", root.display()))?;
    }
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![grant_path_access])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
