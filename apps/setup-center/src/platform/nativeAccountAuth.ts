import { NativeAuth, type AuthorizationResult } from '@openkitsune/native-auth';
import { getAccessToken } from './auth';
import { getActiveServer } from './servers';
import type { AccountStatusSummary } from '../utils/accountStatusEvents';

const STORAGE_KEY = 'openkitsune.native-account-attempt';
const REDIRECTS = new Set([
  'https://account.openkitsune.cn/oauth/mobile/callback',
  'com.openkitsune.mobile:/oauth/callback',
]);
type Attempt = { base: string; id: string; state: string; redirect: string; expiresAt: number };

function assertCurrentServer(base: string, signal?: AbortSignal) {
  if (signal?.aborted || getActiveServer()?.url.replace(/\/+$/, '') !== base.replace(/\/+$/, '')) {
    throw new Error('account_login_cancelled');
  }
}

function instanceClient(base: string, signal?: AbortSignal) {
  assertCurrentServer(base, signal);
  // A server switch must never send the newly selected server's token to this
  // instance, or let a late 401 clear the new server's credentials.
  const token = getAccessToken();
  return (path: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return fetch(base + path, {
      ...init, headers, credentials: 'omit', redirect: 'error', cache: 'no-store',
      signal: init?.signal ?? AbortSignal.timeout(10_000),
    });
  };
}
type InstanceClient = ReturnType<typeof instanceClient>;

export async function readNativeAccountStatus(base: string, signal?: AbortSignal): Promise<AccountStatusSummary> {
  const request = instanceClient(base, signal);
  const response = await request('/api/account/status');
  if (!response.ok) throw new Error('account_native_delivery_failed');
  const snapshot = await response.json();
  assertCurrentServer(base, signal);
  return snapshot;
}

function pending(): Attempt | null {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    return value && typeof value.base === 'string' && typeof value.id === 'string'
      && typeof value.state === 'string' && REDIRECTS.has(value.redirect)
      && typeof value.expiresAt === 'number' ? value : null;
  } catch { return null; }
}

export function parseNativeAuthorizationResult(attempt: Attempt, result: AuthorizationResult) {
  if (result.state && result.state !== attempt.state) throw new Error('account_native_invalid_response');
  if (result.error) throw new Error(result.error);
  if (!result.url) throw new Error('account_native_invalid_response');
  let url: URL;
  try { url = new URL(result.url); }
  catch { throw new Error('account_native_invalid_response'); }
  const base = new URL(url.href);
  base.search = ''; base.hash = '';
  if (base.href !== attempt.redirect || url.hash) throw new Error('account_native_invalid_response');
  for (const key of ['state', 'code', 'error']) {
    if (url.searchParams.getAll(key).length > 1) throw new Error('account_native_invalid_response');
  }
  if (url.searchParams.get('state') !== attempt.state) throw new Error('account_native_invalid_response');
  const code = url.searchParams.get('code') || '';
  const error = url.searchParams.get('error') || '';
  if (Boolean(code) === Boolean(error)) throw new Error('account_native_invalid_response');
  return { state: attempt.state, code, error };
}

function checkAttempt(attempt: Attempt, base: string, signal?: AbortSignal) {
  assertCurrentServer(base, signal);
  if (signal?.aborted || attempt.base !== base) throw new Error('account_login_cancelled');
  if (Date.now() >= attempt.expiresAt) throw new Error('account_login_expired');
}

async function finish(attempt: Attempt, result: AuthorizationResult, base: string, signal?: AbortSignal, client?: InstanceClient) {
  checkAttempt(attempt, base, signal);
  const body = parseNativeAuthorizationResult(attempt, result);
  const request = client ?? instanceClient(base, signal);
  const response = await request(`/api/account/login/native/callback/${encodeURIComponent(attempt.id)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    signal: AbortSignal.timeout(45_000),
  });
  if (!response.ok) {
    if ([400, 404, 409, 410, 422].includes(response.status)) {
      localStorage.removeItem(STORAGE_KEY);
      await NativeAuth.clearPendingResult();
      throw new Error('account_login_expired');
    }
    throw new Error('account_native_delivery_failed');
  }
  const progress = await response.json();
  assertCurrentServer(base, signal);
  if (progress.status !== 'complete') {
    if (['failed', 'expired', 'cancelled'].includes(progress.status)) {
      localStorage.removeItem(STORAGE_KEY);
      await NativeAuth.clearPendingResult();
    }
    throw new Error(progress.error || 'account_token_exchange_failed');
  }
  localStorage.removeItem(STORAGE_KEY);
  await NativeAuth.clearPendingResult();
}

export async function recoverNativeAccountLogin(base: string, signal?: AbortSignal): Promise<boolean> {
  const attempt = pending();
  if (!attempt || attempt.base !== base) return false;
  if (Date.now() >= attempt.expiresAt) {
    localStorage.removeItem(STORAGE_KEY);
    await NativeAuth.clearPendingResult();
    return false;
  }
  const result = await NativeAuth.getPendingResult();
  if (!result.url && !result.error) return false;
  if (result.error) {
    localStorage.removeItem(STORAGE_KEY);
    await NativeAuth.clearPendingResult();
    return false;
  }
  await finish(attempt, result, base, signal);
  return true;
}

export async function runNativeAccountLogin(base: string, signal?: AbortSignal): Promise<void> {
  const request = instanceClient(base, signal);
  if (await recoverNativeAccountLogin(base, signal)) return;
  if (signal?.aborted) throw new Error('account_login_cancelled');
  let redirect: string;
  try { redirect = (await NativeAuth.getRedirectUri()).uri; }
  catch { throw new Error('account_native_unavailable'); }
  if (!REDIRECTS.has(redirect)) throw new Error('account_native_unavailable');
  let attempt: Attempt | null = null;
  let received = false;
  const cancel = () => { void NativeAuth.cancel().catch(() => {}); };
  try {
    const response = await request('/api/account/login/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ flow: 'native', redirect_uri: redirect }),
    });
    if (!response.ok) throw new Error([404, 405, 422].includes(response.status)
      ? 'account_native_not_supported' : 'account_native_delivery_failed');
    const data = await response.json();
    const url = new URL(data.authorization_url);
    const state = url.searchParams.get('state');
    if (data.flow !== 'native' || !data.attempt_id || !state || url.protocol !== 'https:'
      || url.searchParams.get('redirect_uri') !== redirect
      || url.searchParams.get('code_challenge_method') !== 'S256'
      || !url.searchParams.get('code_challenge')) throw new Error('account_native_invalid_response');
    attempt = { base, id: data.attempt_id, state, redirect, expiresAt: Date.now() + data.expires_in * 1000 };
    if (!Number.isFinite(attempt.expiresAt)) throw new Error('account_native_invalid_response');
    checkAttempt(attempt, base, signal);
    // Persist only routing/state metadata. PKCE verifier and tokens stay in the backend.
    localStorage.setItem(STORAGE_KEY, JSON.stringify(attempt));
    signal?.addEventListener('abort', cancel, { once: true });
    const timer = window.setTimeout(cancel, Math.max(0, attempt.expiresAt - Date.now()));
    let result: AuthorizationResult;
    try { result = await NativeAuth.authorize({ url: url.href, redirectUri: redirect, state }); }
    finally { window.clearTimeout(timer); }
    checkAttempt(attempt, base, signal);
    parseNativeAuthorizationResult(attempt, result);
    received = true;
    await finish(attempt, result, base, signal, request);
  } catch (error) {
    // Keep a valid native result for retry after a transient delivery failure.
    if (!received || signal?.aborted) {
      localStorage.removeItem(STORAGE_KEY);
      await NativeAuth.clearPendingResult();
      if (attempt) {
        try { await request(`/api/account/login/cancel/${encodeURIComponent(attempt.id)}`, { method: 'POST' }); }
        catch { /* Backend expires abandoned attempts. */ }
      }
    }
    throw error;
  } finally { signal?.removeEventListener('abort', cancel); }
}

export async function watchNativeAccountResults(callback: () => void) {
  const listener = await NativeAuth.addListener('authorizationResult', callback);
  callback();
  return () => { void listener.remove(); };
}
