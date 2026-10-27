import { useEffect, useState } from "react";
import { useBrowserSession } from "../browserSession";
import type { Locale } from "../types";
import "./FinancialReportingPage.css";

interface StatementRun {
  id: string;
  period_id: string;
  reporting_currency: string;
  report_digest: string;
  prepared_by: string;
  created_at: string;
  statements: {
    balance_sheet: { total_assets_minor: number; total_liabilities_minor: number; equity: { total_equity_minor: number } };
    income_statement: { consolidated_net_profit_minor: number };
  };
}
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.trim().length > 0 && value.length <= 500;
const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value);
function parseRuns(value: unknown): StatementRun[] {
  if (!object(value) || !Array.isArray(value.runs) || value.runs.length > 1000 || value.total_count !== value.runs.length) throw new Error("statement_runs_invalid");
  const ids = new Set<string>();
  return value.runs.map(run => {
    if (!object(run) || !text(run.id) || ids.has(run.id) || !text(run.period_id) || !text(run.prepared_by) || !text(run.created_at)
      || typeof run.reporting_currency !== "string" || !/^[A-Z]{3}$/.test(run.reporting_currency)
      || typeof run.report_digest !== "string" || !/^[a-f0-9]{64}$/.test(run.report_digest) || !object(run.statements)) throw new Error("statement_run_invalid");
    const bs = run.statements.balance_sheet, income = run.statements.income_statement;
    if (!object(bs) || !integer(bs.total_assets_minor) || !integer(bs.total_liabilities_minor) || !object(bs.equity) || !integer(bs.equity.total_equity_minor)
      || !object(income) || !integer(income.consolidated_net_profit_minor)
      || BigInt(bs.total_assets_minor) !== BigInt(bs.total_liabilities_minor) + BigInt(bs.equity.total_equity_minor)) throw new Error("statement_amounts_invalid");
    ids.add(run.id);
    return run as unknown as StatementRun;
  });
}

export default function ConsolidatedStatementsPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <StatementSession key={auth.revision} locale={locale} />;
}
function StatementSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), isAr = locale === "ar";
  const [runs, setRuns] = useState<StatementRun[]>([]), [selected, setSelected] = useState<StatementRun | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState(false), [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setRuns([]); setSelected(null); setError(false);
    if (!auth.session) return;
    setLoading(true); const revision = auth.revision;
    fetch("/api/v1/finance/consolidated-statements/runs", { credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json", "X-ReconForge-Tenant": auth.session.tenantId } })
      .then(response => { if (!response.ok) throw new Error("statement_read_failed"); return response.json(); })
      .then(value => { const result = parseRuns(value); if (!controller.signal.aborted && auth.isCurrent(revision)) setRuns(result); })
      .catch(() => { if (!controller.signal.aborted && auth.isCurrent(revision)) { setRuns([]); setSelected(null); setError(true); } })
      .finally(() => { if (!controller.signal.aborted && auth.isCurrent(revision)) setLoading(false); });
    return () => controller.abort();
  }, [auth.revision, locale, refresh]);
  const activeRun = selected ?? runs[0];
  const minor = (value: number) => `${value.toLocaleString(isAr ? "ar-EG" : "en-US")} ${activeRun!.reporting_currency}`;
  return <div className="reporting-workspace" dir={isAr ? "rtl" : "ltr"}>
    <header className="workspace-header"><h1>{isAr ? "القوائم المالية الموحدة للمجموعة" : "Group Consolidated Financial Statements"}</h1>
      <p>{isAr ? "قراءة تشغيلات محفوظة من الخادم في مساحة العمل المخوّلة." : "Read stored statement runs from the server in the authorized workspace."}</p></header>
    {!auth.session && <p role="status">{isAr ? "سجّل الدخول إلى مساحة عمل مخوّلة لقراءة القوائم المحفوظة." : "Sign in to an authorized workspace to read stored statements."}</p>}
    {loading && <p role="status">{isAr ? "جارٍ تحميل القوائم..." : "Loading statement runs..."}</p>}
    {error && <div role="alert">{isAr ? "تعذر تحميل قوائم صالحة. تحقق من الجلسة والصلاحيات والاتصال ثم أعد المحاولة. لا تتوفر أرقام مالية موثقة." : "Valid statement runs could not be loaded. Check the session, permissions and connection, then retry. No verified financial figures are available."}</div>}
    <section className="reporting-card" aria-labelledby="statement-generation-title"><h2 id="statement-generation-title">{isAr ? "معايير التوحيد المالي" : "Consolidation Parameters"}</h2>
      <p id="statement-source-required">{isAr ? "توليد القوائم معطّل حتى يتوفر اختيار أرصدة مصدر حقيقية وسياسة عملة. لا تُرسل أرصدة تجريبية." : "Generation is unavailable until real source balances and a currency policy can be selected. No sample balances are submitted."}</p>
      <button type="button" disabled aria-describedby="statement-source-required">{isAr ? "توليد القوائم الموحدة" : "Generate Statements"}</button>
    </section>
    {activeRun && <section className="reporting-card" aria-labelledby="consolidated-metrics-title"><h2 id="consolidated-metrics-title">{isAr ? "الملخص المالي الموحد" : "Consolidated Financial Posture"}</h2>
      <p>{isAr ? "المبالغ بوحدات العملة الصغرى كما وردت من الخادم؛ لا يُفترض عدد منازل عشرية." : "Amounts are shown in currency minor units as returned by the server; no decimal precision is assumed."}</p>
      <dl><dt>{isAr ? "إجمالي الأصول" : "Total Assets"}</dt><dd>{minor(activeRun.statements.balance_sheet.total_assets_minor)}</dd>
        <dt>{isAr ? "إجمالي الخصوم" : "Total Liabilities"}</dt><dd>{minor(activeRun.statements.balance_sheet.total_liabilities_minor)}</dd>
        <dt>{isAr ? "إجمالي حقوق الملكية" : "Total Equity"}</dt><dd>{minor(activeRun.statements.balance_sheet.equity.total_equity_minor)}</dd>
        <dt>{isAr ? "صافي الدخل الموحد" : "Consolidated Net Income"}</dt><dd>{minor(activeRun.statements.income_statement.consolidated_net_profit_minor)}</dd></dl>
      <p>{isAr ? "بصمة التقرير المحفوظة:" : "Stored report digest:"} <code>{activeRun.report_digest}</code></p>
    </section>}
    <section className="reporting-card" aria-labelledby="historical-runs-title"><h2 id="historical-runs-title">{isAr ? "سجل التشغيل والأدلة المحفوظة" : "Consolidated Statement Run Ledger"}</h2>
      <button type="button" disabled={!auth.session || loading} onClick={() => { setRuns([]); setSelected(null); setRefresh(value => value + 1); }}>{isAr ? "تحديث" : "Refresh"}</button>
      {auth.session && !loading && !error && runs.length === 0 && <p role="status">{isAr ? "لا توجد تشغيلات قوائم محفوظة." : "No stored statement runs were returned."}</p>}
      <div className="table-responsive"><table aria-label={isAr ? "جدول تشغيلات القوائم الموحدة" : "Consolidated statement runs table"}><thead><tr>
        <th>{isAr ? "معرّف التشغيل" : "Run ID"}</th><th>{isAr ? "الفترة" : "Period"}</th><th>{isAr ? "العملة" : "Currency"}</th><th>{isAr ? "المُعِدّ" : "Prepared By"}</th><th>{isAr ? "تاريخ الإنشاء" : "Created At"}</th><th>{isAr ? "الإجراء" : "Action"}</th>
      </tr></thead><tbody>{runs.map(run => <tr key={run.id}><td><code>{run.id}</code></td><td>{run.period_id}</td><td>{run.reporting_currency}</td><td>{run.prepared_by}</td><td>{run.created_at}</td><td><button onClick={() => setSelected(run)}>{isAr ? "عرض" : "Inspect"}</button></td></tr>)}</tbody></table></div>
    </section>
  </div>;
}
