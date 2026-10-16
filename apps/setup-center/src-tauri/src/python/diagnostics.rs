use crate::prelude::*;

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PythonCandidate {
    command: Vec<String>,
    version_text: String,
    is_usable: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct BundledPythonInstallResult {
    pub(crate) python_command: Vec<String>,
    pub(crate) python_path: String,
    pub(crate) install_dir: String,
    pub(crate) asset_name: String,
    pub(crate) tag: String,
}

pub(crate) fn run_capture(cmd: &[String]) -> Result<String, String> {
    if cmd.is_empty() {
        return Err("empty command".into());
    }
    let mut c = Command::new(&cmd[0]);
    if cmd.len() > 1 {
        c.args(&cmd[1..]);
    }
    apply_no_window(&mut c);
    let out = c
        .output()
        .map_err(|e| format!("failed to run {:?}: {e}", cmd))?;
    let mut s = String::new();
    if !out.stdout.is_empty() {
        s.push_str(&String::from_utf8_lossy(&out.stdout));
    }
    if !out.stderr.is_empty() {
        s.push_str(&String::from_utf8_lossy(&out.stderr));
    }
    Ok(s.trim().to_string())
}

pub(crate) fn python_version_ok(version_text: &str) -> bool {
    // very small parser: "Python 3.11.9"
    let lower = version_text.to_lowercase();
    let Some(idx) = lower.find("python") else {
        return false;
    };
    let ver = version_text[idx..].split_whitespace().nth(1).unwrap_or("");
    let parts: Vec<_> = ver.split('.').collect();
    if parts.len() < 2 {
        return false;
    }
    let major: i32 = parts[0].parse().unwrap_or(0);
    let minor: i32 = parts[1].parse().unwrap_or(0);
    major == 3 && minor >= 11
}

#[tauri::command]
pub(crate) fn detect_python() -> Vec<PythonCandidate> {
    let mut out = vec![];

    let root = openkitsune_root_dir();
    let venv_py = if cfg!(windows) {
        root.join("venv").join("Scripts").join("python.exe")
    } else {
        root.join("venv").join("bin").join("python")
    };
    if venv_py.exists() {
        let c = vec![venv_py.to_string_lossy().to_string()];
        let mut cmd = c.clone();
        cmd.push("--version".into());
        let version_text = run_capture(&cmd).unwrap_or_else(|e| e);
        let is_usable = python_version_ok(&version_text);
        out.push(PythonCandidate {
            command: c,
            version_text,
            is_usable,
        });
    }

    if let Some(seed_py) = managed_python_seed_path() {
        let c = vec![seed_py.to_string_lossy().to_string()];
        let mut cmd = c.clone();
        cmd.push("--version".into());
        let version_text = run_capture(&cmd).unwrap_or_else(|e| e);
        let is_usable = python_version_ok(&version_text);
        out.push(PythonCandidate {
            command: c,
            version_text,
            is_usable,
        });
    }

    if out.is_empty() {
        out.push(PythonCandidate {
            command: vec![],
            version_text: "未检测到可用的项目内置 Python".to_string(),
            is_usable: false,
        });
    }
    out
}

/// Diagnostic report for the Python environment.
#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PythonDiagnostic {
    /// healthy | broken
    summary: String,
    contracts: Vec<PythonContractResult>,
    environment: PythonEnvironmentSnapshot,
    trace_id: String,
    generated_at: String,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PythonContractResult {
    id: String,
    title: String,
    status: String, // pass | warn | fail
    code: String,
    evidence: Vec<String>,
    auto_fix: bool,
    fix_hint: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PythonEnvironmentSnapshot {
    platform: String,
    bundled_python_path: Option<String>,
    openkitsune_version: Option<String>,
}

pub(crate) fn python_diag_trace_id() -> String {
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    format!("pydiag-{now_ms}")
}

pub(crate) fn python_diag_generated_at() -> String {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

/// Run a full diagnostic.
///
/// Strategy:
///   0. Check heartbeat to distinguish "not started" / "starting" / "running".
///   1. If the backend is running → call GET /api/diagnostics (the backend
///      self-reports, no fragile _internal/python3 invocation needed).
///   2. If the backend is NOT running → check the managed Python seed and
///      application virtual environment.
#[tauri::command]
pub(crate) fn diagnose_python_env(venv_dir: String) -> PythonDiagnostic {
    let _ = venv_dir;
    let trace_id = python_diag_trace_id();

    let state = read_state_file();
    let ws_id = state.current_workspace_id.clone();

    // Determine the API port of the current workspace's backend.
    let port = ws_id
        .as_deref()
        .and_then(read_workspace_api_port)
        .unwrap_or(18900);

    // --- Strategy 0: check heartbeat to understand backend lifecycle ---
    let heartbeat = ws_id.as_deref().and_then(read_heartbeat_file);
    let backend_phase = heartbeat.as_ref().map(|hb| hb.phase.as_str()).unwrap_or("");
    let http_ready = heartbeat.as_ref().map(|hb| hb.http_ready).unwrap_or(false);
    let hb_fresh = heartbeat
        .as_ref()
        .map(|hb| {
            let age = now_epoch_secs() as f64 - hb.timestamp;
            age <= 30.0
        })
        .unwrap_or(false);

    // Backend process is alive with fresh heartbeat but HTTP not yet ready
    // → it's still initializing; skip the API call (would just time out).
    if hb_fresh && !http_ready && matches!(backend_phase, "starting" | "initializing") {
        return make_backend_starting_diagnostic(trace_id, port, backend_phase);
    }

    // --- Strategy 1: ask the running backend ---
    if let Some(diag) = diagnose_via_backend_api(port) {
        return PythonDiagnostic {
            summary: diag.summary,
            contracts: diag.contracts,
            environment: diag.environment,
            trace_id,
            generated_at: python_diag_generated_at(),
        };
    }

    // API call failed — but if heartbeat says backend is alive, give a
    // more specific message than a generic "unreachable".
    if hb_fresh && http_ready {
        return make_backend_api_unreachable_diagnostic(trace_id, port);
    }

    // --- Strategy 2: backend not reachable — managed seed check ---
    let seed = managed_python_seed_path();
    make_backend_offline_diagnostic(trace_id, port, seed.as_deref(), &bootstrap_resource_dir())
}

pub(crate) fn make_backend_offline_diagnostic(
    trace_id: String,
    port: u16,
    managed_seed: Option<&Path>,
    bootstrap_dir: &Path,
) -> PythonDiagnostic {
    let mut contracts: Vec<PythonContractResult> = vec![];

    if let Some(seed) = managed_seed {
        contracts.push(PythonContractResult {
            id: "C1_MANAGED_RUNTIME".into(),
            title: "内置运行时".into(),
            status: "pass".into(),
            code: "RUNTIME_OK".into(),
            evidence: vec![format!("python seed: {}", seed.display())],
            auto_fix: false,
            fix_hint: None,
        });
    } else {
        contracts.push(PythonContractResult {
            id: "C1_MANAGED_RUNTIME".into(),
            title: "内置运行时".into(),
            status: "fail".into(),
            code: "RUNTIME_MISSING".into(),
            evidence: vec![format!(
                "missing: {}",
                bootstrap_dir.join("python").display()
            )],
            auto_fix: false,
            fix_hint: Some("请重装 OpenKitsune 以恢复内置运行时".into()),
        });
    }

    contracts.push(PythonContractResult {
        id: "C0_BACKEND_OFFLINE".into(),
        title: "后端服务".into(),
        status: "warn".into(),
        code: "BACKEND_NOT_RUNNING".into(),
        evidence: vec![format!("port {} unreachable", port)],
        auto_fix: false,
        fix_hint: Some("启动后端服务后可获得完整诊断信息".into()),
    });

    let failing: Vec<&PythonContractResult> =
        contracts.iter().filter(|c| c.status == "fail").collect();
    let summary = if failing.is_empty() {
        "healthy"
    } else {
        "broken"
    }
    .to_string();

    PythonDiagnostic {
        summary,
        contracts,
        environment: PythonEnvironmentSnapshot {
            platform: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            bundled_python_path: managed_seed.map(|seed| seed.to_string_lossy().to_string()),
            openkitsune_version: None,
        },
        trace_id,
        generated_at: python_diag_generated_at(),
    }
}

/// Diagnostic result when backend is still initializing (heartbeat alive, HTTP not ready).
pub(crate) fn make_backend_starting_diagnostic(
    trace_id: String,
    port: u16,
    phase: &str,
) -> PythonDiagnostic {
    PythonDiagnostic {
        summary: "healthy".into(),
        contracts: vec![PythonContractResult {
            id: "C0_BACKEND_STARTING".into(),
            title: "后端服务".into(),
            status: "warn".into(),
            code: "BACKEND_STARTING".into(),
            evidence: vec![format!("phase: {}, port {}", phase, port)],
            auto_fix: false,
            fix_hint: Some("后端正在启动，请稍后再试".into()),
        }],
        environment: PythonEnvironmentSnapshot {
            platform: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            bundled_python_path: None,
            openkitsune_version: None,
        },
        trace_id,
        generated_at: python_diag_generated_at(),
    }
}

/// Diagnostic result when heartbeat says http_ready=true but API call still fails.
pub(crate) fn make_backend_api_unreachable_diagnostic(
    trace_id: String,
    port: u16,
) -> PythonDiagnostic {
    PythonDiagnostic {
        summary: "healthy".into(),
        contracts: vec![PythonContractResult {
            id: "C0_BACKEND_OFFLINE".into(),
            title: "后端服务".into(),
            status: "warn".into(),
            code: "BACKEND_API_UNREACHABLE".into(),
            evidence: vec![format!(
                "heartbeat ok, port {} API unreachable — retrying may help",
                port
            )],
            auto_fix: false,
            fix_hint: Some("后端进程正在运行但 API 暂时不可达，请稍后重试".into()),
        }],
        environment: PythonEnvironmentSnapshot {
            platform: format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
            bundled_python_path: None,
            openkitsune_version: None,
        },
        trace_id,
        generated_at: python_diag_generated_at(),
    }
}

/// Call GET /api/diagnostics on the running backend and map the response
/// to our diagnostic structures.
///
/// Uses a quick TCP probe first; if nothing is listening, returns None
/// immediately without wasting time on HTTP. On transient failures
/// (timeout, reset) retries once after a short delay.
pub(crate) fn diagnose_via_backend_api(port: u16) -> Option<PythonDiagnostic> {
    // Quick TCP probe: if nothing is listening, bail out immediately.
    {
        use std::net::TcpStream;
        let addr = format!("127.0.0.1:{}", port);
        if TcpStream::connect_timeout(&addr.parse().ok()?, std::time::Duration::from_secs(2))
            .is_err()
        {
            return None;
        }
    }

    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(6))
        .no_proxy()
        .build()
        .ok()?;

    let url = format!("http://127.0.0.1:{}/api/diagnostics", port);
    let max_attempts: u8 = 2;
    let mut last_err = String::new();

    for attempt in 0..max_attempts {
        if attempt > 0 {
            std::thread::sleep(std::time::Duration::from_millis(1500));
        }
        match client.get(&url).send() {
            Ok(resp) if resp.status().is_success() => match resp.json::<serde_json::Value>() {
                Ok(json) => return parse_diagnostics_json(&json),
                Err(e) => {
                    last_err = format!("json parse: {e}");
                    continue;
                }
            },
            Ok(resp) => {
                last_err = format!("HTTP {}", resp.status());
                continue;
            }
            Err(e) => {
                let msg = format!("{e}");
                // Connection refused → nothing is listening, don't retry.
                if msg.contains("onnection refused") || msg.contains("No connection") {
                    eprintln!("[diagnose] connection refused on port {port}");
                    return None;
                }
                last_err = msg;
                continue;
            }
        }
    }

    eprintln!("[diagnose] backend API unreachable after {max_attempts} attempts (port={port}): {last_err}");
    None
}

pub(crate) fn parse_diagnostics_json(json: &serde_json::Value) -> Option<PythonDiagnostic> {
    let summary = json
        .get("summary")
        .and_then(|v| v.as_str())
        .unwrap_or("healthy")
        .to_string();

    let mut contracts: Vec<PythonContractResult> = vec![];
    if let Some(checks) = json.get("checks").and_then(|v| v.as_array()) {
        for c in checks {
            contracts.push(PythonContractResult {
                id: c.get("id").and_then(|v| v.as_str()).unwrap_or("").into(),
                title: c.get("title").and_then(|v| v.as_str()).unwrap_or("").into(),
                status: c
                    .get("status")
                    .and_then(|v| v.as_str())
                    .unwrap_or("pass")
                    .into(),
                code: c.get("code").and_then(|v| v.as_str()).unwrap_or("").into(),
                evidence: c
                    .get("evidence")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|x| x.as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default(),
                auto_fix: c.get("autoFix").and_then(|v| v.as_bool()).unwrap_or(false),
                fix_hint: c.get("fixHint").and_then(|v| v.as_str()).map(String::from),
            });
        }
    }

    let env_obj = json.get("environment");
    let environment = PythonEnvironmentSnapshot {
        platform: env_obj
            .and_then(|e| e.get("platform"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        bundled_python_path: None,
        openkitsune_version: env_obj
            .and_then(|e| e.get("openkitsuneVersion"))
            .and_then(|v| v.as_str())
            .map(String::from),
    };

    Some(PythonDiagnostic {
        summary,
        contracts,
        environment,
        trace_id: String::new(),
        generated_at: String::new(),
    })
}

#[tauri::command]
pub(crate) fn export_python_diagnostic_report(venv_dir: String) -> Result<String, String> {
    let diag = diagnose_python_env(venv_dir);
    let report_dir = openkitsune_root_dir().join("runtime").join("reports");
    fs::create_dir_all(&report_dir).map_err(|e| format!("创建报告目录失败: {e}"))?;
    let report_path = report_dir.join(format!("python-diagnostic-{}.json", diag.trace_id));
    let text = serde_json::to_string_pretty(&diag).map_err(|e| format!("序列化报告失败: {e}"))?;
    fs::write(&report_path, text).map_err(|e| format!("写入报告失败: {e}"))?;
    Ok(report_path.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn offline_diagnostic_serializes_the_managed_runtime_contract() {
        let bootstrap = Path::new("bootstrap");
        let seed = bootstrap.join("python").join(if cfg!(windows) {
            "python.exe"
        } else {
            "bin/python3"
        });

        let diagnostic =
            make_backend_offline_diagnostic("trace-test".into(), 18900, Some(&seed), bootstrap);
        let value = serde_json::to_value(diagnostic).unwrap();

        assert_eq!(value["summary"], "healthy");
        assert_eq!(value["traceId"], "trace-test");
        assert!(value["generatedAt"].is_string());
        assert_eq!(
            value["environment"]["bundledPythonPath"],
            seed.to_string_lossy().as_ref()
        );
        assert_eq!(value["contracts"][0]["id"], "C1_MANAGED_RUNTIME");
        assert_eq!(value["contracts"][0]["code"], "RUNTIME_OK");
        assert_eq!(value["contracts"][1]["id"], "C0_BACKEND_OFFLINE");
        assert!(value.get("systemPythonOk").is_none());
        assert!(value.get("systemPythonPath").is_none());
    }

    #[test]
    fn offline_diagnostic_marks_a_missing_managed_runtime_as_broken() {
        let diagnostic = make_backend_offline_diagnostic(
            "trace-missing".into(),
            18900,
            None,
            Path::new("bootstrap"),
        );
        let value = serde_json::to_value(diagnostic).unwrap();

        assert_eq!(value["summary"], "broken");
        assert_eq!(value["contracts"][0]["status"], "fail");
        assert_eq!(value["contracts"][0]["code"], "RUNTIME_MISSING");
    }
}
