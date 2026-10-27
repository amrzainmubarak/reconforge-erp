import { request } from "node:https";
import { expect, test } from "@playwright/test";

export interface BrowserFixture { tenant: string; employee_id: string; restricted_username?: string }

// Keep the test credential and metadata out of Playwright failure traces. The
// test server is a local disposable HTTPS runtime with a generated certificate.
async function requestFixture(key?: string): Promise<{ status: number; body: string }> {
  const baseURL = test.info().project.use.baseURL;
  if (typeof baseURL !== "string") throw new Error("Missing local browser test URL");
  const url = new URL("/__test/browser-fixture", baseURL);
  if (url.protocol !== "https:" || url.hostname !== "localhost") throw new Error("Fixture server must be local HTTPS");
  return await new Promise((resolve, reject) => {
    const req = request({ hostname: "127.0.0.1", port: url.port, servername: "localhost", path: url.pathname,
      rejectUnauthorized: false, headers: { host: url.host, ...(key ? { "x-reconforge-fixture-key": key } : {}) } }, response => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", chunk => {
        body += chunk;
        if (body.length > 16_384) req.destroy(new Error("Fixture response too large"));
      });
      response.on("end", () => resolve({ status: response.statusCode ?? 0, body }));
      response.on("error", reject);
    });
    req.on("error", reject);
    req.end();
  });
}

export async function unprivilegedFixtureStatus(): Promise<number> {
  return (await requestFixture()).status;
}

export async function getBrowserFixture(): Promise<BrowserFixture> {
  const key = process.env.RECONFORGE_RELEASE_PRODUCT_FIXTURE_KEY;
  if (!key) throw new Error("Missing synthetic browser fixture key");
  const response = await requestFixture(key);
  expect(response.status).toBe(200);
  return JSON.parse(response.body) as BrowserFixture;
}
