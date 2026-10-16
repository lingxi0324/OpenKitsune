import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildMarketplaceContextUrl,
  buildMarketplaceContextUrlFromDeepLink,
  buildMarketplaceHandoffUrl,
  hasMarketplaceClientVersion,
  marketplaceDeepLinkAction,
  normalizeMarketplaceClientVersion,
} from "../navigation";

describe("Marketplace navigation", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("normalizes the desktop version to the Marketplace contract", () => {
    expect(normalizeMarketplaceClientVersion("v01.027.004-beta.1")).toBe("1.27.4");
    expect(normalizeMarketplaceClientVersion("1.27")).toBeNull();
    expect(hasMarketplaceClientVersion("0.0.0")).toBe(false);
    expect(hasMarketplaceClientVersion("1.27.40")).toBe(true);
  });

  it("opens the Marketplace home through the client context endpoint", () => {
    vi.stubEnv("VITE_MARKETPLACE_URL", "");
    const result = new URL(buildMarketplaceContextUrl("1.27.40"));
    expect(result.origin).toBe("https://marketplace.openkitsune.cn");
    expect(result.pathname).toBe("/openkitsune/context");
    expect(result.searchParams.get("version")).toBe("1.27.40");
    expect(result.searchParams.get("next")).toBe("/");
  });

  it("restores a clean Marketplace detail URL from an open deep link", () => {
    const deepLink = "openkitsune://marketplace/open?return_url="
      + encodeURIComponent("https://marketplace.openkitsune.cn/resources/example?tab=versions#versions");
    const result = new URL(buildMarketplaceContextUrlFromDeepLink(deepLink, "1.27.40")!);

    expect(result.origin).toBe("https://marketplace.openkitsune.cn");
    expect(result.pathname).toBe("/openkitsune/context");
    expect(result.searchParams.get("version")).toBe("1.27.40");
    expect(result.searchParams.get("next")).toBe("/resources/example?tab=versions#versions");
  });

  it("opens a restricted handoff before storing client context without leaking the ticket into it", () => {
    const handoff = new URL(buildMarketplaceHandoffUrl("v1.27.40-beta.1", "t".repeat(64)));
    expect(handoff.origin).toBe("https://marketplace.openkitsune.cn");
    expect(handoff.pathname).toBe("/auth/desktop");
    expect(handoff.searchParams.get("ticket")).toBe("t".repeat(64));
    const context = new URL(handoff.searchParams.get("next")!, handoff.origin);
    expect(context.pathname).toBe("/openkitsune/context");
    expect(context.searchParams.get("version")).toBe("1.27.40");
    expect(context.searchParams.get("next")).toBe("/");
    expect(context.searchParams.has("ticket")).toBe(false);
  });

  it("preserves a detail destination through both redirects on a configured origin", () => {
    const next = "/resources/example?tab=versions&sort=newest#versions";
    const handoff = new URL(buildMarketplaceHandoffUrl("1.27.40", "t".repeat(64), next, "http://localhost:3001"));
    expect(handoff.origin).toBe("http://localhost:3001");
    const context = new URL(handoff.searchParams.get("next")!, handoff.origin);
    expect(context.searchParams.get("next")).toBe(next);
  });

  it.each(["https://evil.example/", "//evil.example/", "/\\evil.example/", "/openkitsune/context?version=1.0.0"])(
    "sanitizes the post-login destination %s",
    (next) => {
      const handoff = new URL(buildMarketplaceHandoffUrl("1.27.40", "t".repeat(64), next));
      const context = new URL(handoff.searchParams.get("next")!, handoff.origin);
      expect(context.searchParams.get("next")).toBe("/");
    },
  );

  it("allows a configured Marketplace origin and local development origins", () => {
    const configured = "https://market.example.com";
    const configuredLink = "openkitsune://marketplace/open?return_url="
      + encodeURIComponent("https://market.example.com/catalog");
    const localLink = "openkitsune://marketplace/open?return_url="
      + encodeURIComponent("http://localhost:3001/catalog");

    expect(buildMarketplaceContextUrlFromDeepLink(configuredLink, "1.27.40", configured))
      .toContain("https://market.example.com/openkitsune/context?");
    expect(buildMarketplaceContextUrlFromDeepLink(localLink, "1.27.40", configured))
      .toContain("http://localhost:3001/openkitsune/context?");
  });

  it("rejects untrusted return URLs and unsupported actions", () => {
    const malicious = "openkitsune://marketplace/open?return_url="
      + encodeURIComponent("https://evil.example/resources/example");

    expect(buildMarketplaceContextUrlFromDeepLink(malicious, "1.27.40")).toBeNull();
    expect(marketplaceDeepLinkAction("openkitsune://marketplace/open?return_url=x")).toBe("open");
    expect(marketplaceDeepLinkAction("openkitsune://marketplace/install?token=x")).toBe("install");
    expect(marketplaceDeepLinkAction("openkitsune://marketplace/unknown")).toBeNull();
  });

  it("prevents recursive client context targets", () => {
    const result = new URL(buildMarketplaceContextUrl(
      "1.27.40",
      "/openkitsune/context?version=0.0.0&next=/catalog",
    ));
    expect(result.searchParams.get("next")).toBe("/");
  });
});
