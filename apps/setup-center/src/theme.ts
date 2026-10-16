export type Theme =
  | "light"
  | "dark"
  | "system"
  | "daltonized-light"
  | "daltonized-dark"
  | "high-contrast"
  | "classic-ink"
  | "classic-bamboo"
  | "classic-moon"
  | "classic-porcelain"
  | "classic-gold"
  | "classic-cinnabar"
  | "classic-purple"
  | "classic-night"
  | "classic-vermilion";

export type ThemeGroup = "standard" | "accessibility" | "classic";

/** Classical (dark) themes that reuse the dark code-highlight palette. */
export const CLASSIC_DARK_THEMES: Theme[] = [
  "classic-gold",
  "classic-cinnabar",
  "classic-purple",
  "classic-night",
  "classic-vermilion",
];

/** Classical (light) themes that reuse the light code-highlight palette. */
export const CLASSIC_LIGHT_THEMES: Theme[] = [
  "classic-ink",
  "classic-bamboo",
  "classic-moon",
  "classic-porcelain",
];

export const isClassicTheme = (t: Theme): boolean =>
  CLASSIC_DARK_THEMES.includes(t) || CLASSIC_LIGHT_THEMES.includes(t);

const RESOLVED_THEMES: Record<string, string> = {
  light: "light",
  dark: "dark",
  "daltonized-light": "daltonized-light",
  "daltonized-dark": "daltonized-dark",
  "high-contrast": "high-contrast",
  "classic-ink": "classic-ink",
  "classic-bamboo": "classic-bamboo",
  "classic-moon": "classic-moon",
  "classic-porcelain": "classic-porcelain",
  "classic-gold": "classic-gold",
  "classic-cinnabar": "classic-cinnabar",
  "classic-purple": "classic-purple",
  "classic-night": "classic-night",
  "classic-vermilion": "classic-vermilion",
};

function resolveTheme(theme: Theme): string {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return RESOLVED_THEMES[theme] || theme;
}

/** Tauri native themes only support light/dark; map extended themes to the nearest. */
function toNativeTheme(theme: Theme): "light" | "dark" | null {
  if (theme === "system") return null;
  if (
    theme === "daltonized-light" ||
    theme === "light" ||
    CLASSIC_LIGHT_THEMES.includes(theme)
  ) {
    return "light";
  }
  return "dark";
}

export function initTheme() {
  const pref = (localStorage.getItem("openkitsune-theme-pref") as Theme) || "system";
  // 无效主题值兜底：旧版本残留在 localStorage 的主题名若已不存在（如主题被
  // 移除/改名），会令 data-theme 落空导致界面回退默认黑白。检出即清理回退。
  if (!isValidTheme(pref)) {
    localStorage.removeItem("openkitsune-theme-pref");
    applyTheme("system");
  } else {
    applyTheme(pref);
  }

  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const listener = (e: MediaQueryListEvent) => {
    const currentPref = localStorage.getItem("openkitsune-theme-pref") as Theme | null;
    if (!currentPref || currentPref === "system") {
      document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
    }
  };

  if (mediaQuery.addEventListener) {
    mediaQuery.addEventListener("change", listener);
  } else if (mediaQuery.addListener) {
    mediaQuery.addListener(listener);
  }
}

/** 判断主题值是否在已知主题列表中（防御 localStorage 脏值导致界面黑白）。 */
export function isValidTheme(theme: string | null | undefined): theme is Theme {
  if (!theme) return false;
  return theme === "system" || theme in RESOLVED_THEMES;
}

export function applyTheme(theme: Theme) {
  // 兜底：未知主题一律回退 system，避免 data-theme 落空呈现黑白界面。
  if (!isValidTheme(theme)) {
    theme = "system";
    try {
      localStorage.removeItem("openkitsune-theme-pref");
    } catch {
      /* ignore */
    }
  }
  const resolved = resolveTheme(theme);
  document.documentElement.setAttribute("data-theme", resolved);

  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
      const win = getCurrentWindow();
      win.setTheme(toNativeTheme(theme));
    }).catch(() => {});
  }
}

export const THEME_CHANGE_EVENT = "openkitsune-theme-change";

let _previewBackup: Theme | null = null;

export function setThemePref(theme: Theme) {
  _previewBackup = null;
  localStorage.setItem("openkitsune-theme-pref", theme);
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}

export function getThemePref(): Theme {
  const pref = localStorage.getItem("openkitsune-theme-pref");
  if (!isValidTheme(pref)) {
    try {
      localStorage.removeItem("openkitsune-theme-pref");
    } catch {
      /* ignore */
    }
    return "system";
  }
  return pref;
}

/** Apply a theme temporarily for live preview without persisting. */
export function previewTheme(theme: Theme) {
  if (!_previewBackup) {
    _previewBackup = getThemePref();
  }
  applyTheme(theme);
}

/** Revert to the persisted theme (cancel preview). */
export function cancelPreview() {
  if (_previewBackup) {
    applyTheme(_previewBackup);
    _previewBackup = null;
  }
}

export const THEME_OPTIONS: { value: Theme; label: string; group: ThemeGroup }[] = [
  { value: "system", label: "themeSystem", group: "standard" },
  { value: "light", label: "themeLight", group: "standard" },
  { value: "dark", label: "themeDark", group: "standard" },
  { value: "daltonized-light", label: "themeDaltonizedLight", group: "accessibility" },
  { value: "daltonized-dark", label: "themeDaltonizedDark", group: "accessibility" },
  { value: "high-contrast", label: "themeHighContrast", group: "accessibility" },
  { value: "classic-ink", label: "themeClassicInk", group: "classic" },
  { value: "classic-bamboo", label: "themeClassicBamboo", group: "classic" },
  { value: "classic-moon", label: "themeClassicMoon", group: "classic" },
  { value: "classic-porcelain", label: "themeClassicPorcelain", group: "classic" },
  { value: "classic-gold", label: "themeClassicGold", group: "classic" },
  { value: "classic-cinnabar", label: "themeClassicCinnabar", group: "classic" },
  { value: "classic-purple", label: "themeClassicPurple", group: "classic" },
  { value: "classic-night", label: "themeClassicNight", group: "classic" },
  { value: "classic-vermilion", label: "themeClassicVermilion", group: "classic" },
];

export const THEME_GROUP_OPTIONS: { value: ThemeGroup; label: string }[] = [
  { value: "standard", label: "themeGroupStandard" },
  { value: "accessibility", label: "themeGroupAccessibility" },
  { value: "classic", label: "themeGroupClassic" },
];

/** Representative background gradient + accent ring for each theme's dropdown swatch. */
export const THEME_SWATCHES: Record<Theme, { from: string; to: string; ring: string }> = {
  system: { from: "#ffffff", to: "#111111", ring: "#94a3b8" },
  light: { from: "#f4f5f7", to: "#e2e8f0", ring: "#cbd5e1" },
  dark: { from: "#09090b", to: "#18181b", ring: "#52525b" },
  "daltonized-light": { from: "#f4f5f7", to: "#dbeafe", ring: "#93c5fd" },
  "daltonized-dark": { from: "#09090b", to: "#312e81", ring: "#818cf8" },
  "high-contrast": { from: "#000000", to: "#1f1f1f", ring: "#ffffff" },
  "classic-ink": { from: "#f8f4ea", to: "#e9e2cf", ring: "#4a5d4f" },
  "classic-bamboo": { from: "#f2f6e9", to: "#dde8cc", ring: "#2f6b3a" },
  "classic-moon": { from: "#f2f4f9", to: "#dbe2ee", ring: "#3a5a8c" },
  "classic-porcelain": { from: "#fbfdfe", to: "#e3eaf2", ring: "#26418f" },
  "classic-gold": { from: "#1d1813", to: "#0f0c09", ring: "#d4af37" },
  "classic-cinnabar": { from: "#341010", to: "#1f0a0a", ring: "#ec7d5c" },
  "classic-purple": { from: "#211832", to: "#140e1d", ring: "#bda4ea" },
  "classic-night": { from: "#11202e", to: "#081019", ring: "#6fb3d9" },
  "classic-vermilion": { from: "#2a150d", to: "#150a06", ring: "#e8a04c" },
};
