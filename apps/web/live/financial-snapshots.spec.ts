import { readFile } from "node:fs/promises";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const base = process.env.RECONFORGE_ERP_LIVE_URL;
const tenant = process.env.RECONFORGE_ERP_TENANT;
const password = process.env.RECONFORGE_ERP_PASSWORD;
const oracleFile = process.env.RECONFORGE_FINANCIAL_SNAPSHOT_ORACLE;

async function login(page: Page, username: string) {
  await page.goto(`${base}/admin-audit`);
  await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password!);
  await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill(password!);
  const response = page.waitForResponse(reply => reply.url().endsWith("/auth/step-up"));
  await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByText("Privileged access is active", { exact: true })).toBeVisible();
}

async function reporting(page: Page) {
  await page.getByRole("navigation", { name: "Primary navigation" }).getByRole("button", { name: "Financial statements", exact: true }).click();
  const scope = page.getByRole("form", { name: "Authorized scope", exact: true });
  for (const [label, value] of Object.entries({ Workspace: "work", Organization: "org", "Legal entity": "entity" })) await scope.getByLabel(label, { exact: true }).fill(value);
  const response = page.waitForResponse(reply => reply.url().endsWith("/financial-reporting/catalog"));
  await scope.getByRole("button", { name: "Apply scope", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByLabel("Classification version name", { exact: true })).toBeVisible();
}

test("wire HTTPS retained financial capture, lost acknowledgement, complete paged evidence and bilingual exact money", async ({ browser }, info) => {
  test.setTimeout(180_000);
  expect(base && tenant && password && oracleFile, "owned configured native financial snapshot fixture is required").toBeTruthy();
  const oracle = JSON.parse(await readFile(oracleFile!, "utf8"));
  const contexts = await Promise.all(["maker", "checker", "poster"].map(() => browser.newContext({ ignoreHTTPSErrors: true })));
  try {
    const [maker, checker, poster] = await Promise.all(contexts.map(context => context.newPage()));
    for (const [page, username] of [[maker, "browser-maker"], [checker, "browser-checker"], [poster, "browser-poster"]] as const) { await login(page, username); await reporting(page); }
    await maker.getByLabel("Classification version name", { exact: true }).fill("Browser durable native statements");
    await maker.getByLabel("Cash account CASH", { exact: true }).check();
    const prepared = maker.waitForResponse(reply => reply.url().endsWith("/financial-reporting/maps") && reply.request().method() === "POST");
    await maker.getByRole("button", { name: "Prepare classification", exact: true }).click();
    expect((await prepared).status()).toBe(200);
    await reporting(checker);
    await checker.getByLabel("Recorded reason", { exact: true }).fill("Independent browser classification review");
    const reviewed = checker.waitForResponse(reply => /\/financial-reporting\/maps\/[^/]+\/review$/.test(reply.url()));
    await checker.getByRole("button", { name: "Review classification", exact: true }).click();
    expect((await reviewed).status()).toBe(200);
    await reporting(poster);
    const form = poster.getByRole("form", { name: "Load financial statements", exact: true });
    await form.getByRole("combobox", { name: "Fiscal period", exact: true }).selectOption("period");
    await form.getByLabel("As of date", { exact: true }).fill("2026-10-31");
    const panel = poster.locator(".report-snapshot-panel");
    await expect(panel.getByRole("button", { name: "Capture statements", exact: true })).toBeEnabled();
    const packets: string[] = []; let dropped = false;
    await poster.route("**/financial-reporting/snapshots", async route => {
      if (route.request().method() !== "POST") { await route.continue(); return; }
      packets.push(route.request().postData()!);
      if (!dropped) { const actual = await route.fetch(); expect(actual.status(), await actual.text()).toBe(200); dropped = true; await route.abort("failed"); }
      else await route.continue();
    });
    await panel.getByRole("button", { name: "Capture statements", exact: true }).click();
    await expect(panel.getByRole("button", { name: "Retry exact capture", exact: true })).toBeVisible();
    await expect(poster.getByRole("form", { name: "Authorized scope", exact: true }).getByLabel("Legal entity", { exact: true })).toBeDisabled();
    await expect(form.getByLabel("As of date", { exact: true })).toBeDisabled();
    const captured = poster.waitForResponse(reply => reply.url().endsWith("/financial-reporting/snapshots") && reply.request().method() === "POST");
    await panel.getByRole("button", { name: "Retry exact capture", exact: true }).click();
    const reply = await captured; expect(reply.status(), await reply.text()).toBe(200);
    const report = (await reply.json()).snapshot;
    expect(report.effect_count).toBe(oracle.effect_count); expect(report.line_count).toBe(oracle.line_count);
    expect(report.balance_sheet).toEqual({ assets_minor: oracle.assets_minor, liabilities_minor: oracle.liabilities_minor,
      equity_minor: oracle.equity_minor, accumulated_unclosed_result_minor: oracle.result_minor, balanced: true });
    expect(report.income_statement).toEqual({ income_minor: oracle.income_minor, expense_minor: oracle.expense_minor, result_minor: oracle.result_minor });
    expect(report.cash_movements.closing_minor).toBe(oracle.cash_minor);
    expect(packets).toHaveLength(2); expect(packets[0]).toBe(packets[1]);
    await poster.unroute("**/financial-reporting/snapshots");
    await expect(panel.getByRole("status")).toHaveText("1–20 / 25");
    const next = poster.waitForResponse(response => response.url().includes("/evidence?") && response.url().includes("after=20"));
    await panel.getByRole("button", { name: "Next evidence page", exact: true }).click();
    const nativePage = await next; expect(nativePage.status()).toBe(200);
    const evidence = (await nativePage.json()).evidence;
    expect(evidence.items).toHaveLength(5); expect(evidence.next_after).toBeNull();
    expect(evidence.items.at(-1).chain_digest).toBe(report.evidence_digest);
    await expect(panel.getByRole("status")).toHaveText("21–25 / 25");
    await panel.locator("details").first().locator("summary").click();
    await expect(panel.getByRole("table").last()).toBeVisible();
    const history = poster.waitForResponse(response => /\/financial-reporting\/snapshots\?/.test(response.url()));
    await panel.getByRole("button", { name: "Reload captured reports", exact: true }).click();
    expect((await history).status()).toBe(200);
    await panel.getByRole("combobox", { name: "Retained reports", exact: true }).selectOption(report.id);
    await expect(panel.getByRole("status")).toHaveText("1–20 / 25");
    const violations = await poster.evaluate(async ({ id, digest, tenantId }) => {
      const headers = { "X-ReconForge-Tenant": tenantId, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity" };
      const wrongScope = await fetch(`/api/v1/financial-reporting/snapshots/${id}`, { headers: { ...headers, "X-ReconForge-Legal-Entity": "foreign" } });
      const wrongCursor = await fetch(`/api/v1/financial-reporting/snapshots/${id}/evidence?expected_digest=${digest === "0".repeat(64) ? "1".repeat(64) : "0".repeat(64)}`, { headers });
      return [wrongScope.status, wrongCursor.status];
    }, { id: report.id, digest: report.report_digest, tenantId: tenant! });
    expect(violations).toEqual([403, 409]);
    for (const arabic of [false, true]) {
      if (arabic) await poster.getByTestId("locale-toggle").click();
      await poster.setViewportSize({ width: 390, height: 844 });
      await expect(poster.getByRole("main")).toHaveAttribute("dir", arabic ? "rtl" : "ltr");
      const layout = await poster.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth,
        overflow: [...document.querySelectorAll(".financial-reporting, .financial-reporting *")].map(element => {
          const box = element.getBoundingClientRect(); return { tag: element.tagName, className: element.className, left: box.left, right: box.right, width: box.width };
        }).filter(box => box.right > innerWidth || box.left < 0) }));
      if (layout.width > layout.viewport) await info.attach(`snapshot-mobile-overflow-${arabic ? "ar" : "en"}`, { body: JSON.stringify(layout), contentType: "application/json" });
      expect(layout.width <= layout.viewport).toBe(true);
      expect((await new AxeBuilder({ page: poster }).include(".financial-reporting").analyze()).violations).toEqual([]);
      await info.attach(`captured-statements-${arabic ? "ar-rtl" : "en"}-390px`, {
        body: await poster.screenshot({ fullPage: true }), contentType: "image/png",
      });
    }
    await info.attach("native-financial-snapshot-oracle", { body: JSON.stringify({ report, oracle, evidence }), contentType: "application/json" });
  } finally { await Promise.all(contexts.map(context => context.close())); }
});
