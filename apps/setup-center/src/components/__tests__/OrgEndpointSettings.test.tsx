import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OrgEndpointSettings } from "../OrgEndpointSettings";
import { safeFetch } from "../../providers";
import i18n from "../../i18n";

vi.mock("../../providers", () => ({ safeFetch: vi.fn() }));
const models = [
  { name: "local", model: "local-model", status: "healthy" },
  { name: "remote", model: "remote-model", status: "unhealthy" },
];
const props = () => ({
  apiBaseUrl: "http://test", visible: true, endpoint: null as string | null,
  policy: "prefer" as const, disabled: false,
  onEndpointChange: vi.fn(), onPolicyChange: vi.fn(),
});

beforeEach(async () => {
  vi.resetAllMocks();
  await i18n.changeLanguage("en");
  vi.mocked(safeFetch).mockResolvedValue({ ok: true, json: async () => ({ models }) } as Response);
});

it("loads configured endpoints and lets the user choose and clear a preference", async () => {
  const p = props();
  const { rerender } = render(<OrgEndpointSettings {...p} />);
  await screen.findByRole("option", { name: "local (local-model)" });
  const select = screen.getByRole("combobox", { name: "LLM Endpoint Preference" });
  expect(safeFetch).toHaveBeenCalledWith("http://test/api/models");
  fireEvent.change(select, { target: { value: "local" } });
  expect(p.onEndpointChange).toHaveBeenCalledWith("local");
  rerender(<OrgEndpointSettings {...p} endpoint="local" />);
  const policy = screen.getAllByRole("combobox")[1];
  fireEvent.change(policy, { target: { value: "require" } });
  expect(p.onPolicyChange).toHaveBeenCalledWith("require");
  fireEvent.change(select, { target: { value: "" } });
  expect(p.onEndpointChange).toHaveBeenCalledWith(null);
  rerender(<OrgEndpointSettings {...p} />);
  expect(policy).toBeDisabled();
});

it("preserves a saved endpoint on load failure and supports retry", async () => {
  vi.mocked(safeFetch).mockRejectedValueOnce(new Error("offline"));
  const p = props();
  render(<OrgEndpointSettings {...p} endpoint="old-endpoint" />);
  await screen.findByRole("alert");
  expect(screen.getAllByRole("combobox")[0]).toHaveValue("old-endpoint");
  expect(p.onEndpointChange).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Refresh endpoints" }));
  await screen.findByRole("option", { name: "local (local-model)" });
  expect(screen.getAllByRole("combobox")[0]).toHaveValue("old-endpoint");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("shows why running organizations cannot edit model settings", async () => {
  render(<OrgEndpointSettings {...props()} endpoint="local" disabled />);
  await screen.findByRole("option", { name: "local (local-model)" });
  for (const select of screen.getAllByRole("combobox")) expect(select).toBeDisabled();
  expect(screen.getByText(/Pause or stop the organization/)).toBeInTheDocument();
});

it("explains an empty list and refreshes when the view is shown again", async () => {
  vi.mocked(safeFetch).mockResolvedValueOnce({ ok: true, json: async () => ({ models: [] }) } as Response);
  const p = props();
  const { rerender } = render(<OrgEndpointSettings {...p} />);
  await screen.findByText(/No endpoints available/);
  rerender(<OrgEndpointSettings {...p} visible={false} />);
  rerender(<OrgEndpointSettings {...p} />);
  await screen.findByRole("option", { name: "local (local-model)" });
  await waitFor(() => expect(safeFetch).toHaveBeenCalledTimes(2));
});
