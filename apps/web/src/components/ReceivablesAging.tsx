import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";
import { agingBuckets, loadArAging, type ArAging, type ArCustomer, type ArInvoice } from "../receivables-data";
import { arTranslate, type ArMessage } from "../receivables-i18n";
import type { Locale } from "../types";

export function ReceivablesAging({ invoice, customer, workspace, locale, disabled, onDenied }: { invoice: ArInvoice; customer: ArCustomer; workspace: string; locale: Locale; disabled: boolean; onDenied: () => void }) {
  const auth = useBrowserSession(), t = (key: ArMessage) => arTranslate(locale, key);
  const [date, setDate] = useState(""), [report, setReport] = useState<ArAging | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<ArMessage | null>(null);
  const controller = useRef<AbortController | null>(null), epoch = useRef(0), alert = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    ++epoch.current; controller.current?.abort(); setReport(null); setError(null); setBusy(false);
    return () => { ++epoch.current; controller.current?.abort(); };
  }, [workspace, invoice.id, invoice.row_version, invoice.outstanding_minor, auth.revision, disabled]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  async function read(event: FormEvent) {
    event.preventDefault(); if (!auth.session || disabled || busy) return;
    controller.current?.abort(); const request = new AbortController(), generation = ++epoch.current;
    controller.current = request; setBusy(true); setReport(null); setError(null);
    try {
      const value = await loadArAging(auth.session, workspace, date, request.signal);
      const item = value.currency_groups.flatMap(group => group.items).find(row => row.invoice_id === invoice.id);
      if (item && (item.invoice_number !== invoice.invoice_number || item.customer_code !== customer.customer_code || item.currency_code !== invoice.currency_code || item.invoice_date !== invoice.invoice_date || item.due_date !== invoice.due_date || BigInt(item.total_minor) !== BigInt(invoice.total_minor) || BigInt(item.outstanding_minor) !== BigInt(invoice.outstanding_minor))) throw new Error("ar_contract_invalid");
      if (!item && BigInt(invoice.outstanding_minor) > 0n && ["Approved", "PartiallyPaid"].includes(invoice.status)) throw new Error("ar_contract_invalid");
      if (!request.signal.aborted && epoch.current === generation && auth.isCurrent(auth.revision)) setReport(value);
    } catch (caught) {
      if (request.signal.aborted || epoch.current !== generation || !auth.isCurrent(auth.revision) || auth.recover(caught, auth.revision)) return;
      if (caught instanceof AdminApiError && caught.status === 403) { setReport(null); onDenied(); }
      setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof Error && caught.message === "ar_contract_invalid" ? "ar_contract_invalid" : "unavailable");
    } finally { if (!request.signal.aborted && epoch.current === generation) setBusy(false); }
  }
  const bucketName = (bucket: typeof agingBuckets[number]) => t(({ Current: "agingCurrent", "1-30": "aging1to30", "31-60": "aging31to60", "61-90": "aging61to90", "90+": "aging90plus" } as const)[bucket]);
  return <section aria-label={t("agingTitle")} dir={locale === "ar" ? "rtl" : "ltr"}>
    <h3>{t("agingTitle")}</h3><p>{t("agingBoundary")}</p>
    <form aria-label={t("agingLoad")} onSubmit={event => void read(event)}>
      <label>{t("agingDate")}<input type="date" required value={date} disabled={disabled || busy} onChange={event => { setDate(event.target.value); setReport(null); setError(null); }} /></label>
      <button disabled={disabled || busy || !date}>{t("agingLoad")}</button>
    </form>
    {busy && <p role="status">{t("loading")}</p>}
    {error && <p role="alert" tabIndex={-1} ref={alert}>{t(error)}</p>}
    {report && <div aria-label={t("agingResults")} role="region"><p>{t("agingDate")}: <bdi>{report.as_of_date}</bdi> · <bdi>{workspace}</bdi></p>
      {!report.currency_groups.length ? <p role="status">{t("agingEmpty")}</p> : report.currency_groups.map(group => <section key={group.currency_code} aria-label={`${t("agingCurrency")} ${group.currency_code}`}>
        <h4><bdi>{group.currency_code}</bdi></h4><p>{t("agingTotal")}: <bdi>{String(group.total_outstanding_minor)} {group.currency_code} · {t("minor")}</bdi></p>
        <dl className="ar-record">{agingBuckets.map(bucket => <div key={bucket}><dt>{bucketName(bucket)}</dt><dd><bdi>{String(group.bucket_totals_minor[bucket])} {group.currency_code} · {t("minor")}</bdi></dd></div>)}</dl>
        <ul>{group.items.map(item => <li key={item.invoice_id}><bdi>{item.invoice_number}</bdi> · <bdi>{item.customer_code}</bdi> · {bucketName(item.bucket)} · <bdi>{String(item.outstanding_minor)} {group.currency_code} · {t("minor")}</bdi></li>)}</ul>
      </section>)}
    </div>}
  </section>;
}
