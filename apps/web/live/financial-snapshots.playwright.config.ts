import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".", testMatch: "financial-snapshots.spec.ts", retries: 0, workers: 1,
  outputDir: process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 15_000, navigationTimeout: 15_000, ignoreHTTPSErrors: true,
    trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "financial-snapshots-chromium", use: { ...devices["Desktop Chrome"] } }],
});
