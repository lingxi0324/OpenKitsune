import { useCallback, useEffect, useState } from "react";
import { getAppVersion, checkForUpdate, relaunchApp, type UpdateInfo } from "../platform";

const GITHUB_REPO = "openkitsune/openkitsune";
const SKIPPED_RELEASE_KEY = "openkitsune_release_skipped";
const LEGACY_DISMISSED_RELEASE_KEY = "openkitsune_release_dismissed";
const REMIND_LATER_RELEASE_KEY = "openkitsune_release_remind_later_session";

export type NewReleaseInfo = { latest: string; current: string; url: string };
export type UpdateProgressState = {
  status: "idle" | "downloading" | "installing" | "done" | "error";
  percent?: number;
  error?: string;
};

export type AppUpdateCheckResult =
  | { status: "update-available"; release: NewReleaseInfo }
  | { status: "up-to-date"; current: string }
  | { status: "suppressed"; release: NewReleaseInfo }
  | { status: "error"; error: string };

export type AppUpdateCheckOptions = {
  manual?: boolean;
};

export function compareSemver(a: string, b: string): number {
  const parse = (v: string) => v.replace(/^v/, "").split(".").map((s) => parseInt(s, 10) || 0);
  const pa = parse(a);
  const pb = parse(b);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) > (pb[i] ?? 0)) return 1;
    if ((pa[i] ?? 0) < (pb[i] ?? 0)) return -1;
  }
  return 0;
}

function normalizeReleaseVersion(version: string): string {
  return String(version || "").trim().replace(/^v/i, "");
}

function getStoredValue(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function setStoredValue(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    // Storage can be unavailable in restricted webviews; the update prompt still works.
  }
}

function removeStoredValue(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // ignore
  }
}

function isReleaseSuppressed(version: string): boolean {
  const normalized = normalizeReleaseVersion(version);
  if (!normalized) return false;
  const skipped = normalizeReleaseVersion(
    getStoredValue(localStorage, SKIPPED_RELEASE_KEY)
      || getStoredValue(localStorage, LEGACY_DISMISSED_RELEASE_KEY)
      || "",
  );
  if (skipped === normalized) return true;
  const remindLater = normalizeReleaseVersion(getStoredValue(sessionStorage, REMIND_LATER_RELEASE_KEY) || "");
  return remindLater === normalized;
}

export function useVersionCheck() {
  const [desktopVersion, setDesktopVersion] = useState("0.0.0");
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [versionMismatch, setVersionMismatch] = useState<{ backend: string; desktop: string } | null>(null);
  const [newRelease, setNewRelease] = useState<NewReleaseInfo | null>(null);
  const [updateAvailable, setUpdateAvailable] = useState<UpdateInfo | null>(null);
  const [updateProgress, setUpdateProgress] = useState<UpdateProgressState>({ status: "idle" });

  useEffect(() => {
    getAppVersion().then((v) => setDesktopVersion(v)).catch(() => setDesktopVersion("1.10.5"));
  }, []);

  const checkVersionMismatch = useCallback((bv: string) => {
    if (!bv || bv === "0.0.0-dev") return;
    if (!desktopVersion || desktopVersion === "0.0.0") return;
    const normB = bv.replace(/^v/, "");
    const normD = desktopVersion.replace(/^v/, "");
    setVersionMismatch(normB !== normD ? { backend: normB, desktop: normD } : null);
  }, [desktopVersion]);

  const checkForAppUpdate = useCallback(async (
    options: AppUpdateCheckOptions = {},
  ): Promise<AppUpdateCheckResult> => {
    const showRelease = (latest: string, url: string, update: UpdateInfo | null) => {
      const release = {
        latest,
        current: desktopVersion,
        url,
      };
      if (!options.manual && isReleaseSuppressed(latest)) {
        return { status: "suppressed", release } as const;
      }
      setUpdateAvailable(update);
      setNewRelease(release);
      return { status: "update-available", release } as const;
    };

    try {
      const update = await checkForUpdate({ apiBaseUrl: "http://127.0.0.1:18900" });
      if (update) {
        const latest = normalizeReleaseVersion(update.version);
        return showRelease(
          latest,
          `https://github.com/${GITHUB_REPO}/releases/tag/v${latest}`,
          update,
        );
      }
      if (options.manual) {
        setNewRelease(null);
        setUpdateAvailable(null);
      }
      return { status: "up-to-date", current: desktopVersion };
    } catch (updaterError) {
      try {
        const res = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/releases/latest`, {
          signal: AbortSignal.timeout(4000),
          headers: { Accept: "application/vnd.github.v3+json" },
        });
        if (!res.ok) throw new Error(`GitHub HTTP ${res.status}`);
        const data = await res.json();
        const tagName = (data.tag_name || "").replace(/^v/, "");
        if (tagName && compareSemver(tagName, desktopVersion) > 0) {
          const latest = normalizeReleaseVersion(tagName);
          return showRelease(
            latest,
            data.html_url || `https://github.com/${GITHUB_REPO}/releases`,
            null,
          );
        }
        if (options.manual) {
          setNewRelease(null);
          setUpdateAvailable(null);
        }
        return { status: "up-to-date", current: desktopVersion };
      } catch (fallbackError) {
        const updaterMessage = updaterError instanceof Error
          ? updaterError.message
          : String(updaterError);
        const fallbackMessage = fallbackError instanceof Error
          ? fallbackError.message
          : String(fallbackError);
        return {
          status: "error",
          error: fallbackMessage || updaterMessage,
        };
      }
    }
  }, [desktopVersion]);

  const skipReleaseVersion = useCallback((version: string) => {
    const normalized = normalizeReleaseVersion(version);
    if (!normalized) return;
    setStoredValue(localStorage, SKIPPED_RELEASE_KEY, normalized);
    removeStoredValue(localStorage, LEGACY_DISMISSED_RELEASE_KEY);
    removeStoredValue(sessionStorage, REMIND_LATER_RELEASE_KEY);
    setNewRelease(null);
    setUpdateAvailable(null);
    setUpdateProgress({ status: "idle" });
  }, []);

  const remindReleaseLater = useCallback((version: string) => {
    const normalized = normalizeReleaseVersion(version);
    if (!normalized) return;
    setStoredValue(sessionStorage, REMIND_LATER_RELEASE_KEY, normalized);
    setNewRelease(null);
    setUpdateProgress({ status: "idle" });
  }, []);

  const doDownloadAndInstall = useCallback(async () => {
    if (!updateAvailable) return;
    setUpdateProgress({ status: "downloading", percent: 0 });
    try {
      let totalBytes = 0;
      let downloadedBytes = 0;
      await updateAvailable.downloadAndInstall((event) => {
        if (event.event === "Started" && event.data.contentLength) {
          totalBytes = event.data.contentLength;
        } else if (event.event === "Progress") {
          downloadedBytes += event.data.chunkLength;
          const percent = totalBytes > 0 ? Math.round((downloadedBytes / totalBytes) * 100) : 0;
          setUpdateProgress({ status: "downloading", percent });
        } else if (event.event === "Finished") {
          setUpdateProgress({ status: "installing" });
        }
      });
      setUpdateProgress({ status: "done" });
    } catch (err) {
      setUpdateProgress({ status: "error", error: String(err) });
    }
  }, [updateAvailable]);

  const doRelaunchAfterUpdate = useCallback(async () => {
    try {
      await relaunchApp();
    } catch {
      setUpdateProgress({ status: "error", error: "请手动重启应用以完成更新" });
    }
  }, []);

  return {
    desktopVersion,
    backendVersion, setBackendVersion,
    versionMismatch, setVersionMismatch,
    newRelease, setNewRelease,
    updateAvailable, setUpdateAvailable,
    updateProgress, setUpdateProgress,
    checkVersionMismatch,
    checkForAppUpdate,
    skipReleaseVersion,
    remindReleaseLater,
    doDownloadAndInstall,
    doRelaunchAfterUpdate,
  };
}
