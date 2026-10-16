import { buildMarketplaceContextUrl } from './navigation';
import { clearInheritedWebSources, webInstallRelay, WEB_INSTALL_ARRIVED } from './webRelay';

const KEY = 'openkitsune.marketplace.web.v1';
const ERROR_KEY = KEY + '.error';
const TTL = 30 * 60_000;
const QUEUE = KEY + '.queue';
const SESSIONS = KEY + '.session.';
export type WebInstallContext = {
  state: string; base: string; endpoint: string; returnUrl: string; expires: number;
  token?: string; jobId?: string; consumed?: boolean;
  relay?: boolean; delivered?: boolean;
  callbackUrl?: string;
};
function read(): WebInstallContext | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { return null; }
}
function write(value: WebInstallContext, storage = sessionStorage) { storage.setItem(KEY, JSON.stringify(value)); }
const baseUrl = (base: string) => new URL(base || location.origin, location.origin).href.replace(/\/+$/, '');

/** Navigation preserves the instance login in its own origin. No
 * instance credentials or API address are sent to the storefront. */
export function buildWebMarketplaceUrl(version: string, base: string, next = '/', origin?: string, storage = sessionStorage) {
  const page = new URL(location.href);
  if (!['https:', 'http:'].includes(page.protocol) || page.username || page.password) {
    throw new Error('marketplace_instruction_invalid');
  }
  // getRandomValues also works on LAN HTTP, where randomUUID is unavailable.
  const state = Array.from(crypto.getRandomValues(new Uint8Array(32)), b => b.toString(16).padStart(2, '0')).join('');
  const url = new URL(buildMarketplaceContextUrl(version, next, origin));
  const originalUrl = page.href;
  page.search = ''; page.hash = '';
  // A distinct, uncached shell avoids reusing an older cached /web/ document
  // when the market returns, even after the source tab was force-refreshed.
  page.pathname = page.pathname.replace(/\/+$/, '') + '/marketplace-return';
  write({ state, base: baseUrl(base), endpoint: url.origin, returnUrl: originalUrl,
    callbackUrl: page.href, expires: Date.now() + TTL }, storage);
  storage.removeItem(ERROR_KEY);
  url.searchParams.set('client', 'web');
  url.searchParams.set('state', state);
  url.searchParams.set('return_url', page.href);
  return url.href;
}

export function openWebMarketplace(version: string, next: string, origin: string | undefined, newTab: boolean) {
  // Web uses the page's service, even if a caller still holds native loopback
  // connection state. Keep validation on return strict; never rewrite old targets.
  const tab = newTab ? window.open('about:blank', '_blank') : null;
  if (!tab) {
    location.assign(buildWebMarketplaceUrl(version, location.origin, next, origin));
    return;
  }
  try {
    // Seed legacy return context while same-origin. Each market window also has
    // a separate direct-message session, so installs target its exact opener.
    const url = new URL(buildWebMarketplaceUrl(version, location.origin, next, origin, tab.sessionStorage));
    const context: WebInstallContext = JSON.parse(tab.sessionStorage.getItem(KEY)!);
    const relay = webInstallRelay();
    if (relay) {
      relay.register(context);
      relay.registerMarket(context, tab);
      write({ ...context, relay: true }, tab.sessionStorage);
    }
    // Only locally issued, expiring contexts can initialize an explicit fallback
    // in a new tab. No instance credentials or instruction tokens are stored here.
    try {
      for (const key of Object.keys(localStorage)) {
        if (!key.startsWith(SESSIONS)) continue;
        try { if (JSON.parse(localStorage.getItem(key)!).expires > Date.now()) continue; } catch { /* Expired/invalid. */ }
        localStorage.removeItem(key);
      }
      localStorage.setItem(SESSIONS + context.state, JSON.stringify(context));
      url.searchParams.set('channel', 'post-message');
    } catch { /* Storage denial retains the existing same-tab return flow. */ }
    clearInheritedWebSources(tab.sessionStorage);
    tab.sessionStorage.removeItem(QUEUE);
    if (!url.searchParams.has('channel')) tab.opener = null;
    tab.location.replace(url.href);
  } catch (error) {
    tab.close();
    throw error;
  }
}

/** Capture before routing/login can replace the hash. Persist before removing
 * the fragment so reloads and instance-login screens cannot lose the ticket. */
export function captureWebInstallReturn() {
  if (!location.hash.startsWith('#openkitsune-install=')) return;
  const params = new URLSearchParams(location.hash.slice(1));
  const direct = params.get('channel') === 'post-message';
  let context = read();
  if (direct) {
    try { context = JSON.parse(localStorage.getItem(SESSIONS + params.get('state')) || 'null'); }
    catch { context = null; }
  }
  let restore = location.pathname + location.search;
  try {
    if (!context || context.expires <= Date.now()) throw new Error('marketplace_context_expired');
    const page = new URL(context.returnUrl);
    const callback = new URL(context.callbackUrl || context.returnUrl);
    if (page.origin !== location.origin || callback.origin !== location.origin || callback.pathname !== location.pathname || context.consumed ||
      params.getAll('state').length !== 1 || params.get('state') !== context.state ||
      params.getAll('openkitsune-install').length !== 1 || !/^[a-f0-9]{64}$/.test(params.get('openkitsune-install') || '') ||
      params.getAll('endpoint').length !== 1 || params.get('endpoint') !== context.endpoint) {
      throw new Error('marketplace_instruction_invalid');
    }
    const token = params.get('openkitsune-install')!;
    if (context.token && context.token !== token) throw new Error('marketplace_install_busy');
    write({ ...context, token, ...(direct ? { state: token, relay: true } : {}) });
    sessionStorage.removeItem(ERROR_KEY);
    restore = page.pathname + page.search + page.hash;
  } catch (error) {
    try { sessionStorage.setItem(ERROR_KEY, error instanceof Error ? error.message : 'marketplace_instruction_invalid'); }
    catch { /* Storage denial must not prevent the rest of OpenKitsune booting. */ }
  } finally { history.replaceState(history.state, '', restore); }
}

export function pendingWebInstall(base: string): WebInstallContext | null {
  const error = sessionStorage.getItem(ERROR_KEY);
  if (error) { sessionStorage.removeItem(ERROR_KEY); throw new Error(error); }
  const context = read();
  if (context?.delivered) return null;
  if (!context || (!context.token && !context.jobId)) return null;
  if (context.base !== baseUrl(base)) throw new Error('marketplace_target_changed');
  if (!context.jobId && context.expires <= Date.now()) throw new Error('marketplace_context_expired');
  return context;
}
export function saveWebInstallJob(context: WebInstallContext, jobId: string) {
  if (read()?.state === context.state) write({ ...context, token: undefined, jobId, consumed: true });
}
export function dismissWebInstall() {
  const context = read();
  if (context) write({ ...context, token: undefined, jobId: undefined, consumed: true });
  const queue = readQueue();
  const next = queue.shift();
  sessionStorage.setItem(QUEUE, JSON.stringify(queue));
  if (next) {
    write(next);
    setTimeout(() => window.dispatchEvent(new Event(WEB_INSTALL_ARRIVED)), 0);
  }
}

function readQueue(): WebInstallContext[] {
  try { return JSON.parse(sessionStorage.getItem(QUEUE) || '[]'); } catch { return []; }
}

/** Persist before acknowledging so a source-page reload does not lose delivery. */
export function enqueueWebInstall(context: WebInstallContext) {
  const active = read();
  const queue = readQueue();
  if (active?.state === context.state || queue.some(item => item.state === context.state)) return;
  const incoming = { ...context, relay: false, delivered: false };
  if (active && !active.delivered && (active.token || active.jobId)) {
    sessionStorage.setItem(QUEUE, JSON.stringify([...queue, incoming]));
  } else write(incoming);
  window.dispatchEvent(new Event(WEB_INSTALL_ARRIVED));
  try { window.focus(); } catch { /* Focus is best effort, persistence is not. */ }
}

export function webReturnToRelay(): WebInstallContext | null {
  if (sessionStorage.getItem(ERROR_KEY)) return null;
  const context = read();
  return context?.relay && (context.token || context.delivered) ? context : null;
}

export function finishWebRelay(sent: boolean) {
  const context = read();
  if (context) write({ ...context, relay: sent, delivered: sent,
    ...(sent ? { token: undefined, consumed: true } : {}) });
}
