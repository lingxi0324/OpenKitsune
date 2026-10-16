use crate::prelude::*;

pub(crate) const PIP_INSTALL_LOG_MAX_CHUNKS: usize = 512;
pub(crate) const PIP_INSTALL_DEFAULT_ID: &str = "default";
pub(crate) const PIP_INSTALL_KEEPALIVE_SECS: u64 = 30;
pub(crate) const PIP_INSTALL_TOTAL_TIMEOUT_SECS: u64 = 2 * 60 * 60;
pub(crate) const PIP_INSTALL_READER_DRAIN_GRACE_MS: u64 = 2_000;
pub(crate) const PIP_NETWORK_OPTIONS: &[&str] = &[
    "--disable-pip-version-check",
    "--prefer-binary",
    "--timeout",
    "120",
    "--retries",
    "8",
    "--progress-bar",
    "off",
];
pub(crate) const PIP_INSTALL_RUNNING_STALE_MS: u64 = 20 * 60 * 1_000;

#[derive(Default)]
pub(crate) struct PipInstallProgressState {
    cursor: u64,
    done: bool,
    failed: bool,
    updated_at_ms: u64,
    stage: Option<String>,
    percent: Option<u8>,
    chunks: VecDeque<(u64, String)>,
}

impl PipInstallProgressState {
    fn touch(&mut self) {
        self.updated_at_ms = now_ms();
    }

    fn push_chunk(&mut self, text: String) {
        if text.is_empty() {
            return;
        }
        self.cursor = self.cursor.saturating_add(1);
        self.chunks.push_back((self.cursor, text));
        while self.chunks.len() > PIP_INSTALL_LOG_MAX_CHUNKS {
            self.chunks.pop_front();
        }
        self.touch();
    }
}

pub(crate) static PIP_INSTALL_PROGRESS: Lazy<Mutex<HashMap<String, PipInstallProgressState>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PipInstallProgressSnapshot {
    cursor: u64,
    done: bool,
    failed: bool,
    stage: Option<String>,
    percent: Option<u8>,
    chunks: Vec<String>,
    missed: bool,
}

pub(crate) fn pip_install_log_path() -> PathBuf {
    runtime_logs_dir().join("pip-install.log")
}

pub(crate) fn append_pip_install_log(text: &str) {
    if text.is_empty() {
        return;
    }
    let path = pip_install_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .and_then(|mut file| file.write_all(text.as_bytes()));
}

pub(crate) fn pip_install_reset_progress(install_id: &str, label: &str, truncate_log: bool) {
    let mut all = PIP_INSTALL_PROGRESS.lock().unwrap();
    let mut state = PipInstallProgressState::default();
    state.touch();
    all.insert(install_id.to_string(), state);
    drop(all);

    let header = format!(
        "\n=== {label} started at {} pid={} ===\n",
        now_epoch_secs(),
        std::process::id()
    );
    let path = pip_install_log_path();
    if truncate_log {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let _ = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(path)
            .and_then(|mut file| file.write_all(header.as_bytes()));
    } else {
        append_pip_install_log(&header);
    }
}

pub(crate) fn pip_install_set_stage(install_id: &str, stage: &str, percent: u8) {
    let mut all = PIP_INSTALL_PROGRESS.lock().unwrap();
    let state = all.entry(install_id.to_string()).or_default();
    state.stage = Some(stage.to_string());
    state.percent = Some(percent.min(100));
    state.touch();
    drop(all);
    append_pip_install_log(&format!("\n[stage] {stage} ({percent}%)\n"));
}

pub(crate) fn pip_install_append_line(install_id: &str, text: &str) {
    if text.is_empty() {
        return;
    }
    let mut all = PIP_INSTALL_PROGRESS.lock().unwrap();
    all.entry(install_id.to_string())
        .or_default()
        .push_chunk(text.to_string());
    drop(all);
    append_pip_install_log(text);
}

pub(crate) fn pip_install_finish_progress(install_id: &str, failed: bool) {
    let mut all = PIP_INSTALL_PROGRESS.lock().unwrap();
    let state = all.entry(install_id.to_string()).or_default();
    state.done = true;
    state.failed = failed;
    state.touch();
    drop(all);
    append_pip_install_log(&format!(
        "\n=== install progress {} at {} ===\n",
        if failed { "failed" } else { "finished" },
        now_epoch_secs()
    ));
}

pub(crate) fn pip_install_is_running() -> bool {
    let Ok(mut all) = PIP_INSTALL_PROGRESS.lock() else {
        return false;
    };
    let now = now_ms();
    all.values_mut().any(|state| {
        if state.done {
            return false;
        }
        if state.updated_at_ms > 0
            && now.saturating_sub(state.updated_at_ms) > PIP_INSTALL_RUNNING_STALE_MS
        {
            state.failed = true;
            state.done = true;
            state.push_chunk(
                "\n[install] progress state expired after 20 minutes without updates\n".to_string(),
            );
            return false;
        }
        true
    })
}

#[tauri::command]
pub(crate) fn pip_install_progress(
    install_id: Option<String>,
    cursor: Option<u64>,
) -> PipInstallProgressSnapshot {
    let install_id = install_id.unwrap_or_else(|| PIP_INSTALL_DEFAULT_ID.to_string());
    let since = cursor.unwrap_or(0);
    let all = PIP_INSTALL_PROGRESS.lock().unwrap();
    let Some(state) = all.get(&install_id) else {
        return PipInstallProgressSnapshot {
            cursor: 0,
            done: false,
            failed: false,
            stage: None,
            percent: None,
            chunks: Vec::new(),
            missed: false,
        };
    };
    let effective_since = if since > state.cursor { 0 } else { since };
    let first_available = state
        .chunks
        .front()
        .map(|(chunk_cursor, _)| *chunk_cursor)
        .unwrap_or(state.cursor);
    let missed = since > state.cursor
        || (effective_since > 0 && first_available > effective_since.saturating_add(1));
    let chunks = state
        .chunks
        .iter()
        .filter(|(chunk_cursor, _)| *chunk_cursor > effective_since)
        .map(|(_, text)| text.clone())
        .collect();
    PipInstallProgressSnapshot {
        cursor: state.cursor,
        done: state.done,
        failed: state.failed,
        stage: state.stage.clone(),
        percent: state.percent,
        chunks,
        missed,
    }
}

/// 校验并返回安装包内置 Python（不再运行时下载 Python）。
pub(crate) fn install_bundled_python_sync(
    _python_series: Option<String>,
    _log_path: Option<PathBuf>,
) -> Result<BundledPythonInstallResult, String> {
    let py = managed_python_seed_path().ok_or_else(|| {
        "安装包内置 Python 不可用。请重新安装 OpenKitsune 以恢复 resources/bootstrap/python"
            .to_string()
    })?;
    Ok(bundled_python_install_result(
        &py,
        &bootstrap_resource_dir(),
    ))
}

pub(crate) fn bundled_python_install_result(
    python_path: &Path,
    install_dir: &Path,
) -> BundledPythonInstallResult {
    BundledPythonInstallResult {
        python_command: vec![python_path.to_string_lossy().to_string()],
        python_path: python_path.to_string_lossy().to_string(),
        install_dir: install_dir.to_string_lossy().to_string(),
        asset_name: "managed-python-seed".to_string(),
        tag: "bootstrap".to_string(),
    }
}

pub(crate) fn effective_pip_install_index(index_url: Option<&str>) -> &str {
    index_url.unwrap_or(DEFAULT_PIP_INDEX_URL)
}

#[tauri::command]
pub(crate) async fn install_bundled_python(
    python_series: Option<String>,
    log_path: Option<String>,
) -> Result<BundledPythonInstallResult, String> {
    let path_buf = log_path.map(PathBuf::from);
    spawn_blocking_result(move || install_bundled_python_sync(python_series, path_buf)).await
}

#[tauri::command]
pub(crate) async fn create_venv(
    python_command: Vec<String>,
    venv_dir: String,
    install_id: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let install_id = install_id.unwrap_or_else(|| PIP_INSTALL_DEFAULT_ID.to_string());
        let install_id_ref = install_id.as_str();
        pip_install_reset_progress(install_id_ref, "create venv", true);
        let result: Result<String, String> = (|| {
            let venv = PathBuf::from(venv_dir);
            let mut log = String::new();
            let emit_line = |text: &str| {
                pip_install_append_line(install_id_ref, text);
            };

            if !venv.exists() {
                pip_install_set_stage(install_id_ref, "创建 venv", 10);
                let mut c = if let Some(seed_py) = managed_python_seed_path() {
                    Command::new(seed_py)
                } else {
                    command_from_python_command(&python_command)?
                };
                apply_no_window(&mut c);
                c.args(["-m", "venv", "--clear"]).arg(&venv);
                let status = run_streaming_command(
                    c,
                    "create venv",
                    Some(&mut log),
                    Some(&emit_line),
                    std::time::Duration::from_secs(PIP_INSTALL_TOTAL_TIMEOUT_SECS),
                )?;
                if !status.success() {
                    return Err(format!("venv creation failed: {status}\n\n{log}"));
                }
            } else {
                pip_install_set_stage(install_id_ref, "复用已有 venv", 10);
                emit_line(&format!("venv already exists: {}\n", venv.display()));
            }

            pip_install_set_stage(install_id_ref, "准备 pip", 20);
            let py = venv_python_path(venv.to_string_lossy().as_ref());
            ensure_pip_available(&py, None, Some(&mut log), Some(&emit_line))?;
            Ok(venv.to_string_lossy().to_string())
        })();
        if result.is_err() {
            pip_install_finish_progress(install_id_ref, true);
        }
        result
    })
    .await
}

pub(crate) fn command_from_python_command(python_command: &[String]) -> Result<Command, String> {
    let Some(program) = python_command.first() else {
        return Err("未检测到 Python 3.11+，无法创建 venv".to_string());
    };
    let mut cmd = Command::new(program);
    if python_command.len() > 1 {
        cmd.args(&python_command[1..]);
    }
    strip_harmful_python_env(&mut cmd);
    Ok(cmd)
}

pub(crate) fn venv_python_path(venv_dir: &str) -> PathBuf {
    let v = PathBuf::from(venv_dir);
    if cfg!(windows) {
        v.join("Scripts").join("python.exe")
    } else {
        v.join("bin").join("python")
    }
}

/// 解析可用的 Python 解释器路径。
/// 只使用 OpenKitsune 管理的环境：venv → bootstrap Python seed。
pub(crate) fn resolve_python(venv_dir: &str) -> Result<(PathBuf, Option<String>), String> {
    let venv_py = venv_python_path(venv_dir);
    if venv_py.exists() {
        return Ok((venv_py, None));
    }
    let py = find_pip_python().ok_or_else(|| {
        "未找到可用 Python 解释器（venv/bootstrap）。请重新安装 OpenKitsune 以恢复内置 Python。"
            .to_string()
    })?;
    Ok((py, None))
}

pub(crate) fn venv_pythonw_path(venv_dir: &str) -> PathBuf {
    let v = PathBuf::from(venv_dir);
    if cfg!(windows) {
        let p = v.join("Scripts").join("pythonw.exe");
        if p.exists() {
            return p;
        }
        v.join("Scripts").join("python.exe")
    } else {
        v.join("bin").join("python")
    }
}

pub(crate) fn append_stream_output(
    log: &mut Option<&mut String>,
    emit_line: Option<&dyn Fn(&str)>,
    text: &str,
) {
    if text.is_empty() {
        return;
    }
    if let Some(emit_line) = emit_line {
        emit_line(text);
    }
    if let Some(log) = log.as_mut() {
        (**log).push_str(text);
    }
}

pub(crate) fn join_reader_thread(handle: std::thread::JoinHandle<()>) {
    let started = Instant::now();
    loop {
        if handle.is_finished() {
            let _ = handle.join();
            return;
        }
        if started.elapsed() >= std::time::Duration::from_millis(PIP_INSTALL_READER_DRAIN_GRACE_MS)
        {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
}

pub(crate) fn run_streaming_command(
    mut cmd: Command,
    header: &str,
    mut log: Option<&mut String>,
    emit_line: Option<&dyn Fn(&str)>,
    total_timeout: std::time::Duration,
) -> Result<std::process::ExitStatus, String> {
    use std::io::Read as _;
    use std::process::Stdio;
    use std::sync::mpsc;
    use std::thread;

    append_stream_output(&mut log, emit_line, &format!("\n=== {header} ===\n"));

    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("{header} failed to start: {e}"))?;
    let child_pid = child.id();
    append_stream_output(
        &mut log,
        emit_line,
        &format!("[{header}] spawned pid={child_pid}\n"),
    );

    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| format!("{header} stdout pipe missing"))?;
    let mut stderr = child
        .stderr
        .take()
        .ok_or_else(|| format!("{header} stderr pipe missing"))?;

    let (tx, rx) = mpsc::channel::<String>();
    let tx1 = tx.clone();
    let h1 = thread::spawn(move || {
        let mut buf = [0u8; 4096];
        let mut pending: Vec<u8> = Vec::new();
        loop {
            match stdout.read(&mut buf) {
                Ok(0) => {
                    if !pending.is_empty() {
                        let _ = tx1.send(String::from_utf8_lossy(&pending).to_string());
                    }
                    break;
                }
                Ok(n) => {
                    pending.extend_from_slice(&buf[..n]);
                    let s = take_valid_utf8_prefix(&mut pending);
                    if !s.is_empty() {
                        let _ = tx1.send(s);
                    }
                }
                Err(_) => break,
            }
        }
    });
    let tx2 = tx.clone();
    let h2 = thread::spawn(move || {
        let mut buf = [0u8; 4096];
        let mut pending: Vec<u8> = Vec::new();
        loop {
            match stderr.read(&mut buf) {
                Ok(0) => {
                    if !pending.is_empty() {
                        let _ = tx2.send(String::from_utf8_lossy(&pending).to_string());
                    }
                    break;
                }
                Ok(n) => {
                    pending.extend_from_slice(&buf[..n]);
                    let s = take_valid_utf8_prefix(&mut pending);
                    if !s.is_empty() {
                        let _ = tx2.send(s);
                    }
                }
                Err(_) => break,
            }
        }
    });
    drop(tx);

    let started_at = Instant::now();
    let mut last_progress_at = Instant::now();
    let keepalive_interval = std::time::Duration::from_secs(PIP_INSTALL_KEEPALIVE_SECS);
    let mut timed_out = false;
    loop {
        match rx.recv_timeout(std::time::Duration::from_millis(120)) {
            Ok(chunk) => {
                last_progress_at = Instant::now();
                append_stream_output(&mut log, emit_line, &chunk);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {}
        }

        if let Ok(Some(_)) = child.try_wait() {
            break;
        }

        if last_progress_at.elapsed() >= keepalive_interval {
            append_stream_output(
                &mut log,
                emit_line,
                &format!(
                    "[{header}] still running for {}s; waiting for subprocess output\n",
                    started_at.elapsed().as_secs()
                ),
            );
            last_progress_at = Instant::now();
        }

        if started_at.elapsed() >= total_timeout {
            timed_out = true;
            append_stream_output(
                &mut log,
                emit_line,
                &format!(
                    "\n[{header}] exceeded total timeout of {}s; killing pid {child_pid}\n",
                    total_timeout.as_secs()
                ),
            );
            let _ = child.kill();
            break;
        }
    }

    let status = child
        .wait()
        .map_err(|e| format!("{header} wait failed: {e}"))?;
    join_reader_thread(h1);
    join_reader_thread(h2);

    while let Ok(chunk) = rx.try_recv() {
        append_stream_output(&mut log, emit_line, &chunk);
    }
    append_stream_output(
        &mut log,
        emit_line,
        &format!("\n[{header}] exited with {status}\n\n"),
    );

    if timed_out {
        Err(format!(
            "{header} exceeded total timeout of {}s; killed pid {child_pid}",
            total_timeout.as_secs()
        ))
    } else {
        Ok(status)
    }
}

pub(crate) fn ensure_pip_available(
    py: &Path,
    pythonpath: Option<&str>,
    mut log: Option<&mut String>,
    emit_line: Option<&dyn Fn(&str)>,
) -> Result<(), String> {
    if !py.exists() {
        return Err(format!("python executable not found: {}", py.display()));
    }

    let mut check = Command::new(py);
    apply_no_window(&mut check);
    strip_harmful_python_env(&mut check);
    check.env("PYTHONUTF8", "1");
    check.env("PYTHONIOENCODING", "utf-8");
    if let Some(pp) = pythonpath {
        check.env("PYTHONPATH", pp);
    }
    check.args(["-m", "pip", "--version"]);
    if check
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
    {
        return Ok(());
    }

    let mut ensure = Command::new(py);
    apply_no_window(&mut ensure);
    strip_harmful_python_env(&mut ensure);
    ensure.env("PYTHONUTF8", "1");
    ensure.env("PYTHONIOENCODING", "utf-8");
    if let Some(pp) = pythonpath {
        ensure.env("PYTHONPATH", pp);
    }
    ensure.args(["-m", "ensurepip", "--upgrade"]);
    let status = run_streaming_command(
        ensure,
        "seed pip (ensurepip)",
        log.as_mut().map(|s| &mut **s),
        emit_line,
        std::time::Duration::from_secs(PIP_INSTALL_TOTAL_TIMEOUT_SECS),
    )?;
    if !status.success() {
        return Err(format!("ensurepip failed for {}", py.display()));
    }

    Ok(())
}

#[tauri::command]
pub(crate) async fn pip_install(
    venv_dir: String,
    package_spec: String,
    index_url: Option<String>,
    install_id: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let install_id = install_id.unwrap_or_else(|| PIP_INSTALL_DEFAULT_ID.to_string());
        let install_id_ref = install_id.as_str();
        pip_install_set_stage(install_id_ref, "安装 openkitsune（pip）", 30);
        pip_install_append_line(
            install_id_ref,
            &format!("\n=== pip install started at {} ===\n", now_epoch_secs()),
        );
        let result: Result<String, String> = (|| {
        let (py, pythonpath) = resolve_python(&venv_dir)?;

        let mut log = String::new();

        let emit_stage = |stage: &str, percent: u8| {
            pip_install_set_stage(install_id_ref, stage, percent);
        };
        let emit_line = |text: &str| {
            pip_install_append_line(install_id_ref, text);
        };

        emit_stage("准备 pip", 20);
        ensure_pip_available(
            &py,
            pythonpath.as_deref(),
            Some(&mut log),
            Some(&emit_line),
        )?;

        // 国内镜像兜底：前端未传 index_url 时默认使用阿里云
        let effective_index = effective_pip_install_index(index_url.as_deref());
        let effective_host = effective_index
            .split("//").nth(1).unwrap_or("")
            .split('/').next().unwrap_or("");

        // upgrade pip first (best-effort)
        emit_stage("升级 pip（best-effort）", 40);
        let mut up = Command::new(&py);
        apply_no_window(&mut up);
        strip_harmful_python_env(&mut up);
        up.env("PYTHONUTF8", "1");
        up.env("PYTHONIOENCODING", "utf-8");
        if let Some(ref pp) = pythonpath {
            up.env("PYTHONPATH", pp);
        }
        up.args([
            "-m",
            "pip",
            "install",
            "-U",
            "pip",
            "setuptools",
            "wheel",
        ]);
        up.args(PIP_NETWORK_OPTIONS);
        up.args(["-i", effective_index]);
        if !effective_host.is_empty() {
            up.args(["--trusted-host", effective_host]);
        }
        let _ = run_streaming_command(
            up,
            "pip upgrade (best-effort)",
            Some(&mut log),
            Some(&emit_line),
            std::time::Duration::from_secs(PIP_INSTALL_TOTAL_TIMEOUT_SECS),
        );

        emit_stage("安装 openkitsune（pip）", 70);
        let mut c = Command::new(&py);
        apply_no_window(&mut c);
        strip_harmful_python_env(&mut c);
        c.env("PYTHONUTF8", "1");
        c.env("PYTHONIOENCODING", "utf-8");
        if let Some(ref pp) = pythonpath {
            c.env("PYTHONPATH", pp);
        }
        c.args([
            "-m",
            "pip",
            "install",
            "-U",
            &package_spec,
        ]);
        c.args(PIP_NETWORK_OPTIONS);
        c.args(["-i", effective_index]);
        if !effective_host.is_empty() {
            c.args(["--trusted-host", effective_host]);
        }
        let status = run_streaming_command(
            c,
            "pip install",
            Some(&mut log),
            Some(&emit_line),
            std::time::Duration::from_secs(PIP_INSTALL_TOTAL_TIMEOUT_SECS),
        )?;
        if !status.success() {
            let tail = if log.len() > 6000 {
                &log[log.len() - 6000..]
            } else {
                &log
            };
            pip_install_finish_progress(install_id_ref, true);
            return Err(format!("pip install failed: {status}\n\n--- output tail ---\n{tail}"));
        }

        // Post-check: ensure Setup Center bridge exists in the installed package.
        emit_stage("验证安装", 95);
        emit_line("\n=== verify ===\n");
        let mut verify = Command::new(&py);
        apply_no_window(&mut verify);
        strip_harmful_python_env(&mut verify);
        verify.env("PYTHONUTF8", "1");
        verify.env("PYTHONIOENCODING", "utf-8");
        if let Some(ref pp) = pythonpath {
            verify.env("PYTHONPATH", pp);
        }
        verify.args([
            "-c",
            "import openkitsune; import openkitsune.setup_center.bridge; print(getattr(openkitsune,'__version__',''))",
        ]);
        let v = verify.output().map_err(|e| format!("verify openkitsune failed: {e}"))?;
        if !v.status.success() {
            let stdout = String::from_utf8_lossy(&v.stdout).to_string();
            let stderr = String::from_utf8_lossy(&v.stderr).to_string();
            pip_install_finish_progress(install_id_ref, true);
            return Err(format!(
                "openkitsune 已安装，但缺少 Setup Center 所需模块（openkitsune.setup_center.bridge）。\n这通常意味着你安装的 openkitsune 版本过旧或来源不包含该模块。\nstdout:\n{}\nstderr:\n{}",
                stdout, stderr
            ));
        }

        let ver = String::from_utf8_lossy(&v.stdout).trim().to_string();
        log.push_str("=== verify ===\n");
        log.push_str("import openkitsune.setup_center.bridge: OK\n");
        emit_line("import openkitsune.setup_center.bridge: OK\n");
        if !ver.is_empty() {
            log.push_str(&format!("openkitsune version: {ver}\n"));
            emit_line(&format!("openkitsune version: {ver}\n"));
        }
        emit_stage("完成", 100);
        pip_install_finish_progress(install_id_ref, false);

        Ok(log)
        })();
        if result.is_err() {
            pip_install_finish_progress(install_id_ref, true);
        }
        result
    })
    .await
}

#[tauri::command]
pub(crate) async fn pip_uninstall(
    venv_dir: String,
    package_name: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let (py, pythonpath) = resolve_python(&venv_dir)?;
        if package_name.trim().is_empty() {
            return Err("package_name is empty".into());
        }

        let mut c = Command::new(&py);
        apply_no_window(&mut c);
        strip_harmful_python_env(&mut c);
        if let Some(ref pp) = pythonpath {
            c.env("PYTHONPATH", pp);
        }
        c.args(["-m", "pip", "uninstall", "-y", package_name.trim()]);
        let status = c
            .status()
            .map_err(|e| format!("pip uninstall failed to start: {e}"))?;
        if !status.success() {
            return Err(format!("pip uninstall failed: {status}"));
        }
        Ok("ok".into())
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_venv_python_path_platform_layout() {
        let dir = if cfg!(windows) {
            r"C:\Users\test\.openkitsune\venv"
        } else {
            "/home/test/.openkitsune/venv"
        };
        let py = venv_python_path(dir);
        if cfg!(windows) {
            assert!(py.to_string_lossy().contains("Scripts"));
            assert!(py.to_string_lossy().ends_with("python.exe"));
        } else {
            assert!(py.to_string_lossy().contains("bin"));
            assert!(py.to_string_lossy().ends_with("python"));
        }
    }

    #[test]
    fn test_venv_pythonw_path_consistent_with_python_path() {
        let dir = if cfg!(windows) {
            r"C:\Users\test\.openkitsune\venv"
        } else {
            "/home/test/.openkitsune/venv"
        };
        let py = venv_python_path(dir);
        let pyw = venv_pythonw_path(dir);
        // On Linux both should resolve to bin/python
        if cfg!(not(windows)) {
            assert_eq!(py, pyw);
        }
        // On Windows pythonw prefers pythonw.exe but falls back to python.exe
        // For non-existent dir it returns python.exe since pythonw.exe doesn't exist
        if cfg!(windows) {
            assert!(pyw.to_string_lossy().contains("python"));
        }
    }

    #[test]
    fn test_ensure_pip_available_seeds_uv_venv_without_pip() {
        let temp =
            std::env::temp_dir().join(format!("openkitsune-pip-seed-test-{}", std::process::id()));
        if temp.exists() {
            let _ = fs::remove_dir_all(&temp);
        }
        let status = Command::new("uv")
            .args(["venv", temp.to_string_lossy().as_ref(), "--python", "3.11"])
            .status();
        let Ok(status) = status else {
            eprintln!("skipping pip seed test: uv not available");
            return;
        };
        if !status.success() {
            eprintln!("skipping pip seed test: uv venv failed");
            let _ = fs::remove_dir_all(&temp);
            return;
        }

        let py = venv_python_path(temp.to_string_lossy().as_ref());
        ensure_pip_available(&py, None, None, None).expect("ensure_pip_available should seed pip");

        let status = Command::new(&py)
            .args(["-m", "pip", "--version"])
            .status()
            .expect("pip --version should run after ensure_pip_available");
        assert!(status.success());
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_pip_install_progress_returns_only_new_chunks() {
        let install_id = "test-progress-cursor";
        let mut state = PipInstallProgressState::default();
        state.push_chunk("first".to_string());
        state.push_chunk("second".to_string());
        PIP_INSTALL_PROGRESS
            .lock()
            .unwrap()
            .insert(install_id.to_string(), state);

        let snapshot = pip_install_progress(Some(install_id.to_string()), Some(1));
        assert_eq!(snapshot.cursor, 2);
        assert_eq!(snapshot.chunks, vec!["second"]);

        PIP_INSTALL_PROGRESS.lock().unwrap().remove(install_id);
    }

    #[test]
    fn test_pip_network_options_use_stable_pip_flags() {
        assert!(PIP_NETWORK_OPTIONS.contains(&"--timeout"));
        assert!(PIP_NETWORK_OPTIONS.contains(&"--retries"));
        assert!(PIP_NETWORK_OPTIONS.contains(&"--progress-bar"));
        assert!(!PIP_NETWORK_OPTIONS.contains(&"--resume-retries"));
    }

    #[test]
    fn pip_install_defaults_to_the_domestic_index() {
        assert_eq!(effective_pip_install_index(None), DEFAULT_PIP_INDEX_URL);
        assert_eq!(
            effective_pip_install_index(Some("https://pypi.org/simple/")),
            "https://pypi.org/simple/"
        );
    }

    #[test]
    fn bundled_python_install_result_reports_the_managed_seed() {
        let install_dir = Path::new("bootstrap");
        let python = install_dir.join("python").join(if cfg!(windows) {
            "python.exe"
        } else {
            "bin/python3"
        });

        let result = bundled_python_install_result(&python, install_dir);

        assert_eq!(result.python_command, vec![result.python_path.clone()]);
        assert_eq!(result.install_dir, install_dir.to_string_lossy());
        assert_eq!(result.asset_name, "managed-python-seed");
        assert_eq!(result.tag, "bootstrap");
    }

    #[test]
    fn test_pip_install_progress_reused_id_with_stale_cursor_returns_fresh_chunks() {
        let install_id = format!("test-progress-{}-{}", std::process::id(), now_epoch_secs());
        pip_install_reset_progress(&install_id, "test old progress", false);
        pip_install_append_line(&install_id, "old chunk 1\n");
        pip_install_append_line(&install_id, "old chunk 2\n");
        let old_cursor = pip_install_progress(Some(install_id.clone()), None).cursor;
        assert!(old_cursor >= 2);
        pip_install_finish_progress(&install_id, true);

        pip_install_reset_progress(&install_id, "test new progress", false);
        pip_install_append_line(&install_id, "fresh chunk\n");
        let snapshot = pip_install_progress(Some(install_id.clone()), Some(old_cursor));

        assert!(snapshot.missed);
        assert!(snapshot.chunks.join("").contains("fresh chunk"));
        assert!(!snapshot.done);

        pip_install_finish_progress(&install_id, false);
    }
}
