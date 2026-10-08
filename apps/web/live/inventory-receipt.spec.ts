import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const base = process.env.RECONFORGE_GFO_LIVE_URL;
const tenant = process.env.RECONFORGE_GFO_RECEIPT_TENANT;
const password = process.env.RECONFORGE_GFO_RECEIPT_PASSWORD;
// This file is explicitly selected only by the owned live gate. Missing fixture
// configuration is a failure, never a skipped acceptance claim.
test.use({ ignoreHTTPSErrors: true });
async function login(page: Page, username: string) {
 await page.goto(`${base}/admin-audit`);
 await page.getByLabel("Tenant ID", { exact: true }).fill(tenant!); await page.getByLabel("Username", { exact: true }).fill(username); await page.getByLabel("Password", { exact: true }).fill(password!);
 await page.getByRole("button", { name: "Sign in to administration", exact: true }).click();
 await expect(page.getByRole("heading", { name: "Confirm privileged access", exact: true })).toBeVisible();
 const elevatedReply = page.waitForResponse(r => r.url().endsWith("/auth/step-up") && r.request().method() === "POST");
 await page.getByLabel("Password", { exact: true }).fill(password!); await page.getByRole("button", { name: "Confirm and continue", exact: true }).click();
 const elevated = await elevatedReply; expect(elevated.status(), await elevated.text()).toBe(200);
 await expect(page.getByText("Privileged access is active", { exact: true })).toBeVisible();
 await page.getByRole("button", { name: /Inventory receipt/i }).first().click();
 await page.getByLabel("Workspace ID", { exact: true }).fill("work"); await page.getByLabel("Organization ID", { exact: true }).fill("org"); await page.getByLabel("Legal entity ID", { exact: true }).fill("entity");
}
test("real HTTPS persisted independent receipt review, stock/GL and unused inverse", async ({ browser }) => {
 test.setTimeout(120_000); expect(base && tenant && password, "owned synthetic fixture is required").toBeTruthy();
 const makerContext = await browser.newContext({ ignoreHTTPSErrors: true }); const checkerContext = await browser.newContext({ ignoreHTTPSErrors: true });
 try {
 const maker = await makerContext.newPage(), checker = await checkerContext.newPage(); await login(maker, "maker"); await login(checker, "checker");
 const number = `LIVE-${Date.now()}`;
 const fields: Record<string, string> = { "Receipt number": number, "Posting date": "2026-10-03", "Fiscal period ID": "period", "Item code": "ITEM", "Warehouse/location code": "MAIN/STOCK", "Exact quantity": "10", "Total value in minor units": "12000", "FIFO policy code": "FIFO", "Organization code": "ORG", "Entity code": "ENTITY" };
 for (const [label, value] of Object.entries(fields)) await maker.getByLabel(label, { exact: true }).fill(value);
 await maker.getByLabel("Reason", { exact: true }).fill("Real browser exact source"); const preparedReply = maker.waitForResponse(r => r.url().endsWith("/inventory-receipt-posting/plans") && r.request().method() === "POST"); await maker.getByRole("button", { name: "Prepare receipt", exact: true }).click(); const prepared = await preparedReply; expect(prepared.status(), await prepared.text()).toBe(200); const plan = (await prepared.json()).receipt;
 await checker.getByLabel("Plan ID", { exact: true }).fill(plan.plan_id); await checker.getByRole("button", { name: "Recover retained receipt", exact: true }).click(); await expect(checker.getByRole("heading", { name: `${number} — Prepared` })).toBeVisible();
 const evidence = checker.getByRole("region", { name: "Retained evidence", exact: true }); await evidence.getByLabel("Reason", { exact: true }).fill("Independent real browser review"); await evidence.getByRole("button", { name: "Review exact plan", exact: true }).click(); await expect(checker.getByRole("heading", { name: `${number} — Reviewed` })).toBeVisible();
 const committedReply = checker.waitForResponse(r => r.url().endsWith("/commit")); await evidence.getByRole("button", { name: "Commit reviewed stock and GL", exact: true }).click(); const posted = await committedReply; expect(posted.status(), await posted.text()).toBe(200); expect((await posted.json()).receipt.total_value_minor).toBe("12000"); await expect(checker.getByRole("heading", { name: `${number} — Committed` })).toBeVisible();
 await maker.getByRole("button", { name: "Recover retained receipt", exact: true }).click(); await expect(maker.getByRole("heading", { name: `${number} — Committed` })).toBeVisible(); const makerEvidence = maker.getByRole("region", { name: "Retained evidence", exact: true }); await makerEvidence.getByLabel("Reason", { exact: true }).fill("Complete unused return"); await makerEvidence.getByLabel("Reversal number", { exact: true }).fill(`${number}-RETURN`); await makerEvidence.getByLabel("Posting date", { exact: true }).fill("2026-10-04"); await makerEvidence.getByLabel("Fiscal period ID", { exact: true }).fill("period"); const inverseReply = maker.waitForResponse(r => r.url().endsWith("/reversal")); await makerEvidence.getByRole("button", { name: "Prepare full unused reversal", exact: true }).click(); const inverse = await inverseReply; expect(inverse.status(), await inverse.text()).toBe(200); const inverseId = (await inverse.json()).receipt.plan_id;
 await checker.getByLabel("Plan ID", { exact: true }).fill(inverseId); await checker.getByRole("button", { name: "Recover retained receipt", exact: true }).click(); await expect(checker.getByRole("heading", { name: `${number}-RETURN — Prepared` })).toBeVisible(); await evidence.getByRole("button", { name: "Review exact plan", exact: true }).click(); await expect(checker.getByRole("heading", { name: `${number}-RETURN — Reviewed` })).toBeVisible(); await evidence.getByRole("button", { name: "Commit reviewed stock and GL", exact: true }).click(); await expect(checker.getByRole("heading", { name: `${number}-RETURN — Committed` })).toBeVisible();
 await checker.setViewportSize({ width: 390, height: 844 }); expect(await checker.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true); expect((await new AxeBuilder({ page: checker }).include("#main-content").analyze()).violations).toEqual([]);
 } finally { await makerContext.close(); await checkerContext.close(); }
});
