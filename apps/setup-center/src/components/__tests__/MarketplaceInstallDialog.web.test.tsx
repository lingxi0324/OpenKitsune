import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
vi.mock('../../platform', () => ({ IS_TAURI: false, IS_CAPACITOR: false }));
vi.mock('../../marketplace/open', () => ({ desktopAccountHeaders: async () => ({}), openMarketplaceWithAccount: vi.fn() }));
vi.mock('../../providers', () => ({ safeFetchResponse: vi.fn() }));
import { safeFetchResponse } from '../../providers';
import { MarketplaceInstallDialog } from '../MarketplaceInstallDialog';
import { buildWebMarketplaceUrl, captureWebInstallReturn, pendingWebInstall } from '../../marketplace/web';
const job = { id: 'web-job', status: 'ready', resource_type: 'skill', resource_name: 'Web skill',
  version: '1', progress: 0, permissions: [], dependencies: [] };
const props = { apiBaseUrl: location.origin, desktopVersion: '1.27.40' };
beforeEach(async () => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear();
  await i18n.changeLanguage('en');
  history.replaceState(null, '', '/web');
  const url = new URL(buildWebMarketplaceUrl('1.27.40', location.origin));
  history.replaceState(null, '', '/web/marketplace-return#' + new URLSearchParams({ 'openkitsune-install': 'a'.repeat(64),
    state: url.searchParams.get('state')!, endpoint: url.origin }));
  captureWebInstallReturn();
});
afterEach(cleanup);
it('prepares once, resumes after reload and waits for explicit confirmation before installing', async () => {
  let status = 'ready';
  vi.mocked(safeFetchResponse).mockImplementation(async (url) => {
    if (String(url).endsWith('/confirm')) status = 'installing';
    return Response.json({ data: { ...job, status } });
  });
  const first = render(<StrictMode><MarketplaceInstallDialog {...props} /></StrictMode>);
  await screen.findByRole('button', { name: i18n.t('marketplaceInstall.install') });
  expect(vi.mocked(safeFetchResponse).mock.calls.filter(([url]) => url.endsWith('/prepare'))).toHaveLength(1);
  expect(vi.mocked(safeFetchResponse).mock.calls.some(([url]) => url.endsWith('/confirm'))).toBe(false);
  expect(pendingWebInstall(location.origin)?.token).toBeUndefined();
  first.unmount();
  render(<MarketplaceInstallDialog {...props} />);
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('marketplaceInstall.install') }));
  await screen.findByRole('button', { name: 'Continue in background' });
  expect(vi.mocked(safeFetchResponse).mock.calls.filter(([url]) => url.endsWith('/prepare'))).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Continue in background' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(pendingWebInstall(location.origin)).toBeNull();
});
it('retains the instruction on a temporary prepare failure so retry can resume it', async () => {
  vi.mocked(safeFetchResponse).mockResolvedValueOnce(Response.json({}, { status: 503 }))
    .mockResolvedValue(Response.json({ data: job }));
  render(<MarketplaceInstallDialog {...props} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  await screen.findByRole('button', { name: i18n.t('marketplaceInstall.install') });
  expect(vi.mocked(safeFetchResponse).mock.calls.filter(([url]) => url.endsWith('/prepare'))).toHaveLength(2);
});
