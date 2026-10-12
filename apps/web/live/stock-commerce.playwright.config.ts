import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".", testMatch: "stock-commerce-cycles.spec.ts", retries: 0, workers: 1,
  outputDir: process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 15_000, navigationTimeout: 15_000, ignoreHTTPSErrors: true, trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "stock-commerce-chromium", use: { ...devices["Desktop Chrome"] } }],
});
