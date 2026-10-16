import { describe, expect, it } from "vitest";

import i18n from "../index";
import en from "../en.json";

const SECURITY_ENGLISH_KEYS = [
  "security.permissionMode",
  "security.modeTrustTitle",
  "security.modeProtectTitle",
  "security.modeStrictTitle",
  "security.modeOffTitle",
  "security.modeCustomTitle",
  "security.refreshAll",
  "security.showAdvanced",
  "common.add",
  "security.dryRun",
  "security.modeTrustCardDesc",
  "security.trustModeAdvancedHint",
  "security.confirmModePathHint",
  "security.auditToFileDesc",
  "security.imOwnerDesc",
  "security.dryRunDesc",
  "security.matrixDesc",
  "security.matrixDataSource",
  "security.sessionRole.coordinator",
  "security.matrixMode.accept_edits",
  "security.tool.delegate_to_agent",
  "security.approvalClass.control_plane",
  "security.reasonCode.safety_immune",
] as const;

function collectStrings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (value && typeof value === "object") {
    return Object.values(value).flatMap(collectStrings);
  }
  return [];
}

describe("security page translations", () => {
  it("uses the expected English labels for the reported controls", () => {
    const t = i18n.getFixedT("en");

    expect([
      t("security.permissionMode"),
      t("security.modeTrustTitle"),
      t("security.modeProtectTitle"),
      t("security.modeStrictTitle"),
      t("security.modeOffTitle"),
      t("security.modeCustomTitle"),
      t("security.refreshAll"),
      t("security.showAdvanced"),
      t("common.add"),
      t("security.dryRun"),
    ]).toEqual([
      "Security Profile",
      "Trust",
      "Protect",
      "Strict",
      "Off",
      "Custom",
      "Refresh All",
      "Show Advanced Settings",
      "Add",
      "Policy Preview",
    ]);
  });

  it("provides English text for controls and explanatory copy", () => {
    const t = i18n.getFixedT("en");

    for (const key of SECURITY_ENGLISH_KEYS) {
      const value = t(key);
      expect(value).not.toBe(key);
      expect(value).not.toMatch(/[\u3400-\u9fff]/u);
    }
  });

  it("contains no Chinese text anywhere in the English security resources", () => {
    for (const value of collectStrings(en.security)) {
      expect(value).not.toMatch(/[\u3400-\u9fff]/u);
    }
  });
});
