import { afterEach, expect, it, vi } from "vitest";
import original from "./project-source-reconciliation-original-report.json";
import { canonicalProject, loadProjectEvidence, parseProjectReport, projectHash, projectMoney } from "./project-source-reconciliation-data";
const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" }, tenant = original.qualified_scope.tenant_id, selected = original.selection;
afterEach(() => vi.unstubAllGlobals());
it("verifies the retained native report and exact signed string-money", async () => { const report = await parseProjectReport(original, scope, tenant, selected); expect(report.project_totals.source_margin_minor).toBe("1267"); expect(projectMoney("-9000000000000000000", 2, "en")).toBe("-90,000,000,000,000,000.00"); expect(report.whole_source_settlement.per_project_cash_allocated).toBe(false); });
it.each(["tenant", "selection", "margin", "settlement", "duplicate", "time", "private", "bank", "number", "seal"])("refuses %s drift before display", async attack => {
  const value = structuredClone(original);
  if (attack === "tenant") value.qualified_scope.tenant_id = "foreign";
  if (attack === "selection") value.selection.invoice_id = "PB1-other";
  if (attack === "margin") value.project_totals.source_margin_minor = "0";
  if (attack === "settlement") value.whole_source_settlement.wage_paid_minor = "0";
  if (attack === "duplicate") value.source_membership.push(value.source_membership[0]);
  if (attack === "time") value.approved_time.push(value.approved_time[0]);
  if (attack === "private") value.limitations.private_personnel_rows_included = true;
  if (attack === "bank") value.limitations.bank_transfer_proven = true;
  if (attack === "number") Object.assign(value.project_totals, { wage_cost_minor: 1268 });
  if (attack === "seal") value.report_digest = "0".repeat(64);
  const { report_digest: _, ...body } = value; if (attack !== "seal") value.report_digest = await projectHash(new TextEncoder().encode(canonicalProject(body)));
  await expect(parseProjectReport(value, scope, tenant, selected)).rejects.toThrow();
});
it("keeps large native integer raw bytes unchanged while verifying only summary money", async () => {
  const raw = JSON.stringify({ schema_version: "project-source-reconciliation-evidence-v1", report: original, evidence_digest: "a".repeat(64), native_execution_proven: true, financial_writes: false, private_personnel_reads: false, private_payroll_command_receipts_exported: false, original_rows: { amount_minor: "UNCHANGED_BIGINT" } }).replace('"UNCHANGED_BIGINT"', "9000000000000000000"), bytes = new TextEncoder().encode(raw), hash = await projectHash(bytes);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(raw, { headers: { "Content-Length": String(bytes.length), "X-ReconForge-Raw-SHA256": hash, "X-ReconForge-Report-Digest": original.report_digest, "X-ReconForge-Evidence-Digest": "a".repeat(64) } })));
  const result = await loadProjectEvidence({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, scope, selected, original.report_digest);
  expect(new TextDecoder().decode(result.bytes)).toBe(raw); expect(result.sha256).toBe(hash);
});
it("refuses truncated/corrupt evidence even with a correct summary", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { headers: { "Content-Length": "2", "X-ReconForge-Raw-SHA256": "0".repeat(64), "X-ReconForge-Report-Digest": original.report_digest } })));
  await expect(loadProjectEvidence({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, scope, selected, original.report_digest)).rejects.toThrow();
});
it("retains an explicit zero Project wage allocation without inventing cost", async () => {
  const value = structuredClone(original); value.project_totals.wage_cost_minor = "0"; value.project_totals.source_margin_minor = value.project_totals.revenue_minor;
  const { report_digest: _, ...body } = value; value.report_digest = await projectHash(new TextEncoder().encode(canonicalProject(body)));
  expect((await parseProjectReport(value, scope, tenant, selected)).project_totals.wage_cost_minor).toBe("0");
});
