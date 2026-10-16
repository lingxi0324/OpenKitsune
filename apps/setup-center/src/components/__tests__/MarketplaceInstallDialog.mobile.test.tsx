import { act, fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
const mocks = vi.hoisted(() => ({ server: { id: 'home', name: 'Home server', url: 'https://home.example' } }));
vi.mock('../../platform/detect', () => ({ IS_CAPACITOR: true }));
vi.mock('../../platform/auth', () => ({ getAccessToken: () => 'home-credential' }));
vi.mock('../../platform/servers', () => ({ getActiveServer: () => mocks.server }));
vi.mock('../../platform', () => ({ IS_CAPACITOR: true, IS_TAURI: false,
  getCurrentDeepLinks: async () => [], onDeepLinkOpen: async () => () => {}, openExternalUrl: vi.fn() }));
import { MarketplaceInstallDialog } from '../MarketplaceInstallDialog';
import { saveInstall, pendingInstall } from '../../marketplace/mobile';
import { getInstallTasks, openInstallTask, patchInstall, taskPhase } from '../../marketplace/installTasks';
const baseJob = { id: 'job', status: 'ready', resource_name: 'Test Skill', resource_type: 'skill', version: '1.0.0', permissions: ['network'], dependencies: [], progress: 0 };
beforeEach(async () => {
  localStorage.clear(); mocks.server = { id: 'home', name: 'Home server', url: 'https://home.example' };
  await i18n.changeLanguage('en');
  saveInstall({ key: 'install-one', target: { id: 'home', name: 'Home server', base: 'https://home.example', state: 'state', expires: Date.now() + 10000 }, endpoint: 'https://marketplace.openkitsune.cn', token: 'a'.repeat(64) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const props = { apiBaseUrl: 'https://home.example', desktopVersion: '1.27.40' };
it('shows dependency activity and elapsed time using the shared progress view instead of a fixed 70 percent', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_url: string) => new Response(JSON.stringify({ data: {
    ...baseJob, status: 'installing', progress: 70, stage: 'dependency_downloading',
    current_dependency: 'python-pptx', elapsed_seconds: 95,
  } }))));
  render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText(i18n.t('marketplaceInstall.stages.dependency_downloading'));
  expect(screen.getByRole('dialog')).toHaveTextContent('python-pptx');
  expect(screen.getByRole('dialog')).toHaveTextContent('1:35');
  expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  expect(screen.getByRole('dialog')).not.toHaveTextContent('70%');
});
it('shows the target and permissions, persists the job and resumes after remount without reinstalling', async () => {
  let status = 'ready';
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url);
    if (url.endsWith('/confirm')) status = 'downloading';
    return new Response(JSON.stringify({ data: { ...baseJob, status } }));
  }));
  const first = render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText('Test Skill · v1.0.0');
  expect(screen.getByRole('dialog')).toHaveTextContent('Home server');
  expect(screen.getByRole('dialog')).toHaveTextContent('network');
  expect(pendingInstall()?.token).toBeUndefined();
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.install') }));
  await screen.findByRole('button', { name: i18n.t('marketplaceInstall.background') });
  first.unmount();
  status = 'installed';
  render(<MarketplaceInstallDialog {...props} />);
  await screen.findByRole('button', { name: i18n.t('marketplaceInstall.pluginSetup.done') });
  expect(calls.filter(url => url.endsWith('/prepare'))).toHaveLength(1);
  expect(calls.filter(url => url.endsWith('/confirm'))).toHaveLength(1);
});
it('does not confirm on a different server and offers target connection recovery', async () => {
  const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ data: baseJob })));
  vi.stubGlobal('fetch', fetcher);
  const manage = vi.fn();
  render(<MarketplaceInstallDialog {...props} onManageServers={manage} />);
  await screen.findByText('Test Skill · v1.0.0');
  mocks.server = { id: 'office', name: 'Office', url: 'https://office.example' };
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.install') }));
  await screen.findByText(i18n.t('marketplaceInstall.errors.marketplace_target_changed'));
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.manageServers') }));
  expect(manage).toHaveBeenCalledOnce();
});
it('keeps authorization failures actionable and retries the same instruction', async () => {
  let attempts = 0;
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith('/api/account/status')) return new Response(JSON.stringify({ profile: {email:'owner@example.test'} }));
    return ++attempts === 1 ? new Response(JSON.stringify({ detail: { code: 'marketplace_account_mismatch' } }), { status: 400 })
      : new Response(JSON.stringify({ data: baseJob }));
  });
  vi.stubGlobal('fetch', fetcher);
  render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText(i18n.t('marketplaceInstall.errors.marketplace_account_mismatch'));
  expect(screen.queryByRole('button', { name: i18n.t('marketplaceInstall.install') })).toBeNull();
  await screen.findByText('owner@example.test');
  fireEvent.click(screen.getByRole('button', { name: i18n.t('common.retry') }));
  await waitFor(() => expect(screen.getByText('Test Skill · v1.0.0')).toBeVisible());
  expect(attempts).toBe(2);
});

it('continues polling after backgrounding, retains pending permissions when hidden and resumes through the app menu action', async () => {
  let installed = false;
  let granted = false;
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url);
    if (url.endsWith('/permissions/grant')) { granted = true; return new Response(JSON.stringify({ success: true })); }
    if (url.endsWith('/api/plugins/list')) return new Response(JSON.stringify({ plugins: [{
      id: 'ppt', enabled: true, status: granted ? 'loaded' : 'disabled', pending_permissions: granted ? [] : ['network'],
    }] }));
    return new Response(JSON.stringify({ data: { ...baseJob, resource_type: 'plugin', plugin_id: 'ppt',
      status: installed ? 'installed' : 'installing' } }));
  }));
  render(<><MarketplaceInstallDialog {...props} /><button onClick={() => openInstallTask()}>Resume installation</button></>);
  await screen.findByText('Test Skill · v1.0.0');
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.background') }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  installed = true;
  await waitFor(() => expect(getInstallTasks()[0]?.setup).toBe('permissions'), { timeout: 4000 });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(calls.some(url => url.endsWith('/installs/job'))).toBe(true);
  await screen.findByRole('button', { name: /View installations: Needs permission/ });
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.tasks.minimize') }));
  expect(getInstallTasks()[0].hidden).toBe(false);
  expect(taskPhase(getInstallTasks()[0])).toBe('permissions');
  fireEvent.click(screen.getByRole('button', { name: 'Resume installation' }));
  fireEvent.click(await screen.findByRole('button', { name: /Test Skill.*Needs permission.*Review permissions/ }));
  await screen.findByRole('dialog');
  fireEvent.click(await screen.findByRole('button', { name: i18n.t('marketplaceInstall.pluginSetup.grant') }));
  await waitFor(() => expect(taskPhase(getInstallTasks()[0])).toBe('complete'));
  expect(calls.filter(url => url.endsWith('/permissions/grant'))).toHaveLength(1);
});

it('restores a background task after remount without reopening its modal or repeating prepare', async () => {
  const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ data: { ...baseJob, status: 'installing' } })));
  vi.stubGlobal('fetch', fetcher);
  const first = render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText('Test Skill · v1.0.0');
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.background') }));
  first.unmount();
  render(<MarketplaceInstallDialog {...props} />);
  await screen.findByRole('button', { name: /View installations: Installing/ });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(fetcher.mock.calls.filter(call => String(call[0]).endsWith('/prepare'))).toHaveLength(1);
});

it('does not send an old task to a newly selected backend', async () => {
  const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify({ data: baseJob })));
  vi.stubGlobal('fetch', fetcher);
  const first = render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText('Test Skill · v1.0.0');
  const task = getInstallTasks()[0];
  act(() => patchInstall(task.key, { background: true }));
  first.unmount();
  mocks.server = { id: 'office', name: 'Office', url: 'https://office.example' };
  render(<MarketplaceInstallDialog {...props} apiBaseUrl="https://office.example" />);
  act(() => openInstallTask(task.key));
  await screen.findByText(i18n.t('marketplaceInstall.errors.marketplace_target_changed'));
  const before = fetcher.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.install') }));
  expect(fetcher.mock.calls.length).toBe(before);
  expect(fetcher.mock.calls.every(call => !String(call[0]).startsWith('https://office.example'))).toBe(true);
});

it('does not reopen an acknowledged completed installation on the next app launch', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ data: { ...baseJob, status: 'installed' } }))));
  const first = render(<MarketplaceInstallDialog {...props} />);
  await screen.findByText('Test Skill · v1.0.0');
  fireEvent.click(screen.getByRole('button', { name: i18n.t('marketplaceInstall.pluginSetup.done') }));
  expect(pendingInstall()?.dismissed).toBe(true);
  first.unmount();
  render(<MarketplaceInstallDialog {...props} />);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(getInstallTasks()).toHaveLength(1);
});

it('does not import server history or resurrect it through the old mobile pending pointer', async () => {
  const oldJob = { ...baseJob, id: 'yesterday', status: 'installed', resource_type: 'plugin', plugin_id: 'old-plugin' };
  saveInstall({ ...pendingInstall()!, token: undefined, jobId: oldJob.id });
  const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify({ data:
    url.endsWith('/installs') ? [oldJob, { ...oldJob, id: 'old-completed' }] : oldJob,
  })));
  vi.stubGlobal('fetch', fetcher);
  render(<MarketplaceInstallDialog {...props} discoverTasks />);
  await waitFor(() => expect(pendingInstall()?.dismissed).toBe(true));
  await waitFor(() => expect(fetcher.mock.calls.some(call => String(call[0]).endsWith('/installs'))).toBe(true));
  expect(getInstallTasks()).toHaveLength(0);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(fetcher.mock.calls.some(call => String(call[0]).endsWith('/api/plugins/list'))).toBe(false);
});
