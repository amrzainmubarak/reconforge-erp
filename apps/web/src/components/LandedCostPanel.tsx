import { useEffect, useRef, useState, type FormEvent } from "react";
import { AdminApiError } from "../data";
import { landedCommand, landedPage, landedRoot, type LandedPlan } from "../landed-cost-data";
import type { PartialDetail } from "../procurement-partial-data";
import type { ProcurementScope } from "../procurement-data";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { BrowserAdminSession, Locale } from "../types";

const words = {
  en: { cancel: "Cancel unreceived bundle", cancelled: "Cancelled; receiving reservations released", cancelEvidence: "Cancellation actor and evidence", title: "Paid landed cost receiving", scope: "Freight and duties are allocated by merchandise value. Receive all selected lines and post the cash payment together, after independent review. Original supplier invoice matching remains at merchandise price.", number: "Landed cost number", freight: "Paid freight in minor units", duty: "Paid duties in minor units", date: "Posting date", period: "Fiscal period", quantity: "Quantity to receive", prepare: "Prepare landed cost bundle", review: "Review bundle", post: "Receive bundle and post paid charges", retry: "Retry the same command", unknown: "The response is unconfirmed. Retry with the retained command identifier.", error: "The bundle could not be confirmed. Reload current evidence or retry the same command.", prepared: "Prepared", reviewed: "Reviewed", posted: "Posted", original: "Merchandise", capitalized: "Capitalized FIFO cost", first: "First bundles", next: "Next bundles", empty: "No paid landed cost bundle in this page.", reason: "Use the purchase evidence reason above.", receipt: "Receipt", actor: "Preparer / reviewer / poster", evidence: "Cash posting evidence" },
  ar: { cancel: "إلغاء الحزمة قبل الاستلام", cancelled: "ملغاة؛ تحررت حجوزات الاستلام", cancelEvidence: "فاعل الإلغاء ودليله", title: "استلام بتكاليف وصول مدفوعة", scope: "توزع تكلفة الشحن والرسوم حسب قيمة البضاعة. تستلم جميع البنود المختارة ويثبت دفع النقدية في معاملة واحدة بعد مراجعة مستقلة. تبقى مطابقة فاتورة المورد بسعر البضاعة الأصلي.", number: "رقم تكاليف الوصول", freight: "الشحن المدفوع بوحدات العملة الصغرى", duty: "الرسوم المدفوعة بوحدات العملة الصغرى", date: "تاريخ القيد", period: "الفترة المالية", quantity: "كمية الاستلام", prepare: "إعداد حزمة تكاليف الوصول", review: "مراجعة الحزمة", post: "استلام الحزمة وإثبات التكاليف المدفوعة", retry: "إعادة إرسال الأمر نفسه", unknown: "لم يتأكد الرد. أعد الإرسال باستخدام معرف الأمر المحفوظ.", error: "تعذر تأكيد الحزمة. حدّث الأدلة الحالية أو أعد إرسال الأمر نفسه.", prepared: "معدة", reviewed: "مراجعة", posted: "مثبتة", original: "البضاعة", capitalized: "تكلفة المخزون المرسملة", first: "أول الحزم", next: "الحزم التالية", empty: "لا توجد حزمة تكاليف وصول مدفوعة في هذه الصفحة.", reason: "استخدم سبب العملية في أدلة أمر الشراء أعلاه.", receipt: "الاستلام", actor: "المعد / المراجع / المثبت", evidence: "دليل قيد النقدية" },
};

const validationWords = {
  en: { members: "Enter a receiving quantity for at least one purchase line.", charges: "Enter positive paid freight or duties with a combined amount no greater than 9000000000000000000 minor units." },
  ar: { members: "أدخل كمية استلام لبند شراء واحد على الأقل.", charges: "أدخل شحنًا أو رسومًا مدفوعة موجبة بمجموع لا يتجاوز 9000000000000000000 وحدة عملة صغرى." },
};

interface Props { locale: Locale; session: BrowserAdminSession; scope: ProcurementScope; detail: PartialDetail; actorId: string | null; permissions: string[]; elevated: boolean; locked: boolean; reason: string; periods: { id: string; name: string }[]; onChanged: () => Promise<void>; onBusy: (value: boolean) => void; onError: (error: unknown) => void }

function mergeAcknowledgement(current: LandedPlan, acknowledgement: LandedPlan): LandedPlan {
  if (current.status === "Cancelled" || current.status === "Posted" ||
      (acknowledgement.status !== "Cancelled" && current.phase > acknowledgement.phase)) return current;
  return acknowledgement;
}

export function LandedCostPanel({ locale, session, scope, detail, actorId, permissions, elevated, locked, reason, periods, onChanged, onBusy, onError }: Props) {
  const t = words[locale], orderId = detail.order.id;
  const [number, setNumber] = useState(""), [freight, setFreight] = useState("0"), [duty, setDuty] = useState("0");
  const [date, setDate] = useState(detail.order.request.posting_date), [period, setPeriod] = useState(detail.order.request.period_id);
  const [quantities, setQuantities] = useState<Record<string, string>>({}), [plans, setPlans] = useState<LandedPlan[]>([]), [focus, setFocus] = useState<LandedPlan | null>(null);
  const [after, setAfter] = useState(""), [next, setNext] = useState<string | null>(null), [reload, setReload] = useState(0);
  const [pending, setPending] = useState<PreparedScopedCommand | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(false);
  const [validation, setValidation] = useState<"members" | "charges" | null>(null);
  const mounted = useRef(true), running = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    landedPage(session, scope, orderId, after, controller.signal).then((page) => {
      if (!controller.signal.aborted && mounted.current) { setPlans(page.records); setNext(page.next_after); }
    }).catch((caught) => { if (!controller.signal.aborted && mounted.current) { setError(true); onError(caught); } });
    return () => controller.abort();
  }, [session, scope, orderId, detail.order.row_version, after, reload]);
  const allowed = (required: string[]) => elevated && actorId !== null && required.every((permission) => permissions.includes(permission));
  const prepareAllowed = allowed(["payables.manage", "payables.settle", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"]);
  const cancelAllowed = (plan: LandedPlan) => allowed(["payables.approve", "payables.settle", "inventory.post", "inventory.valuation.approve", "finance_core.validate"]) && actorId !== plan.preparer_actor_id && actorId !== plan.reviewer_actor_id;
  const phaseAllowed = (plan: LandedPlan) => plan.phase === 0 ? allowed(["payables.approve", "payables.settle", "inventory.post", "inventory.valuation.approve", "finance_core.validate"]) && actorId !== plan.preparer_actor_id :
    allowed(["payables.manage", "payables.settle", "inventory.post", "inventory.valuation.approve", "finance_core.post"]) && actorId !== plan.preparer_actor_id && actorId !== plan.reviewer_actor_id;
  async function send(command: PreparedScopedCommand) {
    if (running.current) return;
    running.current = true; setBusy(true); onBusy(true); setPending(command); setError(false); setValidation(null);
    try {
      const result = await landedCommand(session, scope, orderId, command);
      if (mounted.current) {
        setFocus((current) => current?.id === result.id ? mergeAcknowledgement(current, result) : result);
        setPlans((current) => current.map((plan) => plan.id === result.id ? mergeAcknowledgement(plan, result) : plan));
        setPending(null); setReload((value) => value + 1);
      }
      await onChanged();
    } catch (caught) {
      if (mounted.current) { setError(true); if (caught instanceof AdminApiError && caught.status < 500) setPending(null); onError(caught); }
    } finally {
      running.current = false; if (mounted.current) { setBusy(false); onBusy(false); }
    }
  }
  function prepare(event: FormEvent) {
    event.preventDefault();
    if (locked || pending || !prepareAllowed || !reason.trim() || !/^(0|[1-9][0-9]{0,18})$/.test(freight) || !/^(0|[1-9][0-9]{0,18})$/.test(duty)) return;
    const lines = (detail.lines ?? []).filter((line) => quantities[line.id]?.trim()).map((line) => ({ line_id: line.id, quantity: quantities[line.id].trim() }));
    if (!lines.length) { setError(false); setValidation("members"); return; }
    if (BigInt(freight) + BigInt(duty) < 1n || BigInt(freight) + BigInt(duty) > 9000000000000000000n) { setError(false); setValidation("charges"); return; }
    void send(prepareScopedCommand(landedRoot + "/plans", { number, order_id: orderId, expected_version: detail.order.row_version, lines,
      freight_minor: freight, duty_minor: duty, posting_date: date, period_id: period, reason }));
  }
  const shown = [...(focus && !plans.some((plan) => plan.id === focus.id) ? [focus] : []), ...plans];
  const disabled = locked || busy || pending !== null;
  return <section aria-label={t.title}>
    <h3>{t.title}</h3><p>{t.scope}</p>
    {error && <p role="alert">{t.error}</p>}
    {validation && <p role="alert">{validationWords[locale][validation]}</p>}
    {pending && !busy && <aside role="status"><p>{t.unknown}</p><code>{String(pending.body.command_id)}</code><button disabled={locked} onClick={() => void send(pending)}>{t.retry}</button></aside>}
    {prepareAllowed && <form aria-label={t.prepare} onSubmit={prepare}><fieldset disabled={disabled}><legend>{t.prepare}</legend>
      <label>{t.number}<input required maxLength={40} value={number} onChange={(event) => setNumber(event.target.value)} /></label>
      <label>{t.freight}<input required inputMode="numeric" pattern="(0|[1-9][0-9]{0,18})" value={freight} onChange={(event) => setFreight(event.target.value)} /></label>
      <label>{t.duty}<input required inputMode="numeric" pattern="(0|[1-9][0-9]{0,18})" value={duty} onChange={(event) => setDuty(event.target.value)} /></label>
      <label>{t.date}<input required type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      <label>{t.period}<select required value={period} onChange={(event) => setPeriod(event.target.value)}><option value="">—</option>{periods.map((value) => <option key={value.id} value={value.id}>{value.name}</option>)}</select></label>
      {detail.lines?.map((line) => <label key={line.id}>{t.quantity} · <bdi>{line.item_code} · {line.location_code} · {line.uom_code}</bdi><input maxLength={64} inputMode="decimal" value={quantities[line.id] ?? ""} onChange={(event) => setQuantities({ ...quantities, [line.id]: event.target.value })} /></label>)}
      <p>{t.reason}</p><button disabled={!reason.trim()}>{t.prepare}</button>
    </fieldset></form>}
    <ul className="partial-document-list">{shown.map((plan) => <li key={plan.id}><h4><bdi>{plan.number}</bdi></h4><p>{plan.status === "Cancelled" ? t.cancelled : [t.prepared, t.reviewed, t.posted][plan.phase]} · <bdi>{plan.amount_minor} {plan.currency_code}</bdi></p><code>{plan.id}</code><p>{t.actor}: <bdi>{plan.preparer_actor_id} / {plan.reviewer_actor_id ?? "—"} / {plan.posted_actor_id ?? "—"}</bdi></p>
      <ul>{plan.allocations.map((allocation) => <li key={allocation.receipt_id}><bdi>{detail.lines?.find((line) => line.id === allocation.order_line_id)?.item_code ?? allocation.order_line_id}</bdi> · {allocation.quantity_text} · {t.original}: <bdi>{allocation.base_minor}</bdi> · {t.capitalized}: <bdi>{(BigInt(allocation.base_minor) + BigInt(allocation.freight_minor) + BigInt(allocation.duty_minor)).toString()}</bdi><p>{t.receipt}: <code>{allocation.receipt_plan_id}</code></p></li>)}</ul>
      {plan.posting_effect_id && <p>{t.evidence}: <code>{plan.posting_effect_id}</code></p>}
      {plan.phase < 2 && plan.status !== "Cancelled" && <button disabled={disabled || !reason.trim() || !phaseAllowed(plan)} onClick={() => void send(prepareScopedCommand(`${landedRoot}/plans/${encodeURIComponent(plan.id)}/${plan.phase === 0 ? "review" : "post"}`, { expected_plan_digest: plan.plan_digest, reason }))}>{plan.phase === 0 ? t.review : t.post}</button>}
      {plan.cancellation && <p>{t.cancelEvidence}: <bdi>{plan.cancellation.actor_id} · {plan.cancellation.reason}</bdi><code>{plan.cancellation.audit_event_id}</code></p>}
      {plan.phase < 2 && plan.status !== "Cancelled" && <button disabled={disabled || !reason.trim() || !cancelAllowed(plan)} onClick={() => void send(prepareScopedCommand(`${landedRoot}/plans/${encodeURIComponent(plan.id)}/cancel`, { expected_plan_digest: plan.plan_digest, reason }))}>{t.cancel}</button>}
    </li>)}</ul>
    {shown.length === 0 && <p>{t.empty}</p>}<div className="partial-toolbar"><button disabled={disabled || !after} onClick={() => setAfter("")}>{t.first}</button><button disabled={disabled || !next} onClick={() => next && setAfter(next)}>{t.next}</button></div>
  </section>;
}
