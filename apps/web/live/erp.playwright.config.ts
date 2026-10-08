import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "erp-cycles.spec.ts",
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 15_000, navigationTimeout: 15_000, ignoreHTTPSErrors: true, trace: "retain-on-failure" },
  projects: [{ name: "erp-chromium", use: { ...devices["Desktop Chrome"] } }],
});
