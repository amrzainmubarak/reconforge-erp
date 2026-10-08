import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
const port = process.env.RECONFORGE_BUDGET_UI_PORT ?? "24518";
const python = process.env.RECONFORGE_BUDGET_UI_PYTHON ?? "python";
const webRoot = process.env.RECONFORGE_BUDGET_UI_WEB_ROOT ?? "../../output/budget-ui/web";
export default defineConfig({
  testDir: ".", testMatch: "budget-control-live.acceptance.ts", retries: 0, workers: 1, reporter: "list",
  use: { baseURL: `https://localhost:${port}`, ignoreHTTPSErrors: true, trace: "retain-on-failure" },
  projects: [{ name: "budget-chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    env: { PYTHONPATH: fileURLToPath(new URL("../../..", import.meta.url)) },
    command: `"${python}" ../../tests/serve_budget_control_ui.py --web-root "${webRoot}" --output ../../output/budget-ui/runtime --port ${port}`,
    url: `https://localhost:${port}/api/v1/health`, ignoreHTTPSErrors: true, reuseExistingServer: false, timeout: 120000,
  },
});
