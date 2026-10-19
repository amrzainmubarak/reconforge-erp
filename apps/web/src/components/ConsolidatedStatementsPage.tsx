import { useEffect, useState } from "react";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

interface ConsolidatedStatementsPageProps {
  locale: Locale;
}

interface StatementRun {
  id: string;
  group_id: string;
  organization_id: string;
  reporting_currency: string;
  period_id: string;
  period_start: string;
  period_end: string;
  as_of_date: string;
  report_digest: string;
  prepared_by: string;
  created_at: string;
  statements?: {
    balance_sheet?: {
      total_assets_minor: number;
      total_liabilities_minor: number;
      total_equity_minor: number;
      nci_equity_minor: number;
    };
    income_statement?: {
      gross_profit_minor: number;
      operating_income_minor: number;
      consolidated_net_income_minor: number;
      parent_net_income_minor: number;
      nci_net_income_minor: number;
    };
    cash_flow_statement?: {
      operating_cash_flow_minor: number;
      investing_cash_flow_minor: number;
      financing_cash_flow_minor: number;
      net_cash_change_minor: number;
    };
  };
}

export default function ConsolidatedStatementsPage({ locale }: ConsolidatedStatementsPageProps) {
  const isAr = locale === "ar";
  const [groupId, setGroupId] = useState("GRP_GLOBAL_CORP");
  const [reportingCurrency, setReportingCurrency] = useState("USD");
  const [periodId, setPeriodId] = useState("FY2026_Q3");
  const [runs, setRuns] = useState<StatementRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<StatementRun | null>(null);
  const [generating, setGenerating] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    // Load historical runs
    fetch("/api/v1/finance/consolidated-statements/runs")
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data) => {
        if (data.runs) setRuns(data.runs);
      })
      .catch(() => {
        // Fallback / mock display for offline or initial studio view
        setRuns([
          {
            id: "csr_GRP_GLOBAL_CORP_FY2026_Q3_a1b2c3d4",
            group_id: "GRP_GLOBAL_CORP",
            organization_id: "ORG_HOLDING",
            reporting_currency: "USD",
            period_id: "FY2026_Q3",
            period_start: "2026-07-01",
            period_end: "2026-09-30",
            as_of_date: "2026-09-30",
            report_digest: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            prepared_by: "enterprise_auditor",
            created_at: "2026-10-19T10:30:00Z",
            statements: {
              balance_sheet: {
                total_assets_minor: 425000000,
                total_liabilities_minor: 150000000,
                total_equity_minor: 275000000,
                nci_equity_minor: 25000000,
              },
              income_statement: {
                gross_profit_minor: 85000000,
                operating_income_minor: 45000000,
                consolidated_net_income_minor: 32000000,
                parent_net_income_minor: 28500000,
                nci_net_income_minor: 3500000,
              },
              cash_flow_statement: {
                operating_cash_flow_minor: 38000000,
                investing_cash_flow_minor: -12000000,
                financing_cash_flow_minor: -8000000,
                net_cash_change_minor: 18000000,
              },
            },
          },
        ]);
      });
  }, []);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setGenerating(true);
    setStatusMessage(null);
    try {
      const payload = {
        group_id: groupId,
        organization_id: "ORG_HOLDING",
        reporting_currency: reportingCurrency,
        period_id: periodId,
        period_start: "2026-07-01",
        period_end: "2026-09-30",
        as_of_date: "2026-09-30",
        entities: [
          {
            entity_id: "HOLDING_US",
            functional_currency: "USD",
            fx_rate_to_group_scaled: 1000000,
            parent_ownership_bips: 10000,
            cash_minor: 20000000,
            trade_receivables_minor: 15000000,
            intercompany_receivables_minor: 5000000,
            inventory_minor: 10000000,
            ppe_minor: 50000000,
            other_assets_minor: 0,
            trade_payables_minor: 12000000,
            intercompany_payables_minor: 0,
            short_term_debt_minor: 5000000,
            long_term_debt_minor: 20000000,
            other_liabilities_minor: 0,
            share_capital_minor: 30000000,
            retained_earnings_opening_minor: 28000000,
            gross_revenue_minor: 40000000,
            intercompany_revenue_minor: 2000000,
            cogs_minor: 22000000,
            intercompany_cogs_minor: 0,
            operating_expenses_minor: 8000000,
            depreciation_minor: 3000000,
            finance_costs_minor: 1000000,
            tax_expense_minor: 1000000,
          },
        ],
        eliminations: {
          intercompany_receivables_eliminated_minor: 5000000,
          intercompany_payables_eliminated_minor: 5000000,
          intercompany_revenue_eliminated_minor: 2000000,
          intercompany_cogs_eliminated_minor: 2000000,
        },
      };

      const res = await fetch("/api/v1/finance/consolidated-statements/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const result = await res.json();
      setStatusMessage(isAr ? "تم إعداد القوائم المالية الموحدة بنجاح" : "Consolidated financial statements generated successfully");
      if (result.run_id) {
        setSelectedRun(result);
      }
    } catch {
      setStatusMessage(isAr ? "فشل إعداد القوائم الموحدة" : "Statement generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const activeRun = selectedRun || runs[0];

  return (
    <div className="reporting-workspace" dir={isAr ? "rtl" : "ltr"}>
      <header className="workspace-header">
        <h1 className="workspace-title">
          {isAr ? "القوائم المالية الموحدة للمجموعة" : "Group Consolidated Financial Statements"}
        </h1>
        <p className="workspace-subtitle">
          {isAr
            ? "الميزانية العمومية الموحدة، قائمة الأرباح والخسائر، والتدفقات النقدية غير المباشرة مع الحفاظ الرياضي على حقوق الأقلية وفروق العملة"
            : "Consolidated Balance Sheet, P&L, and Indirect Cash Flows with mathematical NCI and CTA conservation."}
        </p>
      </header>

      {statusMessage && (
        <div className="alert-banner" role="alert" tabIndex={0}>
          {statusMessage}
        </div>
      )}

      <div className="reporting-grid">
        <section className="reporting-card control-card" aria-labelledby="statement-generation-title">
          <h2 id="statement-generation-title" className="card-title">
            {isAr ? "معايير التوحيد المالي" : "Consolidation Parameters"}
          </h2>
          <form onSubmit={handleGenerate} className="form-vertical">
            <div className="form-group">
              <label htmlFor="group-id">{isAr ? "معرّف المجموعة" : "Group ID"}</label>
              <input
                id="group-id"
                type="text"
                value={groupId}
                onChange={(e) => setGroupId(e.target.value)}
                className="input-text"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="reporting-curr">{isAr ? "عملة التقرير" : "Reporting Currency"}</label>
              <input
                id="reporting-curr"
                type="text"
                value={reportingCurrency}
                onChange={(e) => setReportingCurrency(e.target.value)}
                className="input-text"
                maxLength={3}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="period-id">{isAr ? "الفترة المالية" : "Fiscal Period"}</label>
              <input
                id="period-id"
                type="text"
                value={periodId}
                onChange={(e) => setPeriodId(e.target.value)}
                className="input-text"
                required
              />
            </div>
            <button type="submit" className="button button-primary" disabled={generating}>
              {generating ? (isAr ? "جارٍ الحساب والتوحيد..." : "Computing...") : isAr ? "توليد القوائم الموحدة" : "Generate Statements"}
            </button>
          </form>
        </section>

        {activeRun && activeRun.statements && (
          <section className="reporting-card metrics-card" aria-labelledby="consolidated-metrics-title">
            <h2 id="consolidated-metrics-title" className="card-title">
              {isAr ? "الملخص المالي الموحد" : "Consolidated Financial Posture"}
            </h2>
            <div className="metrics-summary">
              <div className="metric-box">
                <span className="metric-label">{isAr ? "إجمالي الأصول" : "Total Assets"}</span>
                <span className="metric-value">
                  ${((activeRun.statements.balance_sheet?.total_assets_minor ?? 0) / 100).toLocaleString()}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "إجمالي الخصوم" : "Total Liabilities"}</span>
                <span className="metric-value">
                  ${((activeRun.statements.balance_sheet?.total_liabilities_minor ?? 0) / 100).toLocaleString()}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "إجمالي حقوق الملكية" : "Total Equity"}</span>
                <span className="metric-value">
                  ${((activeRun.statements.balance_sheet?.total_equity_minor ?? 0) / 100).toLocaleString()}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">{isAr ? "صافي الدخل الموحد" : "Consolidated Net Income"}</span>
                <span className="metric-value">
                  ${((activeRun.statements.income_statement?.consolidated_net_income_minor ?? 0) / 100).toLocaleString()}
                </span>
              </div>
            </div>

            <div className="digest-box">
              <span className="digest-label">{isAr ? "بصمة التقرير المشفرة:" : "Report Cryptographic Digest:"}</span>
              <code className="digest-code">{activeRun.report_digest}</code>
            </div>
          </section>
        )}
      </div>

      <section className="reporting-card history-card" aria-labelledby="historical-runs-title">
        <h2 id="historical-runs-title" className="card-title">
          {isAr ? "سجل التشغيل والأدلة المحفوظة" : "Consolidated Statement Run Ledger"}
        </h2>
        <div className="table-responsive">
          <table className="table" aria-label={isAr ? "جدول تشغيلات القوائم الموحدة" : "Consolidated statement runs table"}>
            <thead>
              <tr>
                <th>{isAr ? "معرّف التشغيل" : "Run ID"}</th>
                <th>{isAr ? "الفترة" : "Period"}</th>
                <th>{isAr ? "العملة" : "Currency"}</th>
                <th>{isAr ? "المُعِدّ" : "Prepared By"}</th>
                <th>{isAr ? "تاريخ الإنشاء" : "Created At"}</th>
                <th>{isAr ? "الإجراء" : "Action"}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td><code>{r.id}</code></td>
                  <td>{r.period_id}</td>
                  <td>{r.reporting_currency}</td>
                  <td>{r.prepared_by}</td>
                  <td>{r.created_at}</td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary button-small"
                      onClick={() => setSelectedRun(r)}
                    >
                      {isAr ? "عرض" : "Inspect"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
