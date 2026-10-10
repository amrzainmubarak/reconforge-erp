import { useEffect, useRef, useState } from "react";
import { AdminApiError } from "../data";
import { loadBudgetDetail } from "../budget-control-data";
import { commitmentRoot, newestCommitment, procurementCommitmentCommand, procurementCommitmentGet, sameProcurementQuantity, type ProcurementCommitment } from "../procurement-commitment-data";
import type { ProcurementScope } from "../procurement-data";
import { distinctPartialPoster, type PartialDetail } from "../procurement-partial-data";
import { prepareScopedCommand, type PreparedScopedCommand } from "../scoped-command";
import type { BrowserAdminSession, Locale } from "../types";

export function ProcurementCommitmentPanel({ session, scope, detail, locale, actorId, permissions, elevated, locked, reason, initial, onState, onBusy, onError, onChanged }: {
  session: BrowserAdminSession; scope: ProcurementScope; detail: PartialDetail; locale: Locale; actorId: string | null; permissions: string[];
  elevated: boolean; locked: boolean; reason: string; initial: ProcurementCommitment | null;
  onState(value: ProcurementCommitment): void; onBusy(value: boolean): void; onError(error: unknown): void; onChanged(): Promise<void>;
}) {
  const ar = locale === "ar", say = (en: string, arabic: string) => ar ? arabic : en;
  const [owner, setOwner] = useState<ProcurementCommitment | null>(initial), [budgetVersion, setBudgetVersion] = useState<number | null>(null);
  const [date, setDate] = useState(detail.order.request.posting_date), [pending, setPending] = useState<PreparedScopedCommand | null>(null);
  const [busy, setBusy] = useState(false), [failed, setFailed] = useState(false), [reload, setReload] = useState(0);
  const alive = useRef(true), sending = useRef(false), latest = useRef(owner);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function accept(value: ProcurementCommitment) {
    const next = newestCommitment(latest.current, value); latest.current = next; setOwner(next); onState(next);
  }
  useEffect(() => {
    const controller = new AbortController();
    procurementCommitmentGet(session, scope, detail.order.id, controller.signal).then(async (value) => {
      if (controller.signal.aborted || !alive.current) return;
      accept(value);
      const budget = await loadBudgetDetail(session, scope, value.budget_id, controller.signal);
      if (!controller.signal.aborted && alive.current) setBudgetVersion(budget.row_version);
    }).catch((error) => { if (!controller.signal.aborted && alive.current) { setFailed(true); onError(error); } });
    return () => controller.abort();
  }, [session, scope, detail.order.id, detail.order.row_version, reload]);
  async function send(command: PreparedScopedCommand) {
    if (sending.current) return; sending.current = true; setBusy(true); onBusy(true); setPending(command); setFailed(false);
    try {
      const value = await procurementCommitmentCommand(session, scope, command);
      if (!alive.current) return;
      accept(value); setBudgetVersion((current) => Math.max(current ?? 0, value.budget_version)); setPending(null);
      setReload((value) => value + 1);
      await onChanged();
    } catch (error) {
      if (!alive.current) return;
      setFailed(true);
      if (error instanceof AdminApiError && error.status < 500) { setPending(null); onError(error); }
    } finally { sending.current = false; if (alive.current) { setBusy(false); onBusy(false); } }
  }
  const permit = (permission: string) => elevated && permissions.includes(permission);
  const blocked = locked || busy || pending !== null || budgetVersion === null;
  const releasable = owner?.status === "Reserved" && actorId !== owner.preparer_actor_id &&
    detail.receipts.every((receipt) => receipt.stage === "Posted") && detail.invoices.every((invoice) => invoice.stage === "Accrued") &&
    (detail.lines ?? []).every((line) => sameProcurementQuantity(line.received_quantity, line.invoiced_quantity));
  return <section aria-label={say("Purchase appropriation", "اعتماد أمر الشراء")}>
    <h3>{say("Purchase appropriation", "اعتماد أمر الشراء")}</h3>
    <p>{say("Native budget reservation and AP accrual consumption share one transaction. Paid freight and duties require a separate appropriation extension.", "حجز الاعتماد واستهلاكه مع قيد المورد يحدثان في معاملة واحدة. تتطلب الشحنات والرسوم المدفوعة توسعة اعتماد مستقلة.")}</p>
    {failed && <p role="alert">{say("The latest read or command was not confirmed. Retained evidence remains visible; refresh or retry the exact pending command.", "لم يتأكد آخر طلب أو تحديث. تبقى الأدلة المحفوظة ظاهرة؛ حدّث القراءة أو أعد الأمر المعلق نفسه.")}</p>}
    {pending && !busy && <aside role="status"><code>{String(pending.body.command_id)}</code><button onClick={() => void send(pending)}>{say("Retry exact appropriation command", "إعادة أمر الاعتماد نفسه")}</button></aside>}
    <button disabled={locked || busy || pending !== null} onClick={() => { setFailed(false); setReload((value) => value + 1); }}>{say("Refresh appropriation", "تحديث الاعتماد")}</button>
    {owner && <><p role="status">{say(owner.status, { Reserved: "محجوز", Consumed: "مستهلك", Released: "محرر" }[owner.status])}</p>
      <dl>{([ ["original_minor", "Original obligation", "الالتزام الأصلي"], ["remaining_minor", "Reserved remainder", "الرصيد المحجوز"], ["consumed_minor", "Accrued consumption", "الاستهلاك المرحل"], ["released_minor", "Released unreceived value", "قيمة الجزء غير المستلم المحررة"] ] as const).map(([key, en, arabic]) => <div key={key}><dt>{say(en, arabic)}</dt><dd><bdi>{owner[key]} {owner.currency_code}</bdi></dd></div>)}</dl>
      <p>{say("Budget version", "إصدار الاعتماد")}: {budgetVersion ?? "—"}</p><code>{owner.budget_id}</code><code>{owner.commitment_id}</code><code>{owner.evidence.budget_event_id}</code><code>{owner.evidence.audit_event_id}</code><code>{owner.evidence.outbox_event_id}</code>
      {owner.status === "Reserved" && detail.invoices.filter((invoice) => invoice.stage === "AccrualReviewed").map((invoice) => <button key={invoice.id}
        disabled={blocked || !reason.trim() || !permit("budget_control.manage") || !permit("payables.manage") || !permit("finance_core.post") || !distinctPartialPoster(invoice.accrual_preparer_actor_id, invoice.accrual_reviewer_actor_id, actorId)}
        onClick={() => void send(prepareScopedCommand(`${commitmentRoot}/orders/${encodeURIComponent(owner.order_id)}/consume`, {
          invoice_id: invoice.id, expected_order_version: detail.order.row_version, expected_budget_version: budgetVersion!, reason,
        }))}>{say("Post AP and consume appropriation", "ترحيل المورد واستهلاك الاعتماد")} {invoice.number}</button>)}
      {owner.status === "Reserved" && <fieldset disabled={blocked}><legend>{say("Release unreceived obligation", "تحرير الالتزام غير المستلم")}</legend>
        <label>{say("Release posting date", "تاريخ التحرير")}<input required type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <button disabled={!releasable || !reason.trim() || !date || !permit("budget_control.manage") || !permit("payables.approve")}
          onClick={() => void send(prepareScopedCommand(`${commitmentRoot}/orders/${encodeURIComponent(owner.order_id)}/release`, {
            expected_order_version: detail.order.row_version, expected_budget_version: budgetVersion!, posting_date: date, reason,
          }))}>{say("Release remaining obligation", "تحرير الالتزام المتبقي")}</button>
      </fieldset>}
    </>}
  </section>;
}
