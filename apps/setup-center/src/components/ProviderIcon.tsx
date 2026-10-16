import { Boxes } from "lucide-react";
import { cn } from "@/lib/utils";

// Vite will bundle referenced SVGs only (tree-shakable) thanks to `?raw`.
// Color variants bake in brand colors; mono variants use fill="currentColor"
// so they naturally follow the current text color in both light and dark mode.
import anthropicSvg from "@lobehub/icons-static-svg/icons/anthropic.svg?raw";
import openaiSvg from "@lobehub/icons-static-svg/icons/openai.svg?raw";
import qwenColorSvg from "@lobehub/icons-static-svg/icons/qwen-color.svg?raw";
import kimiColorSvg from "@lobehub/icons-static-svg/icons/kimi-color.svg?raw";
import minimaxColorSvg from "@lobehub/icons-static-svg/icons/minimax-color.svg?raw";
import deepseekColorSvg from "@lobehub/icons-static-svg/icons/deepseek-color.svg?raw";
import openrouterSvg from "@lobehub/icons-static-svg/icons/openrouter.svg?raw";
import siliconCloudColorSvg from "@lobehub/icons-static-svg/icons/siliconcloud-color.svg?raw";
import volcengineColorSvg from "@lobehub/icons-static-svg/icons/volcengine-color.svg?raw";
import zhipuColorSvg from "@lobehub/icons-static-svg/icons/zhipu-color.svg?raw";
import baiducloudColorSvg from "@lobehub/icons-static-svg/icons/baiducloud-color.svg?raw";
import hunyuanColorSvg from "@lobehub/icons-static-svg/icons/hunyuan-color.svg?raw";
import geminiColorSvg from "@lobehub/icons-static-svg/icons/gemini-color.svg?raw";
import grokSvg from "@lobehub/icons-static-svg/icons/grok.svg?raw";
import mistralColorSvg from "@lobehub/icons-static-svg/icons/mistral-color.svg?raw";
import nvidiaColorSvg from "@lobehub/icons-static-svg/icons/nvidia-color.svg?raw";
import groqSvg from "@lobehub/icons-static-svg/icons/groq.svg?raw";
import togetherColorSvg from "@lobehub/icons-static-svg/icons/together-color.svg?raw";
import fireworksColorSvg from "@lobehub/icons-static-svg/icons/fireworks-color.svg?raw";
import cohereColorSvg from "@lobehub/icons-static-svg/icons/cohere-color.svg?raw";
import longcatColorSvg from "@lobehub/icons-static-svg/icons/longcat-color.svg?raw";
import sparkColorSvg from "@lobehub/icons-static-svg/icons/spark-color.svg?raw";
import ollamaSvg from "@lobehub/icons-static-svg/icons/ollama.svg?raw";
import lmstudioSvg from "@lobehub/icons-static-svg/icons/lmstudio.svg?raw";

// Map provider slug (from providers.json / EndpointDraft.provider) to inline SVG markup.
// Color variants are preferred; monochrome fallbacks inherit current text color.
const SLUG_SVG_MAP: Record<string, string | undefined> = {
  anthropic: anthropicSvg,
  openai: openaiSvg,
  dashscope: qwenColorSvg,
  "dashscope-intl": qwenColorSvg,
  "kimi-cn": kimiColorSvg,
  "kimi-int": kimiColorSvg,
  "minimax-cn": minimaxColorSvg,
  "minimax-int": minimaxColorSvg,
  deepseek: deepseekColorSvg,
  openrouter: openrouterSvg,
  siliconflow: siliconCloudColorSvg,
  "siliconflow-intl": siliconCloudColorSvg,
  volcengine: volcengineColorSvg,
  "zhipu-cn": zhipuColorSvg,
  "zhipu-int": zhipuColorSvg,
  qianfan: baiducloudColorSvg,
  hunyuan: hunyuanColorSvg,
  gemini: geminiColorSvg,
  xai: grokSvg,
  mistral: mistralColorSvg,
  "nvidia-nim": nvidiaColorSvg,
  groq: groqSvg,
  together: togetherColorSvg,
  fireworks: fireworksColorSvg,
  cohere: cohereColorSvg,
  longcat: longcatColorSvg,
  xfyun: sparkColorSvg,
  ollama: ollamaSvg,
  lmstudio: lmstudioSvg,
};

export interface ProviderIconProps {
  slug?: string | null;
  size?: number;
  className?: string;
  title?: string;
}

/**
 * Renders a brand logo for an LLM provider based on its `slug`
 * (e.g. `openai`, `dashscope`, `zhipu-cn`).
 *
 * - Looks up the slug in `SLUG_SVG_MAP`; unknown slugs fall back to a
 *   generic lucide `Boxes` icon so the UI never breaks.
 * - Mono icons use `fill="currentColor"`, so they inherit text color
 *   automatically; wrapping span sets `font-size` so the SVG's `1em`
 *   dimensions resolve to the requested pixel size.
 */
export function ProviderIcon({ slug, size = 16, className, title }: ProviderIconProps) {
  const key = (slug || "").trim().toLowerCase();
  const svg = key ? SLUG_SVG_MAP[key] : undefined;

  if (!svg) {
    return (
      <Boxes
        size={size}
        strokeWidth={1.5}
        className={cn("shrink-0 opacity-60", className)}
        aria-label={title ?? key ?? "provider"}
      />
    );
  }

  return (
    <span
      role="img"
      aria-label={title ?? key}
      className={cn("inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size, fontSize: size, lineHeight: 1 }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

/** Returns true if we have a dedicated icon for the given provider slug. */
export function hasProviderIcon(slug?: string | null): boolean {
  const key = (slug || "").trim().toLowerCase();
  return !!key && !!SLUG_SVG_MAP[key];
}
