#[cfg(windows)]
use crate::backend::win;
use crate::prelude::*;
use tauri::Emitter;

pub(crate) struct ManagedProcess {
    pub(crate) child: std::process::Child,
    pub(crate) workspace_id: String,
    pub(crate) pid: u32,
    pub(crate) started_at: u64,
}

pub(crate) static MANAGED_CHILD: Lazy<Mutex<Option<ManagedProcess>>> =
    Lazy::new(|| Mutex::new(None));

/// Serializes a watchdog restart against an explicit user stop. The manual-stop
/// marker is persistent, but without this lock the watchdog could pass its last
/// marker check just before the UI records the stop intent and still spawn.
pub(crate) static BACKEND_LIFECYCLE_LOCK: Lazy<Mutex<()>> = Lazy::new(|| Mutex::new(()));

/// Rust 自动启动后端时置 true，启动完成（成功/失败）后置 false。
/// 前端可查询该标记以显示"正在自动启动服务"并禁用启动/重启按钮。
pub(crate) static AUTO_START_IN_PROGRESS: AtomicBool = AtomicBool::new(false);

#[repr(u8)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum UiLifecycle {
    Starting = 0,
    Running = 1,
    Quiescing = 2,
    Exited = 3,
}

pub(crate) struct UiLifecycleGate {
    state: AtomicU8,
}

impl UiLifecycleGate {
    pub(crate) const fn new(state: UiLifecycle) -> Self {
        Self {
            state: AtomicU8::new(state as u8),
        }
    }

    pub(crate) fn state(&self) -> UiLifecycle {
        match self.state.load(Ordering::SeqCst) {
            value if value == UiLifecycle::Starting as u8 => UiLifecycle::Starting,
            value if value == UiLifecycle::Running as u8 => UiLifecycle::Running,
            value if value == UiLifecycle::Quiescing as u8 => UiLifecycle::Quiescing,
            _ => UiLifecycle::Exited,
        }
    }

    pub(crate) fn set(&self, state: UiLifecycle) {
        self.state.store(state as u8, Ordering::SeqCst);
    }

    pub(crate) fn accepts_tauri_ops(&self) -> bool {
        matches!(self.state(), UiLifecycle::Starting | UiLifecycle::Running)
    }

    fn run_if_live<T>(&self, operation: impl FnOnce() -> T) -> Option<T> {
        self.accepts_tauri_ops().then(operation)
    }
}

static UI_LIFECYCLE: UiLifecycleGate = UiLifecycleGate::new(UiLifecycle::Starting);
pub(crate) static SHUTDOWN: AtomicBool = AtomicBool::new(false);

pub(crate) const EXIT_CLEANUP_IDLE: u8 = 0;
pub(crate) const EXIT_CLEANUP_RUNNING: u8 = 1;
pub(crate) const EXIT_CLEANUP_COMPLETE: u8 = 2;
pub(crate) static EXIT_CLEANUP_STATE: AtomicU8 = AtomicU8::new(EXIT_CLEANUP_IDLE);

pub(crate) fn set_ui_lifecycle(state: UiLifecycle) {
    UI_LIFECYCLE.set(state);
}

pub(crate) fn ui_lifecycle() -> UiLifecycle {
    UI_LIFECYCLE.state()
}

pub(crate) fn ui_accepts_tauri_ops() -> bool {
    UI_LIFECYCLE.accepts_tauri_ops()
}

trait UiEventEmitter {
    fn emit_event<S: Serialize + Clone>(&self, event: &str, payload: S) -> Result<(), String>;
}

impl<R: tauri::Runtime> UiEventEmitter for tauri::AppHandle<R> {
    fn emit_event<S: Serialize + Clone>(&self, event: &str, payload: S) -> Result<(), String> {
        self.emit(event, payload).map_err(|error| error.to_string())
    }
}

fn emit_if_ui_live_with_gate<E: UiEventEmitter, S: Serialize + Clone>(
    gate: &UiLifecycleGate,
    emitter: &E,
    event: &str,
    payload: S,
) {
    let Some(result) = gate.run_if_live(|| emitter.emit_event(event, payload)) else {
        return;
    };
    if let Err(e) = result {
        log_to_file(&format!("[ui] emit {event} failed: {e}"));
    }
}

pub(crate) fn emit_if_ui_live<R: tauri::Runtime, S: Serialize + Clone>(
    app: &tauri::AppHandle<R>,
    event: &str,
    payload: S,
) {
    emit_if_ui_live_with_gate(&UI_LIFECYCLE, app, event, payload);
}

/// AUTO_START_IN_PROGRESS 置 true 时记录的 wall-clock 毫秒。
/// 用于 ``is_backend_auto_starting`` 的超时兜底：超过 ``AUTO_START_TIMEOUT_MS``
/// 视为后台 spawn 线程已经死掉/卡死，强制返回 false 防止前端 toast 永久卡住。
pub(crate) static AUTO_START_STARTED_AT_MS: AtomicU64 = AtomicU64::new(0);
pub(crate) static DESKTOP_SESSION_TOKEN: Lazy<Mutex<Option<String>>> =
    Lazy::new(|| Mutex::new(None));
pub(crate) const AUTO_START_TIMEOUT_MS: u64 = 180_000;
pub(crate) const RUNTIME_SETUP_TIMEOUT: Duration = Duration::from_secs(180);
pub(crate) const RUNTIME_PROXY_PROBE_TIMEOUT: Duration = Duration::from_millis(750);

/// 后端启动宽限期（秒）。Backend cold-start 在 dual-venv hack 下：
///   * Python 解释器 import 整个生态 ≈ 30s
///   * 加载 122 个 skills + 30 个 handler + 数百兆 Memory ≈ 60s
///   * IM channel 初始化 + uvicorn bind ≈ 10s
/// 实测从 spawn 到 HTTP /api/health 可访问需要 90~120 秒。
///
/// 启动宽限期内：
///   - Rust 心跳即使 fetch /api/health 失败也不视为"backend down"，不发
///     `backend:lost`、不触发 auto-spawn（避免在 startup 期间反复刷
///     "[heartbeat] backend down" 日志、误以为后端崩溃）。
///   - `is_backend_auto_starting` 仍然返回 true，让前端 UI 显示
///     "正在启动" 而非 "未启动"。
pub(crate) const BACKEND_BOOT_GRACE_SEC: u64 = 150;

/// 即便 PID 已不在跑，也允许在 spawn 后这段窗口内继续认为"在启动宽限"。
/// 用于覆盖 spawn → Python 闪退 → Rust 心跳自愈重 spawn 的过渡窗口，
/// 避免前端 UI 在这个 30 秒小窗口里闪一下"已停止"。
pub(crate) const BACKEND_BOOT_GRACE_PID_DEAD_SEC: u64 = 30;

/// `openkitsune_service_start` 的进程级互斥窗口（毫秒）。
/// 在 3 秒内对同一 workspace 的第二次调用将被直接拒绝，避免前端重试/竞态
/// 在短时间内连续 spawn 出多个后端进程（autostart.log 里 27s 内 5 次 spawn
/// 就是这个 bug 的现场表现）。
pub(crate) const SERVICE_START_DEDUPE_MS: u64 = 3_000;
pub(crate) static SERVICE_START_LAST_AT: Lazy<Mutex<HashMap<String, u64>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));
pub(crate) const OPENKITSUNE_ROOT_MARKER: &str = ".openkitsune-root";
pub(crate) const EXTERNAL_BACKEND_DEV_ENV: &str = "OPENKITSUNE_EXTERNAL_BACKEND_DEV";

pub(crate) fn now_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

pub(crate) fn external_backend_dev_mode() -> bool {
    matches!(
        std::env::var(EXTERNAL_BACKEND_DEV_ENV).ok().as_deref(),
        Some("1") | Some("true") | Some("TRUE") | Some("yes") | Some("YES")
    )
}

/// 进程级自愈相关：crash 重启 marker 文件路径。
/// 由 panic hook 在命中 tao#1180 特征时写入，setup 阶段读出并向前端 emit
/// `app-restarted-from-crash` 事件，前端据此恢复上次工作区/视图。
/// 同一窗口去重写：只保留最近一次现场，避免 marker 累积。
pub(crate) fn restart_marker_path() -> PathBuf {
    let base = home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".openkitsune");
    let _ = fs::create_dir_all(&base);
    base.join("restart.marker")
}

pub(crate) fn frontend_session_marker_path() -> PathBuf {
    let base = home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".openkitsune");
    let _ = fs::create_dir_all(&base);
    base.join("frontend-session.marker")
}

pub(crate) static STARTUP_RECOVERY_NOTICE: Lazy<Mutex<Option<serde_json::Value>>> =
    Lazy::new(|| Mutex::new(None));

pub(crate) fn set_startup_recovery_notice(payload: serde_json::Value) {
    if let Ok(mut guard) = STARTUP_RECOVERY_NOTICE.lock() {
        *guard = Some(payload);
    }
}

#[tauri::command]
pub(crate) fn take_startup_recovery_notice() -> Option<serde_json::Value> {
    STARTUP_RECOVERY_NOTICE
        .lock()
        .ok()
        .and_then(|mut guard| guard.take())
}

#[tauri::command]
pub(crate) fn prepare_relaunch() {
    mark_exit_handled();
}

pub(crate) fn record_frontend_session_marker(app_version: &str) {
    let marker = serde_json::json!({
        "ts": now_epoch_secs(),
        "pid": std::process::id(),
        "app_version": app_version,
    });
    let _ = fs::write(
        frontend_session_marker_path(),
        serde_json::to_string_pretty(&marker).unwrap_or_else(|_| "{}".into()),
    );
}

pub(crate) fn detect_previous_frontend_crash() -> Option<serde_json::Value> {
    let marker_path = frontend_session_marker_path();
    let content = fs::read_to_string(&marker_path).ok()?;
    let previous: serde_json::Value = serde_json::from_str(&content).ok()?;
    let prev_pid = previous.get("pid").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
    if prev_pid == 0 || prev_pid == std::process::id() || is_pid_running(prev_pid) {
        return None;
    }
    Some(serde_json::json!({
        "reason": "native_frontend_crash",
        "previous": previous,
    }))
}

pub(crate) fn clear_frontend_session_marker() {
    let marker_path = frontend_session_marker_path();
    let should_remove = fs::read_to_string(&marker_path)
        .ok()
        .and_then(|content| serde_json::from_str::<serde_json::Value>(&content).ok())
        .and_then(|json| {
            json.get("pid")
                .and_then(|v| v.as_u64())
                .map(|pid| pid as u32)
        })
        .map(|pid| pid == std::process::id())
        .unwrap_or(true);
    if should_remove {
        let _ = fs::remove_file(marker_path);
    }
}

/// 防止自愈进入无限重启循环：如果短时间内（30s）已经因 panic 自愈过一次，
/// 再次崩溃则不再 spawn，让用户感知到崩溃并人工介入。
pub(crate) const SELF_HEAL_COOLDOWN_MS: u64 = 30_000;

pub(crate) fn try_self_heal_relaunch(panic_msg: &str) {
    use std::time::{SystemTime, UNIX_EPOCH};

    mark_exit_handled();

    // 写 marker（携带 ts/panic_brief/上次 workspace 等供前端恢复使用）
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let last_ws = read_state_file().current_workspace_id.unwrap_or_default();
    // 命令行恢复时间：若上一份 marker 距今 < 冷却窗，不再二次自愈，
    // 避免无限崩溃-重启循环把 CPU 烧穿。
    if let Ok(prev) = fs::read_to_string(restart_marker_path()) {
        if let Ok(prev_json) = serde_json::from_str::<serde_json::Value>(&prev) {
            if let Some(prev_ts) = prev_json.get("ts").and_then(|v| v.as_u64()) {
                if ts.saturating_sub(prev_ts) < SELF_HEAL_COOLDOWN_MS / 1000 {
                    log_to_file(&format!(
                        "[self-heal] skip relaunch: last self-heal {}s ago < cooldown",
                        ts.saturating_sub(prev_ts)
                    ));
                    return;
                }
            }
        }
    }
    let marker = serde_json::json!({
        "ts": ts,
        "panic_brief": panic_msg.chars().take(200).collect::<String>(),
        "last_workspace_id": last_ws,
        "reason": "tao_destroyed_panic",
    });
    let _ = fs::write(
        restart_marker_path(),
        serde_json::to_string_pretty(&marker).unwrap_or_else(|_| "{}".into()),
    );

    // spawn 自身进程；--auto-restarted 让新实例知晓自己是恢复实例。
    // single-instance 插件会保证只有一个活实例（旧进程即将崩溃）。
    if let Ok(exe) = std::env::current_exe() {
        let mut cmd = Command::new(&exe);
        cmd.arg("--auto-restarted");
        // 避免继承当前控制台句柄，参考 spawn_detached 模式
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt as _;
            const DETACHED_PROCESS: u32 = 0x00000008;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            cmd.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
        }
        match cmd.spawn() {
            Ok(_) => log_to_file(&format!(
                "[self-heal] relaunched {} after tao panic",
                exe.display()
            )),
            Err(e) => log_to_file(&format!("[self-heal] relaunch FAILED: {e}")),
        }
    }
}

pub(crate) fn exit_handled_marker_path() -> PathBuf {
    let base = home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".openkitsune");
    let _ = fs::create_dir_all(&base);
    base.join("exit-handled.marker")
}

pub(crate) fn mark_exit_handled() {
    let _ = fs::write(exit_handled_marker_path(), std::process::id().to_string());
}

pub(crate) fn clear_exit_handled_marker() {
    let _ = fs::remove_file(exit_handled_marker_path());
}

#[cfg(windows)]
pub(crate) fn watchdog_relaunch_marker_path() -> PathBuf {
    let base = home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".openkitsune");
    let _ = fs::create_dir_all(&base);
    base.join("watchdog-relaunch.marker")
}

#[cfg(windows)]
pub(crate) const WATCHDOG_BREAKER_WINDOW_SECS: u64 = 180;
#[cfg(windows)]
pub(crate) const WATCHDOG_BREAKER_MAX_RELAUNCHES: usize = 3;

#[cfg(windows)]
pub(crate) fn spawn_watchdog() {
    if cfg!(debug_assertions) {
        return;
    }
    use std::os::windows::process::CommandExt as _;
    const DETACHED_PROCESS: u32 = 0x00000008;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let exe = match std::env::current_exe() {
        Ok(path) => path,
        Err(error) => {
            log_to_file(&format!("[watchdog] current_exe failed: {error}"));
            return;
        }
    };
    let mut command = Command::new(exe);
    command
        .arg("--watchdog")
        .arg(std::process::id().to_string());
    command.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW);
    match command.spawn() {
        Ok(child) => log_to_file(&format!(
            "[watchdog] spawned (pid={}) watching parent {}",
            child.id(),
            std::process::id()
        )),
        Err(error) => log_to_file(&format!("[watchdog] spawn failed: {error}")),
    }
}

#[cfg(not(windows))]
pub(crate) fn spawn_watchdog() {}

#[cfg(windows)]
pub(crate) fn run_watchdog(parent_pid: u32) {
    let handle = unsafe { win::OpenProcess(win::SYNCHRONIZE, 0, parent_pid) };
    if !handle.is_null() {
        unsafe {
            win::WaitForSingleObject(handle, win::INFINITE);
            win::CloseHandle(handle);
        }
    } else {
        log_to_file(&format!(
            "[watchdog] OpenProcess({parent_pid}) failed; parent likely already gone"
        ));
    }

    let handled = fs::read_to_string(exit_handled_marker_path())
        .ok()
        .and_then(|text| text.trim().parse::<u32>().ok())
        .map(|pid| pid == parent_pid)
        .unwrap_or(false);
    if handled {
        log_to_file("[watchdog] parent exited cleanly or self-healed; no relaunch");
        return;
    }

    let now = now_epoch_secs();
    let window_start = now.saturating_sub(WATCHDOG_BREAKER_WINDOW_SECS);
    let mut recent: Vec<u64> = fs::read_to_string(watchdog_relaunch_marker_path())
        .ok()
        .map(|text| {
            text.lines()
                .filter_map(|line| line.trim().parse::<u64>().ok())
                .filter(|timestamp| *timestamp >= window_start && *timestamp <= now)
                .collect()
        })
        .unwrap_or_default();
    if recent.len() >= WATCHDOG_BREAKER_MAX_RELAUNCHES {
        log_to_file(&format!(
            "[watchdog] circuit breaker tripped: {} relaunches within {}s",
            recent.len(),
            WATCHDOG_BREAKER_WINDOW_SECS
        ));
        return;
    }

    recent.push(now);
    let _ = fs::write(
        watchdog_relaunch_marker_path(),
        recent
            .iter()
            .map(u64::to_string)
            .collect::<Vec<_>>()
            .join("\n"),
    );
    match std::env::current_exe() {
        Ok(exe) => {
            use std::os::windows::process::CommandExt as _;
            const DETACHED_PROCESS: u32 = 0x00000008;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            let mut command = Command::new(exe);
            command.arg("--auto-restarted");
            command.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
            match command.spawn() {
                Ok(_) => log_to_file("[watchdog] relaunched app after hard crash"),
                Err(error) => log_to_file(&format!("[watchdog] relaunch failed: {error}")),
            }
        }
        Err(error) => log_to_file(&format!("[watchdog] current_exe failed: {error}")),
    }
}

/// Diagnostic snapshot collected asynchronously at startup for panic reports.
pub(crate) static MACHINE_INFO: Lazy<Mutex<Option<String>>> = Lazy::new(|| Mutex::new(None));

pub(crate) fn machine_info_snapshot() -> String {
    MACHINE_INFO
        .lock()
        .ok()
        .and_then(|guard| guard.clone())
        .unwrap_or_else(|| "<machine info not yet collected>".to_string())
}

pub(crate) fn spawn_machine_info_collector() {
    std::thread::spawn(|| {
        let info = collect_machine_info();
        if let Ok(mut guard) = MACHINE_INFO.lock() {
            *guard = Some(info);
        }
    });
}

#[cfg(target_os = "windows")]
pub(crate) fn run_capture_diag(program: &str, args: &[&str]) -> Option<String> {
    use std::os::windows::process::CommandExt as _;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let output = Command::new(program)
        .args(args)
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!text.is_empty()).then_some(text)
}

pub(crate) fn collect_machine_info() -> String {
    let mut lines = vec![
        format!("pid: {}", std::process::id()),
        format!("app_version: {}", env!("CARGO_PKG_VERSION")),
        format!("os: {}", std::env::consts::OS),
        format!("arch: {}", std::env::consts::ARCH),
        format!(
            "auto_restarted: {}",
            std::env::args().any(|arg| arg == "--auto-restarted")
        ),
    ];

    if let Ok(value) = std::env::var("SESSIONNAME") {
        lines.push(format!("session_name: {value}"));
    }
    if let Ok(value) = std::env::var("CLIENTNAME") {
        lines.push(format!("client_name: {value}"));
    }

    #[cfg(target_os = "windows")]
    {
        if let Some(value) = run_capture_diag("cmd", &["/c", "ver"]) {
            lines.push(format!("windows_ver: {}", value.replace(['\r', '\n'], " ")));
        }
        if let Some(value) = run_capture_diag(
            "powershell.exe",
            &[
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$o = Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' -ErrorAction SilentlyContinue; if ($o) { \"$($o.ProductName) | $($o.DisplayVersion) | Build $($o.CurrentBuild).$($o.UBR)\" }",
            ],
        ) {
            lines.push(format!("windows_detail: {value}"));
        }
        if let Some(value) = run_capture_diag(
            "powershell.exe",
            &[
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$paths = @('HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}','HKLM:\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}','HKCU:\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'); foreach ($p in $paths) { try { $v = (Get-ItemProperty $p -ErrorAction Stop).pv; if ($v) { Write-Output $v; break } } catch {} }",
            ],
        ) {
            lines.push(format!("webview2_version: {value}"));
        }
        if let Some(value) = run_capture_diag(
            "powershell.exe",
            &[
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | ForEach-Object { \"$($_.Name) [$($_.DriverVersion) $($_.DriverDate)]\" } | Select-Object -First 4",
            ],
        ) {
            let joined = value
                .lines()
                .map(str::trim)
                .filter(|line| !line.is_empty())
                .collect::<Vec<_>>()
                .join(" | ");
            if !joined.is_empty() {
                lines.push(format!("gpu: {joined}"));
            }
        }
    }

    lines.join("\n")
}

#[cfg(not(target_os = "windows"))]
pub(crate) fn run_capture_diag(_program: &str, _args: &[&str]) -> Option<String> {
    None
}

pub(crate) fn panic_payload_to_string(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(value) = payload.downcast_ref::<&'static str>() {
        return (*value).to_string();
    }
    if let Some(value) = payload.downcast_ref::<String>() {
        return value.clone();
    }
    "<non-string panic payload>".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};

    #[derive(Default)]
    struct CountingEmitter {
        emitted: AtomicU64,
    }

    impl UiEventEmitter for CountingEmitter {
        fn emit_event<S: Serialize + Clone>(
            &self,
            _event: &str,
            _payload: S,
        ) -> Result<(), String> {
            self.emitted.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
    }

    #[test]
    fn lifecycle_gate_accepts_operations_only_while_ui_is_live() {
        let gate = UiLifecycleGate::new(UiLifecycle::Starting);
        assert!(gate.accepts_tauri_ops());

        gate.set(UiLifecycle::Running);
        assert!(gate.accepts_tauri_ops());

        gate.set(UiLifecycle::Quiescing);
        assert!(!gate.accepts_tauri_ops());

        gate.set(UiLifecycle::Exited);
        assert!(!gate.accepts_tauri_ops());
    }

    #[test]
    fn background_operation_is_suppressed_after_quiescing_begins() {
        let gate = Arc::new(UiLifecycleGate::new(UiLifecycle::Running));
        let worker_ready = Arc::new(Barrier::new(2));
        let worker_continue = Arc::new(Barrier::new(2));
        let operation_ran = Arc::new(AtomicBool::new(false));

        let worker = {
            let gate = Arc::clone(&gate);
            let worker_ready = Arc::clone(&worker_ready);
            let worker_continue = Arc::clone(&worker_continue);
            let operation_ran = Arc::clone(&operation_ran);
            thread::spawn(move || {
                worker_ready.wait();
                worker_continue.wait();
                gate.run_if_live(|| operation_ran.store(true, Ordering::SeqCst));
            })
        };

        worker_ready.wait();
        gate.set(UiLifecycle::Quiescing);
        worker_continue.wait();
        worker.join().expect("background worker should finish");

        assert!(!operation_ran.load(Ordering::SeqCst));
    }

    #[test]
    fn tauri_events_are_not_emitted_after_ui_starts_quiescing() {
        let gate = UiLifecycleGate::new(UiLifecycle::Running);
        let emitter = CountingEmitter::default();
        emit_if_ui_live_with_gate(
            &gate,
            &emitter,
            "lifecycle-test-event",
            serde_json::json!({ "state": "running" }),
        );
        assert_eq!(emitter.emitted.load(Ordering::SeqCst), 1);

        gate.set(UiLifecycle::Quiescing);
        emit_if_ui_live_with_gate(
            &gate,
            &emitter,
            "lifecycle-test-event",
            serde_json::json!({ "state": "quiescing" }),
        );

        gate.set(UiLifecycle::Exited);
        emit_if_ui_live_with_gate(
            &gate,
            &emitter,
            "lifecycle-test-event",
            serde_json::json!({ "state": "exited" }),
        );
        assert_eq!(emitter.emitted.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_panic_payload_to_string_handles_standard_payloads() {
        let borrowed: &(dyn std::any::Any + Send) = &"borrowed panic";
        let owned_value = "owned panic".to_string();
        let owned: &(dyn std::any::Any + Send) = &owned_value;
        assert_eq!(panic_payload_to_string(borrowed), "borrowed panic");
        assert_eq!(panic_payload_to_string(owned), "owned panic");
    }
}
