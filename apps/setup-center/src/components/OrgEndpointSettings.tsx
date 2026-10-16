import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { safeFetch } from "../providers";
import { Button } from "./ui/button";
import { Label } from "./ui/label";

type Endpoint = { name: string; model: string; status: string };

export function OrgEndpointSettings({
  apiBaseUrl, visible, endpoint, policy, disabled, onEndpointChange, onPolicyChange,
}: {
  apiBaseUrl: string;
  visible: boolean;
  endpoint: string | null;
  policy: "prefer" | "require";
  disabled: boolean;
  onEndpointChange: (endpoint: string | null) => void;
  onPolicyChange: (policy: "prefer" | "require") => void;
}) {
  const { t } = useTranslation();
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const requestId = useRef(0);
  const refresh = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setFailed(false);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/models`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.models)) throw new Error("Invalid model list");
      if (id === requestId.current) setEndpoints(data.models);
    } catch {
      if (id === requestId.current) setFailed(true);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    setEndpoints([]);
    if (visible) void refresh();
    return () => { ++requestId.current; };
  }, [refresh, visible]);

  return <>
    <div className="flex gap-2">
      <select
        aria-label={t("org.editor.llmEndpointTitle")}
        value={endpoint || ""}
        disabled={disabled || loading}
        onChange={(event) => onEndpointChange(event.target.value || null)}
        className="h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-xs"
      >
        <option value="">{t("org.editor.llmEndpointDefault")}</option>
        {endpoint && !endpoints.some((item) => item.name === endpoint) && (
          <option value={endpoint}>{endpoint} ({t("org.editor.llmEndpointUnlisted")})</option>
        )}
        {endpoints.map((item) => <option key={item.name} value={item.name}>
          {item.name} ({item.model}){item.status !== "healthy" ? ` — ${t("org.editor.llmEndpointUnhealthy")}` : ""}
        </option>)}
      </select>
      <Button type="button" variant="outline" size="sm" disabled={disabled || loading} onClick={() => void refresh()}>
        {t("org.editor.llmEndpointRefresh")}
      </Button>
    </div>
    {loading && <p role="status" className="text-[11px] text-muted-foreground">{t("org.editor.llmEndpointLoading")}</p>}
    {failed && <p role="alert" className="text-[11px] text-destructive">{t("org.editor.llmEndpointLoadError")}</p>}
    {!loading && !failed && endpoints.length === 0 && (
      <p className="text-[11px] text-muted-foreground">{t("org.editor.llmEndpointEmpty")}</p>
    )}
    {disabled && <p className="text-[11px] text-muted-foreground">{t("org.editor.llmEndpointLocked")}</p>}
    <div className="space-y-1.5">
      <Label className="text-xs opacity-70">{t("org.editor.llmEndpointPolicy")}</Label>
      <select
        aria-label={t("org.editor.llmEndpointPolicy")}
        value={policy}
        onChange={(event) => onPolicyChange(event.target.value as "prefer" | "require")}
        className="h-8 w-full rounded-md border border-input bg-background px-3 text-xs"
        disabled={disabled || !endpoint}
      >
        <option value="prefer">{t("org.editor.llmEndpointPolicyPrefer")}</option>
        <option value="require">{t("org.editor.llmEndpointPolicyRequire")}</option>
      </select>
      <p className="text-[11px] text-muted-foreground">{t("org.editor.llmEndpointPolicyHint")}</p>
    </div>
  </>;
}
