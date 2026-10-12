import { useEffect, useRef, useState, type FormEvent } from "react";
import { CommercialCollectionsPanel } from "./CommercialCollectionsPanel";
import { AdminApiError } from "../data";
import { type SalesIdentity, type SalesScope } from "../sales-revenue-data";
import { executeCommerceCommand, loadCommerceOrder, loadCommercePage, prepareCommerceCommand, searchCommerceCatalog, type CommerceCommand, type CommerceOrder, type CommerceTranche } from "../stock-commerce-data";
import { type StockOptions } from "../stock-sales-data";
import { type BrowserAdminSession, type Locale } from "../types";
import type { ScopedJsonValue } from "../scoped-command";

const messages = {
  title: ["Commercial orders", "أوامر المبيعات التجارية"], intro: ["One approved order conserves every product line and warehouse through independently reviewed shipment, invoice and collection tranches.", "أمر معتمد واحد يحفظ كميات وقيم كل صنف ومستودع عبر دفعات تسليم وفوترة وتحصيل مستقلة المراجعة."],
  bounds: ["Up to 1000 lines per order. Each recognized invoice supports independently reviewed partial collections with an exact remaining balance; returns require a complete inverse.", "حتى 1000 بند للأمر. تدعم كل فاتورة مرحّلة دفعات تحصيل مستقلة المراجعة ومتَبقّيًا دقيقًا؛ المرتجعات تتطلب دورة عكس مكتملة."],
  create: ["Create commercial order", "إنشاء أمر تجاري"], number: ["Order number", "رقم الأمر"], customer: ["Customer", "العميل"], reference: ["Customer reference", "مرجع العميل"], date: ["Business date", "تاريخ العملية"], currency: ["Currency", "العملة"],
  item: ["Product", "الصنف"], warehouse: ["Warehouse", "المستودع"], location: ["Location", "الموقع"], quantity: ["Quantity", "الكمية"], price: ["Unit price in minor units", "سعر الوحدة بالوحدات النقدية الصغرى"], discount: ["Discount basis points", "نقاط أساس الخصم"], description: ["Description", "الوصف"],
  add: ["Add line", "إضافة بند"], remove: ["Remove line", "حذف البند"], search: ["Search product-code prefix", "بحث ببادئة رمز الصنف"], next: ["Next page", "الصفحة التالية"], refresh: ["Refresh commercial orders", "تحديث الأوامر التجارية"], open: ["Open", "فتح"],
  line: ["Line", "البند"], committed: ["Committed quantity", "الكمية المخصصة"], delivered: ["Delivered quantity", "الكمية المسلّمة"], invoiced: ["Invoiced minor units", "قيمة الفواتير بالوحدات الصغرى"], collected: ["Collected minor units", "قيمة التحصيل بالوحدات الصغرى"], total: ["Total minor units", "الإجمالي بالوحدات الصغرى"],
  tranche: ["Delivery tranche", "دفعة التسليم"], openTranche: ["Create partial delivery tranche", "إنشاء دفعة تسليم جزئية"], reason: ["Reason", "السبب"], submit: ["Submit order", "إرسال الأمر للموافقة"], approve: ["Approve commercial terms", "اعتماد الشروط التجارية"], approveTranche: ["Approve and reserve tranche", "اعتماد وحجز الدفعة"],
  cancel: ["Cancel undelivered tranche and release reservation", "إلغاء الدفعة غير المسلّمة وتحرير الحجز"],
  prepareIssue: ["Prepare FIFO and COGS", "إعداد FIFO وتكلفة المبيعات"], reviewIssue: ["Review FIFO and COGS", "مراجعة FIFO وتكلفة المبيعات"], deliver: ["Post delivery and COGS", "ترحيل التسليم وتكلفة المبيعات"], prepareInvoice: ["Prepare invoice and revenue", "إعداد الفاتورة والإيراد"], reviewInvoice: ["Review invoice and revenue", "مراجعة الفاتورة والإيراد"], invoice: ["Post invoice and revenue", "ترحيل الفاتورة والإيراد"], prepareCollection: ["Prepare collection", "إعداد التحصيل"], reviewCollection: ["Review collection", "مراجعة التحصيل"], collect: ["Post collection", "ترحيل التحصيل"],
  period: ["Fiscal period", "الفترة المالية"], policy: ["FIFO policy", "سياسة FIFO"], journal: ["Journal", "دفتر اليومية"], invoiceNumber: ["Invoice number", "رقم الفاتورة"], receiptNumber: ["Receipt number", "رقم التحصيل"], due: ["Due date", "تاريخ الاستحقاق"], receivable: ["Receivable account", "حساب العملاء"], revenue: ["Revenue account", "حساب الإيراد"], cash: ["Cash account", "حساب النقدية"],
  failed: ["The operation was refused or the response could not be verified. Refresh the selected document before proceeding.", "رُفضت العملية أو تعذر التحقق من الرد. حدّث المستند المحدد قبل المتابعة."], unknown: ["The outcome is unknown. Retry the same frozen command before changing the order or scope.", "النتيجة غير معروفة. أعد إرسال نفس الأمر المحفوظ قبل تغيير الأمر أو النطاق."], retry: ["Retry exact command", "إعادة نفس الأمر"],
  duties: ["Preparation, review and posting require three distinct humans. Your current identity cannot perform this step.", "الإعداد والمراجعة والترحيل تتطلب ثلاثة أشخاص مستقلين. هويتك الحالية لا تسمح بهذه الخطوة."], evidence: ["Retained source and financial evidence", "أدلة المصدر والأثر المالي المحفوظة"], empty: ["No commercial orders in this page.", "لا توجد أوامر تجارية في هذه الصفحة."], precision: ["Quantities use the product's unit precision. Each delivery portion must have an exact additive minor-unit value.", "تُستخدم دقة وحدة الصنف للكميات. يجب أن تحمل كل دفعة قيمة صحيحة قابلة للجمع بالوحدات النقدية الصغرى."],
} as const;
type Message = keyof typeof messages;
const actions: Record<string, { operation: string; message: Message; permissions: string[]; kind?: "issue" | "invoice" | "collection"; poster?: boolean }> = {
  Submitted: { operation: "approve-tranche", message: "approveTranche", permissions: ["sales.approve", "sales.manage", "inventory.manage"] },
  Reserved: { operation: "prepare-issue", message: "prepareIssue", permissions: ["sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"] },
  IssuePrepared: { operation: "review-issue", message: "reviewIssue", permissions: ["sales.approve", "inventory.valuation.approve", "finance_core.validate"], kind: "issue" },
  IssueReviewed: { operation: "deliver", message: "deliver", permissions: ["sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"], kind: "issue", poster: true },
  Delivered: { operation: "prepare-invoice", message: "prepareInvoice", permissions: ["sales.manage", "receivables.manage", "finance_core.manage"] },
  InvoicePrepared: { operation: "review-invoice", message: "reviewInvoice", permissions: ["sales.approve", "receivables.approve", "finance_core.validate"], kind: "invoice" },
  InvoiceReviewed: { operation: "invoice", message: "invoice", permissions: ["sales.manage", "receivables.approve", "finance_core.post"], kind: "invoice", poster: true },
  Invoiced: { operation: "prepare-collection", message: "prepareCollection", permissions: ["sales.manage", "finance_core.manage"] },
  CollectionPrepared: { operation: "review-collection", message: "reviewCollection", permissions: ["sales.approve", "finance_core.validate"], kind: "collection" },
  CollectionReviewed: { operation: "collect", message: "collect", permissions: ["sales.manage", "receivables.manage", "finance_core.post"], kind: "collection", poster: true },
};
const blankLine = () => ({ item_code: "", warehouse_code: "", location_code: "", quantity: "", unit_price_minor: "", discount_basis_points: "0", description: "" });

export function StockCommercePanel({ locale, session, scope, identity, options, disabled, onPendingChange }: { locale: Locale; session: BrowserAdminSession; scope: SalesScope; identity: SalesIdentity; options: StockOptions | null; disabled: boolean; onPendingChange: (pending: boolean) => void }) {
  const t = (message: Message) => messages[message][locale === "ar" ? 1 : 0];
  const [header, setHeader] = useState({ number: "", customer_code: "", customer_reference: "", currency_code: "", order_date: "" }), [lines, setLines] = useState([blankLine()]);
  const [page, setPage] = useState<Awaited<ReturnType<typeof loadCommercePage>> | null>(null), [after, setAfter] = useState(""), [reload, setReload] = useState(0), [detail, setDetail] = useState<CommerceOrder | null>(null), [selected, setSelected] = useState("");
  const [prefix, setPrefix] = useState(""), [catalogAfter, setCatalogAfter] = useState(""), [catalog, setCatalog] = useState<Awaited<ReturnType<typeof searchCommerceCatalog>> | null>(null);
  const [busy, setBusy] = useState(false), [pending, setPending] = useState<CommerceCommand | null>(null), [error, setError] = useState<Message | null>(null), [stale, setStale] = useState(false);
  const [reason, setReason] = useState(""), [portion, setPortion] = useState({ line_number: "1", quantity: "" }), [trancheId, setTrancheId] = useState("");
  const [posting, setPosting] = useState({ posting_date: "", period_id: "", policy_code: "", invoice_number: "", invoice_date: "", due_date: "", journal_code: "", receivable_account_code: "", revenue_account_code: "", receipt_number: "", receipt_date: "", cash_account_code: "" });
  const mounted = useRef(true), lock = useRef(false), errorRef = useRef<HTMLDivElement>(null);
  const blocked = disabled || busy || Boolean(pending), writable = !blocked && !stale && identity.human && identity.stepUp;
  const has = (...permissions: string[]) => permissions.every((permission) => identity.permissions.includes(permission));
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => {
    const controller = new AbortController();
    setStale(true);
    Promise.all([loadCommercePage(session, scope, after, controller.signal), selected ? loadCommerceOrder(session, scope, selected, controller.signal) : Promise.resolve(null)]).then(([next, order]) => {
      if (!controller.signal.aborted && mounted.current) { setPage(next); setDetail(order); setStale(false); setError(null); }
    }).catch(() => { if (!controller.signal.aborted && mounted.current) { setError("failed"); setStale(true); setDetail(null); } });
    return () => controller.abort();
  }, [session, scope, after, selected, reload]);
  useEffect(() => {
    const controller = new AbortController();
    searchCommerceCatalog(session, scope, prefix, catalogAfter, controller.signal).then((next) => { if (!controller.signal.aborted && mounted.current) setCatalog(next); }).catch(() => { if (!controller.signal.aborted && mounted.current) setCatalog(null); });
    return () => controller.abort();
  }, [session, scope, prefix, catalogAfter]);
  async function send(command: CommerceCommand) {
    if (lock.current) return; lock.current = true; setBusy(true); setPending(command); onPendingChange(true); setError(null);
    try { const ack = await executeCommerceCommand(session, command); if (mounted.current) { setPending(null); onPendingChange(false); setSelected(ack.id); setReload((old) => old + 1); setReason(""); setStale(true); } }
    catch (caught) { if (mounted.current) { const unknown = !(caught instanceof AdminApiError) || caught.status >= 500; setError(unknown ? "unknown" : "failed"); setStale(true); if (!unknown) { setPending(null); onPendingChange(false); if (caught.status === 403) { setDetail(null); setPage(null); } } } }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  }
  function command(operation: string, fields: Record<string, ScopedJsonValue> = {}) {
    if (!detail || !writable || !reason.trim()) return;
    void send(prepareCommerceCommand(scope, `/api/v1/stock-sales/commerce/orders/${encodeURIComponent(detail.id)}/${operation}`, { expected_version: detail.row_version, reason, ...fields }));
  }
  function create(event: FormEvent) {
    event.preventDefault(); if (!writable || !has("sales.manage")) return;
    if (lines.some((line) => !/^\d{1,4}$/.test(line.discount_basis_points) || Number(line.discount_basis_points) > 9999)) { setError("failed"); return; }
    void send(prepareCommerceCommand(scope, "/api/v1/stock-sales/commerce/orders", { ...header, lines: lines.map((line) => ({ ...line, discount_basis_points: Number(line.discount_basis_points) })) }));
  }
  const input = (message: Message, value: string, update: (next: string) => void, type = "text") => <label>{t(message)}<input required type={type} maxLength={500} value={value} disabled={blocked} onChange={(event) => update(event.target.value)} /></label>;
  const choose = (message: Message, value: string, update: (next: string) => void, choices: { value: string; label: string }[]) => <label>{t(message)}<select required value={value} disabled={blocked} onChange={(event) => update(event.target.value)}><option value="">—</option>{choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}</select></label>;
  const tranche: CommerceTranche | undefined = detail?.lines.flatMap((line) => line.tranches).find((row) => row.id === trancheId), action = tranche && (tranche.status === "Invoiced" && (tranche.pending_collection || (tranche.collected_minor !== undefined && tranche.collected_minor !== "0")) ? undefined : actions[tranche.status]);
  const preparer = action?.kind && tranche?.[`${action.kind}_preparer_id`], reviewer = action?.kind && tranche?.[`${action.kind}_reviewer_id`];
  const duties = Boolean((action?.kind && (preparer === identity.id || (action.poster && (!preparer || !reviewer || reviewer === identity.id)))) || (action?.operation === "approve-tranche" && tranche?.created_by === identity.id));
  const periodChoices = options?.periods.map((period) => ({ value: period.id, label: period.name })) || [], journalChoices = options?.journals.map((journal) => ({ value: journal.journal_code, label: journal.name })) || [];
  const accountChoices = (kind: "Asset" | "Income") => options?.accounts.filter((account) => account.account_type === kind).map((account) => ({ value: account.account_code, label: account.name })) || [];
  function perform(event: FormEvent) {
    event.preventDefault(); if (!action || !tranche || duties || !has(...action.permissions)) return;
    const keys = action.operation === "prepare-issue" ? ["posting_date", "period_id", "policy_code"] : action.operation === "prepare-invoice" ? ["invoice_number", "invoice_date", "due_date", "journal_code", "period_id", "receivable_account_code", "revenue_account_code"] : action.operation === "prepare-collection" ? ["receipt_number", "receipt_date", "journal_code", "period_id", "cash_account_code"] : [];
    command(action.operation, { tranche_id: tranche.id, parameters: Object.fromEntries(keys.map((key) => [key, posting[key as keyof typeof posting]])) });
  }
  return <section className="stock-commerce" aria-labelledby="commerce-heading" dir={locale === "ar" ? "rtl" : "ltr"}>
    <header><h2 id="commerce-heading">{t("title")}</h2><p>{t("intro")}</p><p>{t("bounds")}</p></header>
    {error && <div role="alert" tabIndex={-1} ref={errorRef}>{t(error)}</div>}
    {pending && !busy && <aside role="status"><p>{t("unknown")}</p><button disabled={disabled} onClick={() => void send(pending)}>{t("retry")}</button></aside>}
    <nav aria-label={t("title")}><button disabled={blocked} onClick={() => { setAfter(""); setReload((old) => old + 1); }}>{t("refresh")}</button><button disabled={blocked || !page?.next_cursor} onClick={() => setAfter(page?.next_cursor || "")}>{t("next")}</button></nav>
    <ul>{page?.orders.map((order) => <li key={order.id}><strong>{order.number}</strong> · {order.status} · {order.line_count} · {order.total_minor} {order.currency_code} <button disabled={blocked} onClick={() => { setSelected(order.id); setTrancheId(""); }}>{t("open")}</button></li>)}</ul>
    {page?.orders.length === 0 && <p>{t("empty")}</p>}
    <details><summary>{t("create")}</summary><label>{t("search")}<input value={prefix} maxLength={64} disabled={blocked} onChange={(event) => { setPrefix(event.target.value); setCatalogAfter(""); }} /></label><button disabled={blocked || !catalog?.next_cursor} onClick={() => setCatalogAfter(catalog?.next_cursor || "")}>{t("next")}</button>
      <form onSubmit={create} aria-label={t("create")}><fieldset><legend>{t("create")}</legend>
        {input("number", header.number, (number) => setHeader({ ...header, number }))}{choose("customer", header.customer_code, (customer_code) => setHeader({ ...header, customer_code, currency_code: options?.customers.find((customer) => customer.customer_code === customer_code)?.currency_code || "" }), options?.customers.map((customer) => ({ value: customer.customer_code, label: customer.name })) || [])}
        {input("reference", header.customer_reference, (customer_reference) => setHeader({ ...header, customer_reference }))}{input("date", header.order_date, (order_date) => setHeader({ ...header, order_date }), "date")}
        {lines.map((line, index) => <fieldset key={index}><legend>{t("line")} {index + 1}</legend>
          {choose("item", line.item_code, (item_code) => setLines(lines.map((entry, at) => at === index ? { ...entry, item_code } : entry)), [...(catalog?.items || []), ...(line.item_code && !catalog?.items.some((item) => item.item_code === line.item_code) ? [{ item_code: line.item_code, name: line.item_code, uom_code: "", decimal_places: 0 }] : [])].map((item) => ({ value: item.item_code, label: `${item.name} · ${item.item_code} · ${item.uom_code}` })))}
          {choose("warehouse", line.warehouse_code, (warehouse_code) => setLines(lines.map((entry, at) => at === index ? { ...entry, warehouse_code, location_code: "" } : entry)), options?.warehouses.map((warehouse) => ({ value: warehouse.warehouse_code, label: warehouse.name })) || [])}
          {choose("location", line.location_code, (location_code) => setLines(lines.map((entry, at) => at === index ? { ...entry, location_code } : entry)), options?.locations.filter((location) => location.warehouse_code === line.warehouse_code).map((location) => ({ value: location.location_code, label: location.name })) || [])}
          {(["quantity", "unit_price_minor", "discount_basis_points", "description"] as const).map((key) => <label key={key}>{t(key === "unit_price_minor" ? "price" : key === "discount_basis_points" ? "discount" : key)}<input required value={line[key]} disabled={blocked} onChange={(event) => setLines(lines.map((entry, at) => at === index ? { ...entry, [key]: event.target.value } : entry))} /></label>)}
          <button type="button" disabled={blocked || lines.length === 1} onClick={() => setLines(lines.filter((_, at) => at !== index))}>{t("remove")}</button></fieldset>)}
        <p>{t("precision")}</p><button type="button" disabled={blocked || lines.length >= 1000} onClick={() => setLines([...lines, blankLine()])}>{t("add")}</button><button disabled={!writable || !has("sales.manage")}>{t("create")}</button>
      </fieldset></form></details>
    {detail && <article><h3>{detail.number} · {detail.status}</h3><p>{t("total")}: <strong>{detail.total_minor} {detail.currency_code}</strong></p>
      <div className="stock-commerce-table" tabIndex={0}><table><caption>{t("title")}</caption><thead><tr>{(["line", "item", "warehouse", "quantity", "committed", "delivered", "invoiced", "collected"] as const).map((message) => <th key={message} scope="col">{t(message)}</th>)}</tr></thead><tbody>{detail.lines.map((line) => <tr key={line.line_number}><th scope="row">{line.line_number}</th><td>{line.source.item_code}</td><td>{line.source.warehouse_code}/{line.source.location_code}</td><td>{line.source.quantity}</td><td>{line.committed_quantity_scaled} ×10⁻{line.quantity_precision}</td><td>{line.delivered_quantity_scaled} ×10⁻{line.quantity_precision}</td><td>{line.invoiced_minor}</td><td>{line.collected_minor}</td></tr>)}</tbody></table></div>
      {input("reason", reason, setReason)}
      {detail.status === "Draft" && <button disabled={!writable || !reason || !has("sales.manage")} onClick={() => command("submit")}>{t("submit")}</button>}
      {detail.status === "Submitted" && <button disabled={!writable || !reason || !has("sales.approve") || detail.created_by === identity.id} onClick={() => command("approve")}>{t("approve")}</button>}
      {detail.status === "Approved" && <><form onSubmit={(event) => { event.preventDefault(); command("open-tranche", { line_number: Number(portion.line_number), quantity: portion.quantity }); }}>{choose("line", portion.line_number, (line_number) => setPortion({ ...portion, line_number }), detail.lines.map((line) => ({ value: String(line.line_number), label: `${line.line_number} · ${line.source.item_code} · ${line.source.warehouse_code}` })))}{input("quantity", portion.quantity, (quantity) => setPortion({ ...portion, quantity }))}<button disabled={!writable || !reason || !has("sales.manage")}>{t("openTranche")}</button></form>
        {choose("tranche", trancheId, setTrancheId, detail.lines.flatMap((line) => line.tranches.map((tranche) => ({ value: tranche.id, label: `${line.line_number} · ${line.source.item_code} · ${tranche.quantity_scaled} · ${tranche.status}` }))))}
        {action && <form onSubmit={perform} aria-label={t(action.message)}>
          {tranche?.status === "Reserved" && <>{input("date", posting.posting_date, (posting_date) => setPosting({ ...posting, posting_date }), "date")}{choose("period", posting.period_id, (period_id) => setPosting({ ...posting, period_id }), periodChoices)}{choose("policy", posting.policy_code, (policy_code) => setPosting({ ...posting, policy_code }), options?.policies.map((policy) => ({ value: policy.policy_code, label: policy.name })) || [])}</>}
          {tranche?.status === "Delivered" && <>{input("invoiceNumber", posting.invoice_number, (invoice_number) => setPosting({ ...posting, invoice_number }))}{input("date", posting.invoice_date, (invoice_date) => setPosting({ ...posting, invoice_date }), "date")}{input("due", posting.due_date, (due_date) => setPosting({ ...posting, due_date }), "date")}{choose("period", posting.period_id, (period_id) => setPosting({ ...posting, period_id }), periodChoices)}{choose("journal", posting.journal_code, (journal_code) => setPosting({ ...posting, journal_code }), journalChoices)}{choose("receivable", posting.receivable_account_code, (receivable_account_code) => setPosting({ ...posting, receivable_account_code }), accountChoices("Asset"))}{choose("revenue", posting.revenue_account_code, (revenue_account_code) => setPosting({ ...posting, revenue_account_code }), accountChoices("Income"))}</>}
          {tranche?.status === "Invoiced" && <>{input("receiptNumber", posting.receipt_number, (receipt_number) => setPosting({ ...posting, receipt_number }))}{input("date", posting.receipt_date, (receipt_date) => setPosting({ ...posting, receipt_date }), "date")}{choose("period", posting.period_id, (period_id) => setPosting({ ...posting, period_id }), periodChoices)}{choose("journal", posting.journal_code, (journal_code) => setPosting({ ...posting, journal_code }), journalChoices)}{choose("cash", posting.cash_account_code, (cash_account_code) => setPosting({ ...posting, cash_account_code }), accountChoices("Asset"))}</>}
          {duties && <p>{t("duties")}</p>}<button disabled={!writable || !reason || !has(...action.permissions) || duties}>{t(action.message)}</button>
        </form>}
        {tranche && ["Submitted", "Reserved", "IssueReviewed"].includes(tranche.status) && <button disabled={!writable || !reason || !has("sales.manage", "finance_core.manage")} onClick={() => command("cancel", { tranche_id: tranche.id })}>{t("cancel")}</button>}
        {tranche?.status === "Invoiced" && tranche.outstanding_minor !== undefined && <CommercialCollectionsPanel key={tranche.id} locale={locale} session={session} scope={scope} identity={identity} tranche={tranche} options={options} disabled={blocked || stale} onPendingChange={onPendingChange} onCommitted={() => { setStale(true); setReload((old) => old + 1); }} />}
        {tranche && <details><summary>{t("evidence")}</summary><ul>{[tranche.stock_order_id, tranche.movement_id, tranche.cogs_effect_id, tranche.invoice_id, tranche.receipt_id].filter(Boolean).map((id) => <li key={id}><code>{id}</code></li>)}</ul></details>}
      </>}
    </article>}
  </section>;
}
