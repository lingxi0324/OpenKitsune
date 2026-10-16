import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, ShieldCheck } from "lucide-react";
import { Button } from "./ui/button";
import { safeFetchResponse } from "../providers";
import { decodeRuntimeOperationResponse } from "../utils/runtimeOperation";
import { permLabel } from "../plugins/permissions";
import { pluginSetupState, type PluginSetupState } from '../marketplace/installTasks';

interface InstalledPlugin {
  id: string;
  status: string;
  enabled?: boolean;
  pending_permissions?: string[];
  pending_update_revision?: string;
  error?: string;
}

export function MarketplacePluginSetup({ apiBaseUrl, pluginId, onBusyChange, onClose, onStateChange, request: boundRequest }: {
  apiBaseUrl: string;
  pluginId: string;
  onBusyChange: (busy: boolean) => void;
  onClose: () => void;
  onStateChange?: (state: PluginSetupState) => void;
  request?: (path: string, init?: RequestInit) => Promise<Response>;
}) {
  const { t, i18n } = useTranslation();
  const [plugin, setPlugin] = useState<InstalledPlugin | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const mounted = useRef(false);
  const operation = useRef(false);
  const fallback = t("marketplaceInstall.pluginSetup.failed");
  const request = useCallback((path: string, init?: RequestInit) => boundRequest
    ? boundRequest(path, init) : safeFetchResponse(apiBaseUrl + path, init), [apiBaseUrl, boundRequest]);
  const refresh = useCallback(async () => {
    if (!pluginId) throw new Error(fallback);
    const response = await request('/api/plugins/list');
    if (!response.ok) throw new Error(fallback);
    const body = await response.json();
    const current = (body.data?.plugins ?? body.plugins)?.find((p: InstalledPlugin) => p.id === pluginId);
    if (!current) throw new Error(fallback);
    if (mounted.current) setPlugin(current);
  }, [request, pluginId, fallback]);

  useEffect(() => {
    mounted.current = true;
    setBusy(true);
    setPlugin(null);
    setError("");
    void refresh().catch(() => { if (mounted.current) setError(fallback); })
      .finally(() => { if (mounted.current) setBusy(false); });
    return () => { mounted.current = false; };
  }, [refresh, fallback]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  useEffect(() => () => onBusyChange(false), [onBusyChange]);

  async function act(action: "grant" | "enable" | "reload" | "check") {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (action !== "check") {
        if (action === "reload" && plugin?.pending_update_revision && plugin.enabled === false) {
          // Applying an update reloads the runtime. For a disabled plugin this
          // needs the explicit "enable and apply" choice shown below.
          const enable = await request(`/api/plugins/${encodeURIComponent(pluginId)}/_admin/enable`, {
            method: "POST", signal: AbortSignal.timeout(120_000),
          });
          const enabled = await decodeRuntimeOperationResponse(enable, fallback);
          if (!enable.ok || enabled.failure) throw new Error(enabled.failure || fallback);
        }
        const response = await request(`/api/plugins/${encodeURIComponent(pluginId)}/_admin/${action === "grant" ? "permissions/grant" : action}`, {
          method: "POST",
          signal: AbortSignal.timeout(120_000),
          headers: { "Content-Type": "application/json" },
          ...(action === "grant" ? { body: JSON.stringify({
            permissions: plugin?.pending_permissions ?? [],
            // Preserve a user's disabled state until they explicitly enable it.
            reload: plugin?.enabled !== false,
          }) } : {}),
        });
        const result = await decodeRuntimeOperationResponse(response, fallback);
        if (!response.ok || result.failure) throw new Error(result.failure || fallback);
        if (mounted.current) setNotice(result.notice || "");
      }
      // Reload can return HTTP 200 even when plugin loading failed. Inspect the
      // actual runtime state instead of assuming that the plugin is ready.
      await refresh();
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : fallback);
    } finally {
      if (action !== "check") {
        window.dispatchEvent(new CustomEvent("openkitsune:plugin-apps-changed"));
        window.dispatchEvent(new CustomEvent("openkitsune:plugin-reloaded", { detail: { pluginId } }));
      }
      operation.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  const pending = plugin?.pending_permissions ?? [];
  // A staged upgrade still exposes the old manifest. Apply it before asking
  // for permissions so the user authorizes the version they just installed.
  const staged = !!plugin?.pending_update_revision;
  const disabled = plugin?.enabled === false;
  const ready = !!plugin && !staged && !pending.length && !disabled && plugin.status === "loaded";
  const state = staged ? "staged" : pending.length ? "permissions" : disabled ? "disabled" : ready ? "ready" : "notLoaded";
  const primary = !plugin || error ? "check" : staged ? "reload" : pending.length ? "grant" : disabled ? "enable" : "reload";
  const label = { check: "retry", reload: staged ? disabled ? "enableUpdate" : "applyUpdate" : "load", grant: "grant", enable: "enable" }[primary];
  useEffect(() => {
    if (!busy) onStateChange?.(error || notice ? 'notLoaded' : pluginSetupState(plugin || undefined));
  }, [busy, plugin, error, notice, onStateChange]);

  return <div className="space-y-4">
    {busy ? <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 shrink-0 animate-spin" />{t("marketplaceInstall.pluginSetup.working")}
    </div> : plugin && <div role="status" className={`rounded-lg border p-3 text-sm ${ready && !error && !notice ? "border-emerald-200 text-emerald-700 dark:text-emerald-300" : "bg-muted/30"}`}>
      {t(`marketplaceInstall.pluginSetup.${state}`)}
    </div>}
    {!staged && pending.length > 0 && <ul className="max-h-48 space-y-2 overflow-y-auto text-sm" aria-label={t("marketplaceInstall.permissions")}>
      {pending.map(permission => <li key={permission} className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span>{permLabel(permission, i18n.language)}<span className="ml-2 text-xs text-muted-foreground">{permission}</span></span>
      </li>)}
    </ul>}
    {(error || notice || plugin?.error) && <p role="alert" className="break-words text-sm text-destructive">{error || notice || plugin?.error}</p>}
    <div className="flex justify-end gap-2">
      {!busy && disabled && !staged && !pending.length && onStateChange && <Button variant="outline" onClick={() => {
        onStateChange('keptDisabled'); onClose();
      }}>{t('marketplaceInstall.tasks.keepDisabled')}</Button>}
      <Button variant="outline" disabled={busy} onClick={onClose}>{t(ready && !error && !notice ? "marketplaceInstall.pluginSetup.done" : "marketplaceInstall.pluginSetup.later")}</Button>
      {!busy && (!ready || !!error) && <Button onClick={() => void act(primary)}>{t(`marketplaceInstall.pluginSetup.${label}`)}</Button>}
    </div>
  </div>;
}
