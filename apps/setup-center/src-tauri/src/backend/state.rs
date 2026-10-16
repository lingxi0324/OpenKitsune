use crate::prelude::*;

pub(crate) fn read_state_file() -> AppStateFile {
    let p = state_file_path();
    if let Ok(content) = fs::read_to_string(&p) {
        if let Ok(state) = serde_json::from_str::<AppStateFile>(&content) {
            if !state.workspaces.is_empty() {
                return state;
            }
            // workspaces is empty — could be a truncated/corrupted write.
            // Fall through to disk recovery, but preserve other fields.
            let recovered = rebuild_state_from_disk(Some(state));
            if !recovered.workspaces.is_empty() {
                eprintln!(
                    "state.json had empty workspaces but {} workspace dir(s) found on disk — recovered",
                    recovered.workspaces.len()
                );
                let _ = write_state_file(&recovered);
            }
            return recovered;
        }
        // JSON parse failed (truncated / corrupted file)
        eprintln!("warning: state.json is corrupted, attempting disk recovery");
    }
    // File missing or unreadable — try to recover from workspaces/ directory
    let recovered = rebuild_state_from_disk(None);
    if !recovered.workspaces.is_empty() {
        eprintln!(
            "state.json missing but {} workspace dir(s) found on disk — recovered",
            recovered.workspaces.len()
        );
        let _ = write_state_file(&recovered);
    }
    recovered
}

/// Scan workspaces/ directory to rebuild state when state.json is missing or corrupted.
/// A subdirectory is considered a valid workspace only if it contains a `data/` child.
pub(crate) fn rebuild_state_from_disk(partial: Option<AppStateFile>) -> AppStateFile {
    let mut state = partial.unwrap_or_default();
    let ws_dir = workspaces_dir();
    let Ok(entries) = fs::read_dir(&ws_dir) else {
        return state;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        if !path.join("data").exists() {
            continue;
        }
        let id = entry.file_name().to_string_lossy().to_string();
        if state.workspaces.iter().any(|w| w.id == id) {
            continue;
        }
        state.workspaces.push(WorkspaceMeta {
            id: id.clone(),
            name: id.clone(),
        });
    }
    if state.current_workspace_id.is_none() && !state.workspaces.is_empty() {
        // Prefer "default" if it exists, otherwise pick the first one
        let preferred = state
            .workspaces
            .iter()
            .find(|w| w.id == "default")
            .unwrap_or(&state.workspaces[0]);
        state.current_workspace_id = Some(preferred.id.clone());
    }
    state
}

pub(crate) fn write_state_file(state: &AppStateFile) -> Result<(), String> {
    let p = state_file_path();
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("create_dir_all failed: {e}"))?;
    }
    let data = serde_json::to_string_pretty(state).map_err(|e| format!("serialize failed: {e}"))?;
    atomic_write_with_backup(&p, data.as_bytes())
}

/// Crash-safe file write: backup existing file, write to .tmp, then atomic rename.
/// On Windows rename failure (file locked), retries up to 3 times before falling back
/// to direct write.
pub(crate) fn atomic_write_with_backup(path: &Path, content: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("create parent dir failed: {e}"))?;
    }
    if path.exists() {
        let bak = path.with_extension("json.bak");
        let _ = fs::copy(path, &bak);
    }
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, content).map_err(|e| format!("write tmp failed: {e}"))?;
    for attempt in 0..3u64 {
        match fs::rename(&tmp, path) {
            Ok(()) => return Ok(()),
            Err(e) => {
                if attempt < 2 {
                    std::thread::sleep(std::time::Duration::from_millis(100 * (attempt + 1)));
                } else {
                    eprintln!(
                        "atomic rename failed after 3 retries ({e}), falling back to direct write"
                    );
                    if let Err(e2) = fs::write(path, content) {
                        let _ = fs::remove_file(&tmp);
                        return Err(format!("write failed: {e2}"));
                    }
                    let _ = fs::remove_file(&tmp);
                    return Ok(());
                }
            }
        }
    }
    Ok(())
}

pub(crate) fn ensure_workspace_scaffold(dir: &Path) -> Result<(), String> {
    fs::create_dir_all(dir.join("data")).map_err(|e| format!("create data dir failed: {e}"))?;
    fs::create_dir_all(dir.join("identity"))
        .map_err(|e| format!("create identity dir failed: {e}"))?;

    // Only ASCII comments in .env to avoid encoding issues on non-UTF-8 Windows systems.
    let env_path = dir.join(".env");
    if !env_path.exists() {
        let content = [
            "# OpenKitsune workspace environment (managed by Setup Center)",
            "#",
            "# - Only keys you explicitly set in Setup Center are written here.",
            "# - Clearing a value removes the key from this file.",
            "# - For the full template, see examples/.env.example",
            "",
        ]
        .join("\n");
        fs::write(&env_path, content).map_err(|e| format!("write .env failed: {e}"))?;
    }

    // identity 文件：从仓库模板复制生成，保证字段完整性与一致性（而不是随意占位）
    const DEFAULT_SOUL: &str = include_str!("../../../../../identity/SOUL.md.example");
    const DEFAULT_AGENT: &str = include_str!("../../../../../identity/AGENT.md.example");
    const DEFAULT_USER: &str = include_str!("../../../../../identity/USER.md.example");
    const DEFAULT_MEMORY: &str = include_str!("../../../../../identity/MEMORY.md.example");

    let soul = dir.join("identity").join("SOUL.md");
    if !soul.exists() {
        fs::write(&soul, DEFAULT_SOUL)
            .map_err(|e| format!("write identity/SOUL.md failed: {e}"))?;
    }
    let agent_md = dir.join("identity").join("AGENT.md");
    if !agent_md.exists() {
        fs::write(&agent_md, DEFAULT_AGENT)
            .map_err(|e| format!("write identity/AGENT.md failed: {e}"))?;
    }
    let user_md = dir.join("identity").join("USER.md");
    if !user_md.exists() {
        fs::write(&user_md, DEFAULT_USER)
            .map_err(|e| format!("write identity/USER.md failed: {e}"))?;
    }
    let memory_md = dir.join("identity").join("MEMORY.md");
    if !memory_md.exists() {
        fs::write(&memory_md, DEFAULT_MEMORY)
            .map_err(|e| format!("write identity/MEMORY.md failed: {e}"))?;
    }

    // 人格预设文件：8 个标配预设 + user_custom 模板
    // 从仓库 identity/personas/ 目录嵌入，确保新工作区开箱即用
    {
        const PERSONA_DEFAULT: &str = include_str!("../../../../../identity/personas/default.md");
        const PERSONA_BUSINESS: &str = include_str!("../../../../../identity/personas/business.md");
        const PERSONA_TECH_EXPERT: &str =
            include_str!("../../../../../identity/personas/tech_expert.md");
        const PERSONA_BUTLER: &str = include_str!("../../../../../identity/personas/butler.md");
        const PERSONA_GIRLFRIEND: &str =
            include_str!("../../../../../identity/personas/girlfriend.md");
        const PERSONA_BOYFRIEND: &str =
            include_str!("../../../../../identity/personas/boyfriend.md");
        const PERSONA_FAMILY: &str = include_str!("../../../../../identity/personas/family.md");
        const PERSONA_JARVIS: &str = include_str!("../../../../../identity/personas/jarvis.md");
        const PERSONA_USER_CUSTOM: &str =
            include_str!("../../../../../identity/personas/user_custom.md.example");

        let personas_dir = dir.join("identity").join("personas");
        fs::create_dir_all(&personas_dir)
            .map_err(|e| format!("create identity/personas dir failed: {e}"))?;

        let presets: &[(&str, &str)] = &[
            ("default.md", PERSONA_DEFAULT),
            ("business.md", PERSONA_BUSINESS),
            ("tech_expert.md", PERSONA_TECH_EXPERT),
            ("butler.md", PERSONA_BUTLER),
            ("girlfriend.md", PERSONA_GIRLFRIEND),
            ("boyfriend.md", PERSONA_BOYFRIEND),
            ("family.md", PERSONA_FAMILY),
            ("jarvis.md", PERSONA_JARVIS),
            ("user_custom.md", PERSONA_USER_CUSTOM),
        ];

        for (filename, content) in presets {
            let path = personas_dir.join(filename);
            if !path.exists() {
                fs::write(&path, content)
                    .map_err(|e| format!("write identity/personas/{filename} failed: {e}"))?;
            }
        }
    }

    // policies 文件：运行时策略规则，builder.py 会读取
    {
        let prompts_dir = dir.join("identity").join("prompts");
        fs::create_dir_all(&prompts_dir)
            .map_err(|e| format!("create identity/prompts dir failed: {e}"))?;
        let policies = prompts_dir.join("policies.md");
        if !policies.exists() {
            const DEFAULT_POLICIES: &str =
                include_str!("../../../../../identity/prompts/policies.md");
            fs::write(&policies, DEFAULT_POLICIES)
                .map_err(|e| format!("write identity/prompts/policies.md failed: {e}"))?;
        }
    }

    // 默认 llm_endpoints.json：用仓库内的 data/llm_endpoints.json.example 作为初始模板
    let llm = dir.join("data").join("llm_endpoints.json");
    if !llm.exists() {
        const DEFAULT_LLM_ENDPOINTS: &str =
            include_str!("../../../../../data/llm_endpoints.json.example");
        fs::write(&llm, DEFAULT_LLM_ENDPOINTS)
            .map_err(|e| format!("write data/llm_endpoints.json failed: {e}"))?;
    }

    Ok(())
}

#[tauri::command]
pub(crate) fn list_workspaces() -> Result<Vec<WorkspaceSummary>, String> {
    let root = openkitsune_root_dir();
    fs::create_dir_all(&root).map_err(|e| format!("create root failed: {e}"))?;
    fs::create_dir_all(workspaces_dir())
        .map_err(|e| format!("create workspaces dir failed: {e}"))?;

    let state = read_state_file();
    let current = state.current_workspace_id.clone();

    let mut out = vec![];
    for w in state.workspaces {
        let dir = workspace_dir(&w.id);
        ensure_workspace_scaffold(&dir)?;
        out.push(WorkspaceSummary {
            id: w.id.clone(),
            name: w.name.clone(),
            path: dir.to_string_lossy().to_string(),
            is_current: current.as_deref() == Some(&w.id),
        });
    }
    Ok(out)
}

pub(crate) fn validate_workspace_id(id: &str) -> Result<(), String> {
    let id = id.trim();
    if id.is_empty() {
        return Err("workspace id is empty".into());
    }
    if id.len() > 64 {
        return Err("workspace id too long (max 64 chars)".into());
    }
    if !id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return Err("workspace id can only contain a-z, A-Z, 0-9, _ and -".into());
    }
    if !id.chars().any(|c| c.is_ascii_alphanumeric()) {
        return Err("workspace id must contain at least one letter or digit".into());
    }
    const RESERVED: &[&str] = &[
        "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8",
        "com9", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    ];
    if RESERVED.contains(&id.to_ascii_lowercase().as_str()) {
        return Err("workspace id conflicts with a reserved system name".into());
    }
    Ok(())
}

#[tauri::command]
pub(crate) fn create_workspace(
    id: String,
    name: String,
    set_current: bool,
) -> Result<WorkspaceSummary, String> {
    validate_workspace_id(&id)?;
    if name.trim().is_empty() {
        return Err("workspace name is empty".into());
    }

    fs::create_dir_all(workspaces_dir())
        .map_err(|e| format!("create workspaces dir failed: {e}"))?;

    let _lock = STATE_FILE_LOCK
        .lock()
        .map_err(|e| format!("state lock failed: {e}"))?;
    let mut state = read_state_file();
    if state.workspaces.iter().any(|w| w.id == id) {
        return Err("workspace id already exists".into());
    }
    state.workspaces.push(WorkspaceMeta {
        id: id.clone(),
        name: name.clone(),
    });
    if set_current {
        state.current_workspace_id = Some(id.clone());
    } else if state.current_workspace_id.is_none() {
        state.current_workspace_id = Some(id.clone());
    }
    write_state_file(&state)?;

    let dir = workspace_dir(&id);
    ensure_workspace_scaffold(&dir)?;

    Ok(WorkspaceSummary {
        id: id.clone(),
        name,
        path: dir.to_string_lossy().to_string(),
        is_current: state.current_workspace_id.as_deref() == Some(&id),
    })
}

#[tauri::command]
pub(crate) fn set_current_workspace(id: String) -> Result<(), String> {
    let _lock = STATE_FILE_LOCK
        .lock()
        .map_err(|e| format!("state lock failed: {e}"))?;
    let mut state = read_state_file();
    if !state.workspaces.iter().any(|w| w.id == id) {
        return Err("workspace id not found".into());
    }
    let dir = workspace_dir(&id);
    if !dir.exists() {
        eprintln!(
            "workspace dir missing, recreating scaffold: {}",
            dir.display()
        );
        ensure_workspace_scaffold(&dir)?;
    }
    state.current_workspace_id = Some(id);
    write_state_file(&state)?;
    Ok(())
}
