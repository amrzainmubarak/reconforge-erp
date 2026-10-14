import { afterEach, expect, it, vi } from "vitest";
import original from "./project-source-reconciliation-original-report.json";
import { canonicalProject, loadProjectCloseDiagnostic, loadProjectCloseEvidence, parseProjectCloseDiagnostic, parseProjectReport, projectHash } from "./project-source-reconciliation-data";
import { projectCloseFixture } from "./project-source-close-test-fixture";

const scope = { workspace_id: "work", organization_id: "org", legal_entity_id: "entity" }, tenant = original.qualified_scope.tenant_id;
afterEach(() => vi.unstubAllGlobals());
async function retainedReport() { return parseProjectReport(original, scope, tenant, original.selection); }
it("binds exact original source obligations and separate consumed claims without formal close", async () => {
  const report = await retainedReport(), diagnostic = await parseProjectCloseDiagnostic(await projectCloseFixture(report), report);
  expect(diagnostic.source_obligations_settled).toBe(true); expect(diagnostic.whole_time_claims).toHaveLength(2);
  expect(diagnostic.limitations.formal_close_workflow_assessed).toBe(false);
});
it.each(["scope", "report", "cost", "obligation", "claim", "owner", "duplicate_period", "status", "full_close", "number_settled", "sequence", "seal"])("refuses resealed wrong source/observation %s", async attack => {
  const report = await retainedReport(), value = await projectCloseFixture(report);
  if (attack === "scope") value.qualified_scope.tenant_id = "foreign";
  if (attack === "report") value.source_report_digest = "0".repeat(64);
  if (attack === "cost") value.project_totals.wage_cost_minor = "0";
  if (attack === "obligation") value.whole_source_obligations.wage_liability_minor = "1";
  if (attack === "claim") value.whole_time_claims[0].time_digest = "0".repeat(64);
  if (attack === "owner") value.whole_time_claims[0].billing_claim.owner_id = "PB1-FOREIGN";
  if (attack === "duplicate_period") value.observed_native_periods.push({ ...value.observed_native_periods[0] });
  if (attack === "status") value.observed_native_periods[0].status = "Ready";
  if (attack === "full_close") value.limitations.formal_close_workflow_assessed = true;
  if (attack === "number_settled") Object.assign(value, { source_obligations_settled: 1 });
  if (attack === "sequence") value.whole_time_claims[0].wage_claim.sequence = 0;
  const { diagnostic_digest: _, ...body } = value; value.diagnostic_digest = attack === "seal" ? "0".repeat(64) : await projectHash(new TextEncoder().encode(canonicalProject(body)));
  await expect(parseProjectCloseDiagnostic(value, report)).rejects.toThrow();
});
it("keeps raw close evidence with native64-bit integers unchanged", async () => {
  const report = await retainedReport(), diagnostic = await parseProjectCloseDiagnostic(await projectCloseFixture(report), report);
  const raw = JSON.stringify({ schema_version: "project-source-close-evidence-v1", diagnostic, evidence_digest: "a".repeat(64), native_execution_proven: true, financial_writes: false, private_personnel_reads: false, source_evidence: { unsafe_native_integer: "BIG" } }).replace('"BIG"', "9000000000000000000");
  const bytes = new TextEncoder().encode(raw), hash = await projectHash(bytes);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(raw, { headers: { "Content-Length": String(bytes.length), "X-ReconForge-Raw-SHA256": hash, "X-ReconForge-Report-Digest": report.report_digest, "X-ReconForge-Diagnostic-Digest": diagnostic.diagnostic_digest, "X-ReconForge-Evidence-Digest": "a".repeat(64) } })));
  const result = await loadProjectCloseEvidence({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, scope, report.selection, report, diagnostic);
  expect(new TextDecoder().decode(result.bytes)).toBe(raw);
});
it("refuses a retained foreign selection before issuing a diagnostic read", async () => {
  const report = await retainedReport(); const request = vi.fn(); vi.stubGlobal("fetch", request);
  await expect(loadProjectCloseDiagnostic({ tenantId: tenant, csrfToken: "csrf", expiresAt: "2099-01-01T00:00:00Z" }, scope, { ...report.selection, invoice_id: "PB1-FOREIGN" }, report)).rejects.toThrow();
  expect(request).not.toHaveBeenCalled();
});
