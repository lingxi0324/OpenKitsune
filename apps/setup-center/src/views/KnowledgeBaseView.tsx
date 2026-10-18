import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Cloud,
  CloudCog,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Folder,
  FolderOpen,
  Home,
  KeyRound,
  Loader2,
  RefreshCw,
  ScanLine,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { safeFetch } from "../providers";
import { CATEGORY_COLORS, KnowledgeGraph } from "../components/KnowledgeGraph";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

type ConnectorStatus = "available" | "configured";

type KnowledgeBase = {
  id: string;
  name: string;
};

type ConnectorSummary = {
  id: string;
  name: string;
  status: ConnectorStatus;
  configured: boolean;
  enabled: boolean;
  auto_retrieve: boolean;
  prefer_knowledge: boolean;
  knowledge_bases: KnowledgeBase[];
  top_k: number;
  workspace_id?: string;
  agent_id?: string;
  service_name?: string;
  region?: string;
};

type SearchResult = {
  media_id: string;
  title: string;
  parent_folder_id: string;
  highlight_content: string;
};

type ValidationResponse = {
  ok: boolean;
  message: string;
  error_code?: string;
  latency_ms?: number;
  knowledge_bases?: KnowledgeBase[];
};

type SearchResponse = {
  ok: boolean;
  message: string;
  error_code?: string;
  latency_ms?: number;
  results?: SearchResult[];
};

/* ── 本地知识库契约类型（与 kb_integration_contract.md 对应） ── */
type LocalStats = {
  files?: number;
  dirs?: number;
  meta_files?: number;
  indexed?: number;
  last_scan_at?: string | null;
  index_age_ms?: number | null;
};

type LocalConfig = {
  ok?: boolean;
  root?: string;
  root_exists?: boolean;
  stats?: LocalStats;
};

type BrowseEntry = {
  name: string;
  rel_path: string;
  is_dir: boolean;
  is_doc: boolean;
  size?: number;
  mtime?: string | null;
  title?: string;
  category?: string | null;
  domain?: string | null;
};

type BrowseResponse = {
  ok?: boolean;
  path?: string;
  entries?: BrowseEntry[];
};

type RelatedNode = {
  id: string;
  label: string;
  category: string;
  domain: string | null;
  path: string;
};

type DocResponse = {
  ok?: boolean;
  path?: string;
  title?: string;
  category?: string | null;
  domain?: string | null;
  keywords?: string[];
  related?: RelatedNode[];
  preview?: string;
  content?: string;
  meta?: Record<string, unknown>;
};

type LocalSearchResult = {
  path: string;
  title: string;
  category?: string | null;
  domain?: string | null;
  keywords?: string[];
  score: number;
  snippet?: string;
};

type LocalSearchResponse = {
  ok?: boolean;
  duration_ms?: number;
  results?: LocalSearchResult[];
};

function formatBytes(n?: number | null) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function ConnectorBadge({ connector }: { connector?: ConnectorSummary }) {
  const { t } = useTranslation();
  if (connector?.enabled) {
    return (
      <Badge variant="outline" className="border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
        <CheckCircle2 size={12} /> {t("knowledgeBase.enabled")}
      </Badge>
    );
  }
  if (connector?.configured) {
    return <Badge variant="secondary">{t("knowledgeBase.disabled")}</Badge>;
  }
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <CircleDashed size={12} /> {t("knowledgeBase.available")}
    </Badge>
  );
}

function useCategoryLabel() {
  const { t } = useTranslation();
  return (c: string | null | undefined): string | null => {
    if (!c) return null;
    switch (c) {
      case "概念": return t("knowledgeBase.catConcept");
      case "人物": return t("knowledgeBase.catPerson");
      case "典籍": case "书籍": return t("knowledgeBase.catClassic");
      case "方剂": return t("knowledgeBase.catFormula");
      case "穴位": return t("knowledgeBase.catAcupoint");
      case "脏腑": return t("knowledgeBase.catOrgan");
      case "文档": return t("knowledgeBase.catDocument");
      case "目录": return t("knowledgeBase.catDirectory");
      default: return t("knowledgeBase.catOther");
    }
  };
}

function CategoryBadge({ category }: { category?: string | null }) {
  const label = useCategoryLabel()(category);
  const color = CATEGORY_COLORS[category || ""] || CATEGORY_COLORS["其他"];
  if (!label) return null;
  return (
    <Badge variant="outline" className="shrink-0 px-1.5 py-0 text-[10px]" style={{ borderColor: color }}>
      <span className="mr-1 inline-block size-1.5 rounded-full" style={{ background: color }} />
      {label}
    </Badge>
  );
}

export function KnowledgeBaseView({
  serviceRunning,
  apiBaseUrl,
}: {
  serviceRunning: boolean;
  apiBaseUrl: string;
}) {
  const { t } = useTranslation();
  const [connectors, setConnectors] = useState<ConnectorSummary[]>([]);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [clientId, setClientId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [validating, setValidating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<ValidationResponse | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [autoRetrieve, setAutoRetrieve] = useState(true);
  const [preferKnowledge, setPreferKnowledge] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<"tencent-ima" | "aliyun-bailian" | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [bailianDialogOpen, setBailianDialogOpen] = useState(false);
  const [bailianApiKey, setBailianApiKey] = useState("");
  const [bailianShowApiKey, setBailianShowApiKey] = useState(false);
  const [bailianWorkspaceId, setBailianWorkspaceId] = useState("");
  const [bailianAgentId, setBailianAgentId] = useState("");
  const [bailianServiceName, setBailianServiceName] = useState("百炼知识检索");
  const [bailianRegion, setBailianRegion] = useState("cn-beijing");
  const [bailianEnabled, setBailianEnabled] = useState(true);
  const [bailianAutoRetrieve, setBailianAutoRetrieve] = useState(true);
  const [bailianPreferKnowledge, setBailianPreferKnowledge] = useState(false);
  const [bailianValidating, setBailianValidating] = useState(false);
  const [bailianSaving, setBailianSaving] = useState(false);
  const [bailianValidation, setBailianValidation] = useState<ValidationResponse | null>(null);
  const [bailianSearchQuery, setBailianSearchQuery] = useState("");
  const [bailianSearching, setBailianSearching] = useState(false);
  const [bailianSearchResponse, setBailianSearchResponse] = useState<SearchResponse | null>(null);

  const ima = connectors.find((item) => item.id === "tencent-ima");
  const bailian = connectors.find((item) => item.id === "aliyun-bailian");

  const fetchConnectors = useCallback(async () => {
    if (!serviceRunning) return;
    setLoadingConnectors(true);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/connectors`);
      const data = await response.json();
      const nextConnectors = Array.isArray(data?.connectors) ? data.connectors as ConnectorSummary[] : [];
      setConnectors(nextConnectors);
      const nextIma = nextConnectors.find((item) => item.id === "tencent-ima");
      if (nextIma) {
        const selected = Array.isArray(nextIma.knowledge_bases) ? nextIma.knowledge_bases : [];
        setKnowledgeBases(selected);
        setSelectedIds(selected.map((item) => item.id));
        setEnabled(nextIma.configured ? nextIma.enabled : true);
        setAutoRetrieve(nextIma.auto_retrieve ?? true);
        setPreferKnowledge(nextIma.prefer_knowledge ?? false);
      }
      const nextBailian = nextConnectors.find((item) => item.id === "aliyun-bailian");
      if (nextBailian) {
        setBailianWorkspaceId(nextBailian.workspace_id || "");
        setBailianAgentId(nextBailian.agent_id || "");
        setBailianServiceName(nextBailian.service_name || t("knowledgeBase.bailianDefaultServiceName"));
        setBailianRegion(nextBailian.region || "cn-beijing");
        setBailianEnabled(nextBailian.configured ? nextBailian.enabled : true);
        setBailianAutoRetrieve(nextBailian.auto_retrieve ?? true);
        setBailianPreferKnowledge(nextBailian.prefer_knowledge ?? false);
      }
    } catch (error) {
      toast.error(t("knowledgeBase.loadFailed", { error: String(error) }));
    } finally {
      setLoadingConnectors(false);
    }
  }, [apiBaseUrl, serviceRunning, t]);

  useEffect(() => {
    void fetchConnectors();
  }, [fetchConnectors]);

  /* ── 本地知识库：状态 ── */
  const [localConfig, setLocalConfig] = useState<LocalConfig | null>(null);
  const [localUnavailable, setLocalUnavailable] = useState(false);
  const [scanningLocal, setScanningLocal] = useState(false);
  const [configDialogOpen, setConfigDialogOpen] = useState(false);
  const [configRootDraft, setConfigRootDraft] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [browseEntries, setBrowseEntries] = useState<BrowseEntry[]>([]);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [docPath, setDocPath] = useState<string | null>(null);
  const [docData, setDocData] = useState<DocResponse | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [localSearchQuery, setLocalSearchQuery] = useState("");
  const [localSearching, setLocalSearching] = useState(false);
  const [localSearchResults, setLocalSearchResults] = useState<LocalSearchResult[] | null>(null);

  /* ── AI 学习：动态图谱 ── */
  const [dynStats, setDynStats] = useState<Record<string, unknown> | null>(null);
  const [learningPath, setLearningPath] = useState("");
  const [learningLoading, setLearningLoading] = useState(false);
  const [learningResult, setLearningResult] = useState<Record<string, unknown> | null>(null);
  const [communityLoading, setCommunityLoading] = useState(false);
  const [communityResult, setCommunityResult] = useState<Record<string, unknown> | null>(null);

  const fetchDynStats = useCallback(async () => {
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/graph/dynamic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation: "getStats" }),
        signal: AbortSignal.timeout(15_000),
      });
      if (response.ok) setDynStats(await response.json());
    } catch {
      setDynStats(null);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    if (serviceRunning) void fetchDynStats();
  }, [serviceRunning, fetchDynStats]);

  const handleIngestLearn = async () => {
    const path = learningPath.trim();
    if (!path) {
      toast.error(t("knowledgeBase.learnPathRequired"));
      return;
    }
    setLearningLoading(true);
    setLearningResult(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/learn/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
        signal: AbortSignal.timeout(60_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || data?.message || response.statusText);
      setLearningResult(data);
      await fetchDynStats();
      toast.success(t("knowledgeBase.learnDone"));
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setLearningLoading(false);
    }
  };

  const handleCommunityDetect = async () => {
    setCommunityLoading(true);
    setCommunityResult(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/learn/communities`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_cluster: 3 }),
        signal: AbortSignal.timeout(30_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || data?.message || response.statusText);
      setCommunityResult(data);
      toast.success(t("knowledgeBase.communityDone"));
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setCommunityLoading(false);
    }
  };

  const fetchLocalConfig = useCallback(async () => {
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/config`, {
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setLocalConfig(await response.json());
      setLocalUnavailable(false);
    } catch {
      // 后端 local 端点可能尚未就绪：静默降级为不可用占位，不打扰用户
      setLocalUnavailable(true);
    }
  }, [apiBaseUrl]);

  const fetchBrowse = useCallback(async (rel: string) => {
    setBrowseLoading(true);
    try {
      const response = await safeFetch(
        `${apiBaseUrl}/api/knowledge/local/browse?path=${encodeURIComponent(rel)}&limit=200`,
        { signal: AbortSignal.timeout(20_000) },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as BrowseResponse;
      setBrowseEntries(Array.isArray(data.entries) ? data.entries : []);
    } catch {
      setBrowseEntries([]);
    } finally {
      setBrowseLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    void fetchLocalConfig();
  }, [fetchLocalConfig]);

  useEffect(() => {
    void fetchBrowse(browsePath);
  }, [fetchBrowse, browsePath]);

  const handleLocalScan = async () => {
    setScanningLocal(true);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh: true }),
        signal: AbortSignal.timeout(120_000),
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data?.ok !== false) {
        toast.success(`${t("knowledgeBase.localScanSuccess")}${data?.message ? `：${data.message}` : ""}`);
      } else {
        toast.error(t("knowledgeBase.localScanFailed"));
      }
    } catch {
      toast.error(t("knowledgeBase.localScanFailed"));
    } finally {
      setScanningLocal(false);
      void fetchLocalConfig();
      void fetchBrowse(browsePath);
    }
  };

  const openConfigDialog = () => {
    setConfigRootDraft(localConfig?.root || "");
    setConfigDialogOpen(true);
  };

  const saveLocalConfig = async () => {
    setSavingConfig(true);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root: configRootDraft.trim() }),
        signal: AbortSignal.timeout(20_000),
      });
      const data = await response.json().catch(() => ({}));
      if (response.ok && data?.ok !== false) {
        toast.success(t("knowledgeBase.localScanSuccess"));
        setConfigDialogOpen(false);
        await fetchLocalConfig();
      } else {
        toast.error(t("knowledgeBase.requestFailed", { error: data?.detail?.message || data?.detail || response.statusText }));
      }
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setSavingConfig(false);
    }
  };

  const openDoc = async (relPath: string) => {
    setDocPath(relPath);
    setDocLoading(true);
    setDocData(null);
    try {
      const response = await safeFetch(
        `${apiBaseUrl}/api/knowledge/local/doc?path=${encodeURIComponent(relPath)}`,
        { signal: AbortSignal.timeout(30_000) },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setDocData((await response.json()) as DocResponse);
    } catch {
      setDocData({
        ok: false,
        path: relPath,
        title: relPath,
        category: null,
        domain: null,
        keywords: [],
        related: [],
        preview: t("knowledgeBase.localDocNoContent"),
        content: "",
      });
    } finally {
      setDocLoading(false);
    }
  };

  const runLocalSearch = async () => {
    if (!localSearchQuery.trim()) return;
    setLocalSearching(true);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/local/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: localSearchQuery.trim(), limit: 10, include_body: false }),
        signal: AbortSignal.timeout(30_000),
      });
      const data = (await response.json()) as LocalSearchResponse;
      setLocalSearchResults(Array.isArray(data.results) ? data.results : []);
    } catch {
      setLocalSearchResults([]);
    } finally {
      setLocalSearching(false);
    }
  };

  const crumbs = browsePath ? browsePath.split("/").filter(Boolean) : [];

  const fmtScanTime = (iso?: string | null) => {
    if (!iso) return t("knowledgeBase.localNeverScanned");
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  };

  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((item) => selectedIds.includes(item.id)),
    [knowledgeBases, selectedIds],
  );

  const validateConnection = async () => {
    setValidating(true);
    setValidation(null);
    setSearchResponse(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/ima/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId.trim(), api_key: apiKey.trim() }),
        signal: AbortSignal.timeout(30_000),
      });
      const data = await response.json() as ValidationResponse;
      setValidation(data);
      if (data.ok) {
        const bases = Array.isArray(data.knowledge_bases) ? data.knowledge_bases : [];
        setKnowledgeBases(bases);
        setSelectedIds((current) => current.filter((id) => bases.some((item) => item.id === id)));
        toast.success(data.message);
      } else {
        toast.error(data.message);
      }
    } catch (error) {
      const result = { ok: false, message: t("knowledgeBase.requestFailed", { error: String(error) }) };
      setValidation(result);
      toast.error(result.message);
    } finally {
      setValidating(false);
    }
  };

  const saveConnection = async () => {
    setSaving(true);
    try {
      const selected = knowledgeBases.filter((item) => selectedIds.includes(item.id));
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/ima/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId.trim(),
          api_key: apiKey.trim(),
          enabled,
          auto_retrieve: autoRetrieve,
          prefer_knowledge: preferKnowledge,
          knowledge_bases: selected,
          top_k: 5,
        }),
        signal: AbortSignal.timeout(30_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail?.message || data?.detail || data?.message || response.statusText);
      toast.success(data.message);
      setClientId("");
      setApiKey("");
      setDialogOpen(false);
      await fetchConnectors();
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setSaving(false);
    }
  };

  const searchKnowledge = async () => {
    if (!selectedKnowledgeBase || !searchQuery.trim()) return;
    setSearching(true);
    setSearchResponse(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/ima/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId.trim(),
          api_key: apiKey.trim(),
          knowledge_base_id: selectedKnowledgeBase.id,
          query: searchQuery.trim(),
        }),
        signal: AbortSignal.timeout(30_000),
      });
      setSearchResponse(await response.json() as SearchResponse);
    } catch (error) {
      setSearchResponse({ ok: false, message: t("knowledgeBase.requestFailed", { error: String(error) }) });
    } finally {
      setSearching(false);
    }
  };

  const toggleKnowledgeBase = (id: string) => {
    setSelectedIds((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  };

  const bailianConnectionBody = () => ({
    api_key: bailianApiKey.trim(),
    workspace_id: bailianWorkspaceId.trim(),
    agent_id: bailianAgentId.trim(),
    service_name: bailianServiceName.trim() || t("knowledgeBase.bailianDefaultServiceName"),
    region: bailianRegion,
  });

  const validateBailianConnection = async () => {
    setBailianValidating(true);
    setBailianValidation(null);
    setBailianSearchResponse(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/bailian/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bailianConnectionBody()),
        signal: AbortSignal.timeout(45_000),
      });
      const data = await response.json() as ValidationResponse;
      setBailianValidation(data);
      if (data.ok) toast.success(data.message);
      else toast.error(data.message);
    } catch (error) {
      const result = { ok: false, message: t("knowledgeBase.requestFailed", { error: String(error) }) };
      setBailianValidation(result);
      toast.error(result.message);
    } finally {
      setBailianValidating(false);
    }
  };

  const saveBailianConnection = async () => {
    setBailianSaving(true);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/bailian/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...bailianConnectionBody(),
          enabled: bailianEnabled,
          auto_retrieve: bailianAutoRetrieve,
          prefer_knowledge: bailianPreferKnowledge,
          top_k: 5,
        }),
        signal: AbortSignal.timeout(45_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail?.message || data?.detail || data?.message || response.statusText);
      toast.success(data.message);
      setBailianApiKey("");
      setBailianDialogOpen(false);
      await fetchConnectors();
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setBailianSaving(false);
    }
  };

  const searchBailianKnowledge = async () => {
    if (!bailianSearchQuery.trim()) return;
    setBailianSearching(true);
    setBailianSearchResponse(null);
    try {
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/bailian/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...bailianConnectionBody(), query: bailianSearchQuery.trim(), limit: 5 }),
        signal: AbortSignal.timeout(45_000),
      });
      setBailianSearchResponse(await response.json() as SearchResponse);
    } catch (error) {
      setBailianSearchResponse({ ok: false, message: t("knowledgeBase.requestFailed", { error: String(error) }) });
    } finally {
      setBailianSearching(false);
    }
  };

  const disconnectConnection = async () => {
    const target = disconnectTarget;
    if (!target) return;
    setDisconnecting(true);
    try {
      const route = target === "tencent-ima" ? "ima" : "bailian";
      const response = await safeFetch(`${apiBaseUrl}/api/knowledge/${route}/config`, {
        method: "DELETE",
        signal: AbortSignal.timeout(30_000),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail?.message || data?.detail || data?.message || response.statusText);
      toast.success(data.message);
      setDisconnectTarget(null);
      if (target === "tencent-ima") {
        setDialogOpen(false);
        setClientId("");
        setApiKey("");
        setKnowledgeBases([]);
        setSelectedIds([]);
        setValidation(null);
        setSearchResponse(null);
      } else {
        setBailianDialogOpen(false);
        setBailianApiKey("");
        setBailianWorkspaceId("");
        setBailianAgentId("");
        setBailianValidation(null);
        setBailianSearchResponse(null);
      }
      await fetchConnectors();
    } catch (error) {
      toast.error(t("knowledgeBase.requestFailed", { error: String(error) }));
    } finally {
      setDisconnecting(false);
    }
  };

  if (!serviceRunning) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-muted-foreground">
        <CloudCog size={48} />
        <div className="mt-3 font-semibold">{t("knowledgeBase.title")}</div>
        <div className="mt-1 text-xs opacity-70">{t("knowledgeBase.serviceNotRunning")}</div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-6 py-5">
      <Card className="gap-0 overflow-hidden border-primary/20 bg-gradient-to-br from-primary/[0.09] via-primary/[0.03] to-background py-0 shadow-sm">
        <CardHeader className="gap-4 px-6 py-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl space-y-2">
              <div className="flex items-center gap-2">
                <div className="flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Cloud size={20} />
                </div>
                <CardTitle className="text-xl tracking-tight">{t("knowledgeBase.title")}</CardTitle>
              </div>
              <CardDescription className="text-sm leading-6">{t("knowledgeBase.subtitle")}</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => void fetchConnectors()} disabled={loadingConnectors}>
              {loadingConnectors ? <Loader2 size={14} className="animate-spin" /> : <CloudCog size={14} />}
              {t("knowledgeBase.refresh")}
            </Button>
          </div>

          <div className="grid gap-2 sm:grid-cols-3">
            {[
              { icon: <Cloud size={15} />, title: t("knowledgeBase.flowConnect"), text: t("knowledgeBase.flowConnectDesc") },
              { icon: <ShieldCheck size={15} />, title: t("knowledgeBase.flowSelect"), text: t("knowledgeBase.flowSelectDesc") },
              { icon: <Sparkles size={15} />, title: t("knowledgeBase.flowKitsune"), text: t("knowledgeBase.flowKitsuneDesc") },
            ].map((item, index) => (
              <div key={item.title} className="flex items-center gap-3 rounded-xl border border-primary/15 bg-background/70 px-3 py-2.5">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">{item.icon}</div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 text-xs font-semibold"><span>{index + 1}</span><span>{item.title}</span></div>
                  <div className="truncate text-[11px] text-muted-foreground">{item.text}</div>
                </div>
              </div>
            ))}
          </div>
        </CardHeader>
      </Card>

      {/* ── 本地知识库：状态卡 ── */}
      <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm">
        <CardHeader className="gap-3 px-5 pb-3 pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">{t("knowledgeBase.localTitle")}</CardTitle>
              <CardDescription className="mt-1">{t("knowledgeBase.localSubtitle")}</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => void handleLocalScan()} disabled={scanningLocal}>
                {scanningLocal ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />}
                {scanningLocal ? t("knowledgeBase.localScanning") : t("knowledgeBase.localScan")}
              </Button>
              <Button variant="outline" size="sm" onClick={openConfigDialog}>
                <Settings2 size={14} /> {t("knowledgeBase.localConfig")}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          {localUnavailable ? (
            <div className="rounded-lg border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
              {t("knowledgeBase.localUnavailable")}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <FolderOpen size={14} className="shrink-0 text-primary" />
                <span className="text-muted-foreground">{t("knowledgeBase.localRoot")}:</span>
                <span className="break-all font-mono text-[11px]">{localConfig?.root || "—"}</span>
                {localConfig && localConfig.root_exists === false && (
                  <Badge variant="outline" className="border-red-400/40 px-1.5 py-0 text-[10px] text-red-600">
                    {t("knowledgeBase.localRootMissing")}
                  </Badge>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {[
                  { label: t("knowledgeBase.localFiles"), value: localConfig?.stats?.files ?? "—" },
                  { label: t("knowledgeBase.localDirs"), value: localConfig?.stats?.dirs ?? "—" },
                  { label: t("knowledgeBase.localMetaFiles"), value: localConfig?.stats?.meta_files ?? "—" },
                  { label: t("knowledgeBase.localIndexed"), value: localConfig?.stats?.indexed ?? "—" },
                  { label: t("knowledgeBase.localLastScan"), value: fmtScanTime(localConfig?.stats?.last_scan_at) },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg border bg-muted/[0.14] px-3 py-2">
                    <div className="truncate text-[10px] text-muted-foreground">{item.label}</div>
                    <div className="mt-0.5 truncate text-sm font-semibold" title={String(item.value)}>{item.value}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── AI 学习：动态知识图谱 ── */}
      <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm">
        <CardHeader className="gap-2 px-5 pb-3 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">{t("knowledgeBase.learnTitle")}</CardTitle>
              <CardDescription className="mt-1">{t("knowledgeBase.learnSubtitle")}</CardDescription>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => void fetchDynStats()} disabled={learningLoading}>
                <RefreshCw size={14} /> {t("knowledgeBase.refresh")}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => void handleCommunityDetect()} disabled={communityLoading}>
                {communityLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {communityLoading ? t("knowledgeBase.communityRunning") : t("knowledgeBase.communityDetect")}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 px-5 pb-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { label: t("knowledgeBase.learnDynNodes"), value: dynStats?.nodes ?? "—" },
              { label: t("knowledgeBase.learnDynEdges"), value: dynStats?.edges ?? "—" },
              { label: t("knowledgeBase.learnVersion"), value: dynStats?.version ?? "—" },
              { label: t("knowledgeBase.localLastScan"), value: fmtScanTime(String(dynStats?.updated_at ?? "")) },
            ].map((item) => (
              <div key={item.label} className="rounded-lg border bg-muted/[0.14] px-3 py-2">
                <div className="truncate text-[10px] text-muted-foreground">{item.label}</div>
                <div className="mt-0.5 truncate text-sm font-semibold" title={String(item.value)}>{String(item.value)}</div>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={learningPath}
              onChange={(event) => setLearningPath(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void handleIngestLearn(); }}
              placeholder={t("knowledgeBase.learnPathPlaceholder")}
              className="max-w-md"
            />
            <Button size="sm" onClick={() => void handleIngestLearn()} disabled={learningLoading}>
              {learningLoading ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
              {learningLoading ? t("knowledgeBase.learnRunning") : t("knowledgeBase.learnIngest")}
            </Button>
          </div>
          {learningResult && (
            <div className="rounded-lg border border-primary/20 bg-primary/[0.05] px-3 py-2 text-xs">
              {t("knowledgeBase.learnResult", {
                doc: String(learningResult.document ?? ""),
                nodes: String(learningResult.created_nodes ?? 0),
                edges: String(learningResult.created_edges ?? 0),
                totalNodes: String(learningResult.total_nodes ?? 0),
                totalEdges: String(learningResult.total_edges ?? 0),
              })}
            </div>
          )}
          {communityResult && (
            <div className="rounded-lg border border-border/60 px-3 py-2 text-xs text-muted-foreground">
              <div className="mb-1 font-medium text-foreground">{t("knowledgeBase.communityTitle")}</div>
              {(() => {
                const communities = Array.isArray(communityResult.communities) ? communityResult.communities : [];
                const top = communities.filter((c: { size?: number }) => (c.size ?? 1) >= 3).slice(0, 6);
                if (top.length === 0) return <span>{t("knowledgeBase.communityNone")}</span>;
                return (
                  <ul className="space-y-0.5">
                    {top.map((c: { label?: string; size?: number; members?: string[] }, idx: number) => (
                      <li key={`${c.label}-${idx}`} className="flex items-center gap-2">
                        <span className="truncate">{c.label}</span>
                        <Badge variant="outline" className="shrink-0 px-1.5 py-0 text-[10px]">{c.size ?? 0}</Badge>
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        {/* ── 文档浏览 ── */}
        <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm">
          <CardHeader className="gap-1 px-5 pb-3 pt-5">
            <CardTitle className="text-sm">{t("knowledgeBase.localBrowseTitle")}</CardTitle>
            <CardDescription className="text-xs">{t("knowledgeBase.localBrowseSubtitle")}</CardDescription>
          </CardHeader>
          <CardContent className="px-3 pb-4">
            <div className="mb-2 flex flex-wrap items-center gap-1 px-2 text-xs">
              <button type="button" className="inline-flex items-center text-primary hover:underline" onClick={() => setBrowsePath("")}>
                <Home size={11} className="mr-0.5" />
                {t("knowledgeBase.localRootCrumb")}
              </button>
              {crumbs.map((c, i) => (
                <span key={`${c}-${i}`} className="flex items-center gap-1">
                  <ChevronRight size={11} className="text-muted-foreground" />
                  <button
                    type="button"
                    className={i === crumbs.length - 1 ? "font-medium" : "text-primary hover:underline"}
                    onClick={() => setBrowsePath(crumbs.slice(0, i + 1).join("/"))}
                  >
                    {c}
                  </button>
                </span>
              ))}
            </div>
            <div className="max-h-64 overflow-y-auto rounded-lg border border-border/60">
              {browseLoading ? (
                <div className="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" />
                  {t("knowledgeBase.localBrowseLoading")}
                </div>
              ) : browseEntries.length === 0 ? (
                <div className="py-6 text-center text-xs text-muted-foreground">{t("knowledgeBase.localBrowseEmpty")}</div>
              ) : (
                browseEntries.map((entry) => (
                  <button
                    key={entry.rel_path}
                    type="button"
                    className="flex w-full items-center gap-2 border-b border-border/40 px-3 py-2 text-left text-xs last:border-b-0 hover:bg-muted/50"
                    onClick={() => {
                      if (entry.is_dir) setBrowsePath(entry.rel_path);
                      else if (entry.is_doc) void openDoc(entry.rel_path);
                    }}
                  >
                    {entry.is_dir ? (
                      <Folder size={14} className="shrink-0 text-muted-foreground" />
                    ) : (
                      <FileText size={14} className="shrink-0 text-primary" />
                    )}
                    <span className="min-w-0 flex-1 truncate font-medium">{entry.title || entry.name}</span>
                    {!entry.is_dir && !entry.is_doc && (
                      <Badge variant="outline" className="shrink-0 px-1.5 py-0 text-[10px] text-muted-foreground">
                        {t("knowledgeBase.localUnindexed")}
                      </Badge>
                    )}
                    <CategoryBadge category={entry.category} />
                    <span className="shrink-0 text-[10px] text-muted-foreground">{formatBytes(entry.size)}</span>
                  </button>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        {/* ── 本地检索 ── */}
        <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm">
          <CardHeader className="gap-1 px-5 pb-3 pt-5">
            <CardTitle className="text-sm">{t("knowledgeBase.localSearchTitle")}</CardTitle>
            <CardDescription className="text-xs">{t("knowledgeBase.localSearchSubtitle")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 px-5 pb-4">
            <div className="flex gap-2">
              <Input
                value={localSearchQuery}
                onChange={(event) => setLocalSearchQuery(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") void runLocalSearch(); }}
                placeholder={t("knowledgeBase.localSearchPlaceholder")}
              />
              <Button variant="secondary" onClick={() => void runLocalSearch()} disabled={!localSearchQuery.trim() || localSearching}>
                {localSearching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                {t("knowledgeBase.localSearchButton")}
              </Button>
            </div>
            {localSearchResults !== null && (
              localSearchResults.length === 0 ? (
                <div className="text-xs text-muted-foreground">{t("knowledgeBase.localSearchEmpty")}</div>
              ) : (
                <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                  {localSearchResults.map((r) => (
                    <button
                      key={r.path}
                      type="button"
                      className="w-full rounded-lg border bg-muted/[0.16] px-3 py-2 text-left transition-colors hover:border-primary/35"
                      onClick={() => void openDoc(r.path)}
                    >
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{r.title}</span>
                        <CategoryBadge category={r.category} />
                        <span className="shrink-0 text-[10px] text-muted-foreground">
                          {typeof r.score === "number" ? r.score.toFixed(2) : r.score} {t("knowledgeBase.localScore")}
                        </span>
                      </div>
                      {r.snippet && (
                        <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">{r.snippet}</div>
                      )}
                      {(r.keywords || []).length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {(r.keywords || []).slice(0, 5).map((k) => (
                            <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{k}</span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── 知识图谱（React Flow 2D） ── */}
      <KnowledgeGraph apiBaseUrl={apiBaseUrl} />

      <div className="space-y-3">
        <div>
          <h2 className="text-base font-semibold">{t("knowledgeBase.cloudTitle")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("knowledgeBase.cloudSubtitle")}</p>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm transition-colors hover:border-primary/35">
            <CardHeader className="gap-3 px-5 pb-3 pt-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-400/10 text-blue-600 dark:text-blue-300">
                  <Cloud size={23} />
                </div>
                <ConnectorBadge connector={ima} />
              </div>
              <div>
                <CardTitle className="text-base">{t("knowledgeBase.imaName")}</CardTitle>
                <CardDescription className="mt-1 leading-5">{t("knowledgeBase.imaDescription")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 px-5 pb-5">
              {ima?.configured && (
                <div className="flex items-center justify-between rounded-lg border bg-muted/[0.16] px-3 py-2.5">
                  <div>
                    <div className="text-xs font-medium">{t("knowledgeBase.selectedCount", { count: ima.knowledge_bases.length })}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {ima.prefer_knowledge
                        ? t("knowledgeBase.preferKnowledgeOn")
                        : ima.auto_retrieve
                          ? t("knowledgeBase.autoRetrieveOn")
                          : t("knowledgeBase.autoRetrieveOff")}
                    </div>
                  </div>
                  <BookOpen size={17} className="text-primary" />
                </div>
              )}
              <Button className="w-full justify-between" onClick={() => setDialogOpen(true)}>
                <span>{ima?.configured ? t("knowledgeBase.manage") : t("knowledgeBase.connect")}</span>
                <ChevronRight size={15} />
              </Button>
            </CardContent>
          </Card>

          <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm transition-colors hover:border-primary/35">
            <CardHeader className="gap-3 px-5 pb-3 pt-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500/20 to-amber-400/10 text-orange-600 dark:text-orange-300">
                  <Sparkles size={23} />
                </div>
                <ConnectorBadge connector={bailian} />
              </div>
              <div>
                <CardTitle className="text-base">{t("knowledgeBase.bailianName")}</CardTitle>
                <CardDescription className="mt-1 leading-5">{t("knowledgeBase.bailianDescription")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 px-5 pb-5">
              {bailian?.configured && (
                <div className="flex items-center justify-between rounded-lg border bg-muted/[0.16] px-3 py-2.5">
                  <div>
                    <div className="text-xs font-medium">{bailian.service_name || t("knowledgeBase.bailianDefaultServiceName")}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {bailian.prefer_knowledge
                        ? t("knowledgeBase.preferKnowledgeOn")
                        : bailian.auto_retrieve
                          ? t("knowledgeBase.autoRetrieveOn")
                          : t("knowledgeBase.autoRetrieveOff")}
                    </div>
                  </div>
                  <BookOpen size={17} className="text-primary" />
                </div>
              )}
              <Button className="w-full justify-between" onClick={() => setBailianDialogOpen(true)}>
                <span>{bailian?.configured ? t("knowledgeBase.manage") : t("knowledgeBase.connectBailian")}</span>
                <ChevronRight size={15} />
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Cloud size={19} /> {t("knowledgeBase.imaDialogTitle")}</DialogTitle>
            <DialogDescription>{t("knowledgeBase.imaDialogDesc")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-5 py-1">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="ima-client-id">Client ID</Label>
                <Input id="ima-client-id" value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder={ima?.configured ? t("knowledgeBase.useConfigured") : "IMA_OPENAPI_CLIENTID"} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ima-api-key">API Key</Label>
                <div className="relative">
                  <Input id="ima-api-key" type={showApiKey ? "text" : "password"} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={ima?.configured ? t("knowledgeBase.useConfigured") : "IMA_OPENAPI_APIKEY"} className="pr-10" />
                  <Button type="button" variant="ghost" size="icon-sm" className="absolute right-1 top-1/2 -translate-y-1/2" onClick={() => setShowApiKey((value) => !value)} aria-label={t("knowledgeBase.toggleSecret")}>
                    {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-2 rounded-lg border border-blue-500/20 bg-blue-500/[0.06] px-3 py-2.5 text-xs leading-5 text-muted-foreground">
              <KeyRound size={15} className="mt-0.5 shrink-0 text-blue-600" />
              <span>{t("knowledgeBase.credentialNotice")}</span>
              <a href="https://ima.qq.com/agent-interface" target="_blank" rel="noreferrer" className="ml-auto inline-flex shrink-0 items-center gap-1 text-primary hover:underline">
                {t("knowledgeBase.getCredentials")} <ExternalLink size={11} />
              </a>
            </div>

            <Button variant="secondary" onClick={() => void validateConnection()} disabled={validating || (!ima?.configured && (!clientId.trim() || !apiKey.trim()))}>
              {validating ? <Loader2 size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
              {validating ? t("knowledgeBase.loadingBases") : t("knowledgeBase.loadBases")}
            </Button>

            {validation && (
              <div className={`rounded-xl border px-4 py-3 ${validation.ok ? "border-emerald-500/25 bg-emerald-500/[0.06]" : "border-red-500/25 bg-red-500/[0.06]"}`}>
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {validation.ok ? <CheckCircle2 size={16} className="text-emerald-600" /> : <CircleDashed size={16} className="text-red-600" />}
                  {validation.message}
                  {validation.latency_ms != null && <span className="ml-auto text-xs font-normal text-muted-foreground">{validation.latency_ms} ms</span>}
                </div>
              </div>
            )}

            {validation?.ok && knowledgeBases.length === 0 && (
              <div className="rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground">
                {t("knowledgeBase.noBases")}
              </div>
            )}

            {knowledgeBases.length > 0 && (
              <div className="space-y-3">
                <div>
                  <div className="text-sm font-semibold">{t("knowledgeBase.availableBases")}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{t("knowledgeBase.availableBasesHint")}</div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {knowledgeBases.map((base) => {
                    const checked = selectedIds.includes(base.id);
                    return (
                      <button key={base.id} type="button" className={`flex items-center gap-3 rounded-lg border px-3 py-3 text-left transition-colors ${checked ? "border-primary/45 bg-primary/[0.06]" : "border-border hover:border-primary/25"}`} onClick={() => toggleKnowledgeBase(base.id)}>
                        <Checkbox checked={checked} tabIndex={-1} />
                        <BookOpen size={16} className="shrink-0 text-primary" />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{base.name}</span>
                        {checked && <Check size={14} className="text-primary" />}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {(ima?.configured || validation?.ok) && (
              <div className="grid gap-4 rounded-xl border border-border/80 p-4 sm:grid-cols-2">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium">{t("knowledgeBase.connectionEnabled")}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.connectionEnabledDesc")}</div>
                    </div>
                    <Switch checked={enabled} onCheckedChange={setEnabled} />
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium">{t("knowledgeBase.autoRetrieve")}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.autoRetrieveDesc")}</div>
                    </div>
                    <Switch checked={autoRetrieve} onCheckedChange={setAutoRetrieve} disabled={!enabled} />
                  </div>
                  <div className="flex items-center justify-between gap-3 sm:col-span-2">
                    <div>
                      <div className="text-sm font-medium">{t("knowledgeBase.preferKnowledge")}</div>
                      <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.preferKnowledgeDesc")}</div>
                    </div>
                    <Switch checked={preferKnowledge} onCheckedChange={setPreferKnowledge} disabled={!enabled} />
                  </div>
              </div>
            )}

            {knowledgeBases.length > 0 && (
              <div className="space-y-3 rounded-xl border border-border/80 p-4">
                  <div>
                    <div className="text-sm font-semibold">{t("knowledgeBase.searchTitle")}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{t("knowledgeBase.searchDesc", { name: selectedKnowledgeBase?.name || "-" })}</div>
                  </div>
                  <div className="flex gap-2">
                    <Input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void searchKnowledge(); }} placeholder={t("knowledgeBase.searchPlaceholder")} />
                    <Button variant="secondary" onClick={() => void searchKnowledge()} disabled={!selectedKnowledgeBase || !searchQuery.trim() || searching}>
                      {searching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                      {t("knowledgeBase.search")}
                    </Button>
                  </div>
                  {searchResponse && (
                    <div className="space-y-2">
                      <div className={`text-xs font-medium ${searchResponse.ok ? "text-emerald-600" : "text-red-600"}`}>
                        {searchResponse.message}{searchResponse.latency_ms != null ? ` · ${searchResponse.latency_ms} ms` : ""}
                      </div>
                      {(searchResponse.results || []).slice(0, 5).map((result) => (
                        <div key={`${result.media_id}-${result.title}`} className="rounded-lg border bg-muted/[0.18] px-3 py-2.5">
                          <div className="text-sm font-medium">{result.title}</div>
                          {result.highlight_content && <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{result.highlight_content}</div>}
                        </div>
                      ))}
                      {searchResponse.ok && (searchResponse.results || []).length === 0 && <div className="text-xs text-muted-foreground">{t("knowledgeBase.noResults")}</div>}
                    </div>
                  )}
              </div>
            )}
          </div>

          <DialogFooter>
            {ima?.configured && (
              <Button
                variant="destructive"
                className="sm:mr-auto"
                onClick={() => {
                  setDialogOpen(false);
                  setDisconnectTarget("tencent-ima");
                }}
              >
                <Trash2 size={15} /> {t("knowledgeBase.removeConnection")}
              </Button>
            )}
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t("knowledgeBase.cancel")}</Button>
            <Button onClick={() => void saveConnection()} disabled={saving || (enabled && selectedIds.length === 0) || (!ima?.configured && (!clientId.trim() || !apiKey.trim()))}>
              {saving && <Loader2 size={15} className="animate-spin" />}
              {t("knowledgeBase.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={bailianDialogOpen} onOpenChange={setBailianDialogOpen}>
        <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Sparkles size={19} /> {t("knowledgeBase.bailianDialogTitle")}</DialogTitle>
            <DialogDescription>{t("knowledgeBase.bailianDialogDesc")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-5 py-1">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="bailian-workspace-id">{t("knowledgeBase.workspaceId")}</Label>
                <Input id="bailian-workspace-id" value={bailianWorkspaceId} onChange={(event) => setBailianWorkspaceId(event.target.value)} placeholder="llm-..." />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bailian-agent-id">{t("knowledgeBase.retrievalServiceId")}</Label>
                <Input id="bailian-agent-id" value={bailianAgentId} onChange={(event) => setBailianAgentId(event.target.value)} placeholder="aid-..." />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bailian-service-name">{t("knowledgeBase.serviceName")}</Label>
                <Input id="bailian-service-name" value={bailianServiceName} onChange={(event) => setBailianServiceName(event.target.value)} placeholder={t("knowledgeBase.bailianDefaultServiceName")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bailian-region">{t("knowledgeBase.region")}</Label>
                <select id="bailian-region" value={bailianRegion} onChange={(event) => setBailianRegion(event.target.value)} className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50">
                  <option value="cn-beijing">{t("knowledgeBase.regionBeijing")}</option>
                  <option value="ap-southeast-1">{t("knowledgeBase.regionSingapore")}</option>
                </select>
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="bailian-api-key">API Key</Label>
                <div className="relative">
                  <Input id="bailian-api-key" type={bailianShowApiKey ? "text" : "password"} value={bailianApiKey} onChange={(event) => setBailianApiKey(event.target.value)} placeholder={bailian?.configured ? t("knowledgeBase.useConfigured") : "sk-..."} className="pr-10" />
                  <Button type="button" variant="ghost" size="icon-sm" className="absolute right-1 top-1/2 -translate-y-1/2" onClick={() => setBailianShowApiKey((value) => !value)} aria-label={t("knowledgeBase.toggleSecret")}>
                    {bailianShowApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-2 rounded-lg border border-orange-500/20 bg-orange-500/[0.06] px-3 py-2.5 text-xs leading-5 text-muted-foreground">
              <KeyRound size={15} className="mt-0.5 shrink-0 text-orange-600" />
              <span>{t("knowledgeBase.bailianCredentialNotice")}</span>
              <a href="https://bailian.console.aliyun.com/" target="_blank" rel="noreferrer" className="ml-auto inline-flex shrink-0 items-center gap-1 text-primary hover:underline">
                {t("knowledgeBase.openBailianConsole")} <ExternalLink size={11} />
              </a>
            </div>

            <Button variant="secondary" onClick={() => void validateBailianConnection()} disabled={bailianValidating || (!bailian?.configured && (!bailianWorkspaceId.trim() || !bailianAgentId.trim() || !bailianApiKey.trim()))}>
              {bailianValidating ? <Loader2 size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
              {bailianValidating ? t("knowledgeBase.validatingBailian") : t("knowledgeBase.validateBailian")}
            </Button>

            {bailianValidation && (
              <div className={`rounded-xl border px-4 py-3 ${bailianValidation.ok ? "border-emerald-500/25 bg-emerald-500/[0.06]" : "border-red-500/25 bg-red-500/[0.06]"}`}>
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {bailianValidation.ok ? <CheckCircle2 size={16} className="text-emerald-600" /> : <CircleDashed size={16} className="text-red-600" />}
                  {bailianValidation.message}
                  {bailianValidation.latency_ms != null && <span className="ml-auto text-xs font-normal text-muted-foreground">{bailianValidation.latency_ms} ms</span>}
                </div>
              </div>
            )}

            <div className="grid gap-4 rounded-xl border border-border/80 p-4 sm:grid-cols-2">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">{t("knowledgeBase.connectionEnabled")}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.connectionEnabledDesc")}</div>
                </div>
                <Switch checked={bailianEnabled} onCheckedChange={setBailianEnabled} />
              </div>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">{t("knowledgeBase.autoRetrieve")}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.autoRetrieveDesc")}</div>
                </div>
                <Switch checked={bailianAutoRetrieve} onCheckedChange={setBailianAutoRetrieve} disabled={!bailianEnabled} />
              </div>
              <div className="flex items-center justify-between gap-3 sm:col-span-2">
                <div>
                  <div className="text-sm font-medium">{t("knowledgeBase.preferKnowledge")}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{t("knowledgeBase.preferKnowledgeDesc")}</div>
                </div>
                <Switch checked={bailianPreferKnowledge} onCheckedChange={setBailianPreferKnowledge} disabled={!bailianEnabled} />
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-border/80 p-4">
              <div>
                <div className="text-sm font-semibold">{t("knowledgeBase.searchTitle")}</div>
                <div className="mt-1 text-xs text-muted-foreground">{t("knowledgeBase.searchDesc", { name: bailianServiceName || t("knowledgeBase.bailianDefaultServiceName") })}</div>
              </div>
              <div className="flex gap-2">
                <Input value={bailianSearchQuery} onChange={(event) => setBailianSearchQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void searchBailianKnowledge(); }} placeholder={t("knowledgeBase.searchPlaceholder")} />
                <Button variant="secondary" onClick={() => void searchBailianKnowledge()} disabled={!bailianSearchQuery.trim() || bailianSearching}>
                  {bailianSearching ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
                  {t("knowledgeBase.search")}
                </Button>
              </div>
              {bailianSearchResponse && (
                <div className="space-y-2">
                  <div className={`text-xs font-medium ${bailianSearchResponse.ok ? "text-emerald-600" : "text-red-600"}`}>
                    {bailianSearchResponse.message}{bailianSearchResponse.latency_ms != null ? ` · ${bailianSearchResponse.latency_ms} ms` : ""}
                  </div>
                  {(bailianSearchResponse.results || []).slice(0, 5).map((result) => (
                    <div key={`${result.media_id}-${result.title}`} className="rounded-lg border bg-muted/[0.18] px-3 py-2.5">
                      <div className="text-sm font-medium">{result.title}</div>
                      {result.highlight_content && <div className="mt-1 line-clamp-3 text-xs leading-5 text-muted-foreground">{result.highlight_content}</div>}
                    </div>
                  ))}
                  {bailianSearchResponse.ok && (bailianSearchResponse.results || []).length === 0 && <div className="text-xs text-muted-foreground">{t("knowledgeBase.noResults")}</div>}
                </div>
              )}
            </div>
          </div>

          <DialogFooter>
            {bailian?.configured && (
              <Button
                variant="destructive"
                className="sm:mr-auto"
                onClick={() => {
                  setBailianDialogOpen(false);
                  setDisconnectTarget("aliyun-bailian");
                }}
              >
                <Trash2 size={15} /> {t("knowledgeBase.removeConnection")}
              </Button>
            )}
            <Button variant="outline" onClick={() => setBailianDialogOpen(false)}>{t("knowledgeBase.cancel")}</Button>
            <Button onClick={() => void saveBailianConnection()} disabled={bailianSaving || (bailianEnabled && (!bailianWorkspaceId.trim() || !bailianAgentId.trim())) || (!bailian?.configured && !bailianApiKey.trim())}>
              {bailianSaving && <Loader2 size={15} className="animate-spin" />}
              {t("knowledgeBase.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 本地库配置弹窗（PUT config） ── */}
      <Dialog open={configDialogOpen} onOpenChange={setConfigDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Settings2 size={18} /> {t("knowledgeBase.localConfigDialogTitle")}</DialogTitle>
            <DialogDescription>{t("knowledgeBase.localConfigDialogDesc")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-2">
              <Label htmlFor="local-root">{t("knowledgeBase.localRootPathLabel")}</Label>
              <Input
                id="local-root"
                value={configRootDraft}
                onChange={(event) => setConfigRootDraft(event.target.value)}
                placeholder={t("knowledgeBase.localRootPathPlaceholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfigDialogOpen(false)}>{t("knowledgeBase.cancel")}</Button>
            <Button onClick={() => void saveLocalConfig()} disabled={savingConfig || !configRootDraft.trim()}>
              {savingConfig && <Loader2 size={14} className="animate-spin" />}
              {t("knowledgeBase.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 文档详情弹窗（GET doc） ── */}
      <Dialog open={docPath !== null} onOpenChange={(open) => { if (!open) setDocPath(null); }}>
        <DialogContent className="max-h-[86vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText size={18} /> {docData?.title || docPath || t("knowledgeBase.localDocDialogTitle")}
            </DialogTitle>
            <DialogDescription>{docData?.path}</DialogDescription>
          </DialogHeader>
          {docLoading ? (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
              <Loader2 size={16} className="animate-spin" />
              {t("knowledgeBase.localDocLoading")}
            </div>
          ) : docData ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <CategoryBadge category={docData.category} />
                {docData.domain && (
                  <Badge variant="secondary" className="text-[10px]">
                    {t("knowledgeBase.localDocDomain")}: {docData.domain}
                  </Badge>
                )}
              </div>
              {(docData.keywords || []).length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">{t("knowledgeBase.localDocKeywords")}:</span>
                  {docData.keywords!.map((k) => (
                    <Badge key={k} variant="outline" className="px-1.5 py-0 text-[10px]">{k}</Badge>
                  ))}
                </div>
              )}
              {docData.preview && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold">{t("knowledgeBase.localDocPreview")}</div>
                  <div className="whitespace-pre-wrap rounded-lg border bg-muted/[0.15] px-3 py-2 text-xs leading-5 text-muted-foreground">
                    {docData.preview}
                  </div>
                </div>
              )}
              {docData.content && docData.content !== docData.preview && (
                <div className="space-y-1">
                  <div className="text-xs font-semibold">{t("knowledgeBase.localDocContent")}</div>
                  <div className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border px-3 py-2 text-xs leading-5">
                    {docData.content}
                  </div>
                </div>
              )}
              {(docData.related || []).length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-xs font-semibold">{t("knowledgeBase.localDocRelated")}</div>
                  {docData.related!.map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs hover:bg-muted/50"
                      onClick={() => void openDoc(n.path)}
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CATEGORY_COLORS[n.category] || CATEGORY_COLORS["其他"] }} />
                      <span className="min-w-0 flex-1 truncate font-medium">{n.label}</span>
                      {n.domain && <span className="shrink-0 text-[10px] text-muted-foreground">{n.domain}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={disconnectTarget !== null}
        onOpenChange={(open) => {
          if (!open && !disconnecting) setDisconnectTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("knowledgeBase.removeConnectionTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t(disconnectTarget === "aliyun-bailian"
                ? "knowledgeBase.removeBailianDescription"
                : "knowledgeBase.removeImaDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={disconnecting}>{t("knowledgeBase.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              disabled={disconnecting}
              onClick={(event) => {
                event.preventDefault();
                void disconnectConnection();
              }}
            >
              {disconnecting && <Loader2 size={15} className="animate-spin" />}
              {disconnecting ? t("knowledgeBase.removing") : t("knowledgeBase.removeConnection")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
