import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Button } from "./ui/button";
import type { DeviceAuthorizationPrompt } from "../utils/accountLogin";

export function AccountDeviceLoginDialog({ prompt, preparing = false, onCancel }: {
  prompt: DeviceAuthorizationPrompt | null;
  preparing?: boolean;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [opened, setOpened] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setOpened(false); setOpening(false); setError(null); }, [prompt]);
  async function continueLogin() {
    if (!prompt || opening) return;
    setOpening(true);
    setError(null);
    try {
      await prompt.openAuthorization();
      setOpened(true);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(t(message === "account_popup_blocked" ? "account.popupBlocked"
        : message === "account_login_expired" ? "account.loginExpired" : "account.deviceStartFailed"));
    } finally { setOpening(false); }
  }
  return (
    <Dialog open={preparing || Boolean(prompt)} onOpenChange={open => { if (!open) onCancel(); }}>
      {/* Both portal layers must cover the mobile navigation drawers (z-index 1000/1001). */}
      <DialogContent overlayClassName="z-[1100]" className="z-[1100] overflow-y-auto max-sm:top-auto max-sm:bottom-0 max-sm:left-0 max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-b-none max-sm:max-h-[90dvh] max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]">
        <DialogHeader>
          <DialogTitle>{t("account.deviceTitle")}</DialogTitle>
          <DialogDescription>{t(opened ? "account.deviceWaitingDescription" : "account.deviceDescription")}</DialogDescription>
        </DialogHeader>
        {prompt && <div style={{ textAlign: "center", padding: "16px 0" }}>
          <div>{t("account.deviceCode")}</div>
          <strong style={{ fontFamily: "monospace", fontSize: 30, letterSpacing: "0.12em" }}>
            {prompt?.userCode}
          </strong>
        </div>}
        {(preparing || opened) && <p role="status">{t(preparing ? "account.preparingLogin" : "account.waitingForAuthorization")}</p>}
        {error && <p role="alert">{error}</p>}
        {prompt && <>
          <Button disabled={opening} onClick={continueLogin}>
            {t(opened ? "account.reopenAuthorization" : "account.continueToAccount")}
          </Button>
          <small className="break-all">{prompt.verificationUri}</small>
        </>}
        <Button variant="outline" onClick={onCancel}>{t("account.cancelLogin")}</Button>
      </DialogContent>
    </Dialog>
  );
}
