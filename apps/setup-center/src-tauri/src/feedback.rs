use crate::prelude::*;

/// Export diagnostic bundle (logs, llm_debug, system info) as a zip.
/// If `dest_path` is given (from a save dialog), write there; otherwise fall back to Downloads.
#[tauri::command]
pub(crate) fn export_diagnostic_bundle(
    workspace_id: String,
    system_info_json: Option<String>,
    dest_path: Option<String>,
) -> Result<String, String> {
    let ws_dir = workspace_dir(&workspace_id);
    let logs_dir = ws_dir.join("logs");
    let llm_debug_dir = ws_dir.join("data").join("llm_debug");

    let dest = if let Some(p) = dest_path {
        PathBuf::from(p)
    } else {
        let downloads_dir = dirs_next::download_dir()
            .or_else(|| dirs_next::home_dir().map(|h| h.join("Downloads")))
            .ok_or_else(|| "Cannot determine Downloads directory".to_string())?;
        fs::create_dir_all(&downloads_dir)
            .map_err(|e| format!("Cannot create Downloads dir: {e}"))?;
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        downloads_dir.join(format!("openkitsune-diagnostic-{ts}.zip"))
    };

    if let Some(parent) = dest.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Cannot create directory: {e}"))?;
    }

    let file = fs::File::create(&dest).map_err(|e| format!("Failed to create zip file: {e}"))?;
    let mut zip_writer = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    fn collect_files(dir: &Path) -> Vec<PathBuf> {
        let mut result = Vec::new();
        if let Ok(entries) = fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    result.extend(collect_files(&path));
                } else {
                    result.push(path);
                }
            }
        }
        result
    }

    fn add_dir_to_zip(
        zip_writer: &mut zip::ZipWriter<fs::File>,
        dir: &Path,
        prefix: &str,
        options: zip::write::SimpleFileOptions,
    ) -> Result<(), String> {
        if !dir.exists() {
            return Ok(());
        }
        for file_path in collect_files(dir) {
            if let Ok(rel) = file_path.strip_prefix(dir) {
                let name = format!("{}/{}", prefix, rel.to_string_lossy().replace('\\', "/"));
                zip_writer
                    .start_file(&name, options)
                    .map_err(|e| format!("zip start error: {e}"))?;
                let data = fs::read(&file_path).unwrap_or_default();
                zip_writer
                    .write_all(&data)
                    .map_err(|e| format!("zip write error: {e}"))?;
            }
        }
        Ok(())
    }

    fn add_dir_to_zip_capped(
        zip_writer: &mut zip::ZipWriter<fs::File>,
        dir: &Path,
        prefix: &str,
        options: zip::write::SimpleFileOptions,
        max_bytes: u64,
    ) -> Result<(), String> {
        if !dir.exists() {
            return Ok(());
        }
        let mut files = collect_files(dir);
        files.sort_by(|a, b| {
            let ma = fs::metadata(a).and_then(|m| m.modified()).ok();
            let mb = fs::metadata(b).and_then(|m| m.modified()).ok();
            mb.cmp(&ma)
        });
        let mut total: u64 = 0;
        for file_path in files {
            let sz = fs::metadata(&file_path).map(|m| m.len()).unwrap_or(0);
            if total + sz > max_bytes {
                continue;
            }
            if let Ok(rel) = file_path.strip_prefix(dir) {
                let name = format!("{}/{}", prefix, rel.to_string_lossy().replace('\\', "/"));
                zip_writer
                    .start_file(&name, options)
                    .map_err(|e| format!("zip start error: {e}"))?;
                let data = fs::read(&file_path).unwrap_or_default();
                zip_writer
                    .write_all(&data)
                    .map_err(|e| format!("zip write error: {e}"))?;
                total += sz;
            }
        }
        Ok(())
    }

    fn add_file_to_zip(
        zip_writer: &mut zip::ZipWriter<fs::File>,
        path: &Path,
        zip_name: &str,
        options: zip::write::SimpleFileOptions,
    ) -> Result<(), String> {
        if !path.exists() || !path.is_file() {
            return Ok(());
        }
        zip_writer
            .start_file(zip_name, options)
            .map_err(|e| format!("zip start error: {e}"))?;
        let data = fs::read(path).unwrap_or_default();
        zip_writer
            .write_all(&data)
            .map_err(|e| format!("zip write error: {e}"))?;
        Ok(())
    }

    // -- Logs (workspace) --
    add_dir_to_zip(&mut zip_writer, &logs_dir, "logs", options)?;

    // -- LLM debug data --
    add_dir_to_zip_capped(
        &mut zip_writer,
        &llm_debug_dir,
        "llm_debug",
        options,
        10 * 1024 * 1024,
    )?;

    // -- Debug data directories (capped per-dir) --
    let data_dir = ws_dir.join("data");
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("delegation_logs"),
        "delegation_logs",
        options,
        2 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("react_traces"),
        "react_traces",
        options,
        5 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("traces"),
        "traces",
        options,
        2 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("orgs"),
        "orgs",
        options,
        2 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("tool_overflow"),
        "tool_overflow",
        options,
        2 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("failure_analysis"),
        "failure_analysis",
        options,
        1 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &data_dir.join("retrospects"),
        "retrospects",
        options,
        1 * 1024 * 1024,
    )?;

    // -- Small state files --
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("runtime_state.json"),
        "state/runtime_state.json",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("sub_agent_states.json"),
        "state/sub_agent_states.json",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("backend.heartbeat"),
        "state/backend.heartbeat",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("sessions").join("sessions.json"),
        "state/sessions.json",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("sessions").join("channel_registry.json"),
        "state/channel_registry.json",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("scheduler").join("tasks.json"),
        "state/scheduler_tasks.json",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &data_dir.join("scheduler").join("executions.json"),
        "state/scheduler_executions.json",
        options,
    )?;

    // -- Global logs (frontend.log, crash.log, onboarding) --
    let global_logs = setup_logs_dir();
    add_file_to_zip(
        &mut zip_writer,
        &global_logs.join("frontend.log"),
        "global_logs/frontend.log",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &global_logs.join("crash.log"),
        "global_logs/crash.log",
        options,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &global_logs.join("autostart.log"),
        "global_logs/autostart.log",
        options,
    )?;
    for entry in fs::read_dir(&global_logs).into_iter().flatten().flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with("onboarding-") && name_str.ends_with(".log") {
            add_file_to_zip(
                &mut zip_writer,
                &entry.path(),
                &format!("global_logs/{}", name_str),
                options,
            )?;
        }
    }

    // -- Runtime diagnostics (available even when backend is down) --
    add_file_to_zip(
        &mut zip_writer,
        &runtime_manifest_path(),
        "runtime/manifest.json",
        options,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &runtime_logs_dir(),
        "runtime/logs",
        options,
        5 * 1024 * 1024,
    )?;
    add_dir_to_zip_capped(
        &mut zip_writer,
        &runtime_root_dir().join("reports"),
        "runtime/reports",
        options,
        5 * 1024 * 1024,
    )?;
    add_file_to_zip(
        &mut zip_writer,
        &bootstrap_resource_dir().join("manifest.json"),
        "bootstrap-manifest.json",
        options,
    )?;

    let port = read_workspace_api_port(&workspace_id).unwrap_or(18900);
    let pid_data = read_pid_file(&workspace_id);
    let runtime_summary = serde_json::json!({
        "desktop_version": env!("CARGO_PKG_VERSION"),
        "runtime_mode": read_runtime_manifest()
            .map(|m| if m.legacy_mode { "legacy-fallback" } else { "dual-venv" })
            .unwrap_or("unknown"),
        "platform": std::env::consts::OS,
        "machine": std::env::consts::ARCH,
        "runtime_root": runtime_root_dir().to_string_lossy(),
        "app_python": runtime_venv_python_path(&app_venv_dir()).to_string_lossy(),
        "agent_python": runtime_venv_python_path(&agent_venv_dir()).to_string_lossy(),
        "toolchain_python": managed_python_seed_path().map(|p| p.to_string_lossy().to_string()),
        "node_toolchain": managed_node_seed_path().map(|p| p.to_string_lossy().to_string()),
        "legacy_mode": read_runtime_manifest().map(|m| m.legacy_mode).unwrap_or(false),
        "last_error": read_runtime_manifest().and_then(|m| m.last_error),
        "env_trust_source": "host-runtime",
        "subprocess_secret_scrub": true,
        "scrubbed_env_keys": ["PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "VIRTUAL_ENV", "PIP_TARGET"],
        "api_port": port,
        "pid": pid_data.as_ref().map(|p| p.pid),
        "pid_running": pid_data.as_ref().map(|p| is_pid_file_valid(p)).unwrap_or(false),
        "health_status": if is_backend_http_healthy(Some(port)) { "ok" } else { "unknown" },
    });
    zip_writer
        .start_file("runtime-env-summary.json", options)
        .map_err(|e| format!("zip error: {e}"))?;
    zip_writer
        .write_all(
            serde_json::to_string_pretty(&runtime_summary)
                .unwrap_or_else(|_| "{}".into())
                .as_bytes(),
        )
        .map_err(|e| format!("zip write error: {e}"))?;

    zip_writer
        .start_file("port-18900.txt", options)
        .map_err(|e| format!("zip error: {e}"))?;
    zip_writer
        .write_all(
            format!(
                "workspace_id={}\napi_port={}\nhttp_healthy={}\npid={:?}\npid_running={}\n",
                workspace_id,
                port,
                is_backend_http_healthy(Some(port)),
                pid_data.as_ref().map(|p| p.pid),
                pid_data
                    .as_ref()
                    .map(|p| is_pid_file_valid(p))
                    .unwrap_or(false)
            )
            .as_bytes(),
        )
        .map_err(|e| format!("zip write error: {e}"))?;

    zip_writer
        .start_file("processes.txt", options)
        .map_err(|e| format!("zip error: {e}"))?;
    let proc_text = pid_data
        .as_ref()
        .map(|p| {
            format!(
                "managed_pid={}\nworkspace_id={}\nrunning={}\n",
                p.pid,
                workspace_id,
                is_pid_file_valid(p)
            )
        })
        .unwrap_or_else(|| "no pid file\n".into());
    zip_writer
        .write_all(proc_text.as_bytes())
        .map_err(|e| format!("zip write error: {e}"))?;

    // -- System info --
    if let Some(info) = system_info_json {
        zip_writer
            .start_file("system-info.json", options)
            .map_err(|e| format!("zip error: {e}"))?;
        zip_writer
            .write_all(info.as_bytes())
            .map_err(|e| format!("zip write error: {e}"))?;
    }

    zip_writer
        .finish()
        .map_err(|e| format!("zip finish error: {e}"))?;

    Ok(dest.to_string_lossy().to_string())
}

// ═══════════════════════════════════════════════════════════════════════
// Offline Feedback (when Python backend is down)
// ═══════════════════════════════════════════════════════════════════════

pub(crate) const DEFAULT_FEEDBACK_ENDPOINT: &str = "https://feedback-openkitsune.fzstack.com";
pub(crate) const DEFAULT_CAPTCHA_SCENE_ID: &str = "jkyrkj0w";
pub(crate) const DEFAULT_CAPTCHA_PREFIX: &str = "yiqg72";

pub(crate) fn pending_feedback_path() -> PathBuf {
    openkitsune_root_dir().join("pending_feedback.json")
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PendingFeedbackRecord {
    report_id: String,
    feedback_token: Option<String>,
    title: String,
    report_type: String,
    contact_email: String,
    submitted_at: String,
    issue_url: Option<String>,
}

/// Read feedback endpoint from workspace config.yaml, falling back to default.
pub(crate) fn read_feedback_endpoint(workspace_id: &str) -> String {
    let cfg_path = workspace_dir(workspace_id).join("config.yaml");
    if let Ok(content) = fs::read_to_string(&cfg_path) {
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("bug_report_endpoint:") {
                let val = trimmed
                    .trim_start_matches("bug_report_endpoint:")
                    .trim()
                    .trim_matches('"')
                    .trim_matches('\'');
                if !val.is_empty() {
                    return val.to_string();
                }
            }
        }
    }
    DEFAULT_FEEDBACK_ENDPOINT.to_string()
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct FeedbackImage {
    filename: String,
    data_base64: String,
}

/// Build a feedback ZIP with diagnostic data, metadata, and optional images.
/// Returns the path to the generated ZIP file.
#[tauri::command]
pub(crate) fn build_feedback_zip(
    workspace_id: String,
    report_id: String,
    title: String,
    description: String,
    report_type: String,
    steps: Option<String>,
    contact_email: Option<String>,
    images: Option<Vec<FeedbackImage>>,
) -> Result<String, String> {
    let ws_dir = workspace_dir(&workspace_id);
    let temp_dir = openkitsune_root_dir().join("temp-feedback");
    fs::create_dir_all(&temp_dir).map_err(|e| format!("mkdir error: {e}"))?;
    let dest = temp_dir.join(format!("{report_id}.zip"));

    let file = fs::File::create(&dest).map_err(|e| format!("create zip: {e}"))?;
    let mut zw = zip::ZipWriter::new(file);
    let opts = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated);

    // --- metadata.json ---
    let now = {
        let d = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        let secs = d % 60;
        let mins = (d / 60) % 60;
        let hrs = (d / 3600) % 24;
        let days = d / 86400;
        let (y, m, day) = civil_from_days(days as i64);
        format!("{y:04}-{m:02}-{day:02}T{hrs:02}:{mins:02}:{secs:02}Z")
    };
    let metadata = serde_json::json!({
        "report_id": report_id,
        "type": report_type,
        "title": title,
        "description": description,
        "steps": steps.unwrap_or_default(),
        "created_at": now,
        "submitted_via": "tauri_offline",
        "contact": { "email": contact_email.clone().unwrap_or_default() },
        "system_info": {
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
        }
    });
    zw.start_file("metadata.json", opts)
        .map_err(|e| format!("zip: {e}"))?;
    zw.write_all(
        serde_json::to_string_pretty(&metadata)
            .unwrap_or_default()
            .as_bytes(),
    )
    .map_err(|e| format!("zip write: {e}"))?;

    // --- images ---
    if let Some(imgs) = images {
        for (i, img) in imgs.iter().enumerate() {
            if let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(&img.data_base64) {
                let name = if img.filename.is_empty() {
                    format!("images/image_{i}.png")
                } else {
                    format!("images/{}", img.filename)
                };
                zw.start_file(&name, opts)
                    .map_err(|e| format!("zip: {e}"))?;
                let _ = zw.write_all(&bytes);
            }
        }
    }

    // --- Reuse diagnostic collection logic (same as export_diagnostic_bundle) ---
    fn collect_files_recursive(dir: &Path) -> Vec<PathBuf> {
        let mut result = Vec::new();
        if let Ok(entries) = fs::read_dir(dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_dir() {
                    result.extend(collect_files_recursive(&p));
                } else {
                    result.push(p);
                }
            }
        }
        result
    }
    fn zip_add_dir(
        zw: &mut zip::ZipWriter<fs::File>,
        dir: &Path,
        prefix: &str,
        opts: zip::write::SimpleFileOptions,
    ) {
        if !dir.exists() {
            return;
        }
        for fp in collect_files_recursive(dir) {
            if let Ok(rel) = fp.strip_prefix(dir) {
                let name = format!("{}/{}", prefix, rel.to_string_lossy().replace('\\', "/"));
                if zw.start_file(&name, opts).is_ok() {
                    let _ = zw.write_all(&fs::read(&fp).unwrap_or_default());
                }
            }
        }
    }
    fn zip_add_dir_capped(
        zw: &mut zip::ZipWriter<fs::File>,
        dir: &Path,
        prefix: &str,
        opts: zip::write::SimpleFileOptions,
        max_bytes: u64,
    ) {
        if !dir.exists() {
            return;
        }
        let mut files = collect_files_recursive(dir);
        files.sort_by(|a, b| {
            let ma = fs::metadata(a).and_then(|m| m.modified()).ok();
            let mb = fs::metadata(b).and_then(|m| m.modified()).ok();
            mb.cmp(&ma)
        });
        let mut total: u64 = 0;
        for fp in files {
            let sz = fs::metadata(&fp).map(|m| m.len()).unwrap_or(0);
            if total + sz > max_bytes {
                continue;
            }
            if let Ok(rel) = fp.strip_prefix(dir) {
                let name = format!("{}/{}", prefix, rel.to_string_lossy().replace('\\', "/"));
                if zw.start_file(&name, opts).is_ok() {
                    let _ = zw.write_all(&fs::read(&fp).unwrap_or_default());
                    total += sz;
                }
            }
        }
    }
    fn zip_add_file(
        zw: &mut zip::ZipWriter<fs::File>,
        path: &Path,
        zip_name: &str,
        opts: zip::write::SimpleFileOptions,
    ) {
        if !path.exists() || !path.is_file() {
            return;
        }
        if zw.start_file(zip_name, opts).is_ok() {
            let _ = zw.write_all(&fs::read(path).unwrap_or_default());
        }
    }

    let logs_dir = ws_dir.join("logs");
    let data_dir = ws_dir.join("data");
    let llm_debug_dir = data_dir.join("llm_debug");

    zip_add_dir(&mut zw, &logs_dir, "logs", opts);
    zip_add_dir_capped(&mut zw, &llm_debug_dir, "llm_debug", opts, 10 * 1024 * 1024);
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("delegation_logs"),
        "delegation_logs",
        opts,
        2 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("react_traces"),
        "react_traces",
        opts,
        5 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("traces"),
        "traces",
        opts,
        2 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("orgs"),
        "orgs",
        opts,
        2 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("tool_overflow"),
        "tool_overflow",
        opts,
        2 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("failure_analysis"),
        "failure_analysis",
        opts,
        1 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &data_dir.join("retrospects"),
        "retrospects",
        opts,
        1 * 1024 * 1024,
    );

    zip_add_file(
        &mut zw,
        &data_dir.join("runtime_state.json"),
        "state/runtime_state.json",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("sub_agent_states.json"),
        "state/sub_agent_states.json",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("backend.heartbeat"),
        "state/backend.heartbeat",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("sessions").join("sessions.json"),
        "state/sessions.json",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("sessions").join("channel_registry.json"),
        "state/channel_registry.json",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("scheduler").join("tasks.json"),
        "state/scheduler_tasks.json",
        opts,
    );
    zip_add_file(
        &mut zw,
        &data_dir.join("scheduler").join("executions.json"),
        "state/scheduler_executions.json",
        opts,
    );

    let global_logs = setup_logs_dir();
    zip_add_file(
        &mut zw,
        &global_logs.join("frontend.log"),
        "global_logs/frontend.log",
        opts,
    );
    zip_add_file(
        &mut zw,
        &global_logs.join("crash.log"),
        "global_logs/crash.log",
        opts,
    );
    zip_add_file(
        &mut zw,
        &global_logs.join("autostart.log"),
        "global_logs/autostart.log",
        opts,
    );
    for entry in fs::read_dir(&global_logs).into_iter().flatten().flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with("onboarding-") && name_str.ends_with(".log") {
            zip_add_file(
                &mut zw,
                &entry.path(),
                &format!("global_logs/{name_str}"),
                opts,
            );
        }
    }

    zip_add_file(
        &mut zw,
        &runtime_manifest_path(),
        "runtime/manifest.json",
        opts,
    );
    zip_add_dir_capped(
        &mut zw,
        &runtime_logs_dir(),
        "runtime/logs",
        opts,
        5 * 1024 * 1024,
    );
    zip_add_dir_capped(
        &mut zw,
        &runtime_root_dir().join("reports"),
        "runtime/reports",
        opts,
        5 * 1024 * 1024,
    );

    // ── Native crash dumps ──
    // Our SetUnhandledExceptionFilter-based crash handler writes
    // ~5 MB mini dumps to ~/.openkitsune/crashdumps/openkitsune-*.dmp.
    // Cap aggregate at 25 MB so a single bad report cannot blow past
    // the 30 MB upload limit; keeps newest dumps first.
    zip_add_dir_capped(
        &mut zw,
        &crashdumps_dir(),
        "crashdumps",
        opts,
        25 * 1024 * 1024,
    );

    // ── Windows Error Reporting metadata + system event log ──
    // Only available on Windows; on macOS / Linux these calls are no-ops
    // and contribute nothing to the zip.
    collect_windows_crash_artifacts(&mut zw, opts);

    zw.finish().map_err(|e| format!("zip finish: {e}"))?;
    Ok(dest.to_string_lossy().to_string())
}

/// Pull Windows-only diagnostic artifacts into a feedback zip:
///   * `wer/Report.wer` files from `%LOCALAPPDATA%\Microsoft\Windows\WER\
///     ReportArchive\*` that mention our exe (metadata only — no PII
///     beyond version + faulting module + exception code).
///   * The last 30 Application Error / Windows Error Reporting events
///     for our exe via `wevtutil qe Application`. Plain XML, ~50 KB max.
///
/// This is purely additive: any failure (permission denied, WER service
/// disabled, wevtutil missing) is swallowed silently so the rest of the
/// bundle still builds.
#[cfg(windows)]
pub(crate) fn collect_windows_crash_artifacts(
    zw: &mut zip::ZipWriter<fs::File>,
    opts: zip::write::SimpleFileOptions,
) {
    let local_appdata = match std::env::var_os("LOCALAPPDATA") {
        Some(v) => PathBuf::from(v),
        None => return,
    };
    let wer_archive = local_appdata
        .join("Microsoft")
        .join("Windows")
        .join("WER")
        .join("ReportArchive");

    // WER report directories aren't reliably named: some are
    // `AppCrash_openkitsune-setup-center.exe_<hash>`, others are just
    // `Report.<hash>`. The exe name is always present in the Report.wer
    // body though, so we filter by (a) dir-name fast path first, (b)
    // fall back to reading the (small, <30 KB) Report.wer text. Limit
    // the candidate set to the 30 most recently modified directories so
    // even a heavily-crashed host doesn't spend minutes scanning.
    let needle = "openkitsune";
    let mut candidates: Vec<(PathBuf, std::time::SystemTime)> = fs::read_dir(&wer_archive)
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let p = e.path();
            if !p.is_dir() {
                return None;
            }
            let m = fs::metadata(&p).and_then(|md| md.modified()).ok()?;
            Some((p, m))
        })
        .collect();
    candidates.sort_by(|a, b| b.1.cmp(&a.1));
    candidates.truncate(30);

    for (report_dir, _) in candidates {
        let report_wer = report_dir.join("Report.wer");
        if !report_wer.is_file() {
            continue;
        }
        let dir_name_lower = report_dir
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let matched = if dir_name_lower.contains(needle) {
            true
        } else {
            // Body match: Report.wer is a tiny INI-like text file with
            // AppName / AppPath / FaultingModule keys. Read at most
            // 64 KB to bound worst-case I/O.
            match fs::read(&report_wer) {
                Ok(bytes) => {
                    let scan_len = bytes.len().min(64 * 1024);
                    let s = String::from_utf8_lossy(&bytes[..scan_len]);
                    s.to_ascii_lowercase().contains(needle)
                }
                Err(_) => false,
            }
        };
        if !matched {
            continue;
        }
        let zip_name = format!(
            "wer/{}-Report.wer",
            report_dir.file_name().unwrap_or_default().to_string_lossy()
        );
        if zw.start_file(&zip_name, opts).is_ok() {
            let _ = zw.write_all(&fs::read(&report_wer).unwrap_or_default());
        }
    }

    // Pull recent Application Error / WER events for our exe. Narrowing
    // the XPath to the last 7 days bounds the index scan on busy hosts.
    let xpath = "*[System[Provider[@Name='Application Error' or @Name='Windows Error Reporting'] \
                 and TimeCreated[timediff(@SystemTime) <= 604800000]]]"; // last 7 days
    let ps_cmd = format!(
        "$ev = Get-WinEvent -LogName Application -MaxEvents 200 -FilterXPath \"{}\" \
         -ErrorAction SilentlyContinue | \
         Where-Object {{ $_.Message -match 'openkitsune' }} | \
         Select-Object -First 30; \
         if ($ev) {{ $ev | ForEach-Object {{ \
           '[{{0}}] {{1}}: {{2}}' -f \
             $_.TimeCreated.ToString('s'), $_.ProviderName, ($_.Message -replace '\\r?\\n', ' | ') \
         }} }}",
        xpath
    );

    if let Some(out) = run_powershell_with_timeout(&ps_cmd, std::time::Duration::from_secs(15)) {
        if !out.is_empty() && zw.start_file("wer/event_log_recent.txt", opts).is_ok() {
            let _ = zw.write_all(&out);
        }
    }
}

/// Spawn `powershell.exe -Command <cmd>` and bound the wall-clock wait.
/// Returns captured stdout on success, or `None` if the process never
/// started, was killed by timeout, or printed nothing.
///
/// Why custom timeout: `std::process::Command::output()` waits forever
/// for the child. A pathological Application event log (corrupted index,
/// remote SACL audit pulling from a slow DC, …) could block the
/// "send feedback" UI indefinitely. We pump stdout from a reader thread
/// and use mpsc::recv_timeout to enforce the deadline without taking on
/// a new crate dependency.
#[cfg(windows)]
pub(crate) fn run_powershell_with_timeout(
    cmd: &str,
    timeout: std::time::Duration,
) -> Option<Vec<u8>> {
    use std::io::Read;
    use std::os::windows::process::CommandExt;
    use std::process::{Command, Stdio};
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    let mut child = Command::new("powershell")
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            cmd,
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .ok()?;

    let mut stdout = child.stdout.take()?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut buf = Vec::with_capacity(4096);
        let _ = stdout.read_to_end(&mut buf);
        let _ = tx.send(buf);
    });

    match rx.recv_timeout(timeout) {
        Ok(buf) => {
            let _ = child.wait();
            Some(buf)
        }
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            None
        }
    }
}

#[cfg(not(windows))]
pub(crate) fn collect_windows_crash_artifacts(
    _zw: &mut zip::ZipWriter<fs::File>,
    _opts: zip::write::SimpleFileOptions,
) {
}

/// Simple days-since-epoch to civil date (year, month, day).
pub(crate) fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
}

/// Upload a feedback ZIP to the cloud FC endpoint (3-phase: prepare → OSS PUT → complete).
/// Returns { reportId, feedbackToken, issueUrl } on success.
#[tauri::command]
pub(crate) fn upload_feedback_to_cloud(
    workspace_id: String,
    zip_path: String,
    report_id: String,
    report_type: String,
    title: String,
    summary: String,
    captcha_verify_param: String,
    contact_email: String,
) -> Result<serde_json::Value, String> {
    let endpoint = read_feedback_endpoint(&workspace_id);
    if endpoint.is_empty() {
        return Err("Feedback endpoint not configured".into());
    }
    let zip_bytes = fs::read(&zip_path).map_err(|e| format!("read zip: {e}"))?;
    let _ = fs::remove_file(&zip_path);
    if zip_bytes.len() > 30 * 1024 * 1024 {
        return Err(format!(
            "ZIP too large: {:.1} MB (max 30 MB)",
            zip_bytes.len() as f64 / 1048576.0
        ));
    }

    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(180))
        .build()
        .map_err(|e| format!("http client: {e}"))?;

    let base = endpoint.trim_end_matches('/');

    fn truncate_chars(s: &str, max_chars: usize) -> &str {
        match s.char_indices().nth(max_chars) {
            Some((idx, _)) => &s[..idx],
            None => s,
        }
    }

    // Phase 1: prepare
    let prepare_resp = client
        .post(format!("{base}/prepare"))
        .json(&serde_json::json!({
            "report_id": report_id,
            "title": truncate_chars(&title, 200),
            "type": report_type,
            "summary": truncate_chars(&summary, 2000),
            "system_info": format!("OS: {} {}", std::env::consts::OS, std::env::consts::ARCH),
            "captcha_verify_param": captcha_verify_param,
            "contact_email": contact_email,
        }))
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .map_err(|e| format!("prepare failed: {e}"))?;

    if prepare_resp.status().as_u16() == 429 {
        return Err("Rate limit, please try later".into());
    }
    if prepare_resp.status().as_u16() == 403 {
        return Err("CAPTCHA verification failed".into());
    }
    if prepare_resp.status().is_client_error() || prepare_resp.status().is_server_error() {
        let text = prepare_resp.text().unwrap_or_default();
        return Err(format!("Cloud error: {}", &text[..text.len().min(200)]));
    }

    let prepare_data: serde_json::Value = prepare_resp
        .json()
        .map_err(|e| format!("parse prepare: {e}"))?;
    let upload_url = prepare_data["upload_url"]
        .as_str()
        .ok_or("missing upload_url")?;
    let report_date = prepare_data["report_date"].as_str().unwrap_or("");

    // Phase 2: OSS upload
    let oss_resp = client
        .put(upload_url)
        .header("Content-Length", zip_bytes.len().to_string())
        .body(zip_bytes)
        .send()
        .map_err(|e| format!("OSS upload failed: {e}"))?;

    if oss_resp.status().is_client_error() || oss_resp.status().is_server_error() {
        return Err(format!("OSS upload error: {}", oss_resp.status()));
    }

    // Phase 3: complete
    let complete_resp = client
        .post(format!("{base}/complete/{report_id}"))
        .json(&serde_json::json!({ "report_date": report_date }))
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .map_err(|e| format!("complete failed: {e}"))?;

    let mut feedback_token: Option<String> = None;
    let mut issue_url: Option<String> = None;
    if complete_resp.status().is_success() {
        if let Ok(data) = complete_resp.json::<serde_json::Value>() {
            feedback_token = data["feedback_token"].as_str().map(|s| s.to_string());
            issue_url = data["issue_url"].as_str().map(|s| s.to_string());
        }
    }

    Ok(serde_json::json!({
        "reportId": report_id,
        "feedbackToken": feedback_token,
        "issueUrl": issue_url,
    }))
}

/// Save a pending feedback record to JSON file for later import by Python backend.
#[tauri::command]
pub(crate) fn save_pending_feedback(record: PendingFeedbackRecord) -> Result<(), String> {
    let path = pending_feedback_path();
    let mut records: Vec<PendingFeedbackRecord> = if path.exists() {
        let data = fs::read_to_string(&path).unwrap_or_else(|_| "[]".to_string());
        serde_json::from_str(&data).unwrap_or_default()
    } else {
        Vec::new()
    };
    records.push(record);

    let tmp = path.with_extension("json.tmp");
    fs::write(
        &tmp,
        serde_json::to_string_pretty(&records).unwrap_or_else(|_| "[]".into()),
    )
    .map_err(|e| format!("write pending: {e}"))?;
    fs::rename(&tmp, &path).map_err(|e| format!("rename pending: {e}"))?;
    Ok(())
}

/// Get feedback config (captcha ids) when backend is offline.
#[tauri::command]
pub(crate) fn get_feedback_config_offline(workspace_id: String) -> serde_json::Value {
    let cfg_path = workspace_dir(&workspace_id).join("config.yaml");
    let mut scene_id = DEFAULT_CAPTCHA_SCENE_ID.to_string();
    let mut prefix = DEFAULT_CAPTCHA_PREFIX.to_string();
    if let Ok(content) = fs::read_to_string(&cfg_path) {
        for line in content.lines() {
            let t = line.trim();
            if t.starts_with("captcha_scene_id:") {
                let v = t
                    .trim_start_matches("captcha_scene_id:")
                    .trim()
                    .trim_matches('"')
                    .trim_matches('\'');
                if !v.is_empty() {
                    scene_id = v.to_string();
                }
            }
            if t.starts_with("captcha_prefix:") {
                let v = t
                    .trim_start_matches("captcha_prefix:")
                    .trim()
                    .trim_matches('"')
                    .trim_matches('\'');
                if !v.is_empty() {
                    prefix = v.to_string();
                }
            }
        }
    }
    serde_json::json!({
        "captcha_scene_id": scene_id,
        "captcha_prefix": prefix,
    })
}

/// Open an external URL in the OS default browser.
#[tauri::command]
pub(crate) fn open_external_url(url: String) -> Result<(), String> {
    let url = url.trim();
    if url.is_empty() {
        return Err("URL is empty".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        // Avoid `cmd /C start`: URLs from WeChat articles often contain `&`,
        // which cmd.exe treats as a command separator and truncates the link.
        let mut c = std::process::Command::new("rundll32");
        c.args(["url.dll,FileProtocolHandler", url]);
        apply_no_window(&mut c);
        c.spawn().map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    Ok(())
}
