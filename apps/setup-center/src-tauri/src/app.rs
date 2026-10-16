use crate::prelude::*;
use tauri::Emitter;
use tauri_plugin_deep_link::DeepLinkExt;

pub fn run() {
    let args: Vec<String> = std::env::args().collect();
    if let Some(index) = args.iter().position(|arg| arg == "--watchdog") {
        #[cfg(windows)]
        if let Some(parent_pid) = args.get(index + 1).and_then(|value| value.parse().ok()) {
            run_watchdog(parent_pid);
        }
        return;
    }

    // 自愈接力进程的启动时序兜底：
    // panic hook 在 spawn 新实例时旧进程还没真正退出，
    // tauri-plugin-single-instance 会让新实例的 callback 在旧进程里触发
    // 然后新实例直接退出。这里在新实例最早期 sleep 让旧进程的崩溃流程
    // 完整执行（写 crash.log + 释放 single-instance 锁），然后再继续启动。
    if std::env::args().any(|a| a == "--auto-restarted") {
        std::thread::sleep(std::time::Duration::from_millis(1500));
    }

    if std::env::var_os("RUST_BACKTRACE").is_none() {
        std::env::set_var("RUST_BACKTRACE", "1");
    }
    crate::graphics::configure_webview_environment();
    spawn_machine_info_collector();

    // Native crash handler: capture SEH exceptions (access violation /
    // heap corruption / illegal instruction) to ~/.openkitsune/crashdumps/
    // *.dmp.  std::panic::set_hook only sees Rust panics, not C-level
    // crashes from WebView2 / DLLs / GPU drivers, which is where the
    // 0xc0000005 / 0xc0000374 / 0xc000001d reports actually originate.
    // No admin / HKLM LocalDumps writes required — the handler runs
    // entirely in-process.
    crash_handler::install(crashdumps_dir());

    // Capture structured panic diagnostics. The tao patch is the primary
    // Destroyed-state fix; self-heal remains a fallback.
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let location = info
            .location()
            .map(|value| format!("{}:{}:{}", value.file(), value.line(), value.column()))
            .unwrap_or_else(|| "<unknown>".to_string());
        let payload = panic_payload_to_string(info.payload());
        let backtrace = std::backtrace::Backtrace::force_capture();
        let machine = machine_info_snapshot();
        let events = crash_handler::snapshot_events();
        let events_block = if events.is_empty() {
            "<none>".to_string()
        } else {
            events.join("\n")
        };
        let msg = format!(
            "PANIC at {location}\n\
             Message: {payload}\n\n\
             === Recent events (oldest -> newest) ===\n{events_block}\n\n\
             === Machine info ===\n{machine}\n\n\
             === Backtrace ===\n{backtrace}"
        );
        eprintln!("{msg}");
        write_crash_log(&msg, true);
        if payload.contains("cannot move state from Destroyed")
            || (payload.contains("tao") && payload.contains("Destroyed"))
        {
            try_self_heal_relaunch(&payload);
        }
        default_hook(info);
    }));

    // Ensure localhost is always excluded from proxy resolution.
    //
    // macOS: Clash/V2Ray set system proxy via Network Preferences. hyper-util
    //   links `system-configuration` and reads these settings, so ALL reqwest
    //   clients (including Tauri HTTP plugin's) would route 127.0.0.1 through
    //   the proxy — which fails because the backend only listens locally.
    // Windows: similar issue with system proxy via Internet Options.
    //
    // We APPEND to any existing NO_PROXY/no_proxy rather than overwrite, so
    // user-defined exclusions (e.g. *.corp.com) are preserved.
    // Both cases are set because different libraries check different variants.
    {
        const LOCALS: &str = "localhost,127.0.0.1";
        for key in ["NO_PROXY", "no_proxy"] {
            let cur = std::env::var(key).unwrap_or_default();
            if !cur.contains("127.0.0.1") {
                let val = if cur.is_empty() {
                    LOCALS.to_string()
                } else {
                    format!("{cur},{LOCALS}")
                };
                std::env::set_var(key, &val);
            }
        }
    }

    let app = match tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _cwd| {
            // 第二个实例启动时，聚焦已有窗口并退出自身
            show_main_window(app, "single-instance", false);
            for arg in args {
                if arg.starts_with("openkitsune://") {
                    let _ = app.emit("openkitsune-deep-link", arg);
                }
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--background"]),
        ))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let result: Result<(), Box<dyn std::error::Error>> = (|| {
            #[cfg(any(windows, target_os = "linux"))]
            if cfg!(debug_assertions) {
                app.deep_link().register_all()?;
            }
            // ── NSIS 安装后以当前用户执行清理（解决“以管理员运行安装程序”时清错目录的问题） ──
            let args: Vec<String> = std::env::args().collect();
            if let Some(pos) = args.iter().position(|a| a == "--clean-env") {
                let mut clean_venv = false;
                let mut clean_runtime = false;
                for a in args.iter().skip(pos + 1) {
                    if a == "venv" {
                        clean_venv = true;
                    }
                    if a == "runtime" {
                        clean_runtime = true;
                    }
                    if a.starts_with("--") {
                        break;
                    }
                }
                if clean_venv || clean_runtime {
                    match cleanup_old_environment(clean_venv, clean_runtime) {
                        Ok(msg) => eprintln!("Clean env: {}", msg),
                        Err(e) => eprintln!("Clean env failed: {}", e),
                    }
                    std::process::exit(0);
                }
            }

            clear_exit_handled_marker();
            spawn_watchdog();

            // ── 启动对账：清理残留 .lock 和 stale PID 文件 ──
            startup_reconcile();

            // ── 配置文件版本迁移 ──
            let root = openkitsune_root_dir();
            let state_path = state_file_path();
            if let Err(e) = migrations::run_migrations(&state_path, &root) {
                eprintln!("Config migration error: {e}");
            }

            setup_tray(app)?;

            // ── 自启自修复：防止注册表条目意外丢失（上游 Issue #771） ──
            // 如果用户之前开启了自启（记录在 state file），但注册表条目被意外移除，
            // 则自动重新注册，确保下次开机仍能自启。
            #[cfg(desktop)]
            {
                let repair_state = read_state_file();
                if repair_state.auto_start_backend.unwrap_or(false) {
                    let mgr = app.autolaunch();
                    match mgr.is_enabled() {
                        Ok(false) => {
                            eprintln!("Auto-start self-repair: registry entry missing, re-enabling...");
                            if let Err(e) = mgr.enable() {
                                eprintln!("Auto-start self-repair failed: {e}");
                            }
                        }
                        Err(e) => eprintln!("Auto-start check failed: {e}"),
                        _ => {} // 已启用，无需修复
                    }
                }
            }

            // ── 首次运行检测 (NSIS 安装后自动启动时传入 --first-run) ──
            let is_first_run_arg = std::env::args().any(|a| a == "--first-run");
            let launch_mode = if is_first_run_arg { "first-run" } else { "normal" };
            emit_if_ui_live(app.handle(), "app-launch-mode", launch_mode);
            let app_version = app.package_info().version.to_string();

            if let Some(payload) = detect_previous_frontend_crash() {
                log_to_file("[self-heal] stale frontend session marker recovered");
                set_startup_recovery_notice(payload);
            }
            record_frontend_session_marker(&app_version);

            // ── 自愈恢复：检查上次崩溃留下的 restart.marker ──
            // 由 panic hook 在命中 tao#1180 特征时写入；这里读出后立刻删除
            // 避免重复触发，并向前端 emit 事件，前端可据此恢复上次工作区/视图
            // 或弹温和提示告诉用户"刚刚已自动恢复"。
            let marker_path = restart_marker_path();
            if marker_path.exists() {
                if let Ok(content) = fs::read_to_string(&marker_path) {
                    log_to_file(&format!(
                        "[self-heal] restart.marker recovered: {}",
                        content.lines().next().unwrap_or("")
                    ));
                    let payload: serde_json::Value =
                        serde_json::from_str(&content).unwrap_or(serde_json::json!({}));
                    set_startup_recovery_notice(payload.clone());
                    emit_if_ui_live(app.handle(), "app-restarted-from-crash", payload);
                }
                let _ = fs::remove_file(&marker_path);
            }

            // 后台启动时：不弹出主窗口，只保留托盘/菜单栏常驻
            let is_background = std::env::args().any(|a| a == "--background");
            if is_background {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }

            // ── 自动拉起后端 ──
            // 如果有已配置的工作区且后端未在运行，则自动启动后端。
            // 前端通过 is_backend_auto_starting 查询此状态，
            // 在启动期间显示提示并禁用启动/重启按钮。
            //
            // startup_version_check 合并了「健康检查」和「版本对账」两步：
            //   - NotRunning  → 端口无响应，需要启动
            //   - RunningOk   → 后端在运行且版本可接受
            //   - Upgraded    → 旧版后端已被终止，需要启动新版
            let state = read_state_file();
            if let Some(ref ws_id) = state.current_workspace_id {
                if backend_was_manually_stopped(ws_id) {
                    log_to_file(&format!(
                        "[auto-start] skipped: backend was manually stopped for ws={}",
                        ws_id
                    ));
                } else {
                    let port = read_workspace_api_port(ws_id).unwrap_or(18900);
                    if cfg!(debug_assertions) {
                        if let Some(pid) = healthy_backend_pid(port) {
                            let should_adopt = read_pid_file(ws_id)
                                .map(|data| !is_pid_file_valid(&data))
                                .unwrap_or(true);
                            if should_adopt {
                                match write_pid_file(ws_id, pid, "external") {
                                    Ok(()) => log_to_file(&format!(
                                        "[auto-start] adopted dev backend pid={} for ws={}",
                                        pid, ws_id
                                    )),
                                    Err(e) => log_to_file(&format!(
                                        "[auto-start] failed to adopt dev backend pid={}: {}",
                                        pid, e
                                    )),
                                }
                            }
                        }
                    }

                    let check_result = startup_version_check(ws_id, &app_version, port);
                    let need_start = !matches!(check_result, VersionCheckResult::RunningOk);
                    log_to_file(&format!(
                        "[auto-start] app_version={}, ws_id={}, port={}, need_start={}",
                        app_version, ws_id, port, need_start
                    ));
                    if need_start {
                        AUTO_START_IN_PROGRESS.store(true, Ordering::SeqCst);
                        AUTO_START_STARTED_AT_MS.store(now_ms(), Ordering::SeqCst);
                        let venv_dir = openkitsune_root_dir()
                            .join("venv")
                            .to_string_lossy()
                            .to_string();
                        let ws_clone = ws_id.clone();
                        std::thread::spawn(move || {
                            let _lifecycle_guard = BACKEND_LIFECYCLE_LOCK.lock().unwrap();
                            if backend_was_manually_stopped(&ws_clone) {
                                log_to_file(&format!(
                                    "[auto-start] cancelled by manual stop for ws={}",
                                    ws_clone
                                ));
                            } else {
                                match openkitsune_service_start_impl(venv_dir, ws_clone) {
                                    Ok(status) => {
                                        log_to_file(&format!(
                                            "[auto-start] success: running={}, pid={:?}",
                                            status.running, status.pid
                                        ));
                                    }
                                    Err(e) => {
                                        log_to_file(&format!("[auto-start] FAILED: {}", e));
                                    }
                                }
                            }
                            AUTO_START_IN_PROGRESS.store(false, Ordering::SeqCst);
                            AUTO_START_STARTED_AT_MS.store(0, Ordering::SeqCst);
                        });
                    }
                }
            } else {
                log_to_file("[auto-start] skipped: no current_workspace_id in state");
            }

            // PR-F1: 启动常驻 5s 心跳。后端崩溃时连续 3 次失败（≈ 15s）就尝试
            // 自动重启 + 向前端 emit `backend:lost` / `backend:back`。
            // 旧实现仅依赖 startup_version_check 一次性探测，进程死后用户要等
            // 60+ 分钟才能在 autostart.log 里看到下一次探测。
            {
                let app_version_for_hb = app_version.clone();
                std::thread::spawn(move || {
                    let mut consecutive_failures: u32 = 0;
                    let mut last_status_was_healthy: Option<bool> = None;
                    let mut last_starting_log_at: u64 = 0;
                    loop {
                        for _ in 0..5 {
                            std::thread::sleep(std::time::Duration::from_secs(1));
                            if SHUTDOWN.load(Ordering::SeqCst) {
                                log_to_file("[heartbeat] shutdown signaled, exiting loop");
                                return;
                            }
                        }
                        let state_snap = read_state_file();
                        let ws_id = match state_snap.current_workspace_id {
                            Some(s) => s,
                            None => continue,
                        };
                        if backend_was_manually_stopped(&ws_id) {
                            consecutive_failures = 0;
                            last_status_was_healthy = None;
                            continue;
                        }
                        let port = read_workspace_api_port(&ws_id).unwrap_or(18900);
                        let healthy = is_backend_http_healthy(Some(port));
                        if SHUTDOWN.load(Ordering::SeqCst) {
                            return;
                        }
                        if healthy {
                            consecutive_failures = 0;
                            last_status_was_healthy = Some(true);
                            continue;
                        }

                        // ── 启动宽限期：PID 还在 spawn 后的 BACKEND_BOOT_GRACE_SEC 秒内 ──
                        // 后端 dual-venv hack cold start 实测需要 90~120 秒（Python
                        // import + 122 个 skills + Memory + IM channels + uvicorn bind）。
                        // 心跳 5s × 3 次失败 = 15s 就报 down 完全不合理：那时后端
                        // 才刚开始加载 skills，HTTP 还没绑定端口。
                        // 在宽限期内：
                        //   - emit `backend:status starting=true` 让 UI 显示"正在启动"
                        //   - 不发 backend:lost，不触发 auto-spawn
                        //   - 不累加 consecutive_failures
                        if backend_in_boot_grace(&ws_id) {
                            let now = now_epoch_secs();
                            // 最多每 30 秒打一条 log + emit，避免刷屏
                            if now.saturating_sub(last_starting_log_at) >= 30 {
                                log_to_file(&format!(
                                    "[heartbeat] backend in boot-grace (port={}) — skipping down/spawn",
                                    port
                                ));
                                last_starting_log_at = now;
                            }
                            consecutive_failures = 0;
                            continue;
                        }

                        consecutive_failures = consecutive_failures.saturating_add(1);
                        if consecutive_failures < 3 {
                            continue;
                        }
                        if let Some(pid_data) = read_pid_file(&ws_id) {
                            if is_pid_running(pid_data.pid) {
                                log_to_file(&format!(
                                    "[heartbeat] backend PID {} still alive; skip auto-spawn",
                                    pid_data.pid
                                ));
                                consecutive_failures = 0;
                                continue;
                            }
                        }
                        if last_status_was_healthy != Some(false) {
                            log_to_file(&format!(
                                "[heartbeat] backend down for {}s, attempting auto spawn (port={})",
                                consecutive_failures * 5,
                                port,
                            ));
                            last_status_was_healthy = Some(false);
                        }
                        if SHUTDOWN.load(Ordering::SeqCst) {
                            return;
                        }
                        if AUTO_START_IN_PROGRESS.load(Ordering::SeqCst) || pip_install_is_running() {
                            continue;
                        }
                        if external_backend_dev_mode() {
                            consecutive_failures = 0;
                            continue;
                        }
                        let _lifecycle_guard = BACKEND_LIFECYCLE_LOCK.lock().unwrap();
                        if backend_was_manually_stopped(&ws_id) {
                            consecutive_failures = 0;
                            last_status_was_healthy = None;
                            continue;
                        }
                        let venv_dir = openkitsune_root_dir().join("venv");
                        let venv_dir_str = venv_dir.to_string_lossy().to_string();
                        if managed_python_seed_path().is_none()
                            && !legacy_venv_has_openkitsune_backend(&venv_dir_str)
                        {
                            consecutive_failures = 0;
                            continue;
                        }
                        let check_result = startup_version_check(&ws_id, &app_version_for_hb, port);
                        let need_start = !matches!(check_result, VersionCheckResult::RunningOk);
                        if !need_start {
                            // 端口又被别人占了或 health 临时抖动 — 重置计数
                            consecutive_failures = 0;
                            continue;
                        }
                        AUTO_START_IN_PROGRESS.store(true, Ordering::SeqCst);
                        AUTO_START_STARTED_AT_MS.store(now_ms(), Ordering::SeqCst);
                        let venv_dir = venv_dir_str;
                        let ws_clone = ws_id.clone();
                        match openkitsune_service_start_impl(venv_dir, ws_clone) {
                            Ok(status) => log_to_file(&format!(
                                "[heartbeat] auto-spawn returned: running={}, pid={:?} (note: pid may be existing process if dedupe-skip)",
                                status.running, status.pid
                            )),
                            Err(e) => log_to_file(&format!("[heartbeat] auto-spawn FAILED: {}", e)),
                        }
                        AUTO_START_IN_PROGRESS.store(false, Ordering::SeqCst);
                        AUTO_START_STARTED_AT_MS.store(0, Ordering::SeqCst);
                        consecutive_failures = 0;
                    }
                });
            }

            Ok(())
            })();

            if let Err(ref e) = result {
                write_crash_log(&format!("Setup failed: {e}"), false);
            }
            result
        })
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                // 默认行为：关闭窗口 -> 隐藏到托盘/菜单栏常驻（用户从托盘 Quit 退出）
                api.prevent_close();
                let _ = window.hide();
            }
            _ => {}
        })
        .invoke_handler(commands::invoke_handler())
        .build(tauri::generate_context!())
    {
        Ok(a) => a,
        Err(e) => {
            let msg = format!("Tauri build failed: {e}");
            eprintln!("{msg}");
            write_crash_log(&msg, true);
            std::process::exit(1);
        }
    };

    app.run(|_app_handle, event| {
        if ui_lifecycle() == UiLifecycle::Starting {
            set_ui_lifecycle(UiLifecycle::Running);
        }
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen {
            has_visible_windows,
            ..
        } = &event
        {
            if !has_visible_windows {
                if let Some(win) = _app_handle.get_webview_window("main") {
                    let _ = win.show();
                    let _ = win.set_focus();
                }
            }
        }
        if let tauri::RunEvent::Exit = event {
            let exit_event_started = Instant::now();
            set_ui_lifecycle(UiLifecycle::Quiescing);
            SHUTDOWN.store(true, Ordering::SeqCst);
            mark_exit_handled();
            clear_frontend_session_marker();
            let cleanup_state = EXIT_CLEANUP_STATE.load(Ordering::SeqCst);
            if cleanup_state == EXIT_CLEANUP_COMPLETE {
                log_to_file(&format!(
                    "[quit] run-event-exit cleanup=skipped reason=tray-complete elapsed_ms={}",
                    exit_event_started.elapsed().as_millis()
                ));
            } else if cleanup_state == EXIT_CLEANUP_RUNNING {
                // A concurrent OS exit can race the tray worker. Do not run a
                // second cleanup over the same PIDs while that worker owns it.
                log_to_file(&format!(
                    "[quit] run-event-exit cleanup=skipped reason=cleanup-running elapsed_ms={}",
                    exit_event_started.elapsed().as_millis()
                ));
            } else if EXIT_CLEANUP_STATE
                .compare_exchange(
                    EXIT_CLEANUP_IDLE,
                    EXIT_CLEANUP_RUNNING,
                    Ordering::SeqCst,
                    Ordering::SeqCst,
                )
                .is_ok()
            {
                cleanup_backends_on_run_event_exit();
                EXIT_CLEANUP_STATE.store(EXIT_CLEANUP_COMPLETE, Ordering::SeqCst);
                log_to_file(&format!(
                    "[quit] run-event-exit cleanup=complete elapsed_ms={}",
                    exit_event_started.elapsed().as_millis()
                ));
            }
            set_ui_lifecycle(UiLifecycle::Exited);
        }
    });
}
