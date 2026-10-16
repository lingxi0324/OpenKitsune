import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import "../../i18n";
import i18n from "../../i18n";
import { safeFetch, safeFetchResponse } from "../../providers";
import { SkillManager } from "../../views/SkillManager";
import { MCPView } from "../../views/MCPView";
import { MarketplaceInstallDialog } from "../MarketplaceInstallDialog";

vi.mock("../../platform", () => ({
  IS_TAURI: true,
  IS_CAPACITOR: false,
  getCurrentDeepLinks: vi.fn(async () => [
    `openkitsune://marketplace/install?token=${"a".repeat(64)}&endpoint=https://marketplace.openkitsune.cn`,
  ]),
  onDeepLinkOpen: vi.fn(async () => () => {}),
}));
vi.mock("../../marketplace/open", () => ({
  desktopAccountHeaders: vi.fn(async () => ({})),
  openMarketplaceWithAccount: vi.fn(),
}));
vi.mock("../../providers", () => ({ safeFetchResponse: vi.fn(), safeFetch: vi.fn() }));

const job = {
  id: "test-job", status: "installed", resource_type: "skill", resource_name: "Demo",
  version: "1.0.0", progress: 100, permissions: [], dependencies: [],
};

beforeEach(async () => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(safeFetchResponse).mockReset();
  vi.mocked(safeFetch).mockReset();
  await i18n.changeLanguage("zh");
});

it("refreshes the mounted skill category from 9 to 10 after polling succeeds without WebSocket", async () => {
  let installed = false;
  const original = Array.from({ length: 9 }, (_, index) => ({
    skill_id: `writer-${index}`, name: `Writer ${index}`, category: "内容创作",
    enabled: true, system: false,
  }));
  vi.mocked(safeFetch).mockImplementation(async (url) => {
    if (String(url).endsWith("/api/skills")) return new Response(JSON.stringify({
      skills: installed ? [...original, {
        skill_id: "tailored-resume-generator", name: "岗位定制简历",
        category: "内容创作", enabled: true, system: false,
      }] : original,
    }));
    if (String(url).endsWith("/api/skill-categories")) return new Response(JSON.stringify({
      categories: [{ name: "内容创作", total: installed ? 10 : 9, enabled: installed ? 10 : 9 }],
    }));
    throw new Error(`Unexpected URL: ${url}`);
  });
  vi.mocked(safeFetchResponse).mockImplementation(async (url) => {
    const status = String(url).endsWith("/prepare") ? "ready"
      : String(url).endsWith("/confirm") ? "installing" : "installed";
    installed = status === "installed";
    return new Response(JSON.stringify({ data: { ...job, status, skill_enabled: true } }));
  });
  render(<>
    <SkillManager venvDir="" currentWorkspaceId="default" envDraft={{}}
      onEnvChange={vi.fn()} onSaveEnvKeys={vi.fn()} serviceRunning apiBaseUrl="http://localhost:18900" />
    <MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />
  </>);
  expect(await screen.findByText("9/9")).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "确认安装" }));
  expect(await screen.findByText("10/10")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "完成" }));
  fireEvent.click(screen.getByRole("button", { name: /内容创作/ }));
  expect(await screen.findByText("岗位定制简历")).toBeInTheDocument();
  expect(vi.mocked(safeFetch).mock.calls.filter(([url]) => String(url).endsWith("/api/skill-categories"))).toHaveLength(2);
});

it("notifies only once for an already completed skill job", async () => {
  vi.mocked(safeFetchResponse).mockImplementation(async () => new Response(JSON.stringify({ data: job })));
  const listener = vi.fn();
  window.addEventListener("openkitsune:skills-changed", listener);
  try {
    const view = render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
    await waitFor(() => expect(listener).toHaveBeenCalledTimes(1));
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ action: "install" });
    view.rerender(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.41" />);
    await screen.findByText(/请在技能管理中确认启用状态/);
    expect(listener).toHaveBeenCalledTimes(1);
  } finally {
    window.removeEventListener("openkitsune:skills-changed", listener);
  }
});

it("refreshes an already mounted MCP page immediately after marketplace installation", async () => {
  let installed = false;
  vi.mocked(safeFetch).mockImplementation(async () => new Response(JSON.stringify({
    servers: installed ? [{
      name: "railway-12306-mcp", description: "火车出行查询", transport: "stdio",
      command: "npx", url: "", connected: true, tools: [], tool_count: 8,
      catalog_tool_count: 8, source: "workspace", enabled: true, auto_connect: false,
      removable: true, has_instructions: false, config_schema: [], config_status: {}, config_complete: true,
    }] : [],
  })));
  vi.mocked(safeFetchResponse).mockImplementation(async url => {
    const status = String(url).endsWith("/prepare") ? "ready" : "installed";
    installed = status === "installed";
    return new Response(JSON.stringify({ data: { ...job, resource_type: "mcp", status } }));
  });
  const listener = vi.fn();
  window.addEventListener("openkitsune:mcp-changed", listener);
  try {
    render(<>
      <MCPView serviceRunning envDraft={{}} onEnvChange={vi.fn()} onSaveEnvKeys={vi.fn()} />
      <MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />
    </>);
    fireEvent.click(await screen.findByRole("button", { name: "确认安装" }));
    expect(await screen.findByText("火车出行查询")).toBeInTheDocument();
    expect(listener).toHaveBeenCalledTimes(1);
    expect(safeFetch).toHaveBeenCalledTimes(2);
  } finally {
    window.removeEventListener("openkitsune:mcp-changed", listener);
  }
});

it.each([
  ["ready", "skill"], ["failed", "skill"], ["cancelled", "skill"],
  ["installed", "plugin"], ["installed", "mcp"],
])("does not announce a skill change for %s %s", async (status, resource_type) => {
  vi.mocked(safeFetchResponse).mockResolvedValue(new Response(JSON.stringify({
    data: { ...job, status, resource_type },
  })));
  const listener = vi.fn();
  window.addEventListener("openkitsune:skills-changed", listener);
  try {
    render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
    await screen.findByText("Demo · v1.0.0");
    expect(listener).not.toHaveBeenCalled();
  } finally {
    window.removeEventListener("openkitsune:skills-changed", listener);
  }
});

it.each([
  [true, false, /技能已安装并启用，下一条消息即可使用/],
  [false, false, /保留了原来的禁用状态/],
  [true, true, /尚未完成运行时加载/],
  [undefined, false, /请在技能管理中确认启用状态/],
])("explains the installed skill state (%s, restart %s)", async (enabled, restart, message) => {
  vi.mocked(safeFetchResponse).mockResolvedValue(new Response(JSON.stringify({
    data: { ...job, skill_enabled: enabled, restart_required: restart },
  })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByText(message)).toBeInTheDocument();
});

it("explains activation before confirmation and displays the resulting enabled state", async () => {
  vi.mocked(safeFetchResponse)
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: { ...job, status: "ready" } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: { ...job, skill_enabled: true } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByText(/首次安装的技能将自动启用/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "确认安装" }));
  expect(await screen.findByText(/技能已安装并启用，下一条消息即可使用/)).toBeInTheDocument();
});

it("shows the installed version without offering a duplicate install", async () => {
  vi.mocked(safeFetchResponse).mockResolvedValue(new Response(JSON.stringify({ data: {
    ...job, install_action: "already_installed", already_installed: true, installed_version: "1.0.0",
  } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByText(/已安装相同版本 v1.0.0/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认安装" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认升级" })).not.toBeInTheDocument();
  expect(safeFetchResponse).toHaveBeenCalledTimes(1);
});

it("asks for upgrade confirmation and shows both versions before submitting", async () => {
  vi.mocked(safeFetchResponse)
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: {
      ...job, status: "ready", install_action: "upgrade", installed_version: "1.0.0", version: "2.0.0",
    } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: { ...job, version: "2.0.0" } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByText("已安装 v1.0.0，是否升级到 v2.0.0？")).toBeInTheDocument();
  expect(screen.getByText("Demo · v1.0.0 → v2.0.0")).toBeInTheDocument();
  expect(safeFetchResponse).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "确认升级" }));
  await screen.findByText(/请在技能管理中确认启用状态/);
  expect(safeFetchResponse).toHaveBeenCalledTimes(2);
});

it("does not offer to replace a newer installed version", async () => {
  vi.mocked(safeFetchResponse).mockResolvedValue(new Response(JSON.stringify({ data: {
    ...job, status: "ready", install_action: "downgrade", installed_version: "2.0.0",
  } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  await screen.findByText(/已安装较新版本 v2.0.0/);
  expect(screen.queryByRole("button", { name: "确认安装" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认升级" })).not.toBeInTheDocument();
});

it("requires a clearly labelled replacement for an unknown existing installation", async () => {
  vi.mocked(safeFetchResponse).mockResolvedValue(new Response(JSON.stringify({ data: {
    ...job, status: "ready", install_action: "replace",
  } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  await screen.findByText(/无法确认其来源或版本/);
  expect(screen.getByRole("button", { name: "确认覆盖安装" })).toBeInTheDocument();
});

it("explains an already staged plugin update", async () => {
  vi.mocked(safeFetchResponse).mockImplementation(async url => new Response(JSON.stringify({ data:
    String(url).endsWith("/list") ? { plugins: [{ id: "demo", status: "loaded", pending_update_revision: "next" }] } : {
      ...job, resource_type: "plugin", resource_slug: "demo", already_installed: true, installed_pending_restart: true,
    },
  })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByText(/请先应用更新，再确认新版本需要的权限/)).toBeInTheDocument();
});

it("shows the dependency failure cause, stage and recovery hint", async () => {
  vi.mocked(safeFetchResponse).mockImplementation(async () => new Response(JSON.stringify({ data: {
    ...job, status: "failed", resource_type: "plugin",
    failure_code: "marketplace_plugin_install_failed", failure_reason: "dependency_network",
    failure_stage: "dependency_downloading", current_dependency: "jinja2",
    failure_detail: "ERROR: IncompleteRead(428516 bytes read, 46522 more expected)",
  } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("自动重试后仍未完成");
  expect(screen.getByText(/最后处理的依赖：jinja2/)).toBeInTheDocument();
  expect(screen.getByText(/失败阶段：/)).toHaveTextContent("下载");
  expect(screen.getByText(/IncompleteRead\(428516/)).toBeInTheDocument();
  expect(screen.getByText(/请检查网络、代理或 Python 镜像源连接/)).toBeInTheDocument();
});

it("handles older failed jobs without detailed diagnostics", async () => {
  vi.mocked(safeFetchResponse).mockImplementation(async () => new Response(JSON.stringify({ data: {
    ...job, status: "failed", failure_code: "marketplace_plugin_install_failed",
  } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("插件安装失败");
  expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
});

it("requires confirmation again if the backend returns a changed preview", async () => {
  vi.mocked(safeFetchResponse)
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: { ...job, status: "ready" } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ data: {
      ...job, status: "ready", install_action: "upgrade", installed_version: "0.9.0",
    } })));
  render(<MarketplaceInstallDialog apiBaseUrl="http://localhost:18900" desktopVersion="1.27.40" />);
  fireEvent.click(await screen.findByRole("button", { name: "确认安装" }));
  expect(await screen.findByText(/本地安装状态已变化/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认升级" })).toBeInTheDocument();
  expect(safeFetchResponse).toHaveBeenCalledTimes(2);
});
