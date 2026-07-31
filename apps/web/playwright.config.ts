import { defineConfig, devices } from "@playwright/test";

const httpsHostingEnabled = process.env.RECONFORGE_LIVE_HTTPS_HOSTING === "1";
const httpsHostingPort = process.env.RECONFORGE_LIVE_HTTPS_PORT ?? "24443";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    colorScheme: "light",
    locale: "en-US",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1024 } },
    },
  ],
  webServer: [
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    ...(httpsHostingEnabled ? [{
      command: `python ../../tests/https_runtime.py --web-root dist --port ${httpsHostingPort}`,
      url: `https://localhost:${httpsHostingPort}/api/v1/health`,
      ignoreHTTPSErrors: true,
      reuseExistingServer: false,
      timeout: 120_000,
    }] : []),
  ],
});
