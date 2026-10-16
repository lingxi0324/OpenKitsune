import { createContext, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ScrollArea } from "radix-ui";

export const AgentMenuHoverContext = createContext<HTMLElement | null | undefined>(undefined);
export const AgentMenuCardContext = createContext<{
  show: (row: HTMLElement) => void;
  hide: () => void;
  active: HTMLElement | null;
  open: boolean;
  id: string;
} | null>(null);

export function AgentMenuScrollArea({ children, className = "" }: { children: ReactNode; className?: string }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const [hoveredRow, setHoveredRow] = useState<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const cardInteracting = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const visible = useRef(false);
  const [active, setActive] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [animatePosition, setAnimatePosition] = useState(false);
  const [revision, setRevision] = useState(0);
  const [geometry, setGeometry] = useState({ left: 0, top: 0, width: 280, height: 0 });
  const id = useId();
  const hide = useCallback(() => {
    clearTimeout(timer.current);
    visible.current = false;
    setAnimatePosition(false);
    setOpen(false);
  }, []);
  const show = useCallback((row: HTMLElement) => {
    clearTimeout(timer.current);
    if (!row.dataset.agentDescription?.trim()) { hide(); return; }
    // Initial placement (including reopening) must settle without travelling
    // from the previous coordinates. Only an already-visible card may move.
    setAnimatePosition(visible.current);
    setActive(row);
    visible.current = true;
    setOpen(true);
  }, [hide]);
  const delayHide = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (!cardInteracting.current) hide(); }, 150);
  }, [hide]);
  useEffect(() => {
    clearTimeout(timer.current);
    if (!hoveredRow) { delayHide(); return; }
    if (visible.current) show(hoveredRow);
    else timer.current = setTimeout(() => show(hoveredRow), 300);
    return () => clearTimeout(timer.current);
  }, [hoveredRow, show, delayHide]);
  useEffect(() => {
    const resize = () => setRevision(value => value + 1);
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") hide(); };
    window.addEventListener("resize", resize);
    document.addEventListener("keydown", escape);
    return () => {
      clearTimeout(timer.current);
      window.removeEventListener("resize", resize);
      document.removeEventListener("keydown", escape);
    };
  }, [hide]);
  useLayoutEffect(() => {
    if (!active || !contentRef.current) return;
    const rect = active.getBoundingClientRect();
    const width = Math.min(280, window.innerWidth - 24);
    const height = Math.min(contentRef.current.getBoundingClientRect().height + 2, 360, window.innerHeight - 24);
    const left = rect.right + 8 + width <= window.innerWidth - 12 ? rect.right + 8 : rect.left - 8 - width;
    setGeometry({ width, height, left: Math.max(12, Math.min(left, window.innerWidth - width - 12)),
      top: Math.max(12, Math.min(rect.top, window.innerHeight - height - 12)) });
  }, [active, revision, geometry.width]);
  const updateHover = () => {
    const viewport = viewportRef.current;
    const position = pointer.current;
    const target = position && document.elementFromPoint(position.x, position.y);
    const row = target instanceof Element ? target.closest<HTMLElement>(".chatAgentMenuItem") : null;
    setHoveredRow(viewport?.contains(row) ? row : null);
  };
  return (
    <AgentMenuCardContext.Provider value={{ show, hide, active, open, id }}>
    <AgentMenuHoverContext.Provider value={hoveredRow}>
      <ScrollArea.Root ref={rootRef} data-agent-menu-card={id} className={`chatModelMenu chatAgentMenu ${className}`} type="auto" style={{ position: "absolute" }}>
        <ScrollArea.Viewport ref={viewportRef} className="chatAgentMenuViewport"
          onPointerMove={(event) => {
            if (event.pointerType === "touch") return;
            pointer.current = { x: event.clientX, y: event.clientY };
            updateHover();
          }}
          onPointerLeave={() => { pointer.current = null; setHoveredRow(null); }}
          onScroll={() => { updateHover(); setRevision(value => value + 1); }}>
          {children}
        </ScrollArea.Viewport>
        <ScrollArea.Scrollbar orientation="vertical" className="chatAgentMenuScrollbar">
          <ScrollArea.Thumb className="chatAgentMenuThumb" />
        </ScrollArea.Scrollbar>
      </ScrollArea.Root>
      {active && createPortal(
        <div ref={cardRef} id={id} className="chatAgentDescriptionCard chatAgentDescriptionShared"
          data-open={open} data-animate-position={animatePosition} aria-hidden={!open} style={geometry} tabIndex={open ? 0 : -1}
          onPointerEnter={() => { cardInteracting.current = true; clearTimeout(timer.current); }}
          onPointerLeave={() => { cardInteracting.current = false; delayHide(); }}
          onFocus={() => { cardInteracting.current = true; clearTimeout(timer.current); }} onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) { cardInteracting.current = false; delayHide(); }
          }}>
          <div ref={contentRef} key={active.dataset.agentCardId} className="chatAgentDescriptionBody">
            <div className="chatAgentDescriptionTitle">{active.dataset.agentName}</div>
            <div>{active.dataset.agentDescription}</div>
          </div>
        </div>, document.body)}
    </AgentMenuHoverContext.Provider>
    </AgentMenuCardContext.Provider>
  );
}
