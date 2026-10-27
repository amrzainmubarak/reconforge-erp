import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
process.env.RECONFORGE_RELEASE_PRODUCT_TEST_PASSWORD ??= `Synthetic-browser-${randomBytes(32).toString("hex")}`;
const port = process.env.RECONFORGE_RELEASE_PRODUCT_PORT ?? "24583";
export default defineConfig({
  testDir: ".", testMatch: "release-product-live.acceptance.ts", retries: 0, workers: 1, reporter: "list",
  use: { baseURL: `https://localhost:${port}`, ignoreHTTPSErrors: true, trace: "retain-on-failure", ...(process.env.RECONFORGE_RELEASE_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.RECONFORGE_RELEASE_BROWSER_EXECUTABLE } } : {}) },
  projects: [{ name: "release-product-chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: { cwd: fileURLToPath(new URL("../../..", import.meta.url)), command: `"${process.env.RECONFORGE_RELEASE_PRODUCT_PYTHON ?? "python"}" -m tests.test_release_product_browser_runtime --port ${port}`, url: `https://localhost:${port}/api/v1/health`, ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 180000 },
});
