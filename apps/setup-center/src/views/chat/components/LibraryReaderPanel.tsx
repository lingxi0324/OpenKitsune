// ─── LibraryReaderPanel: 图书馆读书面板 ───
// 参考 CM-agentic (agentic-rs) 的「灵汐书阁」ReaderPage 界面与交互逻辑，
// 适配 OpenKitsune Web 环境：目录树浏览 → 行分页 Markdown 阅读 → 阅读历史 → AI 伴学。
// 书籍来源为后端 /api/library/* 接口（书库根目录默认 lynzie/图书馆）。

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type CSSProperties } from "react";
import {
  IconBook, IconX, IconChevronDown, IconChevronRight,
  IconFolder, IconFolderOpen, IconFileText, IconSearch,
  IconPlus, IconMinus, IconSend,
} from "../../../icons";
import { appendAuthToken } from "../utils/chatHelpers";
import { useMdModules } from "../hooks/useMdModules";
import type { ChatMessage } from "../../../types";

const HISTORY_KEY = "openkitsune-library-history";
const FONT_KEY = "openkitsune-library-font-size";
const MAX_HISTORY = 12;
// 每页行数（分页阅读，参照 CM-agentic 的 READER_CONFIG）
const PAGE_SIZE = 150;
// 超过此行数才启用分页
const PAGINATION_THRESHOLD = 200;

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  expanded?: boolean;
  children?: TreeNode[];
  childrenLoaded?: boolean;
}

interface FileEntry {
  name: string;
  path: string;
  isDir?: boolean;
  /** 后端返回的 snake_case 目录标记 */
  is_dir?: boolean;
  size?: number | null;
}

interface HistoryItem {
  path: string;
  name: string;
  lastPage: number;
  lastOpened: number;
}

interface LibraryReaderPanelProps {
  open: boolean;
  onClose: () => void;
  apiBaseUrl?: string;
  /**
   * 把问题连同当前页原文直接发送到工作区当前会话（聊天区 AI 回答），
   * 面板不关闭，回答会经 messages 流式回到面板的 AI 伴学问答列。
   */
  onAsk?: (prompt: string) => void;
  /** 工作区当前会话的消息（供 AI 伴学列实时展示问答气泡） */
  messages?: ChatMessage[];
  /** 工作区当前会话 id */
  activeConvId?: string | null;
}

const SUPPORTED_EXT = new Set([
  ".md", ".markdown", ".mdown", ".mkd", ".mdx",
  ".txt", ".text", ".log", ".csv", ".tsv",
  ".json", ".yaml", ".yml", ".toml", ".ini",
  ".html", ".htm", ".xml", ".rst", ".org",
  ".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java",
  ".c", ".h", ".cpp", ".hpp", ".sh", ".bat", ".ps1", ".sql",
]);

function isSupportedFile(name: string): boolean {
  const lower = name.toLowerCase();
  const dot = lower.lastIndexOf(".");
  return dot >= 0 && SUPPORTED_EXT.has(lower.slice(dot));
}

function formatSize(size?: number | null): string {
  if (!size || size <= 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function loadHistory(): HistoryItem[] {
  try {
    const saved = localStorage.getItem(HISTORY_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch {
    return [];
  }
}

function saveHistory(items: HistoryItem[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
  } catch {
    // ignore
  }
}

/**
 * 面板发送到会话的 prompt 形如「…我的问题：{question}\n\n阅读要求…」，
 * 气泡展示时只还原其中的问题，避免把阅读要求/原文刷进气泡。
 */
function extractAskQuestion(content: string): string {
  const m = content.match(
    /(?:回答我的问题|我的问题)：([\s\S]*?)(?:\n\n—— 当前阅读内容节选|—— 当前阅读内容节选|\n\n阅读要求|$)/,
  );
  if (m && m[1] && m[1].trim()) return m[1].trim();
  return content;
}

export function LibraryReaderPanel({ open, onClose, apiBaseUrl, onAsk, messages = [], activeConvId }: LibraryReaderPanelProps) {
  const baseUrl = apiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:18900");
  const md = useMdModules();

  // ── 书库配置 ──
  const [rootPath, setRootPath] = useState<string>("");
  const [rootExists, setRootExists] = useState<boolean>(false);
  const [configLoading, setConfigLoading] = useState(true);
  const [showRootEditor, setShowRootEditor] = useState(false);
  const [rootEditValue, setRootEditValue] = useState("");
  const [rootSaveError, setRootSaveError] = useState("");

  // ── 目录树 ──
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [treeLoading, setTreeLoading] = useState(false);
  const [treeError, setTreeError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // ── 阅读状态 ──
  const [currentFile, setCurrentFile] = useState<FileEntry | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [fileExt, setFileExt] = useState("");
  const [fileSupported, setFileSupported] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState("");
  const [breadcrumbs, setBreadcrumbs] = useState<string[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("");
  const [history, setHistory] = useState<HistoryItem[]>(loadHistory);
  const [fontSize, setFontSize] = useState<number>(() => {
    try {
      const saved = Number(localStorage.getItem(FONT_KEY));
      return saved >= 12 && saved <= 24 ? saved : 15;
    } catch {
      return 15;
    }
  });
  const contentRef = useRef<HTMLDivElement | null>(null);

  // ── AI 伴学（阅读器内嵌问答列，问答直接汇入工作区当前会话）──
  const [askInput, setAskInput] = useState("");
  const [qaOpen, setQaOpen] = useState(false);
  // 打开问答列时记录会话消息游标：问答列只展示此后的问答气泡
  const qaStartIdRef = useRef<string | null>(null);
  const qaListRef = useRef<HTMLDivElement | null>(null);
  const qaLenRef = useRef(0);
  const nearBottomRef = useRef(true);

  const openQa = useCallback(() => {
    if (qaStartIdRef.current === null) {
      qaStartIdRef.current = messages.length ? messages[messages.length - 1].id : null;
    }
    setQaOpen(true);
  }, [messages]);

  // 问答列展示的消息 = 打开问答列之后的会话消息（含流式中的回复）；若会话被切换/新建
  // （找不到游标 id），则回退展示最近 30 条，保证新问题与回答立即可见。
  const qaMessages = useMemo(() => {
    if (!qaOpen) return [];
    const startIdx = qaStartIdRef.current ? messages.findIndex((m) => m.id === qaStartIdRef.current) : -1;
    if (startIdx >= 0) return messages.slice(startIdx + 1);
    return messages.slice(-30);
  }, [messages, qaOpen]);

  const isAsking = qaMessages.some((m) => m.role === "assistant" && m.streaming);

  // 新消息到达或流式推进时自动滚到底（用户手动上翻时停止跟随）
  const onQaScroll = useCallback(() => {
    const el = qaListRef.current;
    if (!el) return;
    nearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);
  useEffect(() => {
    if (!qaOpen) return;
    const el = qaListRef.current;
    if (!el) return;
    const newMsg = qaLenRef.current !== qaMessages.length;
    qaLenRef.current = qaMessages.length;
    if (newMsg || nearBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [qaMessages, qaOpen]);

  const renderQaBubble = useCallback((m: ChatMessage): ReactNode | null => {
    if (m.role !== "user" && m.role !== "assistant") return null;
    const isUser = m.role === "user";
    let body: ReactNode;
    if (m.errorInfo) {
      body = <span style={{ color: "#ef4444" }}>{m.errorInfo.message || "生成失败"}</span>;
    } else if (m.streaming) {
      if (m.content) {
        body = (
          <span>
            {m.content}
            <span style={{ opacity: 0.55, marginLeft: 2 }}>▍</span>
          </span>
        );
      } else if (m.thinking) {
        const shown = m.thinking.length > 600 ? `${m.thinking.slice(0, 600)}…` : m.thinking;
        body = (
          <span style={{ color: "var(--muted)" }}>
            {shown}
            <span style={{ opacity: 0.55 }}>▍</span>
          </span>
        );
      } else {
        body = <span style={{ color: "var(--muted)" }}>思考中…</span>;
      }
    } else {
      const text = isUser ? extractAskQuestion(m.content) : m.content;
      body = text ? (
        <span>{text}</span>
      ) : (
        <span style={{ color: "var(--muted)" }}>（无正文回复）</span>
      );
    }
    return (
      <div key={m.id} style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
        <div
          style={{
            maxWidth: "86%", padding: "7px 11px", borderRadius: 10,
            fontSize: 13, lineHeight: 1.55, whiteSpace: "pre-wrap", wordBreak: "break-word",
            background: isUser ? "var(--primary)" : "var(--bg)",
            color: isUser ? "#fff" : "var(--text)",
            border: isUser ? "none" : "1px solid var(--line)",
          }}
        >
          {body}
        </div>
      </div>
    );
  }, []);

  const fileLines = useMemo(() => (fileContent ? fileContent.split("\n") : []), [fileContent]);
  const totalLines = fileLines.length;
  const totalPages = Math.max(1, Math.ceil(totalLines / PAGE_SIZE));
  const needsPagination = totalLines > PAGINATION_THRESHOLD;
  const pageContent = useMemo(() => {
    if (!needsPagination) return fileContent;
    return fileLines.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).join("\n");
  }, [fileContent, fileLines, currentPage, needsPagination]);

  const apiGet = useCallback(
    (url: string) => fetch(appendAuthToken(`${baseUrl}${url}`), { cache: "no-store" }),
    [baseUrl],
  );

  // 打开面板时加载书库配置（根目录树由 refreshRootTree 统一加载）
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setConfigLoading(true);
    (async () => {
      try {
        const resp = await apiGet("/api/library/config");
        const cfg = await resp.json();
        if (cancelled) return;
        setRootPath(cfg.root_path || "");
        setRootExists(!!cfg.exists);
        setRootEditValue(cfg.root_path || "");
      } catch {
        if (!cancelled) setTreeError("无法连接后端服务，请确认 OpenKitsune 已启动");
      } finally {
        if (!cancelled) setConfigLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 加载目录树（path 为相对书库根的路径，空 = 根目录）
  const loadTreeAt = useCallback(async (path: string): Promise<TreeNode[]> => {
    setTreeLoading(true);
    setTreeError("");
    try {
      const resp = await apiGet(`/api/library/tree?path=${encodeURIComponent(path)}`);
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const nodes: TreeNode[] = (data.entries || []).map((e: FileEntry) => ({
        name: e.name,
        path: e.path,
        // 后端返回 snake_case 的 is_dir，这里兼容两种命名
        isDir: !!(e.is_dir ?? e.isDir),
        expanded: false,
        children: e.is_dir ?? e.isDir ? [] : undefined,
        childrenLoaded: false,
      }));
      // 中文排序：目录在前
      nodes.sort((a, b) => {
        if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
        return a.name.localeCompare(b.name, "zh-CN");
      });
      return nodes;
    } catch (err) {
      setTreeError(err instanceof Error ? err.message : String(err));
      return [];
    } finally {
      setTreeLoading(false);
    }
  }, [apiGet]);

  // 初次加载根目录（panel 打开 + 更换目录后调用）
  const refreshRootTree = useCallback(async () => {
    const nodes = await loadTreeAt("");
    setTree(nodes);
  }, [loadTreeAt]);

  useEffect(() => {
    if (open && rootExists) { void refreshRootTree(); }
  }, [open, rootExists, refreshRootTree]);

  // 展开/折叠目录节点（懒加载子目录）
  const toggleNode = useCallback(async (node: TreeNode) => {
    if (!node.isDir) return;
    const updateNode = (nodes: TreeNode[]): TreeNode[] =>
      nodes.map((n) => {
        if (n.path === node.path) {
          if (n.expanded) return { ...n, expanded: false };
          if (!n.childrenLoaded) {
            void (async () => {
              const children = await loadTreeAt(node.path);
              setTree((prev) => {
                const patch = (items: TreeNode[]): TreeNode[] =>
                  items.map((x) =>
                    x.path === node.path
                      ? { ...x, expanded: true, children, childrenLoaded: true }
                      : x.children ? { ...x, children: patch(x.children) } : x,
                  );
                return patch(prev);
              });
            })();
          }
          return { ...n, expanded: true };
        }
        if (n.children) return { ...n, children: updateNode(n.children) };
        return n;
      });
    setTree((prev) => updateNode(prev));
  }, [loadTreeAt]);

  // 记录阅读历史（打开文件时）
  const pushHistory = useCallback((path: string, name: string, lastPage: number) => {
    setHistory((prev) => {
      const next = [
        { path, name, lastPage, lastOpened: Date.now() },
        ...prev.filter((h) => h.path !== path),
      ].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }, []);

  // 打开文件
  const openFile = useCallback(async (entry: FileEntry, restorePage?: number) => {
    if (!entry.isDir && !isSupportedFile(entry.name)) {
      setCurrentFile(entry);
      setFileContent("");
      setFileExt(entry.name.includes(".") ? entry.name.slice(entry.name.lastIndexOf(".")).toLowerCase() : "");
      setFileSupported(false);
      setFileError("");
      return;
    }
    setFileLoading(true);
    setFileError("");
    try {
      const resp = await apiGet(`/api/library/file?path=${encodeURIComponent(entry.path)}`);
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      if (!data.supported) {
        setCurrentFile(entry);
        setFileContent("");
        setFileExt(data.ext || "");
        setFileSupported(false);
        return;
      }
      setCurrentFile(entry);
      setFileContent(data.content || "");
      setFileExt(data.ext || "");
      setFileSupported(true);
      setBreadcrumbs(entry.path.split("/").filter(Boolean));
      const targetPage = restorePage && restorePage >= 1 ? restorePage : 1;
      setCurrentPage(targetPage);
      setPageInput(String(targetPage));
      pushHistory(entry.path, entry.name, targetPage);
      requestAnimationFrame(() => contentRef.current?.scrollTo({ top: 0 }));
    } catch (err) {
      setFileError(err instanceof Error ? err.message : String(err));
    } finally {
      setFileLoading(false);
    }
  }, [apiGet, pushHistory]);

  // 翻页后记录进度到历史（节流）
  const currentPageRef = useRef(currentPage);
  currentPageRef.current = currentPage;
  const historySyncTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!currentFile || !currentFile.path) return;
    if (historySyncTimer.current) clearTimeout(historySyncTimer.current);
    historySyncTimer.current = setTimeout(() => {
      setHistory((prev) => {
        const next = prev.map((h) =>
          h.path === currentFile.path ? { ...h, lastPage: currentPageRef.current, lastOpened: Date.now() } : h,
        );
        saveHistory(next);
        return next;
      });
    }, 800);
    return () => { if (historySyncTimer.current) clearTimeout(historySyncTimer.current); };
  }, [currentPage, currentFile]);

  // 目录树渲染（含搜索过滤）
  const renderTreeNode = (node: TreeNode, depth: number): ReactNode => {
    const q = searchQuery.trim().toLowerCase();
    const isMatch = !q || node.name.toLowerCase().includes(q);
    if (q && !isMatch && !node.isDir) return null;
    const isActive = currentFile?.path === node.path;
    return (
      <div key={node.path}>
        <div
          onClick={() => { if (node.isDir) void toggleNode(node); else void openFile(node); }}
          title={node.path}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "3px 8px", paddingLeft: 8 + depth * 14,
            borderRadius: 6, cursor: "pointer", fontSize: 13,
            background: isActive ? "var(--primary)" : "transparent",
            color: isActive ? "#fff" : "var(--text)",
          }}
          onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = "var(--hover, rgba(128,128,128,0.08))"; }}
          onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
        >
          <span style={{ width: 14, flexShrink: 0, display: "flex", justifyContent: "center", opacity: 0.6 }}>
            {node.isDir
              ? node.expanded ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />
              : null}
          </span>
          <span style={{ flexShrink: 0, display: "flex", opacity: 0.85 }}>
            {node.isDir
              ? node.expanded ? <IconFolderOpen size={15} /> : <IconFolder size={15} />
              : <IconFileText size={14} />}
          </span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {node.name}
          </span>
        </div>
        {node.isDir && node.expanded && node.children && (
          <div>{node.children.map((child) => renderTreeNode(child, depth + 1))}</div>
        )}
      </div>
    );
  };

  // 保存新的书库根目录
  const saveRoot = useCallback(async () => {
    const root = rootEditValue.trim();
    if (!root) { setRootSaveError("路径不能为空"); return; }
    setRootSaveError("");
    try {
      const resp = await fetch(appendAuthToken(`${baseUrl}/api/library/config`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ root_path: root }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${resp.status}`);
      }
      const cfg = await resp.json();
      setRootPath(cfg.root_path || root);
      setRootExists(true);
      setShowRootEditor(false);
      setTree([]);
      const nodes = await loadTreeAt("");
      setTree(nodes);
    } catch (err) {
      setRootSaveError(err instanceof Error ? err.message : String(err));
    }
  }, [rootEditValue, baseUrl, loadTreeAt]);

  // AI 伴学：把问题 + 书籍定位信息发送到工作区当前会话（面板保持打开）。
  // 不再一次塞入整页原文；AI 使用 library_read_page 工具按当前页起分批增量阅读。
  const handleAsk = useCallback(() => {
    const question = askInput.trim();
    if (!question || !currentFile || !onAsk) return;
    const relPath = currentFile.path; // 书库根内相对路径，如 丹道/九华金书.md
    const pageDesc = needsPagination ? `（第 ${currentPage}/${totalPages} 页）` : "";
    const prompt =
      `我在「图书馆」阅读《${currentFile.name}》${pageDesc}。\n` +
      `书库相对路径：${relPath}\n` +
      `我的问题：${question}\n\n` +
      `阅读要求：\n` +
      `- 请使用 library_read_page 工具分批增量阅读原文，不要一次性读取全部内容；\n` +
      `- 先读取当前页：library_read_page(path="${relPath}", page=${currentPage})；\n` +
      `- 若需更多上下文，请根据返回的 total_pages/has_more 按需继续翻页（page=下一页…），直到找到答案；\n` +
      `- 回答时引用原文，并说明内容出自第几页。`;
    onAsk(prompt);
    setAskInput("");
  }, [askInput, currentFile, needsPagination, currentPage, totalPages, onAsk]);

  // 分页跳转
  const jumpToPage = useCallback((page: number) => {
    const target = Math.max(1, Math.min(totalPages, Math.floor(page) || 1));
    setCurrentPage(target);
    setPageInput(String(target));
    requestAnimationFrame(() => contentRef.current?.scrollTo({ top: 0 }));
  }, [totalPages]);

  const prevPage = useCallback(() => jumpToPage(currentPage - 1), [currentPage, jumpToPage]);
  const nextPage = useCallback(() => jumpToPage(currentPage + 1), [currentPage, jumpToPage]);

  const changeFont = useCallback((delta: number) => {
    setFontSize((prev) => {
      const next = Math.max(12, Math.min(24, prev + delta));
      try { localStorage.setItem(FONT_KEY, String(next)); } catch { /* ignore */ }
      return next;
    });
  }, []);

  if (!open) return null;

  const sidebar = (
    <div style={{ display: "flex", flexDirection: "column", width: 300, flexShrink: 0, borderRight: "1px solid var(--line)", background: "var(--panel2)" }}>
      {/* 书库标题 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--line)" }}>
        <span style={{ display: "flex", color: "var(--primary)" }}><IconBook size={18} /></span>
        <span style={{ fontWeight: 600, fontSize: 14, color: "var(--text)" }}>图书馆</span>
        <span style={{ flex: 1 }} />
        <button
          onClick={() => { setShowRootEditor((v) => !v); setRootSaveError(""); }}
          style={linkBtnStyle}
          title="更换书库目录"
        >
          更换目录
        </button>
        <button onClick={onClose} aria-label="关闭" style={{ ...iconBtnStyle, color: "var(--muted)" }} title="关闭">
          <IconX size={16} />
        </button>
      </div>

      {/* 书库目录编辑器（默认收起） */}
      {showRootEditor && (
        <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--line)", display: "flex", flexDirection: "column", gap: 6 }}>
          <input
            value={rootEditValue}
            onChange={(e) => setRootEditValue(e.target.value)}
            placeholder="输入书库根目录绝对路径"
            style={inputStyle}
          />
          {rootSaveError && <span style={{ color: "#ef4444", fontSize: 12 }}>{rootSaveError}</span>}
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={() => void saveRoot()} style={{ ...primaryBtnStyle, flex: 1 }}>保存</button>
            <button onClick={() => { setShowRootEditor(false); setRootSaveError(""); }} style={ghostBtnStyle}>取消</button>
          </div>
        </div>
      )}

      {/* 根目录路径提示 */}
      {rootPath && (
        <div style={{ padding: "6px 14px", fontSize: 11, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", borderBottom: "1px solid var(--line)" }} title={rootPath}>
          {rootPath}
        </div>
      )}

      {/* 最近阅读 */}
      <div style={{ padding: "8px 14px 4px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--muted)", marginBottom: 4 }}>最近阅读</div>
        {history.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--muted)", padding: "2px 0 6px" }}>暂无记录</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 1, maxHeight: 120, overflowY: "auto" }}>
            {history.map((h) => (
              <button
                key={h.path}
                onClick={() => {
                  void openFile({ name: h.name, path: h.path, isDir: false }, h.lastPage);
                }}
                style={{
                  display: "flex", alignItems: "center", gap: 6, textAlign: "left",
                  padding: "3px 6px", borderRadius: 6, cursor: "pointer", fontSize: 12,
                  background: "transparent", color: "var(--text)", border: "none",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--hover, rgba(128,128,128,0.08))"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
              >
                <IconFileText size={12} style={{ flexShrink: 0, opacity: 0.5 }} />
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</span>
                {h.lastPage > 1 && <span style={{ color: "var(--muted)", fontSize: 11, flexShrink: 0 }}>p{h.lastPage}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 文件名搜索 */}
      <div style={{ padding: "8px 14px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ position: "relative" }}>
          <span style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", display: "flex", color: "var(--muted)" }}>
            <IconSearch size={14} />
          </span>
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索文件名..."
            style={{ ...inputStyle, paddingLeft: 30 }}
          />
        </div>
      </div>

      {/* 目录树 */}
      <div style={{ flex: 1, overflowY: "auto", padding: 6 }}>
        {configLoading && tree.length === 0 ? (
          <div style={{ padding: 16, textAlign: "center", fontSize: 13, color: "var(--muted)" }}>加载中...</div>
        ) : treeLoading && tree.length === 0 ? (
          <div style={{ padding: 16, textAlign: "center", fontSize: 13, color: "var(--muted)" }}>加载书库...</div>
        ) : !rootExists ? (
          <div style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 13, color: "#ef4444", marginBottom: 8 }}>书库目录不存在</div>
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
              默认路径：{rootPath || "E:\\agents\\CM-agentic\\lynzie\\图书馆"}
              <br />点击上方「更换目录」设置正确的书库路径
            </div>
          </div>
        ) : treeError ? (
          <div style={{ padding: 16, textAlign: "center" }}>
            <div style={{ fontSize: 13, color: "#ef4444", marginBottom: 8 }}>{treeError}</div>
            <button onClick={() => void refreshRootTree()} style={ghostBtnStyle}>重试</button>
          </div>
        ) : tree.length === 0 ? (
          <div style={{ padding: 16, textAlign: "center", fontSize: 13, color: "var(--muted)" }}>书库为空</div>
        ) : (
          tree.map((node) => renderTreeNode(node, 0))
        )}
      </div>
    </div>
  );

  // 阅读区工具栏
  const readerToolbar = (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderBottom: "1px solid var(--line)", background: "var(--panel2)" }}>
      <span style={{ display: "flex", color: "var(--primary)" }}><IconBook size={15} /></span>
      {breadcrumbs.length > 0 ? (
        <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, minWidth: 0, overflow: "hidden" }}>
          {breadcrumbs.map((crumb, idx) => (
            <span key={idx} style={{ display: "flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" }}>
              {idx > 0 && <span style={{ color: "var(--muted)" }}>/</span>}
              <span style={{ color: idx === breadcrumbs.length - 1 ? "var(--text)" : "var(--muted)", fontWeight: idx === breadcrumbs.length - 1 ? 600 : 400 }}>
                {crumb}
              </span>
            </span>
          ))}
        </span>
      ) : (
        <span style={{ fontSize: 13, color: "var(--muted)" }}>从左侧选择典籍开始阅读</span>
      )}
      <span style={{ flex: 1 }} />
      {/* 字号调节 */}
      <button onClick={() => changeFont(-1)} title="减小字号" style={iconBtnStyle}>
        <IconMinus size={14} />
      </button>
      <span style={{ fontSize: 12, color: "var(--muted)", width: 28, textAlign: "center" }}>{fontSize}</span>
      <button onClick={() => changeFont(1)} title="增大字号" style={iconBtnStyle}>
        <IconPlus size={14} />
      </button>
      {currentFile && fileSupported && (
        <span style={{ fontSize: 12, color: "var(--muted)" }}>{totalLines.toLocaleString()} 行</span>
      )}
      <button onClick={onClose} aria-label="关闭读书面板" style={{ ...iconBtnStyle, color: "var(--muted)" }} title="关闭">
        <IconX size={16} />
      </button>
    </div>
  );

  // 阅读区内容
  const readerContent = (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, background: "var(--bg)" }}>
      {fileLoading ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: 13 }}>
          加载中...
        </div>
      ) : fileError ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
          <span style={{ color: "#ef4444", fontSize: 13 }}>{fileError}</span>
        </div>
      ) : !currentFile ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, color: "var(--muted)" }}>
          <span style={{ display: "flex", fontSize: 40, opacity: 0.4 }}><IconBook size={48} /></span>
          <div style={{ fontSize: 14 }}>📚 图书馆 · 选择左侧典籍开始阅读</div>
          <div style={{ fontSize: 12, opacity: 0.7 }}>丹道 · 医藏 · 玄学 · 道藏</div>
        </div>
      ) : !fileSupported ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, color: "var(--muted)" }}>
          <span style={{ fontSize: 13 }}>暂不支持在线预览 <b>{fileExt || "该格式"}</b> 文件</span>
          <span style={{ fontSize: 12, opacity: 0.7 }}>{currentFile.name}（{formatSize(currentFile.size)}）</span>
        </div>
      ) : (
        <>
          {/* 正文（行分页） */}
          <div
            ref={contentRef}
            style={{
              flex: 1, minHeight: 0, overflowY: "auto", padding: "28px 48px",
              fontSize, lineHeight: 1.9, color: "var(--text)",
            }}
          >
            {md ? (
              <div className="libraryReaderMarkdown" style={{ maxWidth: 860, margin: "0 auto" }}>
                <md.ReactMarkdown
                  remarkPlugins={md.remarkPlugins}
                  rehypePlugins={md.rehypePlugins}
                  components={{
                    img: ({ src, alt }: any) => {
                      let url = String(src || "");
                      if (url && !url.startsWith("data:") && !/^https?:\/\//i.test(url)) {
                        url = appendAuthToken(`${baseUrl}${url.startsWith("/") ? "" : "/"}${url}`);
                      }
                      return <img src={url} alt={alt || ""} style={{ maxWidth: "100%" }} />;
                    },
                  }}
                >
                  {pageContent || "（空）"}
                </md.ReactMarkdown>
              </div>
            ) : (
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>{pageContent || "（空）"}</pre>
            )}
          </div>

          {/* 底部：分页 + AI 伴学入口 */}
          <div style={{ borderTop: "1px solid var(--line)", background: "var(--panel2)", padding: "8px 14px" }}>
            {needsPagination && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <button onClick={prevPage} disabled={currentPage <= 1} style={{ ...iconBtnStyle, ...(currentPage <= 1 ? { opacity: 0.4 } : {}) }}>
                  ‹
                </button>
                <span style={{ fontSize: 12, color: "var(--muted)", whiteSpace: "nowrap" }}>
                  第
                  <input
                    value={pageInput}
                    onChange={(e) => setPageInput(e.target.value)}
                    onBlur={() => setPageInput(String(currentPage))}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); jumpToPage(Number(pageInput)); } }}
                    style={{ ...inputStyle, width: 46, margin: "0 4px", textAlign: "center", padding: "2px 4px" }}
                  />
                  页 / 共 {totalPages} 页 · {totalLines.toLocaleString()} 行
                </span>
                <button onClick={nextPage} disabled={currentPage >= totalPages} style={{ ...iconBtnStyle, ...(currentPage >= totalPages ? { opacity: 0.4 } : {}) }}>
                  ›
                </button>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ flex: 1 }} />
              <button
                onClick={() => (qaOpen ? setQaOpen(false) : openQa())}
                style={{ ...ghostBtnStyle, fontSize: 12 }}
                title="阅读时内嵌 AI 问答，问题直接汇入工作区当前会话"
              >
                🤖 AI 伴学{qaOpen ? " · 收起" : ""}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );

  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 1100, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.45)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          position: "absolute", inset: 28,
          display: "flex", flexDirection: "column",
          background: "var(--bg)", borderRadius: 14,
          border: "1px solid var(--line)", boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
          overflow: "hidden",
        }}
      >
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          {sidebar}
          <div style={{ display: "flex", flex: 1, flexDirection: "column", minWidth: 0 }}>
            {readerToolbar}
            {readerContent}
          </div>
          {/* AI 伴学问答列（对话直接汇入工作区当前会话，气泡实时展示会话内问答） */}
          {qaOpen && (
            <div style={{ width: 380, flexShrink: 0, borderLeft: "1px solid var(--line)", background: "var(--panel2)", display: "flex", flexDirection: "column", minHeight: 0 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderBottom: "1px solid var(--line)" }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text)" }}>🤖 AI 伴学</span>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>问答汇入工作区会话</span>
                <span style={{ flex: 1 }} />
                <button onClick={() => setQaOpen(false)} style={iconBtnStyle} title="收起问答列">
                  <IconChevronRight size={14} />
                </button>
              </div>
              <div
                ref={qaListRef}
                onScroll={onQaScroll}
                style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 10 }}
              >
                {qaMessages.length === 0 ? (
                  <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.7, marginTop: 18, textAlign: "center" }}>
                    针对《{currentFile?.name || "当前典籍"}》提问，<br />
                    AI 将在工作区当前会话中回答，
                    <br />问答会同步保留在聊天记录里。
                  </div>
                ) : (
                  qaMessages.map((m) => renderQaBubble(m))
                )}
              </div>
              <div style={{ borderTop: "1px solid var(--line)", padding: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                <textarea
                  value={askInput}
                  onChange={(e) => setAskInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleAsk(); }
                  }}
                  placeholder={`针对《${currentFile?.name || "当前典籍"}》提问…`}
                  rows={2}
                  style={{ ...inputStyle, resize: "none", lineHeight: 1.5, fontFamily: "inherit" }}
                />
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 11, color: "var(--muted)", flex: 1 }}>Enter 发送 · Shift+Enter 换行</span>
                  <button
                    onClick={handleAsk}
                    disabled={!askInput.trim() || !onAsk || isAsking}
                    style={{ ...primaryBtnStyle, ...(!askInput.trim() || !onAsk || isAsking ? { opacity: 0.5 } : {}) }}
                    title={isAsking ? "AI 正在回答中" : "发送到工作区会话"}
                  >
                    <IconSend size={14} />
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 样式常量 ──

const linkBtnStyle: CSSProperties = {
  background: "none", border: "none", cursor: "pointer",
  color: "var(--primary)", fontSize: 12, padding: "2px 4px",
};

const iconBtnStyle: CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center",
  width: 26, height: 26, borderRadius: 6, cursor: "pointer",
  background: "transparent", border: "none", color: "var(--text)",
};

const inputStyle: CSSProperties = {
  width: "100%", padding: "5px 10px", borderRadius: 8, fontSize: 13,
  background: "var(--bg)", border: "1px solid var(--line)",
  color: "var(--text)", outline: "none", boxSizing: "border-box",
};

const primaryBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 4,
  padding: "5px 12px", borderRadius: 8, fontSize: 13, cursor: "pointer",
  background: "var(--primary)", color: "#fff", border: "none", fontWeight: 600,
};

const ghostBtnStyle: CSSProperties = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 4,
  padding: "5px 12px", borderRadius: 8, fontSize: 13, cursor: "pointer",
  background: "transparent", border: "1px solid var(--line)", color: "var(--text)",
};
