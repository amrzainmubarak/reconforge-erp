import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: ".", testMatch: ["inventory-receipt.spec.ts", "job-operations.acceptance.ts"],
  retries: 0, workers: 1, reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_GFO_BROWSER_REPORT ?? "../../../output/gfo-browser/playwright.json" }]],
  use: { ignoreHTTPSErrors: true, trace: "retain-on-failure" },
  projects: [{ name: "gfo-chromium", use: { ...devices["Desktop Chrome"] } }],
});
