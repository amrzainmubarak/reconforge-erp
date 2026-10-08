import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { executeSalesCommand, loadSalesDocument, loadSalesIdentity, loadSalesPage, prepareSalesCommand, salesMoney, salesRequest, type SalesCommand, type SalesDocument, type SalesIdentity, type SalesLine, type SalesPage, type SalesScope } from "../sales-revenue-data";
import { salesTranslate, type SalesMessage } from "../sales-revenue-i18n";
import type { Locale } from "../types";
import "./SalesRevenueWorkspace.css";

export function SalesRevenueWorkspace({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <SalesRevenueSession key={auth.revision} locale={locale} />;
}
function SalesRevenueSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: SalesMessage) => salesTranslate(locale, key);
  const [login, setLogin] = useState({ tenant: "", username: "", password: "" }), [stepPassword, setStepPassword] = useState("");
  const [identity, setIdentity] = useState<SalesIdentity | null>(null), [scopeInput, setScopeInput] = useState<SalesScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<SalesScope | null>(null);
  const [page, setPage] = useState<SalesPage | null>(null), [detail, setDetail] = useState<SalesDocument | null>(null), [selected, setSelected] = useState(""), [cursor, setCursor] = useState(""), [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<SalesCommand | null>(null), [error, setError] = useState<SalesMessage | null>(null), [stale, setStale] = useState(false);
  const [customers, setCustomers] = useState<{ customer_code: string; name: string; currency_code: string }[]>([]);
  const [customer, setCustomer] = useState({ customer_code: "", name: "", currency_code: "", credit_limit_minor: "", payment_terms_days: "0" });
  const [quote, setQuote] = useState({ number: "", customer_code: "", business_date: "", valid_until: "", currency_code: "" });
  const [lines, setLines] = useState<SalesLine[]>([{ description: "", quantity: "", unit_price_minor: "", discount_basis_points: 0 }]);
  const [reason, setReason] = useState(""), [reference, setReference] = useState(""), [businessDate, setBusinessDate] = useState("");
  const [invoice, setInvoice] = useState({ invoice_number: "", invoice_date: "", due_date: "", journal_code: "", period_id: "", receivable_account_code: "", revenue_account_code: "" });
  const [collection, setCollection] = useState({ receipt_number: "", receipt_date: "", journal_code: "", period_id: "", cash_account_code: "" });
  const mounted = useRef(true), lock = useRef(false), alert = useRef<HTMLDivElement>(null), heading = useRef<HTMLHeadingElement>(null);
  const active = () => mounted.current && auth.isCurrent(auth.revision);
  const locked = busy || Boolean(pending);
  const has = (...permissions: string[]) => Boolean(identity?.human && permissions.every((permission) => identity.permissions.includes(permission)));
  const writable = identity?.stepUp && !stale && !locked;
  const read = has("sales.read", "receivables.read", "finance_core.read");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!active() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && caught.status === 403 ? "denied" : "failed"); setStale(true);
    if (caught instanceof AdminApiError && caught.status === 403) { setPage(null); setDetail(null); }
  }
  async function identify() {
    if (!auth.session) return;
    try { const next = await loadSalesIdentity(auth.session); if (active()) { setIdentity(next); setScopeInput((old) => ({ workspace_id: old.workspace_id || next.workspaces[0] || "", organization_id: old.organization_id || next.organizations[0] || "", legal_entity_id: old.legal_entity_id || next.entities[0] || "" })); } } catch (caught) { fail(caught); }
  }
  useEffect(() => { void identify(); }, [auth.session]);
  useEffect(() => {
    if (!auth.session || !scope || !read) return;
    const controller = new AbortController();
    Promise.all([loadSalesPage(auth.session, scope, cursor, controller.signal), selected ? loadSalesDocument(auth.session, scope, selected, controller.signal) : Promise.resolve(null)]).then(([next, document]) => {
      if (controller.signal.aborted || !active()) return; setPage(next); setDetail(document); setStale(false); setError(null);
    }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, read, selected, cursor, reload]);
  async function signIn(event: FormEvent) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true);
    try { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (active()) auth.begin(session, login.username, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (active()) { setBusy(false); setLogin({ ...login, password: "" }); } }
  }
  async function signOut() {
    if (!auth.session || lock.current || pending) return; lock.current = true; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (active()) auth.clear(auth.revision); } catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) setBusy(false); }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || lock.current) return; lock.current = true; setBusy(true);
    try { await stepUpBrowserAdminSession(auth.session, stepPassword); await identify(); } catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) { setBusy(false); setStepPassword(""); } }
  }
  function applyScope(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    if (Object.values(scopeInput).some((value) => !value || value !== value.trim()) || [[scopeInput.workspace_id, identity.workspaces], [scopeInput.organization_id, identity.organizations], [scopeInput.legal_entity_id, identity.entities]].some(([value, grants]) => !(grants as string[]).includes(value as string))) { setError("denied"); return; }
    setScope({ ...scopeInput }); setSelected(""); setDetail(null); setPage(null); setCursor(""); setCustomers([]); setStale(false); setError(null);
  }
  async function loadCustomers() {
    if (!auth.session || !scope || lock.current) return; lock.current = true; setBusy(true);
    try { const value = await salesRequest(auth.session, scope, "/api/v1/receivables/customers?status=Active&limit=100"); if (!value || typeof value !== "object" || !("customers" in value) || !Array.isArray(value.customers)) throw new Error("sales_contract_invalid");
      const rows = value.customers as { customer_code: string; name: string; currency_code: string }[];
      if (rows.some((row) => !row.customer_code || !row.name || !/^[A-Z]{3}$/.test(row.currency_code))) throw new Error("sales_contract_invalid"); if (active()) setCustomers(rows);
    } catch (caught) { fail(caught); } finally { lock.current = false; if (active()) setBusy(false); }
  }
  async function saveCustomer(event: FormEvent) {
    event.preventDefault(); if (!auth.session || !scope || !writable || !has("receivables.manage") || lock.current) return;
    if (!/^(0|[1-9]\d{0,18})$/.test(customer.credit_limit_minor) || !/^\d{1,4}$/.test(customer.payment_terms_days)) { setError("invalid"); return; }
    lock.current = true; setBusy(true);
    try { await salesRequest(auth.session, scope, "/api/v1/receivables/customers", { ...customer, payment_terms_days: Number(customer.payment_terms_days), workspace: scope.workspace_id }); if (active()) { setError(null); setCustomers([]); } }
    catch (caught) { fail(caught); } finally { lock.current = false; if (active()) setBusy(false); }
  }
  async function send(command: SalesCommand) {
    if (!auth.session || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null);
    try { const next = await executeSalesCommand(auth.session, command); if (active()) { setPending(null); setSelected(next.id); setDetail(next); setStale(false); setReason(""); setReload((old) => old + 1); heading.current?.focus(); } }
    catch (caught) { if (!active()) return; if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); } else { setPending(null); fail(caught); } }
    finally { lock.current = false; if (active()) setBusy(false); }
  }
  function command(path: string, fields: Record<string, unknown>) { if (!scope || !writable || lock.current) return; try { void send(prepareSalesCommand(scope, path, fields)); } catch { setError("invalid"); } }
  function transition(action: string, extra: Record<string, unknown> = {}) { if (!detail) return; command(`/api/v1/sales-revenue/documents/${encodeURIComponent(detail.id)}/${action}`, { expected_version: detail.row_version, reason, ...extra }); }
  function create(event: FormEvent) { event.preventDefault(); command("/api/v1/sales-revenue/quotations", { ...quote, lines }); }
  const input = (label: SalesMessage, value: string, change: (value: string) => void, type = "text", required = true) => <label>{t(label)}<input type={type} required={required} value={value} maxLength={type === "password" ? 200 : 160} disabled={locked} onChange={(event) => change(event.target.value)} /></label>;
  const scopeField = (field: keyof SalesScope, label: SalesMessage, grants: string[]) => <label>{t(label)}<select required disabled={locked} value={scopeInput[field]} onChange={(event) => { setScopeInput({ ...scopeInput, [field]: event.target.value }); setScope(null); setDetail(null); setPage(null); }}><option value="">—</option>{grants.map((value) => <option key={value}>{value}</option>)}</select></label>;
  const can = (...permissions: string[]) => Boolean(writable && has(...permissions));
  const total = detail ? salesMoney(detail.total_minor, detail.currency_code, detail.quotation.monetary_policy.precision, locale) : "";
  return <main id="main-content" className="sales-revenue" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={alert}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button type="button" onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    {!auth.session ? <form onSubmit={(event) => void signIn(event)} aria-label={t("signIn")}>{input("tenant", login.tenant, (value) => setLogin({ ...login, tenant: value }))}{input("username", login.username, (value) => setLogin({ ...login, username: value }))}{input("password", login.password, (value) => setLogin({ ...login, password: value }), "password")}<button disabled={busy}>{t("signIn")}</button></form> : <>
      <div className="sales-toolbar"><span>{auth.username}</span><button type="button" disabled={locked} onClick={() => void signOut()}>{t("signOut")}</button></div>
      {!identity?.stepUp && <form onSubmit={(event) => void stepUp(event)}><p>{t("stepRequired")}</p>{input("password", stepPassword, setStepPassword, "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      {identity && read ? <>
        <form onSubmit={applyScope}><fieldset disabled={locked}><legend>{t("scope")}</legend>{scopeField("workspace_id", "workspace", identity.workspaces)}{scopeField("organization_id", "organization", identity.organizations)}{scopeField("legal_entity_id", "entity", identity.entities)}<button>{t("load")}</button></fieldset></form>
        {scope && <>
          <details><summary>{t("customerFoundation")}</summary><form onSubmit={(event) => void saveCustomer(event)}>{input("customerCode", customer.customer_code, (value) => setCustomer({ ...customer, customer_code: value }))}{input("name", customer.name, (value) => setCustomer({ ...customer, name: value }))}{input("currency", customer.currency_code, (value) => setCustomer({ ...customer, currency_code: value.toUpperCase() }))}{input("creditLimit", customer.credit_limit_minor, (value) => setCustomer({ ...customer, credit_limit_minor: value }))}{input("terms", customer.payment_terms_days, (value) => setCustomer({ ...customer, payment_terms_days: value }))}<button disabled={!can("receivables.manage")}>{t("saveCustomer")}</button></form></details>
          <section aria-label={t("title")}><div className="sales-toolbar"><button disabled={locked} onClick={() => { void identify(); setReload((old) => old + 1); }}>{t("refresh")}</button><button disabled={locked} onClick={() => void loadCustomers()}>{t("loadingCustomers")}</button></div>
            {page && <><ul className="sales-list">{page.documents.map((row) => <li key={row.id}><strong>{row.number}</strong><span>{t(row.status)}</span><button disabled={locked} onClick={() => { setSelected(row.id); setReason(""); }}>{t("open")} {row.number}</button></li>)}</ul>{page.documents.length === 0 && <p>{t("empty")}</p>}<div className="sales-toolbar"><button disabled={locked || !cursor} onClick={() => { setCursor(""); setSelected(""); }}>{t("first")}</button><button disabled={locked || !page.next_cursor} onClick={() => { setCursor(page.next_cursor!); setSelected(""); }}>{t("next")}</button></div></>}
          </section>
          <details open={!detail}><summary>{t("create")}</summary><form onSubmit={create}>{input("number", quote.number, (value) => setQuote({ ...quote, number: value }))}<label>{t("customer")}<select required disabled={locked} value={quote.customer_code} onChange={(event) => { const chosen = customers.find((row) => row.customer_code === event.target.value); setQuote({ ...quote, customer_code: event.target.value, currency_code: chosen?.currency_code || "" }); }}><option value="">—</option>{customers.map((row) => <option key={row.customer_code} value={row.customer_code}>{row.name} · {row.customer_code}</option>)}</select></label>{input("date", quote.business_date, (value) => setQuote({ ...quote, business_date: value }), "date")}{input("valid", quote.valid_until, (value) => setQuote({ ...quote, valid_until: value }), "date")}<p>{t("currency")}: {quote.currency_code}</p>
            {lines.map((line, index) => <fieldset key={index}><legend>{t("description")} {index + 1}</legend>{input("description", line.description, (value) => setLines(lines.map((old, i) => i === index ? { ...old, description: value } : old)))}{input("quantity", line.quantity, (value) => setLines(lines.map((old, i) => i === index ? { ...old, quantity: value } : old)))}{input("unit", line.unit_price_minor, (value) => setLines(lines.map((old, i) => i === index ? { ...old, unit_price_minor: value } : old)))}<label>{t("discount")}<input required inputMode="numeric" type="number" min={0} max={9999} step={1} disabled={locked} value={line.discount_basis_points} onChange={(event) => setLines(lines.map((old, i) => i === index ? { ...old, discount_basis_points: Number(event.target.value) } : old))} /></label><button type="button" disabled={locked || lines.length === 1} onClick={() => setLines(lines.filter((_, i) => i !== index))}>{t("remove")}</button></fieldset>)}<button type="button" disabled={locked || lines.length >= 16} onClick={() => setLines([...lines, { description: "", quantity: "", unit_price_minor: "", discount_basis_points: 0 }])}>{t("add")}</button><button disabled={!can("sales.manage")}>{t("create")}</button></form></details>
          {detail && <section className="sales-detail"><h2 tabIndex={-1} ref={heading}>{detail.number} · {t(detail.status)}</h2><strong>{total}</strong><p>{detail.quotation.customer_code}</p><ul>{detail.quotation.lines.map((line, i) => <li key={i}>{line.description} · {line.quantity} · {salesMoney(line.line_total_minor, detail.currency_code, detail.quotation.monetary_policy.precision, locale)}</li>)}</ul>
            {input("reason", reason, setReason)}
            {detail.status === "Draft" && <button disabled={!can("sales.manage")} onClick={() => transition("submit")}>{t("submit")}</button>}
            {detail.status === "Submitted" && <button disabled={!can("sales.approve") || detail.created_by === identity.id} onClick={() => transition("approve")}>{t("approve")}</button>}
            {["Approved", "Ordered"].includes(detail.status) && <form onSubmit={(event) => { event.preventDefault(); transition(detail.status === "Approved" ? "order" : "fulfill", { reference, business_date: businessDate }); }}>{input("reference", reference, setReference)}{input("date", businessDate, setBusinessDate, "date")}<button disabled={!can("sales.manage")}>{t(detail.status === "Approved" ? "order" : "fulfill")}</button></form>}
            {["Draft", "Submitted", "Approved", "Ordered"].includes(detail.status) && <button disabled={!can("sales.manage")} onClick={() => transition("cancel")}>{t("cancel")}</button>}
            {detail.status === "Fulfilled" && <form onSubmit={(event) => { event.preventDefault(); transition("invoice/prepare", invoice); }}>{input("invoiceNumber", invoice.invoice_number, (value) => setInvoice({ ...invoice, invoice_number: value }))}{input("date", invoice.invoice_date, (value) => setInvoice({ ...invoice, invoice_date: value }), "date")}{input("due", invoice.due_date, (value) => setInvoice({ ...invoice, due_date: value }), "date")}{input("journal", invoice.journal_code, (value) => setInvoice({ ...invoice, journal_code: value }))}{input("period", invoice.period_id, (value) => setInvoice({ ...invoice, period_id: value }))}{input("ar", invoice.receivable_account_code, (value) => setInvoice({ ...invoice, receivable_account_code: value }))}{input("revenue", invoice.revenue_account_code, (value) => setInvoice({ ...invoice, revenue_account_code: value }))}<button disabled={!can("sales.manage", "receivables.manage", "finance_core.manage")}>{t("invoice")}</button></form>}
            {detail.status === "InvoicePrepared" && <button disabled={!can("sales.approve", "receivables.approve", "finance_core.validate")} onClick={() => transition("invoice/review")}>{t("reviewInvoice")}</button>}
            {detail.status === "InvoiceReviewed" && <button disabled={!can("sales.manage", "receivables.approve", "finance_core.post")} onClick={() => transition("invoice/post")}>{t("postInvoice")}</button>}
            {detail.status === "Invoiced" && <form onSubmit={(event) => { event.preventDefault(); transition("collection/prepare", collection); }}>{input("receipt", collection.receipt_number, (value) => setCollection({ ...collection, receipt_number: value }))}{input("date", collection.receipt_date, (value) => setCollection({ ...collection, receipt_date: value }), "date")}{input("journal", collection.journal_code, (value) => setCollection({ ...collection, journal_code: value }))}{input("period", collection.period_id, (value) => setCollection({ ...collection, period_id: value }))}{input("cash", collection.cash_account_code, (value) => setCollection({ ...collection, cash_account_code: value }))}<button disabled={!can("sales.manage", "finance_core.manage")}>{t("collection")}</button></form>}
            {detail.status === "CollectionPrepared" && <button disabled={!can("sales.approve", "finance_core.validate")} onClick={() => transition("collection/review")}>{t("reviewCollection")}</button>}
            {detail.status === "CollectionReviewed" && <button disabled={!can("sales.manage", "receivables.manage", "finance_core.post")} onClick={() => transition("collection/post")}>{t("postCollection")}</button>}
            {detail.invoice && <p>{t("outstanding")}: {salesMoney(detail.invoice.outstanding_minor, detail.currency_code, detail.quotation.monetary_policy.precision, locale)}</p>}
            <details><summary>{t("evidence")}</summary>{[detail.invoice_plan, detail.collection_plan].filter(Boolean).map((plan) => <dl key={plan!.id}><dt>{t("journal")}</dt><dd><code>{plan!.entry_id}</code></dd><dt>{t("evidence")}</dt><dd><code>{plan!.posting_effect_id || plan!.plan_digest}</code></dd></dl>)}</details>
            <h3>{t("events")}</h3><ol>{detail.events.map((event) => <li key={event.version}>{event.reason} · {event.actor_id}<code>{event.audit_event_id}</code></li>)}</ol>
          </section>}
          <p className="sales-boundary">{t("stockBoundary")}</p>
        </>}
      </> : <p>{identity ? t("denied") : t("loading")}</p>}
    </>}
  </main>;
}
