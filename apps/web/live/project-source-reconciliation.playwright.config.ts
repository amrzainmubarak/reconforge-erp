import { defineConfig, devices } from "@playwright/test";
export default defineConfig({ testDir: ".", testMatch: "project-source-reconciliation.spec.ts", retries: 0, workers: 1,
  outputDir: process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 15000, navigationTimeout: 15000, ignoreHTTPSErrors: true, trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "project-source-reconciliation-chromium", use: { ...devices["Desktop Chrome"] } }],
});
