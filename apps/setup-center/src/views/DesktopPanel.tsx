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
} from "lucide-react";
import { getAccessToken } from "../platform/auth";
import { safeFetch } from "../providers";

const DEFAULT_API_BASE = "http://127.0.0.1:18900";
const AUTO_REFRESH_MS = 3000;
const PANEL_CONTEXT_ID = "desktop-panel";

interface DesktopWindowInfo {
  title?: string;
  class_name?: string;
  process_name?: string;
  is_visible?: boolean;
  is_focused?: boolean;
}

interface DesktopStateData {
  ok: boolean;
  context_id?: string;
  screen_size?: { width?: number; height?: number };
  pointer?: { x?: number; y?: number };
  active_window?: DesktopWindowInfo | null;
  windows?: DesktopWindowInfo[];
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
  const abortRef = useRef<AbortController | null>(null);

  const fetchState = useCallback(
    async (withScreenshot: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setFetchError("");
      try {
        const url = `${apiBaseUrl}/api/desktop/state?include_screenshot=${withScreenshot ? 1 : 0}&context_id=${PANEL_CONTEXT_ID}`;
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
    return (
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
            onLoad={() => { setImgReady(true); setImgFailed(false); }}
            onError={() => { setImgReady(true); setImgFailed(true); }}
            style={{
              display: imgReady ? "block" : "none",
              width: "100%",
              maxHeight: 240,
              objectFit: "contain",
              background: "rgba(0,0,0,0.4)",
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
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "10px 12px", borderRadius: 10, background: "rgba(245,158,11,0.10)", border: "1px solid rgba(245,158,11,0.3)", color: "var(--warning-text, #b45309)", fontSize: 12 }}>
                <AlertTriangle size={14} style={{ marginTop: 1, flexShrink: 0 }} />
                <span style={{ overflowWrap: "anywhere" }}>
                  {t("desktop.fetchError", "桌面状态获取失败")}: {fetchError}
                </span>
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

            {/* 可见窗口 */}
            <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>
                {t("desktop.visibleWindows", "可见窗口")}
              </div>
              {visibleWindows.length === 0 ? (
                <div style={{ fontSize: 12, color: "var(--muted)", padding: "8px 0" }}>
                  {t("desktop.noWindows", "无可见窗口")}
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {visibleWindows.map((win, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex", alignItems: "center", gap: 8,
                        padding: "7px 10px", borderRadius: 10,
                        border: `1px solid ${win.is_focused ? "color-mix(in srgb, var(--accent, #60a5fa) 45%, var(--line))" : "var(--line)"}`,
                        background: win.is_focused ? "color-mix(in srgb, var(--accent, #60a5fa) 8%, transparent)" : "transparent",
                      }}
                    >
                      <AppWindow size={13} style={{ flexShrink: 0, color: win.is_focused ? "var(--accent, #60a5fa)" : "var(--muted)" }} />
                      <span style={{ flex: 1, fontSize: 12, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {win.title || "—"}
                      </span>
                      {win.process_name && (
                        <span style={{ fontSize: 10, color: "var(--muted)", flexShrink: 0 }}>
                          {win.process_name}
                        </span>
                      )}
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
