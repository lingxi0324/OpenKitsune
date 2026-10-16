const OFFICIAL_MARKETPLACE_ORIGIN = "https://marketplace.openkitsune.cn";
const CLIENT_VERSION_PATTERN = /^[vV]?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/;

export type MarketplaceDeepLinkAction = "install" | "open" | null;

function normalizeOrigin(value: string): string | null {
  try {
    const parsed = new URL(value.trim());
    const isLoopback = parsed.protocol === "http:"
      && ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
    if (parsed.protocol !== "https:" && !isLoopback) return null;
    if (parsed.username || parsed.password || parsed.search || parsed.hash) return null;
    if (parsed.pathname !== "/" && parsed.pathname !== "") return null;
    return parsed.origin;
  } catch {
    return null;
  }
}

export function marketplaceOrigin(configured?: string): string {
  return normalizeOrigin(configured || import.meta.env.VITE_MARKETPLACE_URL || "")
    || OFFICIAL_MARKETPLACE_ORIGIN;
}

export function normalizeMarketplaceClientVersion(value: string): string | null {
  const match = CLIENT_VERSION_PATTERN.exec(value.trim());
  if (!match) return null;
  return `${Number(match[1])}.${Number(match[2])}.${Number(match[3])}`;
}

export function hasMarketplaceClientVersion(value: string): boolean {
  const normalized = normalizeMarketplaceClientVersion(value);
  return normalized !== null && normalized !== "0.0.0";
}

function safeMarketplacePath(value: string): string {
  const candidate = value.trim() || "/";
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return "/";
  }
  try {
    const parsed = new URL(candidate, "https://marketplace.invalid");
    if (parsed.origin !== "https://marketplace.invalid") return "/";
    if (parsed.pathname.startsWith("/openkitsune/context")) return "/";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/";
  }
}

export function buildMarketplaceContextUrl(
  version: string,
  next = "/",
  configuredOrigin?: string,
): string {
  const normalizedVersion = normalizeMarketplaceClientVersion(version);
  if (!normalizedVersion || normalizedVersion === "0.0.0") {
    throw new Error("marketplace_client_version_invalid");
  }

  const contextUrl = new URL("/openkitsune/context", marketplaceOrigin(configuredOrigin));
  contextUrl.searchParams.set("version", normalizedVersion);
  contextUrl.searchParams.set("next", safeMarketplacePath(next));
  return contextUrl.toString();
}

/** Preserve the browser's own session; the server resolves desktop identity conflicts. */
export function buildMarketplaceHandoffUrl(
  version: string,
  ticket: string,
  next = "/",
  configuredOrigin?: string,
): string {
  if (!/^[A-Za-z0-9_-]{32,512}$/.test(ticket)) throw new Error("marketplace_handoff_invalid");
  const context = new URL(buildMarketplaceContextUrl(version, next, configuredOrigin));
  const target = new URL("/auth/desktop", context.origin);
  target.search = new URLSearchParams({ ticket, next: context.pathname + context.search }).toString();
  return target.toString();
}

export function marketplaceDeepLinkAction(value: string): MarketplaceDeepLinkAction {
  try {
    const url = new URL(value);
    if (url.protocol !== "openkitsune:" || url.hostname !== "marketplace") return null;
    if (url.pathname === "/install") return "install";
    if (url.pathname === "/open") return "open";
    return null;
  } catch {
    return null;
  }
}

function isTrustedMarketplaceReturnUrl(returnUrl: URL, configuredOrigin?: string): boolean {
  if (returnUrl.username || returnUrl.password) return false;
  if (returnUrl.origin === OFFICIAL_MARKETPLACE_ORIGIN) return true;
  if (returnUrl.origin === marketplaceOrigin(configuredOrigin)) return true;
  return returnUrl.protocol === "http:"
    && ["localhost", "127.0.0.1", "[::1]"].includes(returnUrl.hostname);
}

export function buildMarketplaceContextUrlFromDeepLink(
  value: string,
  version: string,
  configuredOrigin?: string,
): string | null {
  try {
    const deepLink = new URL(value);
    if (
      deepLink.protocol !== "openkitsune:"
      || deepLink.hostname !== "marketplace"
      || deepLink.pathname !== "/open"
    ) return null;

    const rawReturnUrl = deepLink.searchParams.get("return_url");
    if (!rawReturnUrl) return null;
    const returnUrl = new URL(rawReturnUrl);
    if (!isTrustedMarketplaceReturnUrl(returnUrl, configuredOrigin)) return null;

    const next = `${returnUrl.pathname}${returnUrl.search}${returnUrl.hash}`;
    return buildMarketplaceContextUrl(version, next, returnUrl.origin);
  } catch {
    return null;
  }
}
