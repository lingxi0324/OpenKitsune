import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import { safeFetch } from "../../providers";
import { invoke, saveFileDialog } from "../../platform";
import { notifyError, notifySuccess } from "../../utils/notify";
import { AdvancedView, type AdvancedViewProps } from "../AdvancedView";
import { TooltipProvider } from "../../components/ui/tooltip";

const platform = vi.hoisted(() => ({ tauri: false }));
vi.mock("../../providers", () => ({ safeFetch: vi.fn() }));
vi.mock("../../platform", () => ({
  get IS_TAURI() { return platform.tauri; },
  invoke: vi.fn(async () => ({})),
  saveFileDialog: vi.fn(),
}));
vi.mock("../../components/WebPasswordManager", () => ({ WebPasswordManager: () => null }));
vi.mock("../../utils/notify", () => ({
  notifyError: vi.fn(), notifySuccess: vi.fn(),
  notifyLoading: vi.fn(() => "loading"), dismissLoading: vi.fn(),
}));

const props: AdvancedViewProps = {
  envDraft: {}, setEnvDraft: vi.fn(), busy: null, workspaces: [],
  currentWorkspaceId: null, serviceStatus: { running: true, pid: null, pidFile: "" },
  dataMode: "local", info: null, storeVisible: false, setStoreVisible: vi.fn(),
  desktopVersion: "test", endpointSummary: [], shouldUseHttpApi: () => true,
  httpApiBase: () => "http://backend", backendBootPhase: "running",
  onOpenRuntimeEnvironment: vi.fn(), askConfirm: vi.fn(), refreshAll: vi.fn(),
  restartService: vi.fn(), setView: vi.fn(),
};

beforeEach(async () => {
  vi.clearAllMocks();
  platform.tauri = false;
  vi.mocked(safeFetch).mockImplementation(async () => new Response("{}"));
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:diagnostic");
    static revokeObjectURL = vi.fn();
  });
  await i18n.changeLanguage("en");
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

it("downloads in web mode without a desktop workspace and blocks repeat clicks", async () => {
  vi.useFakeTimers();
  let finish!: (response: Response) => void;
  vi.mocked(safeFetch).mockImplementation(async (url) => {
    if (url.endsWith("/api/diagnostics/export")) return new Promise(resolve => { finish = resolve; });
    return new Response("{}");
  });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toMatch(/^openkitsune-diagnostic-\d+\.zip$/);
    expect(this.href).toBe("blob:diagnostic");
  });
  render(<AdvancedView {...props} />, { wrapper: TooltipProvider });
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: "Export Diagnostics" }));
  const packing = screen.getByRole("button", { name: i18n.t("adv.opsLogExporting") });
  expect(packing).toBeDisabled();
  fireEvent.click(packing);
  await act(async () => { finish(new Response("zip", { headers: { "Content-Type": "application/zip" } })); });
  expect(click).toHaveBeenCalledTimes(1);
  expect(vi.mocked(safeFetch).mock.calls.filter(([url]) => url.endsWith("/api/diagnostics/export"))).toHaveLength(1);
  expect(saveFileDialog).not.toHaveBeenCalled();
  expect(invoke).not.toHaveBeenCalled();
  expect(notifySuccess).toHaveBeenCalledWith(i18n.t("adv.opsLogDownloadStarted"));
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:diagnostic");
});

it("shows download errors and enables retry", async () => {
  vi.mocked(safeFetch).mockImplementation(async (url) => {
    if (url.endsWith("/api/diagnostics/export")) throw new Error("Package too large");
    return new Response("{}");
  });
  render(<AdvancedView {...props} />, { wrapper: TooltipProvider });
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Export Diagnostics" })); });
  expect(notifyError).toHaveBeenCalledWith("Error: Package too large");
  expect(screen.getByRole("button", { name: "Export Diagnostics" })).not.toBeDisabled();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("retains native export when the desktop backend is stopped", async () => {
  platform.tauri = true;
  vi.mocked(saveFileDialog).mockResolvedValue("C:/Downloads/diagnostic.zip");
  vi.mocked(invoke).mockImplementation(async (command) => (
    command === "export_diagnostic_bundle" ? "C:/Downloads/diagnostic.zip" : {}
  ) as never);
  render(<AdvancedView {...props} currentWorkspaceId="default" serviceStatus={null} shouldUseHttpApi={() => false} />, { wrapper: TooltipProvider });
  await act(async () => {});
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Export Diagnostics" })); });
  expect(invoke).toHaveBeenCalledWith("export_diagnostic_bundle", {
    workspaceId: "default", systemInfoJson: null, destPath: "C:/Downloads/diagnostic.zip",
  });
  expect(safeFetch).not.toHaveBeenCalled();
});
