import { beforeEach, describe, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), open: vi.fn(), fetch: vi.fn(), remote: vi.fn() }));
vi.mock("../../platform", () => ({ IS_TAURI: true, IS_CAPACITOR: false, invoke: mocks.invoke, openExternalUrl: mocks.open }));
vi.mock("../../providers", () => ({ safeFetchResponse: mocks.fetch }));
vi.mock("../../platform/auth", () => ({ isTauriRemoteMode: mocks.remote }));
import { marketplaceOpenErrorKey, openMarketplaceWithAccount } from "../open";

describe("desktop identity handoff navigation", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.invoke.mockResolvedValue("native-secret");
    mocks.remote.mockReturnValue(false);
  });
  it("opens a one-use handoff without exposing desktop credentials", async () => {
    mocks.fetch.mockResolvedValue(Response.json({ ticket: "a".repeat(64) }));
    await openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900");
    expect(mocks.invoke).toHaveBeenCalledWith("openkitsune_account_session_token");
    const request = mocks.fetch.mock.calls[0][1];
    expect(request.headers["X-OpenKitsune-Desktop-Token"]).toBe("native-secret");
    const opened = new URL(mocks.open.mock.calls[0][0]);
    expect(opened.pathname).toBe("/auth/desktop");
    expect(opened.searchParams.get("ticket")).toBe("a".repeat(64));
    expect(opened.href).not.toContain("native-secret");
  });
  it("leaves the market session alone when desktop is signed out", async () => {
    mocks.fetch.mockResolvedValue(Response.json({ ticket: null }));
    await openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900");
    const opened = new URL(mocks.open.mock.calls[0][0]);
    expect(opened.pathname).toBe("/openkitsune/context");
    expect(opened.searchParams.get("next")).toBe("/");
  });
  it("publishes the recovered desktop identity before opening the browser", async () => {
    const account = { status: "active", profile: { name: "Recovered account" } };
    const changed = vi.fn();
    window.addEventListener("openkitsune:account-status-changed", changed);
    try {
      mocks.fetch.mockResolvedValue(Response.json({ ticket: "a".repeat(64), account }));
      mocks.open.mockImplementation(() => {
        expect(changed).toHaveBeenCalledOnce();
        expect(changed.mock.calls[0][0].detail).toEqual(account);
      });
      await openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900");
      expect(mocks.open).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener("openkitsune:account-status-changed", changed);
    }
  });
  it("never asks a remote service for its owner's credential", async () => {
    mocks.remote.mockReturnValue(true);
    await openMarketplaceWithAccount("1.27.40", "https://remote.example.com");
    expect(mocks.invoke).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(new URL(mocks.open.mock.calls[0][0]).pathname).toBe("/openkitsune/context");
  });
  it("does not fall back to the browser identity when handoff fails", async () => {
    mocks.fetch.mockResolvedValue(new Response("", { status: 503 }));
    await expect(openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900")).rejects.toThrow();
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it("explains a rejected native connection without opening another identity", async () => {
    mocks.fetch.mockResolvedValue(Response.json({ detail: "desktop_account_access_required" }, { status: 403 }));
    const error = await openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900").catch((error) => error);
    expect(marketplaceOpenErrorKey(error)).toBe("topbar.marketplaceDesktopConnectionFailed");
    expect(mocks.open).not.toHaveBeenCalled();
  });
  it("explains an unavailable native credential command", async () => {
    mocks.invoke.mockRejectedValue("command unavailable");
    await expect(openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900")).rejects.toThrow("marketplace_desktop_connection_failed");
    expect(mocks.fetch).not.toHaveBeenCalled();
  });
  it("supports the explicitly disabled account distribution", async () => {
    mocks.fetch.mockResolvedValueOnce(new Response("", { status: 404 }))
      .mockResolvedValueOnce(Response.json({ enabled: false }));
    await openMarketplaceWithAccount("1.27.40", "http://127.0.0.1:18900");
    expect(new URL(mocks.open.mock.calls[0][0]).pathname).toBe("/openkitsune/context");
  });
});
