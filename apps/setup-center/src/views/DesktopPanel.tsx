/**
 * DesktopPanel — AI 桌面可视化浮层（链接式开关 + 右侧滑出面板）
 *
 * 数据源：GET /api/desktop/state（后端 tools/desktop/state.py 采集器）
 * - 截图预览：/api/files?path=... 走 ?token= 认证（<img> 无法带 header）
 * - 手动刷新 + 3s 自动刷新（开关）
 * - 展示：截图 / 屏幕尺寸 / 指针 / 活动窗口 / 可见窗口 / 能力探测 / 错误
 *
 * 组件自包含：样式全部内联 + 局部 keyframes（dt- 前缀），不污染全局样式。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Monitor,
  X,
  RefreshCw,
  Loader2,
  MousePointer,
  Maximize2,
  AppWindow,
  RadioTower,
  CircleDot,
  WifiOff,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from "lucide-react";
import { getAccessToken } from "../platform/auth";
import { safeFetch } from "../providers";

const DEFAULT_API_BASE = "http://127.0.0.1:18900";
const AUTO_REFRESH_MS = 3000;
const PANEL_CONTEXT_ID = "desktop-panel";

interface DesktopWindowInfo {
  title?: string;
  handle?: number;
  process_id?: number;
  class_name?: string;
  process_name?: string;
  bbox?: number[] | null;
  is_visible?: boolean;
  is_focused?: boolean;
  is_minimized?: boolean;
  is_maximized?: boolean;
}

interface DesktopActivity {
  kind?: string;
  ts?: string;
  target?: string;
  detail?: string;
  window?: string;
  location?: string;
  x?: number;
  y?: number;
}

interface DesktopStateData {
  ok: boolean;
  context_id?: string;
  screen_size?: { width?: number; height?: number };
  pointer?: { x?: number; y?: number };
  active_window?: DesktopWindowInfo | null;
  windows?: DesktopWindowInfo[];
  activity?: DesktopActivity[];
  screenshot?: {
    ok?: boolean;
    path?: string;
    file_url?: string;
    width?: number;
    height?: number;
    captured_at?: string;
    recent?: boolean;
  };
  capabilities?: Record<string, string>;
  errors?: string[];
}

interface DesktopPanelProps {
  apiBaseUrl?: string;
}

function withAuthToken(url: string): string {
  const token = getAccessToken();
  if (!token) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
}

function formatCapturedAt(iso: string | undefined): string {
  if (!iso) return "";
  const date = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString([], { hour12: false });
}

const CAPABILITY_LABELS: Record<string, string> = {
  mss: "mss",
  pyautogui: "pyautogui",
  pywinauto: "pywinauto",
  PIL: "Pillow",
};

export function DesktopPanel({ apiBaseUrl = DEFAULT_API_BASE }: DesktopPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<DesktopStateData | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string>("");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [imgReady, setImgReady] = useState(false);
  const [imgFailed, setImgFailed] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [actionError, setActionError] = useState("");
  const [detailsKey, setDetailsKey] = useState("");
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsText, setDetailsText] = useState("");
  const [detailsError, setDetailsError] = useState("");
  const [openTarget, setOpenTarget] = useState("");
  const [openBusy, setOpenBusy] = useState(false);
  const [openError, setOpenError] = useState("");
  const [clickThrough, setClickThrough] = useState(false);
  const [clickBusy, setClickBusy] = useState(false);
  const [clickError, setClickError] = useState("");
  const [clickMark, setClickMark] = useState<{ x: number; y: number; ts: number } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchState = useCallback(
    async (withScreenshot: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setFetchError("");
      try {
        const url = `${apiBaseUrl}/api/desktop/state?include_screenshot=${withScreenshot ? 1 : 0}&context_id=${PANEL_CONTEXT_ID}&refresh=1&screenshot_max_width=1280&screenshot_max_height=720`;
        const res = await safeFetch(url, { signal: controller.signal });
        if (!res.ok) {
          const body = await res.text().catch(() => "");
          throw new Error(`HTTP ${res.status}${body ? ` ${body.slice(0, 120)}` : ""}`);
        }
        const payload = (await res.json()) as DesktopStateData;
        setData(payload);
        setImgReady(false);
        setImgFailed(false);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setFetchError((err as Error).message || String(err));
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  const windowKey = useCallback(
    (win: DesktopWindowInfo) => String(win.handle ?? win.title ?? ""),
    [],
  );

  // 用户点击窗口 → 置前/恢复；AI 侧可通过 desktop_state 感知到新的活动窗口
  const activateWindow = useCallback(
    async (win: DesktopWindowInfo) => {
      const key = windowKey(win);
      if (!key || busyKey) return;
      setBusyKey(key);
      setActionError("");
      try {
        const res = await safeFetch(`${apiBaseUrl}/api/desktop/window`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "switch",
            title: win.title,
            handle: win.handle,
          }),
        });
        const payload = (await res.json()) as {
          ok?: boolean;
          error?: string;
          errors?: string[];
        };
        if (!res.ok || !payload.ok) {
          throw new Error(payload.error || payload.errors?.[0] || `HTTP ${res.status}`);
        }
        await fetchState(false);
      } catch (err) {
        setActionError((err as Error).message || String(err));
      } finally {
        setBusyKey("");
      }
    },
    [apiBaseUrl, busyKey, fetchState, windowKey],
  );

  // 展开/收起窗口元素树（用户查看 + AI 感知同一份数据源）
  const toggleDetails = useCallback(
    async (win: DesktopWindowInfo) => {
      const key = windowKey(win);
      if (!key) return;
      if (detailsKey === key) {
        setDetailsKey("");
        return;
      }
      setDetailsKey(key);
      setDetailsText("");
      setDetailsError("");
      setDetailsLoading(true);
      try {
        const params = new URLSearchParams({ depth: "2" });
        if (win.handle) params.set("handle", String(win.handle));
        else params.set("title", win.title || "");
        const res = await safeFetch(
          `${apiBaseUrl}/api/desktop/window/elements?${params.toString()}`,
        );
        const payload = (await res.json()) as {
          ok?: boolean;
          text?: string;
          error?: string;
          errors?: string[];
        };
        if (!res.ok || !payload.ok) {
          throw new Error(payload.error || payload.errors?.[0] || `HTTP ${res.status}`);
        }
        setDetailsText(payload.text || "");
      } catch (err) {
        setDetailsError((err as Error).message || String(err));
      } finally {
        setDetailsLoading(false);
      }
    },
    [apiBaseUrl, detailsKey, windowKey],
  );

  // 用户从面板打开路径/网址；后端会记录活动供 AI 感知
  const submitOpenTarget = useCallback(async () => {
    const target = openTarget.trim();
    if (!target || openBusy) return;
    setOpenBusy(true);
    setOpenError("");
    try {
      const res = await safeFetch(`${apiBaseUrl}/api/desktop/open`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      const payload = (await res.json()) as {
        ok?: boolean;
        error?: string;
        errors?: string[];
      };
      if (!res.ok || !payload.ok) {
        throw new Error(payload.error || payload.errors?.[0] || `HTTP ${res.status}`);
      }
      await fetchState(true);
    } catch (err) {
      setOpenError((err as Error).message || String(err));
    } finally {
      setOpenBusy(false);
    }
  }, [apiBaseUrl, fetchState, openBusy, openTarget]);

  // 预览图点击穿透：按预览比例换算成屏幕绝对坐标后真实点击
  const handlePreviewClick = useCallback(
    async (e: React.MouseEvent<HTMLImageElement>) => {
      if (!clickThrough || clickBusy) return;
      const img = e.currentTarget;
      const rect = img.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return;

      const relX = (e.clientX - rect.left) / rect.width;
      const relY = (e.clientY - rect.top) / rect.height;
      const screenW = data?.screen_size?.width || img.naturalWidth;
      const screenH = data?.screen_size?.height || img.naturalHeight;
      if (!screenW || !screenH) return;

      const x = Math.round(relX * screenW);
      const y = Math.round(relY * screenH);
      setClickBusy(true);
      setClickError("");
      setClickMark({ x: relX, y: relY, ts: Date.now() });
      try {
        const res = await safeFetch(`${apiBaseUrl}/api/desktop/click`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ x, y, button: "left" }),
        });
        const payload = (await res.json()) as {
          ok?: boolean;
          error?: string;
          errors?: string[];
        };
        if (!res.ok || !payload.ok) {
          throw new Error(payload.error || payload.errors?.[0] || `HTTP ${res.status}`);
        }
        await fetchState(true);
      } catch (err) {
        setClickError((err as Error).message || String(err));
      } finally {
        setClickBusy(false);
      }
    },
    [apiBaseUrl, clickBusy, clickThrough, data?.screen_size, fetchState],
  );

  // 点击标记短暂显示后清除
  useEffect(() => {
    if (!clickMark) return;
    const timer = window.setTimeout(() => setClickMark(null), 800);
    return () => window.clearTimeout(timer);
  }, [clickMark]);

  // 打开面板时立即拉一次（带截图）
  useEffect(() => {
    if (!open) return;
    void fetchState(true);
  }, [open, fetchState]);

  // 自动刷新
  useEffect(() => {
    if (!open || !autoRefresh) return;
    const timer = window.setInterval(() => {
      void fetchState(true);
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [open, autoRefresh, fetchState]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // 卸载时中止在途请求
  useEffect(() => () => abortRef.current?.abort(), []);

  const screenshotUrl = data?.screenshot?.ok && data.screenshot.file_url
    ? withAuthToken(`${apiBaseUrl}${data.screenshot.file_url}`)
    : "";

  const windows = data?.windows ?? [];
  const visibleWindows = windows.filter((w) => w.is_visible !== false).slice(0, 20);
  const capabilities = data?.capabilities ?? {};
  const activity = data?.activity ?? [];
  const errors = data?.errors ?? [];

  const renderScreenshot = () => {
    if (!screenshotUrl) {
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center", justifyContent: "center", minHeight: 180, color: "var(--muted)", fontSize: 13 }}>
          <Monitor size={28} opacity={0.5} />
          <span>{t("desktop.noScreenshot", "暂无截图")}</span>
        </div>
      );
    }
    const interactive = clickThrough;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={() => {
              setClickThrough((v) => !v);
              setClickError("");
            }}
            title={t("desktop.clickThroughHint", "开启后可在截图上直接点击")}
            style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "4px 9px", borderRadius: 8, cursor: "pointer", fontSize: 11,
              border: `1px solid ${clickThrough ? "color-mix(in srgb, var(--accent, #60a5fa) 45%, var(--line))" : "var(--line)"}`,
              background: clickThrough ? "color-mix(in srgb, var(--accent, #60a5fa) 12%, transparent)" : "transparent",
              color: clickThrough ? "var(--accent, #60a5fa)" : "var(--muted)",
            }}
          >
            <MousePointer size={12} />
            {clickThrough
              ? t("desktop.clickThroughOn", "点击穿透：开")
              : t("desktop.clickThrough", "点击穿透")}
          </button>
          <span style={{ fontSize: 10, color: "var(--muted)", flex: 1 }}>
            {clickThrough
              ? t(
                  "desktop.clickThroughHintOn",
                  "点击画面即真实点击；若面板遮挡会先最小化再恢复",
                )
              : t("desktop.clickThroughHint", "开启后可在截图上直接点击")}
          </span>
          {clickBusy && <Loader2 size={12} className="dt-spin" />}
        </div>
        {clickError && (
          <div style={{ fontSize: 11, color: "#dc2626", overflowWrap: "anywhere" }}>
            {clickError}
          </div>
        )}
        <div style={{ position: "relative", borderRadius: 12, overflow: "hidden", border: "1px solid var(--line)", background: "rgba(0,0,0,0.25)" }}>
          {!imgReady && !imgFailed && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
              <Loader2 size={22} className="dt-spin" />
            </div>
          )}
          {imgFailed ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "center", justifyContent: "center", minHeight: 180, color: "var(--warning-text, #b45309)", fontSize: 13 }}>
              <WifiOff size={24} />
              <span>{t("desktop.imgFailed", "截图加载失败，点击刷新重试")}</span>
            </div>
          ) : (
            <img
              src={screenshotUrl}
              alt="desktop"
              onClick={interactive ? handlePreviewClick : undefined}
              onLoad={() => { setImgReady(true); setImgFailed(false); }}
              onError={() => { setImgReady(true); setImgFailed(true); }}
              style={{
                display: imgReady ? "block" : "none",
                width: "100%",
                maxHeight: clickThrough ? undefined : 240,
                height: clickThrough ? "auto" : undefined,
                objectFit: clickThrough ? undefined : "contain",
                cursor: interactive ? "crosshair" : "default",
                background: "rgba(0,0,0,0.4)",
              }}
            />
          )}
          {clickMark && (
            <span
              style={{
                position: "absolute",
                left: `${clickMark.x * 100}%`,
                top: `${clickMark.y * 100}%`,
                width: 18, height: 18, marginLeft: -9, marginTop: -9,
                borderRadius: "50%", border: "2px solid #60a5fa",
                background: "rgba(96,165,250,0.25)",
                pointerEvents: "none",
              }}
            />
          )}
          {imgReady && data?.screenshot?.captured_at && (
            <span style={{
              position: "absolute", right: 8, bottom: 8, padding: "2px 8px", borderRadius: 999,
              background: "rgba(0,0,0,0.55)", color: "#e5e7eb", fontSize: 11, backdropFilter: "blur(4px)",
            }}>
              {formatCapturedAt(data.screenshot.captured_at)}
            </span>
          )}
        </div>
      </div>
    );
  };

  return (
    <>
      <style>{`
        @keyframes dt-slide-in { from { transform: translateX(100%); opacity: 0.6; } to { transform: translateX(0); opacity: 1; } }
        @keyframes dt-fade-in { from { opacity: 0; } to { opacity: 1; } }
        @keyframes dt-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
        .dt-spin { animation: dt-spin 0.9s linear infinite; }
        @keyframes dt-spin { to { transform: rotate(360deg); } }
        .dt-live-dot { animation: dt-pulse 1.6s ease-in-out infinite; }
      `}</style>

      {/* 浮动开关（链接式开关） */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          title={t("desktop.toggle", "AI 桌面可视化")}
          aria-label={t("desktop.toggle", "AI 桌面可视化")}
          style={{
            position: "fixed", right: 18, bottom: 18, zIndex: 90,
            display: "flex", alignItems: "center", gap: 8,
            padding: "9px 14px", borderRadius: 999, cursor: "pointer",
            border: "1px solid var(--line)",
            background: "color-mix(in srgb, var(--panel2, #1f2937) 88%, transparent)",
            backdropFilter: "blur(12px)",
            color: "var(--text)", fontSize: 13, fontWeight: 500,
            boxShadow: "0 6px 24px rgba(0,0,0,0.28)",
            transition: "transform 0.15s ease, box-shadow 0.15s ease",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; }}
        >
          <Monitor size={16} style={{ color: "var(--accent, #60a5fa)" }} />
          <span>{t("desktop.toggle", "AI 桌面可视化")}</span>
          <CircleDot size={12} className="dt-live-dot" style={{ color: "#22c55e" }} />
        </button>
      )}

      {/* 遮罩 */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 95,
            background: "rgba(0,0,0,0.35)", backdropFilter: "blur(2px)",
            animation: "dt-fade-in 0.2s ease",
          }}
        />
      )}

      {/* 滑出面板 */}
      {open && (
        <aside
          role="dialog"
          aria-label={t("desktop.title", "AI 桌面")}
          style={{
            position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 96,
            width: "min(400px, 92vw)",
            display: "flex", flexDirection: "column",
            background: "var(--panel2, #161b22)",
            borderLeft: "1px solid var(--line)",
            boxShadow: "-8px 0 32px rgba(0,0,0,0.35)",
            animation: "dt-slide-in 0.22s cubic-bezier(0.2, 0.8, 0.3, 1)",
          }}
        >
          {/* 头部 */}
          <header style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "14px 16px", borderBottom: "1px solid var(--line)",
          }}>
            <Monitor size={18} style={{ color: "var(--accent, #60a5fa)" }} />
            <span style={{ fontWeight: 600, fontSize: 14, color: "var(--text)" }}>
              {t("desktop.title", "AI 桌面可视化")}
            </span>
            {autoRefresh && (
              <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#22c55e" }}>
                <CircleDot size={10} className="dt-live-dot" />
                {t("desktop.live", "实时")}
              </span>
            )}
            <div style={{ flex: 1 }} />
            <button
              onClick={() => void fetchState(true)}
              title={t("desktop.refresh", "刷新")}
              aria-label={t("desktop.refresh", "刷新")}
              style={iconBtnStyle}
            >
              <RefreshCw size={15} className={loading ? "dt-spin" : undefined} />
            </button>
            <button
              onClick={() => setAutoRefresh((v) => !v)}
              title={t("desktop.autoRefresh", "自动刷新")}
              aria-label={t("desktop.autoRefresh", "自动刷新")}
              style={{
                ...iconBtnStyle,
                color: autoRefresh ? "var(--accent, #60a5fa)" : "var(--muted)",
                background: autoRefresh ? "color-mix(in srgb, var(--accent, #60a5fa) 14%, transparent)" : "transparent",
              }}
            >
              <RadioTower size={15} />
            </button>
            <button
              onClick={() => setOpen(false)}
              title={t("common.close", "关闭")}
              aria-label={t("common.close", "关闭")}
              style={iconBtnStyle}
            >
              <X size={16} />
            </button>
          </header>

          {/* 主体 */}
          <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
            {fetchError && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px", borderRadius: 10, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.3)", color: "var(--warning-text, #b45309)", fontSize: 12 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                  <AlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0 }} />
                  <span style={{ overflowWrap: "anywhere" }}>
                    {t("desktop.fetchError", "桌面状态获取失败")}: {fetchError}
                  </span>
                </div>
                {/fetch|network|failed to fetch/i.test(fetchError) && (
                  <span style={{ opacity: 0.85 }}>
                    {t(
                      "desktop.backendDown",
                      "后端服务未启动或不可达，请确认 openkitsune serve 正在运行",
                    )}
                  </span>
                )}
                <button
                  onClick={() => void fetchState(true)}
                  style={{
                    alignSelf: "flex-start",
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "4px 10px", borderRadius: 8, cursor: "pointer",
                    border: "1px solid rgba(245,158,11,0.45)",
                    background: "rgba(245,158,11,0.12)",
                    color: "var(--warning-text, #b45309)", fontSize: 11,
                  }}
                >
                  <RefreshCw size={12} />
                  {t("desktop.retry", "重试")}
                </button>
              </div>
            )}

            {errors.length > 0 && (
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "10px 12px", borderRadius: 10, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", color: "#dc2626", fontSize: 12 }}>
                <AlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0 }} />
                <span style={{ overflowWrap: "anywhere" }}>
                  {errors.slice(0, 3).join("；")}
                </span>
              </div>
            )}

            {/* 打开路径 / 网址（用户打开，AI 通过活动记录感知） */}
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {t("desktop.openTarget", "打开路径 / 网址")}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  value={openTarget}
                  onChange={(e) => setOpenTarget(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void submitOpenTarget();
                    }
                  }}
                  placeholder={t("desktop.openPlaceholder", "C:\\path\\to\\file 或 https://...")}
                  style={{
                    flex: 1, minWidth: 0, padding: "6px 9px", borderRadius: 8,
                    border: "1px solid var(--line)", background: "transparent",
                    color: "var(--text)", fontSize: 12, outline: "none",
                  }}
                />
                <button
                  onClick={() => void submitOpenTarget()}
                  disabled={openBusy || !openTarget.trim()}
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 5,
                    padding: "6px 10px", borderRadius: 8, fontSize: 12,
                    cursor: openBusy || !openTarget.trim() ? "not-allowed" : "pointer",
                    border: "1px solid var(--line)",
                    background: "color-mix(in srgb, var(--accent, #60a5fa) 12%, transparent)",
                    color: "var(--accent, #60a5fa)",
                    opacity: openBusy || !openTarget.trim() ? 0.6 : 1,
                  }}
                >
                  {openBusy ? <Loader2 size={12} className="dt-spin" /> : <ExternalLink size={12} />}
                  {t("desktop.open", "打开")}
                </button>
              </div>
              {openError && (
                <div style={{ fontSize: 11, color: "#dc2626", overflowWrap: "anywhere" }}>
                  {openError}
                </div>
              )}
            </section>

            {/* 截图 */}
            {renderScreenshot()}

            {/* 状态卡片 */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
              <StatCard
                icon={<Maximize2 size={14} />}
                label={t("desktop.screen", "屏幕")}
                value={data?.screen_size?.width && data.screen_size.height
                  ? `${data.screen_size.width}×${data.screen_size.height}`
                  : "—"}
              />
              <StatCard
                icon={<MousePointer size={14} />}
                label={t("desktop.pointer", "指针")}
                value={data?.pointer ? `${data.pointer.x ?? 0}, ${data.pointer.y ?? 0}` : "—"}
              />
              <StatCard
                icon={<AppWindow size={14} />}
                label={t("desktop.windows", "窗口")}
                value={String(visibleWindows.length)}
              />
            </div>

            {/* 活动窗口 */}
            {data?.active_window && (
              <section style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid color-mix(in srgb, var(--accent, #60a5fa) 40%, var(--line))", background: "color-mix(in srgb, var(--accent, #60a5fa) 7%, transparent)" }}>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4, display: "flex", alignItems: "center", gap: 5 }}>
                  <CircleDot size={10} style={{ color: "var(--accent, #60a5fa)" }} />
                  {t("desktop.activeWindow", "活动窗口")}
                </div>
                <div style={{ fontSize: 13, color: "var(--text)", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {data.active_window.title || "—"}
                </div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {[data.active_window.process_name, data.active_window.class_name].filter(Boolean).join(" · ")}
                </div>
              </section>
            )}

            {/* 可见窗口：用户点击置前；AI 通过 desktop_state 感知同一份清单 */}
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {t("desktop.visibleWindows", "可见窗口")}
                <span style={{ opacity: 0.75 }}>
                  {" · "}
                  {t("desktop.clickToActivate", "点击窗口可置前")}
                </span>
              </div>
              {actionError && (
                <div style={{ fontSize: 11, color: "#dc2626", overflowWrap: "anywhere" }}>
                  {t("desktop.actionFailed", "窗口操作失败")}: {actionError}
                </div>
              )}
              {visibleWindows.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
                  {t("desktop.noWindows", "无可见窗口")}
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {visibleWindows.map((win) => {
                    const key = windowKey(win);
                    const focused = Boolean(win.is_focused);
                    const busy = busyKey === key;
                    const open = detailsKey === key;
                    const bbox = win.bbox;
                    const size = bbox && bbox.length === 4 && bbox[2] > bbox[0] && bbox[3] > bbox[1]
                      ? `${bbox[2] - bbox[0]}×${bbox[3] - bbox[1]}`
                      : "";
                    const badges = [
                      win.is_minimized ? "min" : "",
                      win.is_maximized ? "max" : "",
                    ].filter(Boolean).join(",");
                    return (
                      <div key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <div
                          role="button"
                          tabIndex={0}
                          title={t(
                            "desktop.activateHint",
                            "点击窗口将其置前；AI 可通过 desktop_state 实时感知当前窗口",
                          )}
                          onClick={() => void activateWindow(win)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              void activateWindow(win);
                            }
                          }}
                          style={{
                            display: "flex", alignItems: "center", gap: 8,
                            padding: "7px 10px", borderRadius: 10,
                            cursor: busy ? "progress" : "pointer",
                            border: `1px solid ${focused ? "color-mix(in srgb, var(--accent, #60a5fa) 45%, var(--line))" : "var(--line)"}`,
                            background: focused ? "color-mix(in srgb, var(--accent, #60a5fa) 8%, transparent)" : "transparent",
                            opacity: busy ? 0.7 : 1,
                            transition: "border-color 0.15s ease, background 0.15s ease",
                          }}
                          onMouseEnter={(e) => {
                            if (!focused) e.currentTarget.style.borderColor = "color-mix(in srgb, var(--accent, #60a5fa) 35%, var(--line))";
                          }}
                          onMouseLeave={(e) => {
                            if (!focused) e.currentTarget.style.borderColor = "var(--line)";
                          }}
                        >
                          <AppWindow size={13} style={{ flexShrink: 0, color: focused ? "var(--accent, #60a5fa)" : "var(--muted)" }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                              title={win.title}
                              style={{ fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                            >
                              {win.title || "—"}
                            </div>
                            <div style={{ fontSize: 10, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {[win.process_name, size, badges].filter(Boolean).join(" · ")}
                            </div>
                          </div>
                          {busy ? (
                            <Loader2 size={13} className="dt-spin" style={{ flexShrink: 0 }} />
                          ) : (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                void toggleDetails(win);
                              }}
                              title={open ? t("desktop.hideDetails", "收起") : t("desktop.details", "详情")}
                              aria-label={open ? t("desktop.hideDetails", "收起") : t("desktop.details", "详情")}
                              style={{ ...iconBtnStyle, width: 24, height: 24, flexShrink: 0 }}
                            >
                              {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                          )}
                        </div>
                        {open && (
                          <div style={{ marginLeft: 8, padding: "8px 10px", borderRadius: 8, border: "1px solid var(--line)", background: "rgba(0,0,0,0.18)" }}>
                            {detailsLoading ? (
                              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--muted)" }}>
                                <Loader2 size={12} className="dt-spin" />
                                {t("desktop.detailsLoading", "读取元素树...")}
                              </div>
                            ) : detailsError ? (
                              <div style={{ fontSize: 11, color: "#dc2626", overflowWrap: "anywhere" }}>
                                {detailsError}
                              </div>
                            ) : (
                              <pre style={{ margin: 0, maxHeight: 220, overflow: "auto", fontSize: 10, lineHeight: 1.45, color: "var(--muted)", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
                                {detailsText || "—"}
                              </pre>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            {/* 最近活动：用户打开/点击/聚焦记录，AI 通过 desktop_state 读取 */}
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {t("desktop.activity", "最近活动")}
              </div>
              {activity.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--muted)", padding: "4px 0" }}>—</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {activity.slice(0, 8).map((item, i) => (
                    <div
                      key={`${item.ts || ""}-${i}`}
                      style={{
                        display: "flex", gap: 8, alignItems: "baseline",
                        padding: "5px 8px", borderRadius: 8,
                        border: "1px solid var(--line)", fontSize: 11,
                      }}
                    >
                      <span style={{ color: "var(--accent, #60a5fa)", flexShrink: 0 }}>
                        {item.kind || "activity"}
                      </span>
                      <span
                        title={item.location || item.target || item.window}
                        style={{
                          flex: 1, minWidth: 0, color: "var(--text)",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                        }}
                      >
                        {item.target || item.window || "—"}
                      </span>
                      <span style={{ color: "var(--muted)", flexShrink: 0 }}>
                        {formatCapturedAt(item.ts)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* 能力探测 */}
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {t("desktop.capabilities", "能力探测")}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {Object.keys(CAPABILITY_LABELS).map((key) => {
                  const ok = capabilities[key] === "ok";
                  return (
                    <span
                      key={key}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        padding: "3px 10px", borderRadius: 999, fontSize: 11,
                        border: "1px solid var(--line)",
                        color: ok ? "#16a34a" : "var(--muted)",
                        background: ok ? "rgba(22,163,74,0.08)" : "transparent",
                      }}
                    >
                      <CircleDot size={8} style={{ color: ok ? "#22c55e" : "var(--muted)" }} />
                      {CAPABILITY_LABELS[key]}
                    </span>
                  );
                })}
              </div>
            </section>
          </div>

          {/* 底部提示 */}
          <footer style={{ padding: "10px 16px", borderTop: "1px solid var(--line)", fontSize: 11, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
            <CircleDot size={9} style={{ color: "var(--accent, #60a5fa)" }} />
            {t("desktop.hint", "坐标操作前先观察 · 操作后用新截图验证")}
          </footer>
        </aside>
      )}
    </>
  );
}

const iconBtnStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", justifyContent: "center",
  width: 28, height: 28, borderRadius: 8, cursor: "pointer",
  border: "1px solid transparent", background: "transparent",
  color: "var(--muted)",
};

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, padding: "9px 10px", borderRadius: 12, border: "1px solid var(--line)", background: "transparent" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5, color: "var(--muted)", fontSize: 11 }}>
        {icon}
        {label}
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {value}
      </div>
    </div>
  );
}
