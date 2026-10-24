import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { ChatMessage, MdModules } from "../utils/chatTypes";
import { splitProcessSegments } from "../utils/chatHelpers";
import { MarkdownContent } from "./MarkdownContent";
import { IconCheck, IconChevronRight, IconLoader, IconX } from "../../../icons";

const STEP_RESULT_PREVIEW_LIMIT = 4000;

type StepDetail = {
  tool: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
};

/**
 * Collect tool-call details in execution order so the collapsed step rows in
 * the body can expand into the matching params / result. The ReAct chain is
 * authoritative; legacy `toolCalls` is only a fallback for chain-less messages.
 */
function collectStepDetails(msg: ChatMessage): StepDetail[] {
  const details: StepDetail[] = [];
  const indexById = new Map<string, number>();

  for (const group of msg.thinkingChain || []) {
    for (const entry of group.entries) {
      if (entry.kind === "tool_start") {
        indexById.set(entry.toolId, details.length);
        details.push({
          tool: entry.tool,
          args: entry.args || {},
          status: entry.status === "error" ? "error" : entry.status === "done" ? "done" : "running",
        });
      } else if (entry.kind === "tool_end") {
        const idx = entry.toolId ? indexById.get(entry.toolId) : details.length - 1;
        const detail = idx != null ? details[idx] : undefined;
        if (detail) {
          details[idx as number] = { ...detail, result: entry.result, status: entry.status };
        }
      }
    }
  }

  if (details.length === 0 && msg.toolCalls) {
    for (const tc of msg.toolCalls) {
      details.push({
        tool: tc.tool,
        args: tc.args || {},
        result: tc.result ?? undefined,
        status: tc.status === "error" ? "error" : tc.status === "done" ? "done" : "running",
      });
    }
  }

  return details;
}

function normalizeStepLabel(label: string, running: boolean): string {
  let text = label.trim();
  if (!running) {
    text = text.replace(/^正在/, "");
    text = text.replace(/(\.\.\.|…)$/, "").trim();
    // `调用 run_shell(command, description, timeout)` → `调用 run_shell`
    text = text.replace(/^(调用 [\w.-]+)\(.*\)$/, "$1");
  }
  return text || label;
}

function previewResult(result: string): string {
  if (result.length <= STEP_RESULT_PREVIEW_LIMIT) return result;
  return `${result.slice(0, STEP_RESULT_PREVIEW_LIMIT)}\n\n... 已截断 ${result.length - STEP_RESULT_PREVIEW_LIMIT} 字符（总计 ${result.length} 字符）。`;
}

function ProcessStepLine({
  label,
  running,
  note,
  detail,
}: {
  label: string;
  running: boolean;
  note?: string;
  detail?: StepDetail;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const status = note
    ? detail?.status === "error" ? "error" : "done"
    : detail?.status ?? (running ? "running" : "done");
  const isRunning = status === "running";
  const icon =
    status === "error" ? <IconX size={11} /> :
    isRunning ? <IconLoader size={11} className="chainSpinner" /> :
    <IconCheck size={11} />;
  const displayLabel = normalizeStepLabel(label, isRunning);

  return (
    <div className={`processStep processStep-${status}`}>
      <div
        className={`processStepHead${detail ? " processStepHeadClickable" : ""}`}
        onClick={detail ? () => setOpen((v) => !v) : undefined}
        role={detail ? "button" : undefined}
        title={detail ? (open ? t("chat.collapse", "收起") : t("chat.expand", "展开")) : undefined}
      >
        <span
          className="processStepChevron"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", visibility: detail ? "visible" : "hidden" }}
        >
          <IconChevronRight size={10} />
        </span>
        <span className="processStepIcon">{icon}</span>
        <span className="processStepLabel">{displayLabel}</span>
        {note && <span className="processStepNote">{note}</span>}
      </div>
      {open && detail && (
        <div className="processStepBody">
          <div className="processStepSection">{t("chat.args", "参数：")}</div>
          <pre>{JSON.stringify(detail.args, null, 2)}</pre>
          {detail.result != null && detail.result !== "" && (
            <>
              <div className="processStepSection">{t("chat.result", "结果：")}</div>
              <pre>{previewResult(typeof detail.result === "string" ? detail.result : JSON.stringify(detail.result, null, 2))}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Renders an assistant body as interleaved prose and collapsed process steps
 * (tool calls / file edits), so the answer reads as "one-line conclusion,
 * folded tool work, one-line conclusion, ..." instead of a wall of tool cards.
 */
export function ProcessFlow({
  content,
  msg,
  mdModules,
  streaming,
  apiBaseUrl,
  onImagePreview,
  formatSourceTags,
}: {
  content: string;
  msg: ChatMessage;
  mdModules?: MdModules | null;
  streaming: boolean;
  apiBaseUrl?: string;
  onImagePreview?: (displayUrl: string, downloadUrl: string, name: string) => void;
  formatSourceTags: (text: string) => string;
}) {
  const segments = useMemo(() => splitProcessSegments(content, streaming), [content, streaming]);
  const details = useMemo(() => collectStepDetails(msg), [msg]);

  let stepIndex = 0;
  return (
    <>
      {segments.map((segment, i) => {
        if (segment.kind === "text") {
          return (
            <MarkdownContent
              key={`text-${i}`}
              content={formatSourceTags(segment.text)}
              mdModules={mdModules}
              className="chatMdContent"
              streaming={streaming}
              apiBaseUrl={apiBaseUrl}
              onImagePreview={onImagePreview}
            />
          );
        }
        const detail = details[stepIndex];
        stepIndex += 1;
        return (
          <ProcessStepLine
            key={`step-${i}`}
            label={segment.label}
            running={segment.status === "running"}
            note={segment.note}
            detail={detail}
          />
        );
      })}
    </>
  );
}
