import path from "node:path";
import vite_plugin_react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // P-RC-2 P2.8: stub the compile-time __BUILD_ID__ define so unit
  // tests that read it (StaleBundleBanner) don't need the real Vite
  // build pipeline.
  define: {
    __BUILD_ID__: JSON.stringify("test-build-id"),
  },
  plugins: [vite_plugin_react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@shared/providers.json": path.resolve(
        __dirname,
        "../../src/openkitsune/llm/registries/providers.json",
      ),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/__tests__/**/*.test.{js,ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
    },
  },
});
