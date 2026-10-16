import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { History } from "lucide-react";
import { safeFetch } from "../providers";

type ConflictSource = { origin?: string; plugin_source?: string; path?: string };
export type SkillConflict = {
  skill_id?: string;
  name?: string;
  action?: string;
  winner?: ConflictSource;
  shadowed?: ConflictSource;
  active?: ConflictSource | null;
};

/** Shared record state for the skill page's filter, cards and source dialog. */
export function useSkillConflicts(apiBaseUrl: string, enabled: boolean, onNewRecords?: (records: SkillConflict[]) => void) {
  const { t } = useTranslation();
  const [conflicts, setConflicts] = useState<SkillConflict[]>([]);
  const [busy, setBusy] = useState(false);
  const [busyVisible, setBusyVisible] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const seen = useRef<Set<string> | null>(null);
  const onNewRecordsRef = useRef(onNewRecords);
  onNewRecordsRef.current = onNewRecords;
  useEffect(() => {
    if (!busy) { setBusyVisible(false); return; }
    const timer = window.setTimeout(() => setBusyVisible(true), 200);
    return () => window.clearTimeout(timer);
  }, [busy]);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!enabled) return;
    const request = ++generation.current;
    const current = () => request === generation.current && !signal?.aborted;
    setBusy(true);
    try {
      const resp = await safeFetch(`${apiBaseUrl}/api/skills/conflicts`, { signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      if (current()) {
        const next: SkillConflict[] = Array.isArray(body.conflicts) ? body.conflicts : [];
        // Active metadata can change independently of the historical load event.
        const key = ({ active: _active, ...record }: SkillConflict) => JSON.stringify(record);
        const newRecords = seen.current ? next.filter(record => !seen.current!.has(key(record))) : [];
        seen.current = new Set(next.map(key));
        setConflicts(next);
        setLoaded(true); setError("");
        if (newRecords.length) onNewRecordsRef.current?.(newRecords);
      }
    } catch {
      if (current()) setError(t("status.skillConflicts.refreshFailed"));
    } finally { if (current()) setBusy(false); }
  }, [apiBaseUrl, enabled, t]);
  useEffect(() => {
    const controller = new AbortController();
    seen.current = null;
    setConflicts([]); setError(""); setBusy(false); setLoaded(false); setBusyVisible(false);
    void refresh(controller.signal);
    const onChange = () => void refresh(controller.signal);
    const onFocus = () => { if (!document.hidden) onChange(); };
    window.addEventListener("openkitsune:skills-changed", onChange);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      generation.current++;
      controller.abort();
      window.removeEventListener("openkitsune:skills-changed", onChange);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [refresh]);
  async function clear() {
    const request = ++generation.current;
    setBusy(true);
    try {
      const resp = await safeFetch(`${apiBaseUrl}/api/skills/conflicts/clear`, { method: "POST" });
      const body = await resp.json();
      if (!resp.ok || !body.ok) throw new Error();
      if (request === generation.current) { seen.current = new Set(); setConflicts([]); setLoaded(true); setError(""); }
    } catch { if (request === generation.current) setError(t("status.skillConflicts.clearFailed")); }
    finally { if (request === generation.current) setBusy(false); }
  }
  return { conflicts, busy, busyVisible: busy && busyVisible, loaded, error, refresh, clear };
}

export function SkillConflictsPanel({ conflicts, showEmpty = true }: { conflicts: SkillConflict[]; showEmpty?: boolean }) {
  const { t } = useTranslation();
  if (!conflicts.length) {
    return showEmpty ? (
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-8 text-center">
        <History size={40} className="mb-3 shrink-0 text-muted-foreground/30" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">{t("status.skillConflicts.empty")}</p>
      </div>
    ) : null;
  }
  const source = (s?: ConflictSource) => s ? [
    s.origin ? t(`status.skillConflicts.origin.${s.origin}`, { defaultValue: s.origin }) : "",
    s.plugin_source, s.path,
  ].filter(Boolean).join(" · ") || "—" : "—";
  return <div className="shrink-0 space-y-3 text-sm">
    {[...conflicts].reverse().map((c, i) => <div key={i} className="rounded-md border border-border p-3 space-y-2 break-all">
      <p className="font-medium">{c.name || c.skill_id}</p>
      {c.active !== undefined && <p>{c.active ? t("status.skillConflicts.activeSource", { source: source(c.active) }) : t("status.skillConflicts.notLoaded")}</p>}
      {c.active === undefined && <p>{t("status.skillConflicts.currentSource", { source: source(c.winner) })}</p>}
      <details className="text-muted-foreground">
        <summary className="cursor-pointer">{t("status.skillConflicts.loadDetails")}</summary>
        <div className="mt-2 space-y-2">
          <p>{t(c.action === "overridden" ? "status.skillConflicts.actionOverridden" : "status.skillConflicts.actionRejected")}</p>
          {c.active !== undefined && <p>{t("status.skillConflicts.currentSource", { source: source(c.winner) })}</p>}
          <p>{t("status.skillConflicts.shadowedSource", { source: source(c.shadowed) })}</p>
        </div>
      </details>
    </div>)}
  </div>;
}
