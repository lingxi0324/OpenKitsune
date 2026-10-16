import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { safeFetch } from "../providers";
import { notifyError, notifySuccess } from "../utils/notify";

type Target = { conversation_id: string; profile_id: string; conversation_title?: string; profile_name?: string };
const targetKey = (target: Target) => JSON.stringify([target.conversation_id, target.profile_id]);

export function CacheMaintenancePanel({ httpApiBase, serviceRunning, disabled = false }: {
  httpApiBase: () => string;
  serviceRunning: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [targets, setTargets] = useState<Target[]>([]);
  const [selected, setSelected] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const base = httpApiBase();
  const target = targets.find(item => targetKey(item) === selected);
  const unavailable = disabled || !serviceRunning || loading || clearing;
  const targetLabel = (item: Target) => {
    if (!item.conversation_id) return t("status.linkDiag.defaultTarget");
    const title = item.conversation_title?.trim() || t("status.linkDiag.untitledConversation");
    const agentName = item.profile_name?.trim() || t(item.profile_id === "default" ? "status.linkDiag.defaultTarget" : "status.linkDiag.unnamedAgent");
    return `${title} · ${agentName}`;
  };
  const labels = targets.map(targetLabel);

  useEffect(() => {
    generation.current++;
    setTargets([]); setSelected(""); setLoaded(false); setError("");
    setLoading(false); setClearing(false);
    return () => { generation.current++; };
  }, [base, serviceRunning]);

  async function loadTargets() {
    if (unavailable) return;
    const request = ++generation.current;
    setLoading(true); setError("");
    try {
      const response = await safeFetch(`${base}/api/diagnostics/cache-targets`);
      if (!response.ok) throw new Error();
      const body = await response.json();
      if (request !== generation.current) return;
      const next: Target[] = Array.isArray(body.targets) ? body.targets : [];
      setTargets(next); setLoaded(true);
      // Never choose a different target implicitly when an instance disappears.
      if (selected && !next.some(item => targetKey(item) === selected)) {
        setSelected("");
        setError(t("status.linkDiag.expiredTarget"));
      }
    } catch {
      if (request === generation.current) setError(t("status.linkDiag.targetsFailed"));
    } finally { if (request === generation.current) setLoading(false); }
  }

  async function clear() {
    if (unavailable || !target) return;
    const request = ++generation.current;
    const query = new URLSearchParams();
    if (target.conversation_id) query.set("conversation_id", target.conversation_id);
    if (target.profile_id) query.set("profile_id", target.profile_id);
    query.set("require_runtime", "true");
    setClearing(true); setError("");
    try {
      const response = await safeFetch(`${base}/api/diagnostics/clear-session-caches?${query}`, { method: "POST" });
      const body = await response.json();
      if (request !== generation.current) return;
      if (response.status === 404) {
        setSelected("");
        throw new Error(t("status.linkDiag.expiredTarget"));
      }
      if (!response.ok || !body.ok) throw new Error(t("status.linkDiag.clearFailed"));
      if (Object.values(body.cleared || {}).some(value => value === false)) {
        throw new Error(t("status.linkDiag.clearPartial"));
      }
      notifySuccess(t("status.linkDiag.clearedHint"));
    } catch (e) {
      if (request === generation.current) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message); notifyError(message);
      }
    } finally { if (request === generation.current) setClearing(false); }
  }

  return <>
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" onClick={() => void loadTargets()} disabled={unavailable}>
        <RotateCw size={14} className={loading ? "animate-spin" : undefined} />
        {t(loaded ? "status.linkDiag.refreshTargets" : "status.linkDiag.loadTargets")}
      </Button>
      {!serviceRunning && <span className="text-xs text-muted-foreground">{t("adv.needService")}</span>}
    </div>
    {loaded && <div className="space-y-2">
      <Label htmlFor="cache-runtime-target">{t("status.linkDiag.target")}</Label>
      <Select value={selected} disabled={unavailable || targets.length === 0}
        onValueChange={value => { setSelected(value); setError(""); }}>
        <SelectTrigger id="cache-runtime-target" className="w-full">
          <SelectValue placeholder={t("status.linkDiag.chooseTarget")} />
        </SelectTrigger>
        <SelectContent>
          {targets.map((item, index) => <SelectItem key={targetKey(item)} value={targetKey(item)}>
            {labels.filter(label => label === labels[index]).length > 1
              ? t("status.linkDiag.numberedTarget", { name: labels[index], number: labels.slice(0, index + 1).filter(label => label === labels[index]).length })
              : labels[index]}
          </SelectItem>)}
        </SelectContent>
      </Select>
      {!targets.length && <p className="text-xs text-muted-foreground">{t("status.linkDiag.noTargets")}</p>}
    </div>}
    <p className="text-xs text-muted-foreground">{t("status.linkDiag.clearHint")}</p>
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" onClick={() => void clear()} disabled={unavailable || !target}>
        {clearing && <span className="spinner size-3.5" />}
        {t(clearing ? "status.linkDiag.clearing" : "status.linkDiag.clear")}
      </Button>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </>;
}
