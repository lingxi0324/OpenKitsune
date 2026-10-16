import { invoke, IS_TAURI, IS_CAPACITOR, IS_MOBILE_BROWSER, openExternalUrl } from "../platform";
import { marketplaceOpenErrorKey as mobileOpenErrorKey, openMarketplace } from "./mobile";
import { safeFetchResponse } from "../providers";
import { isTauriRemoteMode } from "../platform/auth";
import { dispatchAccountStatusChanged, type AccountStatusSummary } from "../utils/accountStatusEvents";
import { buildMarketplaceContextUrl, buildMarketplaceHandoffUrl, marketplaceOrigin } from "./navigation";
import { openWebMarketplace } from './web';

export function marketplaceOpenErrorKey(error: unknown): string {
  const code = error instanceof Error ? error.message : String(error);
  return code === "marketplace_desktop_connection_failed"
    ? "topbar.marketplaceDesktopConnectionFailed"
    : mobileOpenErrorKey(error);
}

export async function desktopAccountHeaders(): Promise<Record<string, string>> {
  if (!IS_TAURI || isTauriRemoteMode()) return {};
  let token: string;
  try {
    token = await invoke<string>("openkitsune_account_session_token");
  } catch {
    throw new Error("marketplace_desktop_connection_failed");
  }
  if (!token) throw new Error("marketplace_desktop_connection_failed");
  return token ? { "X-OpenKitsune-Desktop-Token": token } : {};
}

export async function openMarketplaceWithAccount(
  version: string, apiBaseUrl?: string, next = "/", configuredOrigin?: string,
): Promise<void> {
  if (IS_CAPACITOR) return openMarketplace(version, next);
  if (!IS_TAURI) {
    openWebMarketplace(version, next, configuredOrigin, !IS_MOBILE_BROWSER);
    return;
  }
  const origin = marketplaceOrigin(configuredOrigin);
  let target = buildMarketplaceContextUrl(version, next, origin);
  if (IS_TAURI && !isTauriRemoteMode() && apiBaseUrl) {
    // Backend verifies the same-user native credential and target independently.
    const response = await safeFetchResponse(`${apiBaseUrl}/api/account/marketplace/handoff`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...await desktopAccountHeaders() },
      body: JSON.stringify({ origin }),
    });
    if (response.ok) {
      const result = await response.json() as { ticket: string | null; account?: AccountStatusSummary };
      if (result.account) dispatchAccountStatusChanged(result.account);
      if (result.ticket) target = buildMarketplaceHandoffUrl(version, result.ticket, next, origin);
    } else {
      if (response.status === 403) throw new Error("marketplace_desktop_connection_failed");
      // Only a deliberately disabled integration may omit the handoff route.
      // An old/unavailable enabled backend must not silently use another identity.
      const capability = response.status === 404
        ? await safeFetchResponse(`${apiBaseUrl}/api/account/capability`)
        : null;
      if (!capability?.ok || (await capability.json()).enabled !== false) {
        throw new Error("marketplace_handoff_failed");
      }
    }
  }
  await openExternalUrl(target);
}
