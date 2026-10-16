import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import { AccountDeviceLoginDialog } from "../AccountDeviceLoginDialog";

describe("account device confirmation", () => {
  it.each(["zh", "en"])("shows the matching code and offers cancellation in %s", async language => {
    await i18n.changeLanguage(language);
    const onCancel = vi.fn();
    const openAuthorization = vi.fn(async () => undefined);
    const { unmount } = render(<AccountDeviceLoginDialog prompt={{
      userCode: "ABCD-EFGH", verificationUri: "https://account.example/device",
      authorizationUrl: "https://account.example/device?user_code=ABCD-EFGH",
      openAuthorization,
    }} onCancel={onCancel} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("ABCD-EFGH");
    expect(openAuthorization).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:i18n.t("account.continueToAccount")}));
    await waitFor(() => expect(screen.getByRole("button", {name:i18n.t("account.reopenAuthorization")})).toBeVisible());
    expect(openAuthorization).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog")).toHaveTextContent("ABCD-EFGH");
    fireEvent.click(screen.getByRole("button", {name:i18n.t("account.reopenAuthorization")}));
    await waitFor(() => expect(openAuthorization).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", {name:i18n.t("account.cancelLogin")}));
    expect(onCancel).toHaveBeenCalledOnce();
    unmount();
  });

  it("shows preparation without an empty code or a premature continue button", () => {
    const { unmount } = render(<AccountDeviceLoginDialog preparing prompt={null} onCancel={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(i18n.t("account.preparingLogin"));
    expect(screen.queryByRole("button", {name:i18n.t("account.continueToAccount")})).toBeNull();
    unmount();
  });

  it("keeps the code and lets the user retry when a popup is blocked", async () => {
    const openAuthorization = vi.fn().mockRejectedValueOnce(new Error("account_popup_blocked")).mockResolvedValueOnce(undefined);
    const {unmount} = render(<AccountDeviceLoginDialog prompt={{userCode:"ABCD-EFGH",verificationUri:"https://account.example/device",authorizationUrl:"https://account.example/device?user_code=ABCD-EFGH",openAuthorization}} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", {name:i18n.t("account.continueToAccount")}));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("account.popupBlocked")));
    expect(screen.getByRole("dialog")).toHaveTextContent("ABCD-EFGH");
    fireEvent.click(screen.getByRole("button", {name:i18n.t("account.continueToAccount")}));
    await waitFor(() => expect(screen.getByRole("button", {name:i18n.t("account.reopenAuthorization")})).toBeVisible());
    unmount();
  });
});
