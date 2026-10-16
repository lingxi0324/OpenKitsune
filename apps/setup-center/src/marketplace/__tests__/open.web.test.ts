import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ mobile: false, open: vi.fn() }));
vi.mock('../../platform', () => ({
  IS_TAURI: false, IS_CAPACITOR: false,
  get IS_MOBILE_BROWSER() { return mocks.mobile; },
}));
vi.mock('../web', () => ({ openWebMarketplace: mocks.open }));
import { openMarketplaceWithAccount } from '../open';

beforeEach(() => { mocks.mobile = false; mocks.open.mockReset(); });
it('opens desktop Web in a new tab without passing a native loopback target', async () => {
  await openMarketplaceWithAccount('1.27.40', 'http://127.0.0.1:18900', '/catalog');
  expect(mocks.open).toHaveBeenCalledWith('1.27.40', '/catalog', undefined, true);
});
it('keeps mobile Web in the same tab', async () => {
  mocks.mobile = true;
  await openMarketplaceWithAccount('1.27.40', location.origin);
  expect(mocks.open).toHaveBeenCalledWith('1.27.40', '/', undefined, false);
});
