import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: ".", testMatch: "erp-procurement-commitments.spec.ts", retries: 0, workers: 1,
  outputDir: process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 20_000, navigationTimeout: 20_000, ignoreHTTPSErrors: true, trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "erp-procurement-commitments-chromium", use: { ...devices["Desktop Chrome"] } }],
});
