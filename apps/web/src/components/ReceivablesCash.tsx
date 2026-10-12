import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";
import { formatArMoney, hasCapturedPolicy, requireMoneyAffinity, type ArMoneyRecord, type ArMinor } from "../receivables-money";
import { ReceivablesPolicy } from "./ReceivablesPolicy";
import { arTranslate, type ArMessage } from "../receivables-i18n";
import { arFetch, cashAllocationRequest, cashReceiptRequest, loadCashCustomer, loadCashExposure, loadCashInvoice, loadCashPage, loadReceipt, parseReceipt, type ArCustomer, type ArInvoice, type ArPage, type ArReceipt, type CashRequest, type ReceivablesIdentity } from "../receivables-data";
import type { Locale } from "../types";

export function ReceivablesCash({ invoiceId, workspace, identity, locale, onLockChange, onAccessRefresh, onChanged }: { invoiceId: string; workspace: string; identity: ReceivablesIdentity; locale: Locale; onLockChange: (locked: boolean) => void; onAccessRefresh: () => void; onChanged: () => void }) {
  const auth = useBrowserSession();
  const t = (key: ArMessage) => arTranslate(locale, key);
  const [invoice, setInvoice] = useState<ArInvoice | null>(null);
  const [customer, setCustomer] = useState<ArCustomer | null>(null);
  const [exposure, setExposure] = useState<ArMinor | null>(null);
  const [page, setPage] = useState<ArPage<ArReceipt> | null>(null);
  const [offset, setOffset] = useState(0);
  const [receipt, setReceipt] = useState<ArReceipt | null>(null);
  const [receiptId, setReceiptId] = useState("");
  const [number, setNumber] = useState("");
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState("");
  const [initialAllocation, setInitialAllocation] = useState("0");
  const [allocation, setAllocation] = useState("");
  const [review, setReview] = useState<CashRequest | null>(null);
  const [pending, setPending] = useState<CashRequest | null>(null);
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ArMessage | null>(null);
  const [notice, setNotice] = useState<"cashSaved" | "cashRecovered" | null>(null);
  const [created, setCreated] = useState(false);
  const alive = useRef(true), mutation = useRef(false), readEpoch = useRef(0);
  const errorRef = useRef<HTMLDivElement>(null);
  const reviewRef = useRef<HTMLDivElement>(null);
  const current = () => alive.current && auth.isCurrent(auth.revision);
  const allowed = identity.human && identity.permissions.includes("receivables.manage");
  const elevated = Boolean(auth.stepUpExpiresAt && Date.parse(auth.stepUpExpiresAt) > Date.now());
  const locked = busy || Boolean(pending) || Boolean(review) || notice === "cashRecovered";
  const money = (value: ArMinor | bigint, record: ArMoneyRecord = invoice!) => formatArMoney(value, record, locale, t("minor"));
  useEffect(() => { alive.current = true; return () => { alive.current = false; readEpoch.current++; }; }, []);
  useEffect(() => { onLockChange(locked); return () => onLockChange(false); }, [locked, onLockChange]);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => { if (review && !pending) reviewRef.current?.focus(); }, [review, pending]);
  function fail(caught: unknown) {
    if (!current()) return;
    if (auth.recover(caught, auth.revision)) return;
    if (caught instanceof AdminApiError && caught.status === 403) {
      setInvoice(null); setCustomer(null); setReceipt(null); setPage(null); setReview(null); setPending(null); setNumber(""); setAmount(""); setAllocation(""); onAccessRefresh(); return;
    }
    const key = caught instanceof Error ? caught.message : "";
    setError(["ar_amount_invalid", "ar_major_amount_invalid", "ar_contract_invalid", "cash_balance_invalid", "ar_monetary_policy_unverified", "ar_monetary_policy_mismatch"].includes(key) ? key as ArMessage : caught instanceof AdminApiError && caught.status < 500 ? "failed" : "unavailable");
  }
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController(), epoch = ++readEpoch.current;
    setPage(null); setError(null);
    (async () => {
      const freshInvoice = await loadCashInvoice(auth.session!, workspace, invoiceId, controller.signal);
      const freshCustomer = await loadCashCustomer(auth.session!, workspace, freshInvoice.customer_id, controller.signal);
      const [receipts, balance] = await Promise.all([loadCashPage(auth.session!, workspace, freshCustomer.id, offset, controller.signal), loadCashExposure(auth.session!, workspace, freshCustomer, controller.signal)]);
      if (!controller.signal.aborted && current() && epoch === readEpoch.current) { setInvoice(freshInvoice); setCustomer(freshCustomer); setPage(receipts); setExposure(balance); }
    })().catch((caught) => { if (!controller.signal.aborted && epoch === readEpoch.current) fail(caught); });
    return () => controller.abort();
    // Scope/session changes remount this private component; reads also reject late results.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, workspace, offset, auth.revision]);

  async function readBalances(id: string) {
    const session = auth.session;
    if (!session || !customer) throw new Error("ar_contract_invalid");
    const [freshReceipt, freshInvoice, receipts, balance] = await Promise.all([loadReceipt(session, workspace, id), loadCashInvoice(session, workspace, invoiceId), loadCashPage(session, workspace, customer.id, offset), loadCashExposure(session, workspace, customer)]);
    if (freshReceipt.customer_id !== customer.id || freshReceipt.currency_code !== customer.currency_code) throw new Error("ar_contract_invalid");
    if (current()) { setReceipt(freshReceipt); setReceiptId(id); setInvoice(freshInvoice); setPage(receipts); setExposure(balance); }
  }
  async function selectReceipt() {
    if (!receiptId || mutation.current || locked) return;
    mutation.current = true; setBusy(true); setError(null); setReceipt(null);
    try { await readBalances(receiptId); } catch (caught) { fail(caught); }
    finally { mutation.current = false; if (current()) setBusy(false); }
  }
  async function send(request: CashRequest) {
    if (!auth.session || mutation.current || !allowed || !elevated || attempts >= 3) return;
    mutation.current = true; readEpoch.current++; setBusy(true); setError(null); setNotice(null); setPending(request); setAttempts((value) => value + 1);
    try {
      const result = parseReceipt(await arFetch(auth.session, request.path, workspace, { body: request.body }));
      if (!current()) return;
      await readBalances(result.id);
      if (current()) { setPending(null); setReview(null); setNotice("cashSaved"); setAllocation(""); if (request.kind === "receipt") setCreated(true); onChanged(); }
    } catch (caught) {
      if (!current()) return;
      fail(caught);
      if (caught instanceof AdminApiError && caught.status < 500 && request.kind === "receipt") { setPending(null); setReview(null); setAttempts(0); }
    } finally { mutation.current = false; if (current()) setBusy(false); }
  }
  async function recoverAllocation() {
    if (!pending?.receiptId || mutation.current) return;
    mutation.current = true; setBusy(true); setError(null);
    try { await readBalances(pending.receiptId); if (current()) { setPending(null); setReview(null); setNotice("cashRecovered"); setAllocation(""); onChanged(); } }
    catch (caught) { fail(caught); }
    finally { mutation.current = false; if (current()) setBusy(false); }
  }
  function prepare(event: FormEvent, kind: "receipt" | "allocation") {
    event.preventDefault(); if (!invoice || !customer || locked || !allowed || !elevated) return;
    try { setReview(kind === "receipt" ? cashReceiptRequest(invoice, customer, { number, date, amount, allocation: initialAllocation }, workspace, crypto.randomUUID()) : cashAllocationRequest(receipt!, invoice, allocation)); setError(null); setNotice(null); setAttempts(0); }
    catch (caught) { fail(caught); }
  }
  const open = invoice && ["Approved", "PartiallyPaid"].includes(invoice.status) && BigInt(invoice.outstanding_minor) > 0n;
  let receiptReady = false, allocationReady = false;
  try { if (invoice && customer) { requireMoneyAffinity(invoice, customer); receiptReady = true; } } catch { /* Historical reads remain available. */ }
  try { if (invoice && receipt) { requireMoneyAffinity(invoice, receipt); allocationReady = true; } } catch { /* A receipt carries its own policy. */ }
  return <section className="panel ar-draft ar-cash" aria-label={t("cash")}><h2>{t("cash")}</h2><p>{t("cashIntro")}</p>
    {error ? <div role="alert" tabIndex={-1} ref={errorRef} className="ar-error">{t(error)}</div> : null}
    {notice ? <div role="status"><p>{t(notice)}</p>{notice === "cashRecovered" ? <button type="button" className="secondary-button" onClick={() => { setNotice(null); setAttempts(0); }}>{t("cashAcknowledge")}</button> : null}</div> : null}
    {!invoice || !customer || !page ? <p role="status">{t("loading")}</p> : <>
      <p>{t("customer")}: <strong><bdi>{customer.customer_code} · {customer.name} · {customer.currency_code}</bdi></strong></p><div className="ar-amounts"><strong>{t("cashInvoiceBalance")}: <bdi>{money(invoice.outstanding_minor)}</bdi></strong><span>{t("cashCustomerBalance")}: <bdi>{money(exposure!, { currency_code: customer.currency_code })}</bdi></span></div>
      <ReceivablesPolicy record={invoice} locale={locale} id="cash-money-note" />
      {!receiptReady && hasCapturedPolicy(invoice) ? <p role="status">{t("ar_monetary_policy_mismatch")}</p> : null}
      {!allowed ? <p>{t("cashReadOnly")}</p> : !elevated ? <p>{t("cashReauthNeeded")}</p> : !open ? <p>{t("cashNoOpenInvoice")}</p> : !receiptReady ? null : <form onSubmit={(event) => prepare(event, "receipt")}><h3>{t("cashReceipt")}</h3><fieldset aria-label={t("cashReceipt")} disabled={locked || created}>
        <label>{t("cashNumber")}<input required maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" value={number} onChange={(event) => setNumber(event.target.value)} /></label>
        <label>{t("cashDate")}<input required type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <label>{t("cashAmount")} · {customer.currency_code}<input required inputMode="decimal" dir="ltr" maxLength={32} aria-describedby="cash-money-note" value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
        <label>{t("cashInitialAllocation")} · {invoice.currency_code}<input required inputMode="decimal" dir="ltr" maxLength={32} aria-describedby="cash-money-note" value={initialAllocation} onChange={(event) => setInitialAllocation(event.target.value)} /></label>
      </fieldset>{created ? <button type="button" className="secondary-button" disabled={locked} onClick={() => { setCreated(false); setNumber(""); setAmount(""); setInitialAllocation("0"); setNotice(null); }}>{t("cashNew")}</button> : <button className="primary-button" disabled={locked}>{t("cashReview")}</button>}</form>}
      <h3>{t("cashReceipts")}</h3>{!page.records.length ? <p>{t("cashNoReceipts")}</p> : null}<div className="ar-toolbar"><label>{t("cashSelectReceipt")}<select value={receiptId} disabled={locked} onChange={(event) => { setReceiptId(event.target.value); setReceipt(null); setAllocation(""); setNotice(null); }}><option value="">{t("cashChoose")}</option>{page.records.map((item) => <option key={item.id} value={item.id}>{item.receipt_number} · {money(item.unallocated_minor, item)}</option>)}</select></label><button type="button" className="secondary-button" disabled={locked || !receiptId} onClick={() => void selectReceipt()}>{t("cashSelect")}</button></div>
      <div className="ar-pagination"><button className="secondary-button" type="button" disabled={locked || !offset} onClick={() => { setReceipt(null); setReceiptId(""); setOffset(offset - 25); }}>{t("previous")}</button><span>{t("showing")} {page.total ? offset + 1 : 0}–{Math.min(offset + 25, page.total)} {t("of")} {page.total}</span><button className="secondary-button" type="button" disabled={locked || offset + 25 >= page.total} onClick={() => { setReceipt(null); setReceiptId(""); setOffset(offset + 25); }}>{t("next")}</button></div>
      {receipt ? <><dl className="ar-record"><div><dt>{t("cashNumber")}</dt><dd><bdi>{receipt.receipt_number}</bdi></dd></div><div><dt>{t("cashAllocated")}</dt><dd><bdi>{money(receipt.allocated_minor, receipt)}</bdi></dd></div><div><dt>{t("cashUnallocated")}</dt><dd><bdi>{money(receipt.unallocated_minor, receipt)}</bdi></dd></div></dl><details className="ar-evidence"><summary>{t("evidenceDetails")}</summary><dl className="ar-record"><div><dt>{t("identifier")}</dt><dd><bdi>{receipt.id}</bdi></dd></div><div><dt>{t("version")}</dt><dd>{receipt.row_version}</dd></div></dl></details><ReceivablesPolicy record={receipt} locale={locale} id="cash-allocation-note" />{!allocationReady && hasCapturedPolicy(receipt) ? <p role="status">{t("ar_monetary_policy_mismatch")}</p> : null}{allowed && elevated && open && allocationReady && BigInt(receipt.unallocated_minor) > 0n ? <form onSubmit={(event) => prepare(event, "allocation")}><label>{t("cashAllocation")} · {receipt.currency_code}<input required inputMode="decimal" dir="ltr" maxLength={32} aria-describedby="cash-allocation-note" disabled={locked} value={allocation} onChange={(event) => setAllocation(event.target.value)} /></label><button className="primary-button" disabled={locked}>{t("cashAllocateReview")}</button></form> : null}</> : null}
    </>}
    {review && !pending ? <div className="ar-confirm" role="region" tabIndex={-1} ref={reviewRef} aria-label={t("cashReview")}><p>{t("cashReviewNote")}</p><p><bdi>{customer?.customer_code} · {invoice?.invoice_number}</bdi></p><p><bdi>{review.kind === "receipt" ? `${number} · ${date}` : receipt?.receipt_number}</bdi></p><dl className="ar-record"><div><dt>{review.kind === "receipt" ? t("cashAmount") : t("cashAllocation")}</dt><dd><bdi>{money(review.amount)}</bdi></dd></div><div><dt>{t("cashAllocated")}</dt><dd><bdi>{money(review.allocation)}</bdi></dd></div><div><dt>{t("cashUnallocated")}</dt><dd><bdi>{money((review.kind === "receipt" ? review.amount : BigInt(receipt!.unallocated_minor)) - review.allocation)}</bdi></dd></div></dl><div className="ar-toolbar"><button className="primary-button" type="button" disabled={busy} onClick={() => void send(review)}>{t("cashConfirm")}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setReview(null)}>{t("cancel")}</button></div></div> : null}
    {pending && !busy ? <div className="ar-recovery" role="status"><p>{t(pending.kind === "receipt" ? "cashUnknown" : "checking")}</p>{pending.kind === "allocation" ? <button type="button" className="secondary-button" onClick={() => void recoverAllocation()}>{t("cashReadback")}</button> : attempts < 3 ? <button type="button" className="secondary-button" onClick={() => void send(pending)}>{t("retry")}</button> : <p>{t("cashRetryLimit")}</p>}</div> : null}
  </section>;
}
