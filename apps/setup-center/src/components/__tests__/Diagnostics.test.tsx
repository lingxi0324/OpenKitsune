import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import { safeFetch } from "../../providers";
import { CacheMaintenancePanel } from "../CacheMaintenancePanel";
import { Section } from "../Section";
import { LinkDiagnosticsPanel } from "../LinkDiagnosticsPanel";
import { SourceStrip } from "../../views/chat/components/SourceStrip";
import { SkillConflictsPanel, useSkillConflicts } from "../SkillConflictsPanel";

vi.mock("../../providers", () => ({ safeFetch: vi.fn() }));
const base = () => "http://localhost:18900";
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
beforeEach(async () => {
  vi.resetAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  await i18n.changeLanguage("zh");
});
afterEach(() => { cleanup(); HTMLElement.prototype.scrollIntoView = originalScrollIntoView; });

it("does not request diagnostics while offline", () => {
  render(<LinkDiagnosticsPanel httpApiBase={base} serviceRunning={false} />);
  expect(screen.getByRole("button")).toBeDisabled();
  expect(safeFetch).not.toHaveBeenCalled();
});

it("keeps loaded records and expanded details when the section is collapsed", async () => {
  vi.mocked(safeFetch).mockResolvedValue(json({ requested_url: "https://a.example", status: "error" }));
  const { container } = render(<Section title="diagnostics"><LinkDiagnosticsPanel httpApiBase={base} serviceRunning /></Section>);
  fireEvent.click(screen.getByText("diagnostics"));
  expect(safeFetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "加载读取记录" }));
  await screen.findAllByText("https://a.example");
  fireEvent.click(screen.getByText("技术详情"));
  fireEvent.click(screen.getByText("diagnostics"));
  fireEvent.click(screen.getByText("diagnostics"));
  expect(container.querySelectorAll("details[open]")).toHaveLength(2);
  expect(safeFetch).toHaveBeenCalledTimes(1);
});

it("shows a load error instead of a misleading empty diagnosis", async () => {
  vi.mocked(safeFetch).mockResolvedValue(json({}, 503));
  render(<LinkDiagnosticsPanel httpApiBase={base} serviceRunning />);
  fireEvent.click(screen.getByRole("button"));
  expect(await screen.findByRole("alert")).toHaveTextContent("503");
  expect(screen.queryByText("尚无网页读取记录")).toBeNull();
});

it("requires an explicit runtime selection without any link records and does not retarget after refresh", async () => {
  let targets = [{ conversation_id: "a/b", profile_id: "writer", conversation_title: "Link reading", profile_name: "Writer" }];
  vi.mocked(safeFetch).mockImplementation(async url => String(url).includes("clear-session")
    ? json({ ok: true, cleared: { web_fetch: true } }) : json({ targets }));
  render(<CacheMaintenancePanel httpApiBase={base} serviceRunning />);
  fireEvent.click(screen.getByRole("button", { name: "加载运行实例" }));
  await screen.findByRole("combobox");
  expect(screen.getByRole("button", { name: "清理运行时缓存" })).toBeDisabled();
  fireEvent.click(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByRole("option", { name: "Link reading · Writer" }));
  fireEvent.click(screen.getByRole("button", { name: "清理运行时缓存" }));
  await waitFor(() => expect(safeFetch).toHaveBeenCalledWith(expect.stringContaining("conversation_id=a%2Fb&profile_id=writer"), { method: "POST" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新运行实例" })).toBeEnabled());
  targets = [{ conversation_id: "other", profile_id: "writer", conversation_title: "Another conversation", profile_name: "Writer" }];
  fireEvent.click(screen.getByRole("button", { name: "刷新运行实例" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("所选运行实例已失效");
  expect(screen.getByRole("button", { name: "清理运行时缓存" })).toBeDisabled();
});

it("opens the exact message source without fetching another conversation's latest link", async () => {
  const retry = vi.fn();
  render(<SourceStrip conversationId="conversation-a" onRetryLink={retry} sources={[{
    requested_url: "https://a.example/fail", final_url: "https://a.example/fail", status: "error", error_code: "network_error",
  }]} />);
  fireEvent.click(screen.getByRole("button", { name: "查看读取详情" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("conversation-a");
  expect(screen.getByRole("dialog")).toHaveTextContent("网络问题");
  expect(safeFetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
  expect(retry).toHaveBeenCalledWith("https://a.example/fail");
});

it("does not label a historical winner as the current source", () => {
  render(<SkillConflictsPanel conflicts={[{ name: "demo", action: "rejected", winner: { path: "/old" }, active: { path: "/new" } }]} />);
  expect(screen.getByText("当前生效：/new")).toBeInTheDocument();
  expect(screen.getByText("该次加载选用：/old")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("retains source records when the server rejects clearing them", async () => {
  vi.mocked(safeFetch).mockImplementation(async url => String(url).endsWith("/clear")
    ? json({ ok: false }) : json({ conflicts: [{ name: "demo" }] }));
  function Harness() {
    const state = useSkillConflicts(base(), true);
    return <><span>{state.conflicts.length}</span><button onClick={() => void state.clear()}>clear</button><p>{state.error}</p></>;
  }
  render(<Harness />);
  await screen.findByText("1");
  fireEvent.click(screen.getByText("clear"));
  await screen.findByText("清除失败，请稍后再试。");
  expect(screen.getByText("1")).toBeInTheDocument();
});

it("only notifies about new load records, not initial history or changed active metadata", async () => {
  const onNew = vi.fn();
  let records = [{ name: "demo", action: "rejected", winner: { path: "/old" }, active: { path: "/old" } }];
  vi.mocked(safeFetch).mockImplementation(async () => json({ conflicts: records }));
  function Harness() {
    const state = useSkillConflicts(base(), true, onNew);
    return <button disabled={state.busy} onClick={() => void state.refresh()}>refresh</button>;
  }
  render(<Harness />);
  await waitFor(() => expect(screen.getByText("refresh")).toBeEnabled());
  expect(onNew).not.toHaveBeenCalled();
  records = [{ ...records[0], active: { path: "/new" } }];
  fireEvent.click(screen.getByText("refresh"));
  await waitFor(() => expect(screen.getByText("refresh")).toBeEnabled());
  expect(onNew).not.toHaveBeenCalled();
  records = [...records, { ...records[0], name: "second" }];
  fireEvent.click(screen.getByText("refresh"));
  await waitFor(() => expect(onNew).toHaveBeenCalledTimes(1));
  expect(onNew.mock.calls[0][0]).toHaveLength(1);
});
