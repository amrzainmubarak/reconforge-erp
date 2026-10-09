import { useEffect, useRef, useState } from "react";
import type { BrowserAdminSession } from "../types";
import { AdminApiError } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { reportingCommand, reportingRequest, type ReportingCommand, type ReportingMap } from "../financial-reporting-data";
import { parseEvidencePage, parseReportSnapshot, snapshotMoney, type EvidencePage, type ReportSnapshot } from "../financial-reporting-snapshots";
import { formatExactDecimal } from "../locale-format";
import type { Locale } from "../types";

const labels = {
  en: { title: "Captured enterprise statements", hint: "Capture all currently visible native postings with a reviewed classification. Later and backdated postings do not change the retained report. Evidence loads in bounded pages.", create: "Capture statements", reload: "Reload captured reports", history: "Retained reports", date: "As of", effects: "Posting effects", lines: "Native lines", account: "Account", opening: "Opening", movement: "Movement", closing: "Closing", evidence: "Native posting evidence", next: "Next evidence page", first: "First evidence page", retry: "Retry exact capture", unknown: "Capture outcome is unknown. Retry the retained command before changing scope.", empty: "No captured reports in this scope.", assets: "Assets", liabilities: "Liabilities", equity: "Equity", result: "Unclosed result", income: "Period income", expense: "Period expense", cash: "Closing cash", ordinal: "Evidence sequence", effect: "Posting effect", debit: "Debit", credit: "Credit", digest: "Report digest", source: "Captured evidence digest" },
  ar: { title: "قوائم مؤسسية محفوظة", hint: "احفظ جميع القيود الأصلية المرئية حاليًا باستخدام تصنيف مُراجع. القيود اللاحقة والمؤرخة بأثر رجعي لا تغيّر التقرير المحفوظ. تُحمّل الأدلة في صفحات محدودة.", create: "حفظ القوائم", reload: "تحميل التقارير المحفوظة", history: "التقارير المحفوظة", date: "حتى تاريخ", effects: "الآثار المالية", lines: "السطور الأصلية", account: "الحساب", opening: "افتتاحي", movement: "الحركة", closing: "ختامي", evidence: "أدلة القيود الأصلية", next: "صفحة الأدلة التالية", first: "صفحة الأدلة الأولى", retry: "إعادة محاولة الحفظ الدقيق", unknown: "نتيجة الحفظ غير معروفة. أعد محاولة الأمر المحفوظ قبل تغيير النطاق.", empty: "لا توجد تقارير محفوظة في هذا النطاق.", assets: "الأصول", liabilities: "الالتزامات", equity: "حقوق الملكية", result: "النتيجة غير المقفلة", income: "إيراد الفترة", expense: "مصروف الفترة", cash: "النقد الختامي", ordinal: "تسلسل الدليل", effect: "الأثر المالي", debit: "مدين", credit: "دائن", digest: "بصمة التقرير", source: "بصمة الأدلة المحفوظة" },
};
interface Props { locale: Locale; session: BrowserAdminSession; scope: FinanceScope; mapping: ReportingMap; periodId: string; asOfDate: string; locked: boolean; onLock: (value: boolean) => void; onError: (error: unknown) => void }

export default function FinancialReportSnapshotsPanel({ locale, session, scope, mapping, periodId, asOfDate, locked, onLock, onError }: Props) {
  const t = labels[locale], mounted = useRef(true), operation = useRef(false);
  const [pending, setPending] = useState<ReportingCommand | null>(null), [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ReportSnapshot | null>(null), [page, setPage] = useState<EvidencePage | null>(null);
  const [history, setHistory] = useState<{ id: string; as_of_date: string; effect_count: number; report_digest: string }[]>([]), [historyAfter, setHistoryAfter] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const money = (value: string) => report?.currency_policy ? `${formatExactDecimal(snapshotMoney(value, report.currency_policy.currency_precision), locale)} ${report.currency_policy.currency_code}` : "—";
  async function fetchPage(value: ReportSnapshot, after = 0) {
    const response = await reportingRequest(session, scope, `/api/v1/financial-reporting/snapshots/${encodeURIComponent(value.id)}/evidence?${new URLSearchParams({ expected_digest: value.report_digest, after: String(after), limit: "20" })}`);
    const result = parseEvidencePage(response.evidence, value, after);
    if (after > 0 && (page?.report_digest !== value.report_digest || page.next_after !== after || result.previous_digest !== page.items[page.items.length - 1]?.chain_digest)) throw new Error("captured_evidence_predecessor_invalid");
    for (const row of result.items) {
      const bytes = new TextEncoder().encode(JSON.stringify([row.previous_digest, row.ordinal, row.effect_id, row.validation_digest]));
      const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(byte => byte.toString(16).padStart(2, "0")).join("");
      if (digest !== row.chain_digest) throw new Error("captured_evidence_chain_invalid");
    }
    if (mounted.current) setPage(result);
  }
  async function run(action: () => Promise<void>, captureCommand?: ReportingCommand) {
    if (operation.current) return; operation.current = true; setBusy(true); onLock(true);
    let unresolved = false;
    try { await action(); }
    catch (error) {
      unresolved = Boolean(captureCommand && (!(error instanceof AdminApiError) || error.status >= 500));
      if (mounted.current && unresolved) setPending(captureCommand!); else if (mounted.current) { setPending(null); onError(error); }
    } finally { operation.current = false; if (mounted.current) setBusy(false); onLock(unresolved); }
  }
  async function capture(command: ReportingCommand) {
    await run(async () => {
      const response = await reportingRequest(session, scope, command.path, command);
      const value = parseReportSnapshot(response.snapshot, scope);
      if (value.map_id !== mapping.id || value.map_digest !== mapping.map_digest) throw new Error("captured_map_affinity_invalid");
      if (mounted.current) { setReport(value); setPending(null); setPage(null); }
      await fetchPage(value);
    }, command);
  }
  async function loadHistory(after = "") {
    await run(async () => {
      const response = await reportingRequest(session, scope, `/api/v1/financial-reporting/snapshots?${new URLSearchParams({ limit: "20", after_id: after })}`);
      if (!Array.isArray(response.snapshots) || response.snapshots.length > 20 || response.snapshots.some(row => typeof row !== "object" || row === null || typeof row.id !== "string" || typeof row.effect_count !== "number" || !Number.isSafeInteger(row.effect_count) || row.effect_count < 0 || typeof row.report_digest !== "string" || !/^[0-9a-f]{64}$/.test(row.report_digest))) throw new Error("captured_history_invalid");
      if (mounted.current) { setHistory(response.snapshots); setHistoryAfter(after); }
    });
  }
  const figures = report ? [[t.assets, report.balance_sheet.assets_minor], [t.liabilities, report.balance_sheet.liabilities_minor], [t.equity, report.balance_sheet.equity_minor], [t.result, report.balance_sheet.accumulated_unclosed_result_minor], [t.income, report.income_statement.income_minor], [t.expense, report.income_statement.expense_minor], [t.cash, report.cash_movements.closing_minor]] : [];
  return <section className="panel report-snapshot-panel" aria-label={t.title}>
    <h2>{t.title}</h2><p>{t.hint}</p>
    {pending && <aside role="status"><p>{t.unknown}</p><code dir="ltr">{pending.commandId}</code><button disabled={busy} onClick={() => void capture(pending)}>{t.retry}</button></aside>}
    <button disabled={locked || busy || !periodId || !asOfDate} onClick={() => void capture(reportingCommand("/api/v1/financial-reporting/snapshots", { map_id: mapping.id, period_id: periodId, as_of_date: asOfDate }))}>{t.create}</button>
    <button disabled={locked || busy} onClick={() => void loadHistory()}>{t.reload}</button>
    {historyAfter && <button disabled={locked || busy} onClick={() => void loadHistory()}>{locale === "ar" ? "صفحة التقارير الأولى" : "First report page"}</button>}
    {history.length === 20 && <button disabled={locked || busy} onClick={() => void loadHistory(history[history.length - 1].id)}>{locale === "ar" ? "صفحة التقارير التالية" : "Next report page"}</button>}
    {history.length > 0 && <label>{t.history}<select defaultValue="" disabled={locked || busy} onChange={event => { const id = event.target.value; if (!id) return; void run(async () => { const response = await reportingRequest(session, scope, `/api/v1/financial-reporting/snapshots/${encodeURIComponent(id)}`); const value = parseReportSnapshot(response.snapshot, scope); if (mounted.current) { setReport(value); setPage(null); } await fetchPage(value); }); }}><option value="">—</option>{history.map(row => <option key={row.id} value={row.id}>{row.as_of_date} · {row.effect_count} · {row.id}</option>)}</select></label>}
    {report && <>
      <p>{t.effects}: {report.effect_count} · {t.lines}: {report.line_count} · {t.date}: <bdi>{report.as_of_date}</bdi></p>
      <p>{t.digest}: <code dir="ltr">{report.report_digest}</code></p><p>{t.source}: <code dir="ltr">{report.evidence_digest}</code></p>
      <div className="reporting-statement-grid">{figures.map(([label, value]) => <article key={label}><h3>{label}</h3><bdi>{money(value)}</bdi></article>)}</div>
      <div className="reporting-table" role="region" tabIndex={0} aria-label={t.title}><table><caption>{t.title}</caption><thead><tr><th>{t.account}</th><th>{t.opening}</th><th>{t.movement}</th><th>{t.closing}</th><th>{t.lines}</th></tr></thead><tbody>{report.trial_balance.accounts.map(account => <tr key={account.account_id}><td><bdi>{account.account_code} · {account.account_name}</bdi></td><td><bdi>{money(account.opening.balance_minor)}</bdi></td><td><bdi>{money(account.activity.balance_minor)}</bdi></td><td><bdi>{money(account.closing.balance_minor)}</bdi></td><td>{account.line_count}</td></tr>)}</tbody></table></div>
      {page && <section aria-label={t.evidence}><h3>{t.evidence}</h3><p role="status">{page.after + (page.items.length ? 1 : 0)}–{page.after + page.items.length} / {page.effect_count}</p><button disabled={locked || busy || page.after === 0} onClick={() => void run(() => fetchPage(report))}>{t.first}</button><button disabled={locked || busy || page.next_after === null} onClick={() => void run(() => fetchPage(report, page.next_after!))}>{t.next}</button>{page.items.map(item => <details key={item.effect_id}><summary>{t.ordinal} {item.ordinal} · <bdi>{item.effect_id}</bdi></summary><p>{t.effect}: <code dir="ltr">{item.effect.entry_id}</code> · <bdi>{item.effect.snapshot.entry.posting_date}</bdi></p><div className="reporting-table" role="region" tabIndex={0} aria-label={`${t.evidence} ${item.ordinal}`}><table><caption><bdi>{item.effect_id}</bdi></caption><thead><tr><th>{t.account}</th><th>{t.debit}</th><th>{t.credit}</th></tr></thead><tbody>{item.effect.snapshot.lines.map(line => <tr key={line.line_number}><td><bdi>{report.trial_balance.accounts.find(account => account.account_id === line.account_id)?.account_code ?? line.account_id}</bdi></td><td><bdi>{money(line.debit_minor)}</bdi></td><td><bdi>{money(line.credit_minor)}</bdi></td></tr>)}</tbody></table></div></details>)}</section>}
    </>}
  </section>;
}
