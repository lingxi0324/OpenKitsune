use crate::prelude::*;

pub(crate) fn run_python_module_json(
    venv_dir: &str,
    module: &str,
    args: &[&str],
    extra_env: &[(&str, &str)],
) -> Result<String, String> {
    let (py, pythonpath) = resolve_python(venv_dir)?;

    let mut c = Command::new(&py);
    apply_no_window(&mut c);
    strip_harmful_python_env(&mut c);
    c.env("PYTHONUTF8", "1");
    c.env("PYTHONIOENCODING", "utf-8");
    if let Some(ref pp) = pythonpath {
        c.env("PYTHONPATH", pp);
    }
    c.arg("-m").arg(module);
    c.args(args);
    for (k, v) in extra_env {
        c.env(k, v);
    }
    let out = c
        .output()
        .map_err(|e| format!("failed to run python: {e}"))?;
    if !out.status.success() {
        let stderr = String::from_utf8_lossy(&out.stderr).to_string();
        let stdout = String::from_utf8_lossy(&out.stdout).to_string();
        return Err(format!(
            "python failed: {}\nstdout:\n{}\nstderr:\n{}",
            out.status, stdout, stderr
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
}

#[tauri::command]
pub(crate) async fn openkitsune_list_providers(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        run_python_module_json(
            &venv_dir,
            "openkitsune.setup_center.bridge",
            &["list-providers"],
            &[],
        )
    })
    .await
}

#[tauri::command]
pub(crate) async fn openkitsune_list_skills(
    venv_dir: String,
    workspace_id: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        run_python_module_json(
            &venv_dir,
            "openkitsune.setup_center.bridge",
            &["list-skills", "--workspace-dir", &wd_str],
            &[],
        )
    })
    .await
}

#[tauri::command]
pub(crate) async fn openkitsune_list_models(
    venv_dir: String,
    api_type: String,
    base_url: String,
    provider_slug: Option<String>,
    api_key: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let mut args = vec![
            "list-models",
            "--api-type",
            api_type.as_str(),
            "--base-url",
            base_url.as_str(),
        ];
        if let Some(slug) = provider_slug.as_deref() {
            args.push("--provider-slug");
            args.push(slug);
        }

        run_python_module_json(
            &venv_dir,
            "openkitsune.setup_center.bridge",
            &args,
            &[("SETUPCENTER_API_KEY", api_key.as_str())],
        )
    })
    .await
}

#[tauri::command]
pub(crate) async fn openkitsune_version(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        // Use the managed environment to obtain the installed wheel version.
        let (py, pythonpath) = resolve_python(&venv_dir)?;
        let mut c = Command::new(&py);
        apply_no_window(&mut c);
        strip_harmful_python_env(&mut c);
        c.env("PYTHONUTF8", "1");
        c.env("PYTHONIOENCODING", "utf-8");
        if let Some(ref pp) = pythonpath {
            c.env("PYTHONPATH", pp);
        }
        c.args([
            "-c",
            "import openkitsune; print(getattr(openkitsune,'__version__',''))",
        ]);
        let out = c
            .output()
            .map_err(|e| format!("get openkitsune version failed: {e}"))?;
        if !out.status.success() {
            let stderr = String::from_utf8_lossy(&out.stderr).to_string();
            let stdout = String::from_utf8_lossy(&out.stdout).to_string();
            return Err(format!(
                "python failed: {}\nstdout:\n{}\nstderr:\n{}",
                out.status, stdout, stderr
            ));
        }
        Ok(String::from_utf8_lossy(&out.stdout).trim().to_string())
    })
    .await
}

/// Health check LLM endpoints via Python bridge.
/// Returns JSON array of health results.
#[tauri::command]
pub(crate) async fn openkitsune_health_check_endpoint(
    venv_dir: String,
    workspace_id: String,
    endpoint_name: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let mut args = vec!["health-check-endpoint", "--workspace-dir", &wd_str];
        let ep_name_str;
        if let Some(ref name) = endpoint_name {
            ep_name_str = name.clone();
            args.push("--endpoint-name");
            args.push(&ep_name_str);
        }
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Health check IM channels via Python bridge.
/// Returns JSON array of health results.
#[tauri::command]
pub(crate) async fn openkitsune_health_check_im(
    venv_dir: String,
    workspace_id: String,
    channel: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let mut args = vec!["health-check-im", "--workspace-dir", &wd_str];
        let ch_str;
        if let Some(ref ch) = channel {
            ch_str = ch.clone();
            args.push("--channel");
            args.push(&ch_str);
        }
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Ensure IM channel dependencies are installed via Python bridge.
/// Returns JSON with status/installed/message.
#[tauri::command]
pub(crate) async fn openkitsune_ensure_channel_deps(
    venv_dir: String,
    workspace_id: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let args = vec!["ensure-channel-deps", "--workspace-dir", &wd_str];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Install a skill from URL/path.
#[tauri::command]
pub(crate) async fn openkitsune_install_skill(
    venv_dir: String,
    workspace_id: String,
    url: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let args = vec!["install-skill", "--workspace-dir", &wd_str, "--url", &url];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Uninstall a skill by name.
#[tauri::command]
pub(crate) async fn openkitsune_uninstall_skill(
    venv_dir: String,
    workspace_id: String,
    skill_name: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let args = vec![
            "uninstall-skill",
            "--workspace-dir",
            &wd_str,
            "--skill-name",
            &skill_name,
        ];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// List marketplace skills.
#[tauri::command]
pub(crate) async fn openkitsune_list_marketplace(
    venv_dir: String,
    query: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["list-marketplace", "--query", &query];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Get skill config schema.
#[tauri::command]
pub(crate) async fn openkitsune_get_skill_config(
    venv_dir: String,
    workspace_id: String,
    skill_name: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let wd = workspace_dir(&workspace_id);
        let wd_str = wd.to_string_lossy().to_string();
        let args = vec![
            "get-skill-config",
            "--workspace-dir",
            &wd_str,
            "--skill-name",
            &skill_name,
        ];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Start WeCom QR code onboarding (generate QR).
/// Returns JSON with qr_url + qr_id.
#[tauri::command]
pub(crate) async fn openkitsune_wecom_onboard_start(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["wecom-onboard-start"];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Poll WeCom QR code scan result.
/// Returns JSON with bot_id + secret on success.
#[tauri::command]
pub(crate) async fn openkitsune_wecom_onboard_poll(
    venv_dir: String,
    scode: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["wecom-onboard-poll", "--scode", &scode];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Start Feishu Device Flow onboarding (QR scan).
/// Returns JSON with device_code + verification_uri.
#[tauri::command]
pub(crate) async fn openkitsune_feishu_onboard_start(
    venv_dir: String,
    domain: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let d = domain.unwrap_or_else(|| "feishu".to_string());
        let args = vec!["feishu-onboard-start", "--domain", &d];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Poll Feishu Device Flow authorization status.
/// Returns JSON with status / app_id / app_secret on success.
#[tauri::command]
pub(crate) async fn openkitsune_feishu_onboard_poll(
    venv_dir: String,
    domain: Option<String>,
    device_code: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let d = domain.unwrap_or_else(|| "feishu".to_string());
        let args = vec![
            "feishu-onboard-poll",
            "--domain",
            &d,
            "--device-code",
            &device_code,
        ];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Validate Feishu App ID / App Secret credentials.
/// Returns JSON with {valid: bool, error?: string}.
#[tauri::command]
pub(crate) async fn openkitsune_feishu_validate(
    venv_dir: String,
    app_id: String,
    app_secret: String,
    domain: Option<String>,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let d = domain.unwrap_or_else(|| "feishu".to_string());
        let args = vec![
            "feishu-validate",
            "--app-id",
            &app_id,
            "--app-secret",
            &app_secret,
            "--domain",
            &d,
        ];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Start QQ Bot OpenClaw onboarding (QR scan).
/// Returns JSON with session_id + qr_url.
#[tauri::command]
pub(crate) async fn openkitsune_qqbot_onboard_start(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["qqbot-onboard-start"];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Poll QQ Bot OpenClaw login status.
/// Returns JSON with status / developer_id.
#[tauri::command]
pub(crate) async fn openkitsune_qqbot_onboard_poll(
    venv_dir: String,
    session_id: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["qqbot-onboard-poll", "--session-id", &session_id];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Create a QQ bot via OpenClaw.
/// Returns JSON with app_id / app_secret / bot_name.
#[tauri::command]
pub(crate) async fn openkitsune_qqbot_onboard_create(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["qqbot-onboard-create"];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Atomic poll + create in one process so cookies carry over.
/// Returns JSON with status / app_id / app_secret.
#[tauri::command]
pub(crate) async fn openkitsune_qqbot_onboard_poll_and_create(
    venv_dir: String,
    session_id: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["qqbot-onboard-poll-and-create", "--session-id", &session_id];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Validate QQ Bot App ID / App Secret credentials.
/// Returns JSON with {valid: bool, error?: string}.
#[tauri::command]
pub(crate) async fn openkitsune_qqbot_validate(
    venv_dir: String,
    app_id: String,
    app_secret: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec![
            "qqbot-validate",
            "--app-id",
            &app_id,
            "--app-secret",
            &app_secret,
        ];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Start WeChat iLink Bot QR code login.
/// Returns JSON with qrcode + qrcode_url.
#[tauri::command]
pub(crate) async fn openkitsune_wechat_onboard_start(venv_dir: String) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["wechat-onboard-start"];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}

/// Poll WeChat QR code login status (long-poll).
/// Returns JSON with status (wait/scaned/confirmed/expired) + token.
#[tauri::command]
pub(crate) async fn openkitsune_wechat_onboard_poll(
    venv_dir: String,
    qrcode: String,
) -> Result<String, String> {
    spawn_blocking_result(move || {
        let args = vec!["wechat-onboard-poll", "--qrcode", &qrcode];
        run_python_module_json(&venv_dir, "openkitsune.setup_center.bridge", &args, &[])
    })
    .await
}
