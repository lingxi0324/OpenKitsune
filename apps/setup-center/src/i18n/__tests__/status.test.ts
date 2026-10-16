import { describe, expect, it } from "vitest";

import i18n from "../index";

const STATUS_ENGLISH_KEYS = [
  "status.environmentHealthy",
  "status.linkDiag.refresh",
  "status.linkDiag.clear",
  "status.skillConflicts.refresh",
  "status.viewDetails",
  "status.linkDiag.title",
  "status.skillConflicts.title",
  "status.linkDiag.refreshed",
  "status.linkDiag.clearedHint",
  "status.skillConflicts.refreshedEmpty",
  "status.skillConflicts.cleared",
  "status.skillConflicts.origin.remote",
] as const;

describe("status page translations", () => {
  it("provides English text for status diagnostics and actions", () => {
    const t = i18n.getFixedT("en");

    for (const key of STATUS_ENGLISH_KEYS) {
      const value = t(key);
      expect(value).not.toBe(key);
      expect(value).not.toMatch(/[\u3400-\u9fff]/u);
    }
  });

  it("uses the expected English labels for the reported untranslated controls", () => {
    const t = i18n.getFixedT("en");

    expect([
      t("status.environmentHealthy"),
      t("status.linkDiag.refresh"),
      t("status.linkDiag.clear"),
      t("status.skillConflicts.refresh"),
      t("status.viewDetails"),
      t("status.linkDiag.title"),
      t("status.skillConflicts.title"),
    ]).toEqual([
      "Environment healthy",
      "Refresh record",
      "Clear runtime caches",
      "Refresh Status",
      "View Details",
      "Link Read Diagnostics",
      "Skill source records",
    ]);
  });
});
