import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { AlertCircle, CheckCircle2, ChevronRight, Loader2, Minus, PackageCheck, ShieldCheck, X } from 'lucide-react';
import { needsInstallAttention, openInstallTask, removeFailedInstall, taskPhase, type InstallTask } from '../marketplace/installTasks';
import { MarketplaceInstallProgress } from './MarketplaceInstallProgress';
import './MarketplaceTaskEntry.css';

const POSITION_KEY = 'openkitsune.marketplace.capsule-position.v1';
type Dock = { edge: 'left' | 'right'; ratio: number };
type Bounds = { left: number; top: number; width: number; height: number };
export function dockPosition(dock: Dock, bounds: Bounds, width: number, height: number) {
  const minX = bounds.left + 12;
  const maxX = Math.max(minX, bounds.left + bounds.width - width - 12);
  const minY = bounds.top + 56;
  const maxY = Math.max(minY, bounds.top + bounds.height - height - 20);
  return { x: dock.edge === 'left' ? minX : maxX, y: minY + (maxY - minY) * Math.min(1, Math.max(0, dock.ratio)) };
}
function readDock(): Dock | null {
  try {
    const value = JSON.parse(localStorage.getItem(POSITION_KEY) || 'null');
    if (['left', 'right'].includes(value?.edge) && Number.isFinite(value?.ratio)) return value;
  } catch { /* Use the default position. */ }
  return null;
}
function StatusIcon({ phase }: { phase: string }) {
  if (phase === 'permissions' || phase === 'setup') return <ShieldCheck size={18} />;
  if (phase === 'failed' || phase === 'paused') return <AlertCircle size={18} />;
  if (phase === 'complete') return <CheckCircle2 size={18} />;
  if (phase === 'installing' || phase === 'checking') return <Loader2 size={18} className="install-task-spin" />;
  return <PackageCheck size={18} />;
}

/** Only the current working set is passed in; reading never resolves setup. */
export function MarketplaceTaskList({ tasks, onSelect = task => openInstallTask(task.key), onRemove = task => removeFailedInstall(task.key) }: {
  tasks: InstallTask[]; onSelect?: (task: InstallTask) => void; onRemove?: (task: InstallTask) => void;
}) {
  const { t } = useTranslation();
  const ordered = [...tasks].sort((a, b) => Number(taskPhase(b) === 'installing') - Number(taskPhase(a) === 'installing') ||
    Number(needsInstallAttention(b)) - Number(needsInstallAttention(a)) || b.changedAt - a.changedAt);
  return <div className="install-task-list">
    {!ordered.length && <p className="text-sm text-muted-foreground">{t('marketplaceInstall.tasks.empty')}</p>}
    {ordered.map(task => {
      const phase = taskPhase(task);
      return <div key={task.key} className="install-task-row" data-phase={phase}>
        <button type="button" className="install-task-summary" onClick={() => onSelect(task)}>
          <span className="install-task-icon"><StatusIcon phase={phase} /></span>
          <span className="install-task-copy">
            <strong>{task.job.resource_name}</strong>
            <span>{t(`marketplaceInstall.tasks.${phase}`)}</span>
            <small>{task.mobile?.target.name || task.base}</small>
          </span>
          <span className="install-task-action">{t(phase === 'permissions' ? 'marketplaceInstall.tasks.reviewPermissions' : 'marketplaceInstall.tasks.details')}<ChevronRight size={14} /></span>
        </button>
        {task.job.status === 'failed' && <button type="button" className="install-task-remove"
          aria-label={t('marketplaceInstall.tasks.removeNamed', { name: task.job.resource_name })}
          onClick={() => onRemove(task)}><X size={14} />{t('marketplaceInstall.tasks.remove')}</button>}
        {phase === 'installing' && <div className="install-task-progress"><MarketplaceInstallProgress job={task.job} /></div>}
      </div>;
    })}
  </div>;
}

export function MarketplaceTaskEntry({ tasks, onOpen }: { tasks: InstallTask[]; onOpen: () => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const dock = useRef<Dock | null>(readDock());
  const drag = useRef<{ pointer: number; startX: number; startY: number; x: number; y: number; moved: boolean }>();
  const suppressClick = useRef(false);
  const [position, setPosition] = useState({ x: -1000, y: -1000 });
  const [dragging, setDragging] = useState(false);
  const [snapping, setSnapping] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const visible = tasks.filter(task => !['complete', 'cancelled'].includes(taskPhase(task)));
  const priority = ['installing', 'checking', 'permissions', 'setup', 'failed', 'paused', 'ready'];
  const main = [...visible].sort((a, b) => priority.indexOf(taskPhase(a)) - priority.indexOf(taskPhase(b)))[0];
  const phase = main ? taskPhase(main) : '';
  const count = visible.length;
  const label = visible.every(task => taskPhase(task) === phase)
    ? t(`marketplaceInstall.tasks.${phase}`) : t('marketplaceInstall.tasks.title');
  const bounds = (): Bounds => {
    const viewport = window.visualViewport;
    return { left: viewport?.offsetLeft || 0, top: viewport?.offsetTop || 0,
      width: viewport?.width || window.innerWidth, height: viewport?.height || window.innerHeight };
  };
  const place = () => {
    if (!ref.current || drag.current) return;
    const area = bounds();
    const { width, height } = ref.current.getBoundingClientRect();
    const preferred = dock.current || { edge: 'right', ratio: Math.max(0, (area.height - 240) / Math.max(1, area.height - 120)) };
    setPosition(dockPosition(preferred, area, width, height));
  };
  useEffect(() => {
    const check = () => setBlocked(!!document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"], .sidebarOpen'));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state', 'class'] });
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    place();
    window.addEventListener('resize', place);
    window.visualViewport?.addEventListener('resize', place);
    window.visualViewport?.addEventListener('scroll', place);
    return () => {
      window.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('scroll', place);
    };
  }, [phase, count, blocked, minimized]);
  if (!main || blocked) return null;
  return createPortal(<div ref={ref} className="install-task-capsule" data-phase={phase} data-minimized={minimized} data-dragging={dragging} data-snapping={snapping}
    style={{ left: position.x, top: position.y }}>
    <button type="button" className="install-task-grip" aria-label={t('marketplaceInstall.tasks.open', { status: label, count })}
      title={t('marketplaceInstall.tasks.dragHint')}
      onPointerDown={event => {
        if (event.button !== 0 || !event.isPrimary) return;
        suppressClick.current = false;
        setSnapping(false);
        drag.current = { pointer: event.pointerId, startX: event.clientX, startY: event.clientY, ...position, moved: false };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={event => {
        const current = drag.current;
        if (!current || current.pointer !== event.pointerId) return;
        const dx = event.clientX - current.startX, dy = event.clientY - current.startY;
        if (!current.moved && Math.hypot(dx, dy) < 6) return;
        current.moved = true; setDragging(true);
        const area = bounds();
        setPosition({ x: Math.max(area.left + 8, Math.min(area.left + area.width - (ref.current?.offsetWidth || 180) - 8, current.x + dx)),
          y: Math.max(area.top + 12, Math.min(area.top + area.height - 64, current.y + dy)) });
      }}
      onPointerUp={event => {
        const current = drag.current;
        if (!current || current.pointer !== event.pointerId) return;
        suppressClick.current = current.moved;
        if (current.moved) {
          const area = bounds();
          const width = ref.current?.offsetWidth || 180, height = ref.current?.offsetHeight || 44;
          dock.current = { edge: position.x + width / 2 < area.left + area.width / 2 ? 'left' : 'right',
            ratio: Math.max(0, Math.min(1, (position.y - area.top - 56) / Math.max(1, area.height - height - 76))) };
          try { localStorage.setItem(POSITION_KEY, JSON.stringify(dock.current)); } catch { /* Session position is retained. */ }
        }
        drag.current = undefined; setDragging(false); setSnapping(current.moved); place();
      }}
      onPointerCancel={() => { suppressClick.current = true; drag.current = undefined; setDragging(false); place(); }}
      onClick={event => {
        if (suppressClick.current && event.detail !== 0) { suppressClick.current = false; return; }
        setMinimized(false); onOpen();
      }}>
      <StatusIcon phase={phase} />{!minimized && <span className="install-task-label">{label}</span>}<span className="install-task-count">{count}</span>
    </button>
    {!minimized && <button type="button" className="install-task-hide" aria-label={t('marketplaceInstall.tasks.minimize')} title={t('marketplaceInstall.tasks.minimize')}
      onClick={() => setMinimized(true)}><Minus size={14} /></button>}
  </div>, document.body);
}
