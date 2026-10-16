use crate::prelude::*;

pub(crate) static ROOT_CONFIG_LOCK: Lazy<Mutex<()>> = Lazy::new(|| Mutex::new(()));
pub(crate) static STATE_FILE_LOCK: Lazy<Mutex<()>> = Lazy::new(|| Mutex::new(()));

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PlatformInfo {
    os: String,
    arch: String,
    home_dir: String,
    openkitsune_root_dir: String,
}

/// 计算"未配置 custom_root 时的"默认 OpenKitsune 数据目录字符串。
///
/// 注意：日常显示请用 [`openkitsune_root_dir`] 取真实 root，否则会和后端
/// 实际写入位置不一致；此函数仅作为兜底/迁移场景的"默认值"语义保留。
#[allow(dead_code)]
pub(crate) fn default_openkitsune_root() -> String {
    let home = home_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
    home.join(".openkitsune").to_string_lossy().to_string()
}

#[tauri::command]
pub(crate) fn get_platform_info() -> PlatformInfo {
    let home = home_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
    // 用 openkitsune_root_dir() 而不是 default_openkitsune_root()，确保前端
    // 显示的 root（以及拼出的 runtime / venv / logs hint）与后端 Rust /
    // Python 真正使用的位置完全一致。否则在用户配置了 custom_root 或
    // 设置了 OPENKITSUNE_ROOT 环境变量时，面板会指向 ~/.openkitsune 而真实
    // runtime 落在另一个磁盘，让人误以为"runtime 没建出来"。
    PlatformInfo {
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        home_dir: home.to_string_lossy().to_string(),
        openkitsune_root_dir: openkitsune_root_dir().to_string_lossy().to_string(),
    }
}

#[tauri::command]
pub(crate) fn toggle_pet_window(app_handle: tauri::AppHandle, show: bool) -> Result<(), String> {
    if let Some(window) = app_handle.get_webview_window("pet_window") {
        if show {
            window.show().map_err(|e| e.to_string())?;
        } else {
            window.hide().map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn start_dragging(window: tauri::Window) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct WorkspaceSummary {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) path: String,
    pub(crate) is_current: bool,
}

#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AppStateFile {
    #[serde(default = "default_config_version")]
    pub(crate) config_version: u32,
    #[serde(default)]
    pub(crate) current_workspace_id: Option<String>,
    #[serde(default)]
    pub(crate) workspaces: Vec<WorkspaceMeta>,
    #[serde(default)]
    pub(crate) auto_start_backend: Option<bool>,
    #[serde(default)]
    pub(crate) last_installed_version: Option<String>,
    #[serde(default)]
    pub(crate) install_mode: Option<String>,
    #[serde(default)]
    pub(crate) auto_update: Option<bool>,
    /// None preserves the legacy first-run heuristic for existing installs.
    #[serde(default)]
    pub(crate) onboarding_completed: Option<bool>,
}

pub(crate) fn default_config_version() -> u32 {
    migrations::CURRENT_CONFIG_VERSION
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct WorkspaceMeta {
    pub(crate) id: String,
    pub(crate) name: String,
}

pub(crate) fn default_root_dir() -> PathBuf {
    home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".openkitsune")
}

pub(crate) fn comparable_path(path: &Path) -> String {
    let mut text = path.to_string_lossy().replace('/', "\\");
    while text.len() > 1 && text.ends_with('\\') {
        text.pop();
    }
    if cfg!(windows) {
        text.to_ascii_lowercase()
    } else {
        text
    }
}

pub(crate) fn is_path_root(path: &Path) -> bool {
    path.parent().is_none() || path.file_name().is_none()
}

pub(crate) fn is_safe_openkitsune_data_root(path: &Path) -> bool {
    if !path.is_absolute() || is_path_root(path) {
        return false;
    }

    let target = comparable_path(path);
    if let Some(home) = home_dir() {
        if target == comparable_path(&home) {
            return false;
        }
    }

    for protected in [
        dirs_next::desktop_dir(),
        dirs_next::download_dir(),
        dirs_next::document_dir(),
        dirs_next::data_dir(),
        dirs_next::data_local_dir(),
    ]
    .into_iter()
    .flatten()
    {
        if target == comparable_path(&protected) {
            return false;
        }
    }

    true
}

pub(crate) fn ensure_safe_openkitsune_data_root(path: &Path) -> Result<(), String> {
    if is_safe_openkitsune_data_root(path) {
        Ok(())
    } else {
        Err("数据目录不能设置为磁盘根目录、用户主目录或系统常用目录。请使用专用目录，例如 D:\\OpenKitsuneData\\.openkitsune".into())
    }
}

pub(crate) fn write_root_marker(root: &Path) -> Result<(), String> {
    fs::create_dir_all(root).map_err(|e| format!("无法创建数据目录: {e}"))?;
    fs::write(
        root.join(OPENKITSUNE_ROOT_MARKER),
        b"OpenKitsune data root\nDo not delete this file unless you no longer use this directory for OpenKitsune.\n",
    )
    .map_err(|e| format!("write root marker failed: {e}"))
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub(crate) struct RootConfig {
    #[serde(default)]
    pub(crate) custom_root: Option<String>,
}

pub(crate) fn root_config_path() -> PathBuf {
    default_root_dir().join("root_config.json")
}

pub(crate) fn read_root_config() -> RootConfig {
    let p = root_config_path();
    let Ok(content) = fs::read_to_string(&p) else {
        return RootConfig::default();
    };
    match serde_json::from_str(&content) {
        Ok(cfg) => cfg,
        Err(e) => {
            eprintln!(
                "warning: failed to parse {}: {e}, using defaults",
                p.display()
            );
            RootConfig::default()
        }
    }
}

pub(crate) fn write_root_config(config: &RootConfig) -> Result<(), String> {
    let default_dir = default_root_dir();
    fs::create_dir_all(&default_dir).map_err(|e| format!("create default root dir failed: {e}"))?;
    write_root_marker(&default_dir)?;

    let p = root_config_path();
    let data = serde_json::to_string_pretty(config)
        .map_err(|e| format!("serialize root config failed: {e}"))?;
    atomic_write_with_backup(&p, data.as_bytes())?;

    // 同步写入纯文本文件，供 NSIS 安装脚本简单读取（无需解析 JSON）
    // NSIS Unicode 模式的 FileRead 在无 BOM 时按 ANSI(系统代码页) 解读，
    // 含非 ASCII 字符（如中文路径）会乱码。写成 UTF-16LE + BOM 保证 NSIS 正确读取。
    let txt_path = default_dir.join("custom_root.txt");
    match &config.custom_root {
        Some(path) if !path.is_empty() => {
            let trimmed = path.trim();
            let mut bytes: Vec<u8> = Vec::with_capacity(2 + trimmed.len() * 2);
            bytes.extend_from_slice(&[0xFF, 0xFE]);
            for code_unit in trimmed.encode_utf16() {
                bytes.extend_from_slice(&code_unit.to_le_bytes());
            }
            fs::write(&txt_path, bytes)
                .map_err(|e| format!("write custom_root.txt failed: {e}"))?;
        }
        _ => {
            let _ = fs::remove_file(&txt_path);
        }
    }
    Ok(())
}

pub(crate) fn openkitsune_root_dir() -> PathBuf {
    if let Ok(val) = std::env::var("OPENKITSUNE_ROOT") {
        if !val.is_empty() {
            return PathBuf::from(val);
        }
    }
    let config = read_root_config();
    if let Some(ref custom) = config.custom_root {
        if !custom.is_empty() {
            let p = PathBuf::from(custom);
            if !is_safe_openkitsune_data_root(&p) {
                eprintln!(
                    "WARNING: custom root dir '{}' is unsafe, falling back to default",
                    custom
                );
                return default_root_dir();
            }
            // 如果自定义路径所在的父目录都不可访问（如磁盘断开），回退到默认路径
            if p.exists() || p.parent().map(|parent| parent.exists()).unwrap_or(false) {
                return p;
            }
            eprintln!(
                "WARNING: custom root dir '{}' is not accessible, falling back to default",
                custom
            );
        }
    }
    default_root_dir()
}

pub(crate) fn run_dir() -> PathBuf {
    openkitsune_root_dir().join("run")
}

/// 安装配置日志目录：~/.openkitsune/logs/
pub(crate) fn setup_logs_dir() -> PathBuf {
    openkitsune_root_dir().join("logs")
}

/// 进程内 minidump 落地目录：~/.openkitsune/crashdumps/
/// 由 crash_handler 在启动时 ensure dir 并安装 SEH filter；
/// build_feedback_zip 会把 *.dmp 及对应的 *.events.txt 自动打包进反馈包。
pub(crate) fn crashdumps_dir() -> PathBuf {
    openkitsune_root_dir().join("crashdumps")
}

/// Soft size cap for `autostart.log`. Once exceeded, the current file is
/// rotated to `autostart.log.1` (overwriting any previous rotation) and a
/// fresh empty file is started. We keep exactly one rotated generation —
/// this log is diagnostic chatter, not an audit trail, so unbounded
/// retention isn't useful and a single hot+cold pair caps disk use at
/// roughly `2 * AUTOSTART_LOG_MAX_BYTES`.
pub(crate) const AUTOSTART_LOG_MAX_BYTES: u64 = 10 * 1024 * 1024;

/// Best-effort size-based rotation. Any IO failure here is swallowed because
/// the caller (`log_to_file`) is best-effort diagnostics — losing a rotation
/// just means the next call may overshoot the cap slightly, which is fine.
pub(crate) fn rotate_autostart_log_if_needed(path: &Path) {
    let len = match fs::metadata(path) {
        Ok(m) => m.len(),
        Err(_) => return,
    };
    if len < AUTOSTART_LOG_MAX_BYTES {
        return;
    }
    let rotated = path.with_extension("log.1");
    // Drop any existing .1 first; rename on Windows fails if the target
    // already exists, unlike POSIX semantics.
    let _ = fs::remove_file(&rotated);
    let _ = fs::rename(path, &rotated);
}

/// Append a diagnostic line to `~/.openkitsune/logs/autostart.log`.
pub(crate) fn log_to_file(msg: &str) {
    let log_dir = setup_logs_dir();
    let _ = fs::create_dir_all(&log_dir);
    let path = log_dir.join("autostart.log");
    rotate_autostart_log_if_needed(&path);
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let line = format!("[{}] {}\n", secs, msg);
    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .and_then(|mut f| std::io::Write::write_all(&mut f, line.as_bytes()));
    crash_handler::record_event(msg);
}

pub(crate) fn desktop_session_token() -> String {
    let mut guard = DESKTOP_SESSION_TOKEN.lock().unwrap();
    if let Some(token) = guard.as_ref() {
        return token.clone();
    }
    let mut seed = [0u8; 32];
    if getrandom::fill(&mut seed).is_err() {
        let fallback = format!(
            "{}:{}:{:?}",
            now_epoch_secs(),
            std::process::id(),
            std::thread::current().id()
        );
        let token = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(fallback.as_bytes());
        *guard = Some(token.clone());
        return token;
    }
    let token = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(seed);
    *guard = Some(token.clone());
    token
}

#[tauri::command]
pub(crate) fn openkitsune_desktop_session_token() -> String {
    desktop_session_token()
}

pub(crate) fn tail_serve_log_to_autostart(log_path: &Path, max_bytes: usize) {
    let Ok(mut file) = fs::File::open(log_path) else {
        return;
    };
    let Ok(meta) = file.metadata() else {
        return;
    };
    let len = meta.len();
    let start = len.saturating_sub(max_bytes as u64);
    if file.seek(SeekFrom::Start(start)).is_err() {
        return;
    }
    let mut buf = Vec::new();
    if file.read_to_end(&mut buf).is_err() {
        return;
    }
    let text = String::from_utf8_lossy(&buf);
    log_to_file(&format!(
        "[serve_log_tail] path={} bytes={}\n{}",
        log_path.display(),
        buf.len(),
        text
    ));
}

/// 开始写入安装配置日志，创建带日期的日志文件。返回完整路径供前端展示。
#[tauri::command]
pub(crate) fn start_onboarding_log(date_label: String) -> Result<String, String> {
    let log_dir = setup_logs_dir();
    fs::create_dir_all(&log_dir).map_err(|e| format!("create logs dir failed: {e}"))?;
    let safe_label = date_label
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect::<String>();
    let name = if safe_label.is_empty() {
        format!(
            "onboarding-{}.log",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs()
        )
    } else {
        format!("onboarding-{}.log", safe_label)
    };
    let path = log_dir.join(&name);
    let mut f = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&path)
        .map_err(|e| format!("open onboarding log failed: {e}"))?;
    let header = format!("OpenKitsune 安装配置日志 开始于 {}\n", date_label);
    f.write_all(header.as_bytes())
        .map_err(|e| format!("write onboarding log header failed: {e}"))?;
    f.flush().map_err(|e| format!("flush failed: {e}"))?;
    Ok(path.to_string_lossy().to_string())
}

/// 追加一行到安装配置日志（每行建议带时间戳，由前端拼接）。
#[tauri::command]
pub(crate) fn append_onboarding_log(log_path: String, line: String) -> Result<(), String> {
    let path = PathBuf::from(&log_path);
    if !path.exists() {
        return Ok(());
    }
    let mut f = OpenOptions::new()
        .append(true)
        .open(&path)
        .map_err(|e| format!("append onboarding log failed: {e}"))?;
    writeln!(f, "{}", line).map_err(|e| format!("write line failed: {e}"))?;
    f.flush().map_err(|e| format!("flush failed: {e}"))?;
    Ok(())
}

/// 批量追加多行到安装配置日志（用于写入配置快照等）。
#[tauri::command]
pub(crate) fn append_onboarding_log_lines(
    log_path: String,
    lines: Vec<String>,
) -> Result<(), String> {
    let path = PathBuf::from(&log_path);
    if !path.exists() || lines.is_empty() {
        return Ok(());
    }
    let mut f = OpenOptions::new()
        .append(true)
        .open(&path)
        .map_err(|e| format!("append onboarding log failed: {e}"))?;
    for line in lines {
        writeln!(f, "{}", line).map_err(|e| format!("write line failed: {e}"))?;
    }
    f.flush().map_err(|e| format!("flush failed: {e}"))?;
    Ok(())
}

// ── 前端日志持久化 ──

pub(crate) const FRONTEND_LOG_MAX_BYTES: u64 = 5 * 1024 * 1024; // 5 MB
pub(crate) const FRONTEND_LOG_TRUNCATE_TO: u64 = 2 * 1024 * 1024; // 截断后保留最后 2 MB

pub(crate) fn frontend_log_path() -> PathBuf {
    setup_logs_dir().join("frontend.log")
}

/// 自动轮转：当文件超过 FRONTEND_LOG_MAX_BYTES 时，只保留尾部 FRONTEND_LOG_TRUNCATE_TO 字节。
pub(crate) fn maybe_rotate_frontend_log(path: &Path) {
    let meta = match fs::metadata(path) {
        Ok(m) => m,
        Err(_) => return,
    };
    if meta.len() <= FRONTEND_LOG_MAX_BYTES {
        return;
    }
    // Read tail
    let mut f = match fs::File::open(path) {
        Ok(f) => f,
        Err(_) => return,
    };
    let start = meta.len().saturating_sub(FRONTEND_LOG_TRUNCATE_TO);
    if f.seek(SeekFrom::Start(start)).is_err() {
        return;
    }
    let mut tail = Vec::new();
    if f.read_to_end(&mut tail).is_err() {
        return;
    }
    drop(f);
    // Skip to next newline to avoid partial line
    let offset = tail
        .iter()
        .position(|&b| b == b'\n')
        .map(|i| i + 1)
        .unwrap_or(0);
    let _ = fs::write(path, &tail[offset..]);
}

/// 前端 JS 日志批量追加到 ~/.openkitsune/logs/frontend.log。
#[tauri::command]
pub(crate) fn append_frontend_log(lines: Vec<String>) -> Result<(), String> {
    if lines.is_empty() {
        return Ok(());
    }
    let log_dir = setup_logs_dir();
    fs::create_dir_all(&log_dir).map_err(|e| format!("create logs dir failed: {e}"))?;
    let path = frontend_log_path();
    maybe_rotate_frontend_log(&path);
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| format!("open frontend log failed: {e}"))?;
    for line in &lines {
        writeln!(f, "{}", line).map_err(|e| format!("write line failed: {e}"))?;
    }
    f.flush().map_err(|e| format!("flush failed: {e}"))?;
    Ok(())
}

/// 导出日志到用户下载目录，返回保存路径。
#[tauri::command]
pub(crate) fn save_log_export(filename: String, content: String) -> Result<String, String> {
    let downloads = dirs_next::download_dir()
        .or_else(dirs_next::desktop_dir)
        .unwrap_or_else(|| openkitsune_root_dir().join("logs"));
    fs::create_dir_all(&downloads).ok();
    let path = downloads.join(&filename);
    fs::write(&path, content.as_bytes()).map_err(|e| format!("save log export failed: {e}"))?;
    Ok(path.to_string_lossy().to_string())
}

pub(crate) fn modules_dir() -> PathBuf {
    openkitsune_root_dir().join("modules")
}

pub(crate) fn bootstrap_resource_dir() -> PathBuf {
    bundled_resource_dir("bootstrap")
}

pub(crate) fn bundled_resource_dir(resource_name: &str) -> PathBuf {
    let exe_path = std::env::current_exe().ok();
    let exe_dir = exe_path
        .as_ref()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| PathBuf::from("."));

    // macOS: exe 在 .app/Contents/MacOS/，Tauri 将 resources 放在
    // .app/Contents/Resources/ 下并保留原始目录结构。
    // tauri.conf.json 中的资源保留 resources/ 目录层级。
    #[cfg(target_os = "macos")]
    {
        if let Some(contents_dir) = exe_dir.parent() {
            let primary = contents_dir
                .join("Resources")
                .join("resources")
                .join(resource_name);
            if primary.exists() {
                return primary;
            }
            // 兼容可能的简化布局（无额外 resources/ 前缀）
            let fallback = contents_dir.join("Resources").join(resource_name);
            if fallback.exists() {
                return fallback;
            }
        }
    }

    // Windows / Linux: 主路径 — resources 位于 exe 同级目录
    let primary = exe_dir.join("resources").join(resource_name);
    if primary.exists() {
        return primary;
    }

    // Linux deb/AppImage: exe 可能在 /usr/bin/ (symlink) 而 resources 在 /usr/lib/<app>/
    // current_exe() 有时返回 symlink 自身而非目标，导致 exe_dir = /usr/bin/
    #[cfg(target_os = "linux")]
    {
        let mut candidates: Vec<PathBuf> = vec![];

        // Tauri 2.x deb 的二进制名称默认来自 Cargo.toml package.name（非 productName），
        // lib 目录与二进制名称一致: /usr/lib/<binary-name>/resources/...
        // 从 current_exe() 动态推导，避免硬编码过时名称。
        let exe_name = exe_path
            .as_ref()
            .and_then(|p| p.file_name().map(|n| n.to_string_lossy().to_string()));

        let static_names: &[&str] = &[
            "OpenKitsuneDesktop",       // tauri.conf.json productName used by deb resource dir
            "OpenKitsune Desktop",      // legacy productName with a space
            "openkitsune-setup-center", // Cargo.toml package name (Tauri 2.x default)
            "openkitsune-desktop",      // legacy / mainBinaryName override
            "open-akita-desktop",
        ];

        // deb 常见布局: /usr/lib/<app-name>/resources/<resource_name>/
        if let Some(ref name) = exe_name {
            candidates.push(
                Path::new("/usr/lib")
                    .join(name)
                    .join("resources")
                    .join(resource_name),
            );
        }
        for app_name in static_names {
            candidates.push(
                Path::new("/usr/lib")
                    .join(app_name)
                    .join("resources")
                    .join(resource_name),
            );
        }

        // 若 exe 在 /usr/bin/，尝试同级 /usr/lib/<app>/
        if let Some(usr_dir) = exe_dir.parent() {
            if let Some(ref name) = exe_name {
                candidates.push(
                    usr_dir
                        .join("lib")
                        .join(name)
                        .join("resources")
                        .join(resource_name),
                );
            }
            for app_name in static_names {
                candidates.push(
                    usr_dir
                        .join("lib")
                        .join(app_name)
                        .join("resources")
                        .join(resource_name),
                );
            }
        }

        // AppImage: 解压后 exe 在 <mount>/usr/bin/，resources 可能在 <mount>/usr/lib/<app>/
        // 也可能在 <mount>/resources/ (Tauri AppImage 平坦布局)
        if let Some(mount_root) = exe_dir.parent().and_then(|p| p.parent()) {
            if let Some(ref name) = exe_name {
                candidates.push(
                    mount_root
                        .join("lib")
                        .join(name)
                        .join("resources")
                        .join(resource_name),
                );
            }
            for app_name in static_names {
                candidates.push(
                    mount_root
                        .join("lib")
                        .join(app_name)
                        .join("resources")
                        .join(resource_name),
                );
            }
            candidates.push(mount_root.join("resources").join(resource_name));
        }

        for c in &candidates {
            if c.exists() {
                eprintln!(
                    "[bundled_resource_dir] found {} at Linux fallback: {}",
                    resource_name,
                    c.display()
                );
                return c.clone();
            }
        }

        eprintln!(
            "[bundled_resource_dir] {} not found. exe_dir={}, exe_name={:?}, checked {} Linux fallback paths",
            resource_name,
            exe_dir.display(),
            exe_name,
            candidates.len()
        );
    }

    primary
}
