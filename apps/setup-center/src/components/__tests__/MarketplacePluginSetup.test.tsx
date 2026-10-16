import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import "../../i18n";
import i18n from "../../i18n";
import { safeFetch, safeFetchResponse } from "../../providers";
import { MarketplaceInstallDialog } from "../MarketplaceInstallDialog";
import { MarketplacePluginSetup } from "../MarketplacePluginSetup";
import PluginManagerView from "../../views/PluginManagerView";

vi.mock("../../providers", () => ({ safeFetchResponse: vi.fn(), safeFetch: vi.fn() }));
vi.mock("../../platform", () => ({
  IS_TAURI: true,
  IS_CAPACITOR: false,
  getCurrentDeepLinks: vi.fn(async () => [
    `openkitsune://marketplace/install?token=${"b".repeat(64)}&endpoint=https://marketplace.openkitsune.cn`,
  ]),
  onDeepLinkOpen: vi.fn(async () => () => {}),
}));
vi.mock("../../marketplace/open", () => ({ desktopAccountHeaders: vi.fn(async () => ({})), openMarketplaceWithAccount: vi.fn() }));

let plugin: Record<string, unknown>;
let installed: boolean;
let grantFails: boolean;
let loadFails: boolean;
const base = "http://localhost:18900";
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const mutations = () => vi.mocked(safeFetchResponse).mock.calls.filter(([, init]) => init?.method === "POST");

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("zh");
  installed = true;
  grantFails = loadFails = false;
  plugin = { id: "word-maker", name: "Word Maker", version: "1.0.0", category: "tool", type: "tool", status: "loaded", enabled: true, pending_permissions: ["routes.register", "brain.access", "assets.publish"] };
  vi.mocked(safeFetch).mockImplementation(async url => response(String(url).endsWith("/dev-mode") ? { data: { mode: "off" } } : { data: { plugins: installed ? [plugin] : [], failed: {} } }));
  vi.mocked(safeFetchResponse).mockImplementation(async (url, init) => {
    if (String(url).endsWith("/api/plugins/list")) return response({ data: { plugins: installed ? [plugin] : [] } });
    if (String(url).endsWith("/permissions/grant")) {
      if (grantFails) return response({ ok: false, error: "grant unavailable" }, 503);
      plugin = { ...plugin, pending_permissions: [], status: loadFails ? "failed" : "loaded", error: loadFails ? "plugin load failed" : undefined };
      return response({ ok: true });
    }
    if (String(url).endsWith("/enable")) {
      plugin = { ...plugin, enabled: true, status: "loaded" };
      return response({ ok: true });
    }
    if (String(url).endsWith("/reload")) {
      plugin = { ...plugin, pending_update_revision: "", status: "loaded", pending_permissions: ["assets.publish"] };
      return response({ ok: true });
    }
    throw new Error(`Unexpected request: ${url} ${init?.method}`);
  });
});

function setup() {
  return render(<MarketplacePluginSetup apiBaseUrl={base} pluginId="word-maker" onBusyChange={vi.fn()} onClose={vi.fn()} />);
}

it("continues permission setup inside the completed marketplace install and refreshes plugin management", async () => {
  installed = false;
  const fetchPlugin = vi.mocked(safeFetchResponse).getMockImplementation()!;
  vi.mocked(safeFetchResponse).mockImplementation(async (url, init) => {
    if (String(url).includes("/api/marketplace/")) {
      installed = !String(url).endsWith("/prepare");
      return response({ data: { id: "job", resource_name: "Word", resource_type: "plugin", plugin_id: "word-maker", version: "1.0.0", status: installed ? "installed" : "ready", permissions: [], dependencies: [], progress: installed ? 100 : 0 } });
    }
    return fetchPlugin(url, init);
  });
  render(<><PluginManagerView visible httpApiBase={() => base} desktopVersion="1.27.40" /><MarketplaceInstallDialog apiBaseUrl={base} desktopVersion="1.27.40" /></>);
  fireEvent.click(await screen.findByRole("button", { name: "确认安装" }));
  expect((await screen.findAllByText("Word Maker")).length).toBeGreaterThan(0);
  const grant = await screen.findByRole("button", { name: "授权并继续" });
  expect(mutations().filter(([url]) => String(url).includes("/permissions/grant"))).toHaveLength(0);
  fireEvent.click(grant);
  expect(await screen.findByText("插件权限已就绪，已成功加载。")).toBeInTheDocument();
  const [, init] = mutations().find(([url]) => String(url).includes("/permissions/grant"))!;
  expect(JSON.parse(String(init?.body))).toEqual({ permissions: ["routes.register", "brain.access", "assets.publish"], reload: true });
  await waitFor(() => expect(vi.mocked(safeFetch).mock.calls.filter(([url]) => String(url).endsWith("/list")).length).toBeGreaterThanOrEqual(3));
});

it("finishes without a permission action when all permissions are already granted", async () => {
  plugin.pending_permissions = [];
  setup();
  expect(await screen.findByRole("button", { name: "完成" })).toBeInTheDocument();
  expect(mutations()).toHaveLength(0);
});

it("does not grant permissions when setup is deferred", async () => {
  const close = vi.fn();
  render(<MarketplacePluginSetup apiBaseUrl={base} pluginId="word-maker" onBusyChange={vi.fn()} onClose={close} />);
  fireEvent.click(await screen.findByRole("button", { name: "稍后处理" }));
  expect(close).toHaveBeenCalledOnce();
  expect(mutations()).toHaveLength(0);
});

it("keeps failed grants retryable and never displays success", async () => {
  grantFails = true;
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "授权并继续" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("grant unavailable");
  expect(screen.queryByRole("button", { name: "完成" })).not.toBeInTheDocument();
  grantFails = false;
  fireEvent.click(screen.getByRole("button", { name: "重新检查" }));
  fireEvent.click(await screen.findByRole("button", { name: "授权并继续" }));
  expect(await screen.findByRole("button", { name: "完成" })).toBeInTheDocument();
});

it("checks actual runtime load failure even when grant returned HTTP 200", async () => {
  loadFails = true;
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "授权并继续" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("plugin load failed");
  expect(screen.getByRole("button", { name: "加载插件" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "完成" })).not.toBeInTheDocument();
});

it("preserves disabled state through granting until the user explicitly enables the plugin", async () => {
  plugin.enabled = false;
  plugin.status = "disabled";
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "授权并继续" }));
  const enable = await screen.findByRole("button", { name: "启用插件" });
  expect(JSON.parse(String(mutations()[0][1]?.body)).reload).toBe(false);
  fireEvent.click(enable);
  expect(await screen.findByRole("button", { name: "完成" })).toBeInTheDocument();
});

it("applies a staged upgrade before displaying and granting the new manifest's permissions", async () => {
  plugin.pending_update_revision = "next-version";
  plugin.pending_permissions = ["memory.replace"];
  setup();
  const apply = await screen.findByRole("button", { name: "应用更新并继续" });
  expect(screen.queryByText("memory.replace")).not.toBeInTheDocument();
  fireEvent.click(apply);
  expect(await screen.findByText("assets.publish")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "授权并继续" }));
  expect(await screen.findByRole("button", { name: "完成" })).toBeInTheDocument();
  expect(JSON.parse(String(mutations()[1][1]?.body)).permissions).toEqual(["assets.publish"]);
});

it("automatically refreshes a visible plugin page after an installation in another window", async () => {
  installed = false;
  vi.useFakeTimers();
  try {
    const view = render(<PluginManagerView visible httpApiBase={() => base} desktopVersion="1.27.40" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.queryByText("Word Maker")).not.toBeInTheDocument();
    installed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getAllByText("Word Maker").length).toBeGreaterThan(0);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    const count = vi.mocked(safeFetch).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(vi.mocked(safeFetch).mock.calls).toHaveLength(count);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    view.unmount();
    await vi.advanceTimersByTimeAsync(9000);
    expect(vi.mocked(safeFetch).mock.calls).toHaveLength(count);
  } finally {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    vi.useRealTimers();
  }
});

it("requires an explicit enable choice before applying an update to a disabled plugin", async () => {
  plugin.enabled = false;
  plugin.pending_update_revision = "next";
  setup();
  const apply = await screen.findByRole("button", { name: "启用并应用更新" });
  expect(mutations()).toHaveLength(0);
  fireEvent.click(apply);
  await screen.findByRole("button", { name: "授权并继续" });
  expect(mutations().map(([url]) => String(url).split("/").pop())).toEqual(["enable", "reload"]);
});

it("keeps the dialog open and blocks duplicate grants while loading takes time", async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const fetchPlugin = vi.mocked(safeFetchResponse).getMockImplementation()!;
  vi.mocked(safeFetchResponse).mockImplementation(async (url, init) => {
    if (String(url).endsWith("/permissions/grant")) await gate;
    return fetchPlugin(url, init);
  });
  const close = vi.fn();
  render(<MarketplacePluginSetup apiBaseUrl={base} pluginId="word-maker" onBusyChange={vi.fn()} onClose={close} />);
  fireEvent.click(await screen.findByRole("button", { name: "授权并继续" }));
  const later = screen.getByRole("button", { name: "稍后处理" });
  expect(later).toBeDisabled();
  fireEvent.click(later);
  expect(close).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "授权并继续" })).not.toBeInTheDocument();
  await act(async () => { finish(); });
  expect(await screen.findByRole("button", { name: "完成" })).toBeInTheDocument();
  expect(mutations()).toHaveLength(1);
});
