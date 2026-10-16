import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { safeFetch } from "../../../providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { LinkDiagnosticDetails } from "../../../components/LinkDiagnosticsPanel";
import type { ChatSource } from "../utils/chatTypes";

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

function hostOf(source: ChatSource): string {
  if (source.hostname) return source.hostname;
  try {
    const u = new URL(source.final_url || source.requested_url);
    return u.hostname;
  } catch {
    return "";
  }
}

export type SourceStripProps = {
  sources?: ChatSource[] | null;
  onRetryLink?: (url: string) => void;
  conversationId?: string;
  httpApiBase?: () => string;
};

export function SourceStrip({ sources, conversationId, httpApiBase, onRetryLink }: SourceStripProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<ChatSource | null>(null);
  const [error, setError] = useState("");
  const [blockedHosts, setBlockedHosts] = useState<Set<string>>(new Set());
  const [busyHost, setBusyHost] = useState<string | null>(null);
  const apiBase = httpApiBase?.();

  const canManage = !!(conversationId && httpApiBase);

  useEffect(() => {
    setBlockedHosts(new Set());
    setSelected(null);
    if (!canManage) return;
    let cancelled = false;
    (async () => {
      try {
        const url = `${apiBase}/api/diagnostics/domain-rules?conversation_id=${encodeURIComponent(
          conversationId!,
        )}`;
        const resp = await safeFetch(url);
        if (!resp.ok) return;
        const body = (await resp.json()) as { blocked?: string[] };
        if (!cancelled && Array.isArray(body.blocked)) {
          setBlockedHosts(new Set(body.blocked));
        }
      } catch {
        // best-effort: leave the set empty
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [canManage, conversationId, apiBase]);

  if (!sources?.length) return null;

  const toggleBlock = async (host: string, currentlyBlocked: boolean) => {
    if (!canManage || !host) return;
    setBusyHost(host);
    setError("");
    try {
      const path = currentlyBlocked
        ? "/api/diagnostics/domain-unblock"
        : "/api/diagnostics/domain-block";
      const resp = await safeFetch(
        `${httpApiBase!()}${path}?conversation_id=${encodeURIComponent(conversationId!)}&host=${encodeURIComponent(host)}`,
        { method: "POST" },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      if (resp.ok) {
        const body = (await resp.json()) as { blocked?: string[] };
        if (Array.isArray(body.blocked)) setBlockedHosts(new Set(body.blocked));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyHost(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, margin: "6px 0 8px" }}>
      {sources.map((source, i) => {
        const requested = source.requested_url || source.final_url;
        const finalUrl = source.final_url || requested;
        const isError = source.status === "error";
        const host = hostOf(source);
        const isBlocked = !!host && blockedHosts.has(host);
        const text = t(isError ? "status.linkDiag.messageFailed" : source.redirected ? "status.linkDiag.messageRedirected" : "status.linkDiag.messageOk", {
          url: shortUrl(finalUrl), final: shortUrl(finalUrl), requested: shortUrl(requested),
        });
        return (
          <div
            key={`${finalUrl}-${i}`}
            title={source.hint || `${requested} -> ${finalUrl}`}
            style={{
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 8,
              border: "1px solid var(--line)",
              borderRadius: 8,
              padding: "5px 8px",
              fontSize: 12,
              color: isError ? "var(--danger)" : "var(--muted)",
              background: isError
                ? "rgba(239,68,68,0.06)"
                : isBlocked
                  ? "rgba(251,191,36,0.08)"
                  : "rgba(37,99,235,0.04)",
            }}
          >
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
              {text}
              {source.from_cache ? t("status.linkDiag.cached") : ""}
              {isBlocked ? t("status.linkDiag.blocked") : ""}
              {source.hint ? <span style={{ marginLeft: 6, opacity: 0.75 }}>{source.hint}</span> : null}
            </span>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelected(source)}>{t("status.linkDiag.details")}</Button>
            {isError && onRetryLink && /^https?:\/\//i.test(requested) && <Button variant="outline" size="sm" className="h-7 text-xs" disabled={isBlocked} onClick={() => onRetryLink(requested)}>{t("status.linkDiag.retry")}</Button>}
            {canManage && host ? (
              <button
                type="button"
                onClick={() => toggleBlock(host, isBlocked)}
                disabled={busyHost === host}
                style={{
                  fontSize: 11,
                  padding: "2px 8px",
                  borderRadius: 6,
                  border: "1px solid var(--line)",
                  background: "transparent",
                  cursor: busyHost === host ? "wait" : "pointer",
                  color: isBlocked ? "var(--accent)" : "var(--muted)",
                  whiteSpace: "nowrap",
                }}
                title={
                  t("status.linkDiag.blockHint")
                }
              >
                {t(isBlocked ? "status.linkDiag.unblock" : "status.linkDiag.block")}
              </button>
            ) : null}
          </div>
        );
      })}
      {error && <p role="alert">{error}</p>}
      <Dialog open={!!selected} onOpenChange={open => { if (!open) setSelected(null); }}>
        <DialogContent overlayClassName="z-[1100]" className="z-[1101] sm:max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("status.linkDiag.title")}</DialogTitle>
            <DialogDescription>{t("status.linkDiag.details")}</DialogDescription>
          </DialogHeader>
          {selected && <LinkDiagnosticDetails diagnostic={{ ...selected, conversation_id: selected.conversation_id || conversationId }} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
