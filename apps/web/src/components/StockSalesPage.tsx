import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError, beginBrowserAdminSession, endBrowserAdminSession, stepUpBrowserAdminSession } from "../data";
import { loadSalesIdentity, salesMoney, type SalesIdentity, type SalesScope } from "../sales-revenue-data";
import { executeStockCommand, loadStockOrder, loadStockOptions, loadStockOrders, prepareStockCommand, type StockCommand, type StockOptions, type StockOrder, type StockStage } from "../stock-sales-data";
import { stockTranslate, type StockMessage } from "../stock-sales-i18n";
import type { Locale } from "../types";
import "./StockSalesPage.css";

const readPermissions = ["sales.read", "inventory.read", "receivables.read", "finance_core.read"];
const nextAction: Partial<Record<StockStage, { path: string; label: StockMessage; permissions: string[] }>> = {
  Draft: { path: "submit", label: "submit", permissions: ["sales.manage"] },
  Submitted: { path: "approve", label: "approve", permissions: ["sales.approve"] },
  Approved: { path: "reserve", label: "reserve", permissions: ["sales.manage", "inventory.manage"] },
  Reserved: { path: "issue/prepare", label: "prepareIssue", permissions: ["sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"] },
  IssuePrepared: { path: "issue/review", label: "reviewIssue", permissions: ["sales.approve", "inventory.valuation.approve", "finance_core.validate"] },
  IssueReviewed: { path: "deliver", label: "deliver", permissions: ["sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"] },
  Delivered: { path: "invoice/prepare", label: "prepareInvoice", permissions: ["sales.manage", "receivables.manage", "finance_core.manage"] },
  InvoicePrepared: { path: "invoice/review", label: "reviewInvoice", permissions: ["sales.approve", "receivables.approve", "finance_core.validate"] },
  InvoiceReviewed: { path: "invoice/post", label: "postInvoice", permissions: ["sales.manage", "receivables.approve", "finance_core.post"] },
  Invoiced: { path: "collection/prepare", label: "prepareCollection", permissions: ["sales.manage", "finance_core.manage"] },
  CollectionPrepared: { path: "collection/review", label: "reviewCollection", permissions: ["sales.approve", "finance_core.validate"] },
  CollectionReviewed: { path: "collection/post", label: "collect", permissions: ["sales.manage", "receivables.manage", "finance_core.post"] },
};

export function StockSalesPage({ locale }: { locale: Locale }) {
  const auth = useBrowserSession();
  return <StockSalesSession key={auth.revision} locale={locale} />;
}

function StockSalesSession({ locale }: { locale: Locale }) {
  const auth = useBrowserSession(), t = (key: StockMessage) => stockTranslate(locale, key);
  const [login, setLogin] = useState({ tenant: "", username: "", password: "" }), [stepPassword, setStepPassword] = useState("");
  const [identity, setIdentity] = useState<SalesIdentity | null>(null), [scopeInput, setScopeInput] = useState<SalesScope>({ workspace_id: "", organization_id: "", legal_entity_id: "" }), [scope, setScope] = useState<SalesScope | null>(null);
  const [orders, setOrders] = useState<StockOrder[]>([]), [detail, setDetail] = useState<StockOrder | null>(null), [selected, setSelected] = useState(""), [options, setOptions] = useState<StockOptions | null>(null), [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<StockCommand | null>(null), [error, setError] = useState<StockMessage | null>(null), [stale, setStale] = useState(false);
  const [order, setOrder] = useState({ number: "", customer_code: "", customer_reference: "", item_code: "", warehouse_code: "", location_code: "", quantity: "", unit_price_minor: "", currency_code: "", order_date: "", description: "", discount_basis_points: "0" });
  const [reason, setReason] = useState("");
  const [issue, setIssue] = useState({ posting_date: "", period_id: "", policy_code: "" });
  const [invoice, setInvoice] = useState({ invoice_number: "", invoice_date: "", due_date: "", journal_code: "", period_id: "", receivable_account_code: "", revenue_account_code: "" });
  const [collection, setCollection] = useState({ receipt_number: "", receipt_date: "", journal_code: "", period_id: "", cash_account_code: "" });
  const mounted = useRef(true), lock = useRef(false), alert = useRef<HTMLDivElement>(null), heading = useRef<HTMLHeadingElement>(null);
  const active = () => mounted.current && auth.isCurrent(auth.revision), locked = busy || Boolean(pending);
  const has = (...permissions: string[]) => Boolean(identity?.human && permissions.every((permission) => identity.permissions.includes(permission)));
  const read = has(...readPermissions), can = (...permissions: string[]) => Boolean(identity?.stepUp && !stale && !locked && has(...readPermissions, ...permissions));
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!active() || auth.recover(caught, auth.revision)) return;
    setError(caught instanceof AdminApiError && caught.code === "stock_sales_code_invalid" ? "nameHint" : caught instanceof AdminApiError && caught.status === 403 ? "denied" : "failed"); setStale(true);
    if (caught instanceof AdminApiError && caught.status === 403) { setOrders([]); setDetail(null); setOptions(null); }
  }
  async function identify() {
    if (!auth.session) return;
    try { const next = await loadSalesIdentity(auth.session); if (active()) { setIdentity(next); setScopeInput((old) => ({ workspace_id: old.workspace_id || next.workspaces[0] || "", organization_id: old.organization_id || next.organizations[0] || "", legal_entity_id: old.legal_entity_id || next.entities[0] || "" })); } }
    catch (caught) { fail(caught); }
  }
  useEffect(() => { void identify(); }, [auth.session]);
  useEffect(() => {
    if (!auth.session || !scope || !read) return;
    const controller = new AbortController();
    Promise.all([loadStockOrders(auth.session, scope, controller.signal), loadStockOptions(auth.session, scope, controller.signal), selected ? loadStockOrder(auth.session, scope, selected, controller.signal) : Promise.resolve(null)]).then(([rows, choices, document]) => {
      if (controller.signal.aborted || !active()) return;
      setOrders(rows); setOptions(choices); setDetail(document); setError(null); setStale(false);
    }).catch((caught) => { if (!controller.signal.aborted) fail(caught); });
    return () => controller.abort();
  }, [auth.session, scope, read, selected, reload]);
  async function signIn(event: FormEvent) {
    event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true);
    try { const session = await beginBrowserAdminSession({ tenantId: login.tenant, username: login.username, password: login.password }); if (active()) auth.begin(session, login.username, auth.revision); }
    catch (caught) { fail(caught); } finally { lock.current = false; if (active()) { setBusy(false); setLogin((old) => ({ ...old, password: "" })); } }
  }
  async function signOut() {
    if (!auth.session || lock.current || pending) return; lock.current = true; setBusy(true);
    try { await endBrowserAdminSession(auth.session); if (active()) auth.clear(auth.revision); } catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) setBusy(false); }
  }
  async function stepUp(event: FormEvent) {
    event.preventDefault(); if (!auth.session || lock.current || pending) return; lock.current = true; setBusy(true);
    try { await stepUpBrowserAdminSession(auth.session, stepPassword); await identify(); } catch (caught) { fail(caught); }
    finally { lock.current = false; if (active()) { setBusy(false); setStepPassword(""); } }
  }
  function applyScope(event: FormEvent) {
    event.preventDefault(); if (locked || !identity) return;
    if ([[scopeInput.workspace_id, identity.workspaces], [scopeInput.organization_id, identity.organizations], [scopeInput.legal_entity_id, identity.entities]].some(([value, grants]) => !(grants as string[]).includes(value as string))) { setError("denied"); return; }
    setScope({ ...scopeInput }); setOrders([]); setOptions(null); setDetail(null); setSelected(""); setError(null); setStale(false);
  }
  async function send(command: StockCommand) {
    if (!auth.session || lock.current) return; lock.current = true; setBusy(true); setPending(command); setError(null);
    try { const result = await executeStockCommand(auth.session, command); if (active()) { setPending(null); setSelected(result.id); setDetail(result); setReason(""); setStale(false); setReload((old) => old + 1); heading.current?.focus(); } }
    catch (caught) { if (!active()) return; if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); } else { setPending(null); fail(caught); } }
    finally { lock.current = false; if (active()) setBusy(false); }
  }
  function submit(path: string, fields: Record<string, string | number>) {
    if (!scope || !identity?.stepUp || stale || locked || lock.current) return;
    try { void send(prepareStockCommand(scope, path, fields)); } catch { setError("invalid"); }
  }
  function transition(path: string, fields: Record<string, string | number> = {}) {
    if (!detail || !reason.trim()) { setError("invalid"); return; }
    submit(`/api/v1/stock-sales/orders/${encodeURIComponent(detail.id)}/${path}`, { expected_version: detail.row_version, reason, ...fields });
  }
  const input = (label: StockMessage, value: string, update: (value: string) => void, type = "text") => <label>{t(label)}<input required type={type} value={value} disabled={locked} maxLength={type === "password" ? 200 : 500} onChange={(event) => update(event.target.value)} /></label>;
  const choose = (label: StockMessage, value: string, update: (value: string) => void, entries: { value: string; label: string }[]) => <label>{t(label)}<select required disabled={locked} value={value} onChange={(event) => update(event.target.value)}><option value="">—</option>{entries.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}</select></label>;
  const periods = options?.periods.map((row) => ({ value: row.id, label: `${row.name} · ${row.start_date} — ${row.end_date}` })) || [];
  const journals = options?.journals.filter((row) => !detail || row.currency_code === detail.currency_code).map((row) => ({ value: row.journal_code, label: `${row.name} · ${row.journal_code}` })) || [];
  const accounts = (kind: "Asset" | "Income") => options?.accounts.filter((row) => row.account_type === kind).filter((row, index, all) => all.findIndex((value) => value.account_code === row.account_code) === index).map((row) => ({ value: row.account_code, label: `${row.name} · ${row.account_code}` })) || [];
  const action = detail && nextAction[detail.status];
  const actionAllowed = action && can(...action.permissions) && !(detail?.status === "Submitted" && detail.created_by === identity?.id) && !(detail?.status === "IssuePrepared" && detail.issue_preparer_id === identity?.id);
  function perform(event: FormEvent) {
    event.preventDefault(); if (!action || !detail || !actionAllowed) return;
    transition(action.path, detail.status === "Reserved" ? issue : detail.status === "Delivered" ? invoice : detail.status === "Invoiced" ? collection : {});
  }
  return <main id="main-content" className="stock-sales" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h1>{t("title")}</h1><p>{t("intro")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={alert}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button type="button" onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    {!auth.session ? <form aria-label={t("signIn")} onSubmit={(event) => void signIn(event)}>{input("tenant", login.tenant, (value) => setLogin({ ...login, tenant: value }))}{input("username", login.username, (value) => setLogin({ ...login, username: value }))}{input("password", login.password, (value) => setLogin({ ...login, password: value }), "password")}<button disabled={busy}>{t("signIn")}</button></form> : <>
      <div className="stock-sales-toolbar"><span>{auth.username}</span><button type="button" disabled={locked} onClick={() => void signOut()}>{t("signOut")}</button></div>
      {!identity?.stepUp && <form onSubmit={(event) => void stepUp(event)}><p>{t("stepRequired")}</p>{input("password", stepPassword, setStepPassword, "password")}<button disabled={locked}>{t("stepUp")}</button></form>}
      {identity && read ? <>
        <form onSubmit={applyScope}><fieldset disabled={locked}><legend>{t("scope")}</legend>{choose("workspace", scopeInput.workspace_id, (value) => { setScopeInput({ ...scopeInput, workspace_id: value }); setScope(null); }, identity.workspaces.map((value) => ({ value, label: value })))}{choose("organization", scopeInput.organization_id, (value) => { setScopeInput({ ...scopeInput, organization_id: value }); setScope(null); }, identity.organizations.map((value) => ({ value, label: value })))}{choose("entity", scopeInput.legal_entity_id, (value) => { setScopeInput({ ...scopeInput, legal_entity_id: value }); setScope(null); }, identity.entities.map((value) => ({ value, label: value })))}<button>{t("load")}</button></fieldset></form>
        {scope && <>
          <section><button disabled={locked} onClick={() => { void identify(); setReload((old) => old + 1); }}>{t("refresh")}</button><p>{t("listBound")}</p><ul>{orders.map((row) => <li key={row.id}><strong>{row.number}</strong><span>{t(row.status)}</span><button disabled={locked} onClick={() => { setSelected(row.id); setReason(""); }}>{t("open")} {row.number}</button></li>)}</ul>{orders.length === 0 && <p>{t("empty")}</p>}</section>
          <details open={!detail}><summary>{t("create")}</summary><form onSubmit={(event) => { event.preventDefault(); if (!/^[0-9]{1,4}$/.test(order.discount_basis_points)) { setError("invalid"); return; } submit("/api/v1/stock-sales/orders", { ...order, discount_basis_points: Number(order.discount_basis_points) }); }}><p>{t("nameHint")}</p><fieldset><legend>{t("create")}</legend>
            {input("number", order.number, (value) => setOrder({ ...order, number: value }))}
            {choose("customer", order.customer_code, (value) => setOrder({ ...order, customer_code: value, currency_code: options?.customers.find((row) => row.customer_code === value)?.currency_code || "" }), options?.customers.map((row) => ({ value: row.customer_code, label: `${row.name} · ${row.customer_code}` })) || [])}
            {input("reference", order.customer_reference, (value) => setOrder({ ...order, customer_reference: value }))}
            {choose("item", order.item_code, (value) => setOrder({ ...order, item_code: value }), options?.items.map((row) => ({ value: row.item_code, label: `${row.name} · ${row.uom_code}` })) || [])}
            {choose("warehouse", order.warehouse_code, (value) => setOrder({ ...order, warehouse_code: value, location_code: "" }), options?.warehouses.map((row) => ({ value: row.warehouse_code, label: `${row.name} · ${row.warehouse_code}` })) || [])}
            {choose("location", order.location_code, (value) => setOrder({ ...order, location_code: value }), options?.locations.filter((row) => row.warehouse_code === order.warehouse_code).map((row) => ({ value: row.location_code, label: `${row.name} · ${row.location_code}` })) || [])}
            {input("quantity", order.quantity, (value) => setOrder({ ...order, quantity: value }))}{input("unit", order.unit_price_minor, (value) => setOrder({ ...order, unit_price_minor: value }))}{input("discount", order.discount_basis_points, (value) => setOrder({ ...order, discount_basis_points: value }))}{input("date", order.order_date, (value) => setOrder({ ...order, order_date: value }), "date")}{input("description", order.description, (value) => setOrder({ ...order, description: value }))}<p>{t("currency")}: {order.currency_code}</p><button disabled={!can("sales.manage")}>{t("create")}</button>
          </fieldset></form></details>
          {detail && <section><h2 tabIndex={-1} ref={heading}>{detail.number} · {t(detail.status)}</h2><p>{detail.description} · {detail.quantity} · {detail.item_code} · {detail.warehouse_code}/{detail.location_code}</p><dl><dt>{t("total")}</dt><dd>{salesMoney(detail.total_minor, detail.currency_code, detail.monetary_policy.precision, locale)}</dd>{detail.cogs_minor !== null && <><dt>{t("cost")}</dt><dd>{salesMoney(detail.cogs_minor, detail.currency_code, detail.monetary_policy.precision, locale)}</dd></>}</dl>
            {action && <form onSubmit={perform}>{input("reason", reason, setReason)}
              {detail.status === "Reserved" && <fieldset><legend>{t("prepareIssue")}</legend>{input("date", issue.posting_date, (value) => setIssue({ ...issue, posting_date: value }), "date")}{choose("period", issue.period_id, (value) => setIssue({ ...issue, period_id: value }), periods)}{choose("policy", issue.policy_code, (value) => setIssue({ ...issue, policy_code: value }), options?.policies.map((row) => ({ value: row.policy_code, label: `${row.name} · ${row.journal_code}` })) || [])}</fieldset>}
              {detail.status === "Delivered" && <fieldset><legend>{t("prepareInvoice")}</legend>{input("invoiceNumber", invoice.invoice_number, (value) => setInvoice({ ...invoice, invoice_number: value }))}{input("date", invoice.invoice_date, (value) => setInvoice({ ...invoice, invoice_date: value }), "date")}{input("due", invoice.due_date, (value) => setInvoice({ ...invoice, due_date: value }), "date")}{choose("journal", invoice.journal_code, (value) => setInvoice({ ...invoice, journal_code: value }), journals)}{choose("period", invoice.period_id, (value) => setInvoice({ ...invoice, period_id: value }), periods)}{choose("ar", invoice.receivable_account_code, (value) => setInvoice({ ...invoice, receivable_account_code: value }), accounts("Asset"))}{choose("revenue", invoice.revenue_account_code, (value) => setInvoice({ ...invoice, revenue_account_code: value }), accounts("Income"))}</fieldset>}
              {detail.status === "Invoiced" && <fieldset><legend>{t("prepareCollection")}</legend><p>{t("nameHint")}</p>{input("receipt", collection.receipt_number, (value) => setCollection({ ...collection, receipt_number: value }))}{input("date", collection.receipt_date, (value) => setCollection({ ...collection, receipt_date: value }), "date")}{choose("journal", collection.journal_code, (value) => setCollection({ ...collection, journal_code: value }), journals)}{choose("period", collection.period_id, (value) => setCollection({ ...collection, period_id: value }), periods)}{choose("cash", collection.cash_account_code, (value) => setCollection({ ...collection, cash_account_code: value }), accounts("Asset"))}</fieldset>}
              <button disabled={!actionAllowed}>{t(action.label)}</button>
            </form>}
            {detail.status === "IssuePrepared" && <p>{t("cancelReview")}</p>}
            {["Draft", "Submitted", "Approved", "Reserved", "IssueReviewed"].includes(detail.status) && <button disabled={!can("sales.manage", "finance_core.manage") || !reason.trim()} onClick={() => transition("cancel")}>{t("cancel")}</button>}
            <details><summary>{t("evidence")}</summary><ul>{[detail.movement_id, detail.valuation_id, detail.cogs_entry_id, detail.cogs_effect_id, detail.invoice_id, detail.invoice_plan_id, detail.collection_plan_id, detail.receipt_id].filter(Boolean).map((id) => <li key={id}><code>{id}</code></li>)}</ul></details><h3>{t("events")}</h3><ol>{detail.events.map((event) => <li key={event.version}>{event.reason} · {event.actor_id}<p><code>{event.audit_event_id}</code></p></li>)}</ol>
          </section>}
        </>}
      </> : <p>{identity ? t("denied") : t("loading")}</p>}
    </>}
    <p className="stock-sales-boundary">{t("boundary")}</p>
  </main>;
}
