import { useEffect, useRef } from "react";

// Window events cover local installs; visible-page polling also covers installs
// performed by the desktop while this browser tab is already open.
export function useMCPChanges(enabled: boolean, refresh: () => Promise<void>) {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let running = false;
    let queued = false;
    const update = async () => {
      if (stopped || document.visibilityState === "hidden") return;
      if (running) { queued = true; return; }
      running = true;
      try { await refreshRef.current(); }
      finally {
        running = false;
        if (queued && !stopped) { queued = false; void update(); }
      }
    };
    const changed = () => { void update(); };
    const timer = window.setInterval(changed, 3000);
    window.addEventListener("openkitsune:mcp-changed", changed);
    window.addEventListener("focus", changed);
    document.addEventListener("visibilitychange", changed);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      window.removeEventListener("openkitsune:mcp-changed", changed);
      window.removeEventListener("focus", changed);
      document.removeEventListener("visibilitychange", changed);
    };
  }, [enabled]);
}
