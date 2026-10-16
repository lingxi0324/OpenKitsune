import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVersionCheck } from "../useVersionCheck";

const { checkForUpdateMock, getAppVersionMock } = vi.hoisted(() => ({
  checkForUpdateMock: vi.fn(),
  getAppVersionMock: vi.fn(),
}));

vi.mock("../../platform", () => ({
  checkForUpdate: (...args: unknown[]) => checkForUpdateMock(...args),
  getAppVersion: (...args: unknown[]) => getAppVersionMock(...args),
  relaunchApp: vi.fn(),
}));

describe("useVersionCheck", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    checkForUpdateMock.mockReset();
    getAppVersionMock.mockReset();
    getAppVersionMock.mockResolvedValue("1.2.3");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("bypasses skipped-version suppression for a manual check", async () => {
    localStorage.setItem("openkitsune_release_skipped", "1.3.0");
    const update = {
      version: "1.3.0",
      downloadAndInstall: vi.fn(),
    };
    checkForUpdateMock.mockResolvedValue(update);
    const { result } = renderHook(() => useVersionCheck());
    await waitFor(() => expect(result.current.desktopVersion).toBe("1.2.3"));

    let checkResult: Awaited<ReturnType<typeof result.current.checkForAppUpdate>> | undefined;
    await act(async () => {
      checkResult = await result.current.checkForAppUpdate({ manual: true });
    });

    expect(checkResult).toMatchObject({
      status: "update-available",
      release: { latest: "1.3.0", current: "1.2.3" },
    });
    expect(result.current.newRelease?.latest).toBe("1.3.0");
    expect(result.current.updateAvailable).toBe(update);
  });

  it("keeps automatic checks suppressed after remind later", async () => {
    sessionStorage.setItem("openkitsune_release_remind_later_session", "1.3.0");
    checkForUpdateMock.mockResolvedValue({
      version: "1.3.0",
      downloadAndInstall: vi.fn(),
    });
    const { result } = renderHook(() => useVersionCheck());
    await waitFor(() => expect(result.current.desktopVersion).toBe("1.2.3"));

    let checkResult: Awaited<ReturnType<typeof result.current.checkForAppUpdate>> | undefined;
    await act(async () => {
      checkResult = await result.current.checkForAppUpdate();
    });

    expect(checkResult?.status).toBe("suppressed");
    expect(result.current.newRelease).toBeNull();
  });

  it("returns an explicit up-to-date result", async () => {
    checkForUpdateMock.mockResolvedValue(null);
    const { result } = renderHook(() => useVersionCheck());
    await waitFor(() => expect(result.current.desktopVersion).toBe("1.2.3"));

    let checkResult: Awaited<ReturnType<typeof result.current.checkForAppUpdate>> | undefined;
    await act(async () => {
      checkResult = await result.current.checkForAppUpdate({ manual: true });
    });

    expect(checkResult).toEqual({ status: "up-to-date", current: "1.2.3" });
  });

  it("returns an explicit error when updater and fallback checks fail", async () => {
    checkForUpdateMock.mockRejectedValue(new Error("updater unavailable"));
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network unavailable"));
    const { result } = renderHook(() => useVersionCheck());
    await waitFor(() => expect(result.current.desktopVersion).toBe("1.2.3"));

    let checkResult: Awaited<ReturnType<typeof result.current.checkForAppUpdate>> | undefined;
    await act(async () => {
      checkResult = await result.current.checkForAppUpdate({ manual: true });
    });

    expect(checkResult).toEqual({ status: "error", error: "network unavailable" });
  });
});
