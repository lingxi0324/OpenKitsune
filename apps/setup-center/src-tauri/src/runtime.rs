use crate::prelude::*;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct RuntimePipIndex {
    id: String,
    url: String,
    #[serde(default)]
    trusted_host: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(crate) struct RuntimeEnvState {
    path: String,
    status: String,
    #[serde(default)]
    created_at: String,
    #[serde(default)]
    last_verified_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub(crate) struct RuntimeManifest {
    schema_version: u32,
    app_version: String,
    pub(crate) wheel_hash: String,
    python_version: String,
    #[serde(default)]
    python_seed_fingerprint: String,
    #[serde(default)]
    extras: Vec<String>,
    #[serde(default)]
    uv_path: String,
    app_venv: RuntimeEnvState,
    agent_venv: RuntimeEnvState,
    pip_index: RuntimePipIndex,
    pub(crate) legacy_mode: bool,
    pub(crate) last_error: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct BootstrapWheel {
    pub(crate) name: String,
    #[serde(default)]
    pub(crate) sha256: String,
}

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct BootstrapManifest {
    #[serde(default = "default_python_version")]
    python_version: String,
    pub(crate) wheel: BootstrapWheel,
    #[serde(default)]
    default_pip_index: Option<RuntimePipIndex>,
    #[serde(default)]
    wheelhouse: Option<serde_json::Value>,
    #[serde(default)]
    python_seed: Option<serde_json::Value>,
}

#[derive(Clone, Debug)]
pub(crate) struct RuntimeEnvInfo {
    pub(crate) app_python: PathBuf,
    pub(crate) agent_python: PathBuf,
    app_venv: PathBuf,
    agent_venv: PathBuf,
    pip_index: RuntimePipIndex,
}

pub(crate) fn default_python_version() -> String {
    "3.12".to_string()
}

pub(crate) const DEFAULT_PIP_INDEX_URL: &str = "https://mirrors.aliyun.com/pypi/simple/";

pub(crate) fn runtime_root_dir() -> PathBuf {
    openkitsune_root_dir().join("runtime")
}

pub(crate) fn runtime_manifest_path() -> PathBuf {
    runtime_root_dir().join("manifest.json")
}

pub(crate) fn app_venv_dir() -> PathBuf {
    runtime_root_dir().join("app-venv")
}

pub(crate) fn agent_venv_dir() -> PathBuf {
    runtime_root_dir().join("agent-venv")
}

pub(crate) fn runtime_logs_dir() -> PathBuf {
    runtime_root_dir().join("logs")
}

pub(crate) fn runtime_cache_dir() -> PathBuf {
    runtime_root_dir().join("cache")
}

pub(crate) fn runtime_uv_cache_dir() -> PathBuf {
    runtime_cache_dir().join("uv")
}

pub(crate) fn runtime_venv_python_path(venv_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        venv_dir.join("Scripts").join("python.exe")
    } else {
        venv_dir.join("bin").join("python")
    }
}

pub(crate) fn runtime_venv_home_python_path(venv_dir: &Path) -> Option<PathBuf> {
    if !cfg!(windows) {
        return None;
    }
    let cfg_path = venv_dir.join("pyvenv.cfg");
    let content = fs::read_to_string(cfg_path).ok()?;
    for line in content.lines() {
        let Some(home) = line.strip_prefix("home = ") else {
            continue;
        };
        let py = PathBuf::from(home.trim()).join("python.exe");
        if py.exists() {
            return Some(py);
        }
    }
    None
}

pub(crate) fn runtime_venv_site_packages_dir(venv_dir: &Path) -> Option<PathBuf> {
    if cfg!(windows) {
        let sp = venv_dir.join("Lib").join("site-packages");
        return sp.exists().then_some(sp);
    }
    let lib_dir = venv_dir.join("lib");
    if let Ok(entries) = fs::read_dir(&lib_dir) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().to_string();
            if name.starts_with("python") {
                let sp = entry.path().join("site-packages");
                if sp.exists() {
                    return Some(sp);
                }
            }
        }
    }
    None
}

pub(crate) fn python_string_literal(value: &Path) -> String {
    format!("{:?}", value.to_string_lossy().to_string())
}

/// Render a `&[&str]` into a Python tuple literal, e.g. `("a", "b", "c")`.
/// Used by `app_runtime_health_code` to share Rust-side `BAD_*_MARKERS`
/// constants directly with the embedded Python health-check script, so the
/// two sides never drift apart.
pub(crate) fn python_tuple_literal(values: &[&str]) -> String {
    let body: Vec<String> = values.iter().map(|s| format!("{:?}", s)).collect();
    if body.len() == 1 {
        format!("({},)", body[0])
    } else {
        format!("({})", body.join(", "))
    }
}

pub(crate) const CANONICAL_BACKEND_ENTRYPOINT: &str =
    "from openkitsune.main import app as openkitsune_app; openkitsune_app()";

pub(crate) fn canonical_backend_args() -> Vec<String> {
    vec![
        "-u".into(),
        "-c".into(),
        CANONICAL_BACKEND_ENTRYPOINT.into(),
        "serve".into(),
    ]
}

pub(crate) fn runtime_venv_backend_args(venv_dir: &Path) -> Vec<String> {
    if cfg!(windows) && runtime_venv_home_python_path(venv_dir).is_some() {
        if let Some(site_packages) = runtime_venv_site_packages_dir(venv_dir) {
            let venv_python = runtime_venv_python_path(venv_dir);
            let code = format!(
                "import site, sys; sys.prefix = sys.exec_prefix = {}; sys.executable = {}; site.addsitedir({}); {}",
                python_string_literal(venv_dir),
                python_string_literal(&venv_python),
                python_string_literal(&site_packages),
                CANONICAL_BACKEND_ENTRYPOINT,
            );
            return vec!["-u".into(), "-c".into(), code, "serve".into()];
        }
    }
    canonical_backend_args()
}

pub(crate) fn runtime_venv_backend_python_path(venv_dir: &Path) -> PathBuf {
    // Do not use the python.exe/pythonw.exe launcher files created by uv on
    // Windows. They delegate to the managed CPython executable as a grandchild,
    // which escapes our CREATE_NO_WINDOW flag and leaves a visible console.
    if let Some(py) = runtime_venv_home_python_path(venv_dir) {
        return py;
    }
    runtime_venv_python_path(venv_dir)
}

pub(crate) fn runtime_venv_bin_dir(venv_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        venv_dir.join("Scripts")
    } else {
        venv_dir.join("bin")
    }
}

pub(crate) fn ensure_runtime_layout() -> Result<(), String> {
    let root = runtime_root_dir();
    for dir in [
        root.clone(),
        app_venv_dir(),
        agent_venv_dir(),
        runtime_logs_dir(),
        runtime_cache_dir().join("wheels"),
        runtime_uv_cache_dir(),
        runtime_cache_dir().join("python"),
    ] {
        if let Err(e) = fs::create_dir_all(&dir) {
            // 企业 AD 域 / Windows S 模式 / 杀软"勒索软件防护"会把
            // `%LOCALAPPDATA%\OpenKitsuneDesktop\` 设为受保护目录，此时
            // `create_dir_all` 返回 PermissionDenied。Phase 2 加了 30MB seed
            // 后 IO 失败概率上升，必须给出可操作的指引而不是干瘪的报错。
            //
            // 结构化错误码 `RUNTIME_PERMISSION_DENIED|...`：前端识别这个前缀
            // 后渲染中英文指引 + "打开运行时目录"按钮。前后端契约见
            // `apps/setup-center/src/views/StatusView.tsx`。
            if e.kind() == std::io::ErrorKind::PermissionDenied {
                let detail = format!(
                    "RUNTIME_PERMISSION_DENIED|{} 创建被拒。可能是杀软/域策略限制。\
                     请将 {} 加入白名单后重试，或联系管理员。\
                     Permission denied creating {}; please allowlist {} or contact your admin.",
                    dir.display(),
                    runtime_root_dir().display(),
                    dir.display(),
                    runtime_root_dir().display()
                );
                write_runtime_failure_manifest(&detail);
                return Err(detail);
            }
            return Err(format!("create runtime dir {} failed: {e}", dir.display()));
        }
    }
    Ok(())
}

pub(crate) fn default_pip_index() -> RuntimePipIndex {
    RuntimePipIndex {
        id: "aliyun".into(),
        url: DEFAULT_PIP_INDEX_URL.into(),
        trusted_host: "mirrors.aliyun.com".into(),
    }
}

pub(crate) fn trusted_host_for_url(url: &str) -> String {
    url.split_once("://")
        .map(|(_, rest)| rest.split('/').next().unwrap_or("").to_string())
        .unwrap_or_default()
}

pub(crate) fn read_runtime_manifest() -> Option<RuntimeManifest> {
    let content = fs::read_to_string(runtime_manifest_path()).ok()?;
    serde_json::from_str::<RuntimeManifest>(&content).ok()
}

pub(crate) fn resolve_runtime_pip_index() -> RuntimePipIndex {
    if let Ok(url) = std::env::var("OPENKITSUNE_PIP_INDEX_URL") {
        if !url.trim().is_empty() {
            let trusted_host = std::env::var("OPENKITSUNE_PIP_TRUSTED_HOST")
                .unwrap_or_else(|_| trusted_host_for_url(&url));
            return RuntimePipIndex {
                id: "env-openkitsune".into(),
                url,
                trusted_host,
            };
        }
    }
    if let Ok(url) = std::env::var("PIP_INDEX_URL") {
        if !url.trim().is_empty() {
            let trusted_host =
                std::env::var("PIP_TRUSTED_HOST").unwrap_or_else(|_| trusted_host_for_url(&url));
            return RuntimePipIndex {
                id: "env-pip".into(),
                url,
                trusted_host,
            };
        }
    }
    if let Ok(bootstrap) = read_bootstrap_manifest() {
        if let Some(index) = bootstrap.default_pip_index {
            if !index.url.trim().is_empty() {
                return index;
            }
        }
    }
    if let Some(manifest) = read_runtime_manifest() {
        if !manifest.pip_index.url.trim().is_empty() {
            return manifest.pip_index;
        }
    }
    default_pip_index()
}

pub(crate) fn read_bootstrap_manifest() -> Result<BootstrapManifest, String> {
    let path = bootstrap_resource_dir().join("manifest.json");
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("read bootstrap manifest {} failed: {e}", path.display()))?;
    serde_json::from_str(&content)
        .map_err(|e| format!("parse bootstrap manifest {} failed: {e}", path.display()))
}

pub(crate) fn bootstrap_uv_path() -> PathBuf {
    let bootstrap = bootstrap_resource_dir();
    let local = if cfg!(windows) {
        bootstrap.join("bin").join("uv.exe")
    } else {
        bootstrap.join("bin").join("uv")
    };
    if local.exists() {
        local
    } else {
        PathBuf::from("uv")
    }
}

pub(crate) fn app_runtime_extras() -> Vec<String> {
    vec!["desktop".to_string()]
}

pub(crate) fn bootstrap_python_seed_fingerprint(bootstrap: &BootstrapManifest) -> String {
    let Some(seed) = bootstrap.python_seed.as_ref() else {
        return String::new();
    };
    if let Some(hash) = seed.get("sha256").and_then(|v| v.as_str()) {
        return hash.to_string();
    }
    serde_json::to_string(seed).unwrap_or_default()
}

pub(crate) fn runtime_manifest_mismatch(
    manifest: &RuntimeManifest,
    bootstrap: &BootstrapManifest,
    pip_index: &RuntimePipIndex,
) -> Option<String> {
    let expected_version = env!("CARGO_PKG_VERSION");
    let expected_extras = app_runtime_extras();
    let expected_python_seed = bootstrap_python_seed_fingerprint(bootstrap);
    let expected_uv_path = bootstrap_uv_path().to_string_lossy().to_string();

    if manifest.app_version != expected_version {
        return Some(format!(
            "app_version changed (manifest={}, expected={})",
            manifest.app_version, expected_version
        ));
    }
    if manifest.wheel_hash != bootstrap.wheel.sha256 {
        return Some("wheel_hash changed".into());
    }
    if manifest.python_version != bootstrap.python_version {
        return Some(format!(
            "python_version changed (manifest={}, expected={})",
            manifest.python_version, bootstrap.python_version
        ));
    }
    if manifest.python_seed_fingerprint != expected_python_seed {
        return Some("python_seed changed".into());
    }
    if manifest.extras != expected_extras {
        return Some(format!(
            "extras changed (manifest={:?}, expected={:?})",
            manifest.extras, expected_extras
        ));
    }
    if manifest.pip_index != *pip_index {
        return Some("pip_index changed".into());
    }
    if !manifest.uv_path.is_empty() && manifest.uv_path != expected_uv_path {
        return Some("uv_path changed".into());
    }
    if manifest.legacy_mode {
        return Some("legacy_mode=true".into());
    }
    None
}

pub(crate) fn bootstrap_wheelhouse_dir() -> PathBuf {
    bootstrap_resource_dir().join("wheelhouse")
}

pub(crate) fn bootstrap_declares_complete_wheelhouse(bootstrap: &BootstrapManifest) -> bool {
    let Some(wheelhouse) = bootstrap.wheelhouse.as_ref() else {
        return false;
    };
    wheelhouse
        .get("complete")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

pub(crate) fn wheelhouse_has_locked_deps(wheel_path: &Path) -> bool {
    let wheelhouse = bootstrap_wheelhouse_dir();
    let Ok(entries) = fs::read_dir(&wheelhouse) else {
        return false;
    };
    let target = wheel_path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("");
    entries.flatten().any(|entry| {
        let path = entry.path();
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        path.extension().and_then(|e| e.to_str()) == Some("whl")
            && !name.eq_ignore_ascii_case(target)
    })
}

pub(crate) fn managed_python_seed_path() -> Option<PathBuf> {
    managed_python_seed_path_from(&bootstrap_resource_dir())
}

pub(crate) fn managed_python_seed_path_from(bootstrap: &Path) -> Option<PathBuf> {
    let base = bootstrap.join("python");
    if !base.exists() {
        return None;
    }
    let candidates = if cfg!(windows) {
        vec![base.join("python.exe"), base.join("bin").join("python.exe")]
    } else {
        vec![
            base.join("bin").join("python3"),
            base.join("bin").join("python"),
            base.join("python3"),
            base.join("python"),
        ]
    };
    candidates.into_iter().find(|p| p.exists())
}

pub(crate) fn managed_node_seed_path() -> Option<PathBuf> {
    let bootstrap = bootstrap_resource_dir();
    let base = bootstrap.join("node");
    if !base.exists() {
        return None;
    }
    let candidates = if cfg!(windows) {
        vec![base.join("node.exe"), base.join("bin").join("node.exe")]
    } else {
        vec![base.join("bin").join("node"), base.join("node")]
    };
    candidates.into_iter().find(|p| p.exists())
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum RuntimeEnvPurpose {
    Bootstrap,
    Core,
}

impl RuntimeEnvPurpose {
    fn as_str(self) -> &'static str {
        match self {
            Self::Bootstrap => "bootstrap",
            Self::Core => "core",
        }
    }
}

/// Centralized runtime environment builder for OpenKitsune-managed subprocesses.
///
/// Core/bootstrap subprocesses must not inherit user Python, Conda, pip, or SSL
/// state. Both paths receive explicit OpenKitsune runtime locations and secret
/// scrubbing markers.
pub(crate) fn apply_runtime_env_builder(
    cmd: &mut Command,
    purpose: RuntimeEnvPurpose,
    pip_index: Option<&RuntimePipIndex>,
) {
    strip_harmful_python_env(cmd);
    strip_harmful_toolchain_env(cmd);

    // 过滤 PATH 里的 anaconda/pyenv/homebrew/mise/asdf 等已知 Python 污染源
    // 段。即便上面 strip_harmful_python_env 已经清掉 PYTHONHOME/PYTHONPATH，
    // uv 在 `--python <version>` 模式下仍会按 PATH 顺序 discover 一个匹配的
    // python.exe；若 PATH 头部是 `C:\Users\<u>\anaconda3\` 就 100% 命中。
    // 用 PATH 过滤作为兜底，与下面 apply_runtime_bootstrap_env 的
    // `UV_PYTHON_PREFERENCE=only-managed` 形成"配置 + 兜底"双保险。
    filter_path_for_runtime(cmd);

    cmd.env("OPENKITSUNE_RUNTIME_ROOT", runtime_root_dir());
    cmd.env("OPENKITSUNE_BOOTSTRAP_DIR", bootstrap_resource_dir());
    cmd.env("OPENKITSUNE_ENV_PURPOSE", purpose.as_str());
    cmd.env("OPENKITSUNE_ENV_TRUST_SOURCE", "host-runtime");
    cmd.env("PYTHONNOUSERSITE", "1");

    let effective_pip_index;
    let pip_index = match pip_index {
        Some(index) => index,
        None => {
            effective_pip_index = resolve_runtime_pip_index();
            &effective_pip_index
        }
    };
    cmd.env("PIP_INDEX_URL", &pip_index.url);
    cmd.env("UV_INDEX_URL", &pip_index.url);
    if !pip_index.trusted_host.trim().is_empty() {
        cmd.env("PIP_TRUSTED_HOST", &pip_index.trusted_host);
    }

    cmd.env(
        "OPENKITSUNE_APP_PYTHON",
        runtime_venv_python_path(&app_venv_dir()),
    );
    cmd.env(
        "OPENKITSUNE_AGENT_PYTHON",
        runtime_venv_python_path(&agent_venv_dir()),
    );
    cmd.env(
        "OPENKITSUNE_AGENT_BIN",
        runtime_venv_bin_dir(&agent_venv_dir()),
    );

    cmd.env("OPENKITSUNE_SUBPROCESS_SECRET_SCRUB", "1");
}

pub(crate) fn apply_runtime_bootstrap_env(cmd: &mut Command, pip_index: Option<&RuntimePipIndex>) {
    apply_runtime_env_builder(cmd, RuntimeEnvPurpose::Bootstrap, pip_index);
    bypass_unreachable_runtime_proxies(cmd);

    // 仅在 bootstrap 路径上钉死 uv 的 Python 发现策略。Core / Agent 子进程
    // 已经直接通过 venv 内 python 调用，不走 uv 解释器解析。
    //
    //   * UV_PYTHON_PREFERENCE=only-managed：禁止 uv 用宿主 anaconda / pyenv
    //     / brew python。即便 PATH 过滤兜底失效，uv 也不会去 PATH 里找。
    //   * UV_PYTHON_DOWNLOADS=automatic：seed 缺失时允许自动下载
    //     python-build-standalone（联网环境无感升级；断网会落到 fallback）。
    //   * UV_PYTHON_INSTALL_DIR：把下载的 managed Python 落在
    //     OpenKitsune 自管目录而不是 `%LOCALAPPDATA%\uv\python`，便于卸载、
    //     便于"修复运行环境"按钮一刀清理。
    //   * UV_PYTHON_BIN_DIR：与 INSTALL_DIR 同根，避免 uv 把 shim 写到
    //     `~/.local/bin` 这种用户全局位置。
    cmd.env("UV_PYTHON_PREFERENCE", "only-managed");
    cmd.env("UV_PYTHON_DOWNLOADS", "automatic");
    let py_install = runtime_cache_dir().join("python");
    cmd.env("UV_PYTHON_INSTALL_DIR", &py_install);
    cmd.env("UV_PYTHON_BIN_DIR", &py_install);
    // 给 uv 的下载缓存也定向到 runtime/cache/uv/，与现有 cache layout 一致。
    cmd.env("UV_CACHE_DIR", runtime_uv_cache_dir());
}

pub(crate) fn runtime_proxy_endpoint(value: &str) -> Option<(String, u16)> {
    let parsed = reqwest::Url::parse(value).ok()?;
    let host = parsed.host_str()?.to_string();
    let port = parsed
        .port_or_known_default()
        .or_else(|| match parsed.scheme() {
            "socks" | "socks4" | "socks5" | "socks5h" => Some(1080),
            _ => None,
        })?;
    Some((host, port))
}

pub(crate) fn proxy_endpoint_is_reachable(host: &str, port: u16) -> bool {
    let Ok(addresses) = (host, port).to_socket_addrs() else {
        return false;
    };
    addresses
        .take(4)
        .any(|address| TcpStream::connect_timeout(&address, RUNTIME_PROXY_PROBE_TIMEOUT).is_ok())
}

/// uv and pip honor proxy environment variables, but a stale local proxy can
/// turn every package operation into a long retry cascade. Only remove proxy
/// variables from this child command after the configured endpoint has been
/// positively identified as unreachable; the desktop process environment is
/// left untouched.
pub(crate) fn bypass_unreachable_runtime_proxies(cmd: &mut Command) {
    let proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ];
    let mut reachability: HashMap<String, bool> = HashMap::new();

    for key in proxy_keys {
        let Ok(value) = std::env::var(key) else {
            continue;
        };
        let value = value.trim();
        if value.is_empty() {
            continue;
        }
        let Some((host, port)) = runtime_proxy_endpoint(value) else {
            log_to_file(&format!(
                "[runtime] proxy preflight skipped malformed {} value",
                key
            ));
            continue;
        };
        let endpoint = format!("{}:{}", host, port);
        let reachable = *reachability
            .entry(endpoint.clone())
            .or_insert_with(|| proxy_endpoint_is_reachable(&host, port));
        if !reachable {
            cmd.env_remove(key);
            log_to_file(&format!(
                "[runtime] proxy preflight: {} endpoint {} is unreachable; bypassing it for runtime setup",
                key, endpoint
            ));
        }
    }
}

pub(crate) fn apply_runtime_core_env(cmd: &mut Command) {
    apply_runtime_env_builder(cmd, RuntimeEnvPurpose::Core, None);
    prepend_path(cmd, &runtime_venv_bin_dir(&agent_venv_dir()));

    // uv-managed Python can miss an OS trust store on Windows. Prefer the
    // certifi bundle installed into app-venv, and never inherit Conda's SSL vars.
    if let Some(sp) = runtime_venv_site_packages_dir(&app_venv_dir()) {
        let cacert = sp.join("certifi").join("cacert.pem");
        if cacert.exists() {
            cmd.env("SSL_CERT_FILE", &cacert);
            cmd.env("REQUESTS_CA_BUNDLE", &cacert);
            cmd.env("CURL_CA_BUNDLE", &cacert);
            if let Some(parent) = cacert.parent() {
                cmd.env("SSL_CERT_DIR", parent);
            }
        }
    }
}

pub(crate) fn run_and_log(
    mut cmd: Command,
    log_path: &Path,
    deadline: Instant,
) -> Result<(), String> {
    let command_debug = format!("{:?}", cmd);
    if Instant::now() >= deadline {
        return Err(format!(
            "RUNTIME_INSTALL_TIMEOUT|runtime setup exceeded {} seconds before running {}",
            RUNTIME_SETUP_TIMEOUT.as_secs(),
            command_debug
        ));
    }
    let mut log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .map_err(|e| format!("open runtime log {} failed: {e}", log_path.display()))?;
    let _ = writeln!(log, "\n$ {}", command_debug);
    let stdout_log = log
        .try_clone()
        .map_err(|e| format!("clone runtime stdout log failed: {e}"))?;
    let stderr_log = log
        .try_clone()
        .map_err(|e| format!("clone runtime stderr log failed: {e}"))?;
    cmd.stdout(Stdio::from(stdout_log));
    cmd.stderr(Stdio::from(stderr_log));

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("run command failed: {e}"))?;

    let mut timed_out = false;
    let mut wait_error = None;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(100)),
            Ok(None) => {
                timed_out = true;
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            Err(e) => {
                wait_error = Some(e);
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
        }
    };

    if let Some(error) = wait_error {
        Err(format!("wait for command failed: {error}"))
    } else if timed_out {
        let detail = format!(
            "RUNTIME_INSTALL_TIMEOUT|runtime setup exceeded {} seconds while running {}",
            RUNTIME_SETUP_TIMEOUT.as_secs(),
            command_debug
        );
        let _ = writeln!(log, "\n{}", detail);
        Err(detail)
    } else if status.is_some_and(|status| status.success()) {
        Ok(())
    } else {
        Err(format!(
            "command failed with status {}",
            status
                .map(|value| value.to_string())
                .unwrap_or_else(|| "unknown".to_string())
        ))
    }
}

pub(crate) fn health_check_python(
    py: &Path,
    code: &str,
    log_path: &Path,
    deadline: Instant,
) -> bool {
    if !py.exists() {
        return false;
    }
    let mut cmd = Command::new(py);
    cmd.args(["-c", code]);
    apply_runtime_bootstrap_env(&mut cmd, None);
    apply_no_window(&mut cmd);
    run_and_log(cmd, log_path, deadline).is_ok()
}

pub(crate) fn quarantine_runtime_uv_cache(report: &mut String) {
    let cache_dir = runtime_uv_cache_dir();
    if !cache_dir.exists() {
        report.push_str(&format!("uv cache absent: {}\n", cache_dir.display()));
        if let Err(e) = fs::create_dir_all(&cache_dir) {
            report.push_str(&format!(
                "warn: recreate uv cache dir {} failed: {}\n",
                cache_dir.display(),
                e
            ));
        }
        return;
    }

    let quarantine = runtime_root_dir()
        .join("reports")
        .join(format!("uv-cache-quarantine-{}", now_epoch_secs()));
    match fs::rename(&cache_dir, &quarantine) {
        Ok(()) => {
            report.push_str(&format!(
                "quarantined uv cache {} -> {}\n",
                cache_dir.display(),
                quarantine.display()
            ));
        }
        Err(rename_err) => {
            report.push_str(&format!(
                "warn: quarantine uv cache {} failed: {}; deleting cache\n",
                cache_dir.display(),
                rename_err
            ));
            match fs::remove_dir_all(&cache_dir) {
                Ok(()) => report.push_str(&format!("removed uv cache {}\n", cache_dir.display())),
                Err(remove_err) => report.push_str(&format!(
                    "warn: remove uv cache {} failed: {}\n",
                    cache_dir.display(),
                    remove_err
                )),
            }
        }
    }
    if let Err(e) = fs::create_dir_all(&cache_dir) {
        report.push_str(&format!(
            "warn: recreate uv cache dir {} failed: {}\n",
            cache_dir.display(),
            e
        ));
    }
}

/// Disallowed base-Python markers shared by:
///   * `venv_is_real_isolated` —— Rust 端读 `pyvenv.cfg::home`；
///   * `app_runtime_health_code` —— Python 端二次校验同一 marker。
///
/// 两侧共享同一份 marker 是关键：如果只在 Python 端拦，Rust 端
/// `venv_is_real_isolated` 会认为旧的 anaconda-base venv 还能用，跳过重建，
/// 每次启动都白白浪费一次 wheel install。
///
/// 拒绝列表覆盖：Anaconda/Miniconda/Mambaforge/Miniforge、WindowsApps stub、
/// pyenv、Homebrew Cellar、asdf、mise、rye。这些 base Python 之上创建的 venv
/// 一旦命中坏 pydantic / 错版本 OpenSSL，启动后会以 SystemExit(23) 失败。
pub(crate) const BAD_BASE_PYTHON_MARKERS: &[&str] = &[
    "anaconda",
    "miniconda",
    "conda",
    "mambaforge",
    "miniforge",
    "windowsapps",
    "appinstallerpythonredirector",
    ".pyenv",
    "homebrew",
    "/cellar/",
    "\\cellar\\",
    ".asdf",
    ".mise",
    ".rye/py",
    ".rye\\py",
];

/// Disallowed PATH segments. 用于 §2 的 PATH 过滤，跟 base python marker 概念
/// 区分开（PATH 段是字符串匹配整段路径，base python 是 `pyvenv.cfg::home`
/// 单一目录）。两个列表故意分开维护，避免误伤合法路径段（例如某些项目用
/// `homebrew-bottles` 但目的不是激活 Homebrew Python）。
pub(crate) const BAD_PATH_MARKERS: &[&str] = &[
    "anaconda",
    "miniconda",
    "conda",
    "mambaforge",
    "miniforge",
    ".pyenv",
    "homebrew",
    "/cellar/",
    "\\cellar\\",
    ".asdf",
    ".mise",
    ".rye/py",
    ".rye\\py",
    "windowsapps",
];

/// 把绝对路径规整为统一可比较形式（lowercase + canonicalize，失败回退原值）。
/// 用于 marker 子串匹配 / 白名单 starts_with 检查时，跨平台保持一致。
pub(crate) fn normalize_path_for_compare(path: &Path) -> String {
    let resolved = path
        .canonicalize()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|_| path.to_string_lossy().to_string());
    resolved.to_lowercase()
}

/// 判断 `home` 是否落在我们自己管理的 Python 池里（PBS seed 或 uv 下载的
/// managed Python）。命中即视为可信，无视 marker 子串。
///
/// 解决的边角：用户把 OpenKitsune 安装到 `C:\anaconda3\OpenKitsune\` 这种路径，
/// 我们的 seed `pyvenv.cfg::home = C:\anaconda3\OpenKitsune\resources\bootstrap\python`
/// 子串命中 "anaconda" 会被 `BAD_BASE_PYTHON_MARKERS` 误拒，进而陷入
/// "venv 自清 → 重建 → 仍被拒"的无限循环，永远走不到 dual-venv。
pub(crate) fn home_is_under_managed_python_root(home: &str) -> bool {
    let home_norm = normalize_path_for_compare(Path::new(home));
    let candidates = [
        bootstrap_resource_dir().join("python"), // PBS seed
        runtime_cache_dir().join("python"),      // uv downloaded managed
    ];
    for root in &candidates {
        let root_norm = normalize_path_for_compare(root);
        // 空字符串保护：路径不存在时 canonicalize 返回原值；空 root 不能用 starts_with。
        if !root_norm.is_empty() && home_norm.starts_with(&root_norm) {
            return true;
        }
    }
    false
}

/// 读取 `pyvenv.cfg` 的 `home=` 行，命中 `BAD_BASE_PYTHON_MARKERS` 返回 true。
/// 解析失败（例如文件残缺）当成 "未命中"，把判断交给后续的 import 测试。
///
/// 白名单：home 落在我们自己管理的 Python 池里时，永远不拒绝（避免
/// "用户装在 C:\anaconda3\OpenKitsune\ → seed 路径含 anaconda → 自拒死循环"）。
pub(crate) fn pyvenv_cfg_home_is_disallowed(venv_dir: &Path) -> Option<String> {
    let cfg = venv_dir.join("pyvenv.cfg");
    let text = fs::read_to_string(&cfg).ok()?;
    let mut home: Option<String> = None;
    for line in text.lines() {
        let lower = line.to_lowercase();
        if lower.starts_with("home") || lower.starts_with("base-executable") {
            if let Some((_, rhs)) = line.split_once('=') {
                home = Some(rhs.trim().to_string());
                break;
            }
        }
    }
    let home = home?;
    if home_is_under_managed_python_root(&home) {
        return None;
    }
    let lower = home.to_lowercase();
    if BAD_BASE_PYTHON_MARKERS.iter().any(|m| lower.contains(m)) {
        Some(home)
    } else {
        None
    }
}

/// 严格判断目录是否是一个完整的 venv。
///
/// uv 在 Windows 上创建 venv 时会先写 `Scripts/python.exe`（一个 launcher
/// 桩），随后再写 `pyvenv.cfg`、`Lib/site-packages/`、seed pip。如果中间任何
/// 一步失败（被杀软拦截、断网下载 pip 失败、权限问题、用户强行关窗口等），
/// 残骸 launcher 会留在磁盘上。它跑起来时因为读不到 `pyvenv.cfg`，
/// `sys.prefix` 会回退到 base interpreter（即 uv 管理的全局 Python），
/// `import pip` 也能成功——但 `uv pip install --python <这个 launcher>`
/// 会判定为 "externally managed" 而拒绝安装。所以光看 `import pip`
/// 不足以证明这是一个真正的、隔离的 venv。
///
/// 额外地：直接拒绝 `pyvenv.cfg::home` 指向 Anaconda/pyenv/Homebrew 等
/// 受污染发行版的 venv（v1.27.10 启动失败的根因）。共享 `BAD_BASE_PYTHON_MARKERS`
/// 让 Rust 与 Python 两侧的判定逻辑严格对齐。
pub(crate) fn venv_is_real_isolated(
    venv_dir: &Path,
    py: &Path,
    log_path: &Path,
    deadline: Instant,
) -> bool {
    if !py.exists() {
        return false;
    }
    if !venv_dir.join("pyvenv.cfg").exists() {
        return false;
    }
    if let Some(home) = pyvenv_cfg_home_is_disallowed(venv_dir) {
        if let Ok(mut log) = OpenOptions::new().create(true).append(true).open(log_path) {
            let _ = writeln!(
                log,
                "venv {} rejected: pyvenv.cfg home={} matches BAD_BASE_PYTHON_MARKERS",
                venv_dir.display(),
                home
            );
        }
        return false;
    }
    health_check_python(
        py,
        "import sys, pip; assert sys.prefix != sys.base_prefix, 'venv launcher fell back to base interpreter'",
        log_path,
        deadline,
    )
}

pub(crate) fn app_runtime_health_code(venv_dir: &Path) -> String {
    let venv = python_string_literal(venv_dir);
    let home_markers = python_tuple_literal(BAD_BASE_PYTHON_MARKERS);
    let path_markers = python_tuple_literal(BAD_PATH_MARKERS);
    // 把"我们自己管理的 Python 池"也注入到 Python 侧，与 Rust
    // `home_is_under_managed_python_root` 严格对齐。让 marker 子串误命中我们
    // 自己 seed 路径的场景（用户装到 C:\anaconda3\OpenKitsune\）也能放行。
    let managed_seed = python_string_literal(&bootstrap_resource_dir().join("python"));
    let managed_uv = python_string_literal(&runtime_cache_dir().join("python"));
    format!(
        r#"
import importlib, json, pathlib, site, sys

venv = pathlib.Path({venv}).resolve()
managed_roots = []
for raw in ({managed_seed}, {managed_uv}):
    try:
        managed_roots.append(str(pathlib.Path(raw).resolve()).lower())
    except Exception:
        managed_roots.append(str(raw).lower())

report = {{
    "sys_executable": sys.executable,
    "sys_prefix": sys.prefix,
    "sys_base_prefix": sys.base_prefix,
    "sys_prefix_resolved": str(pathlib.Path(sys.prefix).resolve()),
    "venv": str(venv),
    "sys_path": sys.path,
    "site_packages": [],
    "packages": {{}},
    "package_errors": {{}},
    "native_extensions": [],
    "nul_byte_files": [],
    "managed_roots": managed_roots,
}}

def scan_nul_bytes(root, limit=20):
    try:
        base = pathlib.Path(root)
        for py_file in base.rglob("*.py"):
            try:
                data = py_file.read_bytes()
            except Exception:
                continue
            if b"\x00" in data:
                report["nul_byte_files"].append(str(py_file.resolve()))
                if len(report["nul_byte_files"]) >= limit:
                    break
    except Exception as exc:
        report["nul_scan_error"] = repr(exc)

def fail(reason):
    scan_nul_bytes(venv / "Lib" / "site-packages")
    scan_nul_bytes(venv / "lib")
    report["health_status"] = "failed"
    report["health_reason"] = reason
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(23)

def is_under(path, root):
    try:
        pathlib.Path(path).resolve().relative_to(root)
        return True
    except Exception:
        return False

def is_managed_home(home):
    try:
        h = str(pathlib.Path(home).resolve()).lower()
    except Exception:
        h = str(home).lower()
    return any(r and h.startswith(r) for r in managed_roots)

cfg = venv / "pyvenv.cfg"
if not cfg.exists():
    fail("pyvenv.cfg missing")
if pathlib.Path(sys.prefix).resolve() != venv:
    fail("sys.prefix does not match expected venv")
if sys.prefix == sys.base_prefix:
    fail("venv launcher fell back to base interpreter")

cfg_text = cfg.read_text(encoding="utf-8", errors="replace")
home = ""
for line in cfg_text.splitlines():
    if line.lower().startswith("home"):
        home = line.split("=", 1)[1].strip()
        break
report["pyvenv_home"] = home
report["pyvenv_home_managed"] = is_managed_home(home) if home else False
bad_home_markers = {home_markers}
if (
    not is_managed_home(home)
    and any(marker in home.lower() for marker in bad_home_markers)
):
    fail("pyvenv.cfg home points to disallowed Python: " + home)

try:
    report["site_packages"] = [str(pathlib.Path(p).resolve()) for p in site.getsitepackages()]
except Exception as exc:
    report["site_packages_error"] = repr(exc)
report["user_site"] = getattr(site, "ENABLE_USER_SITE", None)
if getattr(site, "ENABLE_USER_SITE", False):
    fail("user site-packages is enabled")

bad_path_markers = {path_markers}
for p in sys.path:
    low = str(p).lower()
    if "site-packages" in low and any(marker in low for marker in bad_path_markers):
        fail("sys.path contains disallowed site-packages: " + str(p))

for mod_name in ("openkitsune", "yaml", "pydantic", "pydantic_core", "certifi"):
    try:
        mod = importlib.import_module(mod_name)
    except Exception as exc:
        report["package_errors"][mod_name] = {{
            "type": type(exc).__name__,
            "message": str(exc),
            "filename": getattr(exc, "filename", ""),
            "lineno": getattr(exc, "lineno", None),
        }}
        fail(f"{{mod_name}} import failed: {{type(exc).__name__}}: {{exc}}")
    mod_file = pathlib.Path(getattr(mod, "__file__", "") or "").resolve()
    report["packages"][mod_name] = str(mod_file)
    if not mod_file or not is_under(mod_file, venv):
        fail(f"{{mod_name}} imported from outside app runtime: {{mod_file}}")
    root = mod_file.parent
    for ext in list(root.rglob("*.pyd")) + list(root.rglob("*.so")) + list(root.rglob("*.dylib")):
        report["native_extensions"].append(str(ext.resolve()))
        if not is_under(ext, venv):
            fail("native extension imported from outside app runtime: " + str(ext))

report["health_status"] = "ok"
print(json.dumps(report, ensure_ascii=False, indent=2))
"#
    )
}

pub(crate) fn ensure_venv(
    venv_dir: &Path,
    python_version: &str,
    log_path: &Path,
    deadline: Instant,
) -> Result<PathBuf, String> {
    let py = runtime_venv_python_path(venv_dir);
    if venv_is_real_isolated(venv_dir, &py, log_path, deadline) {
        return Ok(py);
    }

    // 在重建前彻底清空残骸目录。`uv venv --clear` 自身在某些边界条件下
    // 会留下半残文件（典型场景：上次 uv 在 seed pip 阶段被中断，留下
    // launcher 但缺 pyvenv.cfg），下次再调 `uv venv --clear` 不一定能恢复。
    // 自己 remove_dir_all 一刀更稳。
    if venv_dir.exists() {
        if let Err(e) = fs::remove_dir_all(venv_dir) {
            if let Ok(mut log) = OpenOptions::new().create(true).append(true).open(log_path) {
                let _ = writeln!(
                    log,
                    "warning: pre-clean of {} failed: {} (will fall back to `uv venv --clear`)",
                    venv_dir.display(),
                    e
                );
            }
        }
    }

    let uv = bootstrap_uv_path();
    let mut cmd = Command::new(&uv);
    // uv does not guarantee pip is present unless the venv is seeded. The
    // runtime manager immediately uses `uv pip install` and the health checks
    // require `import pip`, so seed the venv at creation time.
    cmd.arg("venv");
    if let Some(seed) = managed_python_seed_path() {
        // POSIX defensive 0o755 on the seed binary right before invocation.
        // 解决两个边角：
        //   1. installer 解压时 mode bit 在某些杀软策略下被重置；
        //   2. Sync 工具（Dropbox / iCloud / OneDrive 同步用户目录）回写后
        //      丢失 exec bit。
        // 与 prepare 阶段的 chmod 和 CI 校验形成三道防线；忽略错误，
        // 失败时让后续 uv 自己报 EACCES 给用户看，保持现有错误链。
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = fs::metadata(&seed) {
                let mut perms = meta.permissions();
                let current = perms.mode() & 0o777;
                if current & 0o111 == 0 {
                    perms.set_mode(0o755);
                    let _ = fs::set_permissions(&seed, perms);
                    log_to_file(&format!(
                        "[runtime] restored exec bit on seed Python: {} (was {:o})",
                        seed.display(),
                        current
                    ));
                }
            }
        }
        cmd.arg("--python").arg(&seed);
    } else {
        cmd.args(["--python", python_version]);
    }
    cmd.args(["--seed", "--clear"]);
    cmd.arg(venv_dir);
    apply_runtime_bootstrap_env(&mut cmd, None);
    apply_no_window(&mut cmd);
    run_and_log(cmd, log_path, deadline)?;
    if venv_is_real_isolated(venv_dir, &py, log_path, deadline) {
        Ok(py)
    } else {
        let has_cfg = venv_dir.join("pyvenv.cfg").exists();
        Err(format!(
            "venv health check failed after creation: {} (pyvenv.cfg present={}, see {} for details)",
            py.display(),
            has_cfg,
            log_path.display()
        ))
    }
}

pub(crate) fn ensure_app_venv(
    bootstrap: &BootstrapManifest,
    pip_index: &RuntimePipIndex,
    deadline: Instant,
) -> Result<PathBuf, String> {
    let started = Instant::now();
    let log_path = runtime_logs_dir().join("app-venv.log");
    let app_py = runtime_venv_python_path(&app_venv_dir());
    let manifest_result = read_runtime_manifest();
    let manifest_ok = manifest_result
        .as_ref()
        .map(|m| runtime_manifest_mismatch(m, bootstrap, pip_index).is_none())
        .unwrap_or(false);
    if manifest_ok
        && health_check_python(
            &app_py,
            &app_runtime_health_code(&app_venv_dir()),
            &log_path,
            deadline,
        )
    {
        log_to_file(&format!(
            "[runtime] ensure_app_venv reused existing env in {}ms",
            started.elapsed().as_millis()
        ));
        return Ok(app_py);
    }

    if let Some(manifest) = manifest_result.as_ref() {
        let reason = runtime_manifest_mismatch(manifest, bootstrap, pip_index)
            .unwrap_or_else(|| "health_check failed".to_string());
        log_to_file(&format!(
            "[runtime] ensure_app_venv rebuilding app runtime: {}",
            reason
        ));
    } else {
        log_to_file("[runtime] ensure_app_venv rebuilding app runtime: missing manifest");
    }
    let app_py = ensure_venv(
        &app_venv_dir(),
        &bootstrap.python_version,
        &log_path,
        deadline,
    )?;
    let wheel_path = bootstrap_resource_dir().join(&bootstrap.wheel.name);
    if !wheel_path.exists() {
        return Err(format!(
            "bootstrap wheel not found: {}",
            wheel_path.display()
        ));
    }
    let extras = app_runtime_extras();
    let wheel_arg = if extras.is_empty() {
        wheel_path.display().to_string()
    } else {
        format!("{}[{}]", wheel_path.display(), extras.join(","))
    };
    let mut cmd = Command::new(bootstrap_uv_path());
    cmd.args(["pip", "install", "--python"]);
    cmd.arg(&app_py);
    cmd.arg(wheel_arg);
    // 显式把 certifi 加进同一次安装：虽然 httpx/requests/aiohttp 会传递依赖
    // certifi，但 [desktop] extras 不一定每次都触发它；显式钉死避免万一某个
    // resolver 走捷径跳过 certifi 导致 ssl.create_default_context() 找不到
    // cacert.pem（用户日志里 dashscope/QQBot 的 SSL [Errno 2] 根因）。
    cmd.arg("certifi");
    cmd.args(["--reinstall-package", "openkitsune"]);
    // `uv pip install` does not support pip's `--prefer-binary` flag.
    // Keep binary preference on Python-side `pip install` calls only.
    if bootstrap_declares_complete_wheelhouse(bootstrap) && wheelhouse_has_locked_deps(&wheel_path)
    {
        let wheelhouse = bootstrap_wheelhouse_dir();
        log_to_file(&format!(
            "[runtime] app wheel install using bundled wheelhouse: {}",
            wheelhouse.display()
        ));
        cmd.arg("--no-index");
        cmd.arg("--find-links");
        cmd.arg(wheelhouse);
    } else {
        log_to_file(&format!(
            "[runtime] app wheel install using pip index: {}",
            pip_index.url
        ));
        cmd.args(["--index-url", &pip_index.url]);
        if !pip_index.trusted_host.trim().is_empty() {
            cmd.args(["--trusted-host", &pip_index.trusted_host]);
        }
        if bootstrap_wheelhouse_dir().is_dir() {
            log_to_file(
                "[runtime] bundled wheelhouse present but not marked complete; using pip index",
            );
        }
    }
    apply_runtime_bootstrap_env(&mut cmd, Some(pip_index));
    apply_no_window(&mut cmd);
    let install_started = Instant::now();
    run_and_log(cmd, &log_path, deadline)?;
    log_to_file(&format!(
        "[runtime] app wheel install finished in {}ms",
        install_started.elapsed().as_millis()
    ));
    if health_check_python(
        &app_py,
        &app_runtime_health_code(&app_venv_dir()),
        &log_path,
        deadline,
    ) {
        log_to_file(&format!(
            "[runtime] ensure_app_venv ready in {}ms",
            started.elapsed().as_millis()
        ));
        Ok(app_py)
    } else {
        // health check 失败：必须把整个 app-venv 目录干掉，避免下一次启动
        // `venv_is_real_isolated` 仍把它当成"完整 venv"，跳过重建，又白白
        // 跑一次 30–60s 的 wheel install + 同样的 reject。`remove_dir_all`
        // 失败不致命（下次 `uv venv --clear` 还会兜底），只记录到日志。
        if let Err(e) = fs::remove_dir_all(app_venv_dir()) {
            log_to_file(&format!(
                "[runtime] post-fail cleanup of {} failed: {}",
                app_venv_dir().display(),
                e
            ));
        } else {
            log_to_file(&format!(
                "[runtime] post-fail cleanup of {} succeeded",
                app_venv_dir().display()
            ));
        }
        Err(format!(
            "app venv health check failed after OpenKitsune install: python={}, log={}",
            app_py.display(),
            log_path.display()
        ))
    }
}

pub(crate) fn ensure_agent_venv(
    bootstrap: &BootstrapManifest,
    _pip_index: &RuntimePipIndex,
    deadline: Instant,
) -> Result<PathBuf, String> {
    let started = Instant::now();
    let log_path = runtime_logs_dir().join("agent-venv.log");
    let result = ensure_venv(
        &agent_venv_dir(),
        &bootstrap.python_version,
        &log_path,
        deadline,
    );
    log_to_file(&format!(
        "[runtime] ensure_agent_venv finished in {}ms status={}",
        started.elapsed().as_millis(),
        if result.is_ok() { "ok" } else { "error" }
    ));
    result
}

pub(crate) fn write_runtime_manifest(info: &RuntimeEnvInfo, bootstrap: &BootstrapManifest) {
    let now = now_epoch_secs().to_string();
    let manifest = RuntimeManifest {
        schema_version: 1,
        app_version: env!("CARGO_PKG_VERSION").into(),
        wheel_hash: bootstrap.wheel.sha256.clone(),
        python_version: bootstrap.python_version.clone(),
        python_seed_fingerprint: bootstrap_python_seed_fingerprint(bootstrap),
        extras: app_runtime_extras(),
        uv_path: bootstrap_uv_path().to_string_lossy().to_string(),
        app_venv: RuntimeEnvState {
            path: info.app_venv.to_string_lossy().to_string(),
            status: "ready".into(),
            created_at: now.clone(),
            last_verified_at: now.clone(),
        },
        agent_venv: RuntimeEnvState {
            path: info.agent_venv.to_string_lossy().to_string(),
            status: "ready".into(),
            created_at: now.clone(),
            last_verified_at: now,
        },
        pip_index: info.pip_index.clone(),
        legacy_mode: false,
        last_error: None,
    };
    if let Ok(content) = serde_json::to_string_pretty(&manifest) {
        let _ = fs::write(runtime_manifest_path(), content);
    }
}

pub(crate) fn mark_legacy_runtime_mode(error: &str) {
    let pip_index = resolve_runtime_pip_index();
    let now = now_epoch_secs().to_string();
    // Persist the bootstrap identity even when runtime creation fails so the
    // diagnostics page can explain which wheel and Python seed were attempted.
    let (wheel_hash, python_version) = match read_bootstrap_manifest() {
        Ok(b) => (b.wheel.sha256, b.python_version),
        Err(_) => (String::new(), "3.12".to_string()),
    };
    let manifest = RuntimeManifest {
        schema_version: 1,
        app_version: env!("CARGO_PKG_VERSION").into(),
        wheel_hash,
        python_version,
        python_seed_fingerprint: String::new(),
        extras: app_runtime_extras(),
        uv_path: bootstrap_uv_path().to_string_lossy().to_string(),
        app_venv: RuntimeEnvState {
            path: app_venv_dir().to_string_lossy().to_string(),
            status: "failed".into(),
            created_at: now.clone(),
            last_verified_at: now.clone(),
        },
        agent_venv: RuntimeEnvState {
            path: agent_venv_dir().to_string_lossy().to_string(),
            status: "unknown".into(),
            created_at: now.clone(),
            last_verified_at: now,
        },
        pip_index,
        legacy_mode: true,
        last_error: Some(error.to_string()),
    };
    if let Ok(content) = serde_json::to_string_pretty(&manifest) {
        let _ = fs::write(runtime_manifest_path(), content);
    }
}

pub(crate) fn write_runtime_failure_manifest(error: &str) {
    let pip_index = resolve_runtime_pip_index();
    let now = now_epoch_secs().to_string();
    let (wheel_hash, python_version) = match read_bootstrap_manifest() {
        Ok(b) => (b.wheel.sha256, b.python_version),
        Err(_) => (String::new(), default_python_version()),
    };
    let manifest = RuntimeManifest {
        schema_version: 1,
        app_version: env!("CARGO_PKG_VERSION").into(),
        wheel_hash,
        python_version,
        python_seed_fingerprint: String::new(),
        extras: app_runtime_extras(),
        uv_path: bootstrap_uv_path().to_string_lossy().to_string(),
        app_venv: RuntimeEnvState {
            path: app_venv_dir().to_string_lossy().to_string(),
            status: "failed".into(),
            created_at: now.clone(),
            last_verified_at: now.clone(),
        },
        agent_venv: RuntimeEnvState {
            path: agent_venv_dir().to_string_lossy().to_string(),
            status: "failed".into(),
            created_at: now.clone(),
            last_verified_at: now,
        },
        pip_index,
        legacy_mode: false,
        last_error: Some(error.to_string()),
    };
    if let Ok(content) = serde_json::to_string_pretty(&manifest) {
        let _ = fs::write(runtime_manifest_path(), content);
    }
}

pub(crate) fn ensure_dual_runtime_env() -> Result<RuntimeEnvInfo, String> {
    let started = Instant::now();
    let deadline = started + RUNTIME_SETUP_TIMEOUT;
    log_to_file("[runtime] phase=prepare-runtime-layout");
    ensure_runtime_layout()?;
    let bootstrap = read_bootstrap_manifest()?;
    let pip_index = resolve_runtime_pip_index();
    log_to_file(&format!(
        "[runtime] phase=ensure-app-venv uv={} extras={:?} pip_index={}",
        bootstrap_uv_path().display(),
        app_runtime_extras(),
        pip_index.url
    ));
    let app_python = ensure_app_venv(&bootstrap, &pip_index, deadline)?;
    log_to_file("[runtime] phase=ensure-agent-venv");
    let agent_python = ensure_agent_venv(&bootstrap, &pip_index, deadline)?;
    let info = RuntimeEnvInfo {
        app_python,
        agent_python,
        app_venv: app_venv_dir(),
        agent_venv: agent_venv_dir(),
        pip_index,
    };
    write_runtime_manifest(&info, &bootstrap);
    log_to_file(&format!(
        "[runtime] ensure_dual_runtime_env finished in {}ms",
        started.elapsed().as_millis()
    ));
    Ok(info)
}

/// 读取 cmd 上已设置的 PATH（如有），找不到则回退到父进程 PATH。
/// Windows 环境变量名大小写不敏感，所以采用 eq_ignore_ascii_case。
pub(crate) fn cmd_get_env_path(cmd: &Command) -> Option<std::ffi::OsString> {
    cmd.get_envs().find_map(|(k, v)| {
        let key = k.to_string_lossy();
        if key.eq_ignore_ascii_case("path") {
            v.map(|s| s.to_os_string())
        } else {
            None
        }
    })
}

pub(crate) fn prepend_path(cmd: &mut Command, dir: &Path) {
    // 关键：优先读 cmd 上已设置的 PATH —— 上游 `filter_path_for_runtime` 可能
    // 已经把 anaconda/pyenv/homebrew 等污染段剔除并写回 cmd；如果这里仍然
    // 读父进程 PATH，会把过滤掉的段又带回来，让 §2 的 PATH 过滤白做。
    // 找不到再回退到父进程 PATH，与原行为兼容。
    let current =
        cmd_get_env_path(cmd).unwrap_or_else(|| std::env::var_os("PATH").unwrap_or_default());
    let mut paths = vec![dir.to_path_buf()];
    paths.extend(std::env::split_paths(&current));
    if let Ok(joined) = std::env::join_paths(paths) {
        cmd.env("PATH", joined);
    }
}

/// 从子进程 PATH 中剔除已知会污染 Python 发现的目录段（anaconda / pyenv /
/// homebrew / mise / asdf / WindowsApps stub）。
///
/// 与 `BAD_BASE_PYTHON_MARKERS`（pyvenv.cfg::home 检查）共用同一组关键字概念
/// 但**故意不共享列表**：PATH 段是整段路径子串匹配，过宽会误伤合法路径，例如
/// 用户把项目放在 `D:\anaconda-projects\` 下并不应当被剔除（那个目录里没有
/// `python.exe`）。所以 PATH 过滤的 marker 边界与 BAD_PATH_MARKERS 对齐，
/// 但保持独立维护，给后续微调留余地。
///
/// 实现策略：
///   * 用 `std::env::split_paths` 解析当前进程 PATH（按 `;`/`:` 自动适配
///     平台分隔符）；
///   * 对每段路径做 lowercase 后子串比对（Windows 不区分大小写、*nix 也兼容
///     `/opt/Anaconda` 这种异常大小写）；
///   * 命中关键字的段**只**在该段末尾或其下确实存在 `python` / `python.exe`
///     时才剔除。这样不会误伤"anaconda-projects/data"这种巧合命名的工作目录。
///   * 把剩余段重新 `join_paths` 写回子进程 env。
pub(crate) fn filter_path_for_runtime(cmd: &mut Command) {
    let current = match std::env::var_os("PATH") {
        Some(v) => v,
        None => return,
    };
    let mut kept: Vec<PathBuf> = Vec::new();
    let mut removed: Vec<String> = Vec::new();
    for seg in std::env::split_paths(&current) {
        let lowered = seg.to_string_lossy().to_lowercase();
        let matched = BAD_PATH_MARKERS.iter().any(|m| lowered.contains(m));
        if matched && segment_contains_python_binary(&seg) {
            removed.push(seg.to_string_lossy().to_string());
            continue;
        }
        kept.push(seg);
    }
    if !removed.is_empty() {
        log_to_file(&format!(
            "[runtime] PATH filtered: stripped {} segments matching BAD_PATH_MARKERS; sample={:?}",
            removed.len(),
            removed.iter().take(3).collect::<Vec<_>>()
        ));
    }
    if let Ok(joined) = std::env::join_paths(kept) {
        cmd.env("PATH", joined);
    }
}

/// 判断给定路径段下是否真的能找到一个 Python 可执行文件。
/// 用于 `filter_path_for_runtime` 仅在该段确实承载 Python 时才剔除，
/// 减少误伤。
pub(crate) fn segment_contains_python_binary(seg: &Path) -> bool {
    if !seg.is_dir() {
        return false;
    }
    let candidates: &[&str] = if cfg!(windows) {
        &["python.exe", "python3.exe", "pythonw.exe"]
    } else {
        &["python", "python3", "python3.11", "python3.12"]
    };
    candidates.iter().any(|name| seg.join(name).exists())
}

pub(crate) fn apply_dual_runtime_env(cmd: &mut Command) {
    apply_runtime_core_env(cmd);
}

/// 获取后端可执行文件及参数。
///
/// Release builds use the managed app-venv exclusively. The legacy venv path
/// remains only for existing development and pre-dual-runtime installations.
pub(crate) fn get_backend_executable(venv_dir: &str) -> (PathBuf, Vec<String>) {
    match ensure_dual_runtime_env() {
        Ok(runtime) => {
            let backend_python = runtime_venv_backend_python_path(&runtime.app_venv);
            log_to_file(&format!(
                "[runtime] dual venv ready: app_python={}, backend_python={}, agent_python={}",
                runtime.app_python.display(),
                backend_python.display(),
                runtime.agent_python.display()
            ));
            return (backend_python, runtime_venv_backend_args(&runtime.app_venv));
        }
        Err(e) => {
            log_to_file(&format!("[runtime] dual venv unavailable: {e}"));
            mark_legacy_runtime_mode(&e);
        }
    }

    // Compatibility only: old installations and local development may still
    // have ~/.openkitsune/venv. New installers do not create this environment.
    eprintln!(
        "[backend] managed app runtime unavailable\n\
         [backend] current_exe: {:?}\n\
         [backend] falling back to venv python in: {}",
        std::env::current_exe()
            .ok()
            .map(|p| p.display().to_string()),
        venv_dir,
    );
    let py = venv_pythonw_path(venv_dir);
    (py, canonical_backend_args())
}

/// 构建可选模块路径字符串（自动从 module_definitions 获取模块列表）
/// 返回 path-separated 的 site-packages 目录列表，用于 OPENKITSUNE_MODULE_PATHS 环境变量
pub(crate) fn build_modules_pythonpath() -> Option<String> {
    let base = modules_dir();
    if !base.exists() {
        return None;
    }
    let mut paths = Vec::new();
    for module in module_definitions() {
        let sp = base.join(module.id).join("site-packages");
        if sp.exists() {
            paths.push(sp.to_string_lossy().to_string());
        }
    }
    if paths.is_empty() {
        return None;
    }
    let sep = if cfg!(windows) { ";" } else { ":" };
    Some(paths.join(sep))
}

/// 查找可用于 pip install 的 Python 可执行文件路径
pub(crate) fn find_pip_python() -> Option<PathBuf> {
    let root = openkitsune_root_dir();
    // 1. venv python
    let venv_py = if cfg!(windows) {
        root.join("venv").join("Scripts").join("python.exe")
    } else {
        root.join("venv").join("bin").join("python")
    };
    if venv_py.exists() {
        return Some(venv_py);
    }
    // 2. 安装包内置的 standalone Python seed
    if let Some(py) = managed_python_seed_path() {
        return Some(py);
    }
    // 不再搜索用户系统 PATH 中的 Python，也不再运行时下载 Python。
    // 统一要求：使用安装包内置 Python 创建/修复 venv。
    None
}

/// 检查是否有可用于 pip install 的 Python 解释器
#[tauri::command]
pub(crate) fn check_python_for_pip() -> Result<String, String> {
    match find_pip_python() {
        Some(p) => Ok(format!("Python 可用: {}", p.display())),
        None => Err("未找到可用的 Python 解释器".into()),
    }
}

/// 暴露 runtime manifest 的 `last_error` 与 `legacy_mode` 给前端。
///
/// 用途：前端 StatusView 在"后端已停止 / 启动失败"时调本命令，识别
/// `RUNTIME_PERMISSION_DENIED|...` 前缀并渲染中英双语指引 + "打开运行时
/// 目录"按钮。其它结构化前缀（如 `RUNTIME_WHEEL_HASH_MISMATCH|`）也走
/// 同一通道，前端按前缀分发。
///
/// 返回 None 表示尚无 runtime manifest（首次启动尚未跑到 ensure_runtime_layout）。
#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RuntimeLastError {
    last_error: Option<String>,
    legacy_mode: bool,
    runtime_root: String,
    manifest_path: String,
}

#[tauri::command]
pub(crate) fn openkitsune_runtime_last_error() -> RuntimeLastError {
    let manifest = read_runtime_manifest();
    RuntimeLastError {
        last_error: manifest.as_ref().and_then(|m| m.last_error.clone()),
        legacy_mode: manifest.as_ref().map(|m| m.legacy_mode).unwrap_or(false),
        runtime_root: runtime_root_dir().to_string_lossy().to_string(),
        manifest_path: runtime_manifest_path().to_string_lossy().to_string(),
    }
}

/// "打开 runtime 目录"命令——专门为 PermissionDenied 等 banner 设计。
///
/// 与通用 `show_item_in_folder` 不同的点：当 runtime root 还没被创建（典型场景
/// 就是 PermissionDenied 之前的失败），通用命令会直接抛 `Path does not exist`，
/// 用户什么也看不到。本命令向上溯源，找到最近一级**确实存在**的祖先目录
/// 并打开，让用户能在自己的文件管理器里看到现场（例如 `%LOCALAPPDATA%\
/// OpenKitsuneDesktop\` 还在，但 `runtime\` 子目录因为 AD 策略建不出来）。
///
/// 返回的 `fellBack=true` 标记给前端用，用来弹一条"我们退回到上一级"的提示。
#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct OpenedRuntimePath {
    opened: String,
    /// true: 目标路径不存在，已退回到最近一级存在的祖先。
    fell_back: bool,
}

pub(crate) fn first_existing_ancestor(start: &Path) -> Option<PathBuf> {
    let mut cur: Option<&Path> = Some(start);
    while let Some(p) = cur {
        if p.exists() {
            return Some(p.to_path_buf());
        }
        cur = p.parent();
    }
    None
}

pub(crate) fn reveal_in_file_manager(path: &Path) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let mut c = std::process::Command::new("explorer");
        // 目录直接打开，文件用 /select, 高亮。
        if path.is_dir() {
            c.arg(path);
        } else {
            c.args(["/select,", &path.to_string_lossy()]);
        }
        apply_no_window(&mut c);
        c.spawn()
            .map_err(|e| format!("Failed to open explorer: {e}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        // Finder 对目录/文件都接受 -R（reveal）；目录则直接 open 也可。
        let arg = if path.is_dir() { "" } else { "-R" };
        let mut c = std::process::Command::new("open");
        if !arg.is_empty() {
            c.arg(arg);
        }
        c.arg(path);
        c.spawn()
            .map_err(|e| format!("Failed to reveal in Finder: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        let target: PathBuf = if path.is_dir() {
            path.to_path_buf()
        } else {
            path.parent()
                .map(|p| p.to_path_buf())
                .unwrap_or_else(|| path.to_path_buf())
        };
        std::process::Command::new("xdg-open")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("Failed to open file manager: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn openkitsune_open_runtime_root() -> Result<OpenedRuntimePath, String> {
    let target = runtime_root_dir();
    let (resolved, fell_back) = if target.exists() {
        (target.clone(), false)
    } else {
        let ancestor = first_existing_ancestor(&target).ok_or_else(|| {
            format!(
                "No existing ancestor for runtime root: {}",
                target.display()
            )
        })?;
        (ancestor, true)
    };
    reveal_in_file_manager(&resolved)?;
    Ok(OpenedRuntimePath {
        opened: resolved.to_string_lossy().to_string(),
        fell_back,
    })
}

// ── 模块定义（供 build_modules_pythonpath 使用） ──

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_entrypoint_imports_one_canonical_main_module() {
        let args = canonical_backend_args();
        assert_eq!(args[0], "-u");
        assert_eq!(args[1], "-c");
        assert!(args[2].contains("from openkitsune.main import app"));
        assert!(!args[2].contains("runpy"));
        assert_eq!(args[3], "serve");
    }

    #[test]
    fn bootstrap_wheelhouse_uses_dependency_directory() {
        assert_eq!(
            bootstrap_wheelhouse_dir()
                .file_name()
                .and_then(|name| name.to_str()),
            Some("wheelhouse")
        );
    }

    #[test]
    fn managed_python_seed_path_uses_the_bundled_bootstrap_layout() {
        let temp = std::env::temp_dir().join(format!(
            "openkitsune-python-seed-test-{}-{}",
            std::process::id(),
            now_ms()
        ));
        let expected = if cfg!(windows) {
            temp.join("python").join("python.exe")
        } else {
            temp.join("python").join("bin").join("python3")
        };
        fs::create_dir_all(expected.parent().unwrap()).unwrap();
        fs::write(&expected, []).unwrap();

        assert_eq!(managed_python_seed_path_from(&temp), Some(expected));

        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn test_get_backend_executable_falls_back_to_venv_with_canonical_entrypoint() {
        let fake_venv = if cfg!(windows) {
            r"C:\nonexistent-test-venv-12345"
        } else {
            "/tmp/nonexistent-test-venv-12345"
        };
        let (exe, args) = get_backend_executable(fake_venv);
        // When bundled binary is missing, should return venv python path
        let exe_str = exe.to_string_lossy();
        assert!(
            exe_str.contains("python"),
            "fallback exe should contain 'python': {}",
            exe_str
        );
        assert_eq!(args, runtime_venv_backend_args(Path::new(fake_venv)));
        assert!(args[2].contains("from openkitsune.main import app"));
        assert_eq!(args[3], "serve");
    }

    #[test]
    fn test_runtime_proxy_endpoint_parses_http_and_socks_defaults() {
        assert_eq!(
            runtime_proxy_endpoint("http://127.0.0.1:9001"),
            Some(("127.0.0.1".to_string(), 9001))
        );
        assert_eq!(
            runtime_proxy_endpoint("https://proxy.example.test"),
            Some(("proxy.example.test".to_string(), 443))
        );
        assert_eq!(
            runtime_proxy_endpoint("socks5://localhost"),
            Some(("localhost".to_string(), 1080))
        );
    }

    #[test]
    fn test_runtime_proxy_endpoint_rejects_malformed_values() {
        assert_eq!(runtime_proxy_endpoint("127.0.0.1:9001"), None);
        assert_eq!(runtime_proxy_endpoint("http://"), None);
    }

    #[test]
    fn test_runtime_command_timeout_terminates_the_child() {
        let command = if cfg!(windows) {
            let mut command = Command::new("ping");
            command.args(["-n", "30", "127.0.0.1"]);
            command
        } else {
            let mut command = Command::new("sleep");
            command.arg("30");
            command
        };
        let log_path = std::env::temp_dir().join(format!(
            "openkitsune-runtime-timeout-test-{}-{}.log",
            std::process::id(),
            now_ms()
        ));
        let started = Instant::now();

        let result = run_and_log(command, &log_path, started + Duration::from_millis(200));

        assert!(
            result
                .as_ref()
                .is_err_and(|error| error.starts_with("RUNTIME_INSTALL_TIMEOUT|")),
            "unexpected timeout result: {:?}",
            result
        );
        assert!(started.elapsed() < Duration::from_secs(3));
        let _ = fs::remove_file(log_path);
    }
}
