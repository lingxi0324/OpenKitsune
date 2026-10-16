import { useEffect } from 'react';
import { IS_CAPACITOR } from '../platform';
import { safeFetchResponse } from '../providers';
import { desktopAccountHeaders } from './open';
import { getActiveServer } from '../platform/servers';
import { targetFetch, type Target } from './mobile';
import { getInstallTasks, INSTALL_TASK_REFRESH, isInstalling, patchInstall, pluginSetupState, trackInstall, type InstallJob } from './installTasks';

/** Mounted with the app shell, independently of installation dialogs. */
export function useInstallTaskMonitor(apiBaseUrl: string, discover: boolean) {
  useEffect(() => {
    let disposed = false;
    let running = false;
    let timer: ReturnType<typeof setTimeout>;
    let cycle = 0;
    const base = apiBaseUrl.replace(/\/+$/, '');
    const server = IS_CAPACITOR ? getActiveServer() : null;
    const target: Target | undefined = server ? { id: server.id, name: server.name,
      base: server.url.replace(/\/+$/, ''), state: '', expires: 0 } : undefined;
    const request = async (path: string) => {
      if (IS_CAPACITOR) {
        if (!target || target.base !== base) throw new Error('marketplace_target_changed');
        return targetFetch(target)(path);
      }
      return safeFetchResponse(base + path, { headers: await desktopAccountHeaders(), signal: AbortSignal.timeout(10_000) });
    };
    const poll = async () => {
      if (disposed || running) return;
      clearTimeout(timer);
      if (document.visibilityState === 'hidden') return;
      running = true;
      try {
        // Follow live installs, never reclassify installation history as new work.
        if (discover && cycle++ % 5 === 0) {
          try {
            const res = await request('/api/marketplace/installs');
            if (res.ok) {
              const body = await res.json();
              if (!disposed && Array.isArray(body.data)) for (const job of body.data as InstallJob[]) {
                if (job.status === 'ready') continue; // Confirmation stays with its initiating client.
                const known = getInstallTasks().find(t => t.base === base && t.job.id === job.id);
                if (!known && !isInstalling(job)) continue;
                const mobile = known?.mobile || (target ? { target, endpoint: '', jobId: job.id, key: `${base}#${job.id}` } : undefined);
                trackInstall(base, job, mobile, isInstalling(job));
              }
            }
          } catch { /* Older backends can still resume locally known job IDs. */ }
        }
        const tasks = getInstallTasks().filter(t => t.base === base);
        for (const task of tasks) {
          if (!isInstalling(task.job) && (!task.error || task.error === 'marketplace_install_not_found')) continue;
          try {
            const response = await request(`/api/marketplace/installs/${encodeURIComponent(task.job.id)}`);
            const body = await response.json();
            if (!response.ok) throw new Error(body?.detail?.code || 'marketplace_connection_failed');
            if (!disposed && body.data?.id === task.job.id) trackInstall(base, body.data, task.mobile);
          } catch (error) {
            if (!disposed) patchInstall(task.key, { error: error instanceof Error ? error.message : 'marketplace_connection_failed' });
          }
        }
        const plugins = getInstallTasks().filter(t => t.base === base && t.job.status === 'installed' && t.job.resource_type === 'plugin'
          && !['ready', 'keptDisabled'].includes(t.setup || 'checking'));
        if (plugins.length) {
          try {
            const response = await request('/api/plugins/list');
            if (!response.ok) throw new Error('marketplace_connection_failed');
            const body = await response.json();
            const list = body.data?.plugins ?? body.plugins;
            if (!Array.isArray(list)) throw new Error('marketplace_connection_failed');
            if (!disposed) for (const task of plugins) {
              const state = pluginSetupState(list.find(p => p.id === (task.job.plugin_id || task.job.resource_slug)));
              patchInstall(task.key, { setup: state === 'disabled' && task.setup === 'keptDisabled' ? 'keptDisabled' : state, error: undefined });
            }
          } catch {
            if (!disposed) for (const task of plugins) patchInstall(task.key, { error: 'marketplace_connection_failed' });
          }
        }
      } finally {
        running = false;
        if (!disposed) timer = setTimeout(poll, getInstallTasks().some(t => t.base === base && isInstalling(t.job)) ? 1500 : 6000);
      }
    };
    const wake = () => { cycle = 0; void poll(); };
    timer = setTimeout(poll, 500);
    window.addEventListener('focus', wake);
    window.addEventListener('online', wake);
    window.addEventListener(INSTALL_TASK_REFRESH, wake);
    document.addEventListener('visibilitychange', wake);
    return () => {
      disposed = true; clearTimeout(timer);
      window.removeEventListener('focus', wake);
      window.removeEventListener('online', wake);
      window.removeEventListener(INSTALL_TASK_REFRESH, wake);
      document.removeEventListener('visibilitychange', wake);
    };
  }, [apiBaseUrl, discover]);
}
