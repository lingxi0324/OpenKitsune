import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertCircle, Loader2, RefreshCw, X } from "lucide-react";

import { safeFetch } from "../providers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** 冻结色板（见 kb_integration_contract.md），视图层共享复用。 */
export const CATEGORY_COLORS: Record<string, string> = {
  "概念": "#6c8cff",
  "人物": "#f87171",
  "典籍": "#fbbf24",
  "方剂": "#4ade80",
  "穴位": "#c084fc",
  "脏腑": "#fb923c",
  "书籍": "#fbbf24",
  "文档": "#60a5fa",
  "目录": "#94a3b8",
  "其他": "#94a3b8",
};

/** GraphNode —— 与后端契约逐条对应。 */
export type GraphNodeData = {
  id: string;
  label: string;
  category: string;
  description: string;
  keywords: string[];
  domain: string | null;
  path: string;
  is_directory: boolean;
  color: string;
  importance: number;
  file_size: number | null;
  modified: string | null;
};

type GraphEdgeData = {
  id: string;
  source: string;
  target: string;
  label: string;
  weight: number;
};

type GraphResponse = {
  ok?: boolean;
  stats?: Record<string, number>;
  nodes?: GraphNodeData[];
  edges?: GraphEdgeData[];
};

type FlowNode = Node<GraphNodeData, "kbNode">;

/** 图例 / 分区使用的类别顺序（书籍/其他并入同色分区）。 */
const CATEGORY_ORDER = ["概念", "人物", "典籍", "方剂", "穴位", "脏腑", "文档", "目录"];

type Point = { x: number; y: number };

/* ───────────────────────────── 布局 a：目录辐射 ─────────────────────────────
 * 根中心；顶层子库目录环1角度均分；子目录环2；文件环3围绕父目录。
 * 未挂在包含树里的孤立节点放到最外圈。
 */
function radialLayout(nodes: GraphNodeData[], edges: GraphEdgeData[]): Map<string, Point> {
  const pos = new Map<string, Point>();
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const children = new Map<string, string[]>();
  const containment = edges.filter((e) => e.label === "包含");
  for (const e of containment) {
    if (!byId.has(e.source) || !byId.has(e.target)) continue;
    const list = children.get(e.source) || [];
    list.push(e.target);
    children.set(e.source, list);
  }
  const hasParent = new Set(containment.map((e) => e.target));
  const root =
    nodes.find((n) => n.is_directory && !hasParent.has(n.id)) ||
    nodes.find((n) => n.is_directory) ||
    nodes[0];
  if (!root) return pos;

  pos.set(root.id, { x: 0, y: 0 });
  const TAU = Math.PI * 2;

  const placeSubtree = (id: string, angle: number, radius: number) => {
    pos.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
    const kids = children.get(id) || [];
    if (!kids.length) return;
    const dirKids = kids.filter((k) => byId.get(k)?.is_directory);
    const fileKids = kids.filter((k) => !byId.get(k)?.is_directory);
    const spread = Math.PI / 2.2;
    const spreadAngle = (i: number, total: number) =>
      total === 1 ? angle : angle - spread / 2 + spread * (i / (total - 1));
    dirKids.forEach((kid, i) => placeSubtree(kid, spreadAngle(i, dirKids.length), radius + 420));
    fileKids.forEach((kid, i) => {
      const a = spreadAngle(i, fileKids.length);
      pos.set(kid, { x: Math.cos(a) * (radius + 230), y: Math.sin(a) * (radius + 230) });
    });
  };

  const level1 = children.get(root.id) || [];
  level1.forEach((kid, i) => {
    placeSubtree(kid, -Math.PI / 2 + (i * TAU) / Math.max(level1.length, 1), 1050);
  });

  const orphans = nodes.filter((n) => !pos.has(n.id));
  orphans.forEach((n, i) => {
    const a = -Math.PI / 2 + (i * TAU) / Math.max(orphans.length, 1);
    pos.set(n.id, { x: Math.cos(a) * 1800, y: Math.sin(a) * 1800 });
  });
  return pos;
}

/* ───────────────────────────── 布局 b：分类分区 ─────────────────────────────
 * 画面按类别划 4×2 网格分区，同类别节点在本分区内黄金角聚簇；目录节点居中。
 */
function clusterLayout(nodes: GraphNodeData[], _edges: GraphEdgeData[]): Map<string, Point> {
  const pos = new Map<string, Point>();
  const ZW = 950;
  const ZH = 760;
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));
  const zoneOf = (category: string): { col: number; row: number } => {
    switch (category) {
      case "概念": return { col: 0, row: 0 };
      case "人物": return { col: 1, row: 0 };
      case "典籍": case "书籍": return { col: 2, row: 0 };
      case "方剂": return { col: 3, row: 0 };
      case "穴位": return { col: 0, row: 1 };
      case "脏腑": return { col: 1, row: 1 };
      case "文档": case "其他": return { col: 2, row: 1 };
      default: return { col: 3, row: 1 }; // 目录
    }
  };
  const center = (col: number, row: number): Point => ({
    x: col * ZW - 1.5 * ZW,
    y: row * ZH - 0.8 * ZH,
  });
  const byZone = new Map<string, GraphNodeData[]>();
  for (const n of nodes) {
    const key = `${zoneOf(n.category).col}:${zoneOf(n.category).row}`;
    const list = byZone.get(key) || [];
    list.push(n);
    byZone.set(key, list);
  }
  for (const list of byZone.values()) {
    const first = list[0];
    const { col, row } = zoneOf(first.category);
    const c = center(col, row);
    let fileIndex = 0;
    for (const n of list) {
      if (n.is_directory) {
        pos.set(n.id, { x: c.x, y: c.y });
        continue;
      }
      const r = 70 + 60 * Math.sqrt(fileIndex);
      const a = fileIndex * GOLDEN;
      pos.set(n.id, { x: c.x + Math.cos(a) * r, y: c.y + Math.sin(a) * r });
      fileIndex += 1;
    }
  }
  return pos;
}

/* ───────────────────────────── 自定义节点 ─────────────────────────────
 * 必须渲染隐藏 Handle：React Flow v12 中自定义节点没有 Handle 时边无锚点、
 * 不会被渲染。source/target 各一个，尺寸 0、pointer-events-none，纯锚定用。
 */
function KbNode({ data, selected }: NodeProps<FlowNode>) {
  const size = 30 + Math.round((data.importance ?? 0.5) * 36);
  return (
    <div
      title={`${data.label} · ${data.path}`}
      style={{
        width: size,
        height: size,
        borderRadius: data.is_directory ? "28%" : "50%",
        background: data.color || CATEGORY_COLORS["其他"],
        border: selected ? "3px solid var(--foreground)" : "2px solid rgba(255,255,255,0.85)",
        boxShadow: "0 1px 5px rgba(0,0,0,0.28)",
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{ width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
      />
      <Handle
        type="source"
        position={Position.Right}
        style={{ width: 0, height: 0, opacity: 0, pointerEvents: "none" }}
      />
    </div>
  );
}

const nodeTypes = { kbNode: KbNode };

/* ───────────────────────────── 主组件 ───────────────────────────── */
export function KnowledgeGraph({ apiBaseUrl }: { apiBaseUrl: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [layoutMode, setLayoutMode] = useState<"radial" | "cluster">("radial");
  const [enabledCats, setEnabledCats] = useState<Set<string>>(() => new Set(CATEGORY_ORDER));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/knowledge/local/graph?limit=600`, {
        signal: AbortSignal.timeout(30_000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as GraphResponse);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    void load();
  }, [load, reloadTick]);

  const allNodes = useMemo(() => data?.nodes ?? [], [data]);
  const allEdges = useMemo(() => data?.edges ?? [], [data]);

  const visibleNodes = useMemo(
    () => allNodes.filter((n) => enabledCats.has(n.category)),
    [allNodes, enabledCats],
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => allEdges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)),
    [allEdges, visibleIds],
  );

  // 选中节点被筛选掉时，自动收起详情
  useEffect(() => {
    if (selectedId && !visibleIds.has(selectedId)) setSelectedId(null);
  }, [selectedId, visibleIds]);

  const positions = useMemo(
    () => (layoutMode === "radial" ? radialLayout(visibleNodes, visibleEdges) : clusterLayout(visibleNodes, visibleEdges)),
    [visibleNodes, visibleEdges, layoutMode],
  );

  const neighborIds = useMemo(() => {
    const s = new Set<string>();
    if (!selectedId) return s;
    s.add(selectedId);
    visibleEdges.forEach((e) => {
      if (e.source === selectedId) s.add(e.target);
      if (e.target === selectedId) s.add(e.source);
    });
    return s;
  }, [selectedId, visibleEdges]);

  const flowNodes: FlowNode[] = useMemo(
    () =>
      visibleNodes.map((n) => {
        const p = positions.get(n.id) || { x: 0, y: 0 };
        const dimmed = selectedId !== null && !neighborIds.has(n.id);
        return {
          id: n.id,
          type: "kbNode" as const,
          position: p,
          data: n,
          selected: n.id === selectedId,
          style: { opacity: dimmed ? 0.22 : 1, transition: "opacity 0.25s ease" },
        };
      }),
    [visibleNodes, positions, selectedId, neighborIds],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      visibleEdges.map((e) => {
        const touches = selectedId !== null && (e.source === selectedId || e.target === selectedId);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "default" as const,
          style: {
            stroke: touches ? "#f59e0b" : "#94a3b8",
            strokeWidth: touches ? 2.5 : Math.min(0.8 + (e.weight || 1) / 2, 2),
            opacity: selectedId === null ? 0.32 : touches ? 0.9 : 0.07,
            transition: "opacity 0.25s ease",
          },
        };
      }),
    [visibleEdges, selectedId],
  );

  const selectedNode = useMemo(
    () => allNodes.find((n) => n.id === selectedId) || null,
    [allNodes, selectedId],
  );
  const relatedNodes = useMemo(
    () => allNodes.filter((n) => n.id !== selectedId && neighborIds.has(n.id)),
    [allNodes, neighborIds, selectedId],
  );

  const stats = useMemo(() => {
    const map = new Map<string, number>();
    for (const n of allNodes) map.set(n.category, (map.get(n.category) || 0) + 1);
    return map;
  }, [allNodes]);

  const toggleCat = (c: string) =>
    setEnabledCats((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });

  const catName = (c: string) => {
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

  return (
    <Card className="gap-0 overflow-hidden border-border/80 py-0 shadow-sm">
      <CardHeader className="gap-3 px-5 pb-3 pt-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">{t("knowledgeBase.graphTitle")}</CardTitle>
            <CardDescription className="mt-1">{t("knowledgeBase.graphSubtitle")}</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-border bg-muted/40 p-0.5">
              {([
                { key: "radial", label: t("knowledgeBase.graphLayoutRadial") },
                { key: "cluster", label: t("knowledgeBase.graphLayoutCluster") },
              ] as const).map((mode) => (
                <button
                  key={mode.key}
                  type="button"
                  onClick={() => setLayoutMode(mode.key)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    layoutMode === mode.key
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <Button variant="outline" size="sm" onClick={() => setReloadTick((v) => v + 1)} disabled={loading}>
              {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {t("knowledgeBase.graphRefresh")}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-3 pb-3">
        <div className="relative h-[560px] w-full overflow-hidden rounded-xl border border-border/70 bg-muted/[0.04]">
          {/* 河图洛书语义装饰：淡化同心环（纯装饰，不参与布局） */}
          {layoutMode === "cluster" && (
            <div className="pointer-events-none absolute left-1/2 top-1/2 z-0 -translate-x-1/2 -translate-y-1/2">
              {[520, 820, 1120].map((size) => (
                <div
                  key={size}
                  className="absolute rounded-full border border-primary/10"
                  style={{ width: size, height: size, left: -size / 2, top: -size / 2 }}
                />
              ))}
            </div>
          )}

          {loading ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
              <Loader2 size={28} className="animate-spin" />
              <div className="text-sm">{t("knowledgeBase.graphLoading")}</div>
            </div>
          ) : error ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
              <AlertCircle size={28} className="text-red-500" />
              <div className="text-sm text-red-600">{t("knowledgeBase.graphError")}</div>
              <Button variant="outline" size="sm" onClick={() => setReloadTick((v) => v + 1)}>
                {t("knowledgeBase.graphRefresh")}
              </Button>
            </div>
          ) : visibleNodes.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              {t("knowledgeBase.graphEmpty")}
            </div>
          ) : (
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={() => setSelectedId(null)}
              fitView
              minZoom={0.1}
              maxZoom={1.8}
              nodesDraggable={false}
              nodesConnectable={false}
              proOptions={{ hideAttribution: true }}
              defaultEdgeOptions={{ type: "default" }}
            >
              <Background gap={24} size={1} color="var(--line, #e2e8f0)" />
              <Controls showInteractive={false} position="bottom-left" />
              <MiniMap
                pannable
                zoomable
                nodeColor={(n) => CATEGORY_COLORS[(n.data as GraphNodeData)?.category] || CATEGORY_COLORS["其他"]}
                maskColor="rgba(240, 245, 255, 0.55)"
              />

              {/* 类别筛选 chips（多选，客户端过滤） */}
              <Panel position="top-left">
                <div className="flex max-w-[420px] flex-wrap items-center gap-1.5 rounded-lg border border-border/70 bg-background/85 p-2 shadow-sm backdrop-blur">
                  <span className="px-1 text-[11px] font-medium text-muted-foreground">
                    {t("knowledgeBase.graphCategoryFilter")}：
                  </span>
                  {CATEGORY_ORDER.map((c) => {
                    const active = enabledCats.has(c);
                    return (
                      <button
                        key={c}
                        type="button"
                        onClick={() => toggleCat(c)}
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
                          active
                            ? "border-border bg-background text-foreground"
                            : "border-dashed border-border/60 bg-muted/30 text-muted-foreground line-through"
                        }`}
                      >
                        <span className="inline-block size-2 rounded-full" style={{ background: CATEGORY_COLORS[c] }} />
                        {catName(c)}
                      </button>
                    );
                  })}
                </div>
              </Panel>

              {/* 统计卡 */}
              <Panel position="bottom-left">
                <div className="rounded-lg border border-border/70 bg-background/85 p-2.5 text-[11px] shadow-sm backdrop-blur">
                  <div className="mb-1 font-semibold">
                    {t("knowledgeBase.graphStats")} · {allNodes.length} {t("knowledgeBase.graphNodesLabel")} /{" "}
                    {allEdges.length} {t("knowledgeBase.graphEdgesLabel")}
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                    {CATEGORY_ORDER.filter((c) => stats.has(c)).map((c) => (
                      <span key={c} className="inline-flex items-center gap-1">
                        <span className="inline-block size-2 rounded-full" style={{ background: CATEGORY_COLORS[c] }} />
                        {catName(c)} {stats.get(c) || 0}
                      </span>
                    ))}
                  </div>
                </div>
              </Panel>

              {/* 节点详情面板 */}
              <Panel position="top-right">
                {selectedNode ? (
                  <div className="w-64 rounded-lg border border-border/70 bg-background/90 p-3 shadow-md backdrop-blur">
                    <div className="mb-1.5 flex items-start justify-between gap-2">
                      <div className="text-sm font-semibold leading-5">{selectedNode.label}</div>
                      <button type="button" onClick={() => setSelectedId(null)} className="text-muted-foreground hover:text-foreground">
                        <X size={14} />
                      </button>
                    </div>
                    <div className="mb-2 flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline" style={{ borderColor: selectedNode.color }}>
                        <span className="mr-1 inline-block size-2 rounded-full" style={{ background: selectedNode.color }} />
                        {catName(selectedNode.category)}
                      </Badge>
                      {selectedNode.domain && (
                        <Badge variant="secondary" className="text-[10px]">{selectedNode.domain}</Badge>
                      )}
                    </div>
                    {selectedNode.description && (
                      <p className="mb-2 line-clamp-3 text-[11px] leading-4 text-muted-foreground">
                        {selectedNode.description}
                      </p>
                    )}
                    {selectedNode.keywords?.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {selectedNode.keywords.slice(0, 8).map((k) => (
                          <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{k}</span>
                        ))}
                      </div>
                    )}
                    <div className="mb-1 break-all font-mono text-[10px] leading-4 text-muted-foreground">{selectedNode.path}</div>
                    {relatedNodes.length > 0 && (
                      <div className="mt-2 border-t pt-2">
                        <div className="mb-1 text-[10px] font-semibold text-muted-foreground">
                          {t("knowledgeBase.graphRelatedDocs")}（{relatedNodes.length}）
                        </div>
                        <div className="max-h-28 space-y-1 overflow-y-auto">
                          {relatedNodes.slice(0, 12).map((n) => (
                            <button
                              key={n.id}
                              type="button"
                              onClick={() => setSelectedId(n.id)}
                              className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-[11px] hover:bg-muted"
                            >
                              <span className="inline-block size-2 shrink-0 rounded-full" style={{ background: CATEGORY_COLORS[n.category] }} />
                              <span className="truncate">{n.label}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-border/60 bg-background/70 px-3 py-2 text-[11px] text-muted-foreground backdrop-blur">
                    {t("knowledgeBase.graphNoDetail")}
                  </div>
                )}
              </Panel>
            </ReactFlow>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
