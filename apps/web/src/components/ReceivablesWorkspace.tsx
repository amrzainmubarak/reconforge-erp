import { useEffect, useRef, useState, type FormEvent } from "react";
import { FilePlus2, RefreshCw } from "lucide-react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { formatExactDecimal } from "../locale-format";
import { arTranslate, type ArMessage } from "../receivables-i18n";
import { arFetch, draftRequest, invoiceAmounts, loadArIdentity, loadArPage, parseCustomer, parseInvoice, transitionRequest, type ArCustomer, type ArInvoice, type ArPage, type ArRequest, type ReceivablesIdentity } from "../receivables-data";
import type { Locale } from "../types";
import { ReceivablesCash } from "./ReceivablesCash";

function statusMessage(status: string, locale: Locale): string {
  const keys: Record<string, ArMessage> = { Draft: "stateDraft", Submitted: "stateSubmitted", Approved: "stateApproved", PartiallyPaid: "statePartiallyPaid", Paid: "statePaid", Cancelled: "stateCancelled" };
  return keys[status] ? arTranslate(locale, keys[status]) : status;
}

function errorKey(error: unknown): ArMessage {
  if (error instanceof AdminApiError) return error.status === 403 ? "denied" : error.status >= 500 ? "unavailable" : "failed";
  if (error instanceof Error && ["ar_amount_invalid", "ar_quantity_invalid", "ar_contract_invalid"].includes(error.message)) return error.message as ArMessage;
  return "unavailable";
}

export function ReceivablesWorkspace({ locale }: { locale: Locale }) {
  const { revision } = useBrowserSession();
  return <ReceivablesSession key={revision} locale={locale} />;
}

function ReceivablesSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  const t = (key: ArMessage) => arTranslate(locale, key);
  const [tenant, setTenant] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [identity, setIdentity] = useState<ReceivablesIdentity | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [error, setError] = useState<ArMessage | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [reauthPassword, setReauthPassword] = useState("");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && auth.isCurrent(auth.revision);
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    setIdentity(null); setWorkspace(""); setError(null);
    loadArIdentity(auth.session, controller.signal).then((value) => { if (!controller.signal.aborted && auth.isCurrent(auth.revision)) setIdentity(value); }).catch((caught: unknown) => {
      if (!controller.signal.aborted && auth.isCurrent(auth.revision) && !auth.recover(caught, auth.revision)) setError(errorKey(caught));
    });
    return () => controller.abort();
  }, [auth.session, auth.revision, auth.isCurrent, auth.recover, attempt]);

  async function signIn(event: FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError(null);
    try { const session = await beginBrowserAdminSession({ tenantId: tenant, username, password }); if (current()) auth.begin(session, username, auth.revision); }
    catch (caught) { if (current()) setError(errorKey(caught)); }
    finally { if (current()) { setBusy(false); setPassword(""); } }
  }
  async function signOut() {
    if (!auth.session || busy) return; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (current()) auth.clear(auth.revision); }
    catch (caught) { if (current() && !auth.recover(caught, auth.revision)) setError(errorKey(caught)); }
    finally { if (current()) setBusy(false); }
  }
  async function reauthenticate(event: FormEvent) {
    event.preventDefault(); if (!auth.session || busy) return;
    setBusy(true); setError(null);
    try { const expires = await stepUpBrowserAdminSession(auth.session, reauthPassword); if (current()) auth.elevate(expires, auth.revision); }
    catch (caught) { if (current() && !auth.recover(caught, auth.revision)) setError(errorKey(caught)); }
    finally { if (current()) { setBusy(false); setReauthPassword(""); } }
  }
  const readable = identity?.permissions.some((permission) => ["receivables.read", "receivables.manage", "receivables.approve", "receivables.credit_override"].includes(permission));
  return <main id="main-content" className="workbench-content ar-workspace" dir={locale === "ar" ? "rtl" : "ltr"}>
    <section className="workbench-hero workbench-hero--live"><div><p className="eyebrow">{t("live")}</p><h1>{t("title")}</h1><p>{t("intro")}</p></div><FilePlus2 size={36} aria-hidden="true" /></section>
    <p className="live-boundary">{t("boundary")}</p>
    {auth.notice && !auth.session ? <p role="alert">{t("expired")}</p> : null}
    {error ? <div className="ar-error" role="alert"><p>{t(error)}</p>{auth.session ? <button type="button" className="secondary-button" onClick={() => setAttempt((value) => value + 1)}>{t("refresh")}</button> : null}</div> : null}
    {!auth.session ? <section className="panel admin-form"><h2>{t("signIn")}</h2><form onSubmit={(event) => void signIn(event)}>
      <label>{t("tenant")}<input required maxLength={160} value={tenant} onChange={(event) => setTenant(event.target.value)} autoComplete="organization" /></label>
      <label>{t("username")}<input required value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
      <label>{t("password")}<input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
      <button className="primary-button" disabled={busy}>{t("signIn")}</button>
    </form></section> : <>
      <div className="live-freshness"><span>{t("session")}: <strong>{identity?.username ?? auth.username}</strong> · <bdi>{auth.session.tenantId}</bdi></span><button className="secondary-button" type="button" disabled={busy} onClick={() => void signOut()}>{t("signOut")}</button></div>
      {!identity && !error ? <p role="status">{t("loading")}</p> : null}
      {identity?.human && identity.permissions.includes("receivables.manage") ? <section className="panel admin-form" aria-label={t("cashReauth")}><h2>{t("cashReauth")}</h2>{auth.stepUpExpiresAt ? <p role="status">{t("cashReauthReady")}</p> : <><p>{t("cashReauthNote")}</p>{auth.notice === "adminStepUpRequired" ? <p>{t("cashReauthNeeded")}</p> : null}<form onSubmit={(event) => void reauthenticate(event)}><label>{t("password")}<input type="password" required autoComplete="current-password" value={reauthPassword} onChange={(event) => setReauthPassword(event.target.value)} /></label><button className="primary-button" disabled={busy}>{t("cashReauth")}</button></form></>}</section> : null}
      {identity && !readable ? <p role="alert">{t("noRead")}</p> : null}
      {identity && readable ? <><section className="panel ar-scope"><label>{t("workspace")}<select value={workspace} onChange={(event) => setWorkspace(event.target.value)}><option value="">{t("chooseWorkspace")}</option>{identity.workspaces.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>{!identity.workspaces.length ? <p role="status">{t("noWorkspaces")}</p> : null}</section>
        {workspace ? <ReceivablesBody key={workspace} workspace={workspace} identity={identity} locale={locale} onAccessRefresh={() => setAttempt((value) => value + 1)} /> : null}</> : null}
    </>}
  </main>;
}

function ReceivablesBody({ workspace, identity, locale, onAccessRefresh }: { workspace: string; identity: ReceivablesIdentity; locale: Locale; onAccessRefresh: () => void }) {
  const auth = useBrowserSession();
  const t = (key: ArMessage) => arTranslate(locale, key);
  const manage = identity.permissions.includes("receivables.manage");
  const approve = identity.human && identity.permissions.includes("receivables.approve");
  const [customers, setCustomers] = useState<ArPage<ArCustomer> | null>(null);
  const [invoices, setInvoices] = useState<ArPage<ArInvoice> | null>(null);
  const [customerOffset, setCustomerOffset] = useState(0);
  const [invoiceOffset, setInvoiceOffset] = useState(0);
  const [customerId, setCustomerId] = useState("");
  const [number, setNumber] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [price, setPrice] = useState("");
  const [tax, setTax] = useState("0");
  const [selected, setSelected] = useState<ArInvoice | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<ArMessage | null>(null);
  const [notice, setNotice] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<ArRequest | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [cashLocked, setCashLocked] = useState(false);
  const [draftOpen, setDraftOpen] = useState(true);
  const mutationLock = useRef(false);
  const alive = useRef(true);
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  const current = () => alive.current && auth.isCurrent(auth.revision);
  useEffect(() => {
    if (!auth.session) return;
    const controller = new AbortController();
    setCustomers(null); setInvoices(null);
    Promise.all([loadArPage(auth.session, workspace, "customers", customerOffset, parseCustomer, controller.signal), loadArPage(auth.session, workspace, "invoices", invoiceOffset, parseInvoice, controller.signal)]).then(([customerPage, invoicePage]) => {
      if (!controller.signal.aborted && auth.isCurrent(auth.revision)) { setCustomers(customerPage); setInvoices(invoicePage); setSelected((previous) => invoicePage.records.find((item) => item.id === previous?.id) ?? previous); }
    }).catch((caught: unknown) => { if (!controller.signal.aborted && auth.isCurrent(auth.revision)) { setSelected(null); setConfirming(false); if (!auth.recover(caught, auth.revision)) setError(errorKey(caught)); } });
    return () => controller.abort();
  }, [workspace, customerOffset, invoiceOffset, attempt, auth.session, auth.revision, auth.isCurrent, auth.recover]);
  const customer = customers?.records.find((item) => item.id === customerId);
  let amounts: ReturnType<typeof invoiceAmounts> | null = null;
  try { if (price) amounts = invoiceAmounts(quantity, price, tax); } catch { /* Validation is announced on submission. */ }
  const money = (value: number | bigint, currency: string) => `${formatExactDecimal(String(value), locale)} ${currency} · ${t("minor")}`;

  async function send(request: ArRequest) {
    if (!auth.session || mutationLock.current) return;
    mutationLock.current = true; setBusy(true); setError(null); setNotice(false); setPending(request);
    try {
      const response = await arFetch(auth.session, request.path, workspace, { body: request.body });
      const record = parseInvoice(response);
      if (current()) { setSelected(record); if (request.kind === "draft") setDraftSaved(true); setPending(null); setConfirming(false); setNotice(true); setAttempt((value) => value + 1); }
    } catch (caught) {
      if (current() && !auth.recover(caught, auth.revision)) {
        setError(errorKey(caught));
        // Definitive domain rejection permits correcting the form. Unknown outcomes
        // keep the exact request/key frozen; no automatic financial retry occurs.
        if (caught instanceof AdminApiError && caught.status < 500) setPending(null);
        else if (request.kind !== "draft") { setPending(null); setSelected(null); setConfirming(false); setAttempt((value) => value + 1); }
      }
    } finally { mutationLock.current = false; if (current()) setBusy(false); }
  }
  function save(event: FormEvent) {
    event.preventDefault(); if (!customer || pending || busy) return;
    try { void send(draftRequest({ number, customer, invoiceDate, dueDate, description, quantity, price, tax }, workspace, crypto.randomUUID())); }
    catch (caught) { setError(errorKey(caught)); }
  }
  function refresh() { setError(null); setNotice(false); setConfirming(false); setSelected(null); setAttempt((value) => value + 1); }
  function clearDraft() { setNumber(""); setDescription(""); setPrice(""); setTax("0"); setQuantity("1"); setSelected(null); setNotice(false); setDraftSaved(false); }
  const ownInvoice = selected && [identity.id, identity.username].some((actor) => actor.trim().toLocaleLowerCase() === selected.created_by.trim().toLocaleLowerCase());
  return <>
    <div className="ar-toolbar"><p>{t("permissionChanged")}</p><button type="button" className="secondary-button" disabled={busy || cashLocked} onClick={refresh}><RefreshCw size={15} aria-hidden="true" />{t("refresh")}</button></div>
    {error ? <div id="ar-error" className="ar-error" role="alert" tabIndex={-1} ref={errorRef}><p>{t(error)}</p>{error === "denied" ? <button className="secondary-button" type="button" onClick={onAccessRefresh}>{t("refresh")}</button> : null}</div> : null}
    {pending && !busy ? <section className="panel ar-recovery"><p>{t("checking")}</p><button type="button" className="secondary-button" onClick={() => void send(pending)}>{t("retry")}</button></section> : null}
    {notice ? <p role="status" className="ar-success">{t("saved")}</p> : null}
    {!customers || !invoices ? <p role="status">{t("loading")}</p> : null}
    {manage ? <details className="panel ar-draft" open={draftOpen} onToggle={(event) => setDraftOpen(event.currentTarget.open)}><summary>{t("newInvoice")}</summary><p>{t("customerNote")}</p><form onSubmit={save}>
      <fieldset aria-label={t("draft")} disabled={busy || cashLocked || Boolean(pending) || Boolean(draftSaved)}>
        <label className="ar-wide">{t("customer")}<select required value={customerId} onChange={(event) => setCustomerId(event.target.value)}><option value="">{t("chooseCustomer")}</option>{customers?.records.filter((item) => item.status === "Active").map((item) => <option key={item.id} value={item.id}>{item.customer_code} · {item.name} · {item.currency_code}</option>)}</select></label>
        {customers ? <Pagination offset={customerOffset} total={customers.total} change={(value) => { setCustomerId(""); setCustomerOffset(value); }} t={t} /> : null}
        <label>{t("number")}<input required maxLength={100} value={number} onChange={(event) => setNumber(event.target.value)} /></label>
        <label>{t("invoiceDate")}<input required type="date" value={invoiceDate} onChange={(event) => setInvoiceDate(event.target.value)} /></label>
        <label>{t("dueDate")}<input required type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
        <label className="ar-wide">{t("description")}<input required maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <label>{t("quantity")}<input required inputMode="decimal" dir="ltr" maxLength={64} aria-invalid={error === "ar_quantity_invalid"} value={quantity} onChange={(event) => setQuantity(event.target.value)} aria-describedby="ar-minor-note" /></label>
        <label>{t("price")}<input required inputMode="numeric" dir="ltr" maxLength={64} aria-invalid={error === "ar_amount_invalid"} value={price} onChange={(event) => setPrice(event.target.value)} aria-describedby="ar-minor-note" /></label>
        <label>{t("tax")}<input required inputMode="numeric" dir="ltr" maxLength={64} aria-invalid={error === "ar_amount_invalid"} value={tax} onChange={(event) => setTax(event.target.value)} aria-describedby="ar-minor-note" /></label>
      </fieldset>
      <p id="ar-minor-note" className="ar-hint">{t("minorNote")}</p>
      {amounts && customer ? <div className="ar-amounts"><span>{t("subtotal")}: <bdi>{money(amounts.subtotal, customer.currency_code)}</bdi></span><strong>{t("total")}: <bdi>{money(amounts.total, customer.currency_code)}</bdi></strong></div> : null}
      {draftSaved ? <button className="secondary-button" type="button" disabled={cashLocked} onClick={clearDraft}>{t("newDraft")}</button> : <button className="primary-button" disabled={busy || cashLocked || Boolean(pending) || !customers}>{t("save")}</button>}
    </form></details> : <p>{t("readOnly")}</p>}
    <section className="panel ar-invoices" aria-label={t("invoices")}><h2>{t("invoices")}</h2>{invoices?.records.length === 0 ? <p>{t("empty")}</p> : null}<p id="ar-table-instructions" className="ar-hint">{t("tableNavigation")}</p><div className="table-scroll" role="region" aria-label={t("invoiceTable")} aria-describedby="ar-table-instructions" tabIndex={0}><table className="live-table"><thead><tr><th>{t("number")}</th><th>{t("status")}</th><th>{t("total")}</th><th>{t("due")}</th><th>{t("view")}</th></tr></thead><tbody>{invoices?.records.map((invoice) => <tr key={invoice.id}><th scope="row"><bdi>{invoice.invoice_number}</bdi></th><td>{statusMessage(invoice.status, locale)}</td><td><bdi>{money(invoice.total_minor, invoice.currency_code)}</bdi></td><td><bdi>{invoice.due_date}</bdi></td><td><button type="button" className="secondary-button" disabled={busy || Boolean(pending) || cashLocked} onClick={() => { setSelected(invoice); setDraftOpen(false); setConfirming(false); setNotice(false); }}>{t("view")} <bdi>{invoice.invoice_number}</bdi></button></td></tr>)}</tbody></table></div>{invoices ? <Pagination offset={invoiceOffset} total={invoices.total} change={setInvoiceOffset} t={t} /> : null}</section>
    {selected ? <section className="panel ar-review" aria-label={t("review")}><h2>{t("review")} · <bdi>{selected.invoice_number}</bdi></h2><dl className="ar-record"><div><dt>{t("identifier")}</dt><dd><bdi>{selected.id}</bdi></dd></div><div><dt>{t("status")}</dt><dd>{statusMessage(selected.status, locale)}</dd></div><div><dt>{t("version")}</dt><dd>{selected.row_version}</dd></div><div><dt>{t("creator")}</dt><dd><bdi>{selected.created_by}</bdi></dd></div><div><dt>{t("approver")}</dt><dd><bdi>{selected.approved_by || "—"}</bdi></dd></div><div><dt>{t("total")}</dt><dd><bdi>{money(selected.total_minor, selected.currency_code)}</bdi></dd></div><div><dt>{t("outstanding")}</dt><dd><bdi>{money(selected.outstanding_minor, selected.currency_code)}</bdi></dd></div></dl>
      <ul className="ar-lines">{selected.lines.map((line, index) => <li key={index}><span>{line.description}</span><bdi>{line.quantity} × {money(line.unit_price_minor, selected.currency_code)}</bdi><span>{t("subtotal")}: <bdi>{money(line.line_total_minor, selected.currency_code)}</bdi> · {t("tax")}: <bdi>{money(line.tax_minor, selected.currency_code)}</bdi></span></li>)}</ul>
      {manage && selected.status === "Draft" ? <button className="primary-button" type="button" disabled={busy || Boolean(pending) || !invoices} onClick={() => void send(transitionRequest(selected, "submit"))}>{t("submit")}</button> : null}
      {selected.status === "Submitted" && ownInvoice ? <p>{t("sameActor")}</p> : null}
      {approve && selected.status === "Submitted" && !ownInvoice ? confirming ? <div className="ar-confirm"><p>{t("approvalNote")}</p><strong><bdi>{selected.invoice_number} · {money(selected.total_minor, selected.currency_code)}</bdi></strong><div className="ar-toolbar"><button className="primary-button" type="button" disabled={busy || Boolean(pending) || !invoices} onClick={() => void send(transitionRequest(selected, "approve"))}>{t("confirm")}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setConfirming(false)}>{t("cancel")}</button></div></div> : <button className="primary-button" type="button" disabled={busy || Boolean(pending) || !invoices} onClick={() => setConfirming(true)}>{t("approve")}</button> : null}
    </section> : null}
    {selected && ["Approved", "PartiallyPaid", "Paid"].includes(selected.status) ? <ReceivablesCash key={selected.id} invoiceId={selected.id} workspace={workspace} identity={identity} locale={locale} onLockChange={setCashLocked} onAccessRefresh={onAccessRefresh} onChanged={() => setAttempt((value) => value + 1)} /> : null}
  </>;
}

function Pagination({ offset, total, change, t }: { offset: number; total: number; change: (offset: number) => void; t: (key: ArMessage) => string }) {
  return <div className="ar-pagination"><button className="secondary-button" type="button" disabled={offset === 0} onClick={() => change(Math.max(0, offset - 25))}>{t("previous")}</button><span>{t("showing")} {total ? offset + 1 : 0}–{Math.min(offset + 25, total)} {t("of")} {total}</span><button className="secondary-button" type="button" disabled={offset + 25 >= total} onClick={() => change(offset + 25)}>{t("next")}</button></div>;
}
