import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { safeFetch } from "../../../providers";
import type { OptionalFeatureInstallRequest } from "../utils/chatTypes";

function formatBytes(value = 0): string {
  if (value <= 0) return "0 MB";
  return `${(value / 1024 / 1024).toFixed(value >= 100 * 1024 * 1024 ? 0 : 1)} MB`;
}

function ProgressRow({ label, value, detail }: { label: string; value: number; detail?: string }) {
  const percent = Math.max(0, Math.min(100, value));
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
        <span>{label}</span>
        <span style={{ opacity: 0.65 }}>{detail || `${percent}%`}</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--panel2)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", background: "var(--brand)", transition: "width 0.2s" }} />
      </div>
    </div>
  );
}

export function OptionalFeatureInstallCard({
  request: initialRequest,
  apiBaseUrl,
}: {
  request: OptionalFeatureInstallRequest;
  apiBaseUrl: string;
}) {
  const { t } = useTranslation();
  const [request, setRequest] = useState(initialRequest);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setRequest(initialRequest), [initialRequest]);

  const refresh = useCallback(async () => {
    const response = await safeFetch(
      `${apiBaseUrl}/api/optional-features/${encodeURIComponent(request.request_id)}`,
    );
    if (!response.ok) return;
    setRequest(await response.json() as OptionalFeatureInstallRequest);
  }, [apiBaseUrl, request.request_id]);

  useEffect(() => {
    void refresh().catch(() => {});
  }, [refresh]);

  useEffect(() => {
    if (request.status !== "installing") return;
    const timer = window.setInterval(() => void refresh().catch(() => {}), 1000);
    return () => window.clearInterval(timer);
  }, [refresh, request.status]);

  const install = async () => {
    if (submitting || request.status === "installing") return;
    setSubmitting(true);
    setError("");
    setRequest((current) => ({ ...current, status: "installing", progress: 1, message: "准备安装" }));
    try {
      const response = await safeFetch(
        `${apiBaseUrl}/api/optional-features/${encodeURIComponent(request.request_id)}/install`,
        { method: "POST" },
      );
      const payload = await response.json().catch(() => null) as OptionalFeatureInstallRequest | { detail?: string } | null;
      if (!response.ok) throw new Error((payload as { detail?: string } | null)?.detail || "安装失败");
      setRequest(payload as OptionalFeatureInstallRequest);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      await refresh().catch(() => {});
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await safeFetch(
        `${apiBaseUrl}/api/optional-features/${encodeURIComponent(request.request_id)}/cancel`,
        { method: "POST" },
      );
      const payload = await response.json().catch(() => null) as OptionalFeatureInstallRequest | { detail?: string } | null;
      if (!response.ok) throw new Error((payload as { detail?: string } | null)?.detail || "取消失败");
      setRequest(payload as OptionalFeatureInstallRequest);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSubmitting(false);
    }
  };

  const terminal = request.status === "installed" || request.status === "cancelled";
  return (
    <div style={{ margin: "8px 0", padding: 14, border: "1px solid var(--line)", borderRadius: 8, background: "var(--panel)" }}>
      <div style={{ fontSize: 14, fontWeight: 700 }}>{request.title}</div>
      <div style={{ marginTop: 5, fontSize: 12, opacity: 0.72, lineHeight: 1.5 }}>{request.description}</div>
      <div style={{ marginTop: 10, display: "grid", gap: 5 }}>
        {request.components.map((component) => (
          <div key={component.id} style={{ fontSize: 12, display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span>{component.name}</span><span style={{ opacity: 0.55 }}>{component.id}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, fontSize: 12, opacity: 0.72 }}>
        {t("chat.optionalFeatureDownload", "预计下载 {{download}} MB，占用磁盘约 {{disk}} MB", {
          download: request.estimated_download_mb,
          disk: request.estimated_disk_mb,
        })}
      </div>
      {(request.status === "installing" || request.status === "installed" || request.status === "failed") && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          <ProgressRow
            label={request.current_item ? `下载 · ${request.current_item}` : "下载"}
            value={request.phase === "installing" || request.phase === "complete" ? 100 : request.phase_progress || 0}
            detail={request.total_bytes ? `${formatBytes(request.downloaded_bytes)} / ${formatBytes(request.total_bytes)}` : undefined}
          />
          <ProgressRow
            label="安装"
            value={request.install_progress || (request.phase === "complete" ? 100 : 0)}
          />
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 12, color: request.status === "failed" ? "var(--danger)" : "var(--text)" }}>
        {request.message}
      </div>
      {error && <div style={{ marginTop: 6, fontSize: 12, color: "var(--danger)" }}>{error}</div>}
      {!terminal && request.status !== "installing" && (
        <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" className="btnSecondary" disabled={submitting} onClick={() => void cancel()}>
            {t("common.cancel", "取消")}
          </button>
          <button type="button" className="btnPrimary" disabled={submitting} onClick={() => void install()}>
            {request.status === "failed" ? t("common.retry", "重试") : t("chat.downloadAndInstall", "下载并安装")}
          </button>
        </div>
      )}
    </div>
  );
}
