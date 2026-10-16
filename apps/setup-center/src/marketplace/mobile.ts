import { getAccessToken } from '../platform/auth';
import { IS_CAPACITOR } from '../platform/detect';
import { getActiveServer } from '../platform/servers';
import { buildMarketplaceContextUrl, hasMarketplaceClientVersion, marketplaceOrigin } from './navigation';
import { getInstallTasks, taskKey } from './installTasks';

const KEY = 'openkitsune.marketplace.mobile.v1';
const TTL = 8 * 60 * 60_000;
export type Target = { id: string; base: string; name: string; state: string; expires: number };
export type PendingInstall = { target: Target; endpoint: string; token?: string; jobId?: string; dismissed?: boolean; key: string };
type Saved = { targets: Target[]; pending?: PendingInstall };
function read(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (saved && Array.isArray(saved.targets)) return saved;
  } catch { /* A cleared store requires opening the market again. */ }
  return { targets: [] };
}
function write(value: Saved) { localStorage.setItem(KEY, JSON.stringify(value)); }
function needsPendingRecovery(pending?: PendingInstall) {
  if (!pending || pending.dismissed) return false;
  const tracked = pending.jobId && getInstallTasks().find(t => t.key === taskKey(pending.target.base, pending.jobId!));
  return !tracked || tracked.job.status === 'ready';
}
export function pendingInstall() { return read().pending; }
export function saveInstall(value: PendingInstall) {
  const saved = read(); saved.pending = value; write(saved);
}
export function targetIsCurrent(target: Target) {
  const server = getActiveServer();
  return server?.id === target.id && server.url.replace(/\/+$/, '') === target.base;
}

/** Freeze both the address and its credential. Never use the global interceptor's
 * currently selected token for an older operation after a server switch. */
export function targetFetch(target: Target, timeout = 25_000) {
  if (!targetIsCurrent(target)) throw new Error('marketplace_target_changed');
  const token = getAccessToken();
  return async (path: string, init?: RequestInit) => {
    if (!targetIsCurrent(target)) throw new Error('marketplace_target_changed');
    const headers = new Headers(init?.headers);
    headers.set('Content-Type', 'application/json');
    // Explicit empty authorization also prevents interceptor credential injection.
    headers.set('Authorization', token ? `Bearer ${token}` : '');
    const response = await fetch(target.base + path, {
      ...init, headers, credentials: 'omit', redirect: 'error', cache: 'no-store',
      signal: AbortSignal.timeout(timeout),
    });
    if (!targetIsCurrent(target)) throw new Error('marketplace_target_changed');
    return response;
  };
}

function targetRequest(target: Target, timeout = 25_000) {
  const request = targetFetch(target, timeout);
  return async (path: string, init?: RequestInit) => {
    const response = await request(path, init);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error([401, 403].includes(response.status) ? 'marketplace_server_login_required'
      : body?.detail?.code || 'marketplace_connection_failed');
    return body;
  };
}

export function installRequest(target: Target) {
  const request = targetRequest(target);
  return async <T>(path: string, init?: RequestInit): Promise<T> => (await request(path, init)).data as T;
}

export function marketplaceOpenErrorKey(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  const known = ['marketplace_target_changed', 'marketplace_server_login_required',
    'marketplace_server_unavailable', 'marketplace_server_version_invalid',
    'marketplace_client_version_invalid', 'marketplace_browser_unavailable',
    'marketplace_native_unavailable'];
  return known.includes(code) ? `topbar.marketplaceErrors.${code}` : 'topbar.openMarketplaceFailed';
}

export function acceptMobileInstall(raw: string): PendingInstall | null {
  let url: URL;
  try { url = new URL(raw); } catch { return null; }
  const https = url.origin === marketplaceOrigin() && url.pathname === '/openkitsune/install';
  const scheme = url.protocol === 'com.openkitsune.marketplace:' && url.hostname === 'marketplace' && url.pathname === '/install';
  if (!https && !scheme) return null;
  if (url.search || url.username || url.password) throw new Error('marketplace_instruction_invalid');
  const query = new URLSearchParams(url.hash.slice(1));
  for (const key of ['token', 'state', 'endpoint']) {
    if (query.getAll(key).length !== 1) throw new Error('marketplace_instruction_invalid');
  }
  const token = query.get('token') || '';
  const endpoint = query.get('endpoint') || '';
  if (!/^[a-f0-9]{64}$/.test(token) || endpoint !== marketplaceOrigin()) throw new Error('marketplace_instruction_invalid');
  const saved = read();
  const target = saved.targets.find(t => t.state === query.get('state') && t.expires > Date.now());
  if (!target) throw new Error('marketplace_context_expired');
  const key = `${target.state}:${token}`;
  if (saved.pending?.key === key) return saved.pending;
  if (needsPendingRecovery(saved.pending)) throw new Error('marketplace_install_busy');
  const pending = { target, endpoint, token, key };
  saveInstall(pending);
  return pending;
}

export async function openMarketplace(version: string, next = '/') {
  if (!IS_CAPACITOR) {
    const url = new URL(buildMarketplaceContextUrl(version, next));
    const { openExternalUrl } = await import('../platform');
    return openExternalUrl(url.href);
  }
  const saved = read();
  if (needsPendingRecovery(saved.pending)) {
    window.dispatchEvent(new Event('openkitsune-marketplace-resume'));
    return;
  }
  const server = getActiveServer();
  if (!server) throw new Error('marketplace_target_changed');
  const target: Target = { id: server.id, base: server.url.replace(/\/+$/, ''), name: server.name,
    state: crypto.randomUUID(), expires: Date.now() + TTL };
  // Compatibility belongs to this backend, not to the app's one-time startup
  // version lookup (which can fail before a server is selected or connected).
  let health;
  try {
    health = await targetRequest(target, 8_000)('/api/health');
  } catch (error) {
    if (error instanceof Error && ['marketplace_target_changed', 'marketplace_server_login_required'].includes(error.message)) throw error;
    throw new Error('marketplace_server_unavailable');
  }
  if (typeof health?.version !== 'string' || !hasMarketplaceClientVersion(health.version)) {
    throw new Error('marketplace_server_version_invalid');
  }
  const url = new URL(buildMarketplaceContextUrl(health.version, next));
  let uri: string;
  try {
    const { NativeAuth } = await import('@openkitsune/native-auth');
    ({ uri } = await NativeAuth.getRedirectUri());
  } catch { throw new Error('marketplace_native_unavailable'); }
  if (!targetIsCurrent(target)) throw new Error('marketplace_target_changed');
  const latest = read();
  if (needsPendingRecovery(latest.pending)) {
    window.dispatchEvent(new Event('openkitsune-marketplace-resume'));
    return;
  }
  latest.targets = [...latest.targets.filter(t => t.expires > Date.now()).slice(-7), target];
  write(latest);
  // Release Android uses verified HTTPS; debug and iOS use an explicit scheme.
  url.searchParams.set('client', uri.startsWith('https:') ? 'android' : 'mobile');
  url.searchParams.set('state', target.state);
  try {
    const { Browser } = await import('@capacitor/browser');
    if (!targetIsCurrent(target)) throw new Error('marketplace_target_changed');
    await Browser.open({ url: url.href });
  } catch (error) {
    const latest = read();
    latest.targets = latest.targets.filter(t => t.state !== target.state);
    write(latest);
    if (error instanceof Error && error.message === 'marketplace_target_changed') throw error;
    throw new Error('marketplace_browser_unavailable');
  }
}
