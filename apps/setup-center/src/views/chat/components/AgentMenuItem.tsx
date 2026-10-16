import { useContext, useEffect, useId, useRef, useState, type FocusEvent, type ReactNode } from "react";
import { HoverCard } from "radix-ui";
import { useTranslation } from "react-i18next";
import { IconCheck, IconInfo } from "../../../icons";
import { AgentMenuCardContext, AgentMenuHoverContext } from "./AgentMenuScrollArea";

export function AgentMenuItem({ name, description, icon, selected, onSelect, container, infoLabel }: {
  name: string;
  description?: string;
  icon: ReactNode;
  selected: boolean;
  onSelect: () => void;
  container: HTMLElement | null;
  infoLabel?: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const descriptionId = useId();
  const hasDescription = Boolean(description?.trim());
  const hoveredRow = useContext(AgentMenuHoverContext);
  const sharedCard = useContext(AgentMenuCardContext);
  const cardOpen = sharedCard ? sharedCard.open && sharedCard.active === rowRef.current : open;
  const cardId = sharedCard?.id ?? descriptionId;
  const showCard = () => {
    if (sharedCard && rowRef.current) sharedCard.show(rowRef.current);
    else setOpen(true);
  };
  const hovered = hoveredRow != null && hoveredRow === rowRef.current;
  const cardHovered = useRef(false);
  useEffect(() => {
    if (sharedCard || hoveredRow === undefined) return;
    if (!hovered) {
      // Close an obsolete card immediately when scrolling onto another row.
      if (hoveredRow) { setOpen(false); return; }
      const timer = window.setTimeout(() => {
        if (!cardHovered.current) setOpen(false);
      }, 150);
      return () => window.clearTimeout(timer);
    }
    if (!hasDescription) return;
    const timer = window.setTimeout(() => setOpen(true), 300);
    return () => window.clearTimeout(timer);
  }, [hoveredRow, hovered, hasDescription, sharedCard]);
  const handleBlur = (event: FocusEvent) => {
    event.preventDefault();
    const target = event.relatedTarget as Node | null;
    if (sharedCard) {
      if (!rowRef.current?.contains(target) && !(target instanceof Element && target.closest(".chatAgentDescriptionShared"))) sharedCard.hide();
      return;
    }
    if (!rowRef.current?.contains(target) && !cardRef.current?.contains(target)) setOpen(false);
  };
  const row = (
    <div
      ref={rowRef}
      className={`chatModelMenuItem chatAgentMenuItem ${selected ? "chatModelMenuItemActive" : ""}`}
      data-hovered={hoveredRow === undefined ? undefined : hovered}
      data-agent-name={name} data-agent-description={description} data-agent-card-id={descriptionId}
      onPointerEnter={(event) => { if (hoveredRow !== undefined) event.preventDefault(); }}
      onPointerLeave={(event) => { if (hoveredRow !== undefined) event.preventDefault(); }}
      onFocusCapture={(event) => {
        event.preventDefault();
        if (hasDescription) showCard();
      }}
      onBlurCapture={handleBlur}
    >
      <button type="button" data-slot="agent-menu-select" className="chatAgentMenuSelect" onClick={onSelect}
        aria-pressed={selected} aria-describedby={cardOpen ? cardId : undefined}>
        <span className="chatAgentMenuIcon">{icon}</span>
        <span className="chatAgentMenuName" title={name}>{name}</span>
        <span className="chatAgentMenuCheck" aria-hidden="true">
          {selected && <IconCheck size={16} />}
        </span>
      </button>
      {hasDescription && (
        <button type="button" className="chatAgentMenuInfo"
          aria-label={infoLabel ?? t("chat.agentDescription", { name })} aria-expanded={cardOpen}
          aria-controls={cardOpen ? cardId : undefined}
          onClick={showCard}>
          <IconInfo size={16} />
        </button>
      )}
    </div>
  );
  if (!hasDescription || sharedCard) return row;
  return (
    <HoverCard.Root open={open} onOpenChange={setOpen} openDelay={300} closeDelay={150}>
      <HoverCard.Trigger asChild>{row}</HoverCard.Trigger>
      <HoverCard.Portal container={container}>
        <HoverCard.Content ref={cardRef} id={descriptionId} className="chatAgentDescriptionCard"
          side="right" align="start" sideOffset={8} collisionPadding={12} tabIndex={0}
          onPointerEnter={() => { cardHovered.current = true; }}
          onPointerLeave={() => { cardHovered.current = false; }}
          onFocusCapture={() => setOpen(true)} onBlurCapture={handleBlur}>
          <div className="chatAgentDescriptionTitle">{name}</div>
          <div>{description}</div>
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}
