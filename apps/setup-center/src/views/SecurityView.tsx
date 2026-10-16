import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  IconShield, IconPlus, IconX, IconTrash,
  IconChevronDown, IconChevronRight, IconClock, IconAlertCircle,
} from "../icons";
import { safeFetch } from "../providers";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { Loader2, LockKeyhole, RotateCw, Save, Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { PolicyV2MatrixView } from "./security/PolicyV2MatrixView";

type SecurityViewProps = {
  apiBaseUrl: string;
  serviceRunning: boolean;
};

type ZoneConfig = {
  workspace: string[];
  protected: string[];
};

type CommandConfig = {
  custom_critical: string[];
  custom_high: string[];
  excluded_patterns: string[];
  blocked_commands: string[];
};

type SandboxConfig = {
  enabled: boolean;
  backend: string;
  sandbox_risk_levels: string[];
  exempt_commands: string[];
};

type AuditEntry = {
  ts: number;
  tool: string;
  decision: string;
  reason: string;
  policy: string;
};

type CheckpointEntry = {
  checkpoint_id: string;
  timestamp: number;
  tool_name: string;
  description: string;
  file_count: number;
};

const ZONE_META: Record<string, { color: string; tw: string }> = {
  workspace: { color: "#22c55e", tw: "bg-emerald-500" },
  protected: { color: "#f59e0b", tw: "bg-amber-500" },
};

const BACKEND_OPTIONS = [
  { value: "auto", labelKey: "security.sandboxBackendAuto", available: true },
  { value: "none", labelKey: "security.sandboxBackendNone", available: true },
  { value: "low_integrity", labelKey: "security.sandboxBackendLowIntegrity", available: false },
  { value: "bubblewrap", labelKey: "security.sandboxBackendBubblewrap", available: false },
  { value: "seatbelt", labelKey: "security.sandboxBackendSeatbelt", available: false },
  { value: "docker", labelKey: "security.sandboxBackendDocker", available: false },
];

function errorMessage(err: unknown, fallback: string) {
  return err instanceof Error && err.message ? err.message : fallback;
}

type ConfirmConfig = {
  mode: string;
  timeout_seconds: number;
  default_on_timeout: "allow_once" | "deny";
  confirm_ttl: number;
};

type SelfProtectConfig = {
  enabled: boolean;
  protected_dirs: string[];
  death_switch_threshold: number;
  death_switch_total_multiplier: number;
  audit_to_file: boolean;
  audit_path: string;
  readonly_mode: boolean;
};

type AllowlistData = {
  commands: Array<Record<string, unknown>>;
  tools: Array<Record<string, unknown>>;
};

type TabId = "zones" | "commands" | "sandbox" | "audit" | "checkpoints" | "confirmation" | "selfprotection" | "imowner" | "dryrun" | "policy_v2_matrix";

// C9a §3: per-channel IM owner allowlist (调用 C8a backend)
type ImOwnerAllowlistEntry = {
  channel: string;
  configured: boolean;
  owners: string[];
};

// C9a §4: dry-run preview decision row
type DryRunDecision = {
  tool: string;
  tool_label_key?: string;
  params_preview: string;
  decision: string;
  decision_label_key?: string;
  reason: string;
  reason_code?: string;
  approval_class: string | null;
  approval_class_label_key?: string | null;
  risk_level: string;
  safety_immune_match: string | null;
  effective_confirmation_mode?: string;
  security_profile?: string;
};
type PermissionMode = "trust" | "protect" | "strict" | "off" | "custom";
// The API contract currently requires this exact value; the phrase shown to the user is localized.
const OFF_ACK_API_PHRASE = "确认风险同意关闭";

export default function SecurityView({ apiBaseUrl, serviceRunning }: SecurityViewProps) {
  const { t } = useTranslation();
  const offAckPhraseExpected = t("security.offAckPhrase");

  const [tab, setTab] = useState<TabId>("zones");
  const [zones, setZones] = useState<ZoneConfig>({ workspace: [], protected: [] });
  const [commands, setCommands] = useState<CommandConfig>({ custom_critical: [], custom_high: [], excluded_patterns: [], blocked_commands: [] });
  const [sandbox, setSandbox] = useState<SandboxConfig>({ enabled: true, backend: "auto", sandbox_risk_levels: ["HIGH"], exempt_commands: [] });
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointEntry[]>([]);
  const [confirmConfig, setConfirmConfig] = useState<ConfirmConfig>({ mode: "trust", timeout_seconds: 60, default_on_timeout: "deny", confirm_ttl: 120 });
  const [selfProtect, setSelfProtect] = useState<SelfProtectConfig>({ enabled: true, protected_dirs: ["data/", "identity/", "logs/", "src/"], death_switch_threshold: 3, death_switch_total_multiplier: 3, audit_to_file: true, audit_path: "", readonly_mode: false });
  const [allowlist, setAllowlist] = useState<AllowlistData>({ commands: [], tools: [] });
  // 出厂默认 = "trust"：与后端 PolicyConfigV2 schema 一致。GET /security/options
  // 在配置缺失时也返回 trust，下面 fetchAll 会用真实值覆盖；这里仅决定第一次
  // 渲染（loading）时的占位。
  const [permissionMode, setPermissionMode] = useState<PermissionMode>("trust");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [savingAction, setSavingAction] = useState<string | null>(null);
  const [loadingAll, setLoadingAll] = useState(false);
  const [refreshingAudit, setRefreshingAudit] = useState(false);
  const [refreshingCheckpoints, setRefreshingCheckpoints] = useState(false);
  const [rewindingId, setRewindingId] = useState<string | null>(null);
  // C9a §3 / §4 state
  const [imOwnerEntries, setImOwnerEntries] = useState<ImOwnerAllowlistEntry[]>([]);
  const [loadingImOwner, setLoadingImOwner] = useState(false);
  const [dryRunDecisions, setDryRunDecisions] = useState<DryRunDecision[]>([]);
  const [loadingDryRun, setLoadingDryRun] = useState(false);
  const [offDialogOpen, setOffDialogOpen] = useState(false);
  const [offAckPhrase, setOffAckPhrase] = useState("");
  const [offAckError, setOffAckError] = useState("");
  const [customSwitchDialog, setCustomSwitchDialog] = useState<{
    endpoint: string;
    body: unknown;
    successKey: string;
  } | null>(null);
  const [rewindDialog, setRewindDialog] = useState<CheckpointEntry | null>(null);
  const saving = savingAction !== null;

  const api = useCallback(async (path: string, method = "GET", body?: unknown) => {
    const opts: RequestInit = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const res = await safeFetch(`${apiBaseUrl}${path}`, opts);
    const json = await res.json();
    if (method !== "GET" && json && json.status === "error") throw new Error(json.message || "Server error");
    return json;
  }, [apiBaseUrl]);

  const load = useCallback(async (showResult = false) => {
    if (!serviceRunning) {
      if (showResult) toast.error(t("security.backendOff"));
      return false;
    }
    setLoadingAll(true);
    try {
      const [modeRes, zRes, cRes, sRes, cfRes, spRes, alRes] = await Promise.all([
        api("/api/config/security-profile"),
        api("/api/config/security/path-policy"),
        api("/api/config/security/commands"),
        api("/api/config/security/sandbox"),
        api("/api/config/security/confirmation"),
        api("/api/config/security/self-protection"),
        api("/api/config/security/allowlist"),
      ]);
      const m = modeRes?.current;
      if (m === "trust" || m === "protect" || m === "strict" || m === "off" || m === "custom") {
        setPermissionMode(m);
        setShowAdvanced(m === "custom");
      }
      if (zRes && Array.isArray(zRes.workspace_paths)) {
        setZones({
          workspace: zRes.workspace_paths,
          protected: zRes.safety_immune_paths || [],
        });
      }
      if (cRes && Array.isArray(cRes.blocked_commands)) setCommands(cRes);
      if (sRes && typeof sRes.enabled === "boolean") setSandbox(sRes);
      if (cfRes && cfRes.mode) {
        setConfirmConfig({
          mode: String(cfRes.mode),
          timeout_seconds: Number(cfRes.timeout_seconds) || 60,
          default_on_timeout:
            cfRes.default_on_timeout === "allow_once" ? "allow_once" : "deny",
          confirm_ttl: Number(cfRes.confirm_ttl) || 120,
        });
      }
      if (spRes && spRes.enabled !== undefined) setSelfProtect(spRes);
      if (alRes && (alRes.commands || alRes.tools)) setAllowlist(alRes);
      if (showResult) toast.success(t("security.refreshAllDone"));
      return true;
    } catch (err) {
      if (showResult) {
        toast.error(t("security.refreshFailed"), {
          description: errorMessage(err, t("security.refreshFailed")),
        });
      }
      return false;
    } finally {
      setLoadingAll(false);
    }
  }, [api, serviceRunning, t]);

  useEffect(() => { load(); }, [load]);

  const loadAudit = useCallback(async (showResult = false) => {
    if (!serviceRunning) {
      if (showResult) toast.error(t("security.backendOff"));
      return false;
    }
    setRefreshingAudit(true);
    try {
      const res = await api("/api/config/security/audit");
      setAudit(res.entries || []);
      if (showResult) toast.success(t("security.auditRefreshed"));
      return true;
    } catch (err) {
      if (showResult) {
        toast.error(t("security.refreshFailed"), {
          description: errorMessage(err, t("security.refreshFailed")),
        });
      }
      return false;
    } finally {
      setRefreshingAudit(false);
    }
  }, [api, serviceRunning, t]);

  const loadCheckpoints = useCallback(async (showResult = false) => {
    if (!serviceRunning) {
      if (showResult) toast.error(t("security.backendOff"));
      return false;
    }
    setRefreshingCheckpoints(true);
    try {
      const res = await api("/api/config/security/checkpoints");
      setCheckpoints(res.checkpoints || []);
      if (showResult) toast.success(t("security.checkpointsRefreshed"));
      return true;
    } catch (err) {
      if (showResult) {
        toast.error(t("security.refreshFailed"), {
          description: errorMessage(err, t("security.refreshFailed")),
        });
      }
      return false;
    } finally {
      setRefreshingCheckpoints(false);
    }
  }, [api, serviceRunning, t]);

  const loadAllowlist = useCallback(async () => {
    if (!serviceRunning) return;
    try {
      const res = await api("/api/config/security/allowlist");
      if (res.commands || res.tools) setAllowlist(res);
    } catch (err) {
      toast.error(t("security.refreshFailed"), {
        description: errorMessage(err, t("security.refreshFailed")),
      });
    }
  }, [api, serviceRunning, t]);

  // C9a §3: load IM channels + their owner allowlists (one fetch per channel)
  const loadImOwnerAllowlist = useCallback(async (showResult = false) => {
    if (!serviceRunning) return;
    setLoadingImOwner(true);
    try {
      const channelsRes = await api("/api/im/channels");
      const channels: string[] = (channelsRes?.channels || []).map(
        (c: { channel?: string }) => String(c?.channel || ""),
      ).filter(Boolean);
      const entries: ImOwnerAllowlistEntry[] = await Promise.all(
        channels.map(async (ch) => {
          const r = await api(`/api/im/owner-allowlist?channel=${encodeURIComponent(ch)}`);
          return {
            channel: ch,
            configured: Boolean(r?.configured),
            owners: Array.isArray(r?.owners) ? r.owners.map(String) : [],
          };
        }),
      );
      setImOwnerEntries(entries);
      if (showResult) toast.success(t("security.imOwnerRefreshed"));
    } catch (err) {
      if (showResult) toast.error(t("security.refreshFailed"), {
        description: errorMessage(err, t("security.refreshFailed")),
      });
    } finally {
      setLoadingImOwner(false);
    }
  }, [api, serviceRunning, t]);

  const saveImOwnerAllowlist = useCallback(
    async (channel: string, owners: string[] | null) => {
      setSavingAction(`imowner-${channel}`);
      try {
        await api("/api/im/owner-allowlist", "POST", { channel, owners });
        toast.success(
          owners === null
            ? t("security.imOwnerCleared")
            : t("security.imOwnerSaved"),
        );
        await loadImOwnerAllowlist(false);
      } catch (err) {
        toast.error(t("security.saveFailed"), {
          description: errorMessage(err, t("security.saveFailed")),
        });
      } finally {
        setSavingAction(null);
      }
    },
    [api, loadImOwnerAllowlist, t],
  );

  // C9a §4: dry-run preview against current persisted policy config
  const runDryRunPreview = useCallback(async () => {
    if (!serviceRunning) return;
    setLoadingDryRun(true);
    try {
      const res = await api("/api/config/security/preview", "POST", {});
      setDryRunDecisions(Array.isArray(res?.decisions) ? res.decisions : []);
    } catch (err) {
      toast.error(t("security.dryRunFailed"), {
        description: errorMessage(err, t("security.dryRunFailed")),
      });
    } finally {
      setLoadingDryRun(false);
    }
  }, [api, serviceRunning, t]);

  useEffect(() => {
    if (tab === "audit") loadAudit();
    if (tab === "checkpoints") loadCheckpoints();
    if (tab === "imowner") loadImOwnerAllowlist();
    if (tab === "dryrun" && dryRunDecisions.length === 0) runDryRunPreview();
  // dryRunDecisions intentionally omitted: only trigger initial load when first opening tab
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, loadAudit, loadCheckpoints, loadImOwnerAllowlist, runDryRunPreview]);

  const performSave = async (endpoint: string, body: unknown, successKey: string) => {
    setSavingAction(endpoint);
    try {
      await api(endpoint, "POST", body);
      toast.success(t(`security.${successKey}`));
      await load(false);
    } catch (err) {
      toast.error(t("security.saveFailed"), {
        description: errorMessage(err, t("security.saveFailed")),
      });
    } finally {
      setSavingAction(null);
    }
  };

  const doSave = async (endpoint: string, body: unknown, successKey: string) => {
    if (
      endpoint.startsWith("/api/config/security/")
      && endpoint !== "/api/config/security-profile"
      && permissionMode !== "custom"
    ) {
      setCustomSwitchDialog({ endpoint, body, successKey });
      return;
    }
    await performSave(endpoint, body, successKey);
  };

  const confirmCustomSwitch = async () => {
    const pending = customSwitchDialog;
    if (!pending) return;
    setCustomSwitchDialog(null);
    await performSave(pending.endpoint, pending.body, pending.successKey);
  };

  const applyPermissionMode = async (mode: PermissionMode, ack_phrase?: string) => {
    const previousMode = permissionMode;
    setPermissionMode(mode);
    setSavingAction("security-profile");
    try {
      await api("/api/config/security-profile", "POST", { profile: mode, ack_phrase });
      toast.success(t("security.permissionModeSaved"));
      await load();
      setShowAdvanced(mode === "custom");
    } catch (err) {
      setPermissionMode(previousMode);
      toast.error(t("security.saveFailed"), {
        description: errorMessage(err, t("security.saveFailed")),
      });
    } finally {
      setSavingAction(null);
    }
  };

  const selectPermissionMode = async (mode: PermissionMode) => {
    if (mode === "off") {
      setOffAckPhrase("");
      setOffAckError("");
      setOffDialogOpen(true);
      return;
    }
    await applyPermissionMode(mode);
  };

  const confirmOffMode = async () => {
    if (offAckPhrase.trim() !== offAckPhraseExpected) {
      setOffAckError(t("security.offAckMismatch"));
      return;
    }
    setOffDialogOpen(false);
    await applyPermissionMode("off", OFF_ACK_API_PHRASE);
  };

  const requestRewind = (cp: CheckpointEntry) => {
    setRewindDialog(cp);
  };

  const confirmRewind = async () => {
    const cp = rewindDialog;
    if (!cp) return;
    setRewindDialog(null);
    setRewindingId(cp.checkpoint_id);
    try {
      await api("/api/config/security/checkpoint/rewind", "POST", {
        checkpoint_id: cp.checkpoint_id,
      });
      toast.success(t("security.rewound"));
      await loadCheckpoints(false);
    } catch (err) {
      toast.error(t("security.rewindFailed"), {
        description: errorMessage(err, t("security.rewindFailed")),
      });
    } finally {
      setRewindingId(null);
    }
  };

  if (!serviceRunning) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
        <ShieldAlert size={32} className="mb-3 opacity-50" />
        <p className="text-sm">{t("security.backendOff")}</p>
      </div>
    );
  }

  const deleteAllowlistEntry = async (entryType: string, index: number) => {
    try {
      await api(`/api/config/security/allowlist/${entryType}/${index}`, "DELETE");
      toast.success(t("security.allowlistDeleted"));
      loadAllowlist();
    } catch (err) {
      toast.error(t("security.saveFailed"), {
        description: errorMessage(err, t("security.saveFailed")),
      });
    }
  };

  const resetDeathSwitch = async () => {
    setSavingAction("death-switch-reset");
    try {
      await api("/api/config/security/death-switch/reset", "POST");
      toast.success(t("security.deathSwitchReset"));
      setSelfProtect((p) => ({ ...p, readonly_mode: false }));
    } catch (err) {
      toast.error(t("security.saveFailed"), {
        description: errorMessage(err, t("security.saveFailed")),
      });
    } finally {
      setSavingAction(null);
    }
  };

  const TABS: { id: TabId; labelKey: string }[] = [
    { id: "confirmation", labelKey: "security.confirmation" },
    // C23 P2-1: policy_v2 审批矩阵（session_role × confirmation_mode × ApprovalClass）
    { id: "policy_v2_matrix", labelKey: "security.policyV2Matrix" },
    { id: "zones", labelKey: "security.zones" },
    { id: "commands", labelKey: "security.commands" },
    { id: "sandbox", labelKey: "security.sandbox" },
    { id: "selfprotection", labelKey: "security.selfProtection" },
    { id: "imowner", labelKey: "security.imOwner" },
    { id: "dryrun", labelKey: "security.dryRun" },
    { id: "audit", labelKey: "security.audit" },
    { id: "checkpoints", labelKey: "security.checkpoints" },
  ];

  // 信息架构：3 个并列机制页 + 1 个观测分组。
  // 把原本平铺的 10 个 tab 按"功能维度"分组，让用户能一眼分辨：
  //   1. 工具执行：Agent 跑工具时怎么确认/审计/拦截
  //   2. 沙箱：高风险命令在隔离环境里跑
  //   3. 路径白名单：Agent 可以访问/写入哪些目录（硬边界）
  //   4. 观测/历史：策略预览、审计日志、文件快照（事后回溯类）
  const TAB_GROUPS: {
    id: string;
    titleKey: string;
    descKey: string;
    tabs: TabId[];
  }[] = [
    {
      id: "execution",
      titleKey: "security.groupExecutionTitle",
      descKey: "security.groupExecutionDesc",
      tabs: ["confirmation", "policy_v2_matrix", "commands", "selfprotection", "imowner"],
    },
    {
      id: "sandbox",
      titleKey: "security.groupSandboxTitle",
      descKey: "security.groupSandboxDesc",
      tabs: ["sandbox"],
    },
    {
      id: "paths",
      titleKey: "security.groupPathsTitle",
      descKey: "security.groupPathsDesc",
      tabs: ["zones"],
    },
    {
      id: "observability",
      titleKey: "security.groupObservabilityTitle",
      descKey: "security.groupObservabilityDesc",
      tabs: ["dryrun", "audit", "checkpoints"],
    },
  ];
  const advancedVisible = permissionMode === "custom" || showAdvanced;
  const MODE_CARDS: Array<{ id: PermissionMode; title: string; desc: string; icon: typeof ShieldCheck; tone: string }> = [
    {
      id: "trust",
      title: t("security.modeTrustTitle"),
      desc: t("security.modeTrustCardDesc"),
      icon: ShieldCheck,
      tone: "text-emerald-600 bg-emerald-500/10 border-emerald-500/20",
    },
    {
      id: "protect",
      title: t("security.modeProtectTitle"),
      desc: t("security.modeProtectCardDesc"),
      icon: Shield,
      tone: "text-blue-600 bg-blue-500/10 border-blue-500/20",
    },
    {
      id: "strict",
      title: t("security.modeStrictTitle"),
      desc: t("security.modeStrictCardDesc"),
      icon: LockKeyhole,
      tone: "text-amber-600 bg-amber-500/10 border-amber-500/20",
    },
    {
      id: "off",
      title: t("security.modeOffTitle"),
      desc: t("security.modeOffCardDesc"),
      icon: ShieldAlert,
      tone: "text-red-600 bg-red-500/10 border-red-500/20",
    },
    {
      id: "custom",
      title: t("security.modeCustomTitle"),
      desc: t("security.modeCustomCardDesc"),
      icon: Shield,
      tone: "text-purple-600 bg-purple-500/10 border-purple-500/20",
    },
  ];

  return (
    <div className="mx-auto max-w-[1040px] space-y-3.5 px-5 py-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <h2 className="truncate text-xl font-semibold tracking-tight" title={t("security.title")}>
            {t("security.title")}
          </h2>
          <p className="truncate text-[13px] leading-5 text-muted-foreground" title={t("security.desc")}>
            {t("security.desc")}
          </p>
        </div>
        <Button variant="outline" size="sm" className="h-8 shrink-0" onClick={() => load(true)} disabled={loadingAll || saving}>
          <RotateCw size={14} className={cn("mr-1.5", loadingAll && "animate-spin")} />
          {t("security.refreshAll")}
        </Button>
      </div>

      {/* Mode switch */}
      <Card className="gap-0 border-border/70 py-0 shadow-sm">
        <CardHeader className="px-4 py-3">
          <CardTitle className="text-[13px] font-semibold">{t("security.permissionMode")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-4">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {MODE_CARDS.map((mode) => {
              const active = permissionMode === mode.id;
              const ModeIcon = mode.icon;
              return (
                <button
                  key={mode.id}
                  type="button"
                  disabled={saving}
                  onClick={() => selectPermissionMode(mode.id)}
                  style={active ? { backgroundColor: "#2563eb", borderColor: "#2563eb", color: "#ffffff" } : undefined}
                  className={cn(
                    "flex h-[104px] min-w-0 flex-col justify-center overflow-hidden rounded-lg border px-2.5 py-3 text-left transition-all",
                    active
                      ? "shadow-md shadow-blue-600/25 ring-1 ring-blue-500/40"
                      : "border-border/70 hover:bg-muted/40",
                  )}
                >
                  <div className="flex h-7 min-w-0 items-center gap-2">
                    <span className="flex min-w-0 flex-1 items-center gap-2 text-sm font-semibold">
                      <span
                        className={cn(
                          "grid size-6 shrink-0 place-items-center rounded-md border",
                          active
                            ? "border-white/30 bg-white/20 text-white"
                            : mode.tone,
                        )}
                      >
                        <ModeIcon size={14} />
                      </span>
                      <span className={cn("min-w-0 flex-1 truncate", active && "text-white")}>
                        {mode.title}
                      </span>
                    </span>
                  </div>
                  <p
                    className={cn(
                      "mt-2 h-10 overflow-hidden text-[11px] leading-5",
                      active ? "text-white/85" : "text-muted-foreground",
                    )}
                    style={{
                      display: "-webkit-box",
                      WebkitBoxOrient: "vertical",
                      WebkitLineClamp: 2,
                    }}
                  >
                    {mode.desc}
                  </p>
                </button>
              );
            })}
          </div>
          {permissionMode !== "custom" && (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
              <p className="text-[12px] leading-5 text-muted-foreground">
                {t("security.trustModeAdvancedHint")}
              </p>
              <Button variant="outline" size="sm" className="h-8 shrink-0" onClick={() => setShowAdvanced((v) => !v)}>
                {showAdvanced ? t("security.hideAdvanced") : t("security.showAdvanced")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {advancedVisible && (
        <>
      {/* 信息架构重构：把 10 个原始 tab 按"工具执行 / 沙箱 / 路径白名单 / 观测"
          四类分组渲染。每个 group 自带标题与短句解释，让用户一眼看清"这个
          机制管什么"。tab 状态本身仍是平铺 TabId，避免 deep nesting 改动。 */}
      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
        {TAB_GROUPS.map((group) => {
          const groupTabs = TABS.filter((tb) => group.tabs.includes(tb.id));
          if (groupTabs.length === 0) return null;
          const active = group.tabs.includes(tab);
          return (
            <div
              key={group.id}
              className={cn(
                "rounded-lg border px-3 py-2.5 transition-colors",
                active ? "border-primary/40 bg-primary/[0.03]" : "border-border/60 bg-muted/10",
              )}
            >
              <div className="mb-2 space-y-0.5">
                <div className="text-[12px] font-semibold tracking-wide text-foreground/90">
                  {t(group.titleKey)}
                </div>
                <div className="text-[11px] leading-4 text-muted-foreground">
                  {t(group.descKey)}
                </div>
              </div>
              <div className="overflow-x-auto pb-0.5">
                <ToggleGroup
                  type="single"
                  value={tab}
                  onValueChange={(v) => { if (v) setTab(v as TabId); }}
                  variant="outline"
                  className="min-w-max flex-wrap justify-start gap-1"
                >
                  {groupTabs.map((tb) => (
                    <ToggleGroupItem
                      key={tb.id}
                      value={tb.id}
                      className="h-7 rounded-md px-2.5 text-[11px] data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
                      title={t(tb.labelKey)}
                    >
                      {t(tb.labelKey)}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
            </div>
          );
        })}
      </div>

      {/* C23 P2-1: policy_v2 审批矩阵（在 confirmation tab 之前渲染对应 case） */}
      {tab === "policy_v2_matrix" && <PolicyV2MatrixView apiBaseUrl={apiBaseUrl} />}

      {/* Confirmation */}
      {tab === "confirmation" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="border-b border-border/50 px-4 py-2.5">
            <CardTitle className="text-sm font-semibold">{t("security.confirmation")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-4 pb-4 pt-3">
            <p className="text-xs leading-5 text-muted-foreground">{t("security.confirmationDesc")}</p>
            <div className="max-w-md space-y-3.5">
              {/* Mode selector */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.confirmMode")}</Label>
                <Select value={confirmConfig.mode} onValueChange={(v) => setConfirmConfig((p) => ({ ...p, mode: v }))}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="trust">{t("security.confirmModeTrust")}</SelectItem>
                    <SelectItem value="default">{t("security.confirmModeDefault")}</SelectItem>
                    <SelectItem value="accept_edits">{t("security.confirmModeAcceptEdits")}</SelectItem>
                    <SelectItem value="strict">{t("security.confirmModeStrict")}</SelectItem>
                    <SelectItem value="dont_ask">{t("security.confirmModeDontAsk")}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {t("security.confirmModePathHint")}
                </p>
              </div>
              {/* Timeout */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.confirmTimeout")}</Label>
                <Input type="number" value={confirmConfig.timeout_seconds} onChange={(e) => setConfirmConfig((p) => ({ ...p, timeout_seconds: parseInt(e.target.value) || 60 }))} className="h-9 w-32" />
              </div>
              {/* Default on timeout */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.defaultOnTimeout")}</Label>
                <Select
                  value={confirmConfig.default_on_timeout}
                  onValueChange={(v) =>
                    setConfirmConfig((p) => ({
                      ...p,
                      default_on_timeout: v as ConfirmConfig["default_on_timeout"],
                    }))
                  }
                >
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="deny">{t("security.deny")}</SelectItem>
                    <SelectItem value="allow_once">{t("chat.securityAllowOnce")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {/* TTL */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.confirmTtl")}</Label>
                <Input type="number" value={confirmConfig.confirm_ttl} onChange={(e) => setConfirmConfig((p) => ({ ...p, confirm_ttl: parseFloat(e.target.value) || 120 }))} className="h-9 w-32" />
                <p className="text-xs text-muted-foreground">{t("security.confirmTtlDesc")}</p>
              </div>
            </div>

            {/* Persistent allowlist */}
            <div className="border-t border-border/50 pt-4 mt-4 space-y-3">
              <Label className="text-sm font-medium">{t("security.allowlist")}</Label>
              <p className="text-xs text-muted-foreground">{t("security.allowlistDesc")}</p>
              {allowlist.commands.length === 0 && allowlist.tools.length === 0 ? (
                <p className="text-xs text-muted-foreground italic py-2">{t("security.noAllowlist")}</p>
              ) : (
                <div className="space-y-2">
                  {allowlist.commands.map((entry, i) => (
                    <div key={`cmd-${i}`} className="flex items-center gap-2 group bg-muted/30 rounded-md px-3 py-2">
                      <Badge variant="outline" className="text-[10px]">CMD</Badge>
                      <code className="flex-1 text-xs font-mono">{String(entry.pattern || "")}</code>
                      <Button variant="ghost" size="icon" className="size-6 opacity-0 group-hover:opacity-100 text-destructive" onClick={() => deleteAllowlistEntry("command", i)}>
                        <IconTrash size={12} />
                      </Button>
                    </div>
                  ))}
                  {allowlist.tools.map((entry, i) => (
                    <div key={`tool-${i}`} className="flex items-center gap-2 group bg-muted/30 rounded-md px-3 py-2">
                      <Badge variant="outline" className="text-[10px]">TOOL</Badge>
                      <code className="flex-1 text-xs font-mono">{String(entry.name || "")}</code>
                      <Button variant="ghost" size="icon" className="size-6 opacity-0 group-hover:opacity-100 text-destructive" onClick={() => deleteAllowlistEntry("tool", i)}>
                        <IconTrash size={12} />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex justify-end pt-2 border-t border-border/50 mt-6 pt-4">
              <Button onClick={() => doSave("/api/config/security/confirmation", confirmConfig, "confirmationSaved")} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save size={14} className="mr-2" />}
                {t("security.save")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Self-protection */}
      {tab === "selfprotection" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="border-b border-border/50 px-4 py-2.5">
            <CardTitle className="text-sm font-semibold">{t("security.selfProtection")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-4 pb-4 pt-3">
            <p className="text-xs leading-5 text-muted-foreground">{t("security.selfProtectionDesc")}</p>
            <div className="max-w-lg space-y-3.5">
              {/* Enabled switch */}
              <div className="flex items-center justify-between rounded-lg border border-border/50 bg-muted/20 p-3">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium">{t("security.selfProtectionEnabled")}</Label>
                </div>
                <Switch checked={selfProtect.enabled} onCheckedChange={(v) => setSelfProtect((p) => ({ ...p, enabled: v }))} />
              </div>
              {/* Protected dirs */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.protectedDirs")}</Label>
                <TagEditor
                  label=""
                  items={selfProtect.protected_dirs}
                  onChange={(v) => setSelfProtect((p) => ({ ...p, protected_dirs: v }))}
                  placeholder="e.g. data/"
                />
              </div>
              {/* Death switch threshold */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.deathSwitchThreshold")}</Label>
                <Input type="number" value={selfProtect.death_switch_threshold} onChange={(e) => setSelfProtect((p) => ({ ...p, death_switch_threshold: parseInt(e.target.value) || 3 }))} className="h-9 w-32" />
              </div>
              {/* Total multiplier */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.deathSwitchMultiplier")}</Label>
                <Input type="number" value={selfProtect.death_switch_total_multiplier} onChange={(e) => setSelfProtect((p) => ({ ...p, death_switch_total_multiplier: parseInt(e.target.value) || 3 }))} className="h-9 w-32" />
                <p className="text-xs text-muted-foreground">{t("security.deathSwitchMultiplierDesc")}</p>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border/50 bg-muted/20 p-3">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium">{t("security.auditToFile")}</Label>
                  <p className="text-xs text-muted-foreground">{t("security.auditToFileDesc")}</p>
                </div>
                <Switch checked={selfProtect.audit_to_file} onCheckedChange={(v) => setSelfProtect((p) => ({ ...p, audit_to_file: v }))} />
              </div>
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.auditPath")}</Label>
                <Input
                  value={selfProtect.audit_path}
                  onChange={(e) => setSelfProtect((p) => ({ ...p, audit_path: e.target.value }))}
                  placeholder="data/audit/policy_decisions.jsonl"
                  className="h-9 font-mono text-sm"
                  disabled={!selfProtect.audit_to_file}
                />
              </div>
              {/* Readonly mode indicator + reset */}
              {selfProtect.readonly_mode && (
                <div className="flex items-center gap-3 p-4 bg-destructive/10 border border-destructive/30 rounded-lg">
                  <IconAlertCircle size={20} className="text-destructive shrink-0" />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-destructive">{t("security.readonlyModeActive")}</p>
                  </div>
                  <Button variant="destructive" size="sm" onClick={resetDeathSwitch} disabled={savingAction === "death-switch-reset"}>
                    {savingAction === "death-switch-reset" && <Loader2 className="mr-1 size-3 animate-spin" />}
                    {t("security.resetDeathSwitch")}
                  </Button>
                </div>
              )}
            </div>
            <div className="flex justify-end pt-2 border-t border-border/50 mt-6 pt-4">
              <Button onClick={() => doSave("/api/config/security/self-protection", selfProtect, "selfProtectionSaved")} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save size={14} className="mr-2" />}
                {t("security.save")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Zones */}
      {tab === "zones" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="border-b border-border/50 px-4 py-2.5">
            <CardTitle className="text-sm font-semibold">{t("security.zones")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3.5 px-4 pb-4 pt-3">
            {/* Profile-aware enforcement hint — trust 跳过 workspace 白名单；off 全部不生效 */}
            {permissionMode === "trust" && (
              <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                <IconAlertCircle size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-500" />
                <div className="flex-1 space-y-1">
                  <p className="text-sm font-medium">{t("security.zonesHintTrustTitle")}</p>
                  <p className="text-xs leading-5 text-muted-foreground">
                  {t("security.zonesHintTrustDesc")}
                  </p>
                </div>
              </div>
            )}
            {permissionMode === "off" && (
              <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3">
                <IconAlertCircle size={18} className="mt-0.5 shrink-0 text-destructive" />
                <div className="flex-1 space-y-1">
                  <p className="text-sm font-medium text-destructive">{t("security.zonesHintOffTitle")}</p>
                  <p className="text-xs leading-5 text-muted-foreground">
                  {t("security.zonesHintOffDesc")}
                  </p>
                </div>
              </div>
            )}
            <p className="text-xs leading-5 text-muted-foreground">
              {t("security.zonesIntro")}
            </p>
            <div className="grid grid-cols-1 gap-2.5">
              {(["workspace", "protected"] as const).map((zone) => (
                <ZonePanel
                  key={zone}
                  zone={zone}
                  paths={zones[zone] || []}
                  onChange={(paths) => setZones((prev) => ({ ...prev, [zone]: paths }))}
                />
              ))}
            </div>
            <div className="flex justify-end pt-2">
              <Button
                onClick={() => doSave("/api/config/security/path-policy", {
                  workspace_paths: zones.workspace,
                  safety_immune_paths: zones.protected,
                }, "zonesSaved")}
                disabled={saving}
              >
                {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save size={14} className="mr-2" />}
                {t("security.save")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Commands */}
      {tab === "commands" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="border-b border-border/50 px-4 py-2.5">
            <CardTitle className="text-sm font-semibold">{t("security.commands")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-4 pb-4 pt-3">
            <p className="text-xs leading-5 text-muted-foreground">{t("security.commandsDesc")}</p>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <TagEditor
                label={t("security.criticalPatterns")}
                items={commands.custom_critical}
                onChange={(v) => setCommands((p) => ({ ...p, custom_critical: v }))}
                placeholder={`e.g. rm\\s+-rf\\s+/`}
              />
              <TagEditor
                label={t("security.highPatterns")}
                items={commands.custom_high}
                onChange={(v) => setCommands((p) => ({ ...p, custom_high: v }))}
                placeholder="e.g. Remove-Item.*-Recurse"
              />
              <TagEditor
                label={t("security.excludedPatterns")}
                items={commands.excluded_patterns}
                onChange={(v) => setCommands((p) => ({ ...p, excluded_patterns: v }))}
                placeholder={t("security.excludedPh")}
              />
              <TagEditor
                label={t("security.blockedCommands")}
                items={commands.blocked_commands}
                onChange={(v) => setCommands((p) => ({ ...p, blocked_commands: v }))}
                placeholder="e.g. diskpart"
              />
            </div>
            <div className="flex justify-end pt-2 border-t border-border/50 mt-6 pt-4">
              <Button onClick={() => doSave("/api/config/security/commands", commands, "commandsSaved")} disabled={saving}>
                {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save size={14} className="mr-2" />}
                {t("security.save")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sandbox */}
      {tab === "sandbox" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="border-b border-border/50 px-4 py-2.5">
            <CardTitle className="text-sm font-semibold">{t("security.sandbox")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-4 pb-4 pt-3">
            <p className="text-xs leading-5 text-muted-foreground">{t("security.sandboxDesc")}</p>
            <div className="max-w-lg space-y-3.5">
              <div className="flex items-center justify-between rounded-lg border border-border/50 bg-muted/20 p-3">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium">{t("security.sandboxEnabled")}</Label>
                  <p className="text-xs text-muted-foreground">{t("security.sandboxEnabledDesc")}</p>
                </div>
                <Switch
                  checked={sandbox.enabled}
                  onCheckedChange={(v) => setSandbox((p) => ({ ...p, enabled: v }))}
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.sandboxBackend")}</Label>
                <Select
                  value={sandbox.backend === "none" ? "none" : "auto"}
                  onValueChange={(v) => setSandbox((p) => ({ ...p, backend: v, enabled: v === "none" ? false : p.enabled }))}
                >
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {BACKEND_OPTIONS.map((o) => (
                      <SelectItem key={o.value} value={o.value} disabled={!o.available}>
                        {t(o.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground pt-1">
                  {t("security.sandboxBackendDesc")}
                </p>
              </div>
              {/* Risk levels */}
              <div className="space-y-2">
                <Label className="text-sm font-medium">{t("security.sandboxRiskLevels")}</Label>
                <div className="flex gap-2 flex-wrap">
                  {["HIGH", "MEDIUM"].map((lvl) => (
                    <Badge
                      key={lvl}
                      variant={sandbox.sandbox_risk_levels.includes(lvl) ? "default" : "outline"}
                      className="cursor-pointer select-none"
                      onClick={() => {
                        setSandbox((p) => {
                          const has = p.sandbox_risk_levels.includes(lvl);
                          return { ...p, sandbox_risk_levels: has ? p.sandbox_risk_levels.filter((l) => l !== lvl) : [...p.sandbox_risk_levels, lvl] };
                        });
                      }}
                    >
                      {lvl}
                    </Badge>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">{t("security.sandboxRiskLevelsDesc")}</p>
              </div>
              {/* Exempt commands */}
              <TagEditor
                label={t("security.exemptCommands")}
                items={sandbox.exempt_commands}
                onChange={(v) => setSandbox((p) => ({ ...p, exempt_commands: v }))}
                placeholder="e.g. npm test"
              />
            </div>
            <div className="flex justify-end pt-2 border-t border-border/50 mt-6 pt-4">
              <Button
                onClick={() => doSave(
                  "/api/config/security/sandbox",
                  { ...sandbox, backend: sandbox.backend === "none" ? "none" : "auto" },
                  "sandboxSaved",
                )}
                disabled={saving}
              >
                {saving ? <Loader2 className="size-4 animate-spin mr-2" /> : <Save size={14} className="mr-2" />}
                {t("security.save")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Audit */}
      {tab === "audit" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border/50 px-4 py-2.5">
            <div className="space-y-1">
              <CardTitle className="text-sm font-semibold">{t("security.audit")}</CardTitle>
              <p className="text-xs text-muted-foreground">
                {t("security.auditCount", { count: audit.length })}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => loadAudit(true)} disabled={refreshingAudit} className="h-8">
              <RotateCw size={14} className={cn("mr-1.5", refreshingAudit && "animate-spin")} /> {t("security.refresh")}
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {audit.length === 0 ? (
              <div className="flex flex-col items-center py-10 text-center text-sm text-muted-foreground">
                <IconShield size={32} className="mb-3 opacity-20" />
                {t("security.noAudit")}
              </div>
            ) : (
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-[100px] text-xs h-10 px-5 font-medium">{t("security.auditDecision")}</TableHead>
                    <TableHead className="text-xs h-10 px-4 font-medium">{t("security.auditTool")}</TableHead>
                    <TableHead className="hidden sm:table-cell text-xs h-10 px-4 font-medium">{t("security.auditReason")}</TableHead>
                    <TableHead className="w-[120px] text-right text-xs h-10 px-5 font-medium">{t("security.auditTime")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...audit].reverse().map((e, i) => (
                    <TableRow key={i} className="border-b-border/50 transition-colors hover:bg-muted/20">
                      <TableCell className="px-5 py-3"><DecisionBadge decision={e.decision} /></TableCell>
                      <TableCell className="px-4 py-3 font-medium text-sm">{e.tool}</TableCell>
                      <TableCell className="hidden sm:table-cell px-4 py-3 text-muted-foreground text-xs max-w-[300px] truncate" title={e.reason}>{e.reason}</TableCell>
                      <TableCell className="px-5 py-3 text-right text-xs text-muted-foreground whitespace-nowrap font-mono">
                        {new Date(e.ts * 1000).toLocaleTimeString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* C9a §3: IM Owner Allowlist (per-channel) */}
      {tab === "imowner" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border/50 px-4 py-2.5">
            <div className="space-y-1">
              <CardTitle className="text-sm font-semibold">{t("security.imOwner")}</CardTitle>
              <p className="text-xs text-muted-foreground">
                {t("security.imOwnerDesc")}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => loadImOwnerAllowlist(true)} disabled={loadingImOwner} className="h-8">
              <RotateCw size={14} className={cn("mr-1.5", loadingImOwner && "animate-spin")} /> {t("security.refresh")}
            </Button>
          </CardHeader>
          <CardContent className="p-4 space-y-3">
            {imOwnerEntries.length === 0 ? (
              <div className="flex flex-col items-center py-8 text-center text-sm text-muted-foreground">
                <ShieldCheck size={32} className="mb-3 opacity-20" />
                {loadingImOwner
                  ? t("common.loading")
                  : t("security.imOwnerNoChannel")}
              </div>
            ) : (
              imOwnerEntries.map((entry) => (
                <ImOwnerChannelRow
                  key={entry.channel}
                  entry={entry}
                  saving={savingAction === `imowner-${entry.channel}`}
                  onSave={saveImOwnerAllowlist}
                />
              ))
            )}
          </CardContent>
        </Card>
      )}

      {/* C9a §4: Dry-run preview (current persisted policy decisions for sample tools) */}
      {tab === "dryrun" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border/50 px-4 py-2.5">
            <div className="space-y-1">
              <CardTitle className="text-sm font-semibold">{t("security.dryRun")}</CardTitle>
              <p className="text-xs text-muted-foreground">
                {t("security.dryRunDesc")}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={runDryRunPreview} disabled={loadingDryRun} className="h-8">
              <RotateCw size={14} className={cn("mr-1.5", loadingDryRun && "animate-spin")} /> {t("security.dryRunRun")}
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {dryRunDecisions.length === 0 ? (
              <div className="flex flex-col items-center py-10 text-center text-sm text-muted-foreground">
                <Shield size={32} className="mb-3 opacity-20" />
                {loadingDryRun ? t("common.loading") : t("security.dryRunEmpty")}
              </div>
            ) : (
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs h-10 px-5 font-medium">{t("security.dryRunTool")}</TableHead>
                    <TableHead className="text-xs h-10 px-4 font-medium">{t("security.dryRunArgs")}</TableHead>
                    <TableHead className="text-xs h-10 px-4 font-medium">{t("security.dryRunDecision")}</TableHead>
                    <TableHead className="hidden md:table-cell text-xs h-10 px-4 font-medium">{t("security.dryRunClass")}</TableHead>
                    <TableHead className="hidden lg:table-cell text-xs h-10 px-4 font-medium">{t("security.dryRunReason")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dryRunDecisions.map((d, i) => (
                    <TableRow key={i} className="border-b-border/50 hover:bg-muted/20">
                      <TableCell className="px-5 py-2.5 font-mono text-xs">
                        {d.tool_label_key ? t(d.tool_label_key, d.tool) : d.tool}
                      </TableCell>
                      <TableCell className="px-4 py-2.5 font-mono text-xs text-muted-foreground truncate max-w-[260px]" title={d.params_preview}>
                        {d.params_preview}
                      </TableCell>
                      <TableCell className="px-4 py-2.5">
                        <DecisionBadge decision={d.decision} labelKey={d.decision_label_key} />
                        {d.safety_immune_match && (
                          <Badge variant="outline" className="ml-1.5 text-[10px] uppercase border-amber-500/40 text-amber-600">
                            {t("security.flag.immune")}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="hidden md:table-cell px-4 py-2.5">
                        {d.approval_class ? (
                          <Badge variant="secondary" className="text-[10px] font-mono">
                            {d.approval_class_label_key ? t(d.approval_class_label_key, d.approval_class) : d.approval_class}
                          </Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell px-4 py-2.5 text-xs text-muted-foreground truncate max-w-[280px]" title={d.reason}>
                        {d.reason_code
                          ? t(`security.reasonCode.${d.reason_code}`, d.reason || d.reason_code)
                          : (d.reason || "—")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Checkpoints */}
      {tab === "checkpoints" && (
        <Card className="p-0 gap-0 border-border/50 shadow-sm overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 border-b border-border/50 px-4 py-2.5">
            <div className="space-y-1">
              <CardTitle className="text-sm font-semibold">{t("security.checkpoints")}</CardTitle>
              <p className="text-xs text-muted-foreground">
                {t("security.checkpointCount", { count: checkpoints.length })}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={() => loadCheckpoints(true)} disabled={refreshingCheckpoints} className="h-8">
              <RotateCw size={14} className={cn("mr-1.5", refreshingCheckpoints && "animate-spin")} /> {t("security.refresh")}
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {checkpoints.length === 0 ? (
              <div className="flex flex-col items-center py-10 text-center text-sm text-muted-foreground">
                <IconClock size={32} className="mb-3 opacity-20" />
                {t("security.noCheckpoints")}
              </div>
            ) : (
              <Table>
                <TableHeader className="bg-muted/30">
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-xs h-10 px-5 font-medium">ID</TableHead>
                    <TableHead className="text-xs h-10 px-4 font-medium">{t("security.checkpointTool")}</TableHead>
                    <TableHead className="hidden sm:table-cell text-xs h-10 px-4 font-medium">{t("security.checkpointFiles")}</TableHead>
                    <TableHead className="hidden sm:table-cell text-xs h-10 px-4 font-medium">{t("security.checkpointTime")}</TableHead>
                    <TableHead className="w-[100px] text-right text-xs h-10 px-5 font-medium" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {checkpoints.map((cp) => (
                    <TableRow key={cp.checkpoint_id} className="border-b-border/50 transition-colors hover:bg-muted/20">
                      <TableCell className="px-5 py-3 font-mono text-xs truncate max-w-[180px]" title={cp.checkpoint_id}>{cp.checkpoint_id}</TableCell>
                      <TableCell className="px-4 py-3 text-sm">{cp.tool_name}</TableCell>
                      <TableCell className="hidden sm:table-cell px-4 py-3 text-xs text-muted-foreground">
                        <Badge variant="outline" className="font-mono">{cp.file_count}</Badge> {t("security.files")}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell px-4 py-3 text-xs text-muted-foreground whitespace-nowrap font-mono">
                        {new Date(cp.timestamp * 1000).toLocaleString()}
                      </TableCell>
                      <TableCell className="px-5 py-3 text-right">
                        <Button variant="outline" size="sm" onClick={() => requestRewind(cp)} disabled={rewindingId === cp.checkpoint_id} className="h-7 text-xs">
                          {rewindingId === cp.checkpoint_id && <Loader2 className="mr-1 size-3 animate-spin" />}
                          {t("security.rewind")}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
        </>
      )}

      <AlertDialog
        open={offDialogOpen}
        onOpenChange={(open) => {
          if (saving) return;
          setOffDialogOpen(open);
          if (!open) {
            setOffAckPhrase("");
            setOffAckError("");
          }
        }}
      >
        <AlertDialogContent className="sm:max-w-[520px]">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg border border-red-500/20 bg-red-500/10 text-red-600">
                <ShieldAlert size={16} />
              </span>
              {t("security.offDialogTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3 text-sm text-muted-foreground">
                <p>
                  {t("security.offDialogDesc")}
                </p>
                <div className="rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs leading-5 text-red-700 dark:text-red-300">
                  {t("security.offDialogWarning")}
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs font-medium text-foreground">
                    {t("security.offAckLabel")}
                  </Label>
                  <code className="block rounded-md border bg-muted/40 px-2.5 py-2 text-xs text-foreground">
                    {offAckPhraseExpected}
                  </code>
                  <Input
                    autoFocus
                    value={offAckPhrase}
                    onChange={(e) => {
                      setOffAckPhrase(e.target.value);
                      if (offAckError) setOffAckError("");
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void confirmOffMode();
                      }
                    }}
                    placeholder={offAckPhraseExpected}
                    className="h-9"
                  />
                  {offAckError && (
                    <p className="text-xs text-destructive">{offAckError}</p>
                  )}
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <Button
              type="button"
              variant="destructive"
              disabled={saving || offAckPhrase.trim() !== offAckPhraseExpected}
              onClick={() => void confirmOffMode()}
            >
              {saving && <Loader2 className="mr-2 size-4 animate-spin" />}
              {t("security.offDialogConfirm")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={customSwitchDialog !== null}
        onOpenChange={(open) => {
          if (saving) return;
          if (!open) setCustomSwitchDialog(null);
        }}
      >
        <AlertDialogContent className="sm:max-w-[480px]">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-600">
                <ShieldAlert size={16} />
              </span>
              {t("security.customSwitchTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 text-sm text-muted-foreground">
                <p>
                  {t("security.customSwitchDesc")}
                </p>
                <p>
                  {t("security.customSwitchHint")}
                </p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={saving}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <Button
              type="button"
              disabled={saving}
              onClick={() => void confirmCustomSwitch()}
            >
              {saving && <Loader2 className="mr-2 size-4 animate-spin" />}
              {t("security.customSwitchConfirm")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={rewindDialog !== null}
        onOpenChange={(open) => {
          if (rewindingId !== null) return;
          if (!open) setRewindDialog(null);
        }}
      >
        <AlertDialogContent className="sm:max-w-[480px]">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg border border-red-500/20 bg-red-500/10 text-red-600">
                <ShieldAlert size={16} />
              </span>
              {t("security.rewindDialogTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-3 text-sm text-muted-foreground">
                <p>
                  {t("security.rewindDialogDesc")}
                </p>
                {rewindDialog && (
                  <div className="space-y-1 rounded-md border bg-muted/30 px-3 py-2 text-xs">
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">{t("security.checkpointTool")}</span>
                      <span className="font-medium text-foreground">{rewindDialog.tool_name}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">{t("security.checkpointFiles")}</span>
                      <span className="font-mono text-foreground">{rewindDialog.file_count}</span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">{t("security.checkpointTime")}</span>
                      <span className="font-mono text-foreground">
                        {new Date(rewindDialog.timestamp * 1000).toLocaleString()}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-muted-foreground">ID</span>
                      <span className="truncate font-mono text-foreground" title={rewindDialog.checkpoint_id}>
                        {rewindDialog.checkpoint_id}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={rewindingId !== null}>
              {t("common.cancel")}
            </AlertDialogCancel>
            <Button
              type="button"
              variant="destructive"
              disabled={rewindingId !== null}
              onClick={() => void confirmRewind()}
            >
              {rewindingId !== null && <Loader2 className="mr-2 size-4 animate-spin" />}
              {t("security.rewindDialogConfirm")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/* ─── Sub-components ─── */

// C9a §3: per-channel IM owner allowlist editor row
function ImOwnerChannelRow({
  entry,
  saving,
  onSave,
}: {
  entry: ImOwnerAllowlistEntry;
  saving: boolean;
  onSave: (channel: string, owners: string[] | null) => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<string>(entry.owners.join("\n"));
  const [pendingClear, setPendingClear] = useState(false);

  const dirty = draft.trim() !== entry.owners.join("\n").trim();

  const handleSave = () => {
    const owners = draft.split(/[\n,;\s]+/).map((s) => s.trim()).filter(Boolean);
    onSave(entry.channel, owners);
  };

  const handleClear = () => {
    if (pendingClear) {
      onSave(entry.channel, null);
      setPendingClear(false);
      return;
    }
    setPendingClear(true);
    setTimeout(() => setPendingClear(false), 3000);
  };

  return (
    <div className="rounded-md border border-border/50 p-3 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono text-xs">{entry.channel}</Badge>
          {entry.configured ? (
            <Badge variant="secondary" className="text-xs">
              {entry.owners.length} {t("security.imOwnerCount", "owner")}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground border-dashed">
              {t("security.imOwnerUnconfigured")}
            </Badge>
          )}
        </div>
        <div className="flex gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClear}
            disabled={saving || (!entry.configured && !pendingClear)}
            className={cn("h-7 text-xs", pendingClear && "text-destructive")}
          >
            <IconTrash size={12} className="mr-1" />
            {pendingClear
              ? t("security.imOwnerClearConfirm")
              : t("security.imOwnerClear")}
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleSave}
            disabled={saving || !dirty}
            className="h-7 text-xs"
          >
            {saving && <Loader2 className="mr-1 size-3 animate-spin" />}
            <Save size={12} className="mr-1" /> {t("common.save")}
          </Button>
        </div>
      </div>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={t("security.imOwnerPlaceholder")}
        rows={Math.max(2, draft.split("\n").length)}
        className="w-full resize-none rounded-md border border-border/50 bg-background px-3 py-2 font-mono text-xs focus:border-primary focus:outline-none"
      />
      <p className="text-[11px] text-muted-foreground">
        {t("security.imOwnerHint")}
      </p>
    </div>
  );
}

function DecisionBadge({ decision, labelKey }: { decision: string; labelKey?: string | null }) {
  const { t } = useTranslation();
  const variant = decision === "deny" ? "destructive" : decision === "confirm" ? "outline" : "secondary";
  const fallback = decision === "deny"
    ? t("security.decision.deny")
    : decision === "confirm"
      ? t("security.decision.confirm")
      : decision === "allow"
        ? t("security.decision.allow")
        : decision;
  const label = labelKey ? t(labelKey, fallback) : fallback;
  return (
    <Badge variant={variant} className="text-[11px] uppercase shrink-0">
      {label}
    </Badge>
  );
}

function ZonePanel({ zone, paths, onChange }: {
  zone: string;
  paths: string[]; onChange: (v: string[]) => void;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [expanded, setExpanded] = useState(zone === "workspace");
  const meta = ZONE_META[zone];

  const add = () => {
    const v = input.trim();
    if (v && !paths.includes(v)) onChange([...paths, v]);
    setInput("");
  };

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-accent/50"
      >
        <span className={cn("size-2.5 shrink-0 rounded-full", meta.tw)} />
        <span className="flex-1 text-sm font-semibold">{t(`security.zone_${zone}`)}</span>
        <Badge variant="secondary" className="text-xs font-mono">{paths.length}</Badge>
        {expanded ? <IconChevronDown size={16} className="text-muted-foreground" /> : <IconChevronRight size={16} className="text-muted-foreground" />}
      </button>
      {expanded && (
        <CardContent className="space-y-2 pb-3 pt-0">
          {paths.map((p, i) => (
            <div key={i} className="flex items-center gap-2 group bg-muted/30 rounded-md border border-transparent hover:border-border transition-colors px-2 py-1">
              <code className="flex-1 text-xs font-mono">{p}</code>
              <Button
                variant="ghost" size="icon"
                className="size-7 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => onChange(paths.filter((_, j) => j !== i))}
              >
                <IconX size={14} />
              </Button>
            </div>
          ))}
          <div className="mt-2.5 flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()}
              placeholder="D:/path/to/dir/**"
              className="h-8 text-sm font-mono"
            />
            <Button variant="secondary" size="sm" onClick={add} className="h-8 px-3">
              <IconPlus size={14} className="mr-1.5" />
              {t("common.add")}
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

function TagEditor({ label, items, onChange, placeholder }: {
  label: string; items: string[]; onChange: (v: string[]) => void; placeholder?: string;
}) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");

  const add = () => {
    const v = input.trim();
    if (v && !items.includes(v)) onChange([...items, v]);
    setInput("");
  };

  return (
    <div className="space-y-2.5">
      <Label className="text-sm font-medium">{label}</Label>
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item, i) => (
            <Badge key={i} variant="secondary" className="gap-1.5 border-transparent py-0.5 pl-2 pr-1 font-mono text-xs transition-colors hover:border-border">
              {item}
              <button
                onClick={() => onChange(items.filter((_, j) => j !== i))}
                className="ml-0.5 rounded-sm hover:bg-destructive/20 transition-colors p-0.5"
              >
                <IconX size={12} className="text-muted-foreground hover:text-destructive" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder={placeholder}
          className="h-8 text-sm font-mono"
        />
        <Button variant="secondary" size="sm" onClick={add} className="h-8 px-3">
          <IconPlus size={14} className="mr-1.5" />
          {t("common.add")}
        </Button>
      </div>
    </div>
  );
}
