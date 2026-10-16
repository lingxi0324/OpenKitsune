import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from './ui/button';
import { finishWebRelay, webReturnToRelay } from '../marketplace/web';
import { webInstallRelay } from '../marketplace/webRelay';

/** Keep the returning tab out of the regular prepare/install flow until a
 * single recipient has been chosen. The market never retains window.opener. */
export function MarketplaceWebReturn({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const context = useRef(webReturnToRelay());
  const [status, setStatus] = useState<'local' | 'sending' | 'sent' | 'error'>(
    context.current?.delivered ? 'sent' : context.current ? 'sending' : 'local');
  const request = useRef<Promise<'sent' | 'local'> | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (status !== 'sending' || !context.current) return;
    if (context.current.base !== location.origin || context.current.expires <= Date.now()) {
      finishWebRelay(false);
      setStatus('local');
      return;
    }
    let disposed = false;
    const relay = webInstallRelay();
    request.current ??= relay ? relay.handoff(context.current) : Promise.resolve('local');
    void request.current.then(result => {
      if (disposed) return;
      finishWebRelay(result === 'sent');
      setStatus(result);
      if (result === 'sent') window.close();
    }).catch(() => {
      if (!disposed) { request.current = null; setStatus('error'); }
    });
    return () => { disposed = true; };
  }, [attempt, status]);
  if (status === 'local') return children;
  return <main className="min-h-dvh flex items-center justify-center bg-background p-6">
    <section className="w-full max-w-md rounded-xl border bg-card p-6 text-center shadow-sm" aria-live="polite">
      {status === 'sending' ? <Loader2 size={24} className="mx-auto mb-4 animate-spin" />
        : status === 'sent' ? <CheckCircle2 size={28} className="mx-auto mb-4 text-emerald-600" /> : null}
      <h1 className="text-lg font-semibold">{t(`marketplaceInstall.webReturn.${status}`)}</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{t(`marketplaceInstall.webReturn.${status}Hint`)}</p>
      {status === 'sent' && <Button className="mt-5" onClick={() => window.close()}>{t('marketplaceInstall.webReturn.close')}</Button>}
      {status === 'error' && <Button className="mt-5" onClick={() => { setStatus('sending'); setAttempt(value => value + 1); }}>{t('common.retry')}</Button>}
    </section>
  </main>;
}
