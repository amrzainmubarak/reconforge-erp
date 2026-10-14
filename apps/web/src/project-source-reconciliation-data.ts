import { AdminApiError } from "./data";
import { financeRequest, type FinanceScope } from "./enterprise-finance-data";
import { formatExactDecimal } from "./locale-format";
import type { BrowserAdminSession, Locale } from "./types";

export const projectReconciliationPermissions = ["people_project_payroll.read", "project_time_billing.read", "finance_core.read", "receivables.read"];
export interface ProjectSelection { project_id: string; period_id: string; payrun_id: string; invoice_id: string }
export interface ProjectReport {
  schema_version: string; qualified_scope: FinanceScope & { tenant_id: string }; selection: ProjectSelection;
  currency_policy: { currency_code: string; currency_precision: number; currency_rounding_policy: string; currency_registry_version: string; currency_registry_digest: string };
  project: { id: string; project_code: string; dimension_id: string; value_id: string };
  project_totals: { wage_cost_minor: string; revenue_minor: string; source_margin_minor: string };
  whole_source_settlement: { wage_accrued_minor: string; wage_paid_minor: string; wage_liability_minor: string; invoice_minor: string; collected_minor: string; ar_outstanding_minor: string; per_project_cash_allocated: false };
  source_membership: { id: string; plan_digest: string; entry_id: string; effect_id: string; validation_digest: string }[];
  approved_time: { id: string; source_digest: string }[];
  limitations: Record<string, unknown>; report_digest: string;
}
function invalid(): never { throw new Error("project_source_evidence_invalid"); }
export const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
function exactKeys(v: Record<string, unknown>, keys: string[]) { if (keys.length !== Object.keys(v).length || keys.some(k => !Object.hasOwn(v, k))) invalid(); }
function minor(v: unknown, signed = false): string { if (typeof v !== "string" || !(signed ? /^(0|-?[1-9]\d{0,18})$/ : /^(0|[1-9]\d{0,18})$/).test(v) || BigInt(v) > 9000000000000000000n || BigInt(v) < -9000000000000000000n) invalid(); return v; }
export function canonicalProject(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalProject).join(",")}]`;
  if (record(value)) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonicalProject(value[k])}`).join(",")}}`;
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isSafeInteger(value)) return JSON.stringify(value);
  return invalid();
}
export async function projectHash(bytes: Uint8Array): Promise<string> { const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(bytes)); return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, "0")).join(""); }
export async function parseProjectReport(value: unknown, scope: FinanceScope, tenant: string, selected: ProjectSelection): Promise<ProjectReport> {
  if (!record(value)) invalid();
  exactKeys(value, ["schema_version", "qualified_scope", "selection", "currency_policy", "project", "project_totals", "whole_source_settlement", "source_membership", "approved_time", "limitations", "report_digest"]);
  if (value.schema_version !== "project-source-reconciliation-v1" || !record(value.qualified_scope) || !record(value.selection) || !record(value.currency_policy) || !record(value.project) || !record(value.project_totals) || !record(value.whole_source_settlement) || !record(value.limitations) || !hash(value.report_digest)) invalid();
  exactKeys(value.qualified_scope, ["tenant_id", "workspace_id", "organization_id", "legal_entity_id"]);
  const qualified = value.qualified_scope, selectedSource = value.selection;
  if (qualified.tenant_id !== tenant || Object.entries(scope).some(([k, v]) => qualified[k] !== v)) invalid();
  exactKeys(selectedSource, Object.keys(selected)); if (Object.entries(selected).some(([k, v]) => selectedSource[k] !== v)) invalid();
  const policy = value.currency_policy;
  exactKeys(policy, ["currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"]);
  if (!/^[A-Z]{3}$/.test(String(policy.currency_code)) || typeof policy.currency_precision !== "number" || !Number.isSafeInteger(policy.currency_precision) || policy.currency_precision < 0 || policy.currency_precision > 8 || policy.currency_rounding_policy !== "ROUND_HALF_UP" || typeof policy.currency_registry_version !== "string" || !policy.currency_registry_version || !hash(policy.currency_registry_digest)) invalid();
  exactKeys(value.project, ["id", "project_code", "dimension_id", "value_id"]);
  if (value.project.id !== selected.project_id || Object.values(value.project).some(v => typeof v !== "string" || !v)) invalid();
  const totals = value.project_totals, cash = value.whole_source_settlement;
  exactKeys(totals, ["wage_cost_minor", "revenue_minor", "source_margin_minor"]);
  const cost = BigInt(minor(totals.wage_cost_minor)), revenue = BigInt(minor(totals.revenue_minor));
  if (revenue <= 0n || BigInt(minor(totals.source_margin_minor, true)) !== revenue - cost) invalid();
  exactKeys(cash, ["wage_accrued_minor", "wage_paid_minor", "wage_liability_minor", "invoice_minor", "collected_minor", "ar_outstanding_minor", "per_project_cash_allocated"]);
  for (const k of Object.keys(cash).filter(k => k !== "per_project_cash_allocated")) minor(cash[k]);
  if (cash.per_project_cash_allocated !== false || BigInt(cash.wage_accrued_minor as string) < cost || BigInt(cash.invoice_minor as string) < revenue || BigInt(cash.wage_paid_minor as string) + BigInt(cash.wage_liability_minor as string) !== BigInt(cash.wage_accrued_minor as string) || BigInt(cash.collected_minor as string) + BigInt(cash.ar_outstanding_minor as string) !== BigInt(cash.invoice_minor as string)) invalid();
  const limits = { private_earnings_digest_recomputed: false, private_personnel_rows_included: false, original_time_request_digest_recomputed: false, audit_chain_recomputed: false, comprehensive_project_profit_and_loss: false, bank_transfer_proven: false, country_tax_packs: 0, performance_comparison_accepted: false };
  if (canonicalProject(value.limitations) !== canonicalProject(limits)) invalid();
  if (!Array.isArray(value.source_membership) || value.source_membership.length < 2 || value.source_membership.length > 200 || !Array.isArray(value.approved_time) || !value.approved_time.length || value.approved_time.length > 1000) invalid();
  const ids = new Set<string>(), entries = new Set<string>(), effects = new Set<string>();
  for (const item of value.source_membership) { if (!record(item)) invalid(); exactKeys(item, ["id", "plan_digest", "entry_id", "effect_id", "validation_digest"]);
    if (typeof item.id !== "string" || !/^(HC1-|HC1P-|PB1-|PB1C-)/.test(item.id) || typeof item.entry_id !== "string" || !item.entry_id || typeof item.effect_id !== "string" || !item.effect_id || !hash(item.plan_digest) || !hash(item.validation_digest) || ids.has(item.id) || entries.has(item.entry_id) || effects.has(item.effect_id)) invalid(); ids.add(item.id); entries.add(item.entry_id); effects.add(item.effect_id); }
  if (!ids.has(selected.payrun_id) || !ids.has(selected.invoice_id)) invalid();
  const timeIds = new Set<string>(); for (const item of value.approved_time) { if (!record(item)) invalid(); exactKeys(item, ["id", "source_digest"]); if (typeof item.id !== "string" || !item.id || !hash(item.source_digest) || timeIds.has(item.id)) invalid(); timeIds.add(item.id); }
  const { report_digest, ...body } = value;
  if (await projectHash(new TextEncoder().encode(canonicalProject(body))) !== report_digest) invalid();
  return value as unknown as ProjectReport;
}
export function projectMoney(value: string, precision: number, locale: Locale): string { minor(value, true); const negative = value.startsWith("-"), digits = (negative ? value.slice(1) : value).padStart(precision + 1, "0"); return formatExactDecimal(`${negative ? "-" : ""}${precision ? digits.slice(0, -precision) + "." + digits.slice(-precision) : digits}`, locale); }
function path(selected: ProjectSelection, evidence = false) { return `/api/v1/project-source-reconciliation/${evidence ? "evidence" : "report"}?${new URLSearchParams({ ...selected })}`; }
export async function loadProjectReport(session: BrowserAdminSession, scope: FinanceScope, selected: ProjectSelection): Promise<ProjectReport> { const response = await financeRequest(session, scope, path(selected)); if (!record(response)) invalid(); return parseProjectReport(response.report, scope, session.tenantId, selected); }
export async function loadProjectEvidence(session: BrowserAdminSession, scope: FinanceScope, selected: ProjectSelection, expectedReport: string): Promise<{ bytes: Uint8Array; sha256: string }> {
  const response = await fetch(path(selected, true), { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id } });
  if (!response.ok) throw new AdminApiError(response.status, `http_${response.status}`);
  const size = response.headers.get("Content-Length"), expected = response.headers.get("X-ReconForge-Raw-SHA256");
  if (!size || !/^[1-9]\d*$/.test(size) || Number(size) > 67108864 || !hash(expected) || response.headers.get("X-ReconForge-Report-Digest") !== expectedReport) invalid();
  const reader = response.body?.getReader(); if (!reader) invalid(); const parts: Uint8Array[] = []; let length = 0;
  try { for (;;) { const { done, value } = await reader.read(); if (done) break; length += value.byteLength; if (length > Number(size)) invalid(); parts.push(value); } } catch (error) { await reader.cancel(); throw error; } finally { reader.releaseLock(); }
  if (length !== Number(size)) invalid(); const bytes = new Uint8Array(length); let offset = 0; for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  if (await projectHash(bytes) !== expected) invalid();
  // Raw native integers are retained unchanged for the standalone oracle. The
  // browser verifies only the string-money summary; it never rewrites raw rows.
  const original: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); if (!record(original)) invalid();
  if (original.schema_version !== "project-source-reconciliation-evidence-v1" || original.native_execution_proven !== true || original.financial_writes !== false || original.private_personnel_reads !== false || original.private_payroll_command_receipts_exported !== false || !hash(original.evidence_digest) || response.headers.get("X-ReconForge-Evidence-Digest") !== original.evidence_digest) invalid();
  const report = await parseProjectReport(original.report, scope, session.tenantId, selected); if (report.report_digest !== expectedReport) invalid();
  return { bytes, sha256: expected };
}

export interface ProjectCloseDiagnostic {
  schema_version: "project-source-close-diagnostic-v1"; qualified_scope: ProjectReport["qualified_scope"]; selection: ProjectSelection;
  source_report_digest: string; currency_policy: ProjectReport["currency_policy"]; project_totals: ProjectReport["project_totals"];
  whole_source_obligations: ProjectReport["whole_source_settlement"]; source_membership: ProjectReport["source_membership"];
  whole_time_claims: { time_id: string; time_digest: string; wage_claim: { owner_id: string; sequence: number; state: "Consumed" }; billing_claim: { owner_id: string; sequence: number; state: "Consumed" } }[];
  observed_native_periods: { tenant_id: string; id: string; application_workspace_id: string; name: string; start_date: string; end_date: string; status: "Open" | "Soft Closed" | "Closed"; updated_at: string }[];
  source_obligations_settled: boolean; findings: string[]; coverage: string; period_capture_scope: string;
  limitations: Record<string, unknown>; diagnostic_digest: string;
}
export async function parseProjectCloseDiagnostic(value: unknown, report: ProjectReport): Promise<ProjectCloseDiagnostic> {
  if (!record(value)) invalid();
  exactKeys(value, ["schema_version", "qualified_scope", "selection", "source_report_digest", "currency_policy", "project_totals", "whole_source_obligations", "whole_time_claims", "source_membership", "observed_native_periods", "source_obligations_settled", "findings", "coverage", "period_capture_scope", "limitations", "diagnostic_digest"]);
  if (value.schema_version !== "project-source-close-diagnostic-v1" || value.source_report_digest !== report.report_digest || !hash(value.diagnostic_digest)
      || canonicalProject(value.qualified_scope) !== canonicalProject(report.qualified_scope) || canonicalProject(value.selection) !== canonicalProject(report.selection)
      || canonicalProject(value.currency_policy) !== canonicalProject(report.currency_policy) || canonicalProject(value.project_totals) !== canonicalProject(report.project_totals)
      || canonicalProject(value.whole_source_obligations) !== canonicalProject(report.whole_source_settlement) || canonicalProject(value.source_membership) !== canonicalProject(report.source_membership)) invalid();
  if (!Array.isArray(value.whole_time_claims) || value.whole_time_claims.length !== report.approved_time.length) invalid();
  const claims = value.whole_time_claims;
  for (const [index, time] of report.approved_time.entries()) { const row = claims[index]; if (!record(row)) invalid(); exactKeys(row, ["time_id", "time_digest", "wage_claim", "billing_claim"]);
    if (row.time_id !== time.id || row.time_digest !== time.source_digest) invalid();
    for (const [family, owner] of [["wage_claim", report.selection.payrun_id], ["billing_claim", report.selection.invoice_id]] as const) { const claim = row[family]; if (!record(claim)) invalid(); exactKeys(claim, ["owner_id", "sequence", "state"]); if (claim.owner_id !== owner || claim.state !== "Consumed" || typeof claim.sequence !== "number" || !Number.isSafeInteger(claim.sequence) || claim.sequence < 2) invalid(); }
  }
  if (!Array.isArray(value.observed_native_periods) || value.observed_native_periods.length !== 1) invalid();
  const period = value.observed_native_periods[0]; if (!record(period)) invalid(); exactKeys(period, ["tenant_id", "id", "application_workspace_id", "name", "start_date", "end_date", "status", "updated_at"]);
  if (period.tenant_id !== report.qualified_scope.tenant_id || period.id !== report.selection.period_id || period.application_workspace_id !== report.qualified_scope.workspace_id
      || typeof period.name !== "string" || !period.name || typeof period.start_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(period.start_date)
      || typeof period.end_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(period.end_date) || period.start_date > period.end_date
      || !["Open", "Soft Closed", "Closed"].includes(String(period.status)) || typeof period.updated_at !== "string" || !period.updated_at) invalid();
  const findings = [...(BigInt(report.whole_source_settlement.wage_liability_minor) !== 0n ? ["selected_payrun_wages_outstanding"] : []), ...(BigInt(report.whole_source_settlement.ar_outstanding_minor) !== 0n ? ["selected_invoice_receivable_outstanding"] : [])];
  if (canonicalProject(value.findings) !== canonicalProject(findings) || value.source_obligations_settled !== (findings.length === 0)
      || value.coverage !== "one-selected-original-payrun-and-invoice-with-identical-whole-approved-time" || value.period_capture_scope !== "one-readonly-statement-snapshot-without-period-row-locks") invalid();
  const limits = { formal_close_workflow_assessed: false, whole_period_membership_proven: false, comprehensive_project_profit_and_loss: false, private_earnings_formula_recomputed: false, per_project_cash_allocated: false, bank_transfer_proven: false, country_statutory_packs: 0, financial_writes: false, performance_comparison_accepted: false };
  if (canonicalProject(value.limitations) !== canonicalProject(limits)) invalid();
  const { diagnostic_digest, ...body } = value;
  if (await projectHash(new TextEncoder().encode(canonicalProject(body))) !== diagnostic_digest) invalid();
  return value as unknown as ProjectCloseDiagnostic;
}
function closePath(selected: ProjectSelection, evidence = false) { return `/api/v1/project-source-reconciliation/close-diagnostics${evidence ? "/evidence" : ""}?${new URLSearchParams({ ...selected })}`; }
export async function loadProjectCloseDiagnostic(session: BrowserAdminSession, scope: FinanceScope, selected: ProjectSelection, report: ProjectReport): Promise<ProjectCloseDiagnostic> {
  await parseProjectReport(report, scope, session.tenantId, selected);
  const response = await financeRequest(session, scope, closePath(selected)); if (!record(response)) invalid();
  return parseProjectCloseDiagnostic(response.diagnostic, report);
}
export async function loadProjectCloseEvidence(session: BrowserAdminSession, scope: FinanceScope, selected: ProjectSelection, report: ProjectReport, diagnostic: ProjectCloseDiagnostic): Promise<{ bytes: Uint8Array; sha256: string }> {
  await parseProjectReport(report, scope, session.tenantId, selected); await parseProjectCloseDiagnostic(diagnostic, report);
  const response = await fetch(closePath(selected, true), { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json", "X-ReconForge-Tenant": session.tenantId, "X-ReconForge-Workspace": scope.workspace_id, "X-ReconForge-Organization": scope.organization_id, "X-ReconForge-Legal-Entity": scope.legal_entity_id } });
  if (!response.ok) throw new AdminApiError(response.status, `http_${response.status}`);
  const size = response.headers.get("Content-Length"), expected = response.headers.get("X-ReconForge-Raw-SHA256");
  if (!size || !/^[1-9]\d*$/.test(size) || Number(size) > 67108864 || !hash(expected) || response.headers.get("X-ReconForge-Report-Digest") !== report.report_digest || response.headers.get("X-ReconForge-Diagnostic-Digest") !== diagnostic.diagnostic_digest) invalid();
  const reader = response.body?.getReader(); if (!reader) invalid(); const parts: Uint8Array[] = []; let length = 0;
  try { for (;;) { const { done, value } = await reader.read(); if (done) break; length += value.byteLength; if (length > Number(size)) invalid(); parts.push(value); } } catch (error) { await reader.cancel(); throw error; } finally { reader.releaseLock(); }
  if (length !== Number(size)) invalid(); const bytes = new Uint8Array(length); let offset = 0; for (const part of parts) { bytes.set(part, offset); offset += part.length; }
  if (await projectHash(bytes) !== expected) invalid();
  const original: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (!record(original) || original.schema_version !== "project-source-close-evidence-v1" || original.native_execution_proven !== true || original.financial_writes !== false || original.private_personnel_reads !== false || !hash(original.evidence_digest) || response.headers.get("X-ReconForge-Evidence-Digest") !== original.evidence_digest) invalid();
  const retained = await parseProjectCloseDiagnostic(original.diagnostic, report); if (retained.diagnostic_digest !== diagnostic.diagnostic_digest) invalid();
  // Preserve the complete original byte export. Native integer/source custody is
  // independently verified by the stdlib oracle, rather than JSON re-encoding.
  return { bytes, sha256: expected };
}
