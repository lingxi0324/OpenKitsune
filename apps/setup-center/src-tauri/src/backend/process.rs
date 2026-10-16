use crate::prelude::*;

pub(crate) fn state_file_path() -> PathBuf {
    openkitsune_root_dir().join("state.json")
}

pub(crate) fn workspaces_dir() -> PathBuf {
    openkitsune_root_dir().join("workspaces")
}

pub(crate) fn workspace_dir(id: &str) -> PathBuf {
    workspaces_dir().join(id)
}

pub(crate) fn service_pid_file(workspace_id: &str) -> PathBuf {
    run_dir().join(format!("openkitsune-{}.pid", workspace_id))
}

pub(crate) fn backend_manual_stop_marker(workspace_id: &str) -> PathBuf {
    workspace_dir(workspace_id)
        .join("data")
        .join("backend.manual-stop")
}

pub(crate) fn backend_was_manually_stopped(workspace_id: &str) -> bool {
    backend_manual_stop_marker(workspace_id).exists()
}

pub(crate) fn set_backend_manual_stop_marker(marker: &Path, stopped: bool) -> Result<(), String> {
    if stopped {
        if let Some(parent) = marker.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| format!("create backend state directory failed: {e}"))?;
        }
        fs::write(marker, b"user-requested\n")
            .map_err(|e| format!("record manual backend stop failed: {e}"))?;
    } else if let Err(e) = fs::remove_file(marker) {
        if e.kind() != std::io::ErrorKind::NotFound {
            return Err(format!("clear manual backend stop failed: {e}"));
        }
    }
    Ok(())
}

pub(crate) fn set_backend_manually_stopped(
    workspace_id: &str,
    stopped: bool,
) -> Result<(), String> {
    set_backend_manual_stop_marker(&backend_manual_stop_marker(workspace_id), stopped)
}

pub(crate) fn last_clean_shutdown_marker(workspace_id: &str) -> PathBuf {
    workspace_dir(workspace_id)
        .join("data")
        .join("memory")
        .join(".last_clean_shutdown")
}

pub(crate) fn write_last_clean_shutdown_marker(
    workspace_id: &str,
    pid: u32,
    spawn_started_at: u64,
) {
    let marker = last_clean_shutdown_marker(workspace_id);
    if let Some(parent) = marker.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let payload = serde_json::json!({
        "ts": now_epoch_secs().saturating_mul(1000),
        "pid": pid,
        "version": env!("CARGO_PKG_VERSION"),
        "spawn_started_at": spawn_started_at,
    });
    let _ = fs::write(
        &marker,
        serde_json::to_string_pretty(&payload).unwrap_or_default(),
    );
}

// ── PID 文件 JSON 格式 ──
#[derive(Debug, Serialize, Deserialize, Clone)]
pub(crate) struct PidFileData {
    pub(crate) pid: u32,
    #[serde(default = "default_started_by")]
    started_by: String, // "tauri" | "external"
    #[serde(default)]
    started_at: u64, // unix epoch seconds
}

pub(crate) fn default_started_by() -> String {
    "tauri".to_string()
}

pub(crate) fn status_managed_by_from_pid_file(data: &PidFileData) -> &str {
    if data.started_by == "tauri" {
        "tauri"
    } else {
        "external"
    }
}

pub(crate) fn now_epoch_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub(crate) fn write_pid_file(workspace_id: &str, pid: u32, started_by: &str) -> Result<(), String> {
    let data = PidFileData {
        pid,
        started_by: started_by.to_string(),
        started_at: now_epoch_secs(),
    };
    let json = serde_json::to_string_pretty(&data).map_err(|e| format!("serialize pid: {e}"))?;
    let path = service_pid_file(workspace_id);
    fs::write(&path, json).map_err(|e| format!("write pid file: {e}"))?;
    Ok(())
}

/// 判断当前 workspace 的后端是否仍在"启动宽限期"内。
///
/// 宽限规则：
///   1. PID 文件存在，且 `started_at > 0`（旧格式/外部进程不进入宽限）
///   2. age < BACKEND_BOOT_GRACE_SEC
///   3. **PID 还在跑**：仍在宽限
///      **或** PID 已死但 age < BACKEND_BOOT_GRACE_PID_DEAD_SEC：依然算宽限
///         —— 这是为了对付 dual-venv hack 启动初期"Python 子进程
///         一闪而过又被自愈重 spawn"的窗口，避免心跳立刻误判 down
///         然后前端跟着闪一下"已停止"红条。
///
/// 用于压制 startup 期间的"backend down"误报和无意义的 auto-spawn，
/// 同时让前端 UI 在这段时间内持续显示"正在启动"而非"未启动"。
pub(crate) fn backend_in_boot_grace(workspace_id: &str) -> bool {
    let Some(data) = read_pid_file(workspace_id) else {
        return false;
    };
    if data.started_at == 0 {
        return false;
    }
    let age = now_epoch_secs().saturating_sub(data.started_at);
    if age >= BACKEND_BOOT_GRACE_SEC {
        return false;
    }
    if is_pid_running(data.pid) {
        return true;
    }
    // PID 已死，但还在 spawn-死亡-重 spawn 自愈窗口内 → 仍视作宽限，
    // 避免心跳跳过 boot-grace 直接报 lost。
    age < BACKEND_BOOT_GRACE_PID_DEAD_SEC
}

/// 暴露给前端的命令版本，便于 App.tsx 心跳直接判定"是否还在启动宽限"，
/// 而不必走 `is_backend_auto_starting`（后者复用同一逻辑但语义偏向"自启动"）。
#[tauri::command]
pub(crate) fn backend_in_boot_grace_cmd(workspace_id: String) -> bool {
    backend_in_boot_grace(&workspace_id)
}

/// 读取 PID 文件，兼容旧版纯数字格式
pub(crate) fn read_pid_file(workspace_id: &str) -> Option<PidFileData> {
    let path = service_pid_file(workspace_id);
    let content = fs::read_to_string(&path).ok()?;
    let trimmed = content.trim();
    // 尝试 JSON 格式
    if let Ok(data) = serde_json::from_str::<PidFileData>(trimmed) {
        if data.pid > 0 {
            return Some(data);
        }
    }
    // 向后兼容：纯数字格式
    if let Ok(pid) = trimmed.parse::<u32>() {
        if pid > 0 {
            return Some(PidFileData {
                pid,
                started_by: "tauri".to_string(),
                started_at: 0,
            });
        }
    }
    None
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ServicePidEntry {
    pub(crate) workspace_id: String,
    pub(crate) pid: u32,
    pub(crate) pid_file: String,
    #[serde(default)]
    started_by: String,
}

pub(crate) fn can_auto_stop_backend(workspace_id: &str, pid: u32) -> bool {
    if let Some(data) = read_pid_file(workspace_id) {
        if data.pid == pid {
            return data.started_by != "external";
        }
        // A different tracked process belongs to this workspace; do not kill a
        // random healthy backend discovered from the port.
        return false;
    }

    // Release builds still need to replace orphaned old packaged backends after
    // an app upgrade. In dev, an untracked backend is usually a manually started
    // `python -m openkitsune serve`, so keep it alive.
    !cfg!(debug_assertions)
}

pub(crate) fn list_service_pids() -> Vec<ServicePidEntry> {
    let mut out = Vec::new();
    let dir = run_dir();
    let Ok(rd) = fs::read_dir(&dir) else {
        return out;
    };
    for e in rd.flatten() {
        let p = e.path();
        let Some(name) = p.file_name().and_then(|s| s.to_str()) else {
            continue;
        };
        if !name.starts_with("openkitsune-") || !name.ends_with(".pid") {
            continue;
        }
        let ws = name
            .trim_start_matches("openkitsune-")
            .trim_end_matches(".pid")
            .to_string();
        if let Some(data) = read_pid_file(&ws) {
            out.push(ServicePidEntry {
                workspace_id: ws,
                pid: data.pid,
                pid_file: p.to_string_lossy().to_string(),
                started_by: data.started_by,
            });
        }
    }
    out
}

// ── 心跳文件管理 ──
// Python 后端每 10 秒写入心跳文件 {workspace}/data/backend.heartbeat
// Tauri 读取此文件判断后端真实健康状态。

#[derive(Debug, Serialize, Deserialize, Clone)]
pub(crate) struct HeartbeatData {
    pid: u32,
    pub(crate) timestamp: f64, // unix epoch seconds (float for sub-second precision)
    #[serde(default)]
    pub(crate) phase: String, // "starting" | "initializing" | "http_ready" | "starting_im" | "running" | "restarting" | "stopping"
    #[serde(default)]
    pub(crate) http_ready: bool, // HTTP API 是否就绪
    #[serde(default)]
    pub(crate) im_ready: bool, // IM / late-bound gateway 是否完成启动路径
    #[serde(default)]
    pub(crate) ready: bool, // 后端业务启动流程是否整体收敛
}

/// 心跳文件路径：{workspace_dir}/data/backend.heartbeat
pub(crate) fn service_heartbeat_file(workspace_id: &str) -> PathBuf {
    workspace_dir(workspace_id)
        .join("data")
        .join("backend.heartbeat")
}

/// 读取心跳文件
pub(crate) fn read_heartbeat_file(workspace_id: &str) -> Option<HeartbeatData> {
    let path = service_heartbeat_file(workspace_id);
    let content = fs::read_to_string(&path).ok()?;
    serde_json::from_str::<HeartbeatData>(content.trim()).ok()
}

/// 心跳是否过期。max_age_secs 为最大容忍的无心跳时间（秒）。
/// 返回 None 表示没有心跳文件（旧版后端或尚未启动），
/// 返回 Some(true) 表示心跳过期，Some(false) 表示心跳新鲜。
pub(crate) fn is_heartbeat_stale(workspace_id: &str, max_age_secs: u64) -> Option<bool> {
    let hb = read_heartbeat_file(workspace_id)?;
    let now = now_epoch_secs() as f64;
    let age = now - hb.timestamp;
    Some(age > max_age_secs as f64)
}

/// 删除心跳文件（进程清理时调用）
pub(crate) fn remove_heartbeat_file(workspace_id: &str) {
    let _ = fs::remove_file(service_heartbeat_file(workspace_id));
}

/// 检测指定端口是否可用（未被占用）。
/// 尝试绑定端口，成功则可用，失败则被占用。
pub(crate) fn check_port_available(port: u16) -> bool {
    std::net::TcpListener::bind(("127.0.0.1", port)).is_ok()
}

/// 等待端口释放，最多等 timeout_ms 毫秒。
/// 返回 true 表示端口已释放。
pub(crate) fn wait_for_port_free(port: u16, timeout_ms: u64) -> bool {
    let start = std::time::Instant::now();
    let timeout = std::time::Duration::from_millis(timeout_ms);
    while start.elapsed() < timeout {
        if check_port_available(port) {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
    false
}

pub(crate) fn is_backend_http_healthy(port: Option<u16>) -> bool {
    let effective_port = port.unwrap_or(18900);
    reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .no_proxy()
        .build()
        .ok()
        .and_then(|client| {
            client
                .get(format!("http://127.0.0.1:{}/api/health", effective_port))
                .send()
                .ok()
        })
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

pub(crate) fn should_cleanup_stale_heartbeat(
    heartbeat_stale: Option<bool>,
    http_healthy: bool,
) -> bool {
    matches!(heartbeat_stale, Some(true)) && !http_healthy
}

/// 尝试通过 HTTP API 优雅关闭 Python 服务（POST /api/shutdown），
/// 然后等待进程退出。如果 API 调用失败或超时则回退到 kill。
/// `port`: 可选端口号，默认 18900
pub(crate) fn graceful_stop_pid(pid: u32, port: Option<u16>) -> Result<bool, String> {
    if !is_pid_running(pid) {
        return Ok(true);
    }

    let stop_started = Instant::now();
    let effective_port = port.unwrap_or(18900);
    // 第一步：尝试通过 HTTP API 触发优雅关闭
    let http_started = Instant::now();
    let api_ok = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .no_proxy()
        .build()
        .ok()
        .and_then(|client| {
            client
                .post(format!("http://127.0.0.1:{}/api/shutdown", effective_port))
                .send()
                .ok()
        })
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    log_to_file(&format!(
        "[quit] http-shutdown pid={} port={} success={} elapsed_ms={} total_elapsed_ms={}",
        pid,
        effective_port,
        api_ok,
        http_started.elapsed().as_millis(),
        stop_started.elapsed().as_millis()
    ));

    if api_ok {
        // API 调用成功，给 Python 最多 10 秒优雅退出时间
        for _ in 0..50 {
            if !is_pid_running(pid) {
                return Ok(true);
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        }
    }

    // 第二步：进程仍然存活，强制 kill
    if is_pid_running(pid) {
        let force_kill_started = Instant::now();
        let kill_result = kill_pid(pid);
        log_to_file(&format!(
            "[quit] force-kill pid={} success={} elapsed_ms={} total_elapsed_ms={}",
            pid,
            kill_result.is_ok(),
            force_kill_started.elapsed().as_millis(),
            stop_started.elapsed().as_millis()
        ));
        kill_result?;
        // 等待最多 3s 确认退出
        for _ in 0..15 {
            if !is_pid_running(pid) {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        }
    }

    if is_pid_running(pid) {
        Err(format!(
            "pid {} still running after graceful + forced stop",
            pid
        ))
    } else {
        Ok(false)
    }
}

pub(crate) fn stop_service_pid_entry(
    ent: &ServicePidEntry,
    port: Option<u16>,
) -> Result<(), String> {
    if is_pid_running(ent.pid) {
        graceful_stop_pid(ent.pid, port)?;
    }
    let _ = fs::remove_file(PathBuf::from(&ent.pid_file));
    remove_heartbeat_file(&ent.workspace_id);
    Ok(())
}

/// 启动锁文件路径
pub(crate) fn service_lock_file(workspace_id: &str) -> PathBuf {
    run_dir().join(format!("openkitsune-{}.lock", workspace_id))
}

/// 尝试获取启动锁（原子创建文件），成功返回 true
pub(crate) fn try_acquire_start_lock(workspace_id: &str) -> bool {
    let lock_path = service_lock_file(workspace_id);
    let _ = fs::create_dir_all(lock_path.parent().unwrap_or(Path::new(".")));
    // OpenOptions::create_new ensures atomicity
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock_path)
        .is_ok()
}

pub(crate) fn release_start_lock(workspace_id: &str) {
    let _ = fs::remove_file(service_lock_file(workspace_id));
}

/// 获取进程创建时间（Unix epoch 秒）
#[cfg(windows)]
pub(crate) fn get_process_create_time(pid: u32) -> Option<u64> {
    #[repr(C)]
    #[derive(Copy, Clone)]
    struct FILETIME {
        dw_low_date_time: u32,
        dw_high_date_time: u32,
    }
    extern "system" {
        fn GetProcessTimes(
            hProcess: *mut std::ffi::c_void,
            lpCreationTime: *mut FILETIME,
            lpExitTime: *mut FILETIME,
            lpKernelTime: *mut FILETIME,
            lpUserTime: *mut FILETIME,
        ) -> i32;
    }
    unsafe {
        let handle = win::OpenProcess(win::PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return None;
        }
        let mut creation: FILETIME = std::mem::zeroed();
        let mut exit: FILETIME = std::mem::zeroed();
        let mut kernel: FILETIME = std::mem::zeroed();
        let mut user: FILETIME = std::mem::zeroed();
        let ok = GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user);
        win::CloseHandle(handle);
        if ok == 0 {
            return None;
        }
        // Convert FILETIME (100-ns intervals since 1601-01-01) to Unix epoch seconds
        let ft = ((creation.dw_high_date_time as u64) << 32) | (creation.dw_low_date_time as u64);
        // 116444736000000000 = 100-ns intervals between 1601-01-01 and 1970-01-01
        let unix_100ns = ft.checked_sub(116444736000000000)?;
        Some(unix_100ns / 10_000_000)
    }
}

#[cfg(target_os = "linux")]
pub(crate) fn get_process_create_time(pid: u32) -> Option<u64> {
    let stat = fs::read_to_string(format!("/proc/{}/stat", pid)).ok()?;
    let after_comm = stat.rfind(')')? + 2;
    if after_comm >= stat.len() {
        return None;
    }
    let fields: Vec<&str> = stat[after_comm..].split_whitespace().collect();
    let starttime = fields.get(19)?.parse::<u64>().ok()?;
    let clk_tck: u64 = 100;
    let uptime_str = fs::read_to_string("/proc/uptime").ok()?;
    let uptime_secs: f64 = uptime_str.split_whitespace().next()?.parse().ok()?;
    let now = now_epoch_secs();
    let boot_time = now.saturating_sub(uptime_secs as u64);
    Some(boot_time + starttime / clk_tck)
}

#[cfg(target_os = "macos")]
pub(crate) fn get_process_create_time(pid: u32) -> Option<u64> {
    let output = Command::new("ps")
        .args(["-p", &pid.to_string(), "-o", "lstart="])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let lstart = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if lstart.is_empty() {
        return None;
    }
    // lstart format: "Wed Jan  1 08:00:00 2025"
    // Parse with chrono-less manual approach: use `date -jf` on macOS
    let date_out = Command::new("date")
        .args(["-jf", "%a %b %d %T %Y", &lstart, "+%s"])
        .output()
        .ok()?;
    let epoch_str = String::from_utf8_lossy(&date_out.stdout).trim().to_string();
    epoch_str.parse::<u64>().ok()
}

/// 验证 PID 文件中的 started_at 是否与实际进程创建时间匹配（允许 5 秒误差）
pub(crate) fn is_pid_file_valid(data: &PidFileData) -> bool {
    if !is_pid_running(data.pid) {
        return false;
    }
    // 旧格式没有 started_at：不能仅靠 PID 存活来判断——
    // Windows 上 PID 会被复用，必须验证进程身份。
    if data.started_at == 0 {
        return is_openkitsune_process(data.pid);
    }
    if let Some(actual_create) = get_process_create_time(data.pid) {
        let diff = if data.started_at > actual_create {
            data.started_at - actual_create
        } else {
            actual_create - data.started_at
        };
        if diff > 5 {
            // 时间不匹配——PID 被复用了，再验证一下进程身份
            return is_openkitsune_process(data.pid);
        }
        true // 时间匹配
    } else {
        // 无法获取进程创建时间，退回到进程身份验证
        is_openkitsune_process(data.pid)
    }
}

/// 从 workspace .env 文件读取 API_PORT
pub(crate) fn read_workspace_api_port(workspace_id: &str) -> Option<u16> {
    let env_path = workspace_dir(workspace_id).join(".env");
    let content = read_text_lossy(&env_path);
    for line in content.lines() {
        let t = line.trim();
        if let Some(val) = t.strip_prefix("API_PORT=") {
            return val.trim().parse::<u16>().ok();
        }
    }
    None
}

// --- Windows 原生 API FFI（进程检测/杀死/枚举，不依赖 cmd/tasklist/taskkill，中文 Windows 零编码问题）---
#[cfg(windows)]
#[allow(non_snake_case, dead_code)]
pub(crate) mod win {
    extern "system" {
        pub fn OpenProcess(
            dwDesiredAccess: u32,
            bInheritHandle: i32,
            dwProcessId: u32,
        ) -> *mut std::ffi::c_void;
        pub fn TerminateProcess(hProcess: *mut std::ffi::c_void, uExitCode: u32) -> i32;
        pub fn CloseHandle(hObject: *mut std::ffi::c_void) -> i32;
        pub fn WaitForSingleObject(hHandle: *mut std::ffi::c_void, dwMilliseconds: u32) -> u32;
        pub fn CreateToolhelp32Snapshot(dwFlags: u32, th32ProcessID: u32) -> *mut std::ffi::c_void;
        pub fn Process32FirstW(hSnapshot: *mut std::ffi::c_void, lppe: *mut PROCESSENTRY32W)
            -> i32;
        pub fn Process32NextW(hSnapshot: *mut std::ffi::c_void, lppe: *mut PROCESSENTRY32W) -> i32;
    }
    pub const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    pub const PROCESS_TERMINATE: u32 = 0x0001;
    pub const SYNCHRONIZE: u32 = 0x0010_0000;
    pub const INFINITE: u32 = 0xFFFF_FFFF;
    pub const WAIT_OBJECT_0: u32 = 0x0000_0000;
    pub const WAIT_TIMEOUT: u32 = 0x0000_0102;
    pub const TH32CS_SNAPPROCESS: u32 = 0x00000002;
    pub const INVALID_HANDLE_VALUE: *mut std::ffi::c_void = -1_isize as *mut std::ffi::c_void;

    #[repr(C)]
    pub struct PROCESSENTRY32W {
        pub dw_size: u32,
        pub cnt_usage: u32,
        pub th32_process_id: u32,
        pub th32_default_heap_id: usize,
        pub th32_module_id: u32,
        pub cnt_threads: u32,
        pub th32_parent_process_id: u32,
        pub pc_pri_class_base: i32,
        pub dw_flags: u32,
        pub sz_exe_file: [u16; 260],
    }
}

#[cfg(windows)]
pub(crate) fn is_windows_process_handle_running(handle: *mut std::ffi::c_void) -> bool {
    // A terminated Windows process object can remain open while its parent
    // retains a handle. OpenProcess succeeding therefore does not prove that
    // the process is active; only an unsignalled process handle does.
    match unsafe { win::WaitForSingleObject(handle, 0) } {
        win::WAIT_OBJECT_0 => false,
        win::WAIT_TIMEOUT => true,
        // Preserve the conservative historical behaviour if Windows cannot
        // query the handle rather than incorrectly declaring a live PID dead.
        _ => true,
    }
}

pub(crate) fn is_pid_running(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    #[cfg(windows)]
    {
        // SYNCHRONIZE is required to query the process handle's signalled state.
        let handle = unsafe {
            win::OpenProcess(
                win::PROCESS_QUERY_LIMITED_INFORMATION | win::SYNCHRONIZE,
                0,
                pid,
            )
        };
        if handle.is_null() {
            return false;
        }
        let running = is_windows_process_handle_running(handle);
        unsafe {
            win::CloseHandle(handle);
        }
        return running;
    }
    #[cfg(not(windows))]
    {
        let status = Command::new("kill").args(["-0", &pid.to_string()]).status();
        status.map(|s| s.success()).unwrap_or(false)
    }
}

pub(crate) fn kill_pid(pid: u32) -> Result<(), String> {
    if pid == 0 {
        return Ok(());
    }
    #[cfg(windows)]
    {
        // 直接用 TerminateProcess API 杀进程，不走 cmd/taskkill。
        let handle = unsafe { win::OpenProcess(win::PROCESS_TERMINATE, 0, pid) };
        if handle.is_null() {
            if !is_pid_running(pid) {
                return Ok(());
            }
            return Err(format!(
                "\u{65e0}\u{6cd5}\u{6253}\u{5f00}\u{8fdb}\u{7a0b}\u{ff08}pid={}\u{ff09}\u{ff0c}\u{6743}\u{9650}\u{4e0d}\u{8db3}\u{6216}\u{8fdb}\u{7a0b}\u{4e0d}\u{5b58}\u{5728}",
                pid
            ));
        }
        let ok = unsafe { win::TerminateProcess(handle, 1) };
        unsafe {
            win::CloseHandle(handle);
        }
        if ok == 0 {
            if !is_pid_running(pid) {
                return Ok(());
            }
            return Err(format!(
                "TerminateProcess \u{5931}\u{8d25}\u{ff08}pid={}\u{ff09}",
                pid
            ));
        }
        return Ok(());
    }
    #[cfg(not(windows))]
    {
        let pid_str = pid.to_string();

        // SIGTERM: 允许进程优雅退出
        let _ = Command::new("kill").args(["-TERM", &pid_str]).status();

        // 等待最多 2 秒确认退出
        for _ in 0..10 {
            if !is_pid_running(pid) {
                return Ok(());
            }
            std::thread::sleep(std::time::Duration::from_millis(200));
        }

        // SIGKILL: 进程未响应 SIGTERM（可能事件循环卡死），强制终止
        let status = Command::new("kill")
            .args(["-KILL", &pid_str])
            .status()
            .map_err(|e| format!("kill -KILL failed: {e}"))?;
        if !status.success() && is_pid_running(pid) {
            return Err(format!("kill -KILL failed: {status}"));
        }
        Ok(())
    }
}

/// 检查指定 PID 是否属于 OpenKitsune 后端进程（python/openkitsune-server）。
/// 用于判断 PID 文件是否有效——避免 Windows PID 复用导致的误判。
pub(crate) fn is_openkitsune_process(pid: u32) -> bool {
    if pid == 0 || !is_pid_running(pid) {
        return false;
    }
    #[cfg(windows)]
    {
        // Step 1: 用 Toolhelp32 快速检查进程名
        let snap = unsafe { win::CreateToolhelp32Snapshot(win::TH32CS_SNAPPROCESS, 0) };
        if snap == win::INVALID_HANDLE_VALUE || snap.is_null() {
            return false;
        }
        let mut pe: win::PROCESSENTRY32W = unsafe { std::mem::zeroed() };
        pe.dw_size = std::mem::size_of::<win::PROCESSENTRY32W>() as u32;

        let mut exe_name = String::new();
        if unsafe { win::Process32FirstW(snap, &mut pe) } != 0 {
            loop {
                if pe.th32_process_id == pid {
                    exe_name = String::from_utf16_lossy(
                        &pe.sz_exe_file
                            [..pe.sz_exe_file.iter().position(|&c| c == 0).unwrap_or(260)],
                    )
                    .to_ascii_lowercase();
                    break;
                }
                if unsafe { win::Process32NextW(snap, &mut pe) } == 0 {
                    break;
                }
            }
        }
        unsafe {
            win::CloseHandle(snap);
        }

        // 进程名包含 python 或 openkitsune-server → 可能是后端
        if exe_name.contains("openkitsune-server") {
            return true;
        }
        if !exe_name.contains("python") {
            return false; // 既不是 python 也不是 openkitsune-server，肯定不是后端
        }

        // Step 2: python 进程需进一步检查命令行是否包含 openkitsune
        let mut c = Command::new("powershell");
        c.args([
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            &format!(
                "(Get-CimInstance Win32_Process -Filter 'ProcessId={}').CommandLine",
                pid
            ),
        ]);
        apply_no_window(&mut c);
        if let Ok(out) = c.output() {
            let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
            return s.contains("openkitsune");
        }
        false
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(cmdline) = fs::read_to_string(format!("/proc/{}/cmdline", pid)) {
            return cmdline.to_lowercase().contains("openkitsune");
        }
        let output = Command::new("ps")
            .args(["-p", &pid.to_string(), "-o", "args="])
            .output();
        if let Ok(out) = output {
            let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
            return s.contains("openkitsune");
        }
        false
    }
    #[cfg(target_os = "macos")]
    {
        let output = Command::new("ps")
            .args(["-p", &pid.to_string(), "-o", "args="])
            .output();
        if let Ok(out) = output {
            let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
            return s.contains("openkitsune");
        }
        false
    }
}

/// 扫描并杀死所有进程名为 python/pythonw 且命令行包含 "openkitsune" 和 "serve" 的进程。
/// 用于托盘退出时兜底清理孤儿进程（PID 文件可能已被删除但进程仍存活）。
/// 返回被杀掉的 PID 列表。
pub(crate) fn kill_openkitsune_orphans() -> Vec<u32> {
    let mut killed = Vec::new();
    #[cfg(windows)]
    {
        // Step 1: 用 Toolhelp32 枚举所有进程，找到进程名含 python 的
        let snap = unsafe { win::CreateToolhelp32Snapshot(win::TH32CS_SNAPPROCESS, 0) };
        if snap == win::INVALID_HANDLE_VALUE || snap.is_null() {
            return killed;
        }
        let mut pe: win::PROCESSENTRY32W = unsafe { std::mem::zeroed() };
        pe.dw_size = std::mem::size_of::<win::PROCESSENTRY32W>() as u32;

        let mut python_pids: Vec<u32> = Vec::new();
        let mut bundled_pids: Vec<u32> = Vec::new();

        if unsafe { win::Process32FirstW(snap, &mut pe) } != 0 {
            loop {
                let name = String::from_utf16_lossy(
                    &pe.sz_exe_file[..pe.sz_exe_file.iter().position(|&c| c == 0).unwrap_or(260)],
                );
                let name_lower = name.to_ascii_lowercase();
                if name_lower.contains("python") {
                    python_pids.push(pe.th32_process_id);
                }
                // PyInstaller 打包后端进程名为 openkitsune-server.exe
                if name_lower.contains("openkitsune-server") {
                    bundled_pids.push(pe.th32_process_id);
                }
                if unsafe { win::Process32NextW(snap, &mut pe) } == 0 {
                    break;
                }
            }
        }
        unsafe {
            win::CloseHandle(snap);
        }

        // Step 1.5: kill orphaned openkitsune-server.exe (PyInstaller bundled
        // backend). The original code killed every process named like that on
        // sight, which is unsafe when the user has another OpenKitsune install
        // running (e.g. portable + installed side by side) — we'd terminate
        // the other instance's backend. Mirror the python branch and verify
        // the command line contains the `serve` subcommand before killing;
        // any other invocation (CLI help, --version, custom scripts launched
        // by the user) is skipped.
        for ppid in bundled_pids {
            if !is_pid_running(ppid) {
                continue;
            }
            let mut c = Command::new("powershell");
            c.args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                &format!(
                    "(Get-CimInstance Win32_Process -Filter 'ProcessId={}').CommandLine",
                    ppid
                ),
            ]);
            apply_no_window(&mut c);
            let cmdline = c
                .output()
                .ok()
                .map(|out| String::from_utf8_lossy(&out.stdout).to_lowercase())
                .unwrap_or_default();
            // Match the canonical backend invocation. We deliberately don't
            // try to match install-path here — overlapping installs will be
            // caught by per-workspace PID files in step 1.
            if !cmdline.contains("serve") {
                continue;
            }
            let _ = kill_pid(ppid);
            killed.push(ppid);
        }

        // Step 2: 对每个 python 进程查命令行，判断是否是 openkitsune serve 进程
        // 使用 PowerShell Get-CimInstance 替代已废弃的 wmic（Windows 11 已移除 wmic）
        for ppid in python_pids {
            let mut c = Command::new("powershell");
            c.args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                &format!(
                    "(Get-CimInstance Win32_Process -Filter 'ProcessId={}').CommandLine",
                    ppid
                ),
            ]);
            apply_no_window(&mut c);
            if let Ok(out) = c.output() {
                let s = String::from_utf8_lossy(&out.stdout).to_lowercase();
                // 精确匹配模块调用签名
                if s.contains("openkitsune.main") && (s.contains(" serve") || s.ends_with("serve")) {
                    if is_pid_running(ppid) {
                        let _ = kill_pid(ppid);
                        killed.push(ppid);
                    }
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        // 搜索 openkitsune.main serve (venv 模式) 和 openkitsune-server (PyInstaller 模式)
        let patterns = [
            "ps aux | grep '[o]penakita\\.main.*serve' | awk '{print $2}'",
            "ps aux | grep '[o]penakita-server' | awk '{print $2}'",
        ];
        let mut pids_to_kill: Vec<u32> = Vec::new();
        for pattern in &patterns {
            if let Ok(out) = Command::new("sh").args(["-c", pattern]).output() {
                let stdout = String::from_utf8_lossy(&out.stdout);
                for line in stdout.lines() {
                    if let Ok(pid) = line.trim().parse::<u32>() {
                        if is_pid_running(pid)
                            && !killed.contains(&pid)
                            && !pids_to_kill.contains(&pid)
                        {
                            pids_to_kill.push(pid);
                        }
                    }
                }
            }
        }

        // SIGTERM
        for &pid in &pids_to_kill {
            let _ = Command::new("kill")
                .args(["-TERM", &pid.to_string()])
                .status();
        }

        if !pids_to_kill.is_empty() {
            std::thread::sleep(std::time::Duration::from_millis(1500));
        }

        // SIGKILL 升级：对 SIGTERM 后仍存活的进程强制终止
        for pid in pids_to_kill {
            if is_pid_running(pid) {
                let _ = Command::new("kill")
                    .args(["-KILL", &pid.to_string()])
                    .status();
            }
            killed.push(pid);
        }
    }
    killed
}

/// 扫描所有进程名含 python 且命令行包含 "openkitsune" 和 "serve" 的进程。
/// 返回 OpenKitsuneProcess 列表，供前端多进程检测使用。
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct OpenKitsuneProcess {
    pid: u32,
    cmd: String,
}

#[tauri::command]
pub(crate) fn openkitsune_list_processes() -> Vec<OpenKitsuneProcess> {
    let mut out = Vec::new();
    #[cfg(windows)]
    {
        // Step 1: 枚举所有进程，找到进程名含 python 的 PID
        let snap = unsafe { win::CreateToolhelp32Snapshot(win::TH32CS_SNAPPROCESS, 0) };
        if snap == win::INVALID_HANDLE_VALUE || snap.is_null() {
            return out;
        }
        let mut pe: win::PROCESSENTRY32W = unsafe { std::mem::zeroed() };
        pe.dw_size = std::mem::size_of::<win::PROCESSENTRY32W>() as u32;

        let mut python_pids: Vec<(u32, u32)> = Vec::new();

        if unsafe { win::Process32FirstW(snap, &mut pe) } != 0 {
            loop {
                let name = String::from_utf16_lossy(
                    &pe.sz_exe_file[..pe.sz_exe_file.iter().position(|&c| c == 0).unwrap_or(260)],
                );
                let name_lower = name.to_ascii_lowercase();
                if name_lower.contains("python") {
                    python_pids.push((pe.th32_process_id, pe.th32_parent_process_id));
                }
                if unsafe { win::Process32NextW(snap, &mut pe) } == 0 {
                    break;
                }
            }
        }
        unsafe {
            win::CloseHandle(snap);
        }

        let mut matched: Vec<(u32, u32, String)> = Vec::new();

        // Step 2: 对每个 python 进程查命令行
        for (ppid, parent_pid) in python_pids {
            let mut c = Command::new("powershell");
            c.args([
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                &format!(
                    "(Get-CimInstance Win32_Process -Filter 'ProcessId={}').CommandLine",
                    ppid
                ),
            ]);
            apply_no_window(&mut c);
            if let Ok(cmd_out) = c.output() {
                let s = String::from_utf8_lossy(&cmd_out.stdout).to_string();
                let s_lower = s.to_lowercase();
                // 精确匹配模块调用签名，避免 venv 路径中 .openkitsune 误报
                if s_lower.contains("openkitsune.main")
                    && (s_lower.contains(" serve") || s_lower.ends_with("serve"))
                {
                    if is_pid_running(ppid) {
                        matched.push((ppid, parent_pid, s.trim().to_string()));
                    }
                }
            }
        }

        // uv-created venv python.exe can be a launcher parent that delegates to
        // the managed CPython executable. Count only the leaf backend process.
        for (pid, _parent, cmd) in &matched {
            let has_matched_child = matched.iter().any(|(_, parent, _)| parent == pid);
            if !has_matched_child {
                out.push(OpenKitsuneProcess {
                    pid: *pid,
                    cmd: cmd.clone(),
                });
            }
        }
    }
    #[cfg(not(windows))]
    {
        // ps aux | grep openkitsune.main.*serve  —— 精确匹配模块调用
        if let Ok(ps_out) = Command::new("sh")
            .args(["-c", "ps aux | grep '[o]penakita\\.main.*serve'"])
            .output()
        {
            let stdout = String::from_utf8_lossy(&ps_out.stdout);
            for line in stdout.lines() {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 2 {
                    if let Ok(pid) = parts[1].parse::<u32>() {
                        if is_pid_running(pid) {
                            out.push(OpenKitsuneProcess {
                                pid,
                                cmd: parts[10..].join(" "),
                            });
                        }
                    }
                }
            }
        }
    }
    out
}

/// 停止所有检测到的 OpenKitsune serve 进程。
/// 返回被停止的 PID 列表。
#[tauri::command]
pub(crate) fn openkitsune_stop_all_processes() -> Vec<u32> {
    let mut stopped = Vec::new();

    // 第 1 层：按 PID 文件逐一停止
    let entries = list_service_pids();
    for ent in &entries {
        if is_pid_running(ent.pid) {
            let port = read_workspace_api_port(&ent.workspace_id);
            let _ = stop_service_pid_entry(ent, port);
            stopped.push(ent.pid);
        }
    }

    // 第 2 层：兜底扫描所有命令行含 openkitsune serve 的 python 进程并杀掉
    let orphans = kill_openkitsune_orphans();
    for pid in orphans {
        if !stopped.contains(&pid) {
            stopped.push(pid);
        }
    }

    stopped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manual_backend_stop_marker_persists_until_explicit_start() {
        let test_dir = std::env::temp_dir().join(format!(
            "openkitsune-manual-stop-test-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let marker = test_dir.join("backend.manual-stop");

        assert!(!marker.exists());
        set_backend_manual_stop_marker(&marker, true).expect("manual stop should be recorded");
        assert!(marker.exists());
        set_backend_manual_stop_marker(&marker, false)
            .expect("explicit start should clear manual stop");
        assert!(!marker.exists());

        let _ = fs::remove_dir_all(test_dir);
    }

    #[test]
    fn test_stale_heartbeat_cleanup_requires_http_failure() {
        assert!(!should_cleanup_stale_heartbeat(Some(true), true));
        assert!(should_cleanup_stale_heartbeat(Some(true), false));
        assert!(!should_cleanup_stale_heartbeat(Some(false), false));
        assert!(!should_cleanup_stale_heartbeat(None, false));
    }

    #[cfg(windows)]
    #[test]
    fn windows_process_handle_reports_exit_while_parent_retains_handle() {
        use std::os::windows::io::AsRawHandle;

        let mut child = Command::new("cmd")
            .args(["/C", "exit", "0"])
            .spawn()
            .expect("short-lived child should start");
        let handle = child.as_raw_handle() as *mut std::ffi::c_void;
        let deadline = Instant::now() + Duration::from_secs(3);

        loop {
            if child
                .try_wait()
                .expect("short-lived child status should be readable")
                .is_some()
            {
                break;
            }
            assert!(
                Instant::now() < deadline,
                "short-lived child did not exit before the test deadline"
            );
            thread::sleep(Duration::from_millis(10));
        }

        assert!(
            !is_windows_process_handle_running(handle),
            "a signalled process handle must not be treated as a running process"
        );
    }

    #[test]
    fn test_service_status_preserves_pid_file_ownership() {
        let tauri = PidFileData {
            pid: 1,
            started_by: "tauri".to_string(),
            started_at: 0,
        };
        let external = PidFileData {
            pid: 2,
            started_by: "external".to_string(),
            started_at: 0,
        };
        assert_eq!(status_managed_by_from_pid_file(&tauri), "tauri");
        assert_eq!(status_managed_by_from_pid_file(&external), "external");
    }
}
