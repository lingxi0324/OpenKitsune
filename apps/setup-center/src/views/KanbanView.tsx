import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  IconKanban, IconPlus, IconRefresh,
  IconCheck,
} from "../icons";
import { safeFetch } from "../providers";
import { encodePathSegment } from "../platform/apiUrl";
import { IS_WEB, onWsEvent } from "../platform";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { Plus, RefreshCw, Trash2, Pencil, Archive, Undo2, MessageCircle, GripVertical, ChevronRight, Loader2 } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────

type KanbanComment = { id: string; author: string; body: string; created_at: string };
type KanbanEvent = { id: number; kind: string; payload: string | null; created_at: string };

type KanbanCard = {
  id: string;
  board_id: string;
  title: string;
  description: string;
  status: string;
  assignee: string | null;
  priority: number;
  sort_order: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  comment_count: number;
  comments?: KanbanComment[];
  events?: KanbanEvent[];
};

type WorkflowColumn = { key: string; label: string; icon: string };

// Fallback 列定义（API 不可用时兜底；与后端 kanban.store.WORKFLOW_COLUMNS 一致）
const FALLBACK_COLUMNS: WorkflowColumn[] = [
  { key: "todo", label: "待办", icon: "◻" },
  { key: "in_progress", label: "进行中", icon: "●" },
  { key: "blocked", label: "阻塞", icon: "⊘" },
  { key: "done", label: "已完成", icon: "✓" },
];

// 列主题色（中性 + 蓝绿，避免大面积靛紫）
const COLUMN_THEME: Record<string, { head: string; dot: string; border: string }> = {
  todo: { head: "bg-slate-100 text-slate-700", dot: "bg-slate-400", border: "border-slate-200" },
  in_progress: { head: "bg-sky-50 text-sky-700", dot: "bg-sky-500", border: "border-sky-200" },
  blocked: { head: "bg-red-50 text-red-700", dot: "bg-red-500", border: "border-red-200" },
  done: { head: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500", border: "border-emerald-200" },
  archived: { head: "bg-stone-100 text-stone-600", dot: "bg-stone-400", border: "border-stone-200" },
};

const PRIORITY_META: Record<number, { label: string; cls: string }> = {
  0: { label: "priority0", cls: "bg-slate-100 text-slate-600" },
  1: { label: "priority1", cls: "bg-sky-100 text-sky-700" },
  2: { label: "priority2", cls: "bg-amber-100 text-amber-700" },
  3: { label: "priority3", cls: "bg-red-100 text-red-700" },
};

function formatTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function initials(name: string): string {
  const s = (name || "?").trim();
  return s.length > 0 ? s.slice(0, 1).toUpperCase() : "?";
}

function parseEventPayload(raw: string | null): Record<string, any> {
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function eventKindLabel(kind: string): string {
  switch (kind) {
    case "created": return "created";
    case "moved": return "moved";
    case "commented": return "commented";
    case "updated": return "updated";
    default: return kind;
  }
}

// ─── Component ────────────────────────────────────────────────────────

export function KanbanView({ serviceRunning, apiBaseUrl = "" }: { serviceRunning: boolean; apiBaseUrl?: string }) {
  const API_BASE = apiBaseUrl;
  const { t } = useTranslation();

  const [columns, setColumns] = useState<WorkflowColumn[]>(FALLBACK_COLUMNS);
  const [cards, setCards] = useState<KanbanCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [dragCardId, setDragCardId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  // 新建
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ title: "", description: "", assignee: "", priority: "0", status: "todo" });

  // 详情
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KanbanCard | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState({ title: "", description: "", assignee: "", priority: "0" });
  const [commentText, setCommentText] = useState("");
  const [commentBusy, setCommentBusy] = useState(false);
  const [moveBusy, setMoveBusy] = useState(false);

  const fetchWorkflow = useCallback(async () => {
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/workflow`);
      const data = await res.json();
      if (data && Array.isArray(data.columns) && data.columns.length > 0) {
        setColumns(data.columns);
      }
    } catch {
      /* fallback columns keep working */
    }
  }, [API_BASE]);

  const fetchCards = useCallback(async (showArch: boolean) => {
    if (!serviceRunning) return;
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards?include_archived=${showArch ? "true" : "false"}&limit=300`);
      const data = await res.json();
      setCards(data.cards || []);
    } catch {
      toast.error(t("kanban.loadFailed"));
    }
  }, [API_BASE, serviceRunning, t]);

  const refresh = useCallback(async () => {
    setLoading(true);
    await fetchWorkflow();
    await fetchCards(showArchived);
    setLoading(false);
  }, [fetchCards, fetchWorkflow, showArchived]);

  useEffect(() => {
    if (!serviceRunning) return;
    fetchWorkflow();
    fetchCards(showArchived);
  }, [serviceRunning, showArchived, fetchWorkflow, fetchCards]);

  // 服务端广播 → 实时刷新（看板数据被 Agent 工具 / 其他端修改时）
  useEffect(() => {
    if (!IS_WEB) return;
    return onWsEvent((event) => {
      if (event === "kanban:change") fetchCards(showArchived);
    });
  }, [fetchCards, showArchived]);

  // 卡片按状态分组
  const byStatus = useMemo(() => {
    const map: Record<string, KanbanCard[]> = {};
    for (const c of cards) {
      (map[c.status] = map[c.status] || []).push(c);
    }
    for (const col of columns) {
      (map[col.key] = map[col.key] || []).sort(
        (a, b) => b.priority - a.priority || String(a.created_at).localeCompare(String(b.created_at)),
      );
    }
    if (showArchived) (map.archived = map.archived || []);
    return map;
  }, [cards, columns, showArchived]);

  // ── 新建 ──
  const openCreate = () => {
    setCreateForm({ title: "", description: "", assignee: "", priority: "0", status: "todo" });
    setCreateOpen(true);
  };

  const submitCreate = async () => {
    const title = createForm.title.trim();
    if (!title) {
      toast.error(t("kanban.cardTitlePlaceholder"));
      return;
    }
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description: createForm.description.trim(),
          assignee: createForm.assignee.trim() || null,
          priority: parseInt(createForm.priority || "0", 10),
          status: createForm.status,
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setCreateOpen(false);
      toast.success(t("kanban.created"));
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    }
  };

  // ── 详情 ──
  const openDetail = async (cardId: string) => {
    setDetailId(cardId);
    setDetailLoading(true);
    setDetail(null);
    setEditing(false);
    setCommentText("");
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(cardId)}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setDetail(data);
      setEditForm({
        title: data.title,
        description: data.description || "",
        assignee: data.assignee || "",
        priority: String(data.priority ?? 0),
      });
    } catch (e) {
      toast.error(String(e));
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setDetailId(null);
    setDetail(null);
  };

  const submitMove = async (status: string) => {
    if (!detailId) return;
    setMoveBusy(true);
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(detailId)}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(t("kanban.moved"));
      await openDetail(detailId);
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setMoveBusy(false);
    }
  };

  const submitSave = async () => {
    if (!detailId) return;
    const title = editForm.title.trim();
    if (!title) {
      toast.error(t("kanban.cardTitlePlaceholder"));
      return;
    }
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(detailId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description: editForm.description.trim(),
          assignee: editForm.assignee.trim() || null,
          priority: parseInt(editForm.priority || "0", 10),
        }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setEditing(false);
      toast.success(t("kanban.updated"));
      await openDetail(detailId);
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    }
  };

  const submitComment = async () => {
    const body = commentText.trim();
    if (!detailId || !body) return;
    setCommentBusy(true);
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(detailId)}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setCommentText("");
      await openDetail(detailId);
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setCommentBusy(false);
    }
  };

  const submitDelete = async () => {
    if (!detailId) return;
    if (!window.confirm(t("kanban.deleteConfirm"))) return;
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(detailId)}`, { method: "DELETE" });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      closeDetail();
      toast.success(t("kanban.delete"));
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    }
  };

  const submitArchive = async () => {
    if (!detailId) return;
    const target = detail?.status === "archived" ? "todo" : "archived";
    await submitMove(target);
  };

  // ── 拖拽 ──
  const onCardDragStart = (e: React.DragEvent, cardId: string) => {
    setDragCardId(cardId);
    setDragging(true);
    e.dataTransfer.effectAllowed = "move";
    try {
      e.dataTransfer.setData("text/plain", cardId);
    } catch {
      /* ignore */
    }
  };

  const onCardDragEnd = () => {
    setDragCardId(null);
    setDragging(false);
  };

  const onColumnDrop = async (status: string) => {
    const cardId = dragCardId;
    setDragCardId(null);
    setDragging(false);
    if (!cardId) return;
    const card = cards.find(c => c.id === cardId);
    if (!card || card.status === status) return;
    if (status !== "archived" && card.status === "archived") {
      // 从归档拖回 → 恢复为待办
    }
    try {
      const res = await safeFetch(`${API_BASE}/api/kanban/cards/${encodePathSegment(cardId)}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      toast.success(t("kanban.moved"));
      fetchCards(showArchived);
    } catch (e) {
      toast.error(String(e));
    }
  };

  // ── 渲染 ──

  if (!serviceRunning) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
        <IconKanban size={48} />
        <div className="mt-3 font-semibold">{t("kanban.title")}</div>
        <div className="mt-1 text-xs opacity-50">{t("kanban.serviceNotRunning")}</div>
      </div>
    );
  }

  const visibleColumns = showArchived ? [...columns, { key: "archived", label: t("kanban.statusArchived"), icon: "🗂" }] : columns;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── 工具条 ── */}
      <div className="flex items-center gap-3 px-4 py-3 border-b shrink-0">
        <div className="flex items-center gap-2">
          <IconKanban size={20} className="text-primary" />
          <h2 className="text-base font-semibold">{t("kanban.title")}</h2>
          <span className="text-xs text-muted-foreground">
            {t("kanban.totalCards", { count: cards.length })}
          </span>
        </div>
        <div className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowArchived(v => !v)}
          className="text-xs"
        >
          <Archive size={14} className="mr-1" />
          {showArchived ? t("kanban.hideArchived") : t("kanban.showArchived")}
        </Button>
        <Button variant="outline" size="sm" onClick={refresh} className="text-xs" disabled={loading}>
          {loading ? <Loader2 size={14} className="mr-1 animate-spin" /> : <RefreshCw size={14} className="mr-1" />}
          {t("kanban.refresh")}
        </Button>
        <Button size="sm" onClick={openCreate} className="text-xs">
          <Plus size={14} className="mr-1" />
          {t("kanban.newCard")}
        </Button>
      </div>

      {/* ── 看板列 ── */}
      <div className="flex-1 min-h-0 overflow-x-auto">
        <div className="flex gap-3 p-4 h-full min-w-max" style={{ minHeight: "100%" }}>
          {visibleColumns.map(col => {
            const theme = COLUMN_THEME[col.key] || COLUMN_THEME.todo;
            const colCards = byStatus[col.key] || [];
            const isDragOverTarget = dragging && dragCardId && !colCards.some(c => c.id === dragCardId);
            return (
              <div
                key={col.key}
                className={cn(
                  "flex flex-col w-[280px] shrink-0 rounded-lg border bg-card/60 transition-colors",
                  theme.border,
                  isDragOverTarget && "ring-2 ring-primary/40 bg-primary/5",
                )}
                onDragOver={e => { e.preventDefault(); }}
                onDrop={() => onColumnDrop(col.key)}
              >
                {/* 列头 */}
                <div className={cn("flex items-center gap-2 px-3 py-2 rounded-t-lg text-sm font-medium", theme.head)}>
                  <span className="text-xs">{col.icon}</span>
                  <span className="flex-1 truncate">{t(`kanban.status${col.key === "in_progress" ? "InProgress" : col.key.charAt(0).toUpperCase() + col.key.slice(1)}`)}</span>
                  <Badge variant="secondary" className="text-xs px-1.5 min-w-[22px] justify-center">
                    {colCards.length}
                  </Badge>
                </div>
                {/* 卡片 */}
                <div className="flex-1 overflow-y-auto p-2 space-y-2 min-h-[80px]" style={{ maxHeight: "calc(100% - 40px)" }}>
                  {colCards.length === 0 && (
                    <div className="flex items-center justify-center h-12 text-xs text-muted-foreground/60 border border-dashed rounded-md">
                      {t("kanban.noCards")}
                    </div>
                  )}
                  {colCards.map(card => {
                    const pMeta = PRIORITY_META[card.priority] || PRIORITY_META[0];
                    const isDragging = dragCardId === card.id;
                    return (
                      <div
                        key={card.id}
                        draggable
                        onDragStart={e => onCardDragStart(e, card.id)}
                        onDragEnd={onCardDragEnd}
                        onClick={() => openDetail(card.id)}
                        className={cn(
                          "group rounded-md border bg-white p-2.5 cursor-pointer shadow-sm hover:shadow transition-all",
                          isDragging && "opacity-40 ring-2 ring-primary/50",
                        )}
                        title={card.title}
                      >
                        <div className="flex items-start gap-1.5">
                          <GripVertical size={12} className="mt-0.5 text-muted-foreground/40 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <div className="text-[13px] font-medium leading-snug break-words line-clamp-2">{card.title}</div>
                            {card.description && (
                              <div className="mt-1 text-xs text-muted-foreground line-clamp-2 break-words">{card.description}</div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 mt-2">
                          <Badge className={cn("text-[10px] px-1.5 py-0", pMeta.cls)}>
                            {t(`kanban.${pMeta.label}`)}
                          </Badge>
                          {card.assignee && (
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground min-w-0">
                              <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/10 text-primary text-[9px] font-semibold shrink-0">
                                {initials(card.assignee)}
                              </span>
                              <span className="truncate max-w-[80px]">{card.assignee}</span>
                            </span>
                          )}
                          <span className="flex-1" />
                          {card.comment_count > 0 && (
                            <span className="flex items-center gap-0.5 text-[11px] text-muted-foreground">
                              <MessageCircle size={12} />
                              {card.comment_count}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* 快速新建入口 */}
          <button
            onClick={openCreate}
            className="w-[280px] shrink-0 rounded-lg border border-dashed border-muted-foreground/30 hover:border-primary/50 hover:bg-primary/5 flex items-center justify-center gap-2 text-sm text-muted-foreground transition-colors"
            style={{ minHeight: 60 }}
          >
            <IconPlus size={16} />
            {t("kanban.newCard")}
          </button>
        </div>
      </div>

      {/* ── 新建卡片 Dialog ── */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{t("kanban.newCard")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div className="grid gap-1.5">
              <Label>{t("kanban.cardTitle")} *</Label>
              <Input
                value={createForm.title}
                onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))}
                placeholder={t("kanban.cardTitlePlaceholder")}
                autoFocus
                onKeyDown={e => { if (e.key === "Enter") submitCreate(); }}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>{t("kanban.description")}</Label>
              <Textarea
                value={createForm.description}
                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
                placeholder={t("kanban.descriptionPlaceholder")}
                rows={3}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-1.5">
                <Label>{t("kanban.assignee")}</Label>
                <Input
                  value={createForm.assignee}
                  onChange={e => setCreateForm(f => ({ ...f, assignee: e.target.value }))}
                  placeholder={t("kanban.assigneePlaceholder")}
                />
              </div>
              <div className="grid gap-1.5">
                <Label>{t("kanban.priority")}</Label>
                <Select value={createForm.priority} onValueChange={v => setCreateForm(f => ({ ...f, priority: v }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {[0, 1, 2, 3].map(p => (
                      <SelectItem key={p} value={String(p)}>{t(`kanban.priority${p}`)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label>{t("kanban.moveTo")}</Label>
              <Select value={createForm.status} onValueChange={v => setCreateForm(f => ({ ...f, status: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {columns.map(c => (
                    <SelectItem key={c.key} value={c.key}>
                      {t(`kanban.status${c.key === "in_progress" ? "InProgress" : c.key.charAt(0).toUpperCase() + c.key.slice(1)}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>{t("kanban.cancel")}</Button>
            <Button onClick={submitCreate}>
              <IconCheck size={14} className="mr-1" />
              {t("kanban.create")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 卡片详情 Dialog ── */}
      <Dialog open={detailId !== null} onOpenChange={v => { if (!v) closeDetail(); }}>
        <DialogContent className="sm:max-w-[640px] max-h-[85vh] overflow-y-auto">
          {detailLoading || !detail ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 size={20} className="animate-spin" />
            </div>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2 pr-8">
                  <Badge className={cn("text-[11px]", PRIORITY_META[detail.priority]?.cls || PRIORITY_META[0].cls)}>
                    {t(`kanban.${PRIORITY_META[detail.priority]?.label || "priority0"}`)}
                  </Badge>
                  {editing ? (
                    <Input
                      value={editForm.title}
                      onChange={e => setEditForm(f => ({ ...f, title: e.target.value }))}
                      className="text-sm font-medium"
                    />
                  ) : (
                    <span className="text-base break-words">{detail.title}</span>
                  )}
                </DialogTitle>
              </DialogHeader>

              {/* 状态列 + 移动 */}
              <div className="flex items-center gap-2 flex-wrap py-1">
                <Badge className={cn("text-xs", COLUMN_THEME[detail.status]?.head || COLUMN_THEME.todo.head)}>
                  {t(`kanban.status${detail.status === "in_progress" ? "InProgress" : detail.status.charAt(0).toUpperCase() + detail.status.slice(1)}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {t("kanban.by")} {detail.assignee || "—"} · {formatTime(detail.created_at)}
                </span>
                <span className="flex-1" />
                <div className="flex items-center gap-1">
                  {columns
                    .filter(c => c.key !== detail.status)
                    .map(c => (
                      <Button key={c.key} size="sm" variant="outline" className="h-7 text-xs" disabled={moveBusy} onClick={() => submitMove(c.key)}>
                        <ChevronRight size={12} className="mr-0.5" />
                        {t(`kanban.status${c.key === "in_progress" ? "InProgress" : c.key.charAt(0).toUpperCase() + c.key.slice(1)}`)}
                      </Button>
                    ))}
                  <Button size="sm" variant="outline" className="h-7 text-xs" disabled={moveBusy} onClick={submitArchive}>
                    {detail.status === "archived" ? <Undo2 size={12} className="mr-1" /> : <Archive size={12} className="mr-1" />}
                    {detail.status === "archived" ? t("kanban.unarchive") : t("kanban.archive")}
                  </Button>
                </div>
              </div>

              {/* 描述 */}
              <div className="grid gap-1.5">
                <Label>{t("kanban.description")}</Label>
                {editing ? (
                  <Textarea
                    value={editForm.description}
                    onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                    rows={3}
                  />
                ) : (
                  <div className="text-sm whitespace-pre-wrap break-words rounded-md border bg-muted/30 p-2.5 min-h-[40px]">
                    {detail.description || "—"}
                  </div>
                )}
              </div>

              {/* 编辑字段（编辑模式） */}
              {editing && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label>{t("kanban.assignee")}</Label>
                    <Input
                      value={editForm.assignee}
                      onChange={e => setEditForm(f => ({ ...f, assignee: e.target.value }))}
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label>{t("kanban.priority")}</Label>
                    <Select value={editForm.priority} onValueChange={v => setEditForm(f => ({ ...f, priority: v }))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {[0, 1, 2, 3].map(p => (
                          <SelectItem key={p} value={String(p)}>{t(`kanban.priority${p}`)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}

              {/* 评论 */}
              <div className="grid gap-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <MessageCircle size={14} />
                  {t("kanban.comments")}
                  <span className="text-xs text-muted-foreground">({detail.comments?.length || 0})</span>
                </div>
                {(detail.comments || []).length === 0 && (
                  <div className="text-xs text-muted-foreground/70 border border-dashed rounded-md px-3 py-2">
                    {t("kanban.noCards")}
                  </div>
                )}
                {(detail.comments || []).map(c => (
                  <div key={c.id} className="rounded-md border bg-card p-2.5">
                    <div className="flex items-center gap-2 text-xs">
                      <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/10 text-primary text-[9px] font-semibold">
                        {initials(c.author)}
                      </span>
                      <span className="font-medium">{c.author}</span>
                      <span className="flex-1" />
                      <span className="text-muted-foreground">{formatTime(c.created_at)}</span>
                    </div>
                    <div className="mt-1 text-sm whitespace-pre-wrap break-words">{c.body}</div>
                  </div>
                ))}
                <div className="flex items-end gap-2">
                  <Textarea
                    value={commentText}
                    onChange={e => setCommentText(e.target.value)}
                    placeholder={t("kanban.commentPlaceholder")}
                    rows={2}
                    className="text-sm"
                  />
                  <Button size="sm" disabled={commentBusy || !commentText.trim()} onClick={submitComment}>
                    {t("kanban.commentSubmit")}
                  </Button>
                </div>
              </div>

              {/* 动态 */}
              {(detail.events || []).length > 0 && (
                <div className="grid gap-1">
                  <div className="text-sm font-medium flex items-center gap-2">
                    <IconRefresh size={14} />
                    {t("kanban.activity")}
                  </div>
                  <div className="rounded-md border bg-muted/20 p-2 space-y-1">
                    {(detail.events || []).slice(0, 10).map(ev => {
                      const payload = parseEventPayload(ev.payload);
                      const kind = eventKindLabel(ev.kind);
                      let suffix = "";
                      if (ev.kind === "moved" && payload.from && payload.to) suffix = `: ${payload.from} → ${payload.to}`;
                      if (ev.kind === "created" && payload.title) suffix = `: ${payload.title}`;
                      return (
                        <div key={ev.id} className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span className="text-[10px] uppercase tracking-wide opacity-70">{t(`kanban.${kind}`)}</span>
                          <span className="flex-1 truncate">{suffix}</span>
                          <span className="shrink-0">{formatTime(ev.created_at)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <DialogFooter className="flex items-center gap-2">
                <div className="flex-1" />
                {!editing ? (
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                    <Pencil size={14} className="mr-1" />
                    {t("kanban.save")}
                  </Button>
                ) : (
                  <>
                    <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>{t("kanban.cancel")}</Button>
                    <Button size="sm" onClick={submitSave}>
                      <IconCheck size={14} className="mr-1" />
                      {t("kanban.save")}
                    </Button>
                  </>
                )}
                <Button variant="destructive" size="sm" onClick={submitDelete}>
                  <Trash2 size={14} className="mr-1" />
                  {t("kanban.delete")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
