import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openExternalUrl } from "../../platform";
import { safeFetch } from "../../providers";
import {
  connectOpenKitsuneAccount,
  disconnectOpenKitsuneAccount,
  loadAccountCapability,
  refreshOpenKitsuneAccountEntitlements,
  type DeviceAuthorizationPrompt,
} from "../accountLogin";
import { ACCOUNT_STATUS_CHANGED_EVENT } from "../accountStatusEvents";
import { runNativeAccountLogin, readNativeAccountStatus } from '../../platform/nativeAccountAuth';

vi.mock('../../platform/nativeAccountAuth', () => ({ runNativeAccountLogin: vi.fn(), readNativeAccountStatus: vi.fn() }));

const platform = vi.hoisted(() => ({ web: false, local: false, capacitor: false }));
vi.mock("../../platform", () => ({
  openExternalUrl: vi.fn(),
  get IS_WEB() { return platform.web; },
  get IS_CAPACITOR() { return platform.capacitor; },
}));

vi.mock("../../providers", () => ({
  safeFetch: vi.fn(),
}));

const response = (body: unknown) => new Response(JSON.stringify(body), {
  status: 200,
  headers: { "Content-Type": "application/json" },
});

describe("account login flow", () => {
  afterEach(() => { vi.useRealTimers(); });
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    vi.mocked(safeFetch).mockReset();
    platform.web = false;
    platform.local = false;
    platform.capacitor = false;
  });

  it('uses native authentication on Capacitor without the device-code dialog', async () => {
    platform.capacitor = true;
    vi.mocked(runNativeAccountLogin).mockResolvedValue();
    vi.mocked(readNativeAccountStatus).mockResolvedValueOnce({status:'active',profile:{name:'Mobile'}});
    const onDevicePreparing = vi.fn();
    const onNativePreparing = vi.fn();
    const snapshot = await connectOpenKitsuneAccount('https://original.example',{onDevicePreparing,onNativePreparing});
    expect(snapshot.status).toBe('active');
    expect(runNativeAccountLogin).toHaveBeenCalledWith('https://original.example',undefined);
    expect(onNativePreparing).toHaveBeenCalledOnce();
    expect(onDevicePreparing).not.toHaveBeenCalled();
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it('does not publish a native login result after the current server changes', async () => {
    platform.capacitor = true;
    const abort = new AbortController();
    vi.mocked(runNativeAccountLogin).mockResolvedValue();
    vi.mocked(readNativeAccountStatus).mockImplementationOnce(async () => {
      abort.abort();
      return {status:'active',profile:{name:'Old server'}};
    });
    const listener = vi.fn();
    window.addEventListener(ACCOUNT_STATUS_CHANGED_EVENT,listener);
    try {
      await expect(connectOpenKitsuneAccount('https://original.example',{signal:abort.signal})).rejects.toThrow('account_login_cancelled');
      expect(listener).not.toHaveBeenCalled();
    } finally { window.removeEventListener(ACCOUNT_STATUS_CHANGED_EVENT,listener); }
  });

  it("opens OAuth, waits for completion, and publishes the signed-in snapshot", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({
        attempt_id: "attempt/1",
        authorization_url: "https://account.example/authorize",
      }))
      .mockResolvedValueOnce(response({ status: "complete" }))
      .mockResolvedValueOnce(response({
        status: "active",
        profile: { email: "user@example.com" },
      }));

    const listener = vi.fn();
    window.addEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    try {
      const snapshot = await connectOpenKitsuneAccount("http://localhost:18900", {
        pollIntervalMs: 0,
      });

      expect(openExternalUrl).toHaveBeenCalledWith("https://account.example/authorize");
      expect(safeFetch).toHaveBeenNthCalledWith(
        2,
        "http://localhost:18900/api/account/login/status/attempt%2F1",
        { signal: expect.any(AbortSignal) },
      );
      expect(snapshot).toEqual({
        status: "active",
        profile: { email: "user@example.com" },
      });
      expect(listener).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    }
  });

  it("loads the backend account capability before rendering provider UI", async () => {
    vi.mocked(safeFetch).mockResolvedValueOnce(response({
      enabled: false,
      mode: "disabled",
      provider: null,
      display_name: null,
      supports_entitlements: false,
    }));

    const capability = await loadAccountCapability("http://localhost:18900");

    expect(safeFetch).toHaveBeenCalledWith(
      "http://localhost:18900/api/account/capability",
    );
    expect(capability.enabled).toBe(false);
    expect(capability.mode).toBe("disabled");
  });

  it("surfaces a failed OAuth attempt", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({
        attempt_id: "attempt-2",
        authorization_url: "https://account.example/authorize",
      }))
      .mockResolvedValueOnce(response({ status: "failed", error: "Access denied" }));

    await expect(connectOpenKitsuneAccount("http://localhost:18900", {
      pollIntervalMs: 0,
    })).rejects.toThrow("Access denied");
  });

  it("reuses an in-progress login instead of opening OAuth twice", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({
        attempt_id: "attempt-3",
        authorization_url: "https://account.example/authorize",
      }))
      .mockResolvedValueOnce(response({ status: "complete" }))
      .mockResolvedValueOnce(response({ status: "active" }));

    const first = connectOpenKitsuneAccount("http://localhost:18900", { pollIntervalMs: 0 });
    const second = connectOpenKitsuneAccount("http://localhost:18900", { pollIntervalMs: 0 });

    expect(second).toBe(first);
    await first;
    expect(openExternalUrl).toHaveBeenCalledOnce();
  });

  it("refreshes entitlements and publishes the latest status", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ ok: true }))
      .mockResolvedValueOnce(response({ status: "active", fetched_at: "2026-08-10" }));

    const listener = vi.fn();
    window.addEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    try {
      const snapshot = await refreshOpenKitsuneAccountEntitlements("http://localhost:18900");

      expect(safeFetch).toHaveBeenNthCalledWith(
        1,
        "http://localhost:18900/api/account/entitlements/refresh",
        { method: "POST" },
      );
      expect(snapshot.fetched_at).toBe("2026-08-10");
      expect(listener).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    }
  });

  it("signs out locally without opening a browser", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ end_session_url: "https://account.example/" }))
      .mockResolvedValueOnce(response({ status: "signed_out" }));

    const snapshot = await disconnectOpenKitsuneAccount("http://localhost:18900");

    expect(snapshot.status).toBe("signed_out");
    expect(openExternalUrl).not.toHaveBeenCalled();
  });

  it("prepares the code without opening a tab and only opens on explicit continue", async () => {
    vi.useFakeTimers();
    platform.web = true;
    const popup = { closed: false, opener: window, location: { replace: vi.fn() }, close: vi.fn(), focus:vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ attempt_id: "web", flow: "device", user_code: "ABCD-EFGH", verification_uri: "https://account.example/device", authorization_url: "https://account.example/authorize" }))
      .mockResolvedValueOnce(response({ status: "complete" }))
      .mockResolvedValueOnce(response({ status: "active" }));
    let prompt!: DeviceAuthorizationPrompt;
    const onDevicePreparing = vi.fn();
    const operation = connectOpenKitsuneAccount("https://kitsune.example", { pollIntervalMs: 30_000, onDevicePreparing, onDeviceAuthorization:p=>{prompt=p;} });
    expect(onDevicePreparing).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(0);
    expect(open).not.toHaveBeenCalled();
    expect(prompt.userCode).toBe("ABCD-EFGH");
    const opening = prompt.openAuthorization();
    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(popup.opener).toBeNull();
    await opening;
    await prompt.openAuthorization();
    expect(popup.focus).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledOnce();
    expect(safeFetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30_000);
    await operation;
    expect(safeFetch).toHaveBeenNthCalledWith(1, "https://kitsune.example/api/account/login/start", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flow: "device" }),
    });
    expect(popup.location.replace).toHaveBeenCalledWith("https://account.example/authorize");
    expect(openExternalUrl).not.toHaveBeenCalled();
    expect(popup.close).toHaveBeenCalledOnce();
    await expect(prompt.openAuthorization()).rejects.toThrow("account_login_expired");
  });

  it("lets the user retry a blocked popup without creating a second grant", async () => {
    vi.useFakeTimers();
    platform.web = true;
    const popup = {closed:false,opener:null,location:{replace:vi.fn()},close:vi.fn()};
    const open = vi.spyOn(window, "open").mockReturnValueOnce(null).mockReturnValueOnce(popup as unknown as Window);
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({attempt_id:"retry",flow:"device",user_code:"ABCD-EFGH",verification_uri:"https://account.example/device",authorization_url:"https://account.example/device?user_code=ABCD-EFGH"}))
      .mockResolvedValueOnce(response({status:"complete"}))
      .mockResolvedValueOnce(response({status:"active"}));
    let prompt!: DeviceAuthorizationPrompt;
    const operation = connectOpenKitsuneAccount("https://kitsune.example",{pollIntervalMs:30_000,onDeviceAuthorization:p=>{prompt=p;}});
    await vi.advanceTimersByTimeAsync(0);
    await expect(prompt.openAuthorization()).rejects.toThrow("account_popup_blocked");
    await prompt.openAuthorization();
    expect(open).toHaveBeenCalledTimes(2);
    expect(safeFetch).toHaveBeenCalledTimes(1);
    expect(popup.location.replace).toHaveBeenCalledWith(prompt.authorizationUrl);
    await vi.advanceTimersByTimeAsync(30_000);
    await operation;
  });

  it("does not open a blank tab when the account service does not support device authorization", async () => {
    platform.web = true;
    const popup = { closed: false, opener: null, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    vi.mocked(safeFetch).mockRejectedValueOnce(new Error("account_device_not_supported"));
    await expect(connectOpenKitsuneAccount("https://kitsune.example")).rejects.toThrow("account_device_not_supported");
    expect(window.open).not.toHaveBeenCalled();
  });

  it("refuses to navigate an expired preview and cancels without opening a tab", async () => {
    vi.useFakeTimers();
    platform.web = true;
    const abort = new AbortController();
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({attempt_id:"preview",flow:"device",expires_in:1,user_code:"ABCD-EFGH",verification_uri:"https://account.example/device",authorization_url:"https://account.example/device?user_code=ABCD-EFGH"}))
      .mockResolvedValueOnce(response({status:"cancelled"}));
    let prompt!: DeviceAuthorizationPrompt;
    const operation = connectOpenKitsuneAccount("https://kitsune.example",{signal:abort.signal,pollIntervalMs:30_000,onDeviceAuthorization:p=>{prompt=p;}});
    const cancelled = expect(operation).rejects.toThrow("account_login_cancelled");
    await vi.advanceTimersByTimeAsync(1100);
    await expect(prompt.openAuthorization()).rejects.toThrow("account_login_expired");
    expect(open).not.toHaveBeenCalled();
    abort.abort();
    await cancelled;
    expect(safeFetch).toHaveBeenCalledTimes(2);
  });

  it("cancels the backend attempt when the user cancels", async () => {
    const abort = new AbortController();
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ attempt_id: "cancel", authorization_url: "https://account.example/authorize" }))
      .mockResolvedValueOnce(response({ status: "cancelled" }));
    await expect(connectOpenKitsuneAccount("http://localhost:18900", {
      pollIntervalMs: 0, signal: abort.signal, onAuthorizationUrl: () => abort.abort(),
    })).rejects.toThrow("account_login_cancelled");
    expect(safeFetch).toHaveBeenLastCalledWith(
      "http://localhost:18900/api/account/login/cancel/cancel", { method: "POST" },
    );
  });

  it("bounds polling even when the backend never reports expiry", async () => {
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ attempt_id: "expired", authorization_url: "https://account.example/authorize", expires_in: 0 }))
      .mockResolvedValueOnce(response({ status: "cancelled" }));
    await expect(connectOpenKitsuneAccount("http://localhost:18900")).rejects.toThrow("account_login_expired");
    expect(safeFetch).toHaveBeenCalledTimes(2);
  });

  it("publishes a login that finished before cancellation reached the backend", async () => {
    const abort = new AbortController();
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({ attempt_id: "race", authorization_url: "https://account.example/authorize" }))
      .mockResolvedValueOnce(response({ status: "complete" }))
      .mockResolvedValueOnce(response({ status: "active" }));
    const result = await connectOpenKitsuneAccount("http://localhost:18900", {
      signal: abort.signal, onAuthorizationUrl: () => abort.abort(),
    });
    expect(result.status).toBe("active");
  });

  it.each(["visibilitychange", "focus", "pageshow"])("checks immediately on %s and removes wake listeners after completion", async event => {
    vi.useFakeTimers();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({attempt_id:"resume", authorization_url:"https://account.example/device"}))
      .mockResolvedValueOnce(response({status:"complete"}))
      .mockResolvedValueOnce(response({status:"active"}));
    const operation = connectOpenKitsuneAccount("https://kitsune.example", {pollIntervalMs:30_000});
    await vi.advanceTimersByTimeAsync(0);
    expect(safeFetch).toHaveBeenCalledTimes(1);
    const target = event === "visibilitychange" ? document : window;
    target.dispatchEvent(new Event(event));
    await expect(operation).resolves.toEqual({status:"active"});
    target.dispatchEvent(new Event(event));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(safeFetch).toHaveBeenCalledTimes(3);
  });

  it("coalesces foreground events during a request without concurrent polling", async () => {
    vi.useFakeTimers();
    const visible = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    let finishPoll!: (response: Response) => void;
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({attempt_id:"resume", authorization_url:"https://account.example/device"}))
      .mockReturnValueOnce(new Promise(resolve => { finishPoll = resolve; }))
      .mockResolvedValueOnce(response({status:"complete"}))
      .mockResolvedValueOnce(response({status:"active"}));
    const operation = connectOpenKitsuneAccount("https://kitsune.example", {pollIntervalMs:30_000});
    await vi.advanceTimersByTimeAsync(0);
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(safeFetch).toHaveBeenCalledTimes(1);
    visible.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(safeFetch).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("pageshow"));
    await vi.advanceTimersByTimeAsync(0);
    expect(safeFetch).toHaveBeenCalledTimes(2);
    finishPoll(response({status:"pending"}));
    await expect(operation).resolves.toEqual({status:"active"});
    expect(safeFetch).toHaveBeenCalledTimes(4);
  });

  it("wakes a pending wait immediately on cancellation", async () => {
    vi.useFakeTimers();
    const abort = new AbortController();
    vi.mocked(safeFetch)
      .mockResolvedValueOnce(response({attempt_id:"cancel-wait", authorization_url:"https://account.example/device"}))
      .mockResolvedValueOnce(response({status:"cancelled"}));
    const operation = connectOpenKitsuneAccount("https://kitsune.example", {pollIntervalMs:30_000, signal:abort.signal});
    const rejected = expect(operation).rejects.toThrow("account_login_cancelled");
    await vi.advanceTimersByTimeAsync(0);
    abort.abort();
    await rejected;
    expect(safeFetch).toHaveBeenCalledTimes(2);
  });

  it.each(["login", "refresh"])("discards a delayed %s snapshot after logout", async (kind) => {
    let release!: (value: Response) => void;
    const delayed = new Promise<Response>((resolve) => { release = resolve; });
    const requested = vi.fn();
    vi.mocked(safeFetch).mockImplementation(async (url) => {
      const path = String(url);
      if (path.endsWith("/login/start")) return response({ attempt_id: "old", authorization_url: "https://account.example/authorize" });
      if (path.includes("/login/status/")) return response({ status: "complete" });
      if (path.endsWith("/status") && !requested.mock.calls.length) {
        requested();
        return delayed;
      }
      if (path.endsWith("/status")) return response({ status: "signed_out" });
      return response({ ok: true });
    });
    const listener = vi.fn();
    window.addEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    try {
      const old = kind === "login"
        ? connectOpenKitsuneAccount("http://localhost:18900", { pollIntervalMs: 0 })
        : refreshOpenKitsuneAccountEntitlements("http://localhost:18900");
      const rejected = expect(old).rejects.toThrow("account_operation_superseded");
      await vi.waitFor(() => expect(requested).toHaveBeenCalledOnce());
      await disconnectOpenKitsuneAccount("http://localhost:18900");
      release(response({ status: "active", account_user_id: "old-account" }));
      await rejected;
      expect(listener).toHaveBeenCalledOnce();
      expect((listener.mock.calls[0][0] as CustomEvent).detail.status).toBe("signed_out");
    } finally {
      window.removeEventListener(ACCOUNT_STATUS_CHANGED_EVENT, listener);
    }
  });
});
