import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RotateCw } from "lucide-react";
import { Section } from "./Section";
import { Button } from "@/components/ui/button";
import { safeFetch } from "../providers";

export type LinkDiagnostic = {
  requested_url?: string;
  final_url?: string;
  redirect_chain?: string[];
  status_code?: number;
  content_type?: string;
  status?: string;
  error_code?: string;
  hostname?: string;
  conversation_id?: string;
  recorded_at?: string;
  hint?: string;
};

/** Chat passes the exact event; maintenance explicitly shows the latest record. */
export function LinkDiagnosticDetails({ diagnostic: d }: { diagnostic: LinkDiagnostic }) {
  const { t } = useTranslation();
  const reason = d.error_code && t(`status.linkDiag.reason.${({
    binary_content: "binary", domain_blocked: "blocked", too_many_redirects: "tooManyRedirects",
    network_error: "network", empty_content: "empty", redirect_missing_location: "redirectInvalid",
  } as Record<string, string>)[d.error_code] || "unknown"}`, { defaultValue: d.error_code });
  return <div className="space-y-3 text-sm break-words">
    <p>{t(d.status === "error" ? "status.linkDiag.failed" : "status.linkDiag.succeeded")}{reason ? ` · ${reason}` : ""}</p>
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2">
      <dt>{t("status.linkDiag.url")}</dt><dd className="break-all">{d.requested_url || d.final_url || "—"}</dd>
      <dt>{t("status.linkDiag.conversation")}</dt><dd>{d.conversation_id || t("status.linkDiag.unknownConversation")}</dd>
      <dt>{t("status.linkDiag.time")}</dt><dd>{d.recorded_at ? new Date(d.recorded_at).toLocaleString() : "—"}</dd>
    </dl>
    {d.hint && <p className="text-muted-foreground">{d.hint}</p>}
    <Section title={t("status.linkDiag.technical")}>
      <dl className="mt-2 space-y-2 text-xs break-all">
        <dt>{t("status.linkDiag.finalUrl")}</dt><dd>{d.final_url || d.requested_url || "—"}</dd>
        <dt>{t("status.linkDiag.response")}</dt><dd>{d.status_code ?? "—"} · {d.content_type || "—"}</dd>
        {!!d.redirect_chain?.length && <><dt>{t("status.linkDiag.redirects")}</dt><dd>{d.redirect_chain.join(" → ")}</dd></>}
      </dl>
    </Section>
  </div>;
}

export function LinkDiagnosticsPanel({ httpApiBase, serviceRunning, disabled = false }: {
  httpApiBase: () => string;
  serviceRunning: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [diag, setDiag] = useState<LinkDiagnostic | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const base = httpApiBase();
  useEffect(() => {
    generation.current++;
    setDiag(null); setLoaded(false); setLoading(false); setError("");
    return () => { generation.current++; };
  }, [base, serviceRunning]);

  async function refresh() {
    if (!serviceRunning || disabled || loading) return;
    const request = ++generation.current;
    setLoading(true); setError("");
    try {
      const resp = await safeFetch(`${base}/api/diagnostics/last-link`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      if (request === generation.current) {
        setDiag(Object.keys(body).length ? body : null);
        setLoaded(true);
      }
    } catch (e) {
      if (request === generation.current) setError(t("status.linkDiag.refreshFailedDetail", { error: String(e) }));
    } finally { if (request === generation.current) setLoading(false); }
  }
  return <>
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" onClick={() => void refresh()} disabled={disabled || loading || !serviceRunning}>
        <RotateCw size={14} className={loading ? "animate-spin" : undefined} />
        {t(loaded ? "status.linkDiag.refresh" : "status.linkDiag.load")}
      </Button>
      {!serviceRunning && <span className="text-xs text-muted-foreground">{t("adv.needService")}</span>}
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {serviceRunning && diag && <LinkDiagnosticDetails diagnostic={diag} />}
    {serviceRunning && loaded && !diag && !error && <p className="text-sm text-muted-foreground">{t("status.linkDiag.empty")}</p>}
  </>;
}
