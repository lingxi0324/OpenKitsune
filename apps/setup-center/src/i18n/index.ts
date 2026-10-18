import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import zh from "./zh.json";
import en from "./en.json";
import hi from "./hi.json";
import es from "./es.json";
import ar from "./ar.json";
import fr from "./fr.json";
import bn from "./bn.json";
import pt from "./pt.json";
import ru from "./ru.json";

const LS_KEY = "openkitsune_lang";

/**
 * UI languages offered in the top bar language menu: the nine most spoken
 * languages worldwide (Ethnologue 2025, by total speakers).
 *
 * zh / en ship full translation files. The other seven languages ship the
 * core framework layer (topbar + sidebar); deeper page sections currently fall
 * back to English (then Chinese) until their translation JSON is extended —
 * the plumbing (menu, persistence, system detection, fallback) is in place
 * for all nine. Regenerate with scripts/generate_core_i18n.py.
 */
export type AppLang = "zh" | "en" | "hi" | "es" | "ar" | "fr" | "bn" | "pt" | "ru";
export type AppLanguage = "auto" | AppLang;

export const APP_LANGUAGES: AppLang[] = ["zh", "en", "hi", "es", "ar", "fr", "bn", "pt", "ru"];

/** Native (endonym) display names, ordered to match APP_LANGUAGES. */
export const LANGUAGE_NATIVE_NAMES: Record<AppLang, string> = {
  zh: "中文",
  en: "English",
  hi: "हिन्दी",
  es: "Español",
  ar: "العربية",
  fr: "Français",
  bn: "বাংলা",
  pt: "Português",
  ru: "Русский",
};

function getStoredLang(): string | null {
  try { return localStorage.getItem(LS_KEY); } catch { return null; }
}

/** Map the browser/system locale to the closest supported UI language. */
function detectSystemLang(): AppLang {
  const nav = navigator.language || "";
  const primary = nav.split("-")[0].toLowerCase();
  switch (primary) {
    case "zh": return "zh";
    case "hi": return "hi";
    case "es": return "es";
    case "ar": return "ar";
    case "fr": return "fr";
    case "bn": return "bn";
    case "pt": return "pt";
    case "ru": return "ru";
    default: return "en";
  }
}

const stored = getStoredLang();
const initialLng = stored === "auto" || !stored ? detectSystemLang() : stored;

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      zh: { translation: zh },
      en: { translation: en },
      hi: { translation: hi },
      es: { translation: es },
      ar: { translation: ar },
      fr: { translation: fr },
      bn: { translation: bn },
      pt: { translation: pt },
      ru: { translation: ru },
    },
    lng: initialLng,
    fallbackLng: ["en", "zh"],
    detection: {
      order: ["navigator"],
      caches: [],
    },
    interpolation: {
      escapeValue: false,
    },
  });

/**
 * Switch language with persistence.
 * "auto" = follow system; any AppLang = explicit override.
 */
export function setLanguage(lang: AppLanguage): void {
  try { localStorage.setItem(LS_KEY, lang); } catch {}
  const resolved = lang === "auto" ? detectSystemLang() : lang;
  i18n.changeLanguage(resolved);
}

export function getLanguagePref(): AppLanguage {
  const v = getStoredLang();
  if (v === "zh" || v === "en" || v === "hi" || v === "es" || v === "ar" || v === "fr" || v === "bn" || v === "pt" || v === "ru") return v;
  return "auto";
}

export default i18n;
