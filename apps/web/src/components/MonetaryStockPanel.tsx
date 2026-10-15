import { useEffect, useRef, useState, type FormEvent } from "react";
import { useBrowserSession } from "../browserSession";
import { AdminApiError } from "../data";
import type { FinanceScope } from "../enterprise-finance-data";
import { monetaryStockRoot } from "../monetary-paths";
import { monetaryMinor, prepareMonetaryCommand } from "../monetary-public-data";
import { executeMonetaryStockCommand, loadMonetaryStock, loadMonetaryStockOptions, loadMonetaryStockPage, type MonetaryStock, type MonetaryStockOptions, type MonetaryTaxDeclaration } from "../monetary-stock-data";
import { monetaryTranslate, type MonetaryWord } from "../monetary-words";
import type { SalesIdentity } from "../sales-revenue-data";
import type { PreparedScopedCommand, ScopedJsonValue } from "../scoped-command";
import type { StockStage } from "../stock-sales-data";
import { stockTranslate } from "../stock-sales-i18n";
import type { Locale } from "../types";
import { MonetaryStockEvidence } from "./MonetaryEvidence";

const READ = ["sales.read", "inventory.read", "receivables.read", "finance_core.read"];
const actions: Partial<Record<StockStage, { path: string; label: MonetaryWord; permissions: string[]; kind?: "issue" | "invoice" | "collection"; posting?: boolean }>> = {
  Draft: { path: "submit", label: "submit", permissions: ["sales.manage"] }, Submitted: { path: "approve", label: "approve", permissions: ["sales.approve"] },
  Approved: { path: "reserve", label: "reserve", permissions: ["sales.manage", "inventory.manage"] },
  Reserved: { path: "issue/prepare", label: "prepareIssue", permissions: ["sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"] },
  IssuePrepared: { path: "issue/review", label: "reviewIssue", permissions: ["sales.approve", "inventory.valuation.approve", "finance_core.validate"], kind: "issue" },
  IssueReviewed: { path: "deliver", label: "deliver", permissions: ["sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"], kind: "issue", posting: true },
  Delivered: { path: "invoice/prepare", label: "prepareInvoice", permissions: ["sales.manage", "receivables.manage", "finance_core.manage"] },
  InvoicePrepared: { path: "invoice/review", label: "reviewInvoice", permissions: ["sales.approve", "receivables.approve", "finance_core.validate"], kind: "invoice" },
  InvoiceReviewed: { path: "invoice/post", label: "postInvoice", permissions: ["sales.manage", "receivables.approve", "finance_core.post"], kind: "invoice", posting: true },
  Invoiced: { path: "collection/prepare", label: "prepareCollection", permissions: ["sales.manage", "receivables.manage", "finance_core.manage"] },
  Paid: { path: "collection/prepare", label: "prepareCollection", permissions: ["sales.manage", "receivables.manage", "finance_core.manage"] },
  CollectionPrepared: { path: "collection/review", label: "reviewCollection", permissions: ["sales.approve", "receivables.approve", "finance_core.validate"], kind: "collection" },
  CollectionReviewed: { path: "collection/post", label: "postCollection", permissions: ["sales.manage", "receivables.manage", "finance_core.post"], kind: "collection", posting: true },
};
const blankRate = () => ({ rate: "", source: "", effective_at: "" });
const blankTax = (): MonetaryTaxDeclaration => ({ policy_id: "", country_code: "", transaction_class: "", effective_from: "", effective_to: "", rate: "", account_code: "", source: "", version: "" });
interface Props { locale: Locale; scope: FinanceScope; identity: SalesIdentity; externallyLocked: boolean; onLockChange: (locked: boolean) => void }

export function MonetaryStockPanel({ locale, scope, identity, externallyLocked, onLockChange }: Props) {
  const auth = useBrowserSession(), t = (key: MonetaryWord) => monetaryTranslate(locale, key);
  const [orders, setOrders] = useState<MonetaryStock[]>([]), [options, setOptions] = useState<MonetaryStockOptions | null>(null), [detail, setDetail] = useState<MonetaryStock | null>(null), [selected, setSelected] = useState("");
  const [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false), [loading, setLoading] = useState(false), [pending, setPending] = useState<PreparedScopedCommand | null>(null), [stale, setStale] = useState(true), [error, setError] = useState<MonetaryWord | null>(null);
  const [order, setOrder] = useState({ number: "", customer_code: "", customer_reference: "", item_code: "", warehouse_code: "", location_code: "", quantity: "", unit_price_minor: "", currency_code: "", order_date: "", description: "", discount_basis_points: "0" });
  const [issue, setIssue] = useState({ posting_date: "", period_id: "", policy_code: "" });
  const [invoice, setInvoice] = useState({ invoice_number: "", invoice_date: "", due_date: "", journal_code: "", period_id: "", receivable_account_code: "", revenue_account_code: "", cash_account_code: "", refund_liability_account_code: "", gain_account_code: "", loss_account_code: "", country_code: "", transaction_class: "" });
  const [originalRate, setOriginalRate] = useState(blankRate), [taxes, setTaxes] = useState<MonetaryTaxDeclaration[]>([]), [reason, setReason] = useState("");
  const [collection, setCollection] = useState({ receipt_number: "", receipt_date: "", period_id: "", amount_minor: "" }), [settlementRate, setSettlementRate] = useState(blankRate);
  const mounted = useRef(true), lock = useRef(false), epoch = useRef(0), alert = useRef<HTMLParagraphElement>(null), heading = useRef<HTMLHeadingElement>(null);
  const current = () => mounted.current && auth.isCurrent(auth.revision), locked = externallyLocked || busy || Boolean(pending);
  const has = (...permissions: string[]) => identity.human && [...READ, ...permissions].every(permission => identity.permissions.includes(permission));
  const writable = identity.stepUp && has() && !stale && !locked;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; ++epoch.current; onLockChange(false); }; }, [onLockChange]);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  function fail(caught: unknown) {
    if (!current() || auth.recover(caught, auth.revision)) return;
    setStale(true); setError(caught instanceof AdminApiError && [403, 404].includes(caught.status) ? "denied" : caught instanceof AdminApiError && caught.status === 409 ? "conflict" : "unavailable");
    if (caught instanceof AdminApiError && [403, 404].includes(caught.status)) { setOrders([]); setDetail(null); setOptions(null); }
  }
  useEffect(() => {
    if (!auth.session || !has() || pending || externallyLocked) return;
    const controller = new AbortController(), generation = ++epoch.current; setLoading(true); setStale(true);
    Promise.all([loadMonetaryStockPage(auth.session, scope, controller.signal), loadMonetaryStockOptions(auth.session, scope, controller.signal),
      selected ? loadMonetaryStock(auth.session, scope, selected, controller.signal) : Promise.resolve(null)]).then(([rows, choices, selectedOrder]) => {
      if (!current() || controller.signal.aborted || generation !== epoch.current) return;
      setOrders(rows); setOptions(choices); setDetail(selectedOrder); setStale(false); setError(null);
    }).catch(caught => { if (!controller.signal.aborted && generation === epoch.current) fail(caught); })
      .finally(() => { if (current() && !controller.signal.aborted && generation === epoch.current) setLoading(false); });
    return () => { controller.abort(); ++epoch.current; };
  }, [auth.session, auth.revision, scope, identity, selected, refresh, pending, externallyLocked]);
  async function send(command: PreparedScopedCommand) {
    if (!auth.session || lock.current || externallyLocked) return;
    lock.current = true; ++epoch.current; setLoading(false); setBusy(true); setPending(command); setError(null); onLockChange(true);
    try {
      const result = await executeMonetaryStockCommand(auth.session, scope, command);
      if (!current()) return;
      setDetail(result); setSelected(result.id); setPending(null); setReason(""); setStale(false); setRefresh(old => old + 1); onLockChange(false); heading.current?.focus();
    } catch (caught) {
      if (!current()) return;
      if (!(caught instanceof AdminApiError) || caught.status >= 500) { setError("unknown"); setStale(true); }
      else { setPending(null); onLockChange(false); fail(caught); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  function submit(path: string, body: Record<string, ScopedJsonValue>) {
    if (!writable || lock.current) return;
    try { void send(prepareMonetaryCommand(path, body)); } catch { setError("invalid"); }
  }
  const action = detail ? actions[detail.status] : undefined;
  const duties = detail && action?.kind === "issue" ? [detail.issue_preparer_id, detail.issue_reviewer_id]
    : detail && action?.kind === "invoice" ? [detail.monetary_origin?.preparer_actor_id, detail.monetary_origin?.reviewer_actor_id]
      : detail && action?.kind === "collection" ? [detail.collection?.preparer_actor_id, detail.collection?.reviewer_actor_id] : null;
  const collectionAllowed = detail?.balance && BigInt(detail.balance.transaction_outstanding_minor) > 0n && !detail.balance.active_plan_id && !detail.balance.active_revaluation_plan_id;
  const actionAllowed = writable && action && has(...action.permissions) && (detail?.status !== "Submitted" || detail.created_by !== identity.id)
    && (!duties || Boolean(duties[0]) && (action.posting ? Boolean(duties[1]) && !duties.includes(identity.id) : duties[0] !== identity.id))
    && (!detail || !["Invoiced", "Paid"].includes(detail.status) || Boolean(collectionAllowed));
  const identityCurrency = detail?.transaction_policy.currency_code === detail?.functional_policy.currency_code;
  function perform(event: FormEvent) {
    event.preventDefault(); if (!detail || !action || !actionAllowed || !reason.trim()) return;
    let fields: Record<string, ScopedJsonValue> = {};
    if (detail.status === "Reserved") fields = issue;
    if (detail.status === "Delivered") fields = { ...invoice, taxes: taxes.map(tax => ({ ...tax, country_code: invoice.country_code, transaction_class: invoice.transaction_class })), original_rate: identityCurrency ? null : { ...originalRate } };
    if (["Invoiced", "Paid"].includes(detail.status)) {
      try { monetaryMinor(collection.amount_minor, true); if (BigInt(collection.amount_minor) > BigInt(detail.balance!.transaction_outstanding_minor)) throw new Error("overcollection"); }
      catch { setError("invalid"); return; }
      fields = { ...collection, settlement_rate: identityCurrency ? null : { ...settlementRate } };
    }
    submit(`${monetaryStockRoot}/orders/${encodeURIComponent(detail.id)}/${action.path}`, { ...fields, expected_version: detail.row_version, reason });
  }
  const input = (key: MonetaryWord, value: string, update: (value: string) => void, type = "text") => <label>{t(key)}<input required type={type} maxLength={key === "invoice_number" || key === "receipt_number" ? 60 : key === "reason" || key === "description" ? 500 : 200} value={value} disabled={locked} onChange={event => update(event.target.value)} /></label>;
  const select = (key: MonetaryWord, value: string, update: (value: string) => void, entries: { value: string; label: string }[]) => <label>{t(key)}<select required value={value} disabled={locked} onChange={event => update(event.target.value)}><option value="">—</option>{entries.map(entry => <option key={entry.value} value={entry.value}>{entry.label}</option>)}</select></label>;
  const account = (key: keyof typeof invoice, kind: string) => select(key as MonetaryWord, invoice[key], value => setInvoice({ ...invoice, [key]: value }), options?.accounts.filter(row => row.account_type === kind).map(row => ({ value: row.account_code, label: `${row.name} · ${row.account_code}` })) ?? []);
  const period = (value: string, update: (value: string) => void) => select("period_id", value, update, options?.periods.map(row => ({ value: row.id, label: `${row.name} · ${row.start_date} — ${row.end_date}` })) ?? []);
  const rateFields = (value: ReturnType<typeof blankRate>, update: (value: ReturnType<typeof blankRate>) => void) => <div className="reporting-form">{input("rate", value.rate, rate => update({ ...value, rate }))}{input("rateSource", value.source, source => update({ ...value, source }))}{input("effective_at", value.effective_at, effective_at => update({ ...value, effective_at }))}</div>;
  return <section aria-label={t("stockTitle")} dir={locale === "ar" ? "rtl" : "ltr"}><h2 tabIndex={-1} ref={heading}>{t("stockTitle")}</h2><p>{t("stockBoundary")}</p><p>{t("duties")}</p>
    {error && <p role="alert" tabIndex={-1} ref={alert}>{t(error)}</p>}{(loading || busy) && <p role="status">{t("loading")}</p>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button disabled={externallyLocked} onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    <section className="panel"><button disabled={locked} onClick={() => setRefresh(old => old + 1)}>{t("refresh")}</button><label>{t("selectStock")}<select disabled={locked} value={selected} onChange={event => { setSelected(event.target.value); setDetail(null); setError(null); }}><option value="">—</option>{orders.map(row => <option key={row.id} value={row.id}>{row.number} · {stockTranslate(locale, row.status)}</option>)}</select></label>{!loading && !orders.length && <p>{t("empty")}</p>}</section>
    {has("sales.manage") && <details open={!detail}><summary>{t("create")}</summary><form className="panel reporting-form" aria-label={t("create")} onSubmit={event => {
      event.preventDefault(); if (!/^[0-9]{1,4}$/.test(order.discount_basis_points)) { setError("invalid"); return; }
      submit(`${monetaryStockRoot}/orders`, { ...order, discount_basis_points: Number(order.discount_basis_points) });
    }}>{input("number", order.number, number => setOrder({ ...order, number }))}
      {select("customer_code", order.customer_code, value => setOrder({ ...order, customer_code: value, currency_code: options?.customers.find(row => row.customer_code === value)?.currency_code ?? "" }), options?.customers.map(row => ({ value: row.customer_code, label: `${row.name} · ${row.currency_code}` })) ?? [])}
      {input("customer_reference", order.customer_reference, customer_reference => setOrder({ ...order, customer_reference }))}
      {select("item_code", order.item_code, item_code => setOrder({ ...order, item_code }), options?.items.map(row => ({ value: row.item_code, label: `${row.name} · ${row.uom_code}` })) ?? [])}
      {select("warehouse_code", order.warehouse_code, warehouse_code => setOrder({ ...order, warehouse_code, location_code: "" }), options?.warehouses.map(row => ({ value: row.warehouse_code, label: row.name })) ?? [])}
      {select("location_code", order.location_code, location_code => setOrder({ ...order, location_code }), options?.locations.filter(row => row.warehouse_code === order.warehouse_code).map(row => ({ value: row.location_code, label: row.name })) ?? [])}
      {input("quantity", order.quantity, quantity => setOrder({ ...order, quantity }))}{input("unit_price_minor", order.unit_price_minor, unit_price_minor => setOrder({ ...order, unit_price_minor }))}{input("discount_basis_points", order.discount_basis_points, discount_basis_points => setOrder({ ...order, discount_basis_points }))}
      {input("description", order.description, description => setOrder({ ...order, description }))}{input("order_date", order.order_date, order_date => setOrder({ ...order, order_date }), "date")}<p>{t("transaction")}: <bdi>{order.currency_code}</bdi></p><button disabled={!writable}>{t("create")}</button></form></details>}
    {detail && <section className="panel"><h3><bdi>{detail.number}</bdi> · {stockTranslate(locale, detail.status)}</h3><MonetaryStockEvidence stock={detail} locale={locale} />
      {action && <form aria-label={t(action.label)} onSubmit={perform}><h3>{t(action.label)}</h3><div className="reporting-form">{input("reason", reason, setReason)}
        {detail.status === "Reserved" && <>{input("posting_date", issue.posting_date, posting_date => setIssue({ ...issue, posting_date }), "date")}{period(issue.period_id, period_id => setIssue({ ...issue, period_id }))}{select("policy_code", issue.policy_code, policy_code => setIssue({ ...issue, policy_code }), options?.policies.map(row => ({ value: row.policy_code, label: `${row.name} · ${row.journal_code}` })) ?? [])}</>}
        {detail.status === "Delivered" && <>{input("invoice_number", invoice.invoice_number, invoice_number => setInvoice({ ...invoice, invoice_number }))}{input("invoice_date", invoice.invoice_date, invoice_date => setInvoice({ ...invoice, invoice_date }), "date")}{input("due_date", invoice.due_date, due_date => setInvoice({ ...invoice, due_date }), "date")}
          {period(invoice.period_id, period_id => setInvoice({ ...invoice, period_id }))}{select("journal_code", invoice.journal_code, journal_code => setInvoice({ ...invoice, journal_code }), options?.journals.filter(row => row.currency_code === detail.functional_policy.currency_code).map(row => ({ value: row.journal_code, label: row.name })) ?? [])}
          {account("receivable_account_code", "Asset")}{account("revenue_account_code", "Income")}{account("cash_account_code", "Asset")}{account("refund_liability_account_code", "Liability")}{account("gain_account_code", "Income")}{account("loss_account_code", "Expense")}
          {input("country_code", invoice.country_code, country_code => setInvoice({ ...invoice, country_code: country_code.toUpperCase() }))}{input("transaction_class", invoice.transaction_class, transaction_class => setInvoice({ ...invoice, transaction_class }))}</>}
        {["Invoiced", "Paid"].includes(detail.status) && <>{input("receipt_number", collection.receipt_number, receipt_number => setCollection({ ...collection, receipt_number }))}{input("receipt_date", collection.receipt_date, receipt_date => setCollection({ ...collection, receipt_date }), "date")}{period(collection.period_id, period_id => setCollection({ ...collection, period_id }))}{input("amount_minor", collection.amount_minor, amount_minor => setCollection({ ...collection, amount_minor }))}</>}
      </div>{detail.status === "Delivered" && <><fieldset><legend>{t("originalRate")}</legend>{identityCurrency ? <p>{t("identityRate")}</p> : rateFields(originalRate, setOriginalRate)}</fieldset>
        <fieldset><legend>{t("taxes")}</legend>{taxes.map((tax, index) => <fieldset key={index}><legend>{t("tax")} {index + 1}</legend><div className="reporting-form">{(["policy_id", "version", "effective_from", "effective_to"] as const).map(key => <div key={key}>{input(key, tax[key], value => setTaxes(old => old.map((item, at) => at === index ? { ...item, [key]: value } : item)), key.startsWith("effective_") ? "date" : "text")}</div>)}
          {input("taxRate", tax.rate, rate => setTaxes(old => old.map((item, at) => at === index ? { ...item, rate } : item)))}{input("taxSource", tax.source, source => setTaxes(old => old.map((item, at) => at === index ? { ...item, source } : item)))}{select("account_code", tax.account_code, account_code => setTaxes(old => old.map((item, at) => at === index ? { ...item, account_code } : item)), options?.accounts.filter(row => row.account_type === "Liability").map(row => ({ value: row.account_code, label: row.name })) ?? [])}</div><button type="button" disabled={locked} onClick={() => setTaxes(old => old.filter((_, at) => at !== index))}>{t("removeTax")}</button></fieldset>)}<button type="button" disabled={locked || taxes.length >= 8} onClick={() => setTaxes(old => [...old, blankTax()])}>{t("addTax")}</button></fieldset></>}
      {["Invoiced", "Paid"].includes(detail.status) && <fieldset><legend>{t("settlementRate")}</legend>{identityCurrency ? <p>{t("identityRate")}</p> : rateFields(settlementRate, setSettlementRate)}</fieldset>}
      <button disabled={!actionAllowed}>{t(action.label)}</button></form>}
      {["Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed"].includes(detail.status) && <button disabled={!writable || !has("sales.manage", "finance_core.manage") || !reason.trim()} onClick={() => submit(`${monetaryStockRoot}/orders/${encodeURIComponent(detail.id)}/cancel`, { expected_version: detail.row_version, reason })}>{t("cancelStock")}</button>}
    </section>}
  </section>;
}
