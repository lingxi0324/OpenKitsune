use crate::prelude::*;

#[tauri::command]
pub(crate) fn get_current_workspace_id() -> Result<Option<String>, String> {
    let state = read_state_file();
    Ok(state.current_workspace_id)
}

pub(crate) fn workspace_file_path(workspace_id: &str, relative: &str) -> Result<PathBuf, String> {
    let base = workspace_dir(workspace_id);
    let rel = Path::new(relative);
    if rel.is_absolute() {
        return Err("relative path must not be absolute".into());
    }
    // Prevent path traversal: use Path::components to reliably detect ".." segments
    // (more robust than string matching, handles edge cases like "foo/..bar" correctly).
    use std::path::Component;
    if rel.components().any(|c| matches!(c, Component::ParentDir)) {
        return Err("relative path must not contain parent directory references (..)".into());
    }
    Ok(base.join(rel))
}

#[tauri::command]
pub(crate) fn workspace_read_file(
    workspace_id: String,
    relative_path: String,
) -> Result<String, String> {
    let path = workspace_file_path(&workspace_id, &relative_path)?;
    fs::read_to_string(&path).map_err(|e| format!("read failed: {e}"))
}

#[tauri::command]
pub(crate) fn workspace_write_file(
    workspace_id: String,
    relative_path: String,
    content: String,
) -> Result<(), String> {
    let path = workspace_file_path(&workspace_id, &relative_path)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("create parent dir failed: {e}"))?;
    }
    fs::write(&path, content).map_err(|e| format!("write failed: {e}"))
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct EnvEntry {
    key: String,
    value: String,
}

pub(crate) fn update_env_content(existing: &str, entries: &[EnvEntry]) -> String {
    let mut updates = std::collections::BTreeMap::new();
    let mut deletes = std::collections::BTreeSet::new();
    for e in entries {
        if e.key.trim().is_empty() {
            continue;
        }
        let k = e.key.trim().to_string();
        if e.value.trim().is_empty() {
            // 约定：空值表示删除该键（可选字段不填就不落盘）
            deletes.insert(k);
        } else {
            updates.insert(k, e.value.clone());
        }
    }
    if updates.is_empty() && deletes.is_empty() {
        return existing.to_string();
    }

    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();

    for line in existing.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with('#') || !trimmed.contains('=') {
            out.push(line.to_string());
            continue;
        }
        let (k, _v) = trimmed.split_once('=').unwrap_or((trimmed, ""));
        let key = k.trim();
        if deletes.contains(key) {
            // 删除该键：跳过该行
            seen.insert(key.to_string());
            continue;
        }
        if let Some(new_val) = updates.get(key) {
            out.push(format!("{key}={new_val}"));
            seen.insert(key.to_string());
        } else {
            out.push(line.to_string());
        }
    }

    // append missing keys
    for (k, v) in updates {
        if !seen.contains(&k) {
            out.push(format!("{k}={v}"));
        }
    }

    // ensure trailing newline
    let mut s = out.join("\n");
    if !s.ends_with('\n') {
        s.push('\n');
    }
    s
}

#[tauri::command]
pub(crate) fn workspace_update_env(
    workspace_id: String,
    entries: Vec<EnvEntry>,
) -> Result<(), String> {
    let dir = workspace_dir(&workspace_id);
    ensure_workspace_scaffold(&dir)?;
    let env_path = dir.join(".env");
    let existing = read_text_lossy(&env_path);
    let updated = update_env_content(&existing, &entries);
    fs::write(&env_path, updated).map_err(|e| format!("write .env failed: {e}"))
}

/// Read a text file as UTF-8; fall back to lossy conversion for non-UTF-8 files
/// (e.g. .env with GBK-encoded Chinese comments on Windows).
pub(crate) fn read_text_lossy(path: &Path) -> String {
    match fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(_) => {
            // Non-UTF-8 bytes — decode lossily so existing content is preserved.
            fs::read(path)
                .map(|bytes| String::from_utf8_lossy(&bytes).into_owned())
                .unwrap_or_default()
        }
    }
}

// ── Workspace backup commands ────────────────────────────────────────

#[tauri::command]
pub(crate) fn export_workspace_backup(
    workspace_id: String,
    output_dir: String,
    include_userdata: bool,
    include_media: bool,
    api_port: u16,
) -> Result<serde_json::Value, String> {
    // Try the Python backend API first (preferred: consistent logic)
    let url = format!("http://127.0.0.1:{}/api/workspace/export", api_port);
    let body = serde_json::json!({
        "output_dir": output_dir,
        "include_userdata": include_userdata,
        "include_media": include_media,
    });
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(300))
        .no_proxy()
        .build()
        .map_err(|e| format!("http client error: {e}"))?;
    let resp = client.post(&url).json(&body).send();
    match resp {
        Ok(r) if r.status().is_success() => {
            let val: serde_json::Value = r.json().map_err(|e| format!("parse response: {e}"))?;
            Ok(val)
        }
        Ok(r) => {
            let status = r.status();
            let text = r.text().unwrap_or_default();
            Err(format!("Backend returned {status}: {text}"))
        }
        Err(_) => {
            // Fallback: create a basic zip using Rust zip crate
            export_workspace_backup_native(
                &workspace_id,
                &output_dir,
                include_userdata,
                include_media,
            )
        }
    }
}

pub(crate) fn export_workspace_backup_native(
    workspace_id: &str,
    output_dir: &str,
    include_userdata: bool,
    include_media: bool,
) -> Result<serde_json::Value, String> {
    use std::io::Read as _;

    let ws = workspace_dir(workspace_id);
    if !ws.exists() {
        return Err("Workspace directory not found".into());
    }
    let out = PathBuf::from(output_dir);
    fs::create_dir_all(&out).map_err(|e| format!("create output dir: {e}"))?;

    let ts = chrono_like_timestamp();
    let zip_name = format!("openkitsune-backup-{workspace_id}-{ts}.zip");
    let zip_path = out.join(&zip_name);

    let file = fs::File::create(&zip_path).map_err(|e| format!("create zip: {e}"))?;
    let mut zw = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    let always_dirs = [
        "identity",
        "data/agents",
        "data/sessions",
        "data/scheduler",
        "data/mcp",
        "data/telegram",
        "skills",
        "mcps",
    ];
    let always_files = [
        ".env",
        "data/llm_endpoints.json",
        "data/skills.json",
        "data/disabled_views.json",
        "data/runtime_state.json",
        "data/proactive_feedback.json",
        "data/sub_agent_states.json",
    ];
    let userdata_dirs = [
        "data/memory",
        "data/retrospects",
        "data/plans",
        "data/docs",
        "data/reports",
        "data/research",
    ];
    let userdata_files = ["data/agent.db"];
    let media_dirs = [
        "data/generated_images",
        "data/sticker",
        "data/media",
        "data/output",
        "data/screenshots",
    ];
    let exclude_dirs = [
        "logs",
        "data/llm_debug",
        "data/delegation_logs",
        "data/traces",
        "data/react_traces",
        "data/temp",
        "data/tool_overflow",
        "data/selfcheck",
        "data/openkitsune_docs",
        "identity/runtime",
        "node_modules",
        "Lib",
        "__pycache__",
    ];

    let mut file_count: u64 = 0;

    for entry in walkdir(&ws) {
        let full = entry.path();
        if !full.is_file() {
            continue;
        }
        let rel = match full.strip_prefix(&ws) {
            Ok(r) => r.to_string_lossy().replace('\\', "/"),
            Err(_) => continue,
        };

        // Exclude
        if exclude_dirs
            .iter()
            .any(|d| rel == *d || rel.starts_with(&format!("{d}/")))
        {
            continue;
        }
        if rel == "data/backend.heartbeat"
            || rel == "data/backend.manual-stop"
            || rel == "package.json"
            || rel == "package-lock.json"
        {
            continue;
        }

        let included = always_files.contains(&rel.as_str())
            || always_dirs
                .iter()
                .any(|d| rel == *d || rel.starts_with(&format!("{d}/")))
            || (include_userdata
                && (userdata_files.contains(&rel.as_str())
                    || userdata_dirs
                        .iter()
                        .any(|d| rel == *d || rel.starts_with(&format!("{d}/")))))
            || (include_media
                && media_dirs
                    .iter()
                    .any(|d| rel == *d || rel.starts_with(&format!("{d}/"))));

        if !included {
            continue;
        }

        if let Ok(mut f) = fs::File::open(full) {
            let _ = zw.start_file(&rel, options);
            let mut buf = Vec::new();
            if f.read_to_end(&mut buf).is_ok() {
                let _ = zw.write_all(&buf);
                file_count += 1;
            }
        }
    }

    // Write manifest
    let manifest = serde_json::json!({
        "format_version": 1,
        "created_at": chrono_like_timestamp(),
        "workspace_id": workspace_id,
        "include_userdata": include_userdata,
        "include_media": include_media,
        "file_count": file_count,
    });
    let _ = zw.start_file("manifest.json", options);
    let _ = zw.write_all(
        serde_json::to_string_pretty(&manifest)
            .unwrap_or_default()
            .as_bytes(),
    );
    zw.finish().map_err(|e| format!("finalize zip: {e}"))?;

    let size = fs::metadata(&zip_path).map(|m| m.len()).unwrap_or(0);
    Ok(serde_json::json!({
        "status": "ok",
        "path": zip_path.to_string_lossy(),
        "filename": zip_name,
        "size_bytes": size,
    }))
}

#[tauri::command]
pub(crate) fn import_workspace_backup(
    workspace_id: String,
    zip_path: String,
    api_port: u16,
) -> Result<serde_json::Value, String> {
    let url = format!("http://127.0.0.1:{}/api/workspace/import", api_port);
    let body = serde_json::json!({ "zip_path": zip_path });
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(300))
        .no_proxy()
        .build()
        .map_err(|e| format!("http client error: {e}"))?;
    let resp = client.post(&url).json(&body).send();
    match resp {
        Ok(r) if r.status().is_success() => {
            let val: serde_json::Value = r.json().map_err(|e| format!("parse: {e}"))?;
            Ok(val)
        }
        Ok(r) => {
            let status = r.status();
            let text = r.text().unwrap_or_default();
            Err(format!("Backend returned {status}: {text}"))
        }
        Err(_) => {
            // Fallback: native extraction
            import_workspace_backup_native(&workspace_id, &zip_path)
        }
    }
}

pub(crate) fn import_workspace_backup_native(
    workspace_id: &str,
    zip_path: &str,
) -> Result<serde_json::Value, String> {
    use std::io::Read as _;

    let zp = PathBuf::from(zip_path);
    if !zp.exists() {
        return Err("Backup file not found".into());
    }
    let ws = workspace_dir(workspace_id);
    fs::create_dir_all(&ws).map_err(|e| format!("create workspace dir: {e}"))?;

    let file = fs::File::open(&zp).map_err(|e| format!("open zip: {e}"))?;
    let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("read zip: {e}"))?;

    let mut restored = 0u64;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| format!("zip entry: {e}"))?;
        let name = entry.name().to_string();
        if name == "manifest.json" {
            continue;
        }

        // Safety: reject path traversal
        let norm = PathBuf::from(&name);
        if norm
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            continue;
        }

        let target = ws.join(&name);
        if entry.is_dir() {
            let _ = fs::create_dir_all(&target);
            continue;
        }
        if let Some(parent) = target.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let mut buf = Vec::new();
        if entry.read_to_end(&mut buf).is_ok() {
            if fs::write(&target, &buf).is_ok() {
                restored += 1;
            }
        }
    }

    Ok(serde_json::json!({
        "status": "ok",
        "restored_count": restored,
    }))
}

/// Simple recursive file walker (no external crate dependency needed)
pub(crate) fn walkdir(dir: &Path) -> Vec<walkdir_entry::Entry> {
    let mut result = Vec::new();
    walkdir_recurse(dir, &mut result);
    result
}

pub(crate) fn walkdir_recurse(dir: &Path, out: &mut Vec<walkdir_entry::Entry>) {
    let Ok(rd) = fs::read_dir(dir) else { return };
    for entry in rd.flatten() {
        let path = entry.path();
        out.push(walkdir_entry::Entry { path: path.clone() });
        if path.is_dir() {
            walkdir_recurse(&path, out);
        }
    }
}

mod walkdir_entry {
    use std::path::{Path, PathBuf};
    pub struct Entry {
        pub path: PathBuf,
    }
    impl Entry {
        pub fn path(&self) -> &Path {
            &self.path
        }
    }
}

pub(crate) fn chrono_like_timestamp() -> String {
    use std::time::SystemTime;
    let now = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .unwrap_or_default();
    // Convert to a simple YYYYMMDD_HHMMSS using rough calculation
    let secs = now.as_secs();
    // Use a simple approach: format via the system's time
    let dt = time_from_epoch(secs);
    format!(
        "{:04}{:02}{:02}_{:02}{:02}{:02}",
        dt.0, dt.1, dt.2, dt.3, dt.4, dt.5
    )
}

pub(crate) fn time_from_epoch(epoch_secs: u64) -> (u32, u32, u32, u32, u32, u32) {
    // Simple epoch-to-datetime conversion (UTC-based, good enough for filenames)
    const SECS_PER_DAY: u64 = 86400;

    let total_days = epoch_secs / SECS_PER_DAY;
    let time_of_day = epoch_secs % SECS_PER_DAY;
    let hour = (time_of_day / 3600) as u32;
    let minute = ((time_of_day % 3600) / 60) as u32;
    let second = (time_of_day % 60) as u32;

    // Calculate year/month/day from total_days since 1970-01-01
    let mut year = 1970u32;
    let mut remaining = total_days;
    loop {
        let days_in_year = if is_leap(year) { 366 } else { 365 };
        if remaining < days_in_year {
            break;
        }
        remaining -= days_in_year;
        year += 1;
    }
    let days_in_months: [u64; 12] = if is_leap(year) {
        [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    } else {
        [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    };
    let mut month = 1u32;
    for &dm in &days_in_months {
        if remaining < dm {
            break;
        }
        remaining -= dm;
        month += 1;
    }
    let day = remaining as u32 + 1;

    (year, month, day, hour, minute, second)
}

pub(crate) fn is_leap(y: u32) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}
