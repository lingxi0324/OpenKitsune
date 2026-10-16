import { StrictMode } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
const mocks = vi.hoisted(() => ({ handoff: vi.fn(), context: vi.fn(), finish: vi.fn() }));
vi.mock('../../marketplace/web', () => ({ webReturnToRelay: mocks.context, finishWebRelay: mocks.finish }));
vi.mock('../../marketplace/webRelay', () => ({ webInstallRelay: () => ({ handoff: mocks.handoff }) }));
import { MarketplaceWebReturn } from '../MarketplaceWebReturn';
beforeEach(async () => {
  vi.clearAllMocks(); await i18n.changeLanguage('en');
  mocks.context.mockReturnValue({ state: 'session', token: 'token', base: location.origin, expires: Date.now() + 10000 });
  vi.spyOn(window, 'close').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('keeps the app unmounted until handoff is resolved and sends only once in StrictMode', async () => {
  let resolve!: (value: string) => void;
  mocks.handoff.mockReturnValue(new Promise(done => { resolve = done; }));
  render(<StrictMode><MarketplaceWebReturn><div>Application</div></MarketplaceWebReturn></StrictMode>);
  expect(screen.queryByText('Application')).toBeNull();
  resolve('sent');
  await screen.findByText('Installation request delivered');
  expect(mocks.handoff).toHaveBeenCalledOnce(); expect(window.close).toHaveBeenCalledOnce();
  expect(screen.queryByText('Application')).toBeNull();
});
it('mounts the regular confirmation flow when the source is unavailable', async () => {
  mocks.handoff.mockResolvedValue('local');
  render(<MarketplaceWebReturn><div>Application</div></MarketplaceWebReturn>);
  await screen.findByText('Application'); expect(mocks.finish).toHaveBeenCalledWith(false);
});
it('retains the request and retries uncertain delivery without mounting a second installer', async () => {
  mocks.handoff.mockRejectedValueOnce(new Error('unconfirmed')).mockResolvedValue('sent');
  render(<MarketplaceWebReturn><div>Application</div></MarketplaceWebReturn>);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
  await screen.findByText('Installation request delivered');
  expect(screen.queryByText('Application')).toBeNull(); expect(mocks.handoff).toHaveBeenCalledTimes(2);
});
