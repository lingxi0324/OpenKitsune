import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.openkitsune.mobile",
  appName: "OpenKitsune",
  webDir: "dist-web",
  server: {
    androidScheme: "http",
    iosScheme: "http",
    allowNavigation: ["*"],
    cleartext: true,
  },
  android: {
    allowMixedContent: true,
    webContentsDebuggingEnabled: true,
  },
  plugins: {
    CapacitorCookies: {
      enabled: true,
    },
  },
};

export default config;
