use crate::prelude::*;

const OPTIONAL_MODULES_MANIFEST: &str =
    include_str!("../../../../src/openkitsune/optional_modules.json");

#[derive(Debug, Deserialize)]
pub(crate) struct OptionalModulesManifest {
    pub(crate) modules: Vec<OptionalModuleDefinition>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize)]
pub(crate) struct OptionalModuleDefinition {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) description: String,
    pub(crate) packages: Vec<String>,
    pub(crate) estimated_size_mb: u32,
    pub(crate) category: String,
}

pub(crate) fn parse_optional_modules_manifest(
    content: &str,
) -> Result<OptionalModulesManifest, serde_json::Error> {
    serde_json::from_str(content)
}

pub(crate) fn module_definitions() -> Vec<OptionalModuleDefinition> {
    parse_optional_modules_manifest(OPTIONAL_MODULES_MANIFEST)
        .expect("embedded optional modules manifest must be valid JSON")
        .modules
}

#[cfg(test)]
mod optional_modules_tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn embedded_optional_module_manifest_has_complete_unique_definitions() {
        let definitions = module_definitions();
        let mut ids = HashSet::new();

        assert_eq!(definitions.len(), 3);
        for definition in &definitions {
            assert!(!definition.id.trim().is_empty());
            assert!(ids.insert(definition.id.as_str()), "duplicate module id");
            assert!(!definition.name.trim().is_empty());
            assert!(!definition.description.trim().is_empty());
            assert!(!definition.packages.is_empty());
            assert!(definition.estimated_size_mb > 0);
            assert!(!definition.category.trim().is_empty());
        }

        assert_eq!(
            ids,
            HashSet::from(["vector-memory", "whisper", "orchestration"])
        );
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct RootDirInfo {
    default_root: String,
    current_root: String,
    custom_root: Option<String>,
}

#[tauri::command]
pub(crate) fn get_root_dir_info() -> RootDirInfo {
    RootDirInfo {
        default_root: default_root_dir().to_string_lossy().to_string(),
        current_root: openkitsune_root_dir().to_string_lossy().to_string(),
        custom_root: read_root_config().custom_root,
    }
}

#[tauri::command]
pub(crate) fn set_custom_root_dir(
    path: Option<String>,
    migrate: bool,
) -> Result<RootDirInfo, String> {
    let _lock = ROOT_CONFIG_LOCK
        .lock()
        .map_err(|e| format!("lock failed: {e}"))?;
    let clean_path = path
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(String::from);

    if let Some(ref p) = clean_path {
        let target = PathBuf::from(p);
        if !target.is_absolute() {
            return Err("请使用绝对路径（如 D:\\MyData\\.openkitsune 或 /data/openkitsune）".into());
        }
        ensure_safe_openkitsune_data_root(&target)?;
        if target.exists() && !target.is_dir() {
            return Err("指定的路径已存在但不是目录".into());
        }
        fs::create_dir_all(&target).map_err(|e| format!("无法创建目标目录: {e}"))?;
        write_root_marker(&target)?;
        // 验证目录可写
        let test_file = target.join(".openkitsune_write_test");
        fs::write(&test_file, "test").map_err(|e| format!("目标目录无写入权限: {e}"))?;
        let _ = fs::remove_file(&test_file);
    }

    let migrate_old_root: Option<PathBuf> = if migrate {
        let old_root = openkitsune_root_dir();
        let new_root_path = match &clean_path {
            Some(p) => PathBuf::from(p),
            None => default_root_dir(),
        };

        if old_root != new_root_path && old_root.exists() {
            if !new_root_path.exists() {
                fs::create_dir_all(&new_root_path).map_err(|e| format!("无法创建目标目录: {e}"))?;
            }

            let critical_dirs = ["workspaces"];
            let optional_dirs = ["venv", "runtime", "run", "logs", "modules", "bin"];
            let mut errors: Vec<String> = Vec::new();

            for entry_name in critical_dirs.iter().chain(optional_dirs.iter()) {
                let src = old_root.join(entry_name);
                let dst = new_root_path.join(entry_name);
                if src.exists() && src.is_dir() && !dst.exists() {
                    if let Err(e) = copy_dir_recursive(&src, &dst) {
                        let msg = format!("{}: {}", entry_name, e);
                        eprintln!("migrate dir {}", msg);
                        if critical_dirs.contains(entry_name) {
                            let _ = fs::remove_dir_all(&dst);
                            return Err(format!(
                                "关键目录 {} 复制失败，已中止迁移，配置未更改。错误: {}",
                                entry_name, e
                            ));
                        }
                        errors.push(msg);
                    }
                }
            }
            for file_name in &["state.json", "cli.json"] {
                let src = old_root.join(file_name);
                let dst = new_root_path.join(file_name);
                if src.exists() && src.is_file() && !dst.exists() {
                    if let Err(e) = fs::copy(&src, &dst) {
                        errors.push(format!("{}: {}", file_name, e));
                        eprintln!("migrate file {}: {}", file_name, e);
                    }
                }
            }
            if !errors.is_empty() {
                eprintln!(
                    "migration completed with {} non-critical errors",
                    errors.len()
                );
            }

            if !new_root_path.exists() || !new_root_path.is_dir() {
                return Err(
                    "迁移完成后目标目录不可访问，未更改配置。请检查磁盘连接后重试。".into(),
                );
            }
            Some(old_root)
        } else {
            None
        }
    } else {
        None
    };

    let config = RootConfig {
        custom_root: clean_path,
    };
    write_root_config(&config)?;

    // Config updated successfully — clean up migrated entries from old root
    if let Some(ref old_root) = migrate_old_root {
        if is_safe_openkitsune_data_root(old_root) {
            let dir_names = [
                "workspaces",
                "venv",
                "runtime",
                "run",
                "logs",
                "modules",
                "bin",
            ];
            let file_names = ["state.json", "cli.json"];
            for name in &dir_names {
                let p = old_root.join(name);
                if p.exists() && p.is_dir() {
                    if let Err(e) = fs::remove_dir_all(&p) {
                        eprintln!("cleanup old {}: {e}", p.display());
                    }
                }
            }
            for name in &file_names {
                let p = old_root.join(name);
                if p.exists() && p.is_file() {
                    let _ = fs::remove_file(&p);
                }
            }
        } else {
            eprintln!("skip cleanup for unsafe old root {}", old_root.display());
        }
    }

    Ok(RootDirInfo {
        default_root: default_root_dir().to_string_lossy().to_string(),
        current_root: openkitsune_root_dir().to_string_lossy().to_string(),
        custom_root: config.custom_root,
    })
}

pub(crate) fn copy_dir_recursive(src: &Path, dst: &Path) -> Result<(), String> {
    fs::create_dir_all(dst).map_err(|e| format!("create dir {}: {e}", dst.display()))?;
    let entries = fs::read_dir(src).map_err(|e| format!("read dir {}: {e}", src.display()))?;
    for entry in entries.flatten() {
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        // file_type() 不跟随符号链接（区别于 metadata()），能正确识别 symlink
        let ft = match entry.file_type() {
            Ok(ft) => ft,
            Err(_) => continue,
        };
        if ft.is_symlink() {
            continue;
        }
        if ft.is_dir() {
            copy_dir_recursive(&src_path, &dst_path)?;
        } else if ft.is_file() {
            if let Err(e) = fs::copy(&src_path, &dst_path) {
                eprintln!(
                    "copy file {} -> {}: {e}",
                    src_path.display(),
                    dst_path.display()
                );
            }
        }
    }
    Ok(())
}

// ── Workspace migration preflight ──

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MigrateEntry {
    name: String,
    size_mb: f64,
    exists_at_target: bool,
    is_dir: bool,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MigratePreflightInfo {
    source_path: String,
    source_size_mb: f64,
    target_path: String,
    target_free_mb: f64,
    entries: Vec<MigrateEntry>,
    can_migrate: bool,
    reason: String,
}

pub(crate) fn available_space_mb(path: &Path) -> f64 {
    #[cfg(target_os = "windows")]
    {
        use std::ffi::OsStr;
        use std::os::windows::ffi::OsStrExt;
        let fallback = path
            .ancestors()
            .last()
            .map(|r| r.to_string_lossy().to_string())
            .unwrap_or_else(|| "C:\\".to_string());
        let wide: Vec<u16> = OsStr::new(path.to_str().unwrap_or(&fallback))
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();
        let mut free_bytes: u64 = 0;
        unsafe {
            #[link(name = "kernel32")]
            extern "system" {
                fn GetDiskFreeSpaceExW(
                    lpDirectoryName: *const u16,
                    lpFreeBytesAvailableToCaller: *mut u64,
                    lpTotalNumberOfBytes: *mut u64,
                    lpTotalNumberOfFreeBytes: *mut u64,
                ) -> i32;
            }
            GetDiskFreeSpaceExW(
                wide.as_ptr(),
                &mut free_bytes,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            );
        }
        free_bytes as f64 / 1024.0 / 1024.0
    }
    #[cfg(not(target_os = "windows"))]
    {
        use std::mem::MaybeUninit;
        let c_path = std::ffi::CString::new(path.to_str().unwrap_or("/")).unwrap_or_default();
        let mut stat = MaybeUninit::<libc::statvfs>::uninit();
        let ok = unsafe { libc::statvfs(c_path.as_ptr(), stat.as_mut_ptr()) };
        if ok == 0 {
            let stat = unsafe { stat.assume_init() };
            (stat.f_bavail as f64) * (stat.f_frsize as f64) / 1024.0 / 1024.0
        } else {
            0.0
        }
    }
}

#[tauri::command]
pub(crate) fn preflight_migrate_root(target_path: String) -> Result<MigratePreflightInfo, String> {
    let target = PathBuf::from(target_path.trim());
    if !target.is_absolute() {
        return Err("请使用绝对路径".into());
    }
    ensure_safe_openkitsune_data_root(&target)?;

    let source = openkitsune_root_dir();
    if source == target {
        return Ok(MigratePreflightInfo {
            source_path: source.to_string_lossy().to_string(),
            source_size_mb: 0.0,
            target_path: target.to_string_lossy().to_string(),
            target_free_mb: 0.0,
            entries: vec![],
            can_migrate: false,
            reason: "目标路径与当前路径相同".into(),
        });
    }

    let dir_names: &[&str] = &[
        "workspaces",
        "venv",
        "runtime",
        "run",
        "logs",
        "modules",
        "bin",
    ];
    let file_names: &[&str] = &["state.json", "cli.json"];

    let mut entries = Vec::new();
    let mut total_size: u64 = 0;

    for name in dir_names {
        let src = source.join(name);
        if src.exists() && src.is_dir() {
            let size = dir_size_bytes(&src);
            total_size += size;
            entries.push(MigrateEntry {
                name: name.to_string(),
                size_mb: size as f64 / 1024.0 / 1024.0,
                exists_at_target: target.join(name).exists(),
                is_dir: true,
            });
        }
    }
    for name in file_names {
        let src = source.join(name);
        if src.exists() && src.is_file() {
            let size = src.metadata().map(|m| m.len()).unwrap_or(0);
            total_size += size;
            entries.push(MigrateEntry {
                name: name.to_string(),
                size_mb: size as f64 / 1024.0 / 1024.0,
                exists_at_target: target.join(name).exists(),
                is_dir: false,
            });
        }
    }

    let free_space_path = if target.exists() {
        target.clone()
    } else {
        target
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| target.clone())
    };
    let target_free_mb = available_space_mb(&free_space_path);
    let source_size_mb = total_size as f64 / 1024.0 / 1024.0;

    let has_conflicts = entries.iter().any(|e| e.exists_at_target);
    let enough_space = target_free_mb > source_size_mb * 1.1 + 100.0;

    let (can_migrate, reason) = if entries.is_empty() {
        (false, "当前数据目录为空，无需迁移".into())
    } else if !enough_space {
        (
            false,
            format!(
                "目标磁盘空间不足（需要 {:.0} MB，可用 {:.0} MB）",
                source_size_mb * 1.1,
                target_free_mb
            ),
        )
    } else if has_conflicts {
        (true, "目标路径已存在部分数据，已有数据将被跳过".into())
    } else {
        (true, "可以迁移".into())
    };

    Ok(MigratePreflightInfo {
        source_path: source.to_string_lossy().to_string(),
        source_size_mb,
        target_path: target.to_string_lossy().to_string(),
        target_free_mb,
        entries,
        can_migrate,
        reason,
    })
}

#[tauri::command]
pub(crate) fn is_first_run() -> bool {
    let state = read_state_file();
    onboarding_required(&state)
}

pub(crate) fn onboarding_required(state: &AppStateFile) -> bool {
    state
        .onboarding_completed
        .map(|completed| !completed)
        .unwrap_or_else(|| state.workspaces.is_empty())
}

#[tauri::command]
pub(crate) fn set_onboarding_completed(completed: bool) -> Result<(), String> {
    let _lock = STATE_FILE_LOCK
        .lock()
        .map_err(|e| format!("state lock failed: {e}"))?;
    let mut state = read_state_file();
    state.onboarding_completed = Some(completed);
    write_state_file(&state)
}

// ── 环境检测 ──

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct EnvironmentCheck {
    /// 实际检查的根目录路径，便于用户核对是否与已删除的目录一致（如以管理员运行可能为另一用户目录）
    openkitsune_root: String,
    has_old_venv: bool,
    has_old_runtime: bool,
    has_old_workspaces: bool,
    old_version: Option<String>,
    current_version: String,
    running_processes: Vec<String>,
    disk_usage_mb: u64,
    conflicts: Vec<String>,
}

pub(crate) fn dir_size_bytes(path: &Path) -> u64 {
    if !path.exists() {
        return 0;
    }
    let mut total: u64 = 0;
    if let Ok(entries) = fs::read_dir(path) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_file() {
                total += p.metadata().map(|m| m.len()).unwrap_or(0);
            } else if p.is_dir() {
                total += dir_size_bytes(&p);
            }
        }
    }
    total
}

#[tauri::command]
pub(crate) fn check_environment() -> EnvironmentCheck {
    let root = openkitsune_root_dir();
    // 只有目录存在且非空才算有旧残留
    let has_old_venv = root.join("venv").exists()
        && root
            .join("venv")
            .read_dir()
            .map(|mut d| d.next().is_some())
            .unwrap_or(false);
    let has_old_runtime = root.join("runtime").exists()
        && root
            .join("runtime")
            .read_dir()
            .map(|mut d| d.next().is_some())
            .unwrap_or(false);
    let has_old_workspaces = root.join("workspaces").exists()
        && root
            .join("workspaces")
            .read_dir()
            .map(|mut d| d.next().is_some())
            .unwrap_or(false);

    // Read version from state.json
    let state = read_state_file();
    let old_version = state.last_installed_version.clone();
    let current_version = env!("CARGO_PKG_VERSION").to_string();

    // Check running processes (extract workspace_id from filename: openkitsune-{ws_id}.pid)
    let mut running = Vec::new();
    if let Ok(entries) = fs::read_dir(run_dir()) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) == Some("pid") {
                let ws_id = path
                    .file_stem()
                    .and_then(|s| s.to_str())
                    .and_then(|s| s.strip_prefix("openkitsune-"))
                    .unwrap_or("unknown");
                if let Ok(content) = fs::read_to_string(&path) {
                    if let Ok(data) = serde_json::from_str::<PidFileData>(&content) {
                        if is_pid_running(data.pid) {
                            running.push(format!("PID {} (workspace: {})", data.pid, ws_id));
                        }
                    }
                }
            }
        }
    }

    let disk_usage_mb = dir_size_bytes(&root) / (1024 * 1024);

    // venv 是打包后应用运行时的关键组件：
    // - venv: 用于 pip install 模块（vector-memory 等）和工具执行
    // Python 基座来自 bootstrap seed，不依赖运行时下载链路。

    let mut conflicts = Vec::new();
    if !running.is_empty() {
        conflicts.push(format!(
            "检测到 {} 个正在运行的 OpenKitsune 进程",
            running.len()
        ));
    }

    EnvironmentCheck {
        openkitsune_root: root.to_string_lossy().to_string(),
        has_old_venv,
        has_old_runtime,
        has_old_workspaces,
        old_version,
        current_version,
        running_processes: running,
        disk_usage_mb,
        conflicts,
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub(crate) struct BackendAvailability {
    bundled: bool,
    venv_ready: bool,
    exe_path: String,
    bundled_checked: String,
    venv_checked: String,
}

#[tauri::command]
pub(crate) fn check_backend_availability(venv_dir: String) -> BackendAvailability {
    let managed_seed = managed_python_seed_path();
    let venv_py = venv_pythonw_path(&venv_dir);
    let bundled = managed_seed.is_some();
    let venv_ready = legacy_venv_has_openkitsune_backend(&venv_dir);
    let exe_path = if let Some(ref seed) = managed_seed {
        seed.to_string_lossy().to_string()
    } else if venv_ready {
        venv_py.to_string_lossy().to_string()
    } else {
        String::new()
    };
    eprintln!(
        "[backend-check] bootstrap_seed={} ({}) venv={} ({})",
        bundled,
        managed_seed
            .as_deref()
            .unwrap_or_else(|| Path::new("<missing>"))
            .display(),
        venv_ready,
        venv_py.display()
    );
    BackendAvailability {
        bundled,
        venv_ready,
        exe_path,
        bundled_checked: managed_seed
            .map(|path| path.to_string_lossy().to_string())
            .unwrap_or_else(|| {
                bootstrap_resource_dir()
                    .join("python")
                    .to_string_lossy()
                    .to_string()
            }),
        venv_checked: venv_py.to_string_lossy().to_string(),
    }
}

pub(crate) fn legacy_venv_has_openkitsune_backend(venv_dir: &str) -> bool {
    let python = venv_python_path(venv_dir);
    if !python.exists() {
        return false;
    }

    let mut command = Command::new(python);
    apply_no_window(&mut command);
    strip_harmful_python_env(&mut command);
    command.env("PYTHONUTF8", "1");
    command.env("PYTHONIOENCODING", "utf-8");
    command.args([
        "-c",
        "import openkitsune; import openkitsune.main; import openkitsune.setup_center.bridge",
    ]);
    command
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

/// 强制删除目录：先尝试 Rust remove_dir_all，失败时在 Windows 上回退到 cmd /c rd /s /q
pub(crate) fn force_remove_dir(path: &std::path::Path) -> Result<(), String> {
    if !path.exists() {
        return Ok(());
    }
    // 第一次尝试：Rust 标准库
    if fs::remove_dir_all(path).is_ok() {
        return Ok(());
    }
    // 第二次尝试 (Windows)：先去掉只读属性再 rd /s /q，避免“清不掉”
    #[cfg(target_os = "windows")]
    {
        let mut attrib = std::process::Command::new("cmd");
        attrib.args(["/c", "attrib", "-R", "/S", "/D"]).arg(path);
        apply_no_window(&mut attrib);
        let _ = attrib.status();
        let mut rd_cmd = std::process::Command::new("cmd");
        rd_cmd.args(["/c", "rd", "/s", "/q"]).arg(path);
        apply_no_window(&mut rd_cmd);
        let status = rd_cmd
            .status()
            .map_err(|e| format!("执行 rd 命令失败: {e}"))?;
        if status.success() || !path.exists() {
            return Ok(());
        }
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("chmod").args(["-R", "u+w"]).arg(path).status();
        let status = Command::new("rm")
            .args(["-rf"])
            .arg(path)
            .status()
            .map_err(|e| format!("rm -rf failed: {e}"))?;
        if status.success() || !path.exists() {
            return Ok(());
        }
    }
    if path.exists() {
        Err(format!("无法删除目录: {}", path.display()))
    } else {
        Ok(())
    }
}

#[tauri::command]
pub(crate) fn cleanup_old_environment(
    clean_venv: bool,
    clean_runtime: bool,
) -> Result<String, String> {
    let root = openkitsune_root_dir();
    let mut cleaned = Vec::new();
    let mut warnings = Vec::new();

    if clean_venv {
        let venv_path = root.join("venv");
        if venv_path.exists() {
            // 检查是否有已安装的外置模块依赖此 venv
            let modules_base = root.join("modules");
            let has_installed_modules = modules_base.exists()
                && modules_base
                    .read_dir()
                    .map(|mut d| d.any(|e| e.map(|e| e.path().is_dir()).unwrap_or(false)))
                    .unwrap_or(false);
            if has_installed_modules {
                warnings.push(
                    "注意: 清理 venv 后已安装的外置模块（vector-memory 等）可能需要重新安装"
                        .to_string(),
                );
            }
            force_remove_dir(&venv_path).map_err(|e| format!("清理 venv 失败: {e}"))?;
            cleaned.push("venv");
        }
    }
    if clean_runtime {
        let runtime_path = root.join("runtime");
        if runtime_path.exists() {
            force_remove_dir(&runtime_path).map_err(|e| format!("清理 runtime 失败: {e}"))?;
            cleaned.push("runtime");
        }
    }

    if cleaned.is_empty() {
        Ok("无需清理".to_string())
    } else {
        let mut msg = format!("已清理: {}", cleaned.join(", "));
        if !warnings.is_empty() {
            msg.push_str(&format!(" ({})", warnings.join("; ")));
        }
        Ok(msg)
    }
}

/// Reset the entire OpenKitsune installation to factory state.
/// Stops all processes, then removes workspaces, runtime, venv, logs, etc.
/// Preserves only `root_config.json` (custom root dir setting).
#[tauri::command]
pub(crate) fn factory_reset() -> Result<String, String> {
    // 1. Stop all running backend processes
    let stopped = openkitsune_stop_all_processes();

    // 2. Determine root and build list of paths to remove
    let root = openkitsune_root_dir();
    let dirs_to_remove = [
        "workspaces",
        "venv",
        "runtime",
        "run",
        "logs",
        "modules",
        "bin",
        "data",
    ];
    let files_to_remove = ["state.json", "cli.json"];

    let mut removed = Vec::new();
    let mut errors = Vec::new();

    for name in &dirs_to_remove {
        let p = root.join(name);
        if p.exists() {
            match force_remove_dir(&p) {
                Ok(()) => removed.push(name.to_string()),
                Err(e) => errors.push(format!("{name}: {e}")),
            }
        }
    }

    for name in &files_to_remove {
        let p = root.join(name);
        if p.exists() {
            match fs::remove_file(&p) {
                Ok(()) => removed.push(name.to_string()),
                Err(e) => errors.push(format!("{name}: {e}")),
            }
        }
    }

    if !errors.is_empty() {
        return Err(format!(
            "部分重置失败: {}{}",
            errors.join("; "),
            if !removed.is_empty() {
                format!(" (已清理: {})", removed.join(", "))
            } else {
                String::new()
            }
        ));
    }

    let mut msg = if removed.is_empty() {
        "无需清理（已是初始状态）".to_string()
    } else {
        format!("已清理: {}", removed.join(", "))
    };

    if !stopped.is_empty() {
        msg.push_str(&format!(" (已停止 {} 个进程)", stopped.len()));
    }

    Ok(msg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn onboarding_marker_preserves_failures_after_workspace_creation() {
        let mut state = AppStateFile {
            workspaces: vec![WorkspaceMeta {
                id: "default".into(),
                name: "Default".into(),
            }],
            ..Default::default()
        };

        assert!(!onboarding_required(&state));
        state.onboarding_completed = Some(false);
        assert!(onboarding_required(&state));
        state.onboarding_completed = Some(true);
        assert!(!onboarding_required(&state));
    }

    #[test]
    fn test_check_backend_availability_with_nonexistent_venv() {
        let fake = if cfg!(windows) {
            r"C:\nonexistent-venv-test-99999"
        } else {
            "/tmp/nonexistent-venv-test-99999"
        };
        let result = check_backend_availability(fake.to_string());
        assert!(!result.venv_ready);
        assert!(!result.venv_checked.is_empty());
        assert!(!result.bundled_checked.is_empty());
    }

    #[test]
    fn test_check_backend_availability_rejects_empty_venv() {
        let temp =
            std::env::temp_dir().join(format!("openkitsune-empty-venv-test-{}", std::process::id()));
        if temp.exists() {
            let _ = fs::remove_dir_all(&temp);
        }
        let status = Command::new("uv")
            .args(["venv", temp.to_string_lossy().as_ref(), "--python", "3.11"])
            .status();
        let Ok(status) = status else {
            eprintln!("skipping empty venv availability test: uv not available");
            return;
        };
        if !status.success() {
            eprintln!("skipping empty venv availability test: uv venv failed");
            let _ = fs::remove_dir_all(&temp);
            return;
        }

        let result = check_backend_availability(temp.to_string_lossy().to_string());
        assert!(
            !result.venv_ready,
            "empty venv with only python.exe must not be treated as backend-ready"
        );
        let _ = fs::remove_dir_all(&temp);
    }

    #[test]
    fn test_openkitsune_root_dir_is_valid() {
        let root = openkitsune_root_dir();
        assert!(!root.to_string_lossy().is_empty());
        // Should contain .openkitsune unless overridden by OPENKITSUNE_ROOT
        let root_str = root.to_string_lossy();
        assert!(
            root_str.contains(".openkitsune") || std::env::var("OPENKITSUNE_ROOT").is_ok(),
            "root dir should contain '.openkitsune' or OPENKITSUNE_ROOT should be set: {}",
            root_str
        );
    }

    #[test]
    fn test_data_root_rejects_drive_or_filesystem_root() {
        let root = if cfg!(windows) {
            PathBuf::from(r"D:\")
        } else {
            PathBuf::from("/")
        };
        assert!(!is_safe_openkitsune_data_root(&root));
        assert!(ensure_safe_openkitsune_data_root(&root).is_err());
    }

    #[test]
    fn test_data_root_rejects_home_directory() {
        if let Some(home) = home_dir() {
            assert!(!is_safe_openkitsune_data_root(&home));
            assert!(ensure_safe_openkitsune_data_root(&home).is_err());
        }
    }

    #[test]
    fn test_data_root_allows_dedicated_directory() {
        let dedicated = if cfg!(windows) {
            PathBuf::from(r"D:\OpenKitsuneData\.openkitsune")
        } else {
            PathBuf::from("/tmp/openkitsune-data/.openkitsune")
        };
        assert!(is_safe_openkitsune_data_root(&dedicated));
        assert!(ensure_safe_openkitsune_data_root(&dedicated).is_ok());
    }
}
