import { expect, test } from "@playwright/test";

const enabled = process.env.RECONFORGE_LIVE_HTTPS_HOSTING === "1";
const port = process.env.RECONFORGE_LIVE_HTTPS_PORT ?? "24443";
const origin = `https://localhost:${port}`;

test("production Studio executes under the real same-origin HTTPS policy", async ({ browser }) => {
  test.skip(!enabled, "requires the opt-in local HTTPS production-bundle runtime");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.addInitScript(() => {
    (window as Window & { __reconforgeCspViolations?: string[] }).__reconforgeCspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as Window & { __reconforgeCspViolations: string[] }).__reconforgeCspViolations.push(
        `${event.effectiveDirective}:${event.blockedURI}`,
      );
    });
  });

  const response = await page.goto(`${origin}/admin-audit`, { waitUntil: "networkidle" });
  expect(response?.status()).toBe(200);
  const headers = response?.headers() ?? {};
  expect(headers["strict-transport-security"]).toBe("max-age=31536000; includeSubDomains");
  expect(headers["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Redacted audit administration");
  expect(await page.locator("script:not([src])").count()).toBe(0);
  expect(await page.locator("style").count()).toBe(0);
  const result = await page.evaluate(async () => {
    const health = await fetch("/api/v1/health", { credentials: "same-origin" });
    return {
      status: health.status,
      origin: new URL(health.url).origin,
      pageOrigin: window.location.origin,
      violations: (window as Window & { __reconforgeCspViolations: string[] }).__reconforgeCspViolations,
    };
  });
  expect(result).toEqual({ status: 200, origin, pageOrigin: origin, violations: [] });
  await context.close();
});
