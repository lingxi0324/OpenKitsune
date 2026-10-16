import { useSyncExternalStore } from 'react';
import type { InstallationProgress } from '../components/MarketplaceInstallProgress';
import type { PendingInstall } from './mobile';

export type InstallJob = InstallationProgress & {
  id: string;
  status: 'ready' | 'downloading' | 'verifying' | 'installing' | 'installed' | 'failed' | 'cancelled';
  progress: number | null;
  resource_name: string;
  resource_type: 'plugin' | 'skill' | 'mcp';
  version: string;
  permissions: string[];
  dependencies: string[];
  failure_code?: string;
  failure_detail?: string;
  failure_reason?: string;
  failure_stage?: string;
  restart_required?: boolean;
  skill_enabled?: boolean;
  plugin_id?: string;
  resource_slug?: string;
  install_action?: 'install' | 'already_installed' | 'upgrade' | 'downgrade' | 'replace';
  installed_version?: string;
  installed_pending_restart?: boolean;
  already_installed?: boolean;
};
export type PluginSetupState = 'checking' | 'staged' | 'permissions' | 'disabled' | 'ready' | 'notLoaded' | 'keptDisabled';
export type InstallTask = {
  key: string;
  base: string;
  job: InstallJob;
  mobile?: PendingInstall;
  setup?: PluginSetupState;
  background: boolean;
  hidden: boolean;
  error?: string;
  notifiedPhase?: string;
  changedAt: number;
};
export const INSTALL_TASK_OPEN = 'openkitsune:install-task-open';
export const INSTALL_TASK_REFRESH = 'openkitsune:install-task-refresh';
const STORAGE = 'openkitsune.marketplace.tasks.v3';
const PREVIOUS_STORAGE = 'openkitsune.marketplace.tasks.v2';
const LEGACY_STORAGE = 'openkitsune.marketplace.tasks.v1';
const listeners = new Set<() => void>();
let snapshot: InstallTask[] = [];
let stored: string | null | undefined;
let memoryOnly = false;
const removed = new Set<string>();
const baseUrl = (base: string) => base.replace(/\/+$/, '');
export const taskKey = (base: string, id: string) => `${baseUrl(base)}#${id}`;
export const isInstalling = (job: InstallJob) => ['downloading', 'verifying', 'installing'].includes(job.status);
export function taskPhase(task: InstallTask): 'installing' | 'checking' | 'permissions' | 'setup' | 'failed' | 'complete' | 'paused' | 'ready' | 'cancelled' {
  if (task.job.status === 'failed') return 'failed';
  if (task.error) return 'paused';
  if (isInstalling(task.job)) return 'installing';
  if (task.job.status === 'installed') {
    if (task.job.resource_type === 'plugin') {
      if (!task.setup || task.setup === 'checking') return 'checking';
      if (task.setup === 'permissions') return 'permissions';
      if (!['ready', 'keptDisabled'].includes(task.setup)) return 'setup';
    }
    return 'complete';
  }
  if (task.job.status === 'ready' || task.job.status === 'cancelled') return task.job.status;
  return 'installing';
}
export function needsInstallAttention(task: InstallTask) {
  return ['permissions', 'setup', 'failed', 'paused'].includes(taskPhase(task));
}
/** This is a working set, not installation history. Completed resources belong
 * in their management views, including any permissions deferred before migration. */
export function currentInstallTasks(tasks: InstallTask[], base: string) {
  return tasks.filter(task => task.base === baseUrl(base) && !['complete', 'cancelled'].includes(taskPhase(task)));
}
export function getInstallTasks(): InstallTask[] {
  if (memoryOnly) return snapshot;
  try {
    let value = localStorage.getItem(STORAGE);
    if (value === null) {
      stored = undefined;
      const previous = localStorage.getItem(PREVIOUS_STORAGE);
      // v1 imported arbitrary historical jobs and cannot distinguish those from
      // genuinely followed installs. Preserve live work; never alter plugins.
      const legacy = JSON.parse(previous || localStorage.getItem(LEGACY_STORAGE) || '[]');
      const retained = Array.isArray(legacy) ? legacy.filter(task => task?.job &&
        (previous ? !['failed', 'cancelled', 'complete'].includes(taskPhase(task)) : isInstalling(task.job))) : [];
      value = JSON.stringify(retained.map(task => ({ ...task, hidden: false })));
      localStorage.setItem(STORAGE, value);
    }
    if (stored !== value) {
      stored = value;
      const parsed = JSON.parse(value || '[]');
      snapshot = Array.isArray(parsed) ? parsed.filter(t => t?.key && typeof t.base === 'string' && t.job?.id && t.job?.status) : [];
    }
  } catch { /* Keep an in-memory task list if storage is unavailable. */ }
  return snapshot;
}
function publish(next: InstallTask[]) {
  // Never evict unfinished tasks; retain a small recent history of finished ones.
  const completed = next.filter(t => ['complete', 'cancelled'].includes(taskPhase(t)))
    .sort((a, b) => b.changedAt - a.changedAt).slice(0, 20);
  snapshot = [...next.filter(t => !['complete', 'cancelled'].includes(taskPhase(t))), ...completed];
  // Failure notices belong to this page session, not a persistent history.
  // Keep live work and pending setup recoverable after reload.
  try {
    stored = JSON.stringify(snapshot.filter(task => task.job.status !== 'failed' &&
      !['complete', 'cancelled'].includes(taskPhase(task))));
    localStorage.setItem(STORAGE, stored);
  } catch { memoryOnly = true; }
  listeners.forEach(listener => listener());
}
export function useInstallTasks() {
  return useSyncExternalStore(subscribe, getInstallTasks, getInstallTasks);
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  const sync = (event: StorageEvent) => { if (event.key === STORAGE || event.key === null) listener(); };
  window.addEventListener('storage', sync);
  return () => { listeners.delete(listener); window.removeEventListener('storage', sync); };
}
export function trackInstall(base: string, job: InstallJob, mobile?: PendingInstall, background = false) {
  const all = getInstallTasks();
  const key = taskKey(base, job.id);
  const previous = all.find(t => t.key === key);
  const task: InstallTask = previous ? { ...previous, job, error: undefined, mobile: mobile || previous.mobile }
    : { key, base: baseUrl(base), job, mobile, background, hidden: false, changedAt: Date.now() };
  if (previous?.job.status !== job.status) task.changedAt = Date.now();
  // The instruction token is one-use and is never needed to resume a known job.
  if (task.mobile) task.mobile = { ...task.mobile, token: undefined, jobId: job.id };
  // Preserve the return contract without publishing a dismissed poll result.
  if (removed.has(key)) return task;
  publish([...all.filter(t => t.key !== key), task]);
  return task;
}
export function removeFailedInstall(key: string) {
  const all = getInstallTasks();
  if (!all.some(task => task.key === key && task.job.status === 'failed')) return;
  removed.add(key); // Ignore an outstanding poll returning after dismissal.
  publish(all.filter(task => task.key !== key));
}
export function patchInstall(key: string, patch: Partial<Pick<InstallTask, 'hidden' | 'background' | 'setup' | 'error' | 'notifiedPhase'>>) {
  const all = getInstallTasks();
  const current = all.find(t => t.key === key);
  if (!current || Object.entries(patch).every(([k, value]) => current[k as keyof InstallTask] === value)) return;
  const next = { ...current, ...patch };
  if (taskPhase(next) !== taskPhase(current)) next.changedAt = Date.now();
  publish(all.map(t => t.key === key ? next : t));
}
export function openInstallTask(key?: string) {
  window.dispatchEvent(new CustomEvent(INSTALL_TASK_OPEN, { detail: { key } }));
}
export function pluginSetupState(plugin: { pending_update_revision?: string; pending_permissions?: string[]; enabled?: boolean; status?: string } | undefined): PluginSetupState {
  if (!plugin) return 'notLoaded';
  if (plugin.pending_update_revision) return 'staged';
  if (plugin.pending_permissions?.length) return 'permissions';
  if (plugin.enabled === false) return 'disabled';
  return plugin.status === 'loaded' ? 'ready' : 'notLoaded';
}
