import { describe, expect, it } from "vitest";

import i18n from "../index";

describe("onboarding translations", () => {
  it("provides English labels for every step indicator", () => {
    const t = i18n.getFixedT("en");

    expect([
      t("onboarding.step.welcome"),
      t("onboarding.step.agreement"),
      t("onboarding.step.llm"),
      t("onboarding.step.im"),
      t("onboarding.step.finish"),
    ]).toEqual(["Welcome", "Agreement", "Model", "Channels", "Finish"]);
  });

  it("provides an English label for the back button", () => {
    const t = i18n.getFixedT("en");

    expect(t("common.back")).toBe("Back");
  });
});
