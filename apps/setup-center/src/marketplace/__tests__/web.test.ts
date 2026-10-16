import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { buildWebMarketplaceUrl, openWebMarketplace, captureWebInstallReturn, pendingWebInstall, saveWebInstallJob, dismissWebInstall, enqueueWebInstall } from '../web';

const endpoint = 'https://marketplace.openkitsune.cn';
const token = 'a'.repeat(64);
beforeEach(() => { sessionStorage.clear(); history.replaceState(null, '', '/proxy/web?local=value#plugins'); });
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
function returnFromMarket(state: string, overrides: Record<string, string> = {}) {
  history.replaceState(null, '', '/proxy/web/marketplace-return#' + new URLSearchParams({ 'openkitsune-install': token, state, endpoint, ...overrides }));
  captureWebInstallReturn();
}
it('keeps credentials and the original route local, accepts the bound return and persists it across reads', () => {
  localStorage.setItem('openkitsune_access_token', 'secret');
  const url = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  expect(url.searchParams.get('client')).toBe('web');
  expect(url.searchParams.get('return_url')).toBe(location.origin + '/proxy/web/marketplace-return');
  expect(url.href).not.toMatch(/secret|local=value|plugins/);
  returnFromMarket(url.searchParams.get('state')!);
  expect(location.hash).toBe('#plugins');
  expect(location.search).toBe('?local=value');
  expect(pendingWebInstall(location.origin)?.token).toBe(token);
  const pending = pendingWebInstall(location.origin)!;
  saveWebInstallJob(pending, 'job');
  expect(pendingWebInstall(location.origin)?.token).toBeUndefined();
  expect(pendingWebInstall(location.origin)?.jobId).toBe('job');
  dismissWebInstall();
  expect(pendingWebInstall(location.origin)).toBeNull();
});
it.each(['state', 'endpoint', 'openkitsune-install'])('rejects a modified %s without accepting a ticket', (field) => {
  const url = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  returnFromMarket(url.searchParams.get('state')!, { [field]: 'untrusted' });
  expect(() => pendingWebInstall(location.origin)).toThrow('marketplace_instruction_invalid');
  expect(pendingWebInstall(location.origin)).toBeNull();
});
it('rejects a different backend, expired state and replayed returns', () => {
  const url = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  const state = url.searchParams.get('state')!;
  returnFromMarket(state);
  expect(() => pendingWebInstall('https://other.example')).toThrow('marketplace_target_changed');
  saveWebInstallJob(pendingWebInstall(location.origin)!, 'job');
  returnFromMarket(state);
  expect(() => pendingWebInstall(location.origin)).toThrow('marketplace_instruction_invalid');
  vi.useFakeTimers(); vi.setSystemTime(Date.now() + 31 * 60_000);
  returnFromMarket(state);
  expect(() => pendingWebInstall(location.origin)).toThrow('marketplace_context_expired');
});
it('rejects an installation link opened in a different tab without originating context', () => {
  returnFromMarket('b'.repeat(64));
  expect(() => pendingWebInstall(location.origin)).toThrow('marketplace_context_expired');
  expect(location.hash).toBe('');
});

it('gives desktop market tabs independent return contexts and retains the opener for direct delivery', () => {
  const parent = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  const tabs: { sessionStorage: Storage; opener: unknown; location: { replace: ReturnType<typeof vi.fn> }; close: ReturnType<typeof vi.fn> }[] = [];
  vi.spyOn(window, 'open').mockImplementation(() => {
    const values = new Map<string, string>();
    const tab = {
      sessionStorage: { getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => { values.set(key, value); },
        removeItem: (key: string) => { values.delete(key); },
        get length() { return values.size; }, clear: () => values.clear(),
        key: (index: number) => [...values.keys()][index] ?? null },
      opener: window as unknown,
      location: { replace: vi.fn(() => expect(tab.opener).toBe(window)) }, close: vi.fn(),
    };
    tabs.push(tab);
    return tab as unknown as Window;
  });
  openWebMarketplace('1.27.40', '/', undefined, true);
  openWebMarketplace('1.27.40', '/catalog', undefined, true);
  const contexts = tabs.map(tab => JSON.parse(tab.sessionStorage.getItem('openkitsune.marketplace.web.v1')!));
  expect(contexts[0].state).not.toBe(contexts[1].state);
  for (let index = 0; index < tabs.length; index++) {
    const url = new URL(tabs[index].location.replace.mock.calls[0][0]);
    expect(contexts[index].base).toBe(location.origin);
    expect(contexts[index].state).toBe(url.searchParams.get('state'));
    expect(url.searchParams.get('channel')).toBe('post-message');
    expect(url.searchParams.get('return_url')).toBe(location.origin + '/proxy/web/marketplace-return');
  }
  // Opening new tabs must not overwrite a pending installation in the original.
  returnFromMarket(parent.searchParams.get('state')!);
  expect(pendingWebInstall(location.origin)?.token).toBe(token);
});

it('queues concurrent returns without overwriting the active confirmation and deduplicates deliveries', () => {
  vi.spyOn(window, 'focus').mockImplementation(() => {});
  const first = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  returnFromMarket(first.searchParams.get('state')!);
  const active = pendingWebInstall(location.origin)!;
  const next = { ...active, state: 'c'.repeat(64), token: 'd'.repeat(64) };
  enqueueWebInstall(next); enqueueWebInstall(next);
  expect(pendingWebInstall(location.origin)?.state).toBe(active.state);
  dismissWebInstall();
  expect(pendingWebInstall(location.origin)?.state).toBe(next.state);
  dismissWebInstall();
  expect(pendingWebInstall(location.origin)).toBeNull();
});
