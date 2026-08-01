import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiProxyTarget = process.env.RECONFORGE_API_PROXY_TARGET;

export default defineConfig({
  plugins: [react()],
  // Local browser integration can opt in to one explicit same-origin API
  // target. Normal development, tests, and production builds never proxy.
  server: apiProxyTarget ? {
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: false,
      },
    },
  } : undefined,
  build: {
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    globals: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    restoreMocks: true,
  },
});
