import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ server: { id: 'one', url: 'https://one.example', name: 'Home' }, token: 'one-token', open: vi.fn(), fetch: vi.fn(), redirectUri: vi.fn() }));
vi.mock('../../platform/servers', () => ({ getActiveServer: () => mocks.server }));
vi.mock('../../platform/auth', () => ({ getAccessToken: () => mocks.token }));
vi.mock('../../platform/detect', () => ({ IS_CAPACITOR: true }));
vi.mock('@capacitor/browser', () => ({ Browser: { open: mocks.open } }));
vi.mock('@openkitsune/native-auth', () => ({ NativeAuth: { getRedirectUri: mocks.redirectUri } }));
import { acceptMobileInstall, installRequest, marketplaceOpenErrorKey, openMarketplace, pendingInstall, saveInstall } from '../mobile';

const origin = 'https://marketplace.openkitsune.cn';
async function link() {
  await openMarketplace('1.27.40');
  const context = new URL(mocks.open.mock.lastCall![0].url);
  return `${origin}/openkitsune/install#` + new URLSearchParams({ token: 'a'.repeat(64), state: context.searchParams.get('state')!, endpoint: origin });
}
beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks();
  mocks.server = { id: 'one', url: 'https://one.example', name: 'Home' }; mocks.token = 'one-token';
  mocks.fetch.mockReset().mockImplementation(async () => new Response(JSON.stringify({ version: '1.27.40' })));
  mocks.redirectUri.mockReset().mockResolvedValue({ uri: 'https://account.openkitsune.cn/oauth/mobile/callback' });
  mocks.open.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal('fetch', mocks.fetch);
});
afterEach(() => vi.unstubAllGlobals());

describe('opening Marketplace from the app', () => {
  it('recovers from a failed startup version lookup using the selected backend', async () => {
    await openMarketplace('0.0.0');
    const url = new URL(mocks.open.mock.lastCall![0].url);
    expect(url.searchParams.get('version')).toBe('1.27.40');
    expect(mocks.fetch).toHaveBeenCalledWith('https://one.example/api/health', expect.anything());
    expect(new Headers(mocks.fetch.mock.calls[0][1].headers).get('Authorization')).toBe('Bearer one-token');
  });
  it('uses the target backend version instead of a cached app or previous server version', async () => {
    mocks.fetch.mockResolvedValueOnce(new Response(JSON.stringify({ version: '1.28.2' })));
    await openMarketplace('1.27.40');
    expect(new URL(mocks.open.mock.lastCall![0].url).searchParams.get('version')).toBe('1.28.2');
  });
  it('opens the pending installation even before the app version is initialized', async () => {
    const pending = acceptMobileInstall(await link())!;
    saveInstall({ ...pending, jobId: 'job' });
    mocks.open.mockClear(); mocks.fetch.mockClear();
    const resume = vi.fn(); window.addEventListener('openkitsune-marketplace-resume', resume);
    try {
      await openMarketplace('0.0.0');
      expect(resume).toHaveBeenCalledOnce();
      expect(mocks.open).not.toHaveBeenCalled();
      expect(mocks.fetch).not.toHaveBeenCalled();
    } finally { window.removeEventListener('openkitsune-marketplace-resume', resume); }
  });
  it('allows a retry after a temporary backend failure without saving an unusable context', async () => {
    mocks.fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(openMarketplace('0.0.0')).rejects.toThrow('marketplace_server_unavailable');
    expect(mocks.open).not.toHaveBeenCalled();
    expect(localStorage.getItem('openkitsune.marketplace.mobile.v1')).toBeNull();
    await openMarketplace('0.0.0');
    expect(mocks.open).toHaveBeenCalledOnce();
  });
  it('rejects stale health results if the user switches servers during opening', async () => {
    mocks.fetch.mockImplementationOnce(async () => {
      mocks.server = { id: 'two', url: 'https://two.example', name: 'Office' };
      return new Response(JSON.stringify({ version: '1.28.2' }));
    });
    await expect(openMarketplace('1.27.40')).rejects.toThrow('marketplace_target_changed');
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it.each([undefined, '0.0.0', 12740])('reports an unusable backend version (%s)', async version => {
    mocks.fetch.mockResolvedValueOnce(new Response(JSON.stringify({ version })));
    await expect(openMarketplace('1.27.40')).rejects.toThrow('marketplace_server_version_invalid');
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it('reports expired server credentials separately', async () => {
    mocks.fetch.mockResolvedValueOnce(new Response('{}', { status: 401 }));
    await expect(openMarketplace('0.0.0')).rejects.toThrow('marketplace_server_login_required');
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it('reports native component failures before saving a browser context', async () => {
    mocks.redirectUri.mockRejectedValueOnce(new Error('NativeAuth unavailable'));
    await expect(openMarketplace('0.0.0')).rejects.toThrow('marketplace_native_unavailable');
    expect(localStorage.getItem('openkitsune.marketplace.mobile.v1')).toBeNull();
  });
  it('cleans up failed browser launches and supports the debug APK return mode', async () => {
    mocks.redirectUri.mockResolvedValue({ uri: 'com.openkitsune.mobile:/oauth/callback' });
    mocks.open.mockRejectedValueOnce(new Error('Unable to display URL'));
    await expect(openMarketplace('0.0.0')).rejects.toThrow('marketplace_browser_unavailable');
    expect(JSON.parse(localStorage.getItem('openkitsune.marketplace.mobile.v1')!).targets).toEqual([]);
    await openMarketplace('0.0.0');
    expect(new URL(mocks.open.mock.lastCall![0].url).searchParams.get('client')).toBe('mobile');
  });
  it('maps known opening failures without exposing arbitrary error text', () => {
    expect(marketplaceOpenErrorKey(new Error('marketplace_server_unavailable'))).toBe('topbar.marketplaceErrors.marketplace_server_unavailable');
    expect(marketplaceOpenErrorKey(new Error('secret request contents'))).toBe('topbar.openMarketplaceFailed');
  });
});
describe('mobile installation target binding', () => {
  it('does not send the instance address or credential to the browser', async () => {
    const raw = await link();
    expect(mocks.open.mock.lastCall![0].url).not.toContain('one.example');
    expect(mocks.open.mock.lastCall![0].url).not.toContain('one-token');
    const pending = acceptMobileInstall(raw)!;
    expect(pending.target.id).toBe('one');
    saveInstall({ ...pending, jobId: 'job', token: undefined });
    expect(acceptMobileInstall(raw)?.jobId).toBe('job');
    expect(pendingInstall()?.jobId).toBe('job');
    saveInstall({ ...pending, dismissed: true });
    expect(acceptMobileInstall(raw)?.dismissed).toBe(true);
  });
  it('rejects a forged context, duplicate fields and untrusted source', async () => {
    const raw = await link();
    expect(() => acceptMobileInstall(raw.replace(/state=[^&]+/, 'state=unknown'))).toThrow('marketplace_context_expired');
    expect(() => acceptMobileInstall(raw + '&token=' + 'b'.repeat(64))).toThrow('marketplace_instruction_invalid');
    expect(() => acceptMobileInstall(raw.replace(encodeURIComponent(origin), encodeURIComponent('https://evil.example')))).toThrow('marketplace_instruction_invalid');
    expect(acceptMobileInstall('https://evil.example/openkitsune/install#token=x')).toBeNull();
  });
  it('never sends a request to the old target with a new server credential', async () => {
    const pending = acceptMobileInstall(await link())!;
    const request = installRequest(pending.target);
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    mocks.server = { id: 'two', url: 'https://two.example', name: 'Office' }; mocks.token = 'two-token';
    await expect(request('/api/marketplace/installs/job')).rejects.toThrow('marketplace_target_changed');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('ignores in-flight results after a server switch and freezes credentials', async () => {
    const pending = acceptMobileInstall(await link())!;
    const request = installRequest(pending.target);
    let resolve!: (r: Response) => void;
    const fetcher = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) => new Promise<Response>(r => { resolve = r; })); vi.stubGlobal('fetch', fetcher);
    const reading = request('/api/marketplace/installs/job');
    const options = fetcher.mock.calls[0][1] as RequestInit;
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer one-token');
    expect(options.redirect).toBe('error');
    mocks.server = { id: 'two', url: 'https://two.example', name: 'Office' }; mocks.token = 'two-token';
    resolve(new Response(JSON.stringify({ data: { id: 'job' } })));
    await expect(reading).rejects.toThrow('marketplace_target_changed');
  });
  it('supports the explicit browser fallback without using the OAuth receiver', async () => {
    const raw = await link();
    expect(acceptMobileInstall(raw.replace(origin + '/openkitsune/install', 'com.openkitsune.marketplace://marketplace/install'))?.target.id).toBe('one');
  });
});
