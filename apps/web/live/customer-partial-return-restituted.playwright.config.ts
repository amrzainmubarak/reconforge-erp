import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".", testMatch: ["customer-partial-return-restituted-cycles.spec.ts"], retries: 0, repeatEach: 1, workers: 1, forbidOnly: true, failOnFlakyTests: true,
  outputDir: process.env.RECONFORGE_ERP_BROWSER_ARTIFACTS,
  reporter: [["list"], ["json", { outputFile: process.env.RECONFORGE_ERP_BROWSER_REPORT }]],
  use: { actionTimeout: 15_000, navigationTimeout: 15_000, ignoreHTTPSErrors: true, trace: "off", screenshot: "only-on-failure" },
  projects: [{ name: "customer-partial-return-restituted-chromium", use: { ...devices["Desktop Chrome"] } }],
});
