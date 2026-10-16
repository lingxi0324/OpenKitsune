import { IS_CAPACITOR, IS_WEB, openExternalUrl } from "../platform";
import { isTauriRemoteMode } from "../platform/auth";
import { safeFetch } from "../providers";
import {
  dispatchAccountStatusChanged,
  type AccountStatusSummary,
} from "./accountStatusEvents";

type LoginStart = {
  attempt_id: string;
  authorization_url: string;
  expires_in?: number;
  flow?: "loopback" | "device";
  user_code?: string;
  verification_uri?: string;
};

type LoginProgress = {
  status: string;
  error?: string;
};

type AccountLoginOptions = {
  pollIntervalMs?: number;
  signal?: AbortSignal;
  onAuthorizationUrl?: (url: string) => void;
  onDeviceAuthorization?: (prompt: DeviceAuthorizationPrompt) => void;
  onDevicePreparing?: () => void;
  onNativePreparing?: () => void;
};

export type DeviceAuthorizationPrompt = {
  userCode: string;
  verificationUri: string;
  authorizationUrl: string;
  openAuthorization: () => Promise<void>;
};

export type AccountCapability = {
  enabled: boolean;
  mode: "openkitsune" | "custom" | "disabled";
  provider: string | null;
  display_name: string | null;
  supports_entitlements: boolean;
};

let activeLogin: Promise<AccountStatusSummary> | null = null;
let accountGeneration = 0;
export function getAccountGeneration() { return accountGeneration; }
function requireCurrentGeneration(generation: number) {
  if (generation !== accountGeneration) throw new Error('account_operation_superseded');
}
let activeLoginBase: string | null = null;
let nativeRecovery: Promise<AccountStatusSummary | null> | null = null;
let nativeRecoveryBase: string | null = null;

export async function loadAccountCapability(apiBaseUrl: string): Promise<AccountCapability> {
  const response = await safeFetch(`${apiBaseUrl}/api/account/capability`);
  return await response.json() as AccountCapability;
}

function createLoginPollWaiter(signal?: AbortSignal) {
  let wakePending = false;
  let finishWait: (() => void) | undefined;
  const wake = () => {
    wakePending = true;
    finishWait?.();
  };
  const onForeground = () => {
    if (document.visibilityState === "visible") wake();
  };
  document.addEventListener("visibilitychange", onForeground);
  window.addEventListener("focus", onForeground);
  window.addEventListener("pageshow", onForeground);
  signal?.addEventListener("abort", wake);
  return {
    wait(milliseconds: number): Promise<void> {
      // Remember a foreground event during an in-flight request, then poll
      // sequentially. Only the backend decides when to contact the provider.
      if (wakePending || signal?.aborted) {
        wakePending = false;
        return Promise.resolve();
      }
      return new Promise(resolve => {
        const timer = window.setTimeout(finish, milliseconds);
        function finish() {
          window.clearTimeout(timer);
          finishWait = undefined;
          wakePending = false;
          resolve();
        }
        finishWait = finish;
      });
    },
    dispose() {
      document.removeEventListener("visibilitychange", onForeground);
      window.removeEventListener("focus", onForeground);
      window.removeEventListener("pageshow", onForeground);
      signal?.removeEventListener("abort", wake);
      finishWait?.();
    },
  };
}

async function runAccountLogin(
  apiBaseUrl: string,
  options: AccountLoginOptions,
  generation: number,
): Promise<AccountStatusSummary> {
  let attempt: LoginStart | undefined;
  let popup: Window | null = null;
  const openedTabs = new Set<Window>();
  let finished = false;
  let completed = false;
  const pollWaiter = createLoginPollWaiter(options.signal);
  const checkCancelled = () => {
    requireCurrentGeneration(generation);
    if (options.signal?.aborted) throw new Error("account_login_cancelled");
  };
  try {
    checkCancelled();
    const flow = IS_WEB || IS_CAPACITOR || isTauriRemoteMode() ? "device" : "loopback";
    if (flow === "device") options.onDevicePreparing?.();
    const response = await safeFetch(`${apiBaseUrl}/api/account/login/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ flow }),
    });
    attempt = await response.json() as LoginStart;
    if (!attempt.attempt_id || !attempt.authorization_url) {
      throw new Error("The account service returned an invalid login attempt.");
    }
    checkCancelled();
    const authorizationUrl = new URL(attempt.authorization_url);
    if (!["http:", "https:"].includes(authorizationUrl.protocol)) {
      throw new Error("The account service returned an invalid authorization URL.");
    }
    const deadline = Date.now() + (attempt.expires_in ?? 180) * 1_000;
    if (flow === "device") {
      if (attempt.flow !== "device" || !attempt.user_code || !attempt.verification_uri || !options.onDeviceAuthorization) {
        throw new Error("account_device_start_failed");
      }
      const url = attempt.authorization_url;
      options.onDeviceAuthorization({
        userCode: attempt.user_code, verificationUri: attempt.verification_uri,
        authorizationUrl: url,
        async openAuthorization() {
          checkCancelled();
          if (finished || Date.now() >= deadline) throw new Error("account_login_expired");
          if (IS_WEB) {
            // Called directly by the Continue button, while its user gesture
            // is active. Never open a blank tab while preparing the code.
            if (popup && !popup.closed) {
              popup.focus();
            } else {
              popup = window.open("about:blank", "_blank");
              if (!popup) throw new Error("account_popup_blocked");
              openedTabs.add(popup);
              popup.opener = null;
              popup.location.replace(url);
            }
          } else {
            await openExternalUrl(url);
          }
          options.onAuthorizationUrl?.(url);
        },
      });
    } else {
      await openExternalUrl(attempt.authorization_url);
      options.onAuthorizationUrl?.(attempt.authorization_url);
    }

    while (Date.now() < deadline) {
      checkCancelled();
      await pollWaiter.wait(options.pollIntervalMs ?? 1_000);
      checkCancelled();
      const poll = await safeFetch(
        `${apiBaseUrl}/api/account/login/status/${encodeURIComponent(attempt.attempt_id)}`,
        // A successful device poll also fetches the profile and entitlements.
        { signal: AbortSignal.timeout(45_000) },
      );
      const result = await poll.json() as LoginProgress;
      if (result.status === "complete") {
        completed = true;
        return await loadAndPublishAccountStatus(apiBaseUrl, generation, options.signal);
      }
      if (["failed", "expired", "cancelled"].includes(result.status)) {
        throw new Error(result.error || "account_login_expired");
      }
    }
    throw new Error("account_login_expired");
  } catch (error) {
    if (!completed && attempt?.attempt_id) {
      try {
        const cancellation = await safeFetch(
          `${apiBaseUrl}/api/account/login/cancel/${encodeURIComponent(attempt.attempt_id)}`,
          { method: "POST" },
        );
        // Authorization may finish while cancellation is in flight. Reflect
        // the actual backend session instead of leaving the UI signed out.
        if ((await cancellation.json() as LoginProgress).status === "complete") {
          return await loadAndPublishAccountStatus(apiBaseUrl, generation);
        }
      } catch { /* The backend also expires attempts if it is unreachable. */ }
    }
    throw error;
  } finally {
    finished = true;
    pollWaiter.dispose();
    for (const tab of openedTabs) {
      if (!tab.closed) tab.close();
    }
  }
}

async function loadAndPublishAccountStatus(apiBaseUrl: string, generation: number, signal?: AbortSignal): Promise<AccountStatusSummary> {
  requireCurrentGeneration(generation);
  const statusResponse = await safeFetch(`${apiBaseUrl}/api/account/status`);
  const snapshot = await statusResponse.json() as AccountStatusSummary;
  requireCurrentGeneration(generation);
  if (signal?.aborted) throw new Error('account_login_cancelled');
  dispatchAccountStatusChanged(snapshot);
  return snapshot;
}

export function connectOpenKitsuneAccount(
  apiBaseUrl: string,
  options: AccountLoginOptions = {},
): Promise<AccountStatusSummary> {
  if (activeLogin) {
    if (activeLoginBase === apiBaseUrl) return activeLogin;
    return activeLogin.catch(() => undefined).then(() => connectOpenKitsuneAccount(apiBaseUrl, options));
  }
  if (IS_CAPACITOR && nativeRecovery) {
    const recoveryBase = nativeRecoveryBase;
    return nativeRecovery.then(snapshot => snapshot && recoveryBase === apiBaseUrl
      ? snapshot : connectOpenKitsuneAccount(apiBaseUrl, options));
  }

  const generation = ++accountGeneration;
  const operation = IS_CAPACITOR ? (async () => {
    options.onNativePreparing?.();
    const { runNativeAccountLogin, readNativeAccountStatus } = await import('../platform/nativeAccountAuth');
    await runNativeAccountLogin(apiBaseUrl, options.signal);
    if (options.signal?.aborted) throw new Error('account_login_cancelled');
    const snapshot = await readNativeAccountStatus(apiBaseUrl, options.signal);
    if (options.signal?.aborted) throw new Error('account_login_cancelled');
    requireCurrentGeneration(generation);
    dispatchAccountStatusChanged(snapshot);
    return snapshot;
  })() : runAccountLogin(apiBaseUrl, options, generation);
  activeLogin = operation;
  activeLoginBase = apiBaseUrl;
  const clearOperation = () => {
    if (activeLogin === operation) { activeLogin = null; activeLoginBase = null; }
  };
  void operation.then(clearOperation, clearOperation);
  return operation;
}

export async function watchNativeAccountLogin(apiBaseUrl: string, onRestored: (snapshot: AccountStatusSummary) => void) {
  if (!IS_CAPACITOR) return () => {};
  const { recoverNativeAccountLogin, watchNativeAccountResults, readNativeAccountStatus } = await import('../platform/nativeAccountAuth');
  const abort = new AbortController();
  const stop = await watchNativeAccountResults(() => {
    if (activeLogin || nativeRecovery || abort.signal.aborted) return;
    const generation = accountGeneration;
    const operation = (async () => {
      if (!await recoverNativeAccountLogin(apiBaseUrl, abort.signal) || abort.signal.aborted) {
        return null;
      }
      const snapshot = await readNativeAccountStatus(apiBaseUrl, abort.signal);
      if (abort.signal.aborted) return null;
      requireCurrentGeneration(generation);
    dispatchAccountStatusChanged(snapshot);
      return snapshot;
    })();
    nativeRecovery = operation;
    nativeRecoveryBase = apiBaseUrl;
    const clearRecovery = () => {
      if (nativeRecovery === operation) { nativeRecovery = null; nativeRecoveryBase = null; }
    };
    void operation.then(clearRecovery, clearRecovery);
    void operation.then(snapshot => { if (snapshot && !abort.signal.aborted) onRestored(snapshot); })
      .catch(() => { /* Retry from the sign-in button after reconnecting. */ });
  });
  return () => { abort.abort(); stop(); };
}

export async function refreshOpenKitsuneAccountEntitlements(
  apiBaseUrl: string,
): Promise<AccountStatusSummary> {
  const generation = accountGeneration;
  await safeFetch(`${apiBaseUrl}/api/account/entitlements/refresh`, { method: "POST" });
  return loadAndPublishAccountStatus(apiBaseUrl, generation);
}

export async function disconnectOpenKitsuneAccount(
  apiBaseUrl: string,
): Promise<AccountStatusSummary> {
  const generation = ++accountGeneration;
  activeLogin = null;
  await safeFetch(`${apiBaseUrl}/api/account/logout`, { method: "POST" });
  return loadAndPublishAccountStatus(apiBaseUrl, generation);
}
