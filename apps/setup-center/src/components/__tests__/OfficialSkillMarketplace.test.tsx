import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import "../../i18n";
import i18n from "../../i18n";
import { safeFetch } from "../../providers";
import { openMarketplaceWithAccount } from "../../marketplace/open";
import { OfficialSkillMarketplace } from "../../views/OfficialSkillMarketplace";
import { SkillManager } from "../../views/SkillManager";

vi.mock("../../providers", () => ({ safeFetch: vi.fn() }));
vi.mock("../../platform", () => ({ IS_TAURI: false, invoke: vi.fn() }));
vi.mock("../../marketplace/open", () => ({
  openMarketplaceWithAccount: vi.fn(async () => {}), marketplaceOpenErrorKey: () => "topbar.openMarketplaceFailed",
}));

const resource = { id: "one", slug: "example-skill", name: "Official Example", publisher_name: "OpenKitsune", summary: "Example summary" };
const response = (items = [resource], total = items.length) => new Response(JSON.stringify({
  items, total, origin: "https://marketplace.openkitsune.cn", facets: { categories: [] },
}));
const props = { apiBaseUrl: "http://localhost:18900", desktopVersion: "1.27.42", visible: true, onSkillHub: vi.fn() };
const installedResponse = (skills: object[] = []) => new Response(JSON.stringify({ skills }));
const mockCatalog = (fetchCatalog: () => Promise<Response>) => {
  vi.mocked(safeFetch).mockImplementation(url => String(url).endsWith("/api/skills")
    ? Promise.resolve(installedResponse()) : fetchCatalog());
};

beforeEach(async () => {
  vi.clearAllMocks();
  vi.mocked(safeFetch).mockReset();
  localStorage.clear();
  window.history.replaceState(null, "", "#/skills");
  await i18n.changeLanguage("zh");
});

it("keeps installed as the default and loads official and SkillHub catalogs only on selection", async () => {
  vi.mocked(safeFetch).mockImplementation(async url => {
    if (String(url).includes("/api/marketplace/skills")) return response();
    if (String(url).includes("/api/skills/marketplace")) return new Response(JSON.stringify({ schemaVersion: 1, skills: [] }));
    if (String(url).endsWith("/api/skill-categories")) return new Response(JSON.stringify({ categories: [] }));
    return new Response(JSON.stringify({ skills: [] }));
  });
  render(<SkillManager venvDir="" currentWorkspaceId="default" envDraft={{}}
    onEnvChange={vi.fn()} onSaveEnvKeys={vi.fn()} serviceRunning apiBaseUrl={props.apiBaseUrl} desktopVersion={props.desktopVersion} />);
  expect(await screen.findByText(i18n.t("skills.noSkills"))).toBeInTheDocument();
  expect(vi.mocked(safeFetch).mock.calls.every(([url]) => !String(url).includes("marketplace"))).toBe(true);
  fireEvent.click(screen.getByRole("radio", { name: i18n.t("skills.officialMarket.title") }));
  expect(await screen.findByText(resource.name)).toBeInTheDocument();
  expect(window.location.hash).toBe("#/skills?source=official");
  expect(vi.mocked(safeFetch).mock.calls.some(([url]) => String(url).includes("/api/skills/marketplace"))).toBe(false);
  fireEvent.click(screen.getByRole("radio", { name: "SkillHub" }));
  await waitFor(() => expect(vi.mocked(safeFetch).mock.calls.some(([url]) => String(url).includes("/api/skills/marketplace"))).toBe(true));
  expect(screen.queryByText(resource.name)).not.toBeInTheDocument();
  await act(async () => {
    window.history.replaceState(null, "", "#/skills");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(screen.getByText(i18n.t("skills.noSkills"))).toBeInTheDocument();
});

it("opens the exact resource through the account-aware marketplace flow", async () => {
  mockCatalog(async () => response());
  render(<OfficialSkillMarketplace {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: i18n.t("skills.officialMarket.viewResource") }));
  expect(openMarketplaceWithAccount).toHaveBeenCalledWith("1.27.42", props.apiBaseUrl,
    "/resources/example-skill", "https://marketplace.openkitsune.cn");
  expect(vi.mocked(safeFetch).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
});

it("prefers the official installed name over auto-translation and searches by it", async () => {
  vi.mocked(safeFetch).mockImplementation(async url => String(url).endsWith("/api/skills")
    ? installedResponse([{ skill_id: "anki-connect", name: "anki-connect", description: "Cards",
      name_i18n: { zh: "Anki连接" }, marketplace_name: "Anki 记忆卡片助手", system: false, enabled: true }])
    : new Response(JSON.stringify({ categories: [] })));
  render(<SkillManager venvDir="" currentWorkspaceId="default" envDraft={{}}
    onEnvChange={vi.fn()} onSaveEnvKeys={vi.fn()} serviceRunning apiBaseUrl={props.apiBaseUrl} desktopVersion={props.desktopVersion} />);
  const filter = await screen.findByPlaceholderText(i18n.t("skills.filterPlaceholder"));
  fireEvent.click(screen.getByRole("checkbox", { name: i18n.t("skills.category.groupView") }));
  fireEvent.change(filter, { target: { value: "记忆卡片助手" } });
  expect(await screen.findByText("Anki 记忆卡片助手")).toBeInTheDocument();
  expect(screen.queryByText("Anki连接")).not.toBeInTheDocument();
  expect(screen.getByText("anki-connect")).toBeInTheDocument();
});

it("paginates and resets pagination when searching", async () => {
  mockCatalog(async () => response([resource], 30));
  render(<OfficialSkillMarketplace {...props} />);
  await screen.findByText(resource.name);
  fireEvent.click(screen.getByRole("button", { name: i18n.t("skills.officialMarket.next") }));
  await waitFor(() => expect(String(vi.mocked(safeFetch).mock.lastCall?.[0])).toContain("offset=24"));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "new query" } });
  await waitFor(() => expect(String(vi.mocked(safeFetch).mock.lastCall?.[0])).toContain("q=new+query"));
  expect(String(vi.mocked(safeFetch).mock.lastCall?.[0])).toContain("offset=0");
});

it("ignores late search results even when the transport does not honor abort", async () => {
  let resolveOld!: (value: Response) => void;
  const fetchCatalog = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockImplementationOnce(async () => response([{ ...resource, name: "Newest result" }]));
  mockCatalog(fetchCatalog);
  render(<OfficialSkillMarketplace {...props} />);
  await waitFor(() => expect(fetchCatalog).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "newest" } });
  await screen.findByText("Newest result");
  await act(async () => { resolveOld(response([{ ...resource, name: "Stale result" }])); });
  expect(screen.queryByText("Stale result")).not.toBeInTheDocument();
  expect(screen.getByText("Newest result")).toBeInTheDocument();
});

it("shows failure separately from empty results and switches providers only when requested", async () => {
  mockCatalog(vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response([])));
  render(<OfficialSkillMarketplace {...props} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("skills.officialMarket.unavailable"));
  expect(screen.queryByText(i18n.t("skills.officialMarket.empty"))).not.toBeInTheDocument();
  expect(props.onSkillHub).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: i18n.t("skills.officialMarket.retry") }));
  await screen.findByText(i18n.t("skills.officialMarket.empty"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("skills.officialMarket.searchSkillHub") }));
  expect(props.onSkillHub).toHaveBeenCalledWith("");
});

it("marks a disabled installed resource by ID, ignores same-name skills, and updates after uninstall", async () => {
  let skills: object[] = [{ name: resource.name, skill_id: resource.slug, enabled: true, source_url: "skillhub:example-skill" }];
  vi.mocked(safeFetch).mockImplementation(async url => String(url).endsWith("/api/skills")
    ? installedResponse(skills) : response());
  render(<OfficialSkillMarketplace {...props} />);
  expect(await screen.findByRole("button", { name: "获取" })).toBeEnabled();
  skills = [{ name: "Different local name", marketplace_resource_id: resource.id, enabled: false }];
  act(() => { window.dispatchEvent(new CustomEvent("openkitsune:skills-changed", { detail: { action: "install" } })); });
  const installed = await screen.findByRole("button", { name: "已安装" });
  expect(installed).toBeDisabled();
  fireEvent.click(installed);
  expect(openMarketplaceWithAccount).not.toHaveBeenCalled();
  skills = [];
  act(() => { window.dispatchEvent(new CustomEvent("openkitsune:skills-changed", { detail: { action: "uninstall" } })); });
  expect(await screen.findByRole("button", { name: "获取" })).toBeEnabled();
});

it("recognizes prior installs on entry and refreshes when returning from the market", async () => {
  let skills: object[] = [{ marketplace_resource_id: resource.id }];
  vi.mocked(safeFetch).mockImplementation(async url => String(url).endsWith("/api/skills")
    ? installedResponse(skills) : response());
  const { rerender } = render(<OfficialSkillMarketplace {...props} />);
  expect(await screen.findByRole("button", { name: "已安装" })).toBeDisabled();
  skills = [];
  act(() => { window.dispatchEvent(new Event("focus")); });
  expect(await screen.findByRole("button", { name: "获取" })).toBeEnabled();
  rerender(<OfficialSkillMarketplace {...props} visible={false} />);
  skills = [{ marketplace_resource_id: resource.id }];
  rerender(<OfficialSkillMarketplace {...props} />);
  expect(await screen.findByRole("button", { name: "已安装" })).toBeDisabled();
});

it("ignores stale installation reads and preserves installed state on read failures", async () => {
  let resolveOld!: (value: Response) => void;
  const readInstalled = vi.fn().mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockResolvedValueOnce(installedResponse([{ marketplace_resource_id: resource.id }]))
    .mockRejectedValueOnce(new Error("offline"));
  vi.mocked(safeFetch).mockImplementation(url => String(url).endsWith("/api/skills") ? readInstalled() : Promise.resolve(response()));
  render(<OfficialSkillMarketplace {...props} />);
  await screen.findByText(resource.name);
  act(() => { window.dispatchEvent(new Event("openkitsune:skills-changed")); });
  expect(await screen.findByRole("button", { name: "已安装" })).toBeDisabled();
  await act(async () => { resolveOld(installedResponse()); });
  expect(screen.getByRole("button", { name: "已安装" })).toBeDisabled();
  act(() => { window.dispatchEvent(new Event("focus")); });
  await waitFor(() => expect(readInstalled).toHaveBeenCalledTimes(3));
  expect(screen.getByRole("button", { name: "已安装" })).toBeDisabled();
});
