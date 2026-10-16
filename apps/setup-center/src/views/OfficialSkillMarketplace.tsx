import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { safeFetch } from "../providers";
import { marketplaceOpenErrorKey, openMarketplaceWithAccount } from "../marketplace/open";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface Resource {
  id: string;
  slug: string;
  name: string;
  summary?: string;
  publisher_name?: string;
  category?: string;
  latest_version?: string;
}

interface Catalog {
  items: Resource[];
  total: number;
  origin: string;
  facets?: { categories?: { value: string; count: number }[] };
}

const PAGE_SIZE = 24;

export function OfficialSkillMarketplace({ apiBaseUrl, desktopVersion, visible, onSkillHub }: {
  apiBaseUrl: string;
  desktopVersion: string;
  visible: boolean;
  onSkillHub: (query: string) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState("popular");
  const [page, setPage] = useState(0);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [opening, setOpening] = useState<string | null>(null);
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set());

  useEffect(() => { setCatalog(null); setPage(0); }, [apiBaseUrl]);

  // Keep installation facts separate from editable skill settings and catalog
  // requests. A disabled skill is still installed; an acquired resource isn't.
  useEffect(() => {
    setInstalledIds(new Set());
  }, [apiBaseUrl]);

  useEffect(() => {
    if (!visible) return;
    let controller: AbortController | undefined;
    const refreshInstalled = async () => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      try {
        const response = await safeFetch(`${apiBaseUrl}/api/skills`, {
          signal: current.signal, cache: "no-store",
        });
        if (!response.ok) return;
        const data = await response.json();
        if (current.signal.aborted || !Array.isArray(data.skills)) return;
        setInstalledIds(new Set<string>(data.skills
          .filter((skill: { system?: boolean; marketplace_resource_id?: unknown }) =>
            !skill.system && typeof skill.marketplace_resource_id === "string" && skill.marketplace_resource_id)
          .map((skill: { marketplace_resource_id: string }) => skill.marketplace_resource_id)));
      } catch {
        // A transient read failure must not turn an installed resource into "Get".
      }
    };
    const onVisible = () => { if (document.visibilityState === "visible") void refreshInstalled(); };
    void refreshInstalled();
    window.addEventListener("openkitsune:skills-changed", refreshInstalled);
    window.addEventListener("focus", refreshInstalled);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      controller?.abort();
      window.removeEventListener("openkitsune:skills-changed", refreshInstalled);
      window.removeEventListener("focus", refreshInstalled);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [visible, apiBaseUrl]);

  // Abort immediately on query/tab changes, including during the debounce delay.
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: query.trim(), sort,
          limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
        if (category !== "all") params.set("category", category);
        const response = await safeFetch(`${apiBaseUrl}/api/marketplace/skills?${params}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("marketplace_catalog_unavailable");
        const data = await response.json() as Catalog;
        if (!Array.isArray(data.items) || typeof data.total !== "number") throw new Error("invalid_catalog");
        if (!controller.signal.aborted) setCatalog(data);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, query.trim() ? 350 : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [visible, apiBaseUrl, query, category, sort, page, retry]);

  const openResource = async (resource: Resource) => {
    if (opening || installedIds.has(resource.id)) return;
    setOpening(resource.id);
    try {
      await openMarketplaceWithAccount(desktopVersion, apiBaseUrl,
        `/resources/${encodeURIComponent(resource.slug)}`, catalog?.origin);
    } catch (error) {
      toast.error(t(marketplaceOpenErrorKey(error)));
    } finally {
      setOpening(null);
    }
  };

  if (!visible) return null;
  return (
    <section aria-label={t("skills.officialMarket.title")} className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t("skills.officialMarket.description")}</p>
      <Card className="gap-0 border-border/80 py-0 shadow-sm">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row">
          <Input value={query} aria-label={t("skills.officialMarket.search")}
            placeholder={t("skills.officialMarket.search")}
            onChange={e => { setQuery(e.target.value); setPage(0); }} className="flex-1 min-w-0" />
          <Select value={category} onValueChange={v => { setCategory(v); setPage(0); }}>
            <SelectTrigger aria-label={t("skills.officialMarket.category")} className="w-full sm:w-44"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("skills.officialMarket.allCategories")}</SelectItem>
              {(catalog?.facets?.categories || []).filter(c => c.value && c.value !== "all").map(c => (
                <SelectItem key={c.value} value={c.value}>{c.value}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={v => { setSort(v); setPage(0); }}>
            <SelectTrigger aria-label={t("skills.officialMarket.sort")} className="w-full sm:w-40"><SelectValue /></SelectTrigger>
            <SelectContent>
              {["popular", "new", "acquired"].map(value => (
                <SelectItem key={value} value={value}>{t(`skills.officialMarket.sort_${value}`)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardContent>
      </Card>
      {failed && <div role="alert" className="rounded-md border border-destructive/20 bg-destructive/10 p-4 text-sm">
        <p>{t("skills.officialMarket.unavailable")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setRetry(v => v + 1)}>{t("skills.officialMarket.retry")}</Button>
          <Button variant="ghost" onClick={() => onSkillHub(query)}>{t("skills.officialMarket.searchSkillHub")}</Button>
        </div>
      </div>}
      <div aria-busy={loading} className="flex min-h-48 flex-col gap-3">
        {loading && !catalog && <div role="status" className="flex items-center justify-center gap-2 py-16 text-muted-foreground">
          <Loader2 size={20} className="animate-spin" />{t("common.loading")}
        </div>}
        {catalog?.items.map(resource => <Card key={resource.id} className="gap-0 border-border/80 py-0 shadow-sm">
          <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <h3 className="font-semibold break-words">{resource.name}</h3>
                {installedIds.has(resource.id) && <Badge variant="outline" className="bg-emerald-500/10 text-emerald-600 border-emerald-500/30 dark:text-emerald-400">{t("skills.installed")}</Badge>}
                {resource.latest_version && <Badge variant="outline">{resource.latest_version}</Badge>}
              </div>
              <p className="text-sm text-muted-foreground break-words">{resource.summary}</p>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{t("skills.officialMarket.title")}</span>
                {resource.publisher_name && <span>{t("skills.officialMarket.publisher", { name: resource.publisher_name })}</span>}
                {resource.category && <span>{resource.category}</span>}
              </div>
            </div>
            <Button variant="outline" disabled={opening !== null || installedIds.has(resource.id)} onClick={() => openResource(resource)}>
              {opening === resource.id && <Loader2 size={14} className="mr-2 animate-spin" />}
              {installedIds.has(resource.id) && <Check size={14} className="mr-2" />}
              {t(installedIds.has(resource.id) ? "skills.installed" : "skills.officialMarket.viewResource")}
            </Button>
          </CardContent>
        </Card>)}
        {!loading && !failed && catalog?.items.length === 0 && <div className="py-12 text-center text-sm text-muted-foreground">
          <p>{query || category !== "all" ? t("skills.noResults") : t("skills.officialMarket.empty")}</p>
          <Button variant="link" onClick={() => onSkillHub(query)}>{t("skills.officialMarket.searchSkillHub")}</Button>
        </div>}
      </div>
      {catalog && <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>{t("skills.officialMarket.total", { count: catalog.total })}</span>
        <div className="flex items-center gap-3">
          <Button variant="outline" disabled={loading || page === 0} onClick={() => setPage(p => p - 1)}>{t("skills.officialMarket.previous")}</Button>
          <span>{page + 1}</span>
          <Button variant="outline" disabled={loading || failed || (page + 1) * PAGE_SIZE >= catalog.total} onClick={() => setPage(p => p + 1)}>{t("skills.officialMarket.next")}</Button>
        </div>
      </div>}
    </section>
  );
}
