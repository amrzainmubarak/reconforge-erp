/** Synthetic period observation over retained original public report membership. */
import original from "./project-source-reconciliation-original-report.json";
import { canonicalProject, projectHash, type ProjectReport } from "./project-source-reconciliation-data";

export async function projectCloseFixture(report = original as ProjectReport) {
  const value = {
    schema_version: "project-source-close-diagnostic-v1", qualified_scope: structuredClone(report.qualified_scope),
    selection: structuredClone(report.selection), source_report_digest: report.report_digest,
    currency_policy: structuredClone(report.currency_policy), project_totals: structuredClone(report.project_totals),
    whole_source_obligations: structuredClone(report.whole_source_settlement), source_membership: structuredClone(report.source_membership),
    whole_time_claims: report.approved_time.map(time => ({ time_id: time.id, time_digest: time.source_digest,
      wage_claim: { owner_id: report.selection.payrun_id, sequence: 2, state: "Consumed" },
      billing_claim: { owner_id: report.selection.invoice_id, sequence: 2, state: "Consumed" } })),
    observed_native_periods: [{ tenant_id: report.qualified_scope.tenant_id, id: report.selection.period_id,
      application_workspace_id: report.qualified_scope.workspace_id, name: "Synthetic observed period",
      start_date: "2026-10-01", end_date: "2026-10-31", status: "Open", updated_at: "2026-10-31T12:00:00+00:00" }],
    source_obligations_settled: report.whole_source_settlement.wage_liability_minor === "0" && report.whole_source_settlement.ar_outstanding_minor === "0",
    findings: [...(report.whole_source_settlement.wage_liability_minor === "0" ? [] : ["selected_payrun_wages_outstanding"]), ...(report.whole_source_settlement.ar_outstanding_minor === "0" ? [] : ["selected_invoice_receivable_outstanding"])],
    coverage: "one-selected-original-payrun-and-invoice-with-identical-whole-approved-time",
    period_capture_scope: "one-readonly-statement-snapshot-without-period-row-locks",
    limitations: { formal_close_workflow_assessed: false, whole_period_membership_proven: false, comprehensive_project_profit_and_loss: false, private_earnings_formula_recomputed: false, per_project_cash_allocated: false, bank_transfer_proven: false, country_statutory_packs: 0, financial_writes: false, performance_comparison_accepted: false },
  };
  return { ...value, diagnostic_digest: await projectHash(new TextEncoder().encode(canonicalProject(value))) };
}
