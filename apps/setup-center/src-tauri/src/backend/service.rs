use crate::prelude::*;

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ServiceStatus {
    pub(crate) running: bool,
    pub(crate) pid: Option<u32>,
    pid_file: String,
    managed_by: String,
    is_managed_child: bool,
    /// 后端心跳阶段："starting" | "initializing" | "http_ready" | "starting_im" | "running" | "restarting" | "stopping" | ""
    #[serde(default)]
    heartbeat_phase: String,
    /// HTTP API 是否就绪
    #[serde(default)]
    heartbeat_http_ready: bool,
    /// IM / late-bound gateway 启动路径是否已收敛
    #[serde(default)]
    heartbeat_im_ready: bool,
    /// 后端业务启动流程是否整体收敛
    #[serde(default)]
    heartbeat_ready: bool,
    /// 心跳是否过期（超过 30 秒没更新）。None = 没有心跳文件（旧版后端）
    #[serde(default)]
    heartbeat_stale: Option<bool>,
    /// 距上次心跳的秒数。None = 没有心跳文件
    #[serde(default)]
    heartbeat_age_secs: Option<f64>,
}

/// 构造 ServiceStatus，自动填充心跳信息
pub(crate) fn build_service_status(
    workspace_id: &str,
    running: bool,
    pid: Option<u32>,
    pid_file_str: String,
    managed_by: &str,
    is_managed_child: bool,
) -> ServiceStatus {
    let (
        heartbeat_phase,
        heartbeat_http_ready,
        heartbeat_im_ready,
        heartbeat_ready,
        heartbeat_stale,
        heartbeat_age_secs,
    ) = if let Some(hb) = read_heartbeat_file(workspace_id) {
        let now = now_epoch_secs() as f64;
        let age = now - hb.timestamp;
        let stale = age > 30.0; // 超过 30 秒无心跳视为过期
        (
            hb.phase,
            hb.http_ready,
            hb.im_ready,
            hb.ready,
            Some(stale),
            Some(age),
        )
    } else {
        (String::new(), false, false, false, None, None)
    };
    ServiceStatus {
        running,
        pid,
        pid_file: pid_file_str,
        managed_by: managed_by.to_string(),
        is_managed_child,
        heartbeat_phase,
        heartbeat_http_ready,
        heartbeat_im_ready,
        heartbeat_ready,
        heartbeat_stale,
        heartbeat_age_secs,
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ServiceLogChunk {
    path: String,
    content: String,
    truncated: bool,
}

#[tauri::command]
pub(crate) fn openkitsune_service_status(workspace_id: String) -> Result<ServiceStatus, String> {
    let pid_file = service_pid_file(&workspace_id);
    let pf = pid_file.to_string_lossy().to_string();

    // ── 1. 优先用 MANAGED_CHILD（精确 try_wait）──
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        if let Some(ref mut mp) = *guard {
            if mp.workspace_id == workspace_id {
                match mp.child.try_wait() {
                    Ok(None) => {
                        return Ok(build_service_status(
                            &workspace_id,
                            true,
                            Some(mp.pid),
                            pf,
                            "tauri",
                            true,
                        ));
                    }
                    _ => {
                        // 进程已退出，清理 handle、PID 文件和心跳文件
                        *guard = None;
                        let _ = fs::remove_file(&pid_file);
                        remove_heartbeat_file(&workspace_id);
                        return Ok(build_service_status(
                            &workspace_id,
                            false,
                            None,
                            pf,
                            "unknown",
                            false,
                        ));
                    }
                }
            }
        }
    }

    // ── 2. 回退到 PID 文件 ──
    if let Some(data) = read_pid_file(&workspace_id) {
        if is_pid_file_valid(&data) {
            // PID 文件有效，但如果心跳超过 60 秒没更新，进程可能卡死
            // 此时仍报告 running（让前端根据心跳状态决定是否提示用户）
            return Ok(build_service_status(
                &workspace_id,
                true,
                Some(data.pid),
                pf,
                status_managed_by_from_pid_file(&data),
                false,
            ));
        } else {
            // Stale PID，清理 PID 文件和心跳文件
            let _ = fs::remove_file(&pid_file);
            remove_heartbeat_file(&workspace_id);
        }
    }
    Ok(build_service_status(
        &workspace_id,
        false,
        None,
        pf,
        "unknown",
        false,
    ))
}

/// 检查进程是否仍在运行（供前端心跳二次确认用）。
/// 除了检查 PID 存活，还验证进程身份和心跳文件。
/// 如果心跳超过 60 秒没更新且 HTTP 不可达，自动清理进程和 PID 文件。
#[tauri::command]
pub(crate) fn openkitsune_check_pid_alive(workspace_id: String) -> Result<bool, String> {
    // 优先 MANAGED_CHILD（由 Tauri 直接管理的子进程，不需要额外校验身份）
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        if let Some(ref mut mp) = *guard {
            if mp.workspace_id == workspace_id {
                let alive = mp.child.try_wait().ok().flatten().is_none();
                if !alive {
                    // 进程已退出，清理
                    *guard = None;
                    let _ = fs::remove_file(service_pid_file(&workspace_id));
                    remove_heartbeat_file(&workspace_id);
                }
                return Ok(alive);
            }
        }
    }
    // 回退到 PID 文件：检查 PID 存活 + 验证进程身份
    if let Some(data) = read_pid_file(&workspace_id) {
        if !is_pid_running(data.pid) {
            // 进程已死，清理 stale PID 文件和心跳文件
            let _ = fs::remove_file(service_pid_file(&workspace_id));
            remove_heartbeat_file(&workspace_id);
            return Ok(false);
        }
        // PID 存活，但需验证是否真的是 OpenKitsune 进程
        if !is_openkitsune_process(data.pid) {
            // PID 被其他进程复用了，清理 stale PID 文件和心跳文件
            let _ = fs::remove_file(service_pid_file(&workspace_id));
            remove_heartbeat_file(&workspace_id);
            return Ok(false);
        }
        // 进程身份已确认，但检查心跳是否严重过期（> 60 秒）
        // 心跳过期意味着进程虽然存活但可能已经卡死
        if let Some(true) = is_heartbeat_stale(&workspace_id, 60) {
            // 心跳严重过期时先复核 HTTP health；只在 API 也不可达时才清理，
            // 防止心跳文件写入异常造成“后端仍可用却被误杀”。
            let port = read_workspace_api_port(&workspace_id);
            if should_cleanup_stale_heartbeat(Some(true), is_backend_http_healthy(port)) {
                let _ = graceful_stop_pid(data.pid, port);
                let _ = fs::remove_file(service_pid_file(&workspace_id));
                remove_heartbeat_file(&workspace_id);
                return Ok(false);
            }
        }
        return Ok(true);
    }
    Ok(false)
}

#[cfg(windows)]
pub(crate) fn apply_no_window(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    // CREATE_NO_WINDOW: avoid flashing a black console window for spawned commands.
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
pub(crate) fn apply_no_window(_cmd: &mut Command) {}

/// 清除可能干扰 Python 运行环境的外部环境变量。
///
/// 常见场景：用户安装了 Anaconda/Miniconda、系统设置了 PYTHONPATH 等，
/// 这些变量会在 Python 启动时被注入到 sys.path 最前面，覆盖托管虚拟环境
/// 中的包（如 pydantic_core），导致 C 扩展不兼容而崩溃。
///
/// 同时清除 pip 行为干扰变量（PIP_TARGET/PIP_PREFIX 等），
/// 避免 pip install --target 时被用户配置覆盖。
pub(crate) fn strip_harmful_python_env(cmd: &mut Command) {
    // Python 运行时变量
    cmd.env_remove("PYTHONPATH");
    cmd.env_remove("PYTHONHOME");
    cmd.env_remove("PYTHONSTARTUP");
    // 虚拟环境 / Conda 变量
    cmd.env_remove("VIRTUAL_ENV");
    cmd.env_remove("CONDA_PREFIX");
    cmd.env_remove("CONDA_DEFAULT_ENV");
    cmd.env_remove("CONDA_SHLVL");
    cmd.env_remove("CONDA_PYTHON_EXE");
    // pip 行为干扰变量
    cmd.env_remove("PIP_TARGET");
    cmd.env_remove("PIP_PREFIX");
    cmd.env_remove("PIP_USER");
    cmd.env_remove("PIP_INDEX_URL");
    cmd.env_remove("PIP_REQUIRE_VIRTUALENV");
}

pub(crate) fn strip_harmful_toolchain_env(cmd: &mut Command) {
    // SSL and proxy-like CA overrides from Conda/Homebrew often point at files
    // outside the managed runtime. Core/bootstrap will inject its own CA bundle.
    cmd.env_remove("SSL_CERT_FILE");
    cmd.env_remove("SSL_CERT_DIR");
    cmd.env_remove("REQUESTS_CA_BUNDLE");
    cmd.env_remove("CURL_CA_BUNDLE");
    cmd.env_remove("NODE_EXTRA_CA_CERTS");
    cmd.env_remove("NODE_TLS_REJECT_UNAUTHORIZED");
    cmd.env_remove("DYLD_LIBRARY_PATH");
    cmd.env_remove("DYLD_INSERT_LIBRARIES");
    cmd.env_remove("DYLD_FRAMEWORK_PATH");
    cmd.env_remove("DYLD_FALLBACK_LIBRARY_PATH");

    // Node/npm/corepack writes must not fall into a user global prefix/cache
    // when OpenKitsune is creating or repairing its own toolchain.
    cmd.env_remove("NODE_PATH");
    cmd.env_remove("NPM_CONFIG_PREFIX");
    cmd.env_remove("NPM_CONFIG_CACHE");
    cmd.env_remove("npm_config_prefix");
    cmd.env_remove("npm_config_cache");
    cmd.env_remove("COREPACK_HOME");

    if cfg!(target_os = "linux") {
        cmd.env_remove("LD_LIBRARY_PATH");
        cmd.env_remove("LD_PRELOAD");
        cmd.env_remove("LIBRARY_PATH");
        cmd.env_remove("PKG_CONFIG_PATH");
    }
}

pub(crate) fn apply_playwright_browser_env(cmd: &mut Command, modules_root: &Path) {
    let browsers_dir = modules_root.join("browser").join("browsers");
    if browsers_dir.is_dir() {
        cmd.env("PLAYWRIGHT_BROWSERS_PATH", browsers_dir);
    }
}

pub(crate) async fn spawn_blocking_result<R: Send + 'static>(
    f: impl FnOnce() -> Result<R, String> + Send + 'static,
) -> Result<R, String> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|e| format!("后台任务失败（join error）: {e}"))?
}

/// Strip surrounding quotes and inline comments from a raw .env value.
///
/// - Quoted values (`"..."` or `'...'`): return content between quotes literally.
/// - Unquoted values: strip inline comment (`#` preceded by whitespace).
#[allow(dead_code)]
pub(crate) fn clean_env_value(raw: &str) -> String {
    let v = raw.trim();
    if v.len() >= 2 {
        let bytes = v.as_bytes();
        if (bytes[0] == b'"' && bytes[v.len() - 1] == b'"')
            || (bytes[0] == b'\'' && bytes[v.len() - 1] == b'\'')
        {
            return v[1..v.len() - 1].to_string();
        }
    }
    // Unquoted: strip inline comment (# preceded by space or tab)
    for pat in [" #", "\t#"] {
        if let Some(pos) = v.find(pat) {
            return v[..pos].trim_end().to_string();
        }
    }
    v.to_string()
}

#[allow(dead_code)]
pub(crate) fn read_env_kv(path: &Path) -> Vec<(String, String)> {
    let Ok(content) = fs::read_to_string(path) else {
        return vec![];
    };
    let mut out = vec![];
    for line in content.lines() {
        let t = line.trim();
        if t.is_empty() || t.starts_with('#') || !t.contains('=') {
            continue;
        }
        let (k, v) = t.split_once('=').unwrap_or((t, ""));
        let key = k.trim();
        if key.is_empty() {
            continue;
        }
        out.push((key.to_string(), clean_env_value(v)));
    }
    out
}

#[tauri::command]
pub(crate) async fn openkitsune_service_start(
    venv_dir: String,
    workspace_id: String,
) -> Result<ServiceStatus, String> {
    {
        let _lifecycle_guard = BACKEND_LIFECYCLE_LOCK.lock().unwrap();
        set_backend_manually_stopped(&workspace_id, false)?;
    }
    let task_started = Instant::now();
    let log_workspace_id = workspace_id.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        openkitsune_service_start_impl(venv_dir, workspace_id)
    })
    .await
    .map_err(|e| format!("backend start task failed: {e}"))?;
    log_to_file(&format!(
        "[service_start] async command finished: ws={}, elapsed_ms={}, status={}",
        log_workspace_id,
        task_started.elapsed().as_millis(),
        if result.is_ok() { "ok" } else { "error" }
    ));
    result
}

pub(crate) fn openkitsune_service_start_impl(
    venv_dir: String,
    workspace_id: String,
) -> Result<ServiceStatus, String> {
    let service_start_started = Instant::now();
    log_to_file(&format!(
        "[service_start] called: ws={}, venv={}",
        workspace_id, venv_dir
    ));
    // ── 进程级互斥：同一 workspace 在 SERVICE_START_DEDUPE_MS 窗口内拒绝重复 spawn。
    // 解决 autostart.log 里 27s 内 5 次 spawn pid 的现场表现：前端在 health
    // check 还没响应时反复 invoke，下游 try_acquire_start_lock 的文件锁有
    // 短暂失效窗，需要在更外层加一层时间窗去重。命中时直接返回当前已知
    // ServiceStatus（让前端继续轮询 health 即可），不抛错避免触发 toast。
    {
        let mut last_map = SERVICE_START_LAST_AT.lock().unwrap();
        let now = now_ms();
        if let Some(&last) = last_map.get(&workspace_id) {
            let elapsed = now.saturating_sub(last);
            if elapsed < SERVICE_START_DEDUPE_MS {
                log_to_file(&format!(
                    "[service_start] dedupe-skip ws={} elapsed_ms={}",
                    workspace_id, elapsed
                ));
                let pid_file = service_pid_file(&workspace_id);
                let pf = pid_file.to_string_lossy().to_string();
                let pid_data = read_pid_file(&workspace_id);
                let pid_opt = pid_data.as_ref().map(|data| data.pid);
                let running = pid_data.as_ref().map(is_pid_file_valid).unwrap_or(false);
                let managed_by = pid_data
                    .as_ref()
                    .map(status_managed_by_from_pid_file)
                    .unwrap_or("unknown");
                return Ok(build_service_status(
                    &workspace_id,
                    running,
                    pid_opt,
                    pf,
                    managed_by,
                    false,
                ));
            }
        }
        last_map.insert(workspace_id.clone(), now);
    }

    fs::create_dir_all(run_dir()).map_err(|e| {
        let msg = format!("create run dir failed: {e}");
        log_to_file(&format!("[service_start] FAIL: {}", msg));
        msg
    })?;
    let pid_file = service_pid_file(&workspace_id);
    let pf = pid_file.to_string_lossy().to_string();

    // ── 0. 启动前清理旧的心跳文件（避免新进程读到旧心跳） ──
    remove_heartbeat_file(&workspace_id);

    // ── 1. 检查是否已在运行（通过 MANAGED_CHILD 或 PID 文件）──
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        if let Some(ref mut mp) = *guard {
            if mp.workspace_id == workspace_id {
                match mp.child.try_wait() {
                    Ok(None) => {
                        return Ok(build_service_status(
                            &workspace_id,
                            true,
                            Some(mp.pid),
                            pf,
                            "tauri",
                            true,
                        ));
                    }
                    _ => {
                        *guard = None;
                    }
                }
            }
        }
    }
    if let Some(data) = read_pid_file(&workspace_id) {
        if is_pid_file_valid(&data) {
            // 进程已在运行，但检查心跳是否严重过期（可能卡死）
            if let Some(true) = is_heartbeat_stale(&workspace_id, 60) {
                // 心跳严重过期时先复核 HTTP health；如果 API 仍正常，
                // 继续复用现有进程，不启动第二个后端。
                let port = read_workspace_api_port(&workspace_id);
                if should_cleanup_stale_heartbeat(Some(true), is_backend_http_healthy(port)) {
                    let _ = graceful_stop_pid(data.pid, port);
                    let _ = fs::remove_file(&pid_file);
                    remove_heartbeat_file(&workspace_id);
                } else {
                    return Ok(build_service_status(
                        &workspace_id,
                        true,
                        Some(data.pid),
                        pf,
                        status_managed_by_from_pid_file(&data),
                        false,
                    ));
                }
            } else {
                return Ok(build_service_status(
                    &workspace_id,
                    true,
                    Some(data.pid),
                    pf,
                    status_managed_by_from_pid_file(&data),
                    false,
                ));
            }
        } else {
            let _ = fs::remove_file(&pid_file);
            remove_heartbeat_file(&workspace_id);
        }
    }

    // ── 2. 获取启动锁（防止竞态双启动）──
    if !try_acquire_start_lock(&workspace_id) {
        return Err("另一个启动操作正在进行中，请稍候".to_string());
    }
    struct LockGuard(String);
    impl Drop for LockGuard {
        fn drop(&mut self) {
            release_start_lock(&self.0);
        }
    }
    let _lock_guard = LockGuard(workspace_id.clone());

    let ws_dir = workspace_dir(&workspace_id);
    ensure_workspace_scaffold(&ws_dir)?;

    // ── 2.5 端口可用性预检 ──
    // 在 spawn 之前检查端口是否被占用（旧进程残留、TIME_WAIT、其他程序等）。
    // Python 端也有重试，但尽早发现可以给用户更明确的提示。
    let effective_port = read_workspace_api_port(&workspace_id).unwrap_or(18900);
    if !check_port_available(effective_port) {
        // 端口被占用，等待最多 10 秒（处理 TIME_WAIT 等场景）
        if !wait_for_port_free(effective_port, 10_000) {
            return Err(format!(
                "端口 {} 已被占用，无法启动后端服务。\n\
                 可能原因：上次关闭后端口尚未释放、或有其他程序占用该端口。\n\
                 请稍后重试，或检查是否有其他程序占用端口 {}。",
                effective_port, effective_port
            ));
        }
    }

    // Resolve the managed app-venv backend (legacy venv is compatibility-only).
    let backend_resolve_started = Instant::now();
    let (backend_exe, backend_args) = get_backend_executable(&venv_dir);
    log_to_file(&format!(
        "[service_start] backend executable resolved in {}ms",
        backend_resolve_started.elapsed().as_millis()
    ));
    log_to_file(&format!(
        "[service_start] exe={}, exists={}",
        backend_exe.display(),
        backend_exe.exists()
    ));
    if !backend_exe.exists() {
        return Err(format!(
            "后端可执行文件不存在: {}\n\
             请在设置中心修复 Python 运行环境，或重新安装桌面端。",
            backend_exe.to_string_lossy(),
        ));
    }

    let log_dir = ws_dir.join("logs");
    fs::create_dir_all(&log_dir).map_err(|e| format!("create logs dir failed: {e}"))?;
    let log_path = log_dir.join("openkitsune-serve.log");
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("open log failed: {e}"))?;

    let mut cmd = Command::new(&backend_exe);
    cmd.current_dir(&ws_dir);
    cmd.args(&backend_args);

    // ── 注入 dual runtime 环境 ──
    // 清除 Anaconda/PYTHONPATH 等污染源，同时把 agent-venv 的 Scripts/bin
    // 前置到 PATH，让后端工具执行 python/pip 时自然落到 agent tools venv。
    apply_dual_runtime_env(&mut cmd);

    // Force UTF-8 output on Windows and make logs clean & realtime.
    // Without this, Rich may try to write unicode symbols (e.g. ✓) using GBK and crash.
    cmd.env("PYTHONUTF8", "1");
    cmd.env("PYTHONIOENCODING", "utf-8");
    cmd.env("PYTHONUNBUFFERED", "1");
    // Disable colored / styled output to avoid ANSI escape codes in log files.
    cmd.env("NO_COLOR", "1");
    let spawn_started_at_ms = now_epoch_secs().saturating_mul(1000);
    cmd.env("OPENKITSUNE_DESKTOP_SESSION_TOKEN", desktop_session_token());
    cmd.env(
        "OPENKITSUNE_SPAWN_STARTED_AT_MS",
        spawn_started_at_ms.to_string(),
    );

    // .env 由 Python 端的 load_dotenv(override=True) 自行加载，
    // 不再由 Rust 注入，避免编码/BOM 问题导致 Key 丢失或损坏值抢占。
    // Rust 只注入 Python 自己无法确定的路径类环境变量。
    cmd.env(
        "LLM_ENDPOINTS_CONFIG",
        ws_dir.join("data").join("llm_endpoints.json"),
    );
    cmd.env(
        "OPENKITSUNE_ROOT",
        openkitsune_root_dir().to_string_lossy().to_string(),
    );

    // 设置可选模块路径（已安装的可选模块 site-packages）
    // 重要：不能使用 PYTHONPATH！Python 启动时 PYTHONPATH 会被插入到 sys.path
    // 最前面，覆盖托管虚拟环境中的包（如 pydantic），导致外部 pydantic 的
    // C 扩展 pydantic_core._pydantic_core 加载失败，进程在 import 阶段崩溃。
    // 改用自定义环境变量 OPENKITSUNE_MODULE_PATHS，由 Python 端的
    // inject_module_paths() 读取并 append 到 sys.path 末尾。
    if let Some(extra_path) = build_modules_pythonpath() {
        cmd.env("OPENKITSUNE_MODULE_PATHS", extra_path);
    }

    // Playwright 浏览器二进制路径
    // browser 模块已包含在 core wheel 中；这里兼容旧版外置浏览器安装路径。
    apply_playwright_browser_env(&mut cmd, &modules_dir());

    // detach + redirect io
    cmd.stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::from(
            log_file
                .try_clone()
                .map_err(|e| format!("clone log failed: {e}"))?,
        ))
        .stderr(std::process::Stdio::from(log_file));

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x00000008u32 | 0x00000200u32 | 0x0800_0000u32); // DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    }

    let spawn_started = Instant::now();
    let child = cmd.spawn().map_err(|e| {
        let msg = format!("spawn openkitsune serve failed: {e}");
        log_to_file(&format!("[service_start] {}", msg));
        msg
    })?;
    let pid = child.id();
    log_to_file(&format!(
        "[service_start] spawned pid={} in {}ms",
        pid,
        spawn_started.elapsed().as_millis()
    ));
    let started_at = now_epoch_secs();

    // ── 3. 写 JSON PID 文件 ──
    write_pid_file(&workspace_id, pid, "tauri")?;

    // ── 4. 存入 MANAGED_CHILD ──
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        *guard = Some(ManagedProcess {
            child,
            workspace_id: workspace_id.clone(),
            pid,
            started_at,
        });
    }

    // Confirm the process is still alive after spawning.
    // 实测在 dual-venv hack 下，Python 解释器 import 失败/路径错误等
    // "立即退出"故障通常发生在 spawn 后 1-3 秒内。原来 sleep 500ms 仅能
    // 抓到极少数现场，导致 service_start 误返回 Ok，前端跟着进入 starting
    // 死循环。改成 6 次 × 500ms 轮询，命中即停，最多多等 2.5s 即可换来
    // 准确的失败判定。
    let mut alive = true;
    for _ in 0..6 {
        std::thread::sleep(std::time::Duration::from_millis(500));
        if !is_pid_running(pid) {
            alive = false;
            break;
        }
    }
    if !alive {
        {
            let mut guard = MANAGED_CHILD.lock().unwrap();
            if let Some(ref mp) = *guard {
                if mp.pid == pid {
                    *guard = None;
                }
            }
        }
        let _ = fs::remove_file(&pid_file);
        tail_serve_log_to_autostart(&log_path, 8 * 1024);
        let tail = fs::read_to_string(&log_path)
            .ok()
            .and_then(|s| {
                if s.len() > 6000 {
                    Some(s[s.len() - 6000..].to_string())
                } else {
                    Some(s)
                }
            })
            .unwrap_or_default();
        return Err(format!(
            "openkitsune serve 似乎启动后立即退出（PID={pid}）。\n请查看服务日志：{}\n\n--- log tail ---\n{}",
            log_path.to_string_lossy(),
            tail
        ));
    }

    log_to_file(&format!(
        "[service_start] completed in {}ms",
        service_start_started.elapsed().as_millis()
    ));
    Ok(build_service_status(
        &workspace_id,
        true,
        Some(pid),
        pf,
        "tauri",
        true,
    ))
}

#[tauri::command]
pub(crate) fn prepare_backend_manual_stop(workspace_id: String) -> Result<(), String> {
    let _lifecycle_guard = BACKEND_LIFECYCLE_LOCK.lock().unwrap();
    set_backend_manually_stopped(&workspace_id, true)?;
    log_to_file(&format!(
        "[service_stop] recorded manual stop intent for ws={}",
        workspace_id
    ));
    Ok(())
}

#[tauri::command]
pub(crate) fn openkitsune_service_stop(workspace_id: String) -> Result<ServiceStatus, String> {
    let _lifecycle_guard = BACKEND_LIFECYCLE_LOCK.lock().unwrap();
    set_backend_manually_stopped(&workspace_id, true)?;
    let pid_file = service_pid_file(&workspace_id);
    let port = read_workspace_api_port(&workspace_id);
    let effective_port = port.unwrap_or(18900);

    // ── 1. MANAGED_CHILD handle ──
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        if let Some(mut mp) = guard.take() {
            if mp.workspace_id == workspace_id {
                let old_pid = mp.pid;
                let spawn_started_at = mp.started_at.saturating_mul(1000);
                let clean_shutdown = graceful_stop_pid(mp.pid, port).unwrap_or(false);
                if clean_shutdown && !is_pid_running(old_pid) {
                    write_last_clean_shutdown_marker(&workspace_id, old_pid, spawn_started_at);
                }
                if is_pid_running(mp.pid) {
                    let _ = mp.child.kill();
                    let _ = mp.child.wait();
                }
                let _ = fs::remove_file(&pid_file);
                // 等待端口释放（最多 10 秒），确保后续重启不会遇到端口冲突
                let _ = wait_for_port_free(effective_port, 10_000);
                remove_heartbeat_file(&workspace_id);
                return Ok(build_service_status(
                    &workspace_id,
                    false,
                    None,
                    pid_file.to_string_lossy().to_string(),
                    "unknown",
                    false,
                ));
            } else {
                *guard = Some(mp);
            }
        }
    }

    // ── 2. PID 文件回退 ──
    let pid = read_pid_file(&workspace_id).map(|d| d.pid);
    if let Some(pid) = pid {
        // 强制杀干净：如果杀不掉，要显式报错（避免 UI 显示“已停止”但后台仍残留）。
        let clean_shutdown =
            graceful_stop_pid(pid, port).map_err(|e| format!("failed to stop service: {e}"))?;
        if clean_shutdown && !is_pid_running(pid) {
            write_last_clean_shutdown_marker(&workspace_id, pid, 0);
        }
    }
    let _ = fs::remove_file(&pid_file);
    remove_heartbeat_file(&workspace_id);
    // 等待端口释放（最多 10 秒），确保后续重启不会遇到端口冲突
    let _ = wait_for_port_free(effective_port, 10_000);
    Ok(build_service_status(
        &workspace_id,
        false,
        None,
        pid_file.to_string_lossy().to_string(),
        "unknown",
        false,
    ))
}

#[tauri::command]
pub(crate) fn openkitsune_service_log(
    workspace_id: String,
    tail_bytes: Option<u64>,
) -> Result<ServiceLogChunk, String> {
    let ws_dir = workspace_dir(&workspace_id);
    let log_path = ws_dir.join("logs").join("openkitsune-serve.log");
    let path_str = log_path.to_string_lossy().to_string();
    let tail = tail_bytes.unwrap_or(40_000).min(400_000);

    if !log_path.exists() {
        return Ok(ServiceLogChunk {
            path: path_str,
            content: "".into(),
            truncated: false,
        });
    }

    let mut f = std::fs::File::open(&log_path).map_err(|e| format!("open log failed: {e}"))?;
    let len = f
        .metadata()
        .map_err(|e| format!("stat log failed: {e}"))?
        .len();
    let start = len.saturating_sub(tail);
    let truncated = start > 0;
    f.seek(SeekFrom::Start(start))
        .map_err(|e| format!("seek log failed: {e}"))?;
    let mut buf = Vec::new();
    f.read_to_end(&mut buf)
        .map_err(|e| format!("read log failed: {e}"))?;
    let content = String::from_utf8_lossy(&buf).to_string();

    Ok(ServiceLogChunk {
        path: path_str,
        content,
        truncated,
    })
}

#[tauri::command]
pub(crate) fn autostart_is_enabled(app: tauri::AppHandle) -> Result<bool, String> {
    #[cfg(desktop)]
    {
        let mgr = app.autolaunch();
        return mgr
            .is_enabled()
            .map_err(|e| format!("autostart is_enabled failed: {e}"));
    }
    #[cfg(not(desktop))]
    {
        let _ = app;
        Ok(false)
    }
}

#[tauri::command]
pub(crate) fn autostart_set_enabled(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    #[cfg(desktop)]
    {
        let mgr = app.autolaunch();
        if enabled {
            mgr.enable()
                .map_err(|e| format!("autostart enable failed: {e}"))?;
        } else {
            mgr.disable()
                .map_err(|e| format!("autostart disable failed: {e}"))?;
        }
        // 同步持久化到 state file，用于下次启动时的自修复检查
        let mut state = read_state_file();
        state.auto_start_backend = Some(enabled);
        write_state_file(&state)
            .map_err(|e| format!("autostart preference save failed: {e}"))?;
        return Ok(());
    }
    #[cfg(not(desktop))]
    {
        let _ = (app, enabled);
        Ok(())
    }
}

/// 前端调用：查询后端是否正在自动启动中。
/// 返回 true 时前端应禁用启动/重启按钮并显示"正在自动启动服务"提示。
///
/// 判定优先级：
/// 1. `AUTO_START_IN_PROGRESS` 为 true 且未超时 — 自动启动 spawn 线程仍在跑
/// 2. 后端 PID 文件存在但仍处于 BOOT_GRACE 期 + HTTP 不可达 — 进程已 spawn
///    但还在 cold-start（dual-venv hack 实测要 90~120 秒）
///
/// 第 2 条是关键：spawn 调用本身是同步立即返回的，AUTO_START_IN_PROGRESS
/// 在 spawn 返回后立即被清掉，但此时后端可能还要 90 秒才能 HTTP ready。
/// 老逻辑会让前端在 spawn 返回后立刻把 UI 从"启动中"切回"未启动"，
/// 等 90 秒后端真起来再切回"运行中"——这就是用户感知到的诡异闪烁。
#[tauri::command]
pub(crate) fn is_backend_auto_starting() -> bool {
    // 优先级 1：显式的 AUTO_START_IN_PROGRESS flag
    if AUTO_START_IN_PROGRESS.load(Ordering::SeqCst) {
        let started_at = AUTO_START_STARTED_AT_MS.load(Ordering::SeqCst);
        if started_at > 0 {
            let elapsed = now_ms().saturating_sub(started_at);
            if elapsed >= AUTO_START_TIMEOUT_MS {
                log_to_file(&format!(
                    "[auto-start] is_backend_auto_starting timeout after {}ms, clearing flag",
                    elapsed
                ));
                AUTO_START_IN_PROGRESS.store(false, Ordering::SeqCst);
                AUTO_START_STARTED_AT_MS.store(0, Ordering::SeqCst);
            } else {
                return true;
            }
        } else {
            return true;
        }
    }
    // 优先级 2：BOOT_GRACE — 进程已 spawn、PID 还活着、HTTP 还没起来
    let state = read_state_file();
    if let Some(ws_id) = state.current_workspace_id {
        if backend_in_boot_grace(&ws_id) {
            let port = read_workspace_api_port(&ws_id).unwrap_or(18900);
            if !is_backend_http_healthy(Some(port)) {
                return true;
            }
        }
    }
    false
}

/// 前端"重试启动/修复"按钮调用：先把残骸 venv 和 manifest 删干净，
/// 然后重新 ensure dual runtime venv。Bug-rescue 路径，正常启动不会走这里。
///
/// 老的"重试启动/修复"只是再次调 `openkitsune_service_start`，但 `ensure_venv`
/// 的早期健康检查会被残骸 launcher 蒙混通过、直接 return Ok 而不重建 venv，
/// 用户怎么点都修不好——必须先把 app-venv 目录砍了再重建。
#[tauri::command]
pub(crate) fn repair_runtime_env() -> Result<String, String> {
    let mut report = String::new();
    report.push_str("runtime repair started\n");

    let state = read_state_file();
    if let Some(ws_id) = state.current_workspace_id.clone() {
        match openkitsune_service_stop(ws_id.clone()) {
            Ok(_) => report.push_str(&format!("stopped backend for workspace {}\n", ws_id)),
            Err(e) => report.push_str(&format!("warn: stop backend for {} failed: {}\n", ws_id, e)),
        }
    }

    let evidence_dir = runtime_root_dir()
        .join("reports")
        .join(format!("pre-repair-{}", now_epoch_secs()));
    if let Err(e) = fs::create_dir_all(&evidence_dir) {
        report.push_str(&format!("warn: create evidence dir failed: {}\n", e));
    } else {
        for path in [
            runtime_manifest_path(),
            runtime_logs_dir().join("app-venv.log"),
            runtime_logs_dir().join("agent-venv.log"),
        ] {
            if path.exists() {
                if let Some(name) = path.file_name() {
                    let dest = evidence_dir.join(name);
                    match fs::copy(&path, &dest) {
                        Ok(_) => report.push_str(&format!("saved evidence {}\n", dest.display())),
                        Err(e) => report.push_str(&format!(
                            "warn: save evidence {} failed: {}\n",
                            path.display(),
                            e
                        )),
                    }
                }
            }
        }
    }

    for dir in [app_venv_dir(), agent_venv_dir()] {
        if dir.exists() {
            match fs::remove_dir_all(&dir) {
                Ok(()) => report.push_str(&format!("removed {}\n", dir.display())),
                Err(e) => {
                    report.push_str(&format!("warn: remove {} failed: {}\n", dir.display(), e));
                }
            }
        }
    }
    let manifest = runtime_manifest_path();
    if manifest.exists() {
        match fs::remove_file(&manifest) {
            Ok(()) => report.push_str(&format!("removed {}\n", manifest.display())),
            Err(e) => {
                report.push_str(&format!(
                    "warn: remove {} failed: {}\n",
                    manifest.display(),
                    e
                ));
            }
        }
    }
    let app_venv_log = runtime_logs_dir().join("app-venv.log");
    if app_venv_log.exists() {
        let _ = fs::remove_file(&app_venv_log);
    }
    let agent_venv_log = runtime_logs_dir().join("agent-venv.log");
    if agent_venv_log.exists() {
        let _ = fs::remove_file(&agent_venv_log);
    }
    quarantine_runtime_uv_cache(&mut report);
    match ensure_dual_runtime_env() {
        Ok(info) => {
            report.push_str(&format!(
                "ok: app_python={} agent_python={}\n",
                info.app_python.display(),
                info.agent_python.display()
            ));
            Ok(report)
        }
        Err(e) => {
            write_runtime_failure_manifest(&e);
            report.push_str(&format!("ensure_dual_runtime_env failed: {}\n", e));
            Err(report)
        }
    }
}

#[tauri::command]
pub(crate) fn get_auto_start_backend() -> Result<bool, String> {
    let state = read_state_file();
    Ok(state.auto_start_backend.unwrap_or(false))
}

#[tauri::command]
pub(crate) fn set_auto_start_backend(enabled: bool) -> Result<(), String> {
    let mut state = read_state_file();
    state.auto_start_backend = Some(enabled);
    write_state_file(&state)
}

#[tauri::command]
pub(crate) fn get_auto_update() -> Result<bool, String> {
    let state = read_state_file();
    Ok(state.auto_update.unwrap_or(true))
}

#[tauri::command]
pub(crate) fn set_auto_update(enabled: bool) -> Result<(), String> {
    let mut state = read_state_file();
    state.auto_update = Some(enabled);
    write_state_file(&state)
}

/// 前端心跳检测到后端状态变化时调用，更新托盘 tooltip
/// status: "alive" | "degraded" | "dead"
/// im_summary: 可选的 IM 通道状态摘要（如 "TG:✓ FS:✓ WX:✗"）
#[tauri::command]
pub(crate) fn set_tray_backend_status(
    app: tauri::AppHandle,
    status: String,
    im_summary: Option<String>,
) -> Result<(), String> {
    let base = match status.as_str() {
        "alive" => "OpenKitsune - Running",
        "degraded" => "OpenKitsune - Backend Unresponsive",
        "dead" => "OpenKitsune - Backend Stopped",
        _ => "OpenKitsune",
    };
    let tooltip = if let Some(ref im) = im_summary {
        if !im.is_empty() {
            format!("{}\nIM: {}", base, im)
        } else {
            base.to_string()
        }
    } else {
        base.to_string()
    };
    // 更新所有 tray icon 的 tooltip
    if let Some(tray) = app.tray_by_id("main_tray") {
        let _ = tray.set_tooltip(Some(tooltip));
    }

    // 后端死亡时发送系统通知
    if status == "dead" {
        #[cfg(windows)]
        {
            // 使用 Windows toast notification via PowerShell
            // 关键：AUMID 必须与 NSIS 安装器在开始菜单快捷方式上设置的一致（即 tauri.conf.json 的 identifier），
            // 否则 Windows 无法关联到已注册的应用，导致通知内容为空。
            // 同时在注册表注册 AUMID 以确保通知正常显示。
            let mut cmd = Command::new("powershell");
            cmd.args([
                "-NoProfile", "-NonInteractive", "-Command",
                "try { \
                    $aumid = 'com.openkitsune.setupcenter'; \
                    $rp = \"HKCU:\\SOFTWARE\\Classes\\AppUserModelId\\$aumid\"; \
                    if (!(Test-Path $rp)) { New-Item $rp -Force | Out-Null; Set-ItemProperty $rp -Name DisplayName -Value 'OpenKitsune Desktop' }; \
                    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; \
                    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); \
                    $t = $xml.GetElementsByTagName('text'); \
                    $t[0].AppendChild($xml.CreateTextNode('OpenKitsune')) | Out-Null; \
                    $t[1].AppendChild($xml.CreateTextNode('Backend service has stopped')) | Out-Null; \
                    $n = [Windows.UI.Notifications.ToastNotification]::new($xml); \
                    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($n) \
                } catch {}"
            ]);
            apply_no_window(&mut cmd);
            let _ = cmd.spawn();
        }
        #[cfg(not(windows))]
        {
            // macOS: use osascript
            let _ = Command::new("osascript")
                .args([
                    "-e",
                    "display notification \"Backend service has stopped\" with title \"OpenKitsune\"",
                ])
                .spawn();
        }
    }
    Ok(())
}

pub(crate) fn scan_openkitsune_orphans_with_timing(
    context: &str,
    total_started: Instant,
) -> Vec<u32> {
    let scan_started = Instant::now();
    let killed = kill_openkitsune_orphans();
    log_to_file(&format!(
        "[quit] orphan-scan context={} killed_count={} elapsed_ms={} total_elapsed_ms={}",
        context,
        killed.len(),
        scan_started.elapsed().as_millis(),
        total_started.elapsed().as_millis()
    ));
    killed
}

pub(crate) fn run_tray_quit_cleanup(app: tauri::AppHandle) {
    let quit_started = Instant::now();
    let mut handled_pids = HashSet::new();

    // Stop the directly managed child first so its Child handle can be reaped.
    {
        let mut guard = MANAGED_CHILD.lock().unwrap();
        if let Some(mut mp) = guard.take() {
            handled_pids.insert(mp.pid);
            let port = read_workspace_api_port(&mp.workspace_id);
            let _ = graceful_stop_pid(mp.pid, port);
            if is_pid_running(mp.pid) {
                let force_kill_started = Instant::now();
                let kill_result = mp.child.kill();
                log_to_file(&format!(
                    "[quit] force-kill pid={} source=managed-child success={} elapsed_ms={} total_elapsed_ms={}",
                    mp.pid,
                    kill_result.is_ok(),
                    force_kill_started.elapsed().as_millis(),
                    quit_started.elapsed().as_millis()
                ));
                let _ = mp.child.wait();
            }
            let _ = fs::remove_file(service_pid_file(&mp.workspace_id));
            remove_heartbeat_file(&mp.workspace_id);
        }
    }

    // A managed child normally also has a PID file. HashSet keeps that PID from
    // receiving a second HTTP shutdown/kill if the file survived the first step.
    for ent in list_service_pids() {
        if handled_pids.insert(ent.pid) {
            let port = read_workspace_api_port(&ent.workspace_id);
            let _ = stop_service_pid_entry(&ent, port);
        } else {
            let _ = fs::remove_file(PathBuf::from(&ent.pid_file));
            remove_heartbeat_file(&ent.workspace_id);
            log_to_file(&format!(
                "[quit] pid-deduplicated pid={} workspace={} total_elapsed_ms={}",
                ent.pid,
                ent.workspace_id,
                quit_started.elapsed().as_millis()
            ));
        }
    }

    scan_openkitsune_orphans_with_timing("tray-cleanup", quit_started);
    thread::sleep(Duration::from_millis(600));

    let mut verified_pids = HashSet::new();
    let still_pid = list_service_pids()
        .into_iter()
        .filter(|entry| verified_pids.insert(entry.pid) && is_pid_running(entry.pid))
        .collect::<Vec<_>>();
    let still_orphans = scan_openkitsune_orphans_with_timing("tray-verify", quit_started);

    if still_pid.is_empty() && still_orphans.is_empty() {
        EXIT_CLEANUP_STATE.store(EXIT_CLEANUP_COMPLETE, Ordering::SeqCst);
        set_ui_lifecycle(UiLifecycle::Quiescing);
        log_to_file(&format!(
            "[quit] app.exit code=0 elapsed_ms={}",
            quit_started.elapsed().as_millis()
        ));
        app.exit(0);
        return;
    }

    SHUTDOWN.store(false, Ordering::SeqCst);
    EXIT_CLEANUP_STATE.store(EXIT_CLEANUP_IDLE, Ordering::SeqCst);
    log_to_file(&format!(
        "[quit] cleanup-failed tracked_count={} orphan_count={} elapsed_ms={}",
        still_pid.len(),
        still_orphans.len(),
        quit_started.elapsed().as_millis()
    ));
    show_main_window(&app, "quit-failed", false);
    let mut detail = Vec::new();
    for entry in &still_pid {
        detail.push(format!("{} (PID={})", entry.workspace_id, entry.pid));
    }
    for pid in &still_orphans {
        detail.push(format!("orphan PID={}", pid));
    }
    let msg = format!(
        "\u{9000}\u{51fa}\u{5931}\u{8d25}\u{ff1a}\u{540e}\u{53f0}\u{670d}\u{52a1}\u{4ecd}\u{5728}\u{8fd0}\u{884c}\u{3002}\n\n\u{8bf7}\u{5148}\u{5728}\u{201c}\u{72b6}\u{6001}\u{9762}\u{677f}\u{201d}\u{70b9}\u{51fb}\u{201c}\u{505c}\u{6b62}\u{670d}\u{52a1}\u{201d}\u{ff0c}\u{786e}\u{8ba4}\u{72b6}\u{6001}\u{53d8}\u{4e3a}\u{201c}\u{672a}\u{8fd0}\u{884c}\u{201d}\u{540e}\u{518d}\u{9000}\u{51fa}\u{3002}\n\n\u{4ecd}\u{5728}\u{8fd0}\u{884c}\u{7684}\u{8fdb}\u{7a0b}\u{ff1a}{}",
        detail.join("; ")
    );
    emit_if_ui_live(&app, "open_status", serde_json::json!({}));
    emit_if_ui_live(&app, "quit_failed", serde_json::json!({ "message": msg }));
}

pub(crate) fn cleanup_backends_on_run_event_exit() {
    let cleanup_started = Instant::now();
    let mut handled_pids = HashSet::new();
    for ent in list_service_pids() {
        if !handled_pids.insert(ent.pid) {
            let _ = fs::remove_file(PathBuf::from(&ent.pid_file));
            remove_heartbeat_file(&ent.workspace_id);
            log_to_file(&format!(
                "[quit] pid-deduplicated pid={} workspace={} source=run-event-exit total_elapsed_ms={}",
                ent.pid,
                ent.workspace_id,
                cleanup_started.elapsed().as_millis()
            ));
            continue;
        }
        if is_pid_running(ent.pid) {
            let force_kill_started = Instant::now();
            let kill_result = kill_pid(ent.pid);
            log_to_file(&format!(
                "[quit] force-kill pid={} source=run-event-exit success={} elapsed_ms={} total_elapsed_ms={}",
                ent.pid,
                kill_result.is_ok(),
                force_kill_started.elapsed().as_millis(),
                cleanup_started.elapsed().as_millis()
            ));
        }
        let _ = fs::remove_file(PathBuf::from(&ent.pid_file));
        remove_heartbeat_file(&ent.workspace_id);
    }
    scan_openkitsune_orphans_with_timing("run-event-exit", cleanup_started);
}

pub(crate) fn setup_tray(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

    let open_status = MenuItem::with_id(app, "open_status", "打开状态面板", true, None::<&str>)?;
    let open_web = MenuItem::with_id(app, "open_web", "打开网页版", true, None::<&str>)?;
    let show = MenuItem::with_id(app, "show", "显示窗口", true, None::<&str>)?;
    let hide = MenuItem::with_id(app, "hide", "隐藏窗口", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出（Quit）", true, None::<&str>)?;

    let menu = Menu::with_items(app, &[&open_status, &open_web, &show, &hide, &quit])?;

    TrayIconBuilder::with_id("main_tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("OpenKitsune")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(
            move |app: &tauri::AppHandle, event| match event.id.as_ref() {
                "quit" => {
                    if EXIT_CLEANUP_STATE
                        .compare_exchange(
                            EXIT_CLEANUP_IDLE,
                            EXIT_CLEANUP_RUNNING,
                            Ordering::SeqCst,
                            Ordering::SeqCst,
                        )
                        .is_err()
                    {
                        log_to_file(
                            "[quit] quit-started ignored: cleanup already active elapsed_ms=0",
                        );
                        return;
                    }

                    let quit_clicked = Instant::now();
                    if let Some(window) = app.get_webview_window("main") {
                        if let Err(error) = window.hide() {
                            log_to_file(&format!(
                                "[quit] window-hide failed error={} elapsed_ms={}",
                                error,
                                quit_clicked.elapsed().as_millis()
                            ));
                        } else {
                            log_to_file(&format!(
                                "[quit] window-hidden elapsed_ms={}",
                                quit_clicked.elapsed().as_millis()
                            ));
                        }
                    }
                    log_to_file(&format!(
                        "[quit] quit-started source=tray elapsed_ms={}",
                        quit_clicked.elapsed().as_millis()
                    ));
                    SHUTDOWN.store(true, Ordering::SeqCst);
                    let app_handle = app.clone();
                    if let Err(error) = thread::Builder::new()
                        .name("openkitsune-tray-quit".into())
                        .spawn(move || run_tray_quit_cleanup(app_handle))
                    {
                        SHUTDOWN.store(false, Ordering::SeqCst);
                        EXIT_CLEANUP_STATE.store(EXIT_CLEANUP_IDLE, Ordering::SeqCst);
                        log_to_file(&format!(
                            "[quit] quit-worker-spawn failed error={} elapsed_ms={}",
                            error,
                            quit_clicked.elapsed().as_millis()
                        ));
                        show_main_window(app, "quit-worker-spawn-failed", false);
                    }
                }
                "show" => {
                    show_main_window(app, "tray-show", false);
                }
                "hide" => {
                    if let Some(w) = app.get_webview_window("main") {
                        let _ = w.hide();
                    }
                }
                "open_web" => {
                    let state = read_state_file();
                    let ws_id = state
                        .current_workspace_id
                        .unwrap_or_else(|| "default".into());
                    let port = read_workspace_api_port(&ws_id).unwrap_or(18900);
                    let url = format!("http://127.0.0.1:{}/web", port);
                    #[cfg(target_os = "windows")]
                    {
                        let _ = std::process::Command::new("cmd")
                            .args(["/c", "start", &url])
                            .spawn();
                    }
                    #[cfg(target_os = "macos")]
                    {
                        let _ = std::process::Command::new("open").arg(&url).spawn();
                    }
                    #[cfg(target_os = "linux")]
                    {
                        let _ = std::process::Command::new("xdg-open").arg(&url).spawn();
                    }
                }
                "open_status" => {
                    show_main_window(app, "tray-open-status", true);
                }
                _ => {}
            },
        )
        .on_tray_icon_event(move |tray: &tauri::tray::TrayIcon, event| match event {
            TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } => {
                let app = tray.app_handle();
                show_main_window(app, "tray-left-click", true);
            }
            TrayIconEvent::DoubleClick {
                button: MouseButton::Left,
                ..
            } => {
                let app = tray.app_handle();
                show_main_window(app, "tray-double-click", true);
            }
            _ => {}
        })
        .build(app)?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    fn command_env<'a>(cmd: &'a Command, key: &str) -> Option<&'a OsStr> {
        cmd.get_envs()
            .find(|(name, _)| *name == OsStr::new(key))
            .and_then(|(_, value)| value)
    }

    #[test]
    fn playwright_browser_env_is_applied_only_for_an_installed_browser() {
        let modules_root = std::env::temp_dir().join(format!(
            "openkitsune-playwright-env-test-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let browsers_dir = modules_root.join("browser").join("browsers");

        let mut missing = Command::new("openkitsune-test");
        apply_playwright_browser_env(&mut missing, &modules_root);
        assert_eq!(command_env(&missing, "PLAYWRIGHT_BROWSERS_PATH"), None);

        fs::create_dir_all(&browsers_dir).unwrap();
        let mut installed = Command::new("openkitsune-test");
        apply_playwright_browser_env(&mut installed, &modules_root);
        assert_eq!(
            command_env(&installed, "PLAYWRIGHT_BROWSERS_PATH"),
            Some(browsers_dir.as_os_str())
        );

        let _ = fs::remove_dir_all(modules_root);
    }
}
