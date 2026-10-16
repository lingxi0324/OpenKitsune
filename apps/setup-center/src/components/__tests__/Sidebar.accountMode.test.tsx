import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import "../../i18n";
import { Sidebar } from "../Sidebar";
import { connectOpenKitsuneAccount, loadAccountCapability } from "../../utils/accountLogin";
import { patchInstall, trackInstall } from '../../marketplace/installTasks';

vi.mock("../../utils/accountLogin", () => ({
  getAccountGeneration: () => 0,
  connectOpenKitsuneAccount: vi.fn(),
  disconnectOpenKitsuneAccount: vi.fn(),
  loadAccountCapability: vi.fn(),
  refreshOpenKitsuneAccountEntitlements: vi.fn(),
  watchNativeAccountLogin: vi.fn(async () => () => {}),
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    loading: vi.fn(),
    success: vi.fn(),
    dismiss: vi.fn(),
  },
}));

function renderSidebar(onCloseMobile?: () => void) {
  return render(
    <Sidebar
      collapsed={false}
      mobileOpen={Boolean(onCloseMobile)}
      onCloseMobile={onCloseMobile}
      onToggleCollapsed={vi.fn()}
      view="chat"
      onViewChange={vi.fn()}
      configMode={false}
      onEnterConfig={vi.fn()}
      onExitConfig={vi.fn()}
      steps={[]}
      stepId="workspace"
      onStepChange={vi.fn()}
      disabledViews={[]}
      storeVisible={false}
      serviceRunning
      onRefreshStatus={vi.fn(async () => undefined)}
      httpApiBase="http://localhost:18900"
    />,
  );
}

describe("Sidebar account distribution mode", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
  });

  it('keeps installation actions out of the application menu even when tasks exist', async () => {
    vi.mocked(loadAccountCapability).mockResolvedValue({ enabled: false, mode: 'disabled', provider: null,
      display_name: null, supports_entitlements: false });
    const job = { id: 'current', status: 'installing' as const, resource_type: 'skill' as const,
      resource_name: 'Current skill', progress: null, version: '1', permissions: [], dependencies: [] };
    const task = trackInstall('http://localhost:18900', job);
    patchInstall(task.key, { hidden: true, background: true });
    const closeSidebar = vi.fn();
    renderSidebar(closeSidebar);
    fireEvent.click(await screen.findByRole('button', { name: /应用菜单|App menu/i }));
    expect(screen.queryByRole('menuitem', { name: /继续安装|Resume installation/ })).toBeNull();
    expect(closeSidebar).not.toHaveBeenCalled();
  });

  it("closes mobile navigation during device preparation and keeps login alive until cancelled", async () => {
    vi.mocked(loadAccountCapability).mockResolvedValue({
      enabled: true, mode: "openkitsune", provider: "openkitsune",
      display_name: "OpenKitsune", supports_entitlements: true,
    });
    let loginOptions: Parameters<typeof connectOpenKitsuneAccount>[1];
    vi.mocked(connectOpenKitsuneAccount).mockImplementation((_base, options = {}) => {
      loginOptions = options;
      options.onDevicePreparing?.();
      return new Promise((_resolve, reject) => {
        options.signal?.addEventListener("abort", () => reject(new Error("account_login_cancelled")));
      });
    });
    const onCloseMobile = vi.fn();
    const { container, unmount } = renderSidebar(onCloseMobile);
    const menuButton = await screen.findByRole("button", { name: /未登录|Signed out/i });
    fireEvent.click(menuButton);
    fireEvent.click(container.querySelector<HTMLButtonElement>(".sidebarAccountMenuProfile")!);
    await waitFor(() => expect(onCloseMobile).toHaveBeenCalledOnce());
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(loginOptions!.signal!.aborted).toBe(false);
    act(() => loginOptions!.onDeviceAuthorization?.({
      userCode: "ABCD-EFGH", verificationUri: "https://account.example/device",
      authorizationUrl: "https://account.example/device?user_code=ABCD-EFGH",
      openAuthorization: vi.fn(async () => undefined),
    }));
    expect(screen.getByRole("dialog")).toHaveTextContent("ABCD-EFGH");
    fireEvent.click(screen.getByRole("button", { name: /取消登录|Cancel sign-in/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(loginOptions!.signal!.aborted).toBe(true);
    unmount();
  });

  it("renders an account-free application menu when the capability is disabled", async () => {
    vi.mocked(loadAccountCapability).mockResolvedValue({
      enabled: false,
      mode: "disabled",
      provider: null,
      display_name: null,
      supports_entitlements: false,
    });

    renderSidebar();

    const menuButton = await screen.findByRole("button", { name: /应用菜单|App menu/i });
    expect(screen.queryByText(/未登录|Signed out/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/连接账户|Connect account/i)).not.toBeInTheDocument();

    fireEvent.click(menuButton);
    await waitFor(() => {
      expect(screen.getByRole("menu")).toHaveAccessibleName(/应用菜单|App menu/i);
    });
    expect(screen.getByText(/配置|Config/i)).toBeInTheDocument();
    expect(screen.queryByText(/退出登录|Sign out/i)).not.toBeInTheDocument();
  });

  it("uses neutral account branding for a custom provider", async () => {
    vi.mocked(loadAccountCapability).mockResolvedValue({
      enabled: true,
      mode: "custom",
      provider: "vendor-id",
      display_name: "Vendor Account",
      supports_entitlements: true,
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith("/api/account/status")
        ? new Response(JSON.stringify({ status: "active", profile: {} }), { status: 200 })
        : new Response("[]", { status: 200 });
    }));

    const { container } = renderSidebar();

    expect((await screen.findAllByText("Vendor Account")).length).toBeGreaterThan(0);
    expect(container.querySelector("img.sidebarAccountAvatar")).toBeNull();
  });
});
