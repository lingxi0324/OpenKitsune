import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { WebInstallRelay, type RelayChannel, type Receipt } from '../webRelay';
import type { WebInstallContext } from '../web';

function storage(): Storage {
  const data = new Map<string, string>();
  return { getItem: key => data.get(key) ?? null, setItem: (key, value) => { data.set(key, value); },
    removeItem: key => { data.delete(key); }, clear: () => data.clear(),
    key: index => [...data.keys()][index] ?? null, get length() { return data.size; } };
}
function harness() {
  const channels = new Set<Set<(event: MessageEvent) => void>>();
  const receipts = new Map<string, Receipt>();
  const claim = vi.fn(async (context: WebInstallContext, receiver: string) => {
    if (!receipts.has(context.state)) receipts.set(context.state, { state: context.state, context, receiver });
    return receipts.get(context.state)!;
  });
  const create = (session = storage()) => {
    const listeners = new Set<(event: MessageEvent) => void>();
    channels.add(listeners);
    const channel: RelayChannel = {
      postMessage: data => {
        for (const others of channels) if (others !== listeners) for (const listener of others) {
          queueMicrotask(() => listener({ data } as MessageEvent));
        }
      },
      addEventListener: (_, listener) => { listeners.add(listener); },
      removeEventListener: (_, listener) => { listeners.delete(listener); },
      close: () => { channels.delete(listeners); },
    };
    return new WebInstallRelay(session, channel, claim);
  };
  return { create, receipts, claim };
}
const context: WebInstallContext = { state: 'b'.repeat(64), token: 'a'.repeat(64),
  endpoint: 'https://marketplace.openkitsune.cn', base: 'http://192.168.1.30:18900',
  returnUrl: 'http://192.168.1.30:18900/web/', expires: Date.now() + 600_000 };
beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it('delivers only to the originating tab when several pages share one service', async () => {
  const { create } = harness();
  const unrelated = vi.fn(), received = vi.fn();
  create().listen(() => context.base, unrelated);
  const original = create(); original.register(context); original.listen(() => context.base, received);
  const pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('sent');
  expect(received).toHaveBeenCalledOnce(); expect(unrelated).not.toHaveBeenCalled();
});

it('prefers the original live instance over a duplicated sessionStorage tab', async () => {
  const { create } = harness();
  const session = storage(), received = vi.fn(), duplicate = vi.fn();
  const original = create(session); original.register(context); original.listen(() => context.base, received);
  const clone = storage(); clone.setItem('openkitsune.marketplace.sources.v1', session.getItem('openkitsune.marketplace.sources.v1')!);
  create(clone).listen(() => context.base, duplicate);
  const pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('sent');
  expect(received).toHaveBeenCalledOnce(); expect(duplicate).not.toHaveBeenCalled();
});

it('elects one surviving source after refresh even when its session was copied', async () => {
  const { create } = harness();
  const session = storage(); const old = create(session); old.register(context); old.close();
  const first = vi.fn(), second = vi.fn();
  const clone = storage(); clone.setItem('openkitsune.marketplace.sources.v1', session.getItem('openkitsune.marketplace.sources.v1')!);
  create(session).listen(() => context.base, first); create(clone).listen(() => context.base, second);
  const pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('sent');
  expect(first.mock.calls.length + second.mock.calls.length).toBe(1);
});

it.each(['closed', 'changed', 'expired'])('continues locally when the source is %s', async mode => {
  const { create } = harness();
  const received = vi.fn(); const original = create();
  original.register(mode === 'expired' ? { ...context, expires: Date.now() - 1 } : context);
  original.listen(() => mode === 'changed' ? 'https://another.example' : context.base, received);
  if (mode === 'closed') original.close();
  const pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('local'); expect(received).not.toHaveBeenCalled();
});

it('rejects modified instructions and never transfers them to the source', async () => {
  const { create } = harness(); const received = vi.fn();
  const original = create(); original.register(context); original.listen(() => context.base, received);
  const pending = create().handoff({ ...context, endpoint: 'https://untrusted.example' });
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('local'); expect(received).not.toHaveBeenCalled();
});

it('does not fall back to a second receiver after an unacknowledged durable claim', async () => {
  const { create, receipts } = harness();
  receipts.set(context.state, { state: context.state, receiver: 'previous-source', context });
  const pending = create().handoff(context).catch(error => error.message);
  await vi.advanceTimersByTimeAsync(3000);
  expect(await pending).toBe('marketplace_connection_failed');
  expect(receipts.get(context.state)?.receiver).toBe('previous-source');
});

it('acknowledges retried delivery after a source reload without reopening its handled dialog', async () => {
  const { create } = harness(); const session = storage(); const received = vi.fn();
  const original = create(session); original.register(context); original.listen(() => context.base, received);
  let pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000); expect(await pending).toBe('sent');
  original.close();
  const recovered = vi.fn(); create(session).listen(() => context.base, recovered);
  pending = create().handoff(context);
  await vi.advanceTimersByTimeAsync(3000); expect(await pending).toBe('sent');
  expect(received).toHaveBeenCalledOnce(); expect(recovered).not.toHaveBeenCalled();
});
