import { memo, useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { IconUser, IconUpload, IconRefresh } from "../../../icons";

/**
 * Chat avatars for the conversation view.
 *
 * - AI avatar defaults to the nine-tailed fox mark used as the browser/tab
 *   icon (`/web/logo.png`) and is intentionally not user-editable.
 * - The user avatar can be uploaded from a local image; the resized image is
 *   persisted as a data URL in localStorage so it survives reloads and session
 *   restarts (same pattern as `openkitsune-theme-pref` / `openkitsune_lang`).
 */

/** Default AI avatar — the nine-tailed fox mark used as the browser/tab icon. */
export const AI_AVATAR_URL = "/web/logo.png";

const USER_AVATAR_KEY = "openkitsune_user_avatar";
/** Longest edge (px) of the stored user avatar. */
const AVATAR_MAX_EDGE = 256;
/** Keep the stored data URL comfortably inside the localStorage quota. */
const AVATAR_MAX_DATA_URL = 512_000;

export function getUserAvatarUrl(): string | null {
  try {
    const v = localStorage.getItem(USER_AVATAR_KEY);
    return v && v.length > 0 ? v : null;
  } catch {
    return null;
  }
}

export function setUserAvatarUrl(dataUrl: string | null): void {
  try {
    if (dataUrl) localStorage.setItem(USER_AVATAR_KEY, dataUrl);
    else localStorage.removeItem(USER_AVATAR_KEY);
  } catch {
    throw new Error("storage-quota");
  }
}

function readAsImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("decode-failed")); };
    img.src = url;
  });
}

async function fileToResizedDataUrl(file: File): Promise<{ png: string; jpeg: string }> {
  const img = await readAsImage(file);
  const scale = Math.min(1, AVATAR_MAX_EDGE / Math.max(img.naturalWidth, img.naturalHeight));
  const w = Math.max(1, Math.round(img.naturalWidth * scale));
  const h = Math.max(1, Math.round(img.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas-unavailable");
  ctx.drawImage(img, 0, 0, w, h);
  const png = canvas.toDataURL("image/png");
  const jpeg = canvas.toDataURL("image/jpeg", 0.82);
  return { png, jpeg };
}

export const ChatAvatar = memo(function ChatAvatar({
  variant,
  size = 32,
  allowUpload = true,
}: {
  variant: "ai" | "user";
  size?: number;
  /** Only the user avatar is uploadable; the AI mark is fixed. */
  allowUpload?: boolean;
}) {
  const { t } = useTranslation();
  const isUser = variant === "user";
  const [userAvatar, setUserAvatar] = useState<string | null>(() => getUserAvatarUrl());
  const [menuOpen, setMenuOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Close the upload menu on outside click / Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const persist = useCallback((dataUrl: string) => {
    try {
      setUserAvatarUrl(dataUrl);
      return true;
    } catch {
      return false;
    }
  }, []);

  const handlePick = useCallback((file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error(t("chat.avatarInvalidType", "请选择图片文件"));
      return;
    }
    setUploading(true);
    fileToResizedDataUrl(file)
      .then(({ png, jpeg }) => {
        let stored = png;
        if (stored.length > AVATAR_MAX_DATA_URL || !persist(png)) {
          // PNG too large / quota rejected — fall back to the smaller JPEG.
          stored = jpeg;
          if (stored.length > AVATAR_MAX_DATA_URL || !persist(jpeg)) {
            throw new Error("storage-quota");
          }
        }
        setUserAvatar(getUserAvatarUrl());
        toast.success(t("chat.avatarUploaded", "头像已更新"));
      })
      .catch(() => {
        toast.error(t("chat.avatarUploadFailed", "头像上传失败，请换一张图片重试"));
      })
      .finally(() => {
        setUploading(false);
        setMenuOpen(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      });
  }, [persist, t]);

  const handleReset = useCallback(() => {
    try {
      setUserAvatarUrl(null);
    } catch { /* ignore */ }
    setUserAvatar(null);
    setMenuOpen(false);
    toast.success(t("chat.avatarRestored", "已恢复默认头像"));
  }, [t]);

  const circleBase: CSSProperties = {
    width: size,
    height: size,
    borderRadius: "50%",
    objectFit: "cover",
    border: "1px solid var(--line)",
    background: "var(--bg1)",
    flexShrink: 0,
    display: "block",
  };

  const menuItemBase: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    width: "100%",
    padding: "7px 10px",
    borderRadius: 8,
    border: "none",
    background: "transparent",
    color: "var(--text)",
    fontSize: 13,
    cursor: "pointer",
    textAlign: "left",
  };

  if (!isUser) {
    return (
      <img
        src={AI_AVATAR_URL}
        alt={t("chat.aiAvatarAlt", "AI 头像")}
        width={size}
        height={size}
        style={circleBase}
      />
    );
  }

  const hasCustom = Boolean(userAvatar);

  return (
    <div ref={rootRef} style={{ position: "relative", flexShrink: 0, lineHeight: 0 }}>
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        title={t("chat.avatarClickHint", "点击设置头像")}
        aria-label={t("chat.userAvatarAlt", "用户头像")}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        style={{
          ...circleBase,
          padding: 0,
          cursor: "pointer",
          overflow: "hidden",
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
        }}
      >
        {hasCustom ? (
          <img src={userAvatar!} alt="" width={size} height={size} style={{ width: size, height: size, objectFit: "cover", display: "block" }} />
        ) : (
          <IconUser size={Math.round(size * 0.55)} style={{ color: "var(--text-muted)" }} />
        )}
        {uploading && (
          <span
            style={{
              position: "absolute",
              inset: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "rgba(0,0,0,0.4)",
              color: "#fff",
              fontSize: 10,
              fontWeight: 600,
            }}
          >
            …
          </span>
        )}
      </button>

      {menuOpen && (
        <div
          role="menu"
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 6px)",
            zIndex: 40,
            minWidth: 176,
            padding: 4,
            borderRadius: 12,
            background: "var(--panel2)",
            border: "1px solid var(--line)",
            boxShadow: "var(--shadow)",
          }}
        >
          <button
            type="button"
            role="menuitem"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
            style={{ ...menuItemBase, opacity: uploading ? 0.6 : 1 }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-bg, rgba(128,128,128,0.12))"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          >
            <IconUpload size={14} />
            {t("chat.avatarUpload", "上传头像")}
          </button>
          {hasCustom && (
            <button
              type="button"
              role="menuitem"
              onClick={handleReset}
              style={menuItemBase}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-bg, rgba(128,128,128,0.12))"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              <IconRefresh size={14} />
              {t("chat.avatarRestoreDefault", "恢复默认头像")}
            </button>
          )}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(e) => handlePick(e.target.files?.[0])}
      />
    </div>
  );
});
