import { useState, useEffect, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { ChainGroup, ChainEntry, ChatToolCall } from "../utils/chatTypes";
import {
  IconChevronRight, IconCheck, IconX, IconLoader, IconCircle,
  IconAlertCircle, IconRefresh,
} from "../../../icons";
import { TextWithSourceBadges } from "./SourceBadge";
import ConfigHintCard, { type ConfigHintPayload } from "../../../components/ConfigHintCard";

const TOOL_RESULT_PREVIEW_CHAR_LIMIT = 120_000;

/** 毫秒 → 「X分X秒 / Xs」人类可读耗时（截图格式：已处理 2分46秒） */
function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}分${s}秒`;
}

function previewLongText(text: string, limit = TOOL_RESULT_PREVIEW_CHAR_LIMIT): string {
  if (text.length <= limit) return text;
  return `${text.slice(0, limit)}\n\n... 已截断 ${text.length - limit} 字符（总计 ${text.length} 字符）。`;
}

// ── ThinkingBlock: legacy bubble mode ──

export function ThinkingBlock({ content, defaultOpen }: { content: string; defaultOpen?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div className="thinkingBlock">
      <div
        className="thinkingHeader"
        onClick={() => setOpen((v) => !v)}
        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 6, padding: "6px 0", userSelect: "none" }}
      >
        <span style={{ fontSize: 12, opacity: 0.5, transform: open ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.15s", display: "inline-flex", alignItems: "center" }}><IconChevronRight size={12} /></span>
        <span style={{ fontWeight: 700, fontSize: 13, opacity: 0.6 }}>{t("chat.thinkingBlock")}</span>
      </div>
      {open && (
        <div style={{ padding: "8px 12px", background: "rgba(124,58,237,0.04)", borderRadius: 10, fontSize: 13, lineHeight: 1.6, opacity: 0.75, whiteSpace: "pre-wrap" }}>
          <TextWithSourceBadges text={content} />
        </div>
      )}
    </div>
  );
}

// ── ToolCallDetail ──

export function ToolCallDetail({ tc }: { tc: ChatToolCall }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const statusIcon =
    tc.status === "done" ? <IconCheck size={14} /> :
    tc.status === "error" ? <IconX size={14} /> :
    tc.status === "running" ? <IconLoader size={14} /> :
    <IconCircle size={10} />;
  const statusColor = tc.status === "done" ? "var(--ok)" : tc.status === "error" ? "var(--danger)" : "var(--brand)";
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: 8, overflow: "hidden" }}>
      <div
        onClick={() => setOpen((v) => !v)}
        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 6, padding: "6px 10px", background: "rgba(37,99,235,0.03)", userSelect: "none" }}
      >
        <span style={{ color: statusColor, fontWeight: 800, display: "inline-flex", alignItems: "center" }}>{statusIcon}</span>
        <span style={{ fontWeight: 600, fontSize: 12 }}>{tc.tool}</span>
        <span style={{ fontSize: 10, opacity: 0.4, marginLeft: "auto" }}>{open ? t("chat.collapse") : t("chat.expand")}</span>
      </div>
      {open && (
        <div style={{ padding: "6px 10px", fontSize: 12, background: "var(--panel)" }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>{t("chat.args")}</div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11 }}>
            {JSON.stringify(tc.args, null, 2)}
          </pre>
          {tc.result != null && (
            <>
              <div style={{ fontWeight: 700, marginTop: 8, marginBottom: 4 }}>{t("chat.result")}</div>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 11, maxHeight: 200, overflow: "auto" }}>
                {previewLongText(typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2))}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── ToolCallsGroup ──

export function ToolCallsGroup({ toolCalls }: { toolCalls: ChatToolCall[] }) {
  // Aggregate config hints from every child tool call so the card stays
  // visible even when the group is collapsed. Hints are de-duplicated by
  // (error_code, scope, title) — duplicates happen when the same tool is
  // retried multiple times in one turn.
  const aggregatedHints: ConfigHintPayload[] = [];
  const seenHints = new Set<string>();
  for (const tc of toolCalls) {
    for (const h of tc.configHints || []) {
      const key = `${h.error_code}|${h.scope}|${h.title}`;
      if (seenHints.has(key)) continue;
      seenHints.add(key);
      aggregatedHints.push(h);
    }
  }
  return <ToolCallsGroupInner toolCalls={toolCalls} hints={aggregatedHints} />;
}

function ToolCallsGroupInner({
  toolCalls,
  hints,
}: { toolCalls: ChatToolCall[]; hints: ConfigHintPayload[] }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  if (toolCalls.length === 0) return null;

  const errorCount = toolCalls.filter((tc) => tc.status === "error").length;
  const runningCount = toolCalls.filter((tc) => tc.status === "running").length;
  const hasError = errorCount > 0;
  const summaryColor = hasError ? "var(--danger)" : runningCount > 0 ? "var(--brand)" : "var(--ok)";
  const summaryIcon = hasError ? <IconX size={14} /> : runningCount > 0 ? <IconLoader size={14} /> : <IconCheck size={14} />;
  const toolNames = toolCalls.map((tc) => tc.tool);
  const nameCounts: Record<string, number> = {};
  for (const n of toolNames) nameCounts[n] = (nameCounts[n] || 0) + 1;
  const nameLabels = Object.entries(nameCounts).map(([n, c]) => c > 1 ? `${n} ×${c}` : n);
  const summaryText = nameLabels.join(", ");

  return (
    <div style={{ margin: "6px 0", border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", background: "rgba(37,99,235,0.04)", userSelect: "none" }}
      >
        <span style={{ color: summaryColor, fontWeight: 800, display: "inline-flex", alignItems: "center" }}>{summaryIcon}</span>
        <span style={{ fontWeight: 700, fontSize: 13 }}>
          {t("chat.toolCallLabel")}{toolCalls.length > 1 ? `${toolCalls.length} ` : ""}{toolCalls.length === 1 ? toolCalls[0].tool : ""}
        </span>
        {toolCalls.length > 1 && (
          <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
            {summaryText}
          </span>
        )}
        <span style={{ fontSize: 11, opacity: 0.5, marginLeft: "auto", flexShrink: 0 }}>{expanded ? t("chat.collapse") : t("chat.expand")}</span>
      </div>
      {hints.length > 0 && (
        <div style={{ padding: "8px 8px 0 8px", display: "flex", flexDirection: "column", gap: 6 }}>
          {hints.map((h, i) => (
            <ConfigHintCard key={`hint-${i}`} hint={h} />
          ))}
        </div>
      )}
      {expanded && (
        <div style={{ padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4, background: "var(--panel)" }}>
          {toolCalls.map((tc, i) => (
            <ToolCallDetail key={i} tc={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── ToolResultBlock ──

function ToolResultBlock({ result }: { result: string }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  if (!result) return null;
  const safeResult = previewLongText(typeof result === "string" ? result : JSON.stringify(result, null, 2));
  const isShort = safeResult.length < 120;
  if (isShort) return <span className="chainToolResultInline">{safeResult}</span>;
  return (
    <span className="chainToolResultCollapsible">
      <span className="chainToolResultToggle" onClick={() => setExpanded(v => !v)}>
        {expanded ? t("common.collapse", "收起") : t("common.viewDetails", "查看详情")} <IconChevronRight size={9} />
      </span>
      {expanded && <pre className="chainToolResult">{safeResult}</pre>}
    </span>
  );
}

// ── ChainEntryLine ──

function ChainEntryLine({ entry, onSkipStep }: { entry: ChainEntry; onSkipStep?: () => void }) {
  const { t } = useTranslation();
  switch (entry.kind) {
    case "thinking":
      return (
        <div className="chainNarrThinking">
          <span className="chainNarrThinkingLabel">thinking</span>
          <span className="chainNarrThinkingText">
            <TextWithSourceBadges text={entry.content} />
          </span>
        </div>
      );
    case "text": {
      const svgIcon = entry.icon === "alert"
        ? <IconAlertCircle size={12} className="chainNarrStatusIcon chainNarrIconWarn" />
        : entry.icon === "refresh"
          ? <IconRefresh size={12} className="chainNarrStatusIcon chainNarrIconInfo" />
          : null;
      const stepTitle = entry.title?.trim();
      if (stepTitle) {
        // AI 生成的步骤标题：节点图标 + 粗体标题 + 说明正文（截图格式）
        return (
          <div className="chainStepItem">
            <div className="chainStepTitle">
              <span className="chainStepNode" />
              <span className="chainStepTitleText">{stepTitle}</span>
            </div>
            {entry.content && (
              <div className="chainStepBody">
                <TextWithSourceBadges text={entry.content} />
              </div>
            )}
          </div>
        );
      }
      return (
        <div className={`chainNarrText${svgIcon ? " chainNarrStatus" : ""}`}>
          {svgIcon}<TextWithSourceBadges text={entry.content} />
        </div>
      );
    }
    case "tool_start": {
      const isRunning = entry.status === "running";
      const tsIcon = entry.status === "error"
        ? <IconX size={11} />
        : entry.status === "done"
          ? <IconCheck size={11} />
          : <IconLoader size={11} className="chainSpinner" />;
      return (
        <div className={`chainNarrToolStart ${isRunning ? "chainNarrToolRunning" : ""}`} data-tool-id={entry.toolId}>
          {tsIcon}
          <span className="chainNarrToolName">{entry.description || entry.tool}</span>
          {isRunning && (
            <span className="chainToolElapsed" />
          )}
          {isRunning && onSkipStep && (
            <button
              data-slot="skip"
              className="chainToolSkipBtn"
              onClick={(e) => { e.stopPropagation(); onSkipStep(); }}
              title="Skip this step"
            >
              <IconX size={10} />
            </button>
          )}
        </div>
      );
    }
    case "tool_end": {
      const isError = entry.status === "error";
      const icon = isError ? <IconX size={11} /> : <IconCheck size={11} />;
      const cls = isError ? "chainNarrToolEnd chainNarrToolError" : "chainNarrToolEnd";
      return (
        <div className={cls}>
          {icon}
          <ToolResultBlock result={entry.result} />
        </div>
      );
    }
    case "config_hint": {
      // Render the actionable card directly inline in the ReAct timeline.
      // This is what makes the "missing API key → click to configure" UX
      // actually visible — without this branch the ConfigHintCard only
      // shows in legacy ToolCallsGroup, which the default chat UI hides
      // whenever a thinkingChain exists (i.e. essentially always).
      return (
        <div className="chainNarrConfigHint" data-tool-id={entry.toolId || undefined}>
          <ConfigHintCard hint={entry.hint} />
        </div>
      );
    }
    case "compressed":
      return (
        <div className="chainNarrCompressed">
          {t("chat.contextCompressed", "上下文压缩: {{before}}k → {{after}}k tokens", { before: Math.round(entry.beforeTokens / 1000), after: Math.round(entry.afterTokens / 1000) })}
        </div>
      );
    default:
      return null;
  }
}

// ── ChainGroupItem ──

/** One-line phase title for a collapsed group: first tool description wins. */
function summarizeGroupPhase(group: ChainGroup): string {
  for (const entry of group.entries) {
    if (entry.kind === "tool_start" && entry.description) {
      return entry.description;
    }
  }
  for (const entry of group.entries) {
    if (entry.kind === "text" && (entry.title?.trim() || entry.content)) {
      return entry.title?.trim() || entry.content;
    }
  }
  return "";
}

function normalizePhaseTitle(text: string): string {
  return text
    .trim()
    .replace(/^正在/, "")
    .replace(/(\.\.\.|…)$/, "")
    .replace(/^(调用 [\w.-]+)\(.*\)$/, "$1")
    .trim();
}

function ChainGroupItem({ group, onToggle, isLast, streaming, onSkipStep }: {
  group: ChainGroup;
  onToggle: () => void;
  isLast: boolean;
  streaming: boolean;
  onSkipStep?: () => void;
}) {
  const { t } = useTranslation();
  const isActive = isLast && streaming;
  const durMs = group.durationMs;
  const durationSec = durMs ? (durMs / 1000).toFixed(1) : null;
  const hasContent = group.entries.length > 0;

  if (!hasContent && !isActive) {
    return (
      <div className="chainGroup chainGroupCompact">
        <div className="chainProcessedLine">
          <IconCheck size={11} />
          <span>{t("chat.processed", { seconds: durationSec || "0" })}</span>
        </div>
      </div>
    );
  }

  const showContent = !group.collapsed || isActive;
  const phaseTitle = normalizePhaseTitle(summarizeGroupPhase(group));
  const headerLabel = isActive
    ? t("chat.processing")
    : phaseTitle || (group.hasThinking
      ? t("chat.thoughtFor", { seconds: durationSec || "0" })
      : t("chat.processed", { seconds: durationSec || "0" }));

  return (
    <div className={`chainGroup ${group.collapsed && !isActive ? "chainGroupCollapsed" : ""}`}>
      <div className="chainThinkingHeader" onClick={onToggle}>
        <span className="chainChevron" style={{ transform: showContent ? "rotate(90deg)" : "rotate(0deg)" }}>
          <IconChevronRight size={11} />
        </span>
        <span className={`chainThinkingLabel ${isActive ? "chainThinkingLabelActive" : ""}`}>{headerLabel}</span>
        {!isActive && phaseTitle && durationSec && (
          <span className="chainThinkingDuration">{durationSec}s</span>
        )}
        {isActive && <IconLoader size={16} className="chainSpinner chainSpinnerActive" />}
      </div>
      {showContent && (
        <div className="chainNarrFlow">
          {group.entries.map((entry: ChainEntry, i: number) => (
            <ChainEntryLine key={i} entry={entry} onSkipStep={onSkipStep} />
          ))}
          {isActive && group.entries.length > 0 && (
            <div className="chainNarrCursor" />
          )}
        </div>
      )}
    </div>
  );
}

// ── ThinkingChain (main export) ──

export function ThinkingChain({ chain, streaming, showChain, onSkipStep, forceExpand = false }: {
  chain: ChainGroup[];
  streaming: boolean;
  showChain: boolean;
  onSkipStep?: () => void;
  /**
   * One-shot reveal: when this flips to true (e.g. the user clicked "view
   * process" on an otherwise-empty completed bubble) expand every group so the
   * timeline is visible in a single click. It only fires on the transition, so
   * the user can still collapse groups again afterwards.
   */
  forceExpand?: boolean;
}) {
  const { t } = useTranslation();
  // Doubao-style default: the reasoning/tool timeline stays folded into a
  // single summary line; only the currently running iteration is auto-opened
  // while streaming.
  const [localChain, setLocalChain] = useState(() => chain.map(g => ({ ...g, collapsed: true })));
  const wasStreamingRef = useRef(streaming);

  useEffect(() => {
    setLocalChain(prev => {
      const prevMap = new Map(prev.map(g => [g.iteration, g.collapsed]));
      return chain.map(g => ({
        ...g,
        collapsed: prevMap.has(g.iteration) ? prevMap.get(g.iteration)! : true,
      }));
    });
  }, [chain]);

  // Collapse everything again once the turn finishes, so a completed message
  // never leaves expanded tool cards behind.
  useEffect(() => {
    if (wasStreamingRef.current && !streaming) {
      setLocalChain(prev => prev.map(g => ({ ...g, collapsed: true })));
    }
    wasStreamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    if (forceExpand) setLocalChain(prev => prev.map(g => ({ ...g, collapsed: false })));
  }, [forceExpand]);

  // ── 顶部计时：处理中实时累计（已处理 X分X秒），完成后取各轮 durationMs 之和 ──
  const [nowTick, setNowTick] = useState(() => Date.now());
  const turnStartRef = useRef<number>(Date.now());
  useEffect(() => {
    if (!streaming) return;
    const timer = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [streaming]);

  const finishedDurationMs = useMemo(
    () => localChain.reduce((n, g) => n + (g.durationMs || 0), 0),
    [localChain],
  );
  const displayElapsedMs = streaming
    ? Math.max(nowTick - turnStartRef.current, finishedDurationMs)
    : finishedDurationMs;

  // ── 底部状态条：当前正在执行的动作（截图格式：正在执行代码）──
  const activeStatus = useMemo(() => {
    if (!streaming || localChain.length === 0) return "";
    const last = localChain[localChain.length - 1];
    const runningTool = last.entries.find(e => e.kind === "tool_start" && e.status === "running");
    if (runningTool && runningTool.kind === "tool_start") {
      return t("chat.executing", "正在执行 {{action}}", {
        action: runningTool.description || runningTool.tool,
      });
    }
    const lastText = [...last.entries].reverse().find(e => e.kind === "text");
    if (lastText && lastText.kind === "text" && (lastText.title || lastText.content)) {
      return t("chat.executing", "正在执行 {{action}}", {
        action: lastText.title || lastText.content,
      });
    }
    if (last.hasThinking) return t("chat.thinking", "思考中...");
    return t("chat.processing", "处理中...");
  }, [localChain, streaming, t]);

  if (!showChain || !localChain || localChain.length === 0) return null;

  const allCollapsed = localChain.every(g => g.collapsed) && !streaming;
  if (allCollapsed) {
    const toolSteps = localChain.reduce(
      (n, g) => n + g.entries.filter(e => e.kind === "tool_start").length,
      0,
    );
    const totalSteps = toolSteps > 0 ? toolSteps : localChain.reduce((n, g) => n + g.entries.length, 0);
    if (totalSteps === 0) return null;
    return (
      <div
        className="chainCollapsedSummary"
        onClick={() => setLocalChain(prev => prev.map(g => ({ ...g, collapsed: false })))}
      >
        <IconChevronRight size={11} />
        <span>{t("chat.workProcessSummary", { steps: totalSteps })}</span>
        {displayElapsedMs > 0 && (
          <span className="chainSummaryDuration">{t("chat.elapsedProcessedShort", "已处理 {{time}}", { time: formatElapsed(displayElapsedMs) })}</span>
        )}
      </div>
    );
  }

  return (
    <div className="thinkingChain">
      {displayElapsedMs > 0 && (
        <div className="chainElapsedRow">
          <span className="chainElapsedClock">⏱</span>
          <span>{t("chat.elapsedProcessed", "已处理 {{time}}", { time: formatElapsed(displayElapsedMs) })}</span>
          {streaming && <span className="chainElapsedLive">· 实时</span>}
        </div>
      )}
      {localChain.map((group, idx) => (
        <ChainGroupItem
          key={group.iteration}
          group={group}
          isLast={idx === localChain.length - 1}
          streaming={streaming}
          onSkipStep={onSkipStep}
          onToggle={() => {
            setLocalChain(prev => prev.map((g, i) =>
              i === idx ? { ...g, collapsed: !g.collapsed } : g
            ));
          }}
        />
      ))}
      {activeStatus && (
        <div className="chainStatusBar">
          <IconLoader size={13} className="chainSpinner" />
          <span className="chainStatusBarText">{activeStatus}</span>
        </div>
      )}
    </div>
  );
}
