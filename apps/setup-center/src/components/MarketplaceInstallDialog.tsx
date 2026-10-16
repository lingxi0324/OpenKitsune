import { MarketplacePluginSetup } from "./MarketplacePluginSetup";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AlertCircle, CheckCircle2, Download, Loader2, PackageCheck, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MarketplaceInstallProgress } from "./MarketplaceInstallProgress";
import { MarketplaceTaskEntry, MarketplaceTaskList } from './MarketplaceTaskEntry';
import { useInstallTaskMonitor } from '../marketplace/useInstallTaskMonitor';
import { currentInstallTasks, getInstallTasks, isInstalling, INSTALL_TASK_OPEN, INSTALL_TASK_REFRESH, openInstallTask, patchInstall, removeFailedInstall, taskKey, taskPhase, trackInstall, useInstallTasks, type InstallTask, type InstallJob, type PluginSetupState } from '../marketplace/installTasks';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { getCurrentDeepLinks, IS_TAURI, IS_CAPACITOR, onDeepLinkOpen } from "../platform";
import { desktopAccountHeaders, openMarketplaceWithAccount } from "../marketplace/open";
import { safeFetchResponse } from "../providers";
import {
  buildMarketplaceContextUrlFromDeepLink,
  hasMarketplaceClientVersion,
  marketplaceDeepLinkAction,
} from "../marketplace/navigation";

import { acceptMobileInstall, installRequest, pendingInstall, saveInstall, openMarketplace, marketplaceOpenErrorKey, targetFetch, targetIsCurrent, type PendingInstall } from '../marketplace/mobile';
import { captureWebInstallReturn, dismissWebInstall, enqueueWebInstall, pendingWebInstall, saveWebInstallJob } from '../marketplace/web';
import { webInstallRelay, WEB_INSTALL_ARRIVED } from '../marketplace/webRelay';

type ParsedLink = { token: string; endpoint: string };

function parseInstallLink(value: string): ParsedLink | null {
  try {
    const url = new URL(value);
    const token = (url.searchParams.get("token") || "").toLowerCase();
    const endpoint = url.searchParams.get("endpoint") || "";
    if (url.protocol !== "openkitsune:" || url.hostname !== "marketplace" || url.pathname !== "/install") return null;
    if (!/^[a-f0-9]{64}$/.test(token) || !endpoint) return null;
    const source = new URL(endpoint);
    const local = source.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(source.hostname);
    if (source.protocol !== "https:" && !local) return null;
    if (source.username || source.password || source.search || source.hash || (source.pathname !== "/" && source.pathname !== "")) return null;
    return { token, endpoint: source.origin };
  } catch {
    return null;
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await safeFetchResponse(url, { ...init, headers: { "Content-Type": "application/json", ...await desktopAccountHeaders(), ...(init?.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload?.detail?.code
      || ([401, 403].includes(response.status) ? "marketplace_account_required" : "marketplace_connection_failed");
    throw new Error(code);
  }
  return payload.data as T;
}

export function MarketplaceInstallDialog({
  apiBaseUrl,
  desktopVersion,
  onManageServers,
  discoverTasks = false,
}: {
  apiBaseUrl: string;
  desktopVersion: string;
  onManageServers?: () => void;
  discoverTasks?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [compactViewport, setCompactViewport] = useState(() => window.innerWidth <= 768);
  useEffect(() => {
    const resize = () => setCompactViewport(window.innerWidth <= 768);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const [selectedBase, setSelectedBase] = useState(apiBaseUrl.replace(/\/+$/, ''));
  const tasks = useInstallTasks();
  useInstallTaskMonitor(apiBaseUrl, discoverTasks);
  const [loading, setLoading] = useState(false);
  const notifiedInstalls = useRef(new Set<string>());
  const [pluginBusy, setPluginBusy] = useState(false);
  const [job, setJob] = useState<InstallJob | null>(null);
  const [errorCode, setErrorCode] = useState("");
  const recentlyHandled = useRef(new Map<string, number>());
  const pendingOpenLinks = useRef(new Set<string>());
  const mobile = useRef<PendingInstall | undefined>(undefined);
  const loadingMobile = useRef(false);
  const mounted = useRef(true);
  const [acting, setActing] = useState(false);
  const [accountLabel, setAccountLabel] = useState('');
  const selectedTask = job ? tasks.find(task => task.key === taskKey(selectedBase, job.id)) : undefined;
  const currentTasks = tasks.filter(task => task.base === apiBaseUrl.replace(/\/+$/, ''));
  const saveJob = useCallback((next: InstallJob, base = apiBaseUrl, pending = mobile.current) => {
    trackInstall(base, next, pending);
    setSelectedBase(base.replace(/\/+$/, ''));
    setJob(next);
    window.dispatchEvent(new Event(INSTALL_TASK_REFRESH));
  }, [apiBaseUrl]);
  const requestPlugin = useCallback((path: string, init?: RequestInit) => {
    if (!mobile.current) throw new Error('marketplace_context_expired');
    return targetFetch(mobile.current.target, 120_000)(path, init);
  }, []);
  const requestJob = useCallback(<T,>(path: string, init?: RequestInit): Promise<T> => {
    if (selectedBase !== apiBaseUrl.replace(/\/+$/, '')) throw new Error('marketplace_target_changed');
    if (IS_CAPACITOR) {
      if (!mobile.current) throw new Error('marketplace_context_expired');
      return installRequest(mobile.current.target)<T>(path, init);
    }
    return requestJson<T>(apiBaseUrl + path, init);
  }, [apiBaseUrl, selectedBase]);

  const webRequest = useRef<{ key: string; promise: Promise<InstallJob> } | null>(null);
  const restoreWeb = useCallback(async () => {
    if (IS_TAURI || IS_CAPACITOR) return;
    try {
      captureWebInstallReturn();
      const pending = pendingWebInstall(apiBaseUrl);
      if (!pending) return;
      const known = getInstallTasks().find(task => task.key === taskKey(apiBaseUrl, pending.jobId || ''));
      if (known && (known.background || known.hidden || ['complete', 'cancelled'].includes(taskPhase(known)))) return;
      setOpen(true); setLoading(true); setErrorCode('');
      const key = `${pending.state}:${pending.jobId || pending.token}`;
      if (webRequest.current?.key !== key) {
        const promise = pending.jobId
          ? requestJson<InstallJob>(`${apiBaseUrl}/api/marketplace/installs/${encodeURIComponent(pending.jobId)}`)
          : requestJson<InstallJob>(`${apiBaseUrl}/api/marketplace/installs/prepare`, {
            method: 'POST', body: JSON.stringify({ token: pending.token, endpoint: pending.endpoint }),
          });
        webRequest.current = { key, promise };
      }
      const prepared = await webRequest.current.promise;
      if (pending.jobId && !known && prepared.status === 'failed') {
        // A stale recovery pointer must not re-import a previous failed install.
        dismissWebInstall(); setOpen(false); return;
      }
      saveWebInstallJob(pending, prepared.id);
      if (mounted.current) saveJob(prepared, apiBaseUrl, undefined);
    } catch (error) {
      webRequest.current = null;
      if (mounted.current) {
        setOpen(true);
        setErrorCode(error instanceof Error ? error.message : 'marketplace_connection_failed');
      }
    } finally { if (mounted.current) setLoading(false); }
  }, [apiBaseUrl, saveJob]);

  useEffect(() => {
    if (IS_TAURI || IS_CAPACITOR) return;
    void restoreWeb();
    const stopRelay = webInstallRelay()?.listen(() => apiBaseUrl.replace(/\/+$/, ''), enqueueWebInstall);
    const arrived = () => { void restoreWeb(); };
    const resume = () => { if (location.hash.startsWith('#openkitsune-install=')) void restoreWeb(); };
    window.addEventListener('hashchange', resume);
    window.addEventListener('pageshow', resume);
    window.addEventListener(WEB_INSTALL_ARRIVED, arrived);
    return () => { stopRelay?.(); window.removeEventListener(WEB_INSTALL_ARRIVED, arrived); window.removeEventListener('hashchange', resume); window.removeEventListener('pageshow', resume); };
  }, [restoreWeb]);

  const restoreMobile = useCallback(async (pending: PendingInstall, reveal = true, recoverOnly = false) => {
    if (pending.dismissed || loadingMobile.current) return;
    loadingMobile.current = true;
    mobile.current = pending;
    setOpen(reveal); setLoading(true); setErrorCode(''); setJob(null); setAccountLabel('');
    try {
      const request = installRequest(pending.target);
      const prepared = pending.jobId
        ? await request<InstallJob>(`/api/marketplace/installs/${encodeURIComponent(pending.jobId)}`)
        : await request<InstallJob>('/api/marketplace/installs/prepare', {
          method: 'POST', body: JSON.stringify({ token: pending.token, endpoint: pending.endpoint }),
        });
      const known = getInstallTasks().find(task => task.key === taskKey(pending.target.base, prepared.id));
      if (recoverOnly && pending.jobId && !known && !isInstalling(prepared)) {
        // The old single-pending pointer can refer to an installation from days
        // ago. Do not bypass working-set migration through this recovery path.
        if (pendingInstall()?.key === pending.key) saveInstall({ ...pending, dismissed: true });
        setOpen(false);
        return;
      }
      const saved = { ...pending, jobId: prepared.id, token: undefined };
      saveInstall(saved); mobile.current = saved;
      if (mounted.current) {
        saveJob(prepared, pending.target.base, saved);
        if (recoverOnly && pending.jobId && !known) patchInstall(taskKey(pending.target.base, prepared.id), { background: true });
      }
    } catch (error) {
      if (mounted.current) setErrorCode(error instanceof Error ? error.message : 'marketplace_connection_failed');
      if (error instanceof Error && error.message === 'marketplace_account_mismatch') {
        try {
          const { readNativeAccountStatus } = await import('../platform/nativeAccountAuth');
          const account = await readNativeAccountStatus(pending.target.base);
          if (mounted.current) setAccountLabel(account.profile?.email || account.profile?.name || '');
        } catch { /* The original authorization error remains visible. */ }
      }
    } finally {
      loadingMobile.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [saveJob]);

  useEffect(() => {
    mounted.current = true;
    if (!IS_CAPACITOR) return () => { mounted.current = false; };
    const resume = () => {
      const pending = pendingInstall();
      if (pending && !pending.dismissed) void restoreMobile(pending);
    };
    const initial = pendingInstall();
    if (initial && !initial.dismissed) {
      const tracked = initial.jobId && getInstallTasks().find(task => task.key === taskKey(initial.target.base, initial.jobId!));
      void restoreMobile(initial, (!initial.jobId && !tracked) || (!!tracked && !tracked.background && !tracked.hidden && !['complete', 'cancelled'].includes(taskPhase(tracked))), true);
    }
    window.addEventListener('openkitsune-marketplace-resume', resume);
    return () => { mounted.current = false; window.removeEventListener('openkitsune-marketplace-resume', resume); };
  }, [restoreMobile]);

  const friendlyError = useCallback((code: string) => t(`marketplaceInstall.errors.${code}`, {
    defaultValue: t("marketplaceInstall.errors.marketplace_install_failed"),
  }), [t]);

  const prepare = useCallback(async (raw: string) => {
    if (!IS_TAURI) return;
    const parsed = parseInstallLink(raw);
    setOpen(true);
    setJob(null);
    setErrorCode("");
    if (!parsed) {
      setErrorCode("marketplace_instruction_invalid");
      return;
    }
    setLoading(true);
    const deadline = Date.now() + 120_000;
    while (Date.now() < deadline) {
      try {
        const prepared = await requestJson<InstallJob>(`${apiBaseUrl}/api/marketplace/installs/prepare`, {
          method: "POST", body: JSON.stringify(parsed),
        });
        saveJob(prepared, apiBaseUrl, undefined);
        setLoading(false);
        return;
      } catch (error) {
        const code = error instanceof Error ? error.message : "marketplace_connection_failed";
        if (code !== "marketplace_connection_failed") {
          setErrorCode(code);
          setLoading(false);
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
      }
    }
    setErrorCode("marketplace_connection_failed");
    setLoading(false);
  }, [apiBaseUrl, saveJob]);

  const handleDeepLink = useCallback((raw: string) => {
    if (IS_CAPACITOR) {
      try {
        const pending = acceptMobileInstall(raw);
        if (pending && !pending.dismissed) {
          void import('@capacitor/browser').then(({ Browser }) => Browser.close()).catch(() => {});
          void restoreMobile(pending);
        }
      } catch (error) { toast.error(friendlyError(error instanceof Error ? error.message : 'marketplace_instruction_invalid')); }
      return;
    }
    const action = marketplaceDeepLinkAction(raw);
    if (action === "open" && !hasMarketplaceClientVersion(desktopVersion)) {
      pendingOpenLinks.current.add(raw);
      return;
    }

    const now = Date.now();
    const previous = recentlyHandled.current.get(raw) || 0;
    if (now - previous < 1_500) return;
    recentlyHandled.current.set(raw, now);
    if (recentlyHandled.current.size > 100) {
      for (const [value, timestamp] of recentlyHandled.current) {
        if (now - timestamp >= 1_500) recentlyHandled.current.delete(value);
      }
    }

    if (action === "install") {
      void prepare(raw);
      return;
    }
    if (action !== "open") return;

    const target = buildMarketplaceContextUrlFromDeepLink(raw, desktopVersion);
    if (!target) {
      toast.error(t("marketplaceInstall.openLinkInvalid"));
      return;
    }
    const context = new URL(target);
    void openMarketplaceWithAccount(desktopVersion, apiBaseUrl, context.searchParams.get("next") || "/", context.origin).catch(() => {
      toast.error(t("marketplaceInstall.openFailed"));
    });
  }, [desktopVersion, apiBaseUrl, prepare, restoreMobile, friendlyError, t]);

  useEffect(() => {
    if (!IS_TAURI && !IS_CAPACITOR) return;
    let disposed = false;
    let cleanup = () => {};
    void getCurrentDeepLinks().then((urls) => { if (!disposed) urls.forEach(handleDeepLink); }).catch(() => {});
    void onDeepLinkOpen((urls) => urls.forEach(handleDeepLink)).then((unlisten) => {
      if (disposed) unlisten(); else cleanup = unlisten;
    }).catch(() => {});
    return () => { disposed = true; cleanup(); };
  }, [handleDeepLink]);

  useEffect(() => {
    if (!hasMarketplaceClientVersion(desktopVersion)) return;
    const pending = [...pendingOpenLinks.current];
    pendingOpenLinks.current.clear();
    pending.forEach(handleDeepLink);
  }, [desktopVersion, handleDeepLink]);

  useEffect(() => {
    if (!selectedTask) return;
    setJob(selectedTask.job);
    setErrorCode(previous => selectedTask.base !== apiBaseUrl.replace(/\/+$/, '')
      ? 'marketplace_target_changed' : selectedTask.error ||
        (['marketplace_connection_failed', 'marketplace_target_changed'].includes(previous) ? '' : previous));
  }, [selectedTask, apiBaseUrl]);

  const selectTask = useCallback((task: InstallTask) => {
    setPanelOpen(false);
    setSelectedBase(task.base);
    mobile.current = task.mobile;
    setJob(task.job);
    setLoading(false);
    setOpen(true);
    setErrorCode(task.base !== apiBaseUrl.replace(/\/+$/, '') ? 'marketplace_target_changed' : task.error || '');
    window.dispatchEvent(new Event(INSTALL_TASK_REFRESH));
  }, [apiBaseUrl]);

  const removeFailedTask = useCallback((task: InstallTask) => {
    if (task.job.status !== 'failed') return;
    removeFailedInstall(task.key);
    if (task.mobile && pendingInstall()?.key === task.mobile.key) saveInstall({ ...task.mobile, dismissed: true });
    if (!IS_TAURI && !IS_CAPACITOR) {
      try { if (pendingWebInstall(apiBaseUrl)?.jobId === task.job.id) dismissWebInstall(); } catch { /* No matching recovery pointer. */ }
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    const restore = (event: Event) => {
      const key = (event as CustomEvent).detail?.key;
      const task = getInstallTasks().find(task => task.key === key);
      if (task) selectTask(task);
      else { setOpen(false); setPanelOpen(true); }
    };
    window.addEventListener(INSTALL_TASK_OPEN, restore);
    return () => window.removeEventListener(INSTALL_TASK_OPEN, restore);
  }, [selectTask]);

  const updateSetup = useCallback((setup: PluginSetupState) => {
    if (job) patchInstall(taskKey(selectedBase, job.id), { setup, error: undefined });
  }, [selectedBase, job?.id]);

  useEffect(() => {
    for (const task of currentTasks) {
      if (task.job.status === 'installed') {
        const key = `${task.key}/resource-refresh`;
        if (!notifiedInstalls.current.has(key)) {
          notifiedInstalls.current.add(key);
          window.dispatchEvent(new CustomEvent({ skill: 'openkitsune:skills-changed', plugin: 'openkitsune:plugin-apps-changed', mcp: 'openkitsune:mcp-changed' }[task.job.resource_type], { detail: { action: 'install' } }));
        }
      }
      const phase = taskPhase(task);
      if (!task.background || task.notifiedPhase === phase || !['complete', 'permissions', 'setup', 'failed'].includes(phase)) continue;
      patchInstall(task.key, { notifiedPhase: phase });
      toast(t(phase === 'complete' ? 'marketplaceInstall.tasks.completedNotice' : 'marketplaceInstall.tasks.attentionNotice', {
        name: task.job.resource_name, status: t(`marketplaceInstall.tasks.${phase}`),
      }), { action: { label: t('marketplaceInstall.tasks.details'), onClick: () => openInstallTask(task.key) } });
    }
  }, [currentTasks, t]);

  async function confirm() {
    if (!job || acting || selectedBase !== apiBaseUrl.replace(/\/+$/, '')) return;
    setActing(true);
    setErrorCode("");
    try {
      const next = await requestJob<InstallJob>(`/api/marketplace/installs/${encodeURIComponent(job.id)}/confirm`, { method: "POST" });
      saveJob(next);
      if (next.status === "ready") setErrorCode("marketplace_install_state_changed");
    } catch (error) {
      setErrorCode(error instanceof Error ? error.message : "marketplace_install_failed");
    } finally { setActing(false); }
  }

  const active = !!job && ["downloading", "verifying", "installing"].includes(job.status);
  const canInstall = job?.status === "ready" && job.install_action !== "downgrade";

  const close = useCallback(async () => {
    if (loading || acting || pluginBusy) return;
    const nextWebInstall = () => { if (!IS_TAURI && !IS_CAPACITOR) dismissWebInstall(); };
    const current = job;
    setOpen(false);
    if (current?.status === 'failed') {
      removeFailedInstall(taskKey(selectedBase, current.id));
      if (mobile.current && pendingInstall()?.key === mobile.current.key) saveInstall({ ...mobile.current, dismissed: true });
      nextWebInstall();
      return;
    }
    if (current && current.status !== 'ready') {
      const task = getInstallTasks().find(task => task.key === taskKey(selectedBase, current.id));
      const done = task && ['complete', 'cancelled'].includes(taskPhase(task));
      patchInstall(taskKey(selectedBase, current.id), done ? { background: false, hidden: true } : { background: true });
      if (done && mobile.current && pendingInstall()?.key === mobile.current.key) saveInstall({ ...mobile.current, dismissed: true });
      if (active) toast(t('marketplaceInstall.tasks.backgroundHint'));
      nextWebInstall();
      return;
    }
    if (mobile.current && pendingInstall()?.key === mobile.current.key) saveInstall({ ...mobile.current, dismissed: true });
    if (current?.status !== "ready") { nextWebInstall(); return; }
    try {
      saveJob(await requestJob<InstallJob>(`/api/marketplace/installs/${encodeURIComponent(current.id)}/cancel`, { method: "POST" }));
    } catch {
      // The local service persists the pending cancellation and retries delivery.
    }
    nextWebInstall();
  }, [active, requestJob, job, loading, acting, pluginBusy, selectedBase, saveJob, t]);

  const closeRef = useRef(() => {});
  closeRef.current = () => { if (open) void close(); else setPanelOpen(false); };
  const overlayOpen = open || panelOpen;
  useEffect(() => {
    if (!IS_CAPACITOR || !overlayOpen) return;
    let disposed = false;
    let remove: (() => void) | undefined;
    void import('@capacitor/app').then(({ App }) => App.addListener('backButton', () => closeRef.current()))
      .then(handle => { if (disposed) void handle.remove(); else remove = () => { void handle.remove(); }; }).catch(() => {});
    return () => { disposed = true; remove?.(); };
  }, [overlayOpen]);

  const pendingSetup = job?.status === 'installed' && job.resource_type === 'plugin' && selectedTask && taskPhase(selectedTask) !== 'complete';
  const statusLabel = pendingSetup ? t(`marketplaceInstall.tasks.${taskPhase(selectedTask)}`)
    : job ? t(`marketplaceInstall.status.${job.status}`) : "";
  let completionKey = job?.restart_required ? "completedRestart" : "completed";
  if (job?.resource_type === "skill") {
    if (job.skill_enabled === false) completionKey = "completedSkillDisabled";
    else if (job.skill_enabled === true) {
      completionKey = job.restart_required ? "completedSkillRestart" : "completedSkillEnabled";
    } else completionKey = "completedSkillUnknown";
  }
  if (job?.already_installed) completionKey = job.installed_pending_restart ? "alreadyInstalledPending" : "alreadyInstalled";

  return (<>
    <MarketplaceTaskEntry tasks={currentInstallTasks(tasks, apiBaseUrl)} onOpen={() => setPanelOpen(true)} />
    <Dialog open={panelOpen} onOpenChange={setPanelOpen} modal={compactViewport}>
      <DialogContent overlayClassName="z-[1100]" className="install-task-panel z-[1100]" onCloseAutoFocus={event => event.preventDefault()}>
        <button className="install-task-handle" aria-label={t('marketplaceInstall.tasks.collapse')}
          onClick={() => setPanelOpen(false)}
          onPointerDown={event => { event.currentTarget.dataset.startY = String(event.clientY); event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerUp={event => { if (event.clientY - Number(event.currentTarget.dataset.startY) > 40) setPanelOpen(false); }} />
        <DialogHeader><DialogTitle>{t('marketplaceInstall.tasks.title')}</DialogTitle>
          <DialogDescription>{t('marketplaceInstall.tasks.description')}</DialogDescription></DialogHeader>
        <MarketplaceTaskList tasks={currentInstallTasks(tasks, apiBaseUrl)} onSelect={selectTask} onRemove={removeFailedTask} />
      </DialogContent>
    </Dialog>
    <Dialog open={open} onOpenChange={(next) => { if (!next) void close(); }}>
      <DialogContent overlayClassName="z-[1100]" className="install-task-detail z-[1100] sm:max-w-[520px] max-h-[85dvh] overflow-y-auto" showCloseButton={!loading && !acting && !pluginBusy}>
        <button className="install-task-handle" aria-label={t('marketplaceInstall.tasks.collapse')} onClick={() => void close()}
          onPointerDown={event => { event.currentTarget.dataset.startY = String(event.clientY); event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerUp={event => { if (event.clientY - Number(event.currentTarget.dataset.startY) > 40) void close(); }} />
        <DialogHeader>
          <DialogTitle className="flex items-start gap-2 pr-6 text-left">
            {pendingSetup ? <ShieldCheck className="mt-0.5 shrink-0 text-amber-600" size={22} /> : job?.status === "installed" ? <CheckCircle2 className="mt-0.5 shrink-0 text-emerald-500" size={22} /> : <PackageCheck className="mt-0.5 shrink-0 text-blue-600" size={22} />}
            <span className="min-w-0 break-words">{t("marketplaceInstall.title")}</span>
          </DialogTitle>
          <DialogDescription>{job ? `${job.resource_name} · ${job.install_action === "upgrade" ? `v${job.installed_version} → ` : ""}v${job.version}` : t("marketplaceInstall.connecting")}</DialogDescription>
        </DialogHeader>
        {selectedTask?.background && <Button variant="ghost" size="sm" onClick={() => { if (!pluginBusy && !acting) { setOpen(false); setPanelOpen(true); } }}>{t('marketplaceInstall.tasks.backToList')}</Button>}

        {IS_CAPACITOR && mobile.current && <div className="rounded-md border p-3 text-sm break-all">
          <div className="text-muted-foreground">{t('marketplaceInstall.target')}</div>
          <strong>{mobile.current.target.name}</strong><div>{mobile.current.target.base}</div>
          {accountLabel && <div>{accountLabel}</div>}
        </div>}
        {!IS_TAURI && !IS_CAPACITOR && <div className="rounded-md border p-3 text-sm break-all">
          <div className="text-muted-foreground">{t('marketplaceInstall.target')}</div>
          <strong>{apiBaseUrl || location.origin}</strong>
        </div>}
        {loading && <div role="status" className="flex flex-col items-center gap-3 py-8 text-center text-sm text-muted-foreground"><Loader2 size={24} className="size-6 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />{t("marketplaceInstall.connecting")}</div>}

        {errorCode && <div className="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"><AlertCircle className="mt-0.5 shrink-0" size={18} /><span>{friendlyError(errorCode)}</span></div>}

        {job && !loading && <>
          <div className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-4 text-sm">
            <div><span className="block text-muted-foreground">{t("marketplaceInstall.type")}</span><strong>{t(`marketplaceInstall.types.${job.resource_type}`)}</strong></div>
            <div><span className="block text-muted-foreground">{t("marketplaceInstall.statusLabel")}</span><strong>{statusLabel}</strong></div>
          </div>

          {active && <MarketplaceInstallProgress job={job} />}

          {job.status === "ready" && ["upgrade", "downgrade", "replace"].includes(job.install_action || "") && <p className="text-sm text-muted-foreground">{t(`marketplaceInstall.${job.install_action}Hint`, { current: job.installed_version, target: job.version })}</p>}

          {canInstall && <div className="space-y-3"><div className="flex items-center gap-2 text-sm font-medium"><ShieldCheck size={18} className="text-emerald-600" />{t("marketplaceInstall.permissions")}</div>{job.permissions.length ? <div className="flex flex-wrap gap-2">{job.permissions.map((permission) => <span key={permission} className="rounded-md border bg-background px-2.5 py-1 text-xs">{permission}</span>)}</div> : <p className="text-sm text-muted-foreground">{t("marketplaceInstall.noPermissions")}</p>}</div>}

          {canInstall && job.dependencies.length > 0 && <div className="space-y-3"><div className="text-sm font-medium">{t("marketplaceInstall.dependencies")}</div><div className="flex flex-wrap gap-2">{job.dependencies.map((dependency) => <span key={dependency} className="rounded-md border bg-background px-2.5 py-1 text-xs">{dependency}</span>)}</div></div>}

          {canInstall && job.resource_type === "skill" && <p className="text-sm text-muted-foreground">{t("marketplaceInstall.skillActivationHint")}</p>}
          {job.status === "installed" && job.resource_type !== "plugin" && <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300">{t(`marketplaceInstall.${completionKey}`, { version: job.installed_version || job.version })}</div>}
          {job.status === "installed" && job.resource_type === "plugin" && job.already_installed && !job.installed_pending_restart && <p className="text-sm text-muted-foreground">{t("marketplaceInstall.alreadyInstalled", { version: job.installed_version || job.version })}</p>}
           {open && selectedBase === apiBaseUrl.replace(/\/+$/, '') && job.status === "installed" && job.resource_type === "plugin" && (!IS_CAPACITOR || (mobile.current && targetIsCurrent(mobile.current.target))) && <MarketplacePluginSetup
            key={`${apiBaseUrl}/${job.id}`}
             apiBaseUrl={apiBaseUrl} pluginId={job.plugin_id || job.resource_slug || ""}
             request={IS_CAPACITOR ? requestPlugin : undefined}
            onBusyChange={setPluginBusy} onClose={() => void close()} onStateChange={updateSetup}
          />}
          {job.status === "failed" && <div role="alert" className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
            <p className="font-medium">{t(`marketplaceInstall.failureReasons.${job.failure_reason || "unknown"}`, { defaultValue: friendlyError(job.failure_code || "marketplace_install_failed") })}</p>
            {(job.failure_stage || job.stage) && <p>{t("marketplaceInstall.failureStage", { stage: t(`marketplaceInstall.stages.${job.failure_stage || job.stage}`, { defaultValue: t("marketplaceInstall.status.installing") }) })}</p>}
            {job.current_dependency && <p>{t("marketplaceInstall.lastDependency", { name: job.current_dependency })}</p>}
            {job.failure_detail && <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-background/70 p-2 text-xs font-mono">{job.failure_detail}</pre>}
            <p>{t(job.failure_reason === "dependency_network" ? "marketplaceInstall.networkRetryHint" : "marketplaceInstall.failureRetryHint")}</p>
          </div>}
        </>}

        <DialogFooter>
          {IS_CAPACITOR && errorCode === 'marketplace_account_required' && !acting && <Button onClick={async () => {
            const pending = mobile.current;
            if (!pending) return;
            setActing(true);
            try {
              const { runNativeAccountLogin, readNativeAccountStatus } = await import('../platform/nativeAccountAuth');
              const { dispatchAccountStatusChanged } = await import('../utils/accountStatusEvents');
              await runNativeAccountLogin(pending.target.base);
              dispatchAccountStatusChanged(await readNativeAccountStatus(pending.target.base));
              await restoreMobile(pending);
            } catch { setErrorCode('marketplace_account_required'); }
            finally { setActing(false); }
          }}>{t('marketplaceInstall.loginAccount')}</Button>}
          {!loading && !acting && !pluginBusy && !(job?.status === "installed" && job.resource_type === "plugin") && <Button variant="outline" onClick={() => void close()}>{active ? t("marketplaceInstall.background") : job?.status === "installed" ? t("marketplaceInstall.pluginSetup.done") : job?.status === 'failed' ? t('marketplaceInstall.tasks.dismissFailure') : t("common.cancel")}</Button>}
          {job?.status === 'failed' && selectedBase === apiBaseUrl.replace(/\/+$/, '') && <Button onClick={async () => {
            await close();
            try { await openMarketplaceWithAccount(desktopVersion, apiBaseUrl); }
            catch (error) { toast.error(t(marketplaceOpenErrorKey(error))); }
          }}>{t('marketplaceInstall.backToMarket')}</Button>}
          {canInstall && <Button onClick={confirm} disabled={acting || loading || errorCode === "marketplace_target_changed"}><Download size={16} />{t(job.install_action === 'upgrade' ? 'marketplaceInstall.upgrade' : job.install_action === 'replace' ? 'marketplaceInstall.replace' : 'marketplaceInstall.install')}</Button>}
          {IS_CAPACITOR && errorCode && !loading && <Button variant="outline" onClick={() => { if (mobile.current) void restoreMobile(mobile.current); }}>{t('common.retry')}</Button>}
          {!IS_CAPACITOR && errorCode && !loading && <Button variant="outline" onClick={() => {
            if (!IS_TAURI && !job) void restoreWeb();
            else window.dispatchEvent(new Event(INSTALL_TASK_REFRESH));
          }}>{t('common.retry')}</Button>}
          {IS_CAPACITOR && ['marketplace_target_changed', 'marketplace_server_login_required'].includes(errorCode) && <Button onClick={onManageServers}>{t('marketplaceInstall.manageServers')}</Button>}
          {IS_CAPACITOR && ['marketplace_account_required', 'marketplace_account_mismatch', 'marketplace_instruction_unavailable', 'marketplace_install_not_found'].includes(errorCode) && <Button variant="outline" onClick={async () => {
            await close();
            try { await openMarketplace(desktopVersion); } catch (error) { toast.error(t(marketplaceOpenErrorKey(error))); }
          }}>{t('marketplaceInstall.backToMarket')}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>);
}
