import { useEffect, useRef } from "react";

// A desktop install can change the backend of an already open browser tab.
// Local events give immediate updates; visible-page polling covers other windows.
export function usePluginChanges(visible: boolean, refresh: () => Promise<void>) {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    if (!visible) return;
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
    const changed = (event: Event) => {
      if ((event as CustomEvent).detail?.source !== "plugin-list") void update();
    };
    const foreground = () => void update();
    void update();
    const timer = window.setInterval(foreground, 3000);
    window.addEventListener("openkitsune:plugin-apps-changed", changed);
    window.addEventListener("focus", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      window.removeEventListener("openkitsune:plugin-apps-changed", changed);
      window.removeEventListener("focus", foreground);
      document.removeEventListener("visibilitychange", foreground);
    };
  }, [visible]);
}
