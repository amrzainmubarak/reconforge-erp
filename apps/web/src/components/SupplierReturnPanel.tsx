import { useEffect, useRef, useState, type FormEvent } from "react";
import { AdminApiError } from "../data";
import { scaledQuantity, type PartialDetail } from "../procurement-partial-data";
import type { ProcurementScope } from "../procurement-data";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import { supplierReturnCommand, supplierReturnPage, supplierReturnRoot, type SupplierReturnPlan } from "../supplier-return-data";
import type { BrowserAdminSession, Locale } from "../types";

const words = {
  en: { title: "Original receipt supplier debit", scope: "Return one whole unissued receipt and its exact unpaid single-line accrued invoice. Remove original FIFO cost and credit original AP together. Paid freight and duties become expense; historical receiving quantities stay retained. Appropriation-backed purchases and paid or partial returns require a later cycle.", number: "Supplier return number", receipt: "Whole original receipt", invoice: "Exact unpaid supplier invoice", date: "Supplier return posting date", period: "Supplier return fiscal period", expense: "Paid charge expense account", prepare: "Prepare original supplier debit", review: "Review supplier debit", post: "Remove original FIFO and credit AP", cancel: "Cancel unposted supplier debit", retry: "Retry the same supplier return command", unknown: "The response is unconfirmed. Retain this exact command and retry.", error: "Supplier return could not be confirmed. Refresh current evidence or retry the retained command.", original: "Original supplier credit", inventory: "Original FIFO removed", charges: "Paid charges expensed", actors: "Preparer / reviewer / poster", evidence: "Native posting effects", empty: "No supplier return in this page.", statuses: ["Prepared", "Reviewed", "Posted", "Cancelled"] },
  ar: { title: "إشعار خصم المورد للاستلام الأصلي", scope: "أعد استلامًا أصليًا كاملًا لم تُصرف كميته مع فاتورته المستحقة غير المدفوعة ذات البند الواحد. تزال تكلفة FIFO الأصلية ويخفض AP في معاملة واحدة. يصبح الشحن والرسوم المدفوعة مصروفًا؛ تبقى كميات الاستلام التاريخية محفوظة. الشراء المحجوز على اعتماد والمرتجعات المدفوعة أو الجزئية تحتاج دورة لاحقة.", number: "رقم مرتجع المورد", receipt: "الاستلام الأصلي الكامل", invoice: "فاتورة المورد غير المدفوعة المطابقة", date: "تاريخ قيد مرتجع المورد", period: "الفترة المالية للمرتجع", expense: "حساب مصروف التكاليف المدفوعة", prepare: "إعداد إشعار خصم المورد الأصلي", review: "مراجعة إشعار خصم المورد", post: "إزالة FIFO الأصلي وتخفيض AP", cancel: "إلغاء إشعار الخصم قبل التثبيت", retry: "إعادة إرسال أمر المرتجع نفسه", unknown: "لم يتأكد الرد. احتفظ بمعرف الأمر وأعد إرساله كما هو.", error: "تعذر تأكيد المرتجع. حدّث الأدلة أو أعد إرسال الأمر المحفوظ.", original: "ائتمان المورد الأصلي", inventory: "تكلفة FIFO الأصلية المزالة", charges: "التكاليف المدفوعة المحولة لمصروف", actors: "المعد / المراجع / المثبت", evidence: "آثار القيود الأصلية", empty: "لا يوجد مرتجع مورد في هذه الصفحة.", statuses: ["معد", "مراجع", "مثبت", "ملغى"] },
};
interface Props { locale: Locale; session: BrowserAdminSession; scope: ProcurementScope; detail: PartialDetail; actorId: string | null; permissions: string[]; elevated: boolean; locked: boolean; reason: string; periods: { id: string; name: string }[]; onChanged: () => Promise<void>; onBusy: (value: boolean) => void; onError: (error: unknown) => void }
const merge = (old: SupplierReturnPlan, ack: SupplierReturnPlan) => old.phase >= 2 || old.phase > ack.phase ? old : ack;
export function SupplierReturnPanel({ locale, session, scope, detail, actorId, permissions, elevated, locked, reason, periods, onChanged, onBusy, onError }: Props) {
  const t = words[locale], orderId = detail.order.id;
  const [plans, setPlans] = useState<SupplierReturnPlan[]>([]), [focus, setFocus] = useState<SupplierReturnPlan | null>(null), [reload, setReload] = useState(0);
  const [number, setNumber] = useState("SR1-"), [receipt, setReceipt] = useState(""), [invoice, setInvoice] = useState("");
  const [date, setDate] = useState(detail.order.request.posting_date), [period, setPeriod] = useState(detail.order.request.period_id), [expense, setExpense] = useState("ADJUSTMENT");
  const [pending, setPending] = useState<PreparedScopedCommand | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(false);
  const mounted = useRef(true), running = useRef(false), observed = useRef(new Map<string, SupplierReturnPlan>());
  function retain(plan: SupplierReturnPlan) {
    const prior = observed.current.get(plan.id), current = prior ? merge(prior, plan) : plan;
    observed.current.set(plan.id, current); return current;
  }
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const control = new AbortController();
    supplierReturnPage(session, scope, orderId, control.signal).then(rows => { if (!control.signal.aborted && mounted.current) setPlans(rows.map(retain)); })
      .catch(caught => { if (!control.signal.aborted && mounted.current) { setError(true); onError(caught); } });
    return () => control.abort();
  }, [session, scope, orderId, detail.order.row_version, reload]);
  const allowed = (required: string[]) => elevated && actorId !== null && ["payables.read", "inventory.read", "finance_core.read", ...required].every(p => permissions.includes(p));
  const canPrepare = allowed(["payables.manage", "inventory.manage", "inventory.valuation.manage", "inventory.valuation.reverse.manage", "finance_core.manage", "finance_core.reverse"]);
  const independent = (plan: SupplierReturnPlan) => actorId !== plan.preparer_actor_id && actorId !== plan.reviewer_actor_id;
  const canPhase = (plan: SupplierReturnPlan) => independent(plan) && (plan.phase === 0 ? allowed(["payables.approve", "inventory.post", "inventory.valuation.approve", "inventory.valuation.reverse.approve", "finance_core.validate", "finance_core.reverse"]) : allowed(["payables.manage", "inventory.post", "inventory.valuation.approve", "inventory.valuation.reverse.approve", "finance_core.post", "finance_core.reverse"]));
  const canCancel = (plan: SupplierReturnPlan) => independent(plan) && allowed(["payables.approve", "inventory.valuation.reverse.approve", "finance_core.validate"]);
  async function send(command: PreparedScopedCommand) {
    if (running.current) return;
    running.current = true; setBusy(true); setError(false); setPending(command); onBusy(true);
    try {
      const result = await supplierReturnCommand(session, scope, orderId, command);
      if (mounted.current) { const confirmed = retain(result); setFocus(confirmed); setPlans(old => old.map(p => p.id === confirmed.id ? confirmed : p)); setPending(null); setReload(n => n + 1); }
      await onChanged();
    } catch (caught) { if (mounted.current) { setError(true); if (caught instanceof AdminApiError && caught.status < 500) setPending(null); onError(caught); } }
    finally { running.current = false; if (mounted.current) { setBusy(false); onBusy(false); } }
  }
  function prepare(event: FormEvent) {
    event.preventDefault();
    if (locked || busy || pending || !canPrepare || !reason.trim() || !receipt || !invoice) return;
    void send(prepareScopedCommand(`${supplierReturnRoot}/plans`, { order_id: orderId, receipt_id: receipt, invoice_id: invoice, number, posting_date: date, period_id: period, expense_account_code: expense, reason }));
  }
  const selectedReceipt = detail.receipts.find(r => r.id === receipt);
  const eligible = selectedReceipt ? detail.invoices.filter(i => i.stage === "Accrued" && i.native_status === "Approved" && i.paid_minor === "0" && !i.supplier_return_owner_id && !i.installment_plans.length && i.lines?.length === 1 && i.lines[0].line_id === selectedReceipt?.order_line_id && i.total_minor === selectedReceipt.total_minor && scaledQuantity(i.lines[0].quantity_text) === scaledQuantity(selectedReceipt.quantity_text)) : [];
  const shown = [...(focus && !plans.some(p => p.id === focus.id) ? [focus] : []), ...plans], disabled = locked || busy || pending !== null;
  return <section aria-label={t.title}><h3>{t.title}</h3><p>{t.scope}</p>
    {error && <p role="alert">{t.error}</p>}{pending && !busy && <aside role="status"><p>{t.unknown}</p><code>{pending.body.command_id}</code><button disabled={locked} onClick={() => void send(pending)}>{t.retry}</button></aside>}
    {canPrepare && <form aria-label={t.prepare} onSubmit={prepare}><fieldset disabled={disabled}><legend>{t.prepare}</legend>
      <label>{t.number}<input required pattern="SR1-.+" maxLength={64} value={number} onChange={e => setNumber(e.target.value)} /></label>
      <label>{t.receipt}<select required value={receipt} onChange={e => { setReceipt(e.target.value); setInvoice(""); }}><option value="">—</option>{detail.receipts.filter(r => r.stage === "Posted" && !r.supplier_return_owner_id).map(r => <option key={r.id} value={r.id}>{r.number} · {r.quantity_text}</option>)}</select></label>
      <label>{t.invoice}<select required value={invoice} onChange={e => setInvoice(e.target.value)}><option value="">—</option>{eligible.map(i => <option key={i.id} value={i.id}>{i.number} · {i.outstanding_minor}</option>)}</select></label>
      <label>{t.date}<input required type="date" value={date} onChange={e => setDate(e.target.value)} /></label><label>{t.period}<select required value={period} onChange={e => setPeriod(e.target.value)}><option value="">—</option>{periods.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <label>{t.expense}<input required maxLength={64} value={expense} onChange={e => setExpense(e.target.value)} /></label><button disabled={!reason.trim() || !eligible.some(i => i.id === invoice)}>{t.prepare}</button>
    </fieldset></form>}
    <ul className="partial-document-list">{shown.map(plan => <li key={plan.id}><h4>{plan.number}</h4><p>{t.statuses[plan.phase]}</p><code>{plan.id}</code><dl><dt>{t.original}</dt><dd>{plan.credit_minor} {plan.currency_code}</dd><dt>{t.inventory}</dt><dd>{plan.inventory_removed_minor}</dd><dt>{t.charges}</dt><dd>{plan.charge_expense_minor}</dd></dl><p>{t.actors}: <bdi>{plan.preparer_actor_id} / {plan.reviewer_actor_id ?? "—"} / {plan.posted_actor_id ?? "—"}</bdi></p><p>{t.evidence}: {plan.posting_effect_ids.map(id => <code key={id}>{id}</code>)}</p>
      {Object.entries(plan.evidence).filter(([,v]) => v !== null).map(([k,v]) => <code key={k}>{v}</code>)}{plan.phase === 3 && <p><bdi>{plan.cancelled_actor_id} · {plan.cancellation_reason}</bdi></p>}
      {plan.phase < 2 && <><button disabled={disabled || !reason.trim() || !canPhase(plan)} onClick={() => void send(prepareScopedCommand(`${supplierReturnRoot}/plans/${encodeURIComponent(plan.id)}/${plan.phase === 0 ? "review" : "post"}`, { expected_plan_digest: plan.plan_digest, reason }))}>{plan.phase === 0 ? t.review : t.post}</button><button disabled={disabled || !reason.trim() || !canCancel(plan)} onClick={() => void send(prepareScopedCommand(`${supplierReturnRoot}/plans/${encodeURIComponent(plan.id)}/cancel`, { expected_plan_digest: plan.plan_digest, reason }))}>{t.cancel}</button></>}
    </li>)}</ul>{!shown.length && <p>{t.empty}</p>}
  </section>;
}
