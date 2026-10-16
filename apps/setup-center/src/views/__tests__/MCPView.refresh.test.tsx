import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import "../../i18n";
import i18n from "../../i18n";
import { safeFetch } from "../../providers";
import { MCPView } from "../MCPView";

vi.mock("../../providers", () => ({ safeFetch: vi.fn() }));

const props = { serviceRunning: true, envDraft: {}, onEnvChange: vi.fn(), onSaveEnvKeys: vi.fn() };
const server = {
  name: "new-mcp", description: "New marketplace server", transport: "stdio", command: "uv",
  url: "", connected: true, tools: [], tool_count: 5, catalog_tool_count: 5,
  source: "workspace", removable: true, enabled: true, auto_connect: false,
  has_instructions: false, config_schema: [], config_status: {}, config_complete: true,
};
const response = (servers: object[]) => new Response(JSON.stringify({ servers }));

beforeEach(async () => {
  vi.mocked(safeFetch).mockReset();
  await i18n.changeLanguage("zh");
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("detects installation in another window without replacing the page with a loading state", async () => {
  vi.useFakeTimers();
  vi.mocked(safeFetch).mockImplementation(async () => response([]));
  const view = render(<MCPView {...props} />);
  await act(async () => {});
  expect(screen.getByText(i18n.t("mcp.noServers"))).toBeInTheDocument();
  vi.mocked(safeFetch).mockImplementation(async () => response([server]));
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(screen.getByText("New marketplace server")).toBeInTheDocument();
  expect(safeFetch).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: i18n.t("common.refresh") })).not.toBeDisabled();
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(safeFetch).toHaveBeenCalledTimes(2);
});

it("pauses hidden-page polling and catches up immediately on returning to the page", async () => {
  vi.useFakeTimers();
  vi.mocked(safeFetch).mockImplementation(async () => response([]));
  const view = render(<MCPView {...props} />);
  await act(async () => {});
  expect(screen.getByText(i18n.t("mcp.noServers"))).toBeInTheDocument();
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
  expect(safeFetch).toHaveBeenCalledTimes(1);
  vi.mocked(safeFetch).mockImplementation(async () => response([server]));
  visibility.mockReturnValue("visible");
  await act(async () => { fireEvent(document, new Event("visibilitychange")); });
  expect(screen.getByText("New marketplace server")).toBeInTheDocument();
  view.rerender(<MCPView {...props} serviceRunning={false} />);
  await act(async () => {
    window.dispatchEvent(new Event("openkitsune:mcp-changed"));
    await vi.advanceTimersByTimeAsync(6000);
  });
  expect(safeFetch).toHaveBeenCalledTimes(2);
});

it("does not let a slow pre-install response overwrite the refreshed MCP list", async () => {
  let finishInitial!: (value: Response) => void;
  vi.mocked(safeFetch)
    .mockImplementationOnce(() => new Promise(resolve => { finishInitial = resolve; }))
    .mockImplementation(async () => response([server]));
  render(<MCPView {...props} />);
  await act(async () => { window.dispatchEvent(new Event("openkitsune:mcp-changed")); });
  expect(screen.getByText("New marketplace server")).toBeInTheDocument();
  await act(async () => { finishInitial(response([])); });
  expect(screen.getByText("New marketplace server")).toBeInTheDocument();
});
