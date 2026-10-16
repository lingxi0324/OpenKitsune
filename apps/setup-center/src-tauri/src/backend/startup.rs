use crate::prelude::*;

/// 启动时后端版本对账的结果。
///
/// 三种状态覆盖所有情况，调用方据此决定是否启动新后端，
/// 且只需一次 HTTP 健康检查，避免重复请求。
pub(crate) enum VersionCheckResult {
    /// 端口上没有后端在运行。
    NotRunning,
    /// 后端正在运行且版本可接受（匹配、dev 版本、或重启无法改善）。
    RunningOk,
    /// 旧版后端已被终止，需要启动新后端。
    Upgraded,
}

pub(crate) fn runtime_wheel_hash_matches_bootstrap() -> bool {
    let bootstrap_hash = match read_bootstrap_manifest() {
        Ok(b) => b.wheel.sha256,
        Err(e) => {
            log_to_file(&format!(
                "[version_check] bootstrap manifest unavailable: {e}"
            ));
            return false;
        }
    };
    if bootstrap_hash.trim().is_empty() {
        return true;
    }
    read_runtime_manifest()
        .map(|m| {
            // Legacy venv compatibility does not install from the bootstrap
            // wheel, so its hash cannot be reconciled with the managed runtime.
            if m.legacy_mode {
                return true;
            }
            m.wheel_hash == bootstrap_hash
        })
        .unwrap_or(false)
}

pub(crate) fn stop_backend_for_restart(
    workspace_id: &str,
    pid: u32,
    port: u16,
) -> VersionCheckResult {
    if !can_auto_stop_backend(workspace_id, pid) {
        log_to_file(&format!(
            "[version_check] keeping externally owned backend pid={} for ws={}",
            pid, workspace_id
        ));
        return VersionCheckResult::RunningOk;
    }

    if let Err(e) = graceful_stop_pid(pid, Some(port)) {
        eprintln!(
            "Failed to stop old backend (pid={}): {}. Keeping current backend.",
            pid, e
        );
        return VersionCheckResult::RunningOk;
    }

    // 清理被终止进程对应的 PID 文件
    for ent in list_service_pids() {
        if let Some(data) = read_pid_file(&ent.workspace_id) {
            if data.pid == pid || !is_pid_running(data.pid) {
                let _ = fs::remove_file(service_pid_file(&ent.workspace_id));
                remove_heartbeat_file(&ent.workspace_id);
            }
        }
    }

    eprintln!(
        "Old backend (pid={}) stopped. New backend will be started automatically.",
        pid
    );
    VersionCheckResult::Upgraded
}

pub(crate) fn healthy_backend_pid(port: u16) -> Option<u32> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .no_proxy()
        .build()
        .ok()?;
    let resp = client
        .get(format!("http://127.0.0.1:{}/api/health", port))
        .send()
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let json: serde_json::Value = resp.json().ok()?;
    if json.get("service").and_then(|v| v.as_str()) != Some("openkitsune") {
        return None;
    }
    json.get("pid")
        .and_then(|v| v.as_u64())
        .and_then(|pid| u32::try_from(pid).ok())
        .filter(|pid| is_pid_running(*pid))
}

/// DMG 覆盖安装后版本对账：检查运行中后端的版本，必要时替换。
///
/// macOS 上通过 DMG 拖拽覆盖安装后，旧的 openkitsune-server 进程可能仍在端口上
/// 服务。新版 app 启动时必须检测版本不匹配并主动替换，否则会一直使用旧后端。
///
/// 此函数合并了「是否有后端在运行」和「版本是否匹配」两个检查，
/// 只发一次 HTTP 请求，避免 setup 阶段重复探测。
pub(crate) fn startup_version_check(
    workspace_id: &str,
    app_version: &str,
    port: u16,
) -> VersionCheckResult {
    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .no_proxy()
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            log_to_file(&format!("[version_check] client build failed: {e}"));
            return VersionCheckResult::NotRunning;
        }
    };

    let resp = match client
        .get(format!("http://127.0.0.1:{}/api/health", port))
        .send()
    {
        Ok(r) if r.status().is_success() => r,
        Ok(r) => {
            log_to_file(&format!(
                "[version_check] health check non-success: {}",
                r.status()
            ));
            return VersionCheckResult::NotRunning;
        }
        Err(e) => {
            log_to_file(&format!("[version_check] health check failed: {e}"));
            return VersionCheckResult::NotRunning;
        }
    };

    let json: serde_json::Value = match resp.json() {
        Ok(v) => v,
        Err(_) => return VersionCheckResult::RunningOk, // 响应成功但 JSON 解析失败，保守处理
    };

    let backend_version = json
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim_start_matches('v');
    let desktop_version = app_version.trim_start_matches('v');

    // 版本无法判断或 dev 后端 → 保守保持现有后端。
    if backend_version.is_empty() || backend_version == "0.0.0-dev" {
        return VersionCheckResult::RunningOk;
    }

    if backend_version == desktop_version {
        if runtime_wheel_hash_matches_bootstrap() {
            return VersionCheckResult::RunningOk;
        }
        let pid = match json.get("pid").and_then(|v| v.as_u64()).map(|p| p as u32) {
            Some(p) => p,
            None => {
                eprintln!("Runtime wheel changed but backend PID is unavailable; keeping current backend.");
                return VersionCheckResult::RunningOk;
            }
        };
        eprintln!(
            "Runtime wheel changed for version {}. Stopping backend to refresh app-venv...",
            desktop_version
        );
        return stop_backend_for_restart(workspace_id, pid, port);
    }

    eprintln!(
        "Version mismatch: running={} desktop={}. Stopping old backend for upgrade...",
        backend_version, desktop_version
    );

    // graceful_stop_pid 内部已包含：POST /api/shutdown → 等待 5s → force kill → 等待 2s
    // 无需手动再发 shutdown 或 sleep。
    let pid = match json.get("pid").and_then(|v| v.as_u64()).map(|p| p as u32) {
        Some(p) => p,
        None => {
            eprintln!(
                "Cannot determine backend PID from health response; keeping current backend."
            );
            return VersionCheckResult::RunningOk;
        }
    };

    stop_backend_for_restart(workspace_id, pid, port)
}

/// 启动对账：清理残留锁文件和已死的 PID 文件
pub(crate) fn startup_reconcile() {
    let dir = run_dir();
    if !dir.exists() {
        return;
    }

    // 1. 清理残留 .lock 文件（上次崩溃可能遗留）
    if let Ok(rd) = fs::read_dir(&dir) {
        for e in rd.flatten() {
            let p = e.path();
            if let Some(ext) = p.extension() {
                if ext == "lock" {
                    let _ = fs::remove_file(&p);
                }
            }
        }
    }

    // 2. 扫描 PID 文件，清理已死进程的 stale 条目
    let entries = list_service_pids();
    for ent in &entries {
        if let Some(data) = read_pid_file(&ent.workspace_id) {
            if !is_pid_file_valid(&data) {
                // 进程已死或 PID 被复用，清理 PID 文件和心跳文件
                let _ = fs::remove_file(service_pid_file(&ent.workspace_id));
                remove_heartbeat_file(&ent.workspace_id);
            } else if let Some(true) = is_heartbeat_stale(&ent.workspace_id, 60) {
                // PID 文件有效但心跳超时。先用 HTTP health 复核，避免因心跳文件
                // 写入异常误杀仍可响应的后端进程。
                let port = read_workspace_api_port(&ent.workspace_id);
                if should_cleanup_stale_heartbeat(Some(true), is_backend_http_healthy(port)) {
                    let _ = graceful_stop_pid(data.pid, port);
                    let _ = fs::remove_file(service_pid_file(&ent.workspace_id));
                    remove_heartbeat_file(&ent.workspace_id);
                }
            }
        }
    }
}

/// Append a crash entry to `~/.openkitsune/logs/crash.log`.
///
/// When `show_dialog` is true, a native `MessageBoxW` (Windows) is displayed
/// so the user gets feedback instead of a silent flash-exit.
///
/// Returns the path to the crash log (best-effort; may not exist if writing
/// failed, e.g. due to permissions).
pub(crate) fn write_crash_log(message: &str, show_dialog: bool) -> PathBuf {
    let log_dir = setup_logs_dir();
    let _ = fs::create_dir_all(&log_dir);
    let crash_path = log_dir.join("crash.log");

    let timestamp = {
        let dur = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default();
        dur.as_secs()
    };
    let exe = std::env::current_exe()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| "<unknown>".to_string());
    let cwd = std::env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| "<unknown>".to_string());
    let home = home_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| "<None>".to_string());
    let entry = format!("[{timestamp}] exe={exe} cwd={cwd} home={home}\n{message}\n---\n");

    let _ = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&crash_path)
        .and_then(|mut f| f.write_all(entry.as_bytes()));

    if show_dialog {
        #[cfg(windows)]
        {
            use std::ffi::OsStr;
            use std::iter::once;
            use std::os::windows::ffi::OsStrExt;

            extern "system" {
                fn MessageBoxW(
                    hwnd: *mut std::ffi::c_void,
                    text: *const u16,
                    caption: *const u16,
                    typ: u32,
                ) -> i32;
            }

            fn to_wide(s: &str) -> Vec<u16> {
                OsStr::new(s).encode_wide().chain(once(0)).collect()
            }

            let body = format!(
                "OpenKitsune Desktop 启动失败 (startup failed)\n\n\
                 {message}\n\n\
                 崩溃日志已写入 (crash log): {}\n\
                 请将此日志发送给开发者以帮助诊断问题。",
                crash_path.display()
            );
            let caption = "OpenKitsune – Crash";
            let wb = to_wide(&body);
            let wc = to_wide(caption);
            unsafe {
                MessageBoxW(std::ptr::null_mut(), wb.as_ptr(), wc.as_ptr(), 0x10);
            }
        }
    }

    crash_path
}

pub(crate) fn show_main_window(app: &tauri::AppHandle, reason: &str, open_status: bool) {
    if !ui_accepts_tauri_ops() {
        log_to_file(&format!(
            "[window] ignored show_main_window during shutdown ({reason})"
        ));
        return;
    }
    let app_handle = app.clone();
    let reason = reason.to_string();

    #[cfg(target_os = "windows")]
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(120));
        if !ui_accepts_tauri_ops() {
            return;
        }
        let app_for_ui = app_handle.clone();
        let reason_for_log = reason.clone();
        if let Err(error) = app_handle.run_on_main_thread(move || {
            show_main_window_now(&app_for_ui, &reason, open_status);
        }) {
            log_to_file(&format!(
                "[window] run_on_main_thread failed ({reason_for_log}): {error}"
            ));
        }
    });

    #[cfg(not(target_os = "windows"))]
    show_main_window_now(&app_handle, &reason, open_status);
}

pub(crate) fn show_main_window_now(app: &tauri::AppHandle, reason: &str, open_status: bool) {
    if !ui_accepts_tauri_ops() {
        return;
    }
    if let Some(w) = app.get_webview_window("main") {
        if let Err(e) = w.show() {
            log_to_file(&format!("[window] show failed ({reason}): {e}"));
        }
        let _ = w.unminimize();
        if let Err(e) = w.set_focus() {
            log_to_file(&format!("[window] focus failed ({reason}): {e}"));
        }
    } else {
        log_to_file(&format!("[window] main window not found ({reason})"));
    }
    if open_status {
        emit_if_ui_live(app, "open_status", serde_json::json!({}));
    }
}
