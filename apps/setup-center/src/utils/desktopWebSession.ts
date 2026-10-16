import { invoke, IS_TAURI, openExternalUrl } from '../platform';
import { isTauriRemoteMode, setAccessToken } from '../platform/auth';
import { safeFetchResponse } from '../providers';

export async function openDesktopWebSession(webUrl: string) {
  if (!IS_TAURI || isTauriRemoteMode()) return openExternalUrl(webUrl);
  const base = new URL(webUrl).origin;
  const token = await invoke<string>('openkitsune_account_session_token');
  const response = await safeFetchResponse(base + '/api/auth/desktop-web-session', {
    method: 'POST', headers: { 'X-OpenKitsune-Desktop-Token': token },
  });
  if (!response.ok) throw new Error('desktop_web_session_failed');
  const result = await response.json();
  const destination = new URL(result.url);
  if (destination.origin !== base || destination.pathname !== '/web/' ||
    !destination.hash.startsWith('#openkitsune-web-session=')) throw new Error('desktop_web_session_failed');
  await openExternalUrl(destination.href);
}

export async function consumeDesktopWebSession() {
  if (!location.hash.startsWith('#openkitsune-web-session=')) return;
  const params = new URLSearchParams(location.hash.slice(1));
  const ticket = params.get('openkitsune-web-session');
  history.replaceState(history.state, '', location.pathname + location.search);
  if (params.getAll('openkitsune-web-session').length !== 1 || !ticket) throw new Error('desktop_web_session_failed');
  const response = await fetch('/api/auth/desktop-web-session/consume', {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ticket }), signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error('desktop_web_session_failed');
  const result = await response.json();
  if (typeof result.access_token !== 'string') throw new Error('desktop_web_session_failed');
  setAccessToken(result.access_token);
}
