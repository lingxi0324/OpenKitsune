import type { WebInstallContext } from './web';

export const WEB_INSTALL_ARRIVED = 'openkitsune:web-install-arrived';
const SOURCES = 'openkitsune.marketplace.sources.v1';
const CHANNEL = 'openkitsune.marketplace.relay.v1';
export const randomRelayId = () => Array.from(crypto.getRandomValues(new Uint8Array(32)),
  value => value.toString(16).padStart(2, '0')).join('');

type Source = WebInstallContext & { sourceInstance: string; acceptedBy?: string };
export type Receipt = { state: string; receiver: string; context: WebInstallContext };
type Message = { type: 'query' | 'offer' | 'deliver' | 'ack'; state: string; from: string;
  to?: string; preferred?: boolean; context?: WebInstallContext };
export interface RelayChannel {
  postMessage(message: Message): void;
  addEventListener(type: 'message', listener: (event: MessageEvent<Message>) => void): void;
  removeEventListener(type: 'message', listener: (event: MessageEvent<Message>) => void): void;
  close(): void;
}

/** IndexedDB serializes claims across tabs on LAN HTTP as well as HTTPS.
 * A delayed delivery and the return-page fallback cannot both win. */
export async function claimWebReturn(context: WebInstallContext, receiver: string): Promise<Receipt> {
  if (context.expires <= Date.now()) throw new Error('marketplace_context_expired');
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open(CHANNEL, 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore('receipts', { keyPath: 'state' });
    opening.onerror = () => reject(opening.error);
    opening.onblocked = () => reject(new Error('marketplace_connection_failed'));
    opening.onsuccess = () => {
      const db = opening.result;
      const transaction = db.transaction('receipts', 'readwrite');
      const store = transaction.objectStore('receipts');
      let receipt: Receipt;
      const request = store.get(context.state);
      request.onsuccess = () => {
        receipt = request.result;
        if (receipt && (receipt.context.token !== context.token || receipt.context.base !== context.base ||
          receipt.context.endpoint !== context.endpoint)) { transaction.abort(); return; }
        if (!receipt) {
          receipt = { state: context.state, receiver, context };
          store.add(receipt);
        }
      };
      // These short-lived records contain no account credentials. Drop expired
      // instructions during subsequent claims instead of retaining a history.
      const cursor = store.openCursor();
      cursor.onsuccess = () => {
        const value = cursor.result;
        if (value) {
          if (value.value.context.expires <= Date.now()) value.delete();
          value.continue();
        }
      };
      transaction.oncomplete = () => { db.close(); resolve(receipt); };
      transaction.onerror = transaction.onabort = () => { db.close(); reject(transaction.error); };
    };
  });
}

export class WebInstallRelay {
  readonly instance = randomRelayId();
  private sources: Source[];
  private stop?: () => void;
  private marketWindows = new Map<string, Window>();
  constructor(private storage: Storage, private channel: RelayChannel,
    private claim = claimWebReturn) {
    try { this.sources = JSON.parse(storage.getItem(SOURCES) || '[]'); }
    catch { this.sources = []; }
    this.sources = this.sources.filter(source => source.expires > Date.now());
  }

  register(context: WebInstallContext) {
    this.sources = [...this.sources.filter(source => source.expires > Date.now()),
      { ...context, sourceInstance: this.instance }];
    this.storage.setItem(SOURCES, JSON.stringify(this.sources));
  }

  registerMarket(context: WebInstallContext, market: Window) {
    this.marketWindows.set(context.state, market);
  }

  listen(base: () => string, receive: (context: WebInstallContext) => void) {
    this.stop?.();
    const onMessage = async ({ data }: MessageEvent<Message>) => {
      if (!data || data.from === this.instance) return;
      const source = this.sources.find(source => source.state === data.state && source.expires > Date.now());
      if (!source || source.base !== base()) return;
      if (data.type === 'query') {
        this.channel.postMessage({ type: 'offer', state: data.state, from: this.instance,
          to: data.from, preferred: source.sourceInstance === this.instance });
      } else if (data.type === 'deliver' && data.to === this.instance) {
        const context = data.context;
        if (!context || context.state !== source.state || context.endpoint !== source.endpoint ||
          context.base !== source.base || context.returnUrl !== source.returnUrl ||
          context.expires !== source.expires || !/^[a-f0-9]{64}$/.test(context.token || '')) return;
        try {
          const receipt = await this.claim(context, this.instance);
          if (source.base !== base()) return;
          if (receipt.receiver === this.instance && !source.acceptedBy) {
            receive(receipt.context);
            source.acceptedBy = this.instance;
            this.storage.setItem(SOURCES, JSON.stringify(this.sources));
          }
          // A refreshed source can acknowledge its persisted inbox. A copied
          // source never steals an instruction already assigned elsewhere.
          if (receipt.receiver === this.instance || receipt.receiver === source.acceptedBy) {
            this.channel.postMessage({ type: 'ack', state: data.state, from: this.instance, to: data.from });
          }
        } catch { /* The return page retains the instruction and shows a retry. */ }
      }
    };
    const onDirect = async (event: MessageEvent) => {
      const data = event.data;
      if (data?.type !== 'openkitsune:install-request:v1' ||
        this.marketWindows.get(data.state) !== event.source) return;
      const session = this.sources.find(item => item.state === data.state);
      if (!session || session.expires <= Date.now() || session.endpoint !== event.origin ||
        session.base !== base() || !/^[a-f0-9]{64}$/.test(data.token || '')) return;
      // Each ticket owns a receipt, allowing several installations per market tab.
      const context = { ...session, state: data.token, token: data.token, relay: true };
      if (!this.sources.some(item => item.state === context.state)) this.register(context);
      const source = this.sources.find(item => item.state === context.state)!;
      try {
        const receipt = await this.claim(context, this.instance);
        if (session.base !== base() || session.expires <= Date.now()) return;
        if (receipt.receiver === this.instance && !source.acceptedBy) {
          receive(context);
          source.acceptedBy = this.instance;
          this.storage.setItem(SOURCES, JSON.stringify(this.sources));
        }
        if (receipt.receiver === this.instance || receipt.receiver === source.acceptedBy) {
          (event.source as Window).postMessage({ type: 'openkitsune:install-ack:v1',
            state: data.state, token: data.token }, event.origin);
        }
      } catch { /* Keep the same instruction available for explicit fallback. */ }
    };
    this.channel.addEventListener('message', onMessage);
    window.addEventListener('message', onDirect);
    this.stop = () => {
      this.channel.removeEventListener('message', onMessage);
      window.removeEventListener('message', onDirect);
    };
    return this.stop;
  }

  async handoff(context: WebInstallContext): Promise<'sent' | 'local'> {
    const offers = new Map<string, boolean>();
    let acknowledged: (() => void) | undefined;
    let selected: string | undefined;
    let received = false;
    const handler = ({ data }: MessageEvent<Message>) => {
      if (!data || data.state !== context.state || data.to !== this.instance) return;
      if (data.type === 'offer') offers.set(data.from, !!data.preferred);
      if (data.type === 'ack' && data.from === selected) { received = true; acknowledged?.(); }
    };
    this.channel.addEventListener('message', handler);
    try {
      // Only pages retaining the originating session can offer. Prefer the
      // original runtime over a copied tab; after refresh choose one responder.
      for (let attempt = 0; attempt < 3; attempt++) {
        this.channel.postMessage({ type: 'query', state: context.state, from: this.instance });
        await new Promise(resolve => setTimeout(resolve, 250));
        if ([...offers.values()].some(Boolean)) break;
      }
      selected = [...offers].sort((a, b) => Number(b[1]) - Number(a[1]) || a[0].localeCompare(b[0]))[0]?.[0];
      if (selected) {
        await new Promise<void>(resolve => {
          const timer = setTimeout(resolve, 1800);
          acknowledged = () => { clearTimeout(timer); resolve(); };
          this.channel.postMessage({ type: 'deliver', state: context.state, from: this.instance,
            to: selected, context });
        });
      }
      // ACK loss is not permission to install twice. Inspect/claim atomically:
      // either the source owns it, or this page wins and late messages lose.
      const receipt = await this.claim(context, this.instance);
      if (receipt.receiver !== this.instance && !received) throw new Error('marketplace_connection_failed');
      return receipt.receiver === this.instance ? 'local' : 'sent';
    } finally { this.channel.removeEventListener('message', handler); }
  }

  close() { this.stop?.(); this.channel.close(); }
}

let relay: WebInstallRelay | undefined;
export function webInstallRelay(): WebInstallRelay | undefined {
  if (!('BroadcastChannel' in window) || !('indexedDB' in window)) return undefined;
  return relay ??= new WebInstallRelay(sessionStorage, new BroadcastChannel(CHANNEL));
}

export function clearInheritedWebSources(storage: Storage) { storage.removeItem(SOURCES); }
