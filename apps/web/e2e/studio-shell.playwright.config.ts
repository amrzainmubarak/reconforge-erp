import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
const port = process.env.RECONFORGE_STUDIO_SHELL_PORT ?? "24673";
export default defineConfig({
  testDir: ".", testMatch: "studio-shell.acceptance.ts", retries: 0, workers: 1, reporter: "list",
  outputDir: process.env.RECONFORGE_STUDIO_SHELL_OUT ? `${process.env.RECONFORGE_STUDIO_SHELL_OUT}/playwright` : "../../../output/assurance-20261026/studio-shell/playwright",
  use: { baseURL: `https://localhost:${port}`, ignoreHTTPSErrors: true, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: { cwd: fileURLToPath(new URL("../../..", import.meta.url)), command: `"${process.env.RECONFORGE_RELEASE_PRODUCT_PYTHON ?? "python"}" -m tests.test_studio_shell_browser_runtime --port ${port}`,
    url: `https://localhost:${port}/api/v1/health`, ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 180000 },
});
