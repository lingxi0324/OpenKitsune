import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import i18n from '../../i18n';
import { dockPosition, MarketplaceTaskEntry, MarketplaceTaskList } from '../MarketplaceTaskEntry';
import { currentInstallTasks, getInstallTasks, patchInstall, taskPhase, trackInstall } from '../../marketplace/installTasks';
import { InboxBadge } from '../InboxBadge';

beforeEach(async () => { localStorage.clear(); await i18n.changeLanguage('en'); });
afterEach(() => { cleanup(); vi.useRealTimers(); });
const job = { id: 'a', status: 'installing' as const, resource_type: 'plugin' as const,
  resource_name: 'PPT', version: '1', progress: null, permissions: [], dependencies: [] };
it('clamps remembered positions into the resized visual viewport', () => {
  const bounds = { left: 0, top: 30, width: 390, height: 340 };
  expect(dockPosition({ edge: 'right', ratio: 2 }, bounds, 180, 44)).toEqual({ x: 198, y: 306 });
  expect(dockPosition({ edge: 'left', ratio: -1 }, bounds, 180, 44)).toEqual({ x: 12, y: 86 });
});
it('minimizing preserves an actionable entry without hiding the task', () => {
  const task = trackInstall('https://home.example', job, undefined, true);
  const open = vi.fn();
  render(<MarketplaceTaskEntry tasks={[task]} onOpen={open} />);
  fireEvent.click(screen.getByRole('button', { name: /View installations/ }));
  expect(open).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button', { name: /Minimize floating/ }));
  expect(getInstallTasks()[0].hidden).toBe(false);
  expect(screen.getByRole('button', { name: /View installations/ })).toBeVisible();
  expect(taskPhase(getInstallTasks()[0])).toBe('installing');
});
it('completion retires the capsule, while pending permissions persist', () => {
  vi.useFakeTimers();
  const task = trackInstall('https://home.example', { ...job, status: 'installed' }, undefined, true);
  patchInstall(task.key, { setup: 'permissions' });
  const rendered = render(<MarketplaceTaskEntry tasks={getInstallTasks()} onOpen={vi.fn()} />);
  act(() => vi.advanceTimersByTime(60_000));
  expect(screen.getByRole('button', { name: /Needs permission/ })).toBeVisible();
  patchInstall(task.key, { setup: 'ready' });
  rendered.rerender(<MarketplaceTaskEntry tasks={getInstallTasks()} onOpen={vi.fn()} />);
  act(() => vi.advanceTimersByTime(5000));
  expect(screen.queryByRole('button', { name: /View installations/ })).toBeNull();
  expect(getInstallTasks()).toHaveLength(1);
});

it('migrates only live v1 tasks without importing historical permissions or completed jobs', () => {
  const task = { key: 'old', base: 'https://home.example', job, background: true, hidden: false, changedAt: Date.now() };
  localStorage.setItem('openkitsune.marketplace.tasks.v1', JSON.stringify([
    task,
    { ...task, key: 'yesterday', job: { ...job, id: 'yesterday', status: 'installed' }, setup: 'permissions' },
    { ...task, key: 'done', job: { ...job, id: 'done', status: 'installed' }, setup: 'ready' },
  ]));
  expect(getInstallTasks().map(task => task.key)).toEqual(['old']);
  expect(JSON.parse(localStorage.getItem('openkitsune.marketplace.tasks.v1')!)).toHaveLength(3);
});

it('puts the running installation first and excludes completed and other-server tasks', () => {
  const pending = trackInstall('https://home.example', { ...job, id: 'pending', resource_name: 'Waiting', status: 'installed' });
  patchInstall(pending.key, { setup: 'permissions' });
  trackInstall('https://home.example', { ...job, resource_name: 'Current installation' });
  trackInstall('https://home.example', { ...job, id: 'done', resource_type: 'skill', status: 'installed' });
  trackInstall('https://office.example', { ...job, id: 'other' });
  const current = currentInstallTasks(getInstallTasks(), 'https://home.example');
  render(<MarketplaceTaskList tasks={current} />);
  const rows = screen.getAllByRole('button');
  expect(rows).toHaveLength(2);
  expect(rows[0]).toHaveTextContent('Current installation');
  expect(rows[1]).toHaveTextContent('Waiting');
});

it('does not change the notification badge for local installation permissions', () => {
  const task = trackInstall('https://home.example', { ...job, status: 'installed' });
  patchInstall(task.key, { setup: 'permissions' });
  render(<InboxBadge apiBaseUrl="https://home.example" serviceRunning countOverride={3} />);
  expect(screen.getByLabelText('3 unread inbox messages')).toHaveTextContent('3');
});
