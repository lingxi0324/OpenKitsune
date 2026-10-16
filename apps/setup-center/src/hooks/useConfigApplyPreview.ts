import { useEffect, useRef, useState } from "react";
import type { EnvMap } from "../types";
import { safeFetch } from "../providers";

export type ConfigApplyMode =
  | "immediate"
  | "next_task"
  | "component_reload"
  | "process_restart";

type CachedApplyMode = ConfigApplyMode | "unknown";

export type ConfigApplyCounts = Record<ConfigApplyMode, number>;

type UseConfigApplyPreviewOptions = {
  keys: string[];
  draft: EnvMap;
  baseline: EnvMap;
  enabled: boolean;
  apiBase: string;
  onEffectiveValues?: (values: EnvMap) => void;
};

const EMPTY_COUNTS: ConfigApplyCounts = {
  immediate: 0,
  next_task: 0,
  component_reload: 0,
  process_restart: 0,
};

function normalizedEnvValue(value: string | undefined): string {
  return (value ?? "").trim();
}

export function useConfigApplyPreview({
  keys,
  draft,
  baseline,
  enabled,
  apiBase,
  onEffectiveValues,
}: UseConfigApplyPreviewOptions) {
  const modeCache = useRef(new Map<string, CachedApplyMode>());
  const effectiveValueCache = useRef(new Map<string, string>());
  const attemptedKeys = useRef(new Set<string>());
  const mounted = useRef(true);
  const onEffectiveValuesRef = useRef(onEffectiveValues);
  onEffectiveValuesRef.current = onEffectiveValues;
  const [, refreshCacheView] = useState(0);

  const uniqueKeys = Array.from(new Set(keys));
  const keySignature = uniqueKeys.join("\u0000");
  const dirtyKeys = uniqueKeys.filter((key) => {
    const savedValue = normalizedEnvValue(baseline[key]);
    const effectiveValue = effectiveValueCache.current.get(key);
    const comparisonValue = savedValue || effectiveValue || "";
    return normalizedEnvValue(draft[key]) !== normalizedEnvValue(comparisonValue);
  });

  useEffect(
    () => () => {
      mounted.current = false;
    },
    [],
  );

  useEffect(() => {
    if (!enabled || !keySignature) return;
    const currentKeys = keySignature.split("\u0000");
    const missing = currentKeys.filter((key) => !attemptedKeys.current.has(key));
    if (missing.length === 0) return;

    for (const key of missing) attemptedKeys.current.add(key);
    void safeFetch(`${apiBase}/api/config/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys: missing }),
    })
      .then(async (response) => {
        const data = await response.json();
        const modes = data.apply_modes || {};
        const effectiveValues = data.effective_values || {};
        for (const key of missing) {
          modeCache.current.set(key, modes[key] || "unknown");
          if (Object.prototype.hasOwnProperty.call(effectiveValues, key)) {
            effectiveValueCache.current.set(key, String(effectiveValues[key]));
          }
        }
        onEffectiveValuesRef.current?.(effectiveValues);
      })
      .catch(() => {
        for (const key of missing) modeCache.current.set(key, "unknown");
      })
      .finally(() => {
        if (mounted.current) refreshCacheView((version) => version + 1);
      });
  }, [apiBase, enabled, keySignature]);

  const counts = { ...EMPTY_COUNTS };
  let unknownCount = 0;
  let pendingCount = 0;
  for (const key of dirtyKeys) {
    const mode = modeCache.current.get(key);
    if (!mode) {
      if (enabled) pendingCount += 1;
      else unknownCount += 1;
    } else if (mode === "unknown") unknownCount += 1;
    else counts[mode] += 1;
  }

  return { dirtyKeys, counts, unknownCount, pendingCount };
}
