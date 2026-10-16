/**
 * Encapsulates all env-draft state and persistence logic that was previously
 * scattered across App.tsx (envDraft, secretShown, ensureEnvLoaded, saveEnvKeys).
 *
 * Dependencies are injected via `opts` so the hook stays decoupled from service
 * status, workspace routing, etc.
 */

import { useRef, useState } from "react";
import { invoke, IS_TAURI, logger } from "../platform";
import { safeFetch } from "../providers";
import { parseEnv } from "../utils";
import type { EnvMap } from "../types";

export interface UseEnvManagerOpts {
  currentWorkspaceId: string | null;
  shouldUseHttpApi: () => boolean;
  httpApiBase: () => string;
}

const ENV_DEFAULTS: Record<string, string> = {
  DESKTOP_ENABLED: "true",
  MCP_ENABLED: "true",
};

const BACKUP_ENV_KEYS = new Set([
  "BACKUP_ENABLED",
  "BACKUP_PATH",
  "BACKUP_CRON",
  "BACKUP_MAX_BACKUPS",
  "BACKUP_INCLUDE_USERDATA",
  "BACKUP_INCLUDE_MEDIA",
]);

type BackupSettings = {
  enabled: boolean;
  cron: string;
  backup_path: string;
  max_backups: number;
  include_userdata: boolean;
  include_media: boolean;
};

function backupSettingsFromEnv(env: EnvMap): BackupSettings {
  return {
    enabled: (env.BACKUP_ENABLED || "false").toLowerCase() === "true",
    cron: env.BACKUP_CRON || "0 2 * * *",
    backup_path: env.BACKUP_PATH || "",
    max_backups: Math.max(1, Number.parseInt(env.BACKUP_MAX_BACKUPS || "5", 10) || 5),
    include_userdata: (env.BACKUP_INCLUDE_USERDATA || "true").toLowerCase() === "true",
    include_media: (env.BACKUP_INCLUDE_MEDIA || "false").toLowerCase() === "true",
  };
}

function applyBackupSettings(env: EnvMap, settings: Partial<BackupSettings>): void {
  if (typeof settings.enabled === "boolean") env.BACKUP_ENABLED = String(settings.enabled);
  if (typeof settings.cron === "string") env.BACKUP_CRON = settings.cron;
  if (typeof settings.backup_path === "string") env.BACKUP_PATH = settings.backup_path;
  if (typeof settings.max_backups === "number") env.BACKUP_MAX_BACKUPS = String(settings.max_backups);
  if (typeof settings.include_userdata === "boolean") env.BACKUP_INCLUDE_USERDATA = String(settings.include_userdata);
  if (typeof settings.include_media === "boolean") env.BACKUP_INCLUDE_MEDIA = String(settings.include_media);
}

export function useEnvManager(opts: UseEnvManagerOpts) {
  const [envDraft, setEnvDraft] = useState<EnvMap>({});
  const [envBaseline, setEnvBaseline] = useState<EnvMap>({});
  const [secretShown, setSecretShown] = useState<Record<string, boolean>>({});
  const envLoadedForWs = useRef<string | null>(null);

  const optsRef = useRef(opts);
  optsRef.current = opts;

  async function ensureEnvLoaded(workspaceId: string): Promise<EnvMap> {
    if (envLoadedForWs.current === workspaceId) return envDraft;
    let parsed: EnvMap = {};
    const { shouldUseHttpApi, httpApiBase } = optsRef.current;

    if (shouldUseHttpApi()) {
      try {
        const res = await safeFetch(`${httpApiBase()}/api/config/env`);
        const data = await res.json();
        parsed = data.env || {};
        const backupRes = await safeFetch(`${httpApiBase()}/api/workspace/backup-settings`);
        const backupData = await backupRes.json();
        applyBackupSettings(parsed, backupData.settings || {});
      } catch {
        if (IS_TAURI && workspaceId) {
          try {
            const content = await invoke<string>("workspace_read_file", { workspaceId, relativePath: ".env" });
            parsed = parseEnv(content);
            try {
              const backupContent = await invoke<string>("workspace_read_file", { workspaceId, relativePath: "data/backup_settings.json" });
              applyBackupSettings(parsed, JSON.parse(backupContent));
            } catch { /* no backup settings yet */ }
          } catch { parsed = {}; }
        }
      }
    } else if (IS_TAURI && workspaceId) {
      try {
        const content = await invoke<string>("workspace_read_file", { workspaceId, relativePath: ".env" });
        parsed = parseEnv(content);
        try {
          const backupContent = await invoke<string>("workspace_read_file", { workspaceId, relativePath: "data/backup_settings.json" });
          applyBackupSettings(parsed, JSON.parse(backupContent));
        } catch { /* no backup settings yet */ }
      } catch { parsed = {}; }
    }

    for (const [dk, dv] of Object.entries(ENV_DEFAULTS)) {
      if (!(dk in parsed)) parsed[dk] = dv;
    }
    setEnvDraft(parsed);
    setEnvBaseline({ ...parsed });
    envLoadedForWs.current = workspaceId;
    return parsed;
  }

  async function saveEnvKeys(keys: string[]): Promise<{
    restartRequired?: boolean;
    hotReloadable?: boolean;
    applyMode?: "immediate" | "next_task" | "component_reload" | "process_restart";
  }> {
    const { shouldUseHttpApi, httpApiBase, currentWorkspaceId } = optsRef.current;
    const savesBackupSettings = keys.some((key) => BACKUP_ENV_KEYS.has(key));
    const backupSettings = backupSettingsFromEnv(envDraft);
    const markKeysSaved = () => {
      setEnvBaseline((previous) => {
        const next = { ...previous };
        for (const key of keys) next[key] = envDraft[key] ?? "";
        return next;
      });
    };

    const entries: Record<string, string> = {};
    const deleteKeys: string[] = [];
    for (const k of keys) {
      if (BACKUP_ENV_KEYS.has(k)) {
        // Backup settings live in data/backup_settings.json. Delete legacy
        // .env copies so there is only one persisted source of truth.
        deleteKeys.push(k);
        continue;
      }
      if (Object.prototype.hasOwnProperty.call(envDraft, k)) {
        const v = (envDraft[k] ?? "").trim();
        if (v.length > 0) {
          entries[k] = v;
        } else {
          deleteKeys.push(k);
        }
      }
    }
    if (!Object.keys(entries).length && !deleteKeys.length && !savesBackupSettings) return {};

    if (shouldUseHttpApi()) {
      try {
        const res = await safeFetch(`${httpApiBase()}/api/config/env`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entries, delete_keys: deleteKeys }),
        });
        const data = await res.json().catch(() => ({}));
        if (savesBackupSettings) {
          await safeFetch(`${httpApiBase()}/api/workspace/backup-settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(backupSettings),
          });
        }
        markKeysSaved();
        return {
          restartRequired: data.restart_required ?? false,
          hotReloadable: data.hot_reloadable ?? true,
          applyMode: data.apply_mode,
        };
      } catch {
        logger.warn("useEnvManager", "saveEnvKeys: HTTP failed, falling back to Tauri");
      }
    }
    if (IS_TAURI && currentWorkspaceId) {
      await ensureEnvLoaded(currentWorkspaceId);
      const tauriEntries = [
        ...Object.entries(entries).map(([key, value]) => ({ key, value })),
        ...deleteKeys.map((key) => ({ key, value: "" })),
      ];
      await invoke("workspace_update_env", { workspaceId: currentWorkspaceId, entries: tauriEntries });
      if (savesBackupSettings) {
        await invoke("workspace_write_file", {
          workspaceId: currentWorkspaceId,
          relativePath: "data/backup_settings.json",
          content: JSON.stringify(backupSettings, null, 2),
        });
      }
      markKeysSaved();
      return {
        restartRequired: true,
        hotReloadable: false,
        applyMode: "process_restart",
      };
    }
    return {};
  }

  function resetEnvLoaded() {
    envLoadedForWs.current = null;
    setEnvDraft({});
    setEnvBaseline({});
  }

  function markEnvLoaded(workspaceId: string, loadedEnv?: EnvMap) {
    envLoadedForWs.current = workspaceId;
    if (loadedEnv) setEnvBaseline((previous) => ({ ...previous, ...loadedEnv }));
  }

  function mergeEffectiveEnvDefaults(values: EnvMap) {
    const mergeMissing = (previous: EnvMap) => {
      const next = { ...previous };
      for (const [key, value] of Object.entries(values)) {
        if (!Object.prototype.hasOwnProperty.call(previous, key)) next[key] = value;
      }
      return next;
    };
    setEnvDraft(mergeMissing);
    setEnvBaseline(mergeMissing);
  }

  return {
    envDraft,
    envBaseline,
    setEnvDraft,
    secretShown,
    setSecretShown,
    ensureEnvLoaded,
    saveEnvKeys,
    resetEnvLoaded,
    markEnvLoaded,
    mergeEffectiveEnvDefaults,
  };
}
